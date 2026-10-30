"""Orchestration advice, the change passport, budget governor, and CLI ergonomics."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import commit_all, run_cli

FAKE_GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" + "kLmNoPqRsTuVwXyZ12"


def _init(repo: Path, *extra: str) -> None:
    proc = run_cli(repo, "init", "--agent", "claude", *extra, "-q")
    assert proc.returncode == 0, proc.stderr


def test_simple_task_needs_no_subagent(pyweb: Path):
    _init(pyweb)
    plan = json.loads(run_cli(pyweb, "orchestrate", "plan", "fix the typo in the health check "
                              "endpoint response message", "--json").stdout)
    agents = [n["agent"] for n in plan["nodes"]]
    assert set(agents) == {"main"} or plan["complexity"] in {"trivial", "moderate"}
    assert all(n["mode"] == "read-only" for n in plan["nodes"] if n["agent"] != "main")
    writers = [n for n in plan["nodes"] if n["mode"] == "write"]
    assert [w["agent"] for w in writers] == ["main"]


def test_core_plans_keep_every_step_in_the_main_session(pyweb: Path):
    _init(pyweb)  # a new install: feature_set = "core", no subagents installed
    task = "change the auth token signing and password check in login"
    plan = json.loads(run_cli(pyweb, "orchestrate", "plan", task, "--json").stdout)
    assert {n["agent"] for n in plan["nodes"]} == {"main"}
    assert "security" in {n["id"] for n in plan["nodes"]}  # the review step is still planned
    assert any("subagents are off" in note for note in plan["notes"])


def test_risky_task_gets_security_review_and_skeptic_only_when_enabled(pyweb: Path):
    _init(pyweb, "--feature-set", "full")
    cfg = pyweb / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nskeptic_reviewer = false\n")
    assert run_cli(pyweb, "update", "-q").returncode == 0
    task = "change the auth token signing and password check in login"
    plan = json.loads(run_cli(pyweb, "orchestrate", "plan", task, "--json").stdout)
    agents = {n["agent"] for n in plan["nodes"]}
    assert "repo-security-reviewer" in agents and "repo-skeptic" not in agents
    assert len([a for a in agents if a != "main"]) <= 3
    skeptic = pyweb / ".claude" / "agents" / "repo-skeptic.md"
    assert not skeptic.exists()
    cfg = pyweb / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text().replace("skeptic_reviewer = false", "skeptic_reviewer = true"))
    assert run_cli(pyweb, "update", "-q").returncode == 0
    assert skeptic.exists() and "tools: Read, Grep, Glob" in skeptic.read_text()
    plan = json.loads(run_cli(pyweb, "orchestrate", "plan", task, "--json").stdout)
    assert "repo-skeptic" in {n["agent"] for n in plan["nodes"]}
    cfg.write_text(cfg.read_text().replace("skeptic_reviewer = true", "skeptic_reviewer = false"))
    assert run_cli(pyweb, "update", "-q").returncode == 0
    assert not skeptic.exists()


def test_change_passport(pyweb: Path):
    _init(pyweb)
    commit_all(pyweb, "repo-ai")
    (pyweb / "app" / "api" / "users.py").write_text(
        (pyweb / "app" / "api" / "users.py").read_text() + f'\nTOKEN = "{FAKE_GH}"\n')
    login = pyweb / "app" / "auth" / "login.py"
    login.write_text(login.read_text() + "\n# validation tweak\n")
    (pyweb / "migrations").mkdir()
    (pyweb / "migrations" / "0002_add_email.py").write_text("def upgrade():\n    pass\n")
    proc = run_cli(pyweb, "review", "--changed", "--format", "json")
    data = json.loads(proc.stdout)
    paths = {f["path"] for f in data["files"]}
    assert {"app/api/users.py", "migrations/0002_add_email.py"} <= paths
    assert "CLAUDE.md" not in paths  # repo-ai's own managed block is not the user's change
    risks = " ".join(data["risks"])
    assert "API:" in risks and "migration:" in risks
    assert any("app/api/users.py:" in s for s in data["security"]), data
    assert FAKE_GH not in proc.stdout  # never the value
    assert "tests/test_login.py" in data["tests_recommended"]
    md = run_cli(pyweb, "review", "--changed").stdout
    assert "not an approval" in md and "Blind spots" in md


def test_budget_governor(pyweb: Path):
    _init(pyweb, "--smart")
    data = json.loads(run_cli(pyweb, "budget", "--json").stdout)
    assert data["always_loaded_repo_ai_tokens_est"] > 0
    assert "estimates" in data["note"]
    manual = [i for i in data["items"] if i["name"] in {"/repo-learn", "/repo-pr"}]
    assert manual and all(not i["always_loaded"] for i in manual)
    cfg = pyweb / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nalways_loaded_budget_tokens = 50\n")
    proc = run_cli(pyweb, "budget", "--check")
    assert proc.returncode == 1 and "OVER BUDGET" in proc.stdout


def test_generated_skill_cap(pyweb: Path):
    cfg_dir = pyweb / ".repo-ai"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text("max_generated_skills = 1\n")
    _init(pyweb, "--smart")
    generated = [p for p in (pyweb / ".claude" / "skills").glob("*/SKILL.md")
                 if "origin=generated" in p.read_text()]
    assert len(generated) == 1


def test_status_reports_active_capabilities(pyweb: Path):
    _init(pyweb, "--smart")
    data = json.loads(run_cli(pyweb, "status", "--json").stdout)
    caps = data["capabilities"]
    assert caps["signals"] == "outcomes" and caps["llm_drafting"] == "off"
    assert caps["zone"] == "none" and caps["outcome_prior"] == "off"


def test_completion_and_quickstart(tmp_path: Path, pyweb: Path):
    bash = run_cli(None, "completion", "bash").stdout
    assert "complete -F _repo_ai repo-ai" in bash and "packet" in bash and "--dry-run" in bash
    fish = run_cli(None, "completion", "fish").stdout
    assert "__fish_use_subcommand" in fish
    zsh = run_cli(None, "completion", "zsh").stdout
    assert "bashcompinit" in zsh
    plain = tmp_path / "plain"
    plain.mkdir()
    out = run_cli(plain, "quickstart").stdout
    assert "initialized here: no" in out and "init --agent claude --dry-run --diff" in out
    _init(pyweb)
    assert "initialized here: yes" in run_cli(pyweb, "quickstart").stdout
