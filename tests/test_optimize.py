"""Continuous optimisation: zero-value detection, budget governor, research
proposals and the Self-Improvement Governor (bounded, journaled, revertible)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from repo_ai import optimize
from repo_ai.config import Config, load_config


def _episode(i: int, ranks: list[int], injected_n: int = 8, t0: int = 1000) -> dict:
    """One session; each prompt edits the file ranked `rank` in its candidates."""
    prompts, edits = [], []
    for j, rank in enumerate(ranks):
        t = t0 + i * 1000 + j * 100
        cands = [[f"src/f{i}_{j}_{k}.py", 1.0 - k / 20] for k in range(16)]
        prompts.append({"t": t, "intents": ["bugfix"], "cands": cands,
                        "injected": [c[0] for c in cands[:injected_n]], "confidence": "high"})
        edits.append([t + 10, cands[rank - 1][0]])
    return {"session": f"s{i}", "prompts": prompts, "edits": edits, "status": "verified"}


@pytest.fixture(autouse=True)
def _isolated_homes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REPO_AI_LAB_HOME", str(tmp_path / "lab"))
    monkeypatch.setenv("REPO_AI_HOME", str(tmp_path / "rh"))


def _layout(tmp_path: Path):
    return SimpleNamespace(state_dir=tmp_path / "state", learning_dir=tmp_path / "learning", root=tmp_path)


def test_edits_are_attributed_to_the_prompt_before_them():
    ep = _episode(0, [1, 3])
    stats = optimize.injection_stats([ep])
    assert stats["prompts_with_edits"] == 2
    assert stats["first_ranks"] == [1, 3]
    assert stats["hit_rate"] == 1.0


def test_governor_needs_evidence():
    stats, prop = optimize.budget_governor([_episode(0, [1, 2])], Config())
    assert prop is None and stats["status"].startswith("insufficient evidence")


def test_governor_shrinks_the_shortlist_in_one_bounded_step():
    eps = [_episode(i, [1, 2]) for i in range(8)]  # 16 prompts, edited file always in top 2
    stats, prop = optimize.budget_governor(eps, Config())
    assert stats["coverage_rank"] == 2
    assert prop is not None and prop.change == {"key": "hook_max_files", "from": 8, "to": 4}
    assert "step-limited" in prop.title


def test_governor_widens_when_edited_files_rank_below_the_cut():
    cfg = Config()
    cfg.hook_max_files = 3
    eps = [_episode(i, [6, 7], injected_n=3) for i in range(8)]
    _, prop = optimize.budget_governor(eps, cfg)
    assert prop is not None and prop.change["to"] == 6  # doubling is the step limit


def test_governor_rules(tmp_path: Path):
    layout = _layout(tmp_path)
    eps = [_episode(i, [1, 2]) for i in range(8)]
    cfg = Config()
    _, prop = optimize.budget_governor(eps, cfg)
    assert optimize.govern(prop, cfg, layout, []).governor["auto_apply"]
    # explicit settings win over tuning
    cfg.extra["_explicit_keys"] = ["hook_max_files"]
    assert not optimize.govern(prop, cfg, layout, []).governor["auto_apply"]
    # rate limit
    cfg.extra["_explicit_keys"] = []
    recent = [{"kind": "tune", "ts": time.time() - 3600}]
    decision = optimize.govern(prop, cfg, layout, recent).governor
    assert not decision["auto_apply"] and "rate limit" in decision["reasons"][0]
    # anything that is not a bounded tune needs a human
    other = optimize.Proposal("x", "disable", "t", "h", [], "", "", "")
    assert not optimize.govern(other, cfg, layout, []).governor["auto_apply"]
    huge = optimize.Proposal("y", "tune", "t", "h", [], "", "", "",
                             {"key": "hook_max_files", "from": 8, "to": 1})
    assert not optimize.govern(huge, cfg, layout, []).governor["auto_apply"]
    perms = optimize.Proposal("z", "tune", "t", "h", [], "", "", "",
                              {"key": "permissions", "from": 0, "to": 1})
    assert "not tunable" in optimize.govern(perms, cfg, layout, []).governor["reasons"][0]


def test_apply_journal_and_revert(tmp_path: Path):
    layout = _layout(tmp_path)
    eps = [_episode(i, [1, 2]) for i in range(8)]
    cfg = Config()
    plan = optimize.proposals(tmp_path, cfg, layout, eps)
    plan["proposals"] = [p.to_json() for p in plan["proposals"]]
    applied = optimize.apply(layout, cfg, plan)
    assert [a["key"] for a in applied] == ["hook_max_files"]
    assert optimize.load_tuning(layout) == {"hook_max_files": 4}
    assert optimize.apply_tuning(Config(), layout).hook_max_files == 4
    # a second apply in the same week is refused by the rate limit
    plan2 = optimize.proposals(tmp_path, cfg, layout, eps)
    assert not any(p.governor["auto_apply"] for p in plan2["proposals"])
    reverted = optimize.revert(layout)
    assert reverted[0]["id"] == applied[0]["id"]
    assert optimize.load_tuning(layout) == {}
    assert optimize.apply_tuning(Config(), layout).hook_max_files == 8


def test_named_apply_refuses_what_the_governor_denies(tmp_path: Path):
    layout = _layout(tmp_path)
    plan = optimize.proposals(tmp_path, Config(), layout, [])
    plan["proposals"] = [p.to_json() for p in plan["proposals"]]
    with pytest.raises(ValueError, match="not allowed by the governor"):
        optimize.apply(layout, Config(), plan, ["experiment-pilot"])


def test_tampered_tuning_is_ignored(tmp_path: Path):
    layout = _layout(tmp_path)
    optimize.tuning_path(layout).parent.mkdir(parents=True, exist_ok=True)
    optimize.tuning_path(layout).write_text(json.dumps(
        {"hook_max_files": 500, "claude_cmd": "evil", "hook_budget_tokens": 800}))
    assert optimize.load_tuning(layout) == {"hook_budget_tokens": 800}


def test_explicit_repository_config_beats_tuning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / ".repo-ai").mkdir()
    (tmp_path / ".repo-ai" / "config.toml").write_text("hook_max_files = 6\n")
    cfg = load_config(tmp_path)
    assert "hook_max_files" in cfg.extra["_explicit_keys"]
    layout = _layout(tmp_path)
    optimize.tuning_path(layout).parent.mkdir(parents=True, exist_ok=True)
    optimize.tuning_path(layout).write_text(json.dumps({"hook_max_files": 3}))
    assert optimize.apply_tuning(cfg, layout).hook_max_files == 6


def test_revert_is_proposed_when_a_change_hurt(tmp_path: Path):
    layout = _layout(tmp_path)
    optimize.journal_path(layout).parent.mkdir(parents=True, exist_ok=True)
    change_ts = 100_000
    before = [_episode(i, [1, 2], t0=0) for i in range(8)]  # hit rate 1.0
    after = [_episode(i, [6, 7], injected_n=4, t0=change_ts) for i in range(8)]  # hit rate 0
    optimize.journal_path(layout).write_text(json.dumps([
        {"id": "opt-1", "ts": change_ts, "kind": "tune", "key": "hook_max_files", "from": 8, "to": 4,
         "active": True}]))
    cfg = Config()
    cfg.hook_max_files = 4
    plan = optimize.proposals(tmp_path, cfg, layout, before + after)
    revert = [p for p in plan["proposals"] if p.kind == "revert"]
    assert revert and revert[0].change["to"] == 8
    assert revert[0].governor["auto_apply"]  # undoing a journaled change is always allowed


def _skill(root: Path, name: str, desc: str, manual: bool = False) -> None:
    d = root / ".claude" / "skills" / name
    d.mkdir(parents=True)
    extra = "disable-model-invocation: true\n" if manual else ""
    d.joinpath("SKILL.md").write_text(f'---\nname: {name}\ndescription: "{desc}"\n{extra}---\n\nbody\n')


def test_zero_value_detector(tmp_path: Path):
    _skill(tmp_path, "my-notes", "Write release notes when asked for a changelog entry.")
    _skill(tmp_path, "repo-optimize", "Propose improvements.", manual=True)
    _skill(tmp_path, "used-one", "Do the used thing when asked.")
    eps = [_episode(i, [1]) for i in range(10)]
    eps[0]["skills"] = [[1, "used-one", 0]]
    zv = optimize.zero_value(tmp_path, eps)
    by = {s["name"]: s for s in zv["skills"]}
    assert by["my-notes"]["status"] == "zero-value" and by["my-notes"]["origin"] == "user"
    assert by["repo-optimize"]["status"].startswith("no standing cost")
    assert by["used-one"]["status"] == "used"
    assert "subagent" in zv["not_observable"][0]
    few = optimize.zero_value(tmp_path, eps[:3])
    assert all(s["status"] == "insufficient evidence" for s in few["skills"])
    plan = optimize.proposals(tmp_path, Config(), _layout(tmp_path), eps)
    prop = next(p for p in plan["proposals"] if p.id == "zero-value-my-notes")
    assert "your own skill" in prop.experiment  # user-authored skills are never touched
    assert not prop.governor["auto_apply"]


def test_management_skills_are_manual_only_and_spec_valid():
    import re

    from repo_ai.adapters.claude_content import NATIVE_MANAGEMENT_SKILLS, management_skills
    docs = management_skills()
    assert tuple(d.name for d in docs) == NATIVE_MANAGEMENT_SKILLS
    for d in docs:
        text = d.render()
        assert d.manual_only and "disable-model-invocation: true" in text
        assert "allowed-tools" not in text
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", d.name) and len(d.name) <= 64
        assert 0 < len(d.description) <= 1024


def test_cli_capabilities_performance_optimize(pyweb: Path, tmp_path: Path):
    from functools import partial

    from conftest import run_cli as _run
    run_cli = partial(_run, env={"REPO_AI_LAB_HOME": str(tmp_path / "lab"),
                                 "REPO_AI_HOME": str(tmp_path / "rh")})
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    for name in ("repo-capabilities", "repo-optimize", "repo-skill-evaluate"):
        assert (pyweb / ".claude" / "skills" / name / "SKILL.md").is_file()
    caps = json.loads(run_cli(pyweb, "capabilities", "--json").stdout)
    assert {s["origin"] for s in caps["skills"]} == {"native"}
    assert "Python" in caps["stack"]["languages"] and "FastAPI" in caps["stack"]["frameworks"]
    gap = next(r for r in caps["capabilities"] if r["gap"] == "test-coverage")
    assert gap["status"] == "gap"  # skills that merely mention tests do not cover test authoring
    perf = json.loads(run_cli(pyweb, "performance", "--json").stdout)
    assert perf["task_success"].startswith("UNVERIFIED")
    plan = json.loads(run_cli(pyweb, "optimize", "--json").stdout)
    assert any(p["id"] == "experiment-pilot" for p in plan["proposals"])
    out = run_cli(pyweb, "optimize", "--apply")
    assert out.returncode == 0 and "nothing the governor may apply" in out.stdout
    assert run_cli(pyweb, "friction").returncode == 0
    assert run_cli(pyweb, "uninstall", "--agent", "claude", "--yes").returncode == 0
    assert not (pyweb / ".claude" / "skills" / "repo-optimize").exists()


def test_skill_evolution_proposes_revising_a_skill_with_worse_outcomes(tmp_path: Path):
    layout = SimpleNamespace(state_dir=tmp_path / "state", learning_dir=tmp_path / "learning",
                             root=tmp_path)
    layout.learning_dir.mkdir()
    (layout.learning_dir / "skills.json").write_text(json.dumps(
        {"version": 1, "skills": {"repo-fix-money": {"status": "active", "version": 2,
                                                     "history": [{"version": 1}]}}}))
    eps = []
    for i in range(8):
        ep = _episode(i, [1])
        ep["skills"] = [[1, "repo-fix-money", 1 + i % 2]]
        ep["status"] = "failed"
        eps.append(ep)
    for i in range(8, 16):
        eps.append(_episode(i, [1]))  # verified, without the skill
    props = {p.id: p for p in optimize.skill_evolution(layout, eps)}
    assert "evolve-repo-fix-money" in props
    assert "Fisher" in props["evolve-repo-fix-money"].evidence[0]
    assert "canary-repo-fix-money" not in props  # 4 uses per version: not enough to settle
    assert not optimize.govern(props["evolve-repo-fix-money"], Config(), layout, []).governor["auto_apply"]
