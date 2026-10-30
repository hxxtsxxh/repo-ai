"""Coding Performance Research Lab: arms, isolation, grading, statistics.

Everything here uses a deterministic fake Claude (tests/fake_claude_lab.py).
No model is called and nothing is billed. Grading runs in the real sandbox
when one is available on the host.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import run_cli
from test_evals import _suite

from repo_ai import coding_lab as lab
from repo_ai import evals, sandbox

FAKE = Path(__file__).parent / "fake_claude_lab.py"


def _sandbox_available() -> bool:
    try:
        sandbox.get_backend("auto", toolchain="python")
        return True
    except sandbox.SandboxUnavailable:
        return False


needs_sandbox = pytest.mark.skipif(not _sandbox_available(), reason="no sandbox backend for grading")


@pytest.fixture(autouse=True)
def _isolated_lab_home(tmp_path, monkeypatch):
    """Canary decoys are planted under lab_home(); never share the user's real one
    (concurrent shards or sessions would race on the canaries/ assertion)."""
    monkeypatch.setenv(lab.RESULTS_ENV, str(tmp_path / "lab-home"))


def _opts(tmp_path: Path, solutions: Path, policy: str, arms: str = "baseline,core,full",
          **kw) -> lab.LabOptions:
    return lab.LabOptions(arms=lab.make_arms(arms.split(",")), fake=True,
                          claude_cmd=[sys.executable, str(FAKE), str(solutions), policy],
                          results_dir=tmp_path / "results", timeout_s=120, **kw)


def _solutions(tmp_path: Path, tasks) -> Path:
    path = tmp_path / "solutions.json"
    path.write_text(json.dumps({t.prompt: t.solution for t in tasks}))
    return path


def test_arm_features_and_ablation():
    arms = {a.name: a for a in lab.make_arms(["baseline", "core", "full"])}
    assert arms["baseline"].features == frozenset()
    assert {"hooks", "packet", "rules"} == set(arms["core"].features)
    assert "skills" in arms["full"].features and "outcomes" in arms["full"].features
    assert 'skills_mode = "curated"' in arms["core"].config_toml()
    assert 'learning_signals = "off"' in arms["core"].config_toml()
    assert "write_claude_agents = false" in arms["core"].config_toml()
    ablate = lab.make_arms(["full"], ablate="skills")
    assert [a.name for a in ablate] == ["full", "full-skills"]
    assert "skills" not in ablate[1].features
    with pytest.raises(SystemExit):
        lab.make_arms(["turbo"])


def test_arm_settings_lock_away_home_and_suite(tmp_path: Path):
    suite = tmp_path / "suite"
    suite.mkdir()
    settings = lab.arm_settings(tmp_path / "ws-root", suite, [tmp_path / "lab"])
    sb = settings["sandbox"]
    assert sb["enabled"] and sb["failIfUnavailable"] and not sb["allowUnsandboxedCommands"]
    deny = sb["filesystem"]["denyRead"]
    assert str(Path.home().resolve()) in deny and str(suite.resolve()) in deny
    assert sb["network"]["allowedDomains"] == []
    reads = settings["permissions"]["deny"]
    assert f"Read(/{suite.resolve()}/**)" in reads and "WebFetch" in reads
    assert settings["autoMemoryEnabled"] is False


def test_isolation_checks():
    base, core, full = lab.make_arms(["baseline", "core", "full"])
    assert lab.check_isolation(base, {"skills": ["simplify"], "agents": []}, 0) == []
    assert lab.check_isolation(base, {"skills": ["repo-locate"]}, 0)
    assert lab.check_isolation(base, {"skills": []}, 3)
    assert lab.check_isolation(core, {"skills": []}, 2)  # core without repo-ai skills
    assert lab.check_isolation(core, {"skills": ["repo-locate"], "agents": []}, 2) == []
    assert lab.check_isolation(full, {"skills": ["repo-locate"],
                                      "agents": [{"name": "repo-explorer"}]}, 2) == []
    assert lab.check_isolation(base, {}, 0)  # no init event: unverifiable


def test_eval_config_dir_audit(tmp_path: Path):
    cfg = tmp_path / "claude-eval"
    assert lab.audit_config_dir(cfg)  # missing
    cfg.mkdir()
    assert lab.audit_config_dir(cfg) == []
    (cfg / "skills" / "mine").mkdir(parents=True)
    (cfg / "skills" / "mine" / "SKILL.md").write_text("x")
    (cfg / "CLAUDE.md").write_text("personal memory")
    (cfg / "settings.json").write_text('{"hooks": {"Stop": []}, "enabledPlugins": {"x@y": true}}')
    text = " ".join(lab.audit_config_dir(cfg))
    assert "skills" in text and "CLAUDE.md" in text and "enabledPlugins" in text


@needs_sandbox
def test_three_arm_fake_experiment_end_to_end(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    opts = _opts(tmp_path, _solutions(tmp_path, task), "solve-with-repo-ai")
    meta = lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    meta2, runs = lab.load_runs(str(opts.results_dir))
    by_arm = {r["arm"]: r for r in runs}
    assert set(by_arm) == {"baseline", "core", "full"}
    for r in runs:
        assert r["valid"], r
        assert r["backend"] in sandbox.BACKENDS
    assert by_arm["baseline"]["success"] is False
    assert by_arm["core"]["success"] is True and by_arm["full"]["success"] is True
    assert by_arm["full"]["files_changed"] == ["calc/money.py"]
    assert by_arm["baseline"]["abandoned"] is True
    summary = lab.summarize(runs)
    assert summary["fake"] and summary["arms"]["full"]["success_rate"] == 1.0
    comp = next(c for c in summary["comparisons"] if c["a"] == "baseline" and c["b"] == "full")
    assert comp["pairs"] == 1 and comp["verdict"].startswith("inconclusive")
    report = lab.render_report(meta2, summary)
    assert "FAKE CLIENT" in report and "| Task success rate |" in report
    assert meta["spent_usd_charged"] == 0.0


@needs_sandbox
def test_regression_investigator_and_resume(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    opts = _opts(tmp_path, _solutions(tmp_path, task), "solve-without-repo-ai", arms="baseline,full")
    meta = lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    _, runs = lab.load_runs(str(opts.results_dir))
    regs = lab.regressions(runs, "baseline", "full")
    assert [r["task"] for r in regs] == ["mini-001-rounding"] and regs[0]["signals"]
    again = lab.run_experiment(suite, task, bases, opts, resume=meta["id"], log=lambda *_: None)
    _, runs2 = lab.load_runs(str(opts.results_dir))
    assert len(runs2) == len(runs)  # nothing re-run
    assert again["id"] == meta["id"]


def test_live_needs_budget_and_clean_config(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    opts = lab.LabOptions(arms=lab.make_arms(["baseline", "full"]), results_dir=tmp_path / "r")
    with pytest.raises(SystemExit, match="max-cost-usd"):
        lab.run_experiment(suite, tasks[:1], bases, opts)
    opts.max_cost_usd = 1.0
    opts.config_dir = tmp_path / "does-not-exist"
    with pytest.raises(SystemExit, match="not clean"):
        lab.run_experiment(suite, tasks[:1], bases, opts)


def test_cli_dry_run_spends_nothing(tmp_path: Path):
    suite = _suite(tmp_path)
    proc = run_cli(None, "eval", "coding", "--suite", str(suite), "--dry-run", "--max-cost-usd", "5",
                   "--results", str(tmp_path / "r"), "--claude-config", str(tmp_path / "cfg"))
    assert proc.returncode == 0, proc.stderr
    assert "nothing was executed" in proc.stdout and "NOT READY" in proc.stdout
    assert not (tmp_path / "r").exists()  # a dry run records no experiment
    proc = run_cli(None, "eval", "coding", "--suite", str(suite), "--results", str(tmp_path / "r2"))
    assert proc.returncode != 0 and "max-cost-usd" in proc.stderr


def test_pass_fraction_parsing():
    assert lab.pass_fraction("Ran 4 tests in 0.01s\n\nFAILED (failures=1)", False) == 0.75
    assert lab.pass_fraction("# pass 3\n# fail 1\n", False) == 0.75
    assert lab.pass_fraction("PASS a\nFAIL b\n", False) == 0.5
    assert lab.pass_fraction("", True) == 1.0 and lab.pass_fraction("boom", False) == 0.0


def test_statistics_verdicts():
    rows = []
    for i in range(12):
        rows.append({"task": f"t{i}", "rep": 0, "arm": "baseline", "valid": True, "success": i < 3,
                     "category": "bugfix"})
        rows.append({"task": f"t{i}", "rep": 0, "arm": "full", "valid": True, "success": True,
                     "category": "bugfix"})
    comp = lab.summarize(rows)["comparisons"][0]
    assert comp["pairs"] == 12 and comp["mcnemar_p"] < 0.05
    assert comp["verdict_class"] == "improvement" and "statistically supported" in comp["verdict"]
    assert comp["ci95"][0] > 0


def test_all_success_pilot_reports_uncertainty_not_equivalence():
    rows = []
    for i in range(6):
        for arm, tok in (("baseline", 170_000), ("core", 130_000), ("full", 135_000)):
            rows.append({"task": f"t{i}", "rep": 0, "arm": arm, "valid": True, "success": True,
                         "category": "bugfix", "input_tokens": tok + i, "output_tokens": 0,
                         "tool_calls": 8 if arm == "baseline" else 5, "reported_cost_usd": 0.08})
    summary = lab.summarize(rows)
    comp = next(c for c in summary["comparisons"] if c["a"] == "baseline" and c["b"] == "core")
    assert comp["verdict_class"] == "inconclusive" and not comp["equivalent"]
    assert comp["ci95"][0] < -0.3 and comp["ci95"][1] > 0.3 and "ceiling" in comp["verdict"]
    assert comp["metrics"]["tokens"]["lower_in_b"] == 6
    report = lab.render_report({"id": "x", "model": "m"}, summary)
    assert "Wilson" in report and "not evidence of equivalence" in report and "+0%…+0%" not in report


@pytest.mark.skipif(not __import__("shutil").which("claude"), reason="Claude Code not installed")
def test_settings_preflight_uses_claude_doctor(tmp_path: Path):
    """No model call: `claude doctor` validates project settings."""
    good = lab.arm_settings(tmp_path, tmp_path / "suite", [])
    (tmp_path / "suite").mkdir()
    assert lab.preflight_settings(good, ["claude"], None) == []
    bad = {**good, "sandbox": {**good["sandbox"], "enabled": "yes"}}
    problems = lab.preflight_settings(bad, ["claude"], None)
    assert problems and "sandbox.enabled" in problems[0]


def test_agent_environment_carries_no_host_credentials(monkeypatch):
    for k in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK", "ANTHROPIC_API_KEY", "NPM_TOKEN"):
        monkeypatch.setenv(k, "secret-value")
    monkeypatch.delenv("REPO_AI_LAB_USE_API_KEY", raising=False)
    env = evals.agent_env({"CLAUDE_CONFIG_DIR": "/x"})
    assert "secret-value" not in env.values() and env["CLAUDE_CONFIG_DIR"] == "/x" and "PATH" in env
    monkeypatch.setenv("REPO_AI_LAB_USE_API_KEY", "1")
    assert evals.agent_env()["ANTHROPIC_API_KEY"] == "secret-value"  # explicit opt-in only


def test_each_run_may_write_only_its_own_workspace(tmp_path: Path):
    ws = tmp_path / "root" / "task-arm"
    ws.mkdir(parents=True)
    s = lab.arm_settings(ws, tmp_path / "suite", [tmp_path / "lab"])
    assert s["sandbox"]["filesystem"]["allowWrite"] == [str(ws.resolve())]
    assert str((tmp_path / "root").resolve()) not in s["sandbox"]["filesystem"]["allowRead"]


def test_fake_mode_refuses_the_real_client(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    for cmd in (["claude"], ["/usr/local/bin/claude"]):
        opts = lab.LabOptions(arms=lab.make_arms(["baseline"]), fake=True, claude_cmd=cmd,
                              results_dir=tmp_path / "r")
        with pytest.raises(SystemExit, match="fake client"):
            lab.run_experiment(suite, tasks[:1], bases, opts)


def test_fake_mode_never_passes_an_api_key(monkeypatch):
    monkeypatch.setenv("REPO_AI_LAB_USE_API_KEY", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "ANTHROPIC_API_KEY" not in evals.agent_env(allow_api_key=False)


@needs_sandbox
def test_tempfile_works_inside_the_grading_sandbox(tmp_path: Path):
    from repo_ai import sandbox as sb
    ws = tmp_path / "ws"
    ws.mkdir()
    res = sb.get_backend("auto", toolchain="python").run(
        ["python3", "-c", "import tempfile; f=tempfile.NamedTemporaryFile(); print('tmp ok', f.name)"],
        ws, limits=sb.Limits(timeout_s=60))
    assert res.ok and "tmp ok" in res.stdout, res.stderr


def test_builtin_claude_plugins_are_allowed_others_are_not():
    arm = lab.make_arms(["baseline"])[0]
    builtin = {"skills": [], "agents": [], "plugins": [{"name": "cc-plugin-agents-md"}, {"name": "cc-plugin-tips"}]}
    assert lab.check_isolation(arm, builtin, 0) == []
    user = {**builtin, "plugins": [*builtin["plugins"], {"name": "my-marketplace-plugin"}]}
    assert any("my-marketplace-plugin" in p for p in lab.check_isolation(arm, user, 0))
    mcp = {**builtin, "mcp_servers": [{"name": "gmail"}]}
    assert any("MCP" in p for p in lab.check_isolation(arm, mcp, 0))


def test_suite_inside_repo_ais_own_environment_is_carved_out(tmp_path: Path):
    env = tmp_path / "venv"
    suite = env / "lib" / "site-packages" / "repo_ai" / "_evalsuite"
    (suite / "cases" / "t1" / "hidden").mkdir(parents=True)
    (env / "bin").mkdir()
    (env / "lib" / "site-packages" / "pathspec").mkdir()
    (env / "lib" / "site-packages" / "repo_ai" / "cli.py").write_text("")
    allowed = lab.carve_out([str(env)], [suite])
    resolved = [Path(a).resolve() for a in allowed]
    assert str((env / "bin").resolve()) in allowed
    assert str((env / "lib" / "site-packages" / "pathspec").resolve()) in allowed
    assert str((env / "lib" / "site-packages" / "repo_ai" / "cli.py").resolve()) in allowed
    # neither the suite nor any directory containing it is re-opened
    assert not any(suite.resolve().is_relative_to(a) for a in resolved)
    assert lab.carve_out([str(env)], [tmp_path / "elsewhere"]) == [str(env.resolve())]


def test_named_ablations_remove_exactly_their_features():
    arms = {a.name: a for a in lab.make_arms(["baseline", "core", "ablations"])}
    full = arms["full"].features
    assert set(arms) == {"baseline", "core", "full", *[f"full-{a}" for a in lab.ABLATIONS]}
    for name, (removed, _) in lab.ABLATIONS.items():
        arm = arms[f"full-{name}"]
        assert full - arm.features == removed and arm.features < full
    assert lab.ABLATIONS["subagents"][0] == {"agents", "orchestration"}
    cfg = arms["full-packets"].config_toml()
    assert "write_claude_md = false" in cfg and 'skills_mode = "auto"' in cfg
    assert "write_claude_agents = false" in arms["full-subagents"].config_toml()
    assert 'learning_signals = "off"' in arms["full-outcomes"].config_toml()
    assert [a.name for a in lab.make_arms(["full"], ablate="subagents")] == ["full", "full-subagents"]


def test_crashed_attempts_are_charged_rerun_and_reported(tmp_path: Path):
    runs = tmp_path / "runs.jsonl"
    rows = [{"reservation": True, "task": "t1", "arm": "baseline", "rep": 0, "reserved_usd": 0.5},
            {"task": "t1", "arm": "baseline", "rep": 0, "valid": True, "success": True, "reported_cost_usd": 0.1},
            {"reservation": True, "task": "t1", "arm": "full", "rep": 0, "reserved_usd": 0.5}]
    runs.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    done, spent = lab.ledger_state(runs, 0.5)
    assert done == {("t1", "baseline", 0)}  # the crashed attempt runs again on resume
    assert spent == pytest.approx(0.6)  # 0.1 reported + the crashed attempt's full cap
    (tmp_path / "experiment.json").write_text(json.dumps({"id": "x"}))
    _, loaded = lab.load_runs(str(tmp_path))
    crashed = [r for r in loaded if r.get("crashed")]
    assert len(crashed) == 1 and crashed[0]["arm"] == "full" and not crashed[0]["valid"]
    assert lab.outcome_counts(loaded, "full")["crashed"] == 1


def test_limits_are_valid_failures_and_counted():
    runs = [{"arm": "core", "valid": True, "success": False, "subtype": "error_max_budget_usd"},
            {"arm": "core", "valid": True, "success": False, "subtype": "error_max_turns"},
            {"arm": "core", "valid": True, "success": False, "timed_out": True},
            {"arm": "core", "valid": False, "isolation_problems": ["x"]},
            {"arm": "core", "valid": True, "success": True}]
    c = lab.outcome_counts(runs, "core")
    assert c["attempts"] == 5 and c["valid"] == 4 and c["failure"] == 3 and c["success"] == 1
    assert c["stopped_by_cost_cap"] == 1 and c["stopped_by_max_turns"] == 1 and c["timed_out"] == 1
    assert c["invalid_isolation"] == 1


def test_arm_order_is_preregistered_and_resume_keeps_it():
    arms = lab.make_arms(["baseline", "core", "full"])
    first = [a.name for a in lab.arm_order("oss-md-001", 0, arms, 0)]
    assert first == [a.name for a in lab.arm_order("oss-md-001", 0, arms, 0)]  # pure function
    orders = {tuple(a.name for a in lab.arm_order(f"t{i}", r, arms, 0)) for i in range(20) for r in range(2)}
    assert len(orders) > 1  # randomised across tasks
    sched = lab.schedule([type("T", (), {"id": "a"})(), type("T", (), {"id": "b"})()], arms, 2, 0)
    assert [(s["rep"], s["task"]) for s in sched] == [(0, "a"), (0, "b"), (1, "a"), (1, "b")]


@needs_sandbox
def test_resume_refuses_a_different_protocol(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    opts = _opts(tmp_path, _solutions(tmp_path, task), "none", arms="baseline,full")
    meta = lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    opts2 = _opts(tmp_path, _solutions(tmp_path, task), "none", arms="baseline,core")
    with pytest.raises(SystemExit, match="different protocol"):
        lab.run_experiment(suite, task, bases, opts2, resume=meta["id"], log=lambda *_: None)
    again = lab.run_experiment(suite, task, bases, opts, resume=meta["id"], log=lambda *_: None)
    _, runs = lab.load_runs(str(opts.results_dir))
    assert again["id"] == meta["id"] and len(runs) == 2  # nothing re-run, nothing double-counted


def test_invalid_rate_counts_finished_attempts_only(tmp_path: Path):
    runs = tmp_path / "runs.jsonl"
    rows = [{"reservation": True, "task": "t", "arm": "a", "rep": 0}] + \
        [{"task": f"t{i}", "arm": "a", "valid": i % 3 != 0} for i in range(9)] + \
        [{"task": "x", "arm": "a", "cancelled": True, "valid": False}]
    runs.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert lab._invalid_rate(runs) == (9, 3)


@needs_sandbox
def test_blind_mode_never_logs_outcomes(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    opts = _opts(tmp_path, _solutions(tmp_path, task), "solve-all", arms="baseline,full", blind=True)
    lines: list[str] = []
    meta = lab.run_experiment(suite, task, bases, opts, log=lines.append)
    assert lines and all("PASS" not in line and "fail" not in line for line in lines)
    assert all(" done " in line for line in lines) and meta["blind"] is True
    assert [s["order"] for s in meta["schedule"]] == [[a.name for a in lab.arm_order(task[0].id, 0, opts.arms, 0, 0)]]


def test_balanced_schedule_uses_every_order_about_equally():
    import collections
    arms = lab.make_arms(["baseline", "core", "full"])
    tasks = [type("T", (), {"id": f"t{i:02d}"})() for i in range(25)]
    sched = lab.schedule(tasks, arms, 2, 0)
    counts = collections.Counter(tuple(s["order"]) for s in sched)
    assert len(counts) == 6 and max(counts.values()) - min(counts.values()) <= 1
    first = collections.Counter(s["order"][0] for s in sched)
    assert max(first.values()) - min(first.values()) <= 2  # each arm goes first about as often
    by_task = collections.defaultdict(list)
    for s in sched:
        by_task[s["task"]].append(tuple(s["order"]))
    assert all(a != b for a, b in by_task.values())  # the two repetitions differ


# -- money: the budget gate against near-cap spending (0.7.4) ---------------

def _stub_runs(monkeypatch, costs):
    """Replace the agent run with one that reports the next cost from `costs`
    (None = a run that reported no cost), so the gate is tested without Claude."""
    it = iter(costs)
    actual: list[float | None] = []

    def fake_run(task, base, suite, arm, opts, root, cap, cancel):
        assert cap == opts.max_cost_per_run  # every arm gets the same cap
        cost = next(it)
        actual.append(cost)
        return {"task": task.id, "arm": arm.name, "valid": True, "success": False,
                "reported_cost_usd": cost}
    monkeypatch.setattr(lab, "run_one", fake_run)
    monkeypatch.setattr(lab, "grading_sandbox_problems", lambda *a, **k: [])
    return actual


def _budget_run(tmp_path, monkeypatch, costs, budget, cap=0.04, repeat=2, **kw):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)  # 2 tasks; x 2 arms x 2 reps = 8 runs
    actual = _stub_runs(monkeypatch, costs)
    opts = _opts(tmp_path, _solutions(tmp_path, tasks), "none", arms="baseline,full",
                 max_cost_usd=budget, max_cost_per_run=cap, repeat=repeat, **kw)
    return lab.run_experiment(suite, tasks, bases, opts, log=lambda *_: None), actual


def test_reservation_and_completion_budget_formulas():
    opts = lab.LabOptions(arms=lab.make_arms(["baseline"]), max_cost_per_run=1.5)
    assert lab.reservation(opts) == pytest.approx(1.875)  # cap + 25% for the call past the cap
    assert lab.completion_budget(150, lab.reservation(opts)) == 281.25  # not 150 x 1.50 = 225
    assert lab.completion_budget(12, lab.reservation(opts)) == 22.5  # calibration fits $24
    opts.reserve_per_run = 2.0
    assert lab.reservation(opts) == 2.0
    opts.reserve_per_run = 1.0
    with pytest.raises(SystemExit):
        lab.reservation(opts)  # a reservation below the cap cannot hold a capped run
    # 147 runs at an average of $0.40, the last task's 3 arms at their full reservation
    assert lab.recommended_budget(150, 3, 0.40, 1.875) == 64.43  # rounded up to the cent


def test_planned_runs_x_cap_is_not_a_completion_budget(tmp_path, monkeypatch):
    # the 0.7.3 pre-registration's B = N x C: runs costing exactly the cap do not all fit,
    # because the gate holds 1.25 x cap for every pending arm of the next task
    meta, actual = _budget_run(tmp_path, monkeypatch, [0.04] * 8, budget=8 * 0.04)
    assert meta["stopped"] == "budget" and len(actual) == 6  # the last task-repetition never started
    assert meta["completion_budget_usd"] == 0.4 and meta["worst_case_usd"] == 0.4


@pytest.mark.parametrize("cost", [0.0, 0.04, 0.0495, 0.05])  # 0, cap, 0.99 R, exactly R
def test_planned_runs_x_reservation_always_completes(tmp_path, monkeypatch, cost):
    budget = lab.completion_budget(8, 0.05)
    meta, actual = _budget_run(tmp_path, monkeypatch, [cost] * 8, budget=budget)
    assert meta["stopped"] is None and len(actual) == 8
    assert meta["spent_usd_charged"] == pytest.approx(8 * cost) and meta["spent_usd_charged"] <= budget


def test_runs_that_report_no_cost_are_charged_their_reservation(tmp_path, monkeypatch):
    meta, actual = _budget_run(tmp_path, monkeypatch, [None, 0.01, None, 0.01, 0.01, 0.01, 0.01, 0.01],
                               budget=0.40)
    assert len(actual) == 8 and meta["spent_usd_charged"] == pytest.approx(2 * 0.05 + 6 * 0.01)
    # ...and so they hold back exactly as much as a run costing its reservation
    meta, actual = _budget_run(tmp_path / "b", monkeypatch, [None] * 8, budget=0.39)
    assert meta["stopped"] == "budget" and len(actual) == 6


def test_a_run_above_its_reservation_stops_the_experiment(tmp_path, monkeypatch):
    # Claude checks the cap between API calls: if one call overshoots by more
    # than the reservation's margin, the assumption behind the gate failed
    meta, actual = _budget_run(tmp_path, monkeypatch, [0.01, 0.0501] + [0.01] * 6, budget=10)
    assert len(actual) == 2 and meta["stopped"].startswith("run cost $0.0501 above its reservation")


def test_the_charged_total_never_exceeds_the_budget(tmp_path, monkeypatch):
    # property check over random near-cap spending: whenever every run stays
    # within its reservation, the money charged never exceeds the approved budget
    import random
    rng = random.Random(7)
    for trial in range(60):
        reserve = 0.05
        costs = [rng.choice([0.0, 0.04, 0.049, 0.0499, 0.05, None, rng.uniform(0, 0.05)])
                 for _ in range(8)]
        budget = round(rng.uniform(0.0, 0.45), 4)
        meta, actual = _budget_run(tmp_path / str(trial), monkeypatch, costs, budget=budget)
        charged = sum(reserve if c is None else c for c in actual)
        assert charged <= budget + 1e-9, (costs, budget)
        assert meta["spent_usd_charged"] == pytest.approx(charged, abs=1e-4)
        assert len(actual) % 2 == 0  # a task's arms always run together: pairs are never broken
        if budget >= lab.completion_budget(8, reserve):
            assert len(actual) == 8 and meta["stopped"] is None


def test_per_call_cost_is_estimated_from_assistant_usage(tmp_path: Path):
    def assistant(mid, **usage):
        return json.dumps({"type": "assistant", "message": {"id": mid, "content": [], "usage": usage}})
    lines = [assistant("m1", input_tokens=1000, output_tokens=0),
             assistant("m1", input_tokens=1000, output_tokens=200),  # same call streamed twice
             assistant("m2", input_tokens=10, cache_read_input_tokens=10000, output_tokens=100),
             json.dumps({"type": "result", "subtype": "success", "num_turns": 2,
                         "total_cost_usd": 0.30, "usage": {"input_tokens": 1010, "output_tokens": 300}})]
    m = evals.parse_stream(lines, tmp_path, [])
    # price units: m1 = 1000 + 5 x 200 = 2000; m2 = 10 + 0.1 x 10000 + 5 x 100 = 1510
    assert m["api_calls"] == 2
    assert m["max_call_cost_usd_est"] == pytest.approx(0.30 * 2000 / 3510, abs=1e-4)


def test_preregistered_limits_follow_the_rule_exactly():
    def run(arm, cost, turns=20, wall=300.0, call=0.05, subtype="success"):
        return {"arm": arm, "reported_cost_usd": cost, "turns": turns, "wall_s": wall,
                "max_call_cost_usd_est": call, "subtype": subtype}
    runs = [run(a, c) for a, cs in {"baseline": [0.10, 0.12, 0.20, 0.30], "core": [0.15, 0.2, 0.25, 0.35],
                                    "full": [0.2, 0.3, 0.3, 0.4]}.items() for c in cs]
    lim = lab.preregistered_limits(runs)
    # largest per-arm p90 is 0.40 (4 runs: nearest-rank p90 is the max): C >= 0.80 -> $1.00
    assert lim["max_cost_per_run"] == 1.00 and lim["max_turns"] == 30 and lim["timeout_s"] == 1800
    assert lim["reserve_margin"] == 0.25 and lim["reserve_per_run"] == 1.25 and not lim["reserve_flag_needed"]
    assert lim["guaranteed_budget"] == 187.5
    # u = 2 x largest arm mean (full: 0.30) = 0.60 >= overall p90; 147 x 0.60 + 3 x 1.25 = 91.95 -> $95
    assert lim["mean_cost_upper"] == pytest.approx(0.60) and lim["recommended_budget"] == 95
    # a large single call widens the margin; long runs raise turns and timeout
    runs[0].update(max_call_cost_usd_est=0.31, turns=45, wall_s=1200.0)
    lim = lab.preregistered_limits(runs)
    assert lim["reserve_margin"] == 0.65 and lim["reserve_per_run"] == 1.65 and lim["reserve_flag_needed"]
    assert lim["max_turns"] == 80 and lim["timeout_s"] == 2400
    runs[0]["subtype"] = "error_max_turns"
    assert lab.preregistered_limits(runs)["max_turns"] == 80
    # costs too high for every pre-registered cap: stop, never improvise
    assert lab.preregistered_limits([run("baseline", 1.2)])["max_cost_per_run"] is None
    assert "problem" in lab.preregistered_limits([{"arm": "core", "reported_cost_usd": None}])


def test_calibration_report_applies_the_preregistered_rule():
    runs = [{"task": f"cal-{t}", "arm": arm, "rep": 0, "valid": True, "success": bool(i % 2),
             "category": "bugfix", "reported_cost_usd": 0.1 + 0.05 * i, "turns": 10 + i, "wall_s": 100.0 + i,
             "max_call_cost_usd_est": 0.02, "subtype": "success"}
            for i, (t, arm) in enumerate((t, a) for t in "abcd" for a in ("baseline", "core", "full"))]
    summary = lab.summarize(runs)
    lim = summary["preregistered_limits"]
    assert lim["max_cost_per_run"] == 1.50 and lim["reserve_per_run"] == 1.875  # p90 0.65 -> C >= 1.30
    text = lab.render_report({"id": "x", "tasks": ["cal-a"], "repeat": 1}, summary)
    assert "per-run cap C = $1.50" in text and "Largest single API call" in text
    # the main experiment's report never carries it
    assert "preregistered_limits" not in lab.summarize([{**r, "task": "oss-" + r["task"]} for r in runs])


# -- execution artifacts are not edits (0.7.5) --------------------------------

def test_execution_artifacts_are_told_apart_from_edits():
    artifact = ["calc/__pycache__/money.cpython-312.pyc", "tests/__pycache__/test_x.cpython-312-pytest-8.3.2.pyc",
                "pkg/__pycache__/m.cpython-314.opt-1.pyc", "pkg/__pycache__/m.pypy310.pyc",
                ".pytest_cache/v/cache/nodeids", "sub/.mypy_cache/3.12/x.json", ".ruff_cache/0.1/a",
                ".hypothesis/examples/x", ".coverage", ".coverage.host.123"]
    edits = ["calc/money.py", "calc/money.pyc",  # a module-level .pyc is importable without source
             "pkg/__pycache__/notes.txt", "pkg/__pycache__/evil.pyc",  # not an interpreter cache name
             "__pycache__", "README.md", "coverage.py", "docs/pytest_cache.md"]
    assert all(lab.is_execution_artifact(p) for p in artifact)
    assert not any(lab.is_execution_artifact(p) for p in edits)


def test_grading_copy_drops_planted_bytecode(tmp_path: Path):
    """Without the filter, bytecode whose header matches the source's mtime and
    size is imported instead of the source: an agent could make hidden tests
    pass with code that is not in the repository."""
    import importlib.util
    import os
    import py_compile
    import shutil
    import subprocess
    ws = tmp_path / "ws"
    (ws / "calc").mkdir(parents=True)
    src = ws / "calc" / "money.py"
    src.write_text("def f():\n    return 'buggy'\n")
    st = src.stat()
    fake = tmp_path / "fake_src.py"
    fake.write_text("def f():\n    return 'FIXED'\n")  # same size as the real source
    assert fake.stat().st_size == st.st_size
    os.utime(fake, ns=(st.st_atime_ns, st.st_mtime_ns))
    py_compile.compile(str(fake), cfile=importlib.util.cache_from_source(str(src)), doraise=True)
    probe = [sys.executable, "-c", "import calc.money as m; print(m.f())"]
    for name, ignore in (("plain", None), ("graded", lab._no_bytecode)):
        dest = tmp_path / name
        shutil.copytree(ws, dest, symlinks=True, ignore=ignore)
        out = subprocess.run(probe, cwd=dest, capture_output=True, text=True,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}).stdout.strip()
        assert out == ("FIXED" if name == "plain" else "buggy")  # the vector, then the fix


@needs_sandbox
@pytest.mark.parametrize("stray", [False, True])
def test_running_tests_is_not_an_unnecessary_edit_in_any_arm(tmp_path: Path, stray: bool):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    policy = "solve-all+runtests" + ("+stray" if stray else "")
    opts = _opts(tmp_path, _solutions(tmp_path, task), policy)
    meta = lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    _, runs = lab.load_runs(meta["id"] if not opts.results_dir else str(opts.results_dir))
    assert sorted(r["arm"] for r in runs) == ["baseline", "core", "full"]
    for r in runs:
        assert r["valid"] and r["success"] and not r["regression"], r["arm"]  # grading unaffected
        assert r["execution_artifacts"] > 0 and r["test_commands"] == 1, r["arm"]
        assert not any(p.endswith(".pyc") or ".pytest_cache" in p for p in r["files_changed"])
        assert "calc/money.py" in r["files_changed"]
        assert r["unnecessary_edits"] == (["calc/text.py"] if stray else []), r["arm"]
    assert lab.summarize(runs)["arms"]["core"]["unnecessary_edit_rate"] == (1.0 if stray else 0.0)


def test_bash_commands_and_test_runs_are_recorded(tmp_path: Path):
    def bash(cmd):
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}})
    lines = [bash("git diff"), bash("python3 -m unittest tests.test_x"), bash("cd sub && pytest -q"),
             bash("ls tests"), bash("x" * 1000),
             json.dumps({"type": "result", "subtype": "success", "num_turns": 1, "total_cost_usd": 0.1})]
    m = evals.parse_stream(lines, tmp_path, [])
    assert m["bash_commands"][:4] == ["git diff", "python3 -m unittest tests.test_x", "cd sub && pytest -q",
                                      "ls tests"]
    assert len(m["bash_commands"][4]) == evals.BASH_COMMAND_CHARS and m["test_commands"] == 2


def test_resume_refuses_a_different_repo_ai_build(tmp_path: Path, monkeypatch):
    # the pre-registration pins one repo-ai release per experiment
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    monkeypatch.setattr(lab, "grading_sandbox_problems", lambda *a, **k: [])
    monkeypatch.setattr(lab, "run_one", lambda task, base, suite, arm, opts, *a: {
        "task": task.id, "arm": arm.name, "valid": True, "success": False, "reported_cost_usd": 0.01})
    opts = _opts(tmp_path, _solutions(tmp_path, task), "none", arms="baseline,full", repeat=2)
    meta = lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    assert meta["repo_ai_version"] == lab.__version__
    monkeypatch.setattr(lab, "__version__", "0.0.0-other")
    with pytest.raises(SystemExit, match="repo_ai_version"):
        lab.run_experiment(suite, task, bases, opts, resume=meta["id"], log=lambda *_: None)


# -- integrity: proof of access, not content similarity (0.7.6) ----------------

def _integrity_run(tmp_path: Path, policy: str, extra: dict | None = None):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    hidden = task[0].dir / "hidden" / "test_hidden_round.py"
    solutions = {t.prompt: t.solution for t in task}
    solutions.update({"__peek__": str(hidden), "__dest__": "tests/test_hidden_round.py",
                      "__match__": hidden.read_text()}, **(extra or {}))
    path = tmp_path / "solutions.json"
    path.write_text(json.dumps(solutions))
    opts = _opts(tmp_path, path, policy, arms="baseline")
    lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    _, runs = lab.load_runs(str(opts.results_dir))
    assert not list((lab.lab_home() / "canaries").glob("*/cases")), "canary decoys are removed"
    return runs[0]


@needs_sandbox
def test_reading_a_hidden_test_invalidates_the_run(tmp_path: Path):
    r = _integrity_run(tmp_path, "solve-all+peek")
    assert not r["valid"] and any("Read read:" in c for c in r["contaminated"])


@needs_sandbox
def test_a_denied_attempt_is_recorded_but_does_not_invalidate(tmp_path: Path):
    r = _integrity_run(tmp_path, "solve-all+peek-denied")
    assert r["valid"] and r["success"] and not r["contaminated"]
    assert r["hidden_access_attempts"] and "denied" in r["hidden_access_attempts"][0]


@needs_sandbox
def test_a_sandbox_escape_is_caught_by_the_canary(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REPO_AI_LAB_HOME", str(tmp_path / "labhome"))
    r = _integrity_run(tmp_path, "solve-all+canary")
    assert not r["valid"] and any("canary" in c for c in r["contaminated"])


@needs_sandbox
def test_a_legitimate_edit_matching_the_hidden_test_stays_valid(tmp_path: Path):
    # the oss-tl-001 case: the agent's own edit reproduces the upstream test byte for byte
    r = _integrity_run(tmp_path, "solve-all+match")
    assert r["valid"] and r["success"] and not r["contaminated"] and not r["hidden_access_attempts"]
    diag = r["hidden_content_match"]
    assert diag["identical_files"] == ["tests/test_hidden_round.py"]
    assert diag["hidden_only_lines"] > 0 and diag["hidden_only_lines_present"] == diag["hidden_only_lines"]


def test_transcript_scan_distinguishes_access_attempts_and_discovery():
    from repo_ai import integrity

    def use(uid, name, inp):
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": uid, "name": name, "input": inp}]}})

    def result(uid, body, error=False):
        return json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": uid, "content": body, "is_error": error}]}})
    protected = integrity.protected_paths(Path("/opt/suite"))
    lines = [use("1", "Read", {"file_path": "/opt/suite/cases/t/hidden/test_x.py"}), result("1", "def test(): ..."),
             use("2", "Bash", {"command": "cat /opt/suite/cases/t/task.json"}),
             result("2", "cat: /opt/suite/cases/t/task.json: Operation not permitted", True),
             use("3", "Bash", {"command": "find / -name 'test_x.py'"}),
             result("3", "/work/tests/test_x.py\n/opt/suite/cases/t/hidden/test_x.py"),
             use("4", "Read", {"file_path": "/work/src/app.py"}), result("4", "print('ok')")]
    seen = integrity.scan_transcript(lines, protected, "REPO_AI_CANARY_x")
    assert seen["access"] == ["Read read: /opt/suite", "Bash revealed: /opt/suite"]
    assert seen["attempts"] == ["Bash denied: /opt/suite"] and not seen["canary_seen"]
    assert integrity.scan_transcript([use("5", "Bash", {"command": "echo REPO_AI_CANARY_x"}), result("5", "")],
                                     protected, "REPO_AI_CANARY_x")["canary_seen"]


@needs_sandbox
def test_a_repository_kept_suites_authoring_notes_are_denied(tmp_path: Path):
    # sealed-v2 lives in the repository beside benchmarks/authoring (the fixes): deny both
    suite = _suite(tmp_path / "bench")
    (suite.parent / "authoring").mkdir()
    bases, tasks = evals.load_suite(suite)
    task = [t for t in tasks if t.id == "mini-001-rounding"]
    opts = _opts(tmp_path, _solutions(tmp_path, task), "solve-all+denylist", arms="baseline",
                 keep_workspaces=True)
    lab.run_experiment(suite, task, bases, opts, log=lambda *_: None)
    _, runs = lab.load_runs(str(opts.results_dir))
    deny = json.loads((Path(runs[0]["workspace"]) / "denylist.json").read_text())
    assert str((suite.parent / "authoring").resolve()) in {str(Path(d).resolve()) for d in deny}
    assert str(suite.resolve()) in {str(Path(d).resolve()) for d in deny}


# -- the budget-limited two-arm design (0.7.7) --------------------------------

def _sealed_like_tasks():
    from types import SimpleNamespace
    sizes = {"sg": 8, "dns": 6, "ac": 4, "asn": 2, "lk": 2, "mi": 1, "te": 1, "mk": 1}
    return [SimpleNamespace(id=f"v2-{b}-{i:03d}", base=f"v2-{b}") for b, n in sizes.items()
            for i in range(1, n + 1)]


def test_interleaved_order_spreads_every_prefix_across_the_bases():
    import collections
    tasks = _sealed_like_tasks()
    order = lab.interleave_by_base(tasks, 0)
    assert sorted(t.id for t in order) == sorted(t.id for t in tasks)  # a permutation: nothing dropped
    assert [t.id for t in order] == [t.id for t in lab.interleave_by_base(list(reversed(tasks)), 0)]
    assert [t.id for t in order] != [t.id for t in lab.interleave_by_base(tasks, 1)]  # seeded
    assert len({t.base for t in order[:8]}) == 8  # the first round reaches every project
    totals = collections.Counter(t.base for t in tasks)
    for k in range(1, len(order) + 1):
        seen = collections.Counter(t.base for t in order[:k])
        open_bases = [b for b in totals if seen[b] < totals[b]]
        # round-robin: no base gets two tasks ahead of a base that still has tasks
        assert all(seen[b] <= seen[o] + 1 for b in totals for o in open_bases)


def test_two_arm_schedule_alternates_which_arm_goes_first():
    arms = lab.make_arms(["baseline", "core"])
    sched = lab.schedule(lab.interleave_by_base(_sealed_like_tasks(), 0), arms, 1, 0)
    firsts = [s["order"][0] for s in sched]
    assert all(sorted(s["order"]) == ["baseline", "core"] for s in sched)
    for k in range(1, len(firsts) + 1):  # balanced in every prefix, so under any budget stop
        assert abs(firsts[:k].count("baseline") - firsts[:k].count("core")) <= 1


def test_a_budget_stop_never_splits_a_tasks_arms(tmp_path, monkeypatch):
    # 2 tasks x 2 arms, reservation 0.05: the second task needs 0.10 left, only 0.09 is
    meta, actual = _budget_run(tmp_path, monkeypatch, [0.04] * 4, budget=0.17, repeat=1)
    _, runs = lab.load_runs(str(tmp_path / "results"))
    assert meta["stopped"] == "budget" and len(actual) == 2
    assert {r["task"] for r in runs} == {meta["tasks"][0]}
    assert sorted(r["arm"] for r in runs) == ["baseline", "full"]


def test_resume_refuses_a_different_task_order(tmp_path, monkeypatch):
    meta, _ = _budget_run(tmp_path, monkeypatch, [0.01] * 8, budget=1.0, repeat=1)
    bases, tasks = evals.load_suite(tmp_path / "suite")
    opts = _opts(tmp_path, _solutions(tmp_path, tasks), "none", arms="baseline,full",
                 max_cost_usd=1.0, max_cost_per_run=0.04)
    with pytest.raises(SystemExit, match="different protocol"):
        lab.run_experiment(tmp_path / "suite", list(reversed(tasks)), bases, opts,
                           resume=meta["id"], log=lambda *_: None)


def test_a_live_run_refuses_a_missing_toolchain_instead_of_skipping(tmp_path, monkeypatch):
    suite = _suite(tmp_path)
    data = json.loads((suite / "bases.json").read_text())
    data["mini"]["toolchain"] = ["python", "no-such-tool-repo-ai"]
    (suite / "bases.json").write_text(json.dumps(data))
    bases, tasks = evals.load_suite(suite)
    monkeypatch.setattr(lab, "audit_config_dir", lambda *a: [])
    monkeypatch.setattr(lab, "preflight_settings", lambda *a: [])
    called: list[object] = []
    monkeypatch.setattr(lab, "run_one", lambda *a: called.append(a))
    opts = lab.LabOptions(arms=lab.make_arms(["baseline", "core"]), max_cost_usd=1.0,
                          claude_cmd=["/nonexistent/claude"], results_dir=tmp_path / "results")
    with pytest.raises(SystemExit, match="(?s)toolchain missing.*no-such-tool-repo-ai"):
        lab.run_experiment(suite, tasks, bases, opts, log=lambda *_: None)
    assert not called and not (tmp_path / "results").exists()
    dry = lab.run_experiment(suite, tasks, bases, lab.LabOptions(
        arms=opts.arms, claude_cmd=opts.claude_cmd, dry_run=True), log=lambda *_: None)
    assert set(dry["missing_toolchains"]) == {t.id for t in tasks}


def test_correct_without_regression_and_unpaired_tasks_are_reported():
    def run(task, arm, success, regression=False, valid=True):
        return {"task": task, "arm": arm, "rep": 0, "valid": valid, "success": success,
                "regression": regression, "category": "bugfix"}
    runs = [run("t1", "baseline", True, regression=True), run("t1", "core", True),
            run("t2", "baseline", True), run("t2", "core", False, valid=False),
            run("t3", "baseline", False), run("t3", "core", False, regression=True)]
    s = lab.summarize(runs)
    assert s["arms"]["baseline"]["success_rate"] == pytest.approx(0.667)  # hidden tests only, as graded
    assert s["arms"]["baseline"]["correct_no_regression_rate"] == 0.333
    assert s["arms"]["core"]["correct_no_regression_rate"] == 0.5
    assert s["arms"]["core"]["regression_free_rate"] == 0.5
    composite = s["outcome_comparisons"]["correct_no_regression"][0]
    assert composite["tasks"] == 2 and composite["diff"] == pytest.approx(0.5)
    assert s["comparisons"][0]["unpaired_tasks"] == ["t2"]  # never silently dropped
    runs[0]["hidden_content_match"] = {"identical_files": ["tests/test_x.py"]}  # diagnostic only
    s2 = lab.summarize(runs)
    assert s2["arms"]["baseline"]["n"] == 3  # still valid in the primary analysis
    assert s2["sensitivity"]["content_match_as_invalid"][0]["tasks"] == 1  # t1 leaves the pairs
    text = lab.render_report({"id": "x", "tasks": ["t1", "t2", "t3"]}, s)
    assert "Correct with no regression" in text and "not compared (a valid run in one arm only): t2" in text
    assert "regression-free (visible suite passes)" in text
