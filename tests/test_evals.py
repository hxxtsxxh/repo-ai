"""`repo-ai eval`: oracle validation, localization, and the live pipeline.

`eval --live` runs in the coding lab (sandboxed grading). It is exercised end
to end with a fake `claude` (tests/fake_claude_lab.py) that speaks stream-json
and applies the reference solution, so no model is called and nothing is billed.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

import pytest

from conftest import run_cli

from repo_ai import evals



def _suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    base = suite / "bases" / "mini"
    (base / "calc").mkdir(parents=True)
    (base / "tests").mkdir()
    (base / "calc" / "__init__.py").write_text("")
    (base / "calc" / "money.py").write_text(
        '"""Money helpers: rounding of currency amounts."""\n\n\n'
        "def round_cents(amount: float) -> int:\n"
        '    """Round a currency amount to whole cents."""\n'
        "    return int(round(amount * 100))\n")
    (base / "calc" / "text.py").write_text(
        '"""Text helpers."""\n\n\ndef shout(s: str) -> str:\n    return s.upper()\n')
    (base / "tests" / "__init__.py").write_text("")
    (base / "tests" / "test_text.py").write_text(
        "import unittest\nfrom calc.text import shout\n\n\n"
        "class T(unittest.TestCase):\n    def test_shout(self):\n"
        "        self.assertEqual(shout('a'), 'A')\n")
    (suite / "bases.json").write_text(json.dumps({"mini": {
        "language": "python", "toolchain": ["python"],
        "visible_tests": [["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", "."]]}}))
    hidden = "import unittest\nfrom calc.money import round_cents\n\n\nclass H(unittest.TestCase):\n" \
             "    def test_round(self):\n        self.assertEqual(round_cents(1.005), 101)\n" \
             "        self.assertEqual(round_cents(2.0), 200)\n"
    for task_id, solution in (
        ("mini-001-rounding", [{"file": "calc/money.py", "find": "int(round(amount * 100))",
                                "replace": "int(round(amount * 100 + 1e-9))"}]),
        ("mini-002-broken-oracle", [{"file": "calc/text.py", "find": "s.upper()",
                                     "replace": "s.upper()  # unrelated"}]),
    ):
        case = suite / "cases" / task_id
        (case / "hidden").mkdir(parents=True)
        (case / "hidden" / "test_hidden_round.py").write_text(hidden)
        (case / "task.json").write_text(json.dumps({
            "id": task_id, "base": "mini", "language": "python", "category": "bugfix",
            "difficulty": "easy",
            "prompt": "Rounding of currency amounts to cents is off by one for values like 1.005",
            "setup": [], "solution": solution, "gold_files": [solution[0]["file"]],
            "hidden": [{"src": "hidden/test_hidden_round.py", "dest": "tests/test_hidden_round.py"}],
            "commands": [["{python}", "-m", "unittest", "tests.test_hidden_round"]],
            "timeout_s": 60, "attribution": "test"}))
    return suite


def test_suite_loads_and_rejects_unsafe_paths(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    assert set(bases) == {"mini"} and [t.id for t in tasks] == ["mini-001-rounding",
                                                                 "mini-002-broken-oracle"]
    with pytest.raises(evals.SuiteError):
        evals.apply_edits(tmp_path, [{"file": "../escape.py", "create": "x"}], "t")


def test_validation_accepts_a_sound_task_and_flags_a_broken_oracle(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    report = evals.run_offline(suite, tasks, bases, localization=False)
    v = report["validation"]
    assert v["valid"] == 1
    bad = {r["id"]: r for r in v["invalid"]}
    assert "mini-002-broken-oracle" in bad
    assert "hidden tests fail on the reference solution" in bad["mini-002-broken-oracle"]["problems"]
    assert "gold_files" not in " ".join(bad["mini-002-broken-oracle"]["problems"])


def test_localization_scores_repo_ai_and_the_naive_baseline(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    report = evals.run_offline(suite, tasks[:1], bases, validate=False)
    row = report["localization"]["tasks"][0]
    assert row["repo_ai"]["first_rank"] == 1, row
    assert row["naive"]["first_rank"] is not None
    summary = report["localization"]["summary"]
    assert summary["repo_ai"]["recall_at_5"] == 1.0
    assert "regressions_vs_naive" in summary


def test_cli_offline_gate_fails_on_invalid_tasks(tmp_path: Path):
    suite = _suite(tmp_path)
    proc = run_cli(None, "eval", "--suite", str(suite), "--no-localization", "--format", "json")
    assert proc.returncode == 1
    assert "GATE FAIL: invalid task mini-002-broken-oracle" in proc.stderr
    data = json.loads(proc.stdout)
    assert data["mode"] == "offline" and data["validation"]["valid"] == 1


def test_live_requires_an_explicit_budget(tmp_path: Path):
    suite = _suite(tmp_path)
    proc = run_cli(None, "eval", "--suite", str(suite), "--live")
    assert proc.returncode != 0 and "--max-cost-usd" in proc.stderr
    proc = run_cli(None, "eval", "--suite", str(suite), "--live", "--no-network",
                   "--max-cost-usd", "1")
    assert proc.returncode != 0 and "network" in proc.stderr


def test_live_is_the_sandboxed_lab_and_its_dry_run_spends_nothing(tmp_path: Path):
    suite = _suite(tmp_path)
    proc = run_cli(None, "eval", "--suite", str(suite), "--live", "--dry-run", "--max-cost-usd", "5",
                   "--claude-cmd", "/nonexistent/claude", "--results", str(tmp_path / "r"),
                   "--claude-config", str(tmp_path / "cfg"))
    assert proc.returncode == 0, proc.stderr
    assert "eval coding --compare baseline,full" in proc.stdout
    assert "nothing was executed" in proc.stdout and "grading sandbox:" in proc.stdout
    assert not hasattr(evals, "run_live") and not hasattr(evals, "LiveOptions")


@pytest.mark.skipif(not __import__("repo_ai.sandbox", fromlist=["x"]).AUTO_ORDER, reason="")
def test_live_pipeline_with_fake_claude_grades_in_the_sandbox(tmp_path: Path):
    from repo_ai import sandbox
    try:
        sandbox.get_backend("auto", toolchain="python")
    except sandbox.SandboxUnavailable:
        pytest.skip("no sandbox backend")
    suite = _suite(tmp_path)
    _, tasks = evals.load_suite(suite)
    solutions = tmp_path / "solutions.json"
    solutions.write_text(json.dumps({t.prompt: t.solution for t in tasks if t.id == "mini-001-rounding"}))
    fake = Path(__file__).parent / "fake_claude_lab.py"
    proc = run_cli(None, "eval", "--suite", str(suite), "--live", "--fake", "--tasks", "mini-001",
                   "--claude-cmd", f"{sys.executable} {fake} {solutions} solve-all",
                   "--results", str(tmp_path / "r"), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout[proc.stdout.index("{"):])
    arms = report["summary"]["arms"]
    assert set(arms) == {"baseline", "full"} and arms["full"]["success_rate"] == 1.0
    runs = [json.loads(line) for line in (tmp_path / "r" / "runs.jsonl").read_text().splitlines()]
    assert all(r["backend"] in sandbox.BACKENDS for r in runs)


@pytest.mark.skipif(not __import__("repo_ai.sandbox", fromlist=["x"]).AUTO_ORDER, reason="")
def test_budget_stops_before_a_task_that_might_not_fit(tmp_path: Path):
    from repo_ai import coding_lab as lab
    from repo_ai import sandbox
    try:
        sandbox.get_backend("auto", toolchain="python")
    except sandbox.SandboxUnavailable:
        pytest.skip("no sandbox backend")
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    tasks = [t for t in tasks if t.id == "mini-001-rounding"] * 1 + [t for t in tasks if t.id != "mini-001-rounding"]
    fake = Path(__file__).parent / "fake_claude_lab.py"
    solutions = tmp_path / "s.json"
    solutions.write_text("{}")
    # 2 arms × $0.03 worst case = $0.06 per task; the fake reports $0.02 per run
    opts = lab.LabOptions(arms=lab.make_arms(["baseline", "full"]), fake=True, max_cost_usd=0.09,
                          max_cost_per_run=0.03, claude_cmd=[sys.executable, str(fake), str(solutions), "none"],
                          results_dir=tmp_path / "r", timeout_s=120)
    meta = lab.run_experiment(suite, tasks, bases, opts, log=lambda *_: None)
    _, runs = lab.load_runs(str(tmp_path / "r"))
    assert len(runs) == 2 and meta["stopped"] == "budget"  # $0.09 - $0.04 < $0.06
    assert meta["spent_usd_charged"] == pytest.approx(0.04)


def test_mcnemar_lives_in_stats():
    from repo_ai import stats
    assert stats.mcnemar_exact(0, 6) == pytest.approx(0.03125)


def test_parse_stream_ignores_unknown_events(tmp_path: Path):
    lines = ["not json", json.dumps({"type": "future_event"}),
             json.dumps({"type": "assistant", "message": {"content": [
                 {"type": "tool_use", "name": "Read", "input": {"file_path": str(tmp_path / "a.py")}},
                 {"type": "tool_use", "name": "Edit", "input": {"file_path": str(tmp_path / "b.py")}},
                 {"type": "tool_use", "name": "Task", "input": {}}]}}),
             json.dumps({"type": "result", "subtype": "success", "num_turns": 2,
                         "total_cost_usd": 0.5, "duration_ms": 1500,
                         "usage": {"input_tokens": 10, "output_tokens": 5}})]
    m = evals.parse_stream(lines, tmp_path, ["b.py"])
    assert m["files_read_before_first_edit"] == 1 and m["first_edit"] == "b.py"
    assert m["first_edit_in_gold"] and m["subagent_calls"] == 1 and m["duration_s"] == 1.5


def test_claude_argv_is_least_privilege_and_sandboxed(tmp_path: Path):
    from repo_ai import coding_lab as lab
    opts = lab.LabOptions(arms=lab.make_arms(["baseline"]), model="sonnet")
    argv = lab.claude_argv(opts, "do it", 0.5, tmp_path / "settings.json")
    assert argv[:3] == ["claude", "-p", "do it"]
    assert "--dangerously-skip-permissions" not in argv and "bypassPermissions" not in argv
    joined = shlex.join(argv)
    assert "--permission-mode dontAsk" in joined and "--strict-mcp-config" in joined
    assert argv[argv.index("--disallowedTools") + 1] == "WebFetch"


def test_materialize_never_copies_bytecode(tmp_path: Path):
    suite = _suite(tmp_path)
    cache = suite / "bases" / "mini" / "calc" / "__pycache__"
    cache.mkdir()
    (cache / "money.cpython-313.pyc").write_bytes(b"\x00compiled")
    bases, tasks = evals.load_suite(suite)
    ws = evals.materialize(tasks[0], suite, tmp_path / "ws", git=False)
    assert not list(ws.rglob("__pycache__")) and not list(ws.rglob("*.pyc"))


def test_parse_stream_records_invoked_skills(tmp_path: Path):
    lines = [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": str(tmp_path / "a.py")}},
        {"type": "tool_use", "name": "Skill", "input": {"skill": "repo-locate", "args": "x"}},
        {"type": "tool_use", "name": "Skill", "input": {"skill": "/pdf extract"}}]}})]
    m = evals.parse_stream(lines, tmp_path, [])
    assert m["skills_invoked"] == ["repo-locate", "pdf"]


def test_regression_runner_ignores_only_hidden_defined_tests(tmp_path: Path):
    import subprocess
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_hidden.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_fixed(self):\n        self.fail('bug present')\n")
    (tests / "test_other.py").write_text(
        "import unittest\nfrom tests.test_hidden import T\nclass Sub(T):\n    def test_mine(self):\n        pass\n")
    task = evals.Task("t", "b", "python", "bugfix", "easy", "p", [], [], [], [{"src": "x", "dest": "tests/test_hidden.py"}],
                      [], 60, "", tmp_path, visible_after_hidden=True)
    base = evals.Base("b", "python", [["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", "."]], ["python"])
    (cmd,) = evals.regression_commands(task, base)
    argv = [sys.executable if a == "{python}" else a for a in cmd]
    assert subprocess.run(argv, cwd=tmp_path, capture_output=True).returncode == 0  # inherited failure ignored
    (tests / "test_other.py").write_text((tests / "test_other.py").read_text()
                                         + "    def test_broken(self):\n        self.fail('regression')\n")
    out = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 1 and "REGRESSION tests.test_other.Sub.test_broken" in out.stdout
    assert evals.regression_commands(evals.Task("t", "b", "python", "bugfix", "easy", "p", [], [], [], [], [], 60, "",
                                                tmp_path), base) == base.visible_tests


def test_final_split_is_only_selected_by_name(tmp_path: Path):
    suite = _suite(tmp_path)
    bases, tasks = evals.load_suite(suite)
    tasks[0].split = "final"
    assert tasks[0] not in evals.select_tasks(tasks, None, None, 0, "all")
    assert evals.select_tasks(tasks, None, None, 0, "final") == [tasks[0]]
    assert tasks[0] not in evals.select_tasks(tasks, None, None, 0, evals.split_of(tasks[0].id))


def test_delete_edits_remove_files_the_fix_added(tmp_path: Path):
    (tmp_path / "a.py").write_text("x")
    evals.apply_edits(tmp_path, [{"file": "a.py", "delete": True}, {"file": "gone.py", "delete": True}], "t")
    assert not (tmp_path / "a.py").exists()


def test_open_source_tasks_are_sealed_and_licensed():
    bases, tasks = evals.load_suite(evals.default_suite_dir())
    oss = [t for t in tasks if bases[t.base].third_party]
    final = [t for t in oss if evals.task_split(t) == "final"]
    calibration = [t for t in oss if evals.task_split(t) == "calibration"]
    assert len(final) == 25 and len(final) + len(calibration) == len(oss)
    assert all(t.id.startswith("oss-") for t in final) and all(t.id.startswith("cal-") for t in calibration)
    import re
    commit = re.compile(r"commit ([0-9a-f]{40})")
    final_commits = {commit.search(t.attribution).group(1) for t in final}
    assert not final_commits & {commit.search(t.attribution).group(1) for t in calibration}
    assert not [t for t in evals.select_tasks(tasks, None, None, 0, "all") if bases[t.base].third_party]
    for name in {t.base for t in oss}:
        base_dir = evals.default_suite_dir() / "bases" / name
        assert any(p.name.upper().startswith("LICENSE") for p in base_dir.iterdir()), name
        assert bases[name].source.startswith("https://github.com/") and bases[name].license
    for t in oss:
        assert t.visible_after_hidden and "commit" in t.attribution
        assert not any(Path(g).name in t.prompt for g in t.gold_files)


def test_token_accounting_prefers_model_usage_and_separates_cache(tmp_path: Path):
    result = {"type": "result", "subtype": "success", "num_turns": 2, "total_cost_usd": 0.1,
              "usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 1000},
              "modelUsage": {"main": {"inputTokens": 100, "outputTokens": 10, "cacheReadInputTokens": 1000,
                                      "cacheCreationInputTokens": 50},
                             "sub": {"inputTokens": 30, "outputTokens": 5}}}
    m = evals.parse_stream([json.dumps(result)], tmp_path, [])
    assert m["token_source"] == "modelUsage" and m["models_used"] == ["main", "sub"]
    assert m["input_tokens"] == 100 + 30 + 1000 + 50 and m["output_tokens"] == 15
    assert m["cache_read_tokens"] == 1000 and m["cache_creation_tokens"] == 50 and m["uncached_input_tokens"] == 130
    assert m["main_model_input_tokens"] == 1100
    legacy = evals.parse_stream([json.dumps({**result, "modelUsage": None})], tmp_path, [])
    assert legacy["token_source"] == "usage" and legacy["input_tokens"] == 1100


def test_sealed_sets_are_reserved_and_the_analysed_one_is_labelled(tmp_path: Path):
    assert {"final", "calibration", "sealed-v2"} <= evals.RESERVED_SPLITS
    assert "final" in evals.ANALYZED_SPLITS and "sealed-v2" not in evals.ANALYZED_SPLITS
    proc = run_cli(None, "eval", "coding", "--split", "final", "--dry-run", "--max-cost-usd", "1",
                   "--claude-config", str(tmp_path / "cfg"))
    assert "not fresh confirmatory evidence" in proc.stderr


def test_regression_commands_handle_explicit_module_lists_cd_and_node():
    """sealed-v2 bases run an explicit module list (excluding modules that need
    unavailable dependencies), a `cd src && ...` form, or node: the regression
    check must run exactly those, never `discover` over everything."""
    def task(dests):
        return evals.Task(id="t", base="b", language="python", category="bugfix", difficulty="hard",
                          prompt="p", setup=[], solution=[], gold_files=[],
                          hidden=[{"src": f"hidden/{i}", "dest": d} for i, d in enumerate(dests)],
                          commands=[], timeout_s=60, attribution="", dir=Path("."), split="sealed-v2",
                          visible_after_hidden=True)

    def base(argv):
        return evals.Base(name="b", language="python", visible_tests=[argv], toolchain=["python"])
    cmd = evals.regression_commands(task(["tests/dialects/test_x.py"]),
                                    base(["{python}", "-m", "unittest", "tests.a", "tests.dialects.test_x"]))
    assert cmd[0][3:] == ["--names", ".", "tests.a", "tests.dialects.test_x", "--", "tests.dialects.test_x"]
    cmd = evals.regression_commands(task(["src/test_te.py"]),
                                    base(["sh", "-c", "cd src && python3 -m unittest test_te"]))
    assert cmd[0][3:] == ["--names", "src", "test_te", "--", "test_te"]
    cmd = evals.regression_commands(task(["test/unit/Hooks.test.js"]),
                                    base(["sh", "-c", "node --test test/unit/Lexer.test.js test/unit/Hooks.test.js"]))
    assert cmd == [["sh", "-c", "node --test test/unit/Lexer.test.js"]]
    old = evals.regression_commands(task(["tests/test_x.py"]),
                                    base(["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", "."]))
    assert old[0][3:] == ["tests", ".", "tests.test_x"]  # the analysed set's form is unchanged


def test_sealed_v2_is_complete_reserved_and_never_released():
    import hashlib
    root = Path(__file__).resolve().parent.parent
    suite = root / "benchmarks" / "sealed-v2"
    if not suite.is_dir():
        pytest.skip("the sealed-v2 set is not part of the public source export")
    bases, tasks = evals.load_suite(suite)
    assert len(tasks) == 25 and {t.split for t in tasks} == {"sealed-v2"}
    assert all(t.prompt and t.prompt != "TODO" and len(t.prompt.split()) >= 20 for t in tasks)
    assert all(bases[t.base].third_party for t in tasks)  # graded only in the sandbox
    assert not evals.select_tasks(tasks, None, None, 0, "all")  # never part of routine runs
    # answers and authoring notes stay out of the suite directory and out of release artifacts
    assert not list(suite.rglob("REVIEW.md")) and not list(suite.rglob("NOTES.md"))
    py = (root / "pyproject.toml").read_text()
    sdist = py.split("[tool.hatch.build.targets.sdist]")[1].split("\n[")[0]
    assert re.search(r'(?m)^exclude = .*"benchmarks/sealed-v2".*"benchmarks/authoring"', sdist)
    assert "sealed-v2" not in py.split("[tool.hatch.build.targets.wheel.force-include]")[1].split("\n[")[0]
    sched = json.loads((root / "benchmarks" / "preregistration" / "sealed-v2-schedule.json").read_text())
    assert hashlib.sha256(json.dumps(sched["schedule"], sort_keys=True).encode()).hexdigest() == \
        sched["schedule_sha256"]
    assert sched["schedule_sha256"] in (root / "docs" / "PREREGISTRATION-v2.md").read_text()


def test_sealed_v2_pairs_schedule_is_the_one_the_runner_produces():
    import hashlib

    from repo_ai import coding_lab as lab
    root = Path(__file__).resolve().parent.parent
    if not (root / "benchmarks" / "sealed-v2").is_dir():
        pytest.skip("the sealed-v2 set is not part of the public source export")
    bases, tasks = evals.load_suite(root / "benchmarks" / "sealed-v2")
    order = lab.interleave_by_base(evals.select_tasks(tasks, None, None, 0, "sealed-v2"), 0)
    sched = json.loads((root / "benchmarks" / "preregistration" / "sealed-v2-pairs-schedule.json").read_text())
    expected = lab.schedule(order, lab.make_arms(["baseline", "core"]), 1, 0)
    assert sched["schedule"] == expected and sched["tasks"] == [t.id for t in order]
    assert hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest() == sched["schedule_sha256"]
    assert sched["schedule_sha256"] in (root / "docs" / "EXPLORATORY-v2-pairs.md").read_text()
    assert len({t.base for t in order[:8]}) == 8  # every project before any project's second task
