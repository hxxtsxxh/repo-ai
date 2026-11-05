"""Follow-ups from the #152 review (QUEUE row 36).

1. After `verify --record`, an edit to a file pytest's own recorded
   collection leaves out (marshmallow's `tests/mypy_test_cases` under
   `norecursedirs`) requires the full suite, which passes without the file
   ever running: the run must name that edit as untested.
2. A passing full suite without a trusted per-test report re-runs every
   selected file; the cost model must learn that it is no faster.
3. End to end: Node's unreached path, and the trusted-failing full path with
   an unreached file.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import run_cli

from repo_ai.verify import cache, engine, evidence, results, strategy
from repo_ai.verify.runner import parse_command

PY_CMD = "python -m pytest -q tests"
OLD = "tests/mypy_test_cases/test_old.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _sandbox() -> bool:
    import tempfile
    from repo_ai.sandbox import SandboxUnavailable
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        try:
            ex = get_executor(Path(d), "auto", "python")
            with isolate.materialize(Path(d)) as ws:
                return ex.in_workspace(ws).run(["python", "-c", "pass"], timeout_s=60).exit_code == 0
        except SandboxUnavailable:
            return False


needs_sandbox = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")


def _project(root: Path, files: dict[str, str], cmd: str, record: bool = True) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    if record:
        assert run_cli(root, "verify", "--record", "--test-command", cmd).returncode == 0
    return root


def _run(root: Path, cmd: str, *extra: str) -> dict:
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--workers", "2", "--test-command", cmd, *extra)
    assert proc.returncode in {0, 1}, proc.stderr[-800:]
    return json.loads(proc.stdout)


def _marshmallow_like(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    pytest.importorskip("pytest")
    files = {
        "pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = ".git docs tests/mypy_test_cases"\n',
        "pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n",
        "tests/test_ok.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
        "tests/test_two.py": "from pkg.core import f\n\n\ndef test_g():\n    assert f() + 1 == 2\n",
        # a case file for a type checker, matched by name, never collected by the project's pytest
        OLD: "from pkg.core import f\n\n\ndef test_old():\n    assert f() == 1\n",
        **(extra or {})}
    return _project(tmp_path / "m", files, PY_CMD)


# -- 1: an edit no test runs is named ----------------------------------------------
LINE = f"{OLD}: pytest's recorded collection never runs it; no test exercised this edit"


def _run_exit(root: Path, *extra: str) -> tuple[int, dict]:
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--workers", "2", "--test-command", PY_CMD, *extra)
    assert proc.returncode in {0, 1}, proc.stderr[-800:]
    return proc.returncode, json.loads(proc.stdout)


@needs_sandbox
def test_an_edit_only_to_a_file_no_test_runs_is_not_verified(tmp_path: Path):
    """Alone, such an edit is what any unlinked behavioural edit is: not verified, exit 1. It used to require the
    full suite, which passes without running the file, so the run said PASSED (#155 review)."""
    root = _marshmallow_like(tmp_path)
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 3\n")  # now fails alone
    code, out = _run_exit(root)
    ev, summary = out["evidence"], out["summary"]
    assert code == 1
    assert ev["verdict"] == evidence.NOT_VERIFIED_UNLINKED, ev["verdict"]
    assert ev["selected"] == [] and not ev["plan"]["full_suite_required"] and not ev["full_suite"]
    assert not any(OLD in t for t in ev["plan"]["triggers"]), ev["plan"]["triggers"]
    assert ev["plan"]["uncertainty"][0] == LINE, ev["plan"]["uncertainty"]
    assert summary["untested_edits"] == [OLD]
    shown = run_cli(root, "verify", "--run", "--test-command", PY_CMD)   # the reused record, as printed
    assert shown.returncode == 1 and shown.stdout.startswith("repo-ai verify"), shown.stdout
    assert "NOT VERIFIED" in shown.stdout and f"! {LINE}" in shown.stdout, shown.stdout
    assert "PASSED" not in shown.stdout
    later = run_cli(root, "evidence")
    assert "NOT VERIFIED" in later.stdout and "PASSED" not in later.stdout, later.stdout


@needs_sandbox
def test_next_to_a_tested_change_the_edit_no_test_runs_is_named_and_the_tests_decide(tmp_path: Path):
    root = _marshmallow_like(tmp_path)
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 3\n")
    (root / "pkg" / "core.py").write_text("def f():\n    return 0 + 1\n")   # behaviour kept, linked to two tests
    code, out = _run_exit(root)
    ev = out["evidence"]
    assert code == 0 and ev["verdict"] in evidence.PASSING_VERDICTS, ev["verdict"]
    assert sorted(ev["selected"]) == ["tests/test_ok.py", "tests/test_two.py"]
    assert ev["plan"]["uncertainty"][0] == LINE and out["summary"]["untested_edits"] == [OLD]
    assert not any(OLD in t for t in ev["plan"]["triggers"]), ev["plan"]["triggers"]
    shown = run_cli(root, "verify", "--run", "--test-command", PY_CMD).stdout
    assert shown.index(f"! {LINE}") < shown.index("evidence reused"), shown


@needs_sandbox
def test_an_untouched_excluded_file_or_a_comment_edit_is_not_named(tmp_path: Path):
    root = _marshmallow_like(tmp_path)
    (root / "pkg" / "core.py").write_text("def f():\n    return 1  # same\n")
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 1  # same\n")
    out = _run(root, PY_CMD)
    assert out["summary"]["untested_edits"] == []
    assert not any("never runs it" in u for u in out["evidence"]["plan"]["uncertainty"])


@needs_sandbox
def test_an_excluded_file_another_test_reads_is_linked_not_named(tmp_path: Path):
    """A case file a collected test opens (a type-checker test reading its cases) is exercised by that test."""
    reader = ("from pathlib import Path\n\n\ndef test_cases_parse():\n"
              f"    assert 'def test_old' in Path('{OLD}').read_text()\n")
    root = _marshmallow_like(tmp_path, {"tests/test_cases_read.py": reader})
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 3\n")
    out = _run(root, PY_CMD)
    assert out["summary"]["untested_edits"] == []
    assert "tests/test_cases_read.py" in out["evidence"]["selected"], out["evidence"]["selected"]


@needs_sandbox
def test_full_does_not_turn_an_edit_no_test_runs_into_a_pass(tmp_path: Path):
    """`--full` runs the project's suite, which never runs the edited file: still not verified, exit 1, with the
    full suite's own result shown (#155 final review)."""
    root = _marshmallow_like(tmp_path)
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 3\n")
    code, out = _run_exit(root, "--full")
    ev = out["evidence"]
    assert code == 1 and ev["full_suite"]["status"] == "pass"
    assert ev["verdict"] == evidence.NOT_VERIFIED_UNTESTED, ev["verdict"]
    assert out["summary"]["untested_edits"] == [OLD]
    shown = run_cli(root, "verify", "--run", "--full", "--test-command", PY_CMD)   # the reused record, as printed
    assert shown.returncode == 1 and "NOT VERIFIED" in shown.stdout and "PASSED" not in shown.stdout, shown.stdout
    assert "the full suite passed, without running the changed file(s)" in shown.stdout
    assert f"! {LINE}" in shown.stdout and "No test ran" not in shown.stdout


@needs_sandbox
def test_full_with_a_tested_change_next_to_it_still_passes(tmp_path: Path):
    root = _marshmallow_like(tmp_path)
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 3\n")
    (root / "pkg" / "core.py").write_text("def f():\n    return 0 + 1\n")
    code, out = _run_exit(root, "--full")
    ev = out["evidence"]
    assert code == 0 and ev["verdict"] == "selected-and-full-suite-passed", ev["verdict"]
    assert ev["plan"]["uncertainty"][0] == LINE and out["summary"]["untested_edits"] == [OLD]


def test_the_verdict_for_edits_no_run_executes():
    full_pass = {"status": "pass"}
    assert evidence.verdict([], full_pass, 0, False, untested_only=True) == evidence.NOT_VERIFIED_UNTESTED
    pre = [{"test": "tests/a.py", "status": "fail", "baseline": "fail", "shape": "full"}]
    assert evidence.verdict(pre, {"status": "fail", "attributed": True}, 0, False, untested_only=True) \
        == evidence.NOT_VERIFIED_UNTESTED                       # failing as at the base says nothing either
    new = [{"test": "tests/a.py", "status": "fail", "baseline": "pass", "shape": "full"}]
    assert evidence.verdict(new, full_pass, 0, False, untested_only=True) == "regression"   # a new failure stands
    # nothing ran at all: the unlinked rule, as before
    assert evidence.verdict([], None, 0, False, untested_only=True) == evidence.NOT_VERIFIED_UNLINKED
    # a docs change naming a test ran it; it does not run the edited file either
    docs = [{"test": "tests/a.py", "status": "pass"}]
    assert evidence.verdict(docs, None, 1, False, untested_only=True) == evidence.NOT_VERIFIED_UNTESTED
    # otherwise unchanged: an unlinked source edit under --full still passes (the suite may run that code)
    assert evidence.verdict([], full_pass, 0, False) == "selected-and-full-suite-passed"


def test_untested_only_needs_every_behavioural_file_to_be_untested():
    def plan(files, untested):
        return SimpleNamespace(untested_edits=untested, files=[SimpleNamespace(path=f, behavioral=b, kind=k)
                                                               for f, b, k in files])
    assert engine._untested_only(plan([(OLD, True, "test-helper")], [OLD]))
    assert engine._untested_only(plan([(OLD, True, "test-helper"), ("README.md", True, "docs"),
                                       ("pkg/core.py", False, "source")], [OLD]))   # docs, comment-only: ignored
    assert not engine._untested_only(plan([(OLD, True, "test-helper"), ("pkg/core.py", True, "source")], [OLD]))
    assert not engine._untested_only(plan([("pkg/core.py", True, "source")], []))
    assert not engine._untested_only(plan([], []))


# -- 2: an untrusted passing full suite is not chosen for speed again -------------------
def test_a_passing_full_suite_without_a_trusted_report_is_marked_unusable_for_speed(tmp_path: Path, monkeypatch):
    timings = cache.Timings(tmp_path, "env")
    res = SimpleNamespace(exit_code=0, timed_out=False, stdout="", stderr="", duration_s=1.0, notes=[])
    calls: list[list[str]] = []
    monkeypatch.setattr(engine, "_process", lambda *a, **k: (res, None))   # no per-test report
    monkeypatch.setattr(engine, "_run_batch", lambda ctx, b: calls.append(b) or [
        {"test": f, "status": "pass", "shape": "batch"} for f in b])
    monkeypatch.setattr(engine, "_row", lambda ctx, f, status, *a, **k: {"test": f, "status": status, "shape": "full"})
    runner = parse_command(PY_CMD)
    sel = ["tests/test_a.py", "tests/test_b.py"]
    p = SimpleNamespace(selected=[SimpleNamespace(test=t) for t in sel], universe_files=sel + ["tests/test_c.py"],
                        duplicates={}, full_suite_required=False)
    ctx = SimpleNamespace(p=p, runner=runner, timings=timings, log=lambda m: None, timeout_s=60.0,
                          timeout_explicit=False, executor=None, durations={}, workers=2, deadline=None,
                          deadline_hit=False, full_reached_all=False)
    rec: dict = {}
    decision = strategy.Decision("full", "the full suite (measured 1.0s as one process) is expected to be no slower",
                                 basis="compared")   # chosen for speed
    rows = engine._run_full(ctx, rec, ["python", "-m", "pytest"], decision)  # type: ignore[arg-type]
    assert sorted(sum(calls, [])) == sel and {r["test"] for r in rows} == set(sel)
    assert timings.full_unusable and "per-test report" in timings.full_unusable
    assert rec["full_suite"]["status"] == "pass" and rec["full_suite"]["reason"].startswith("not chosen for speed")
    again = strategy.decide(runner, sel, p.universe_files, {f: 0.3 for f in p.universe_files},
                            full_required=False, full_requested=False, workers=2, measured_full=0.1,
                            measured_startup=0.2, full_runnable=True, full_unusable=timings.full_unusable)
    assert again.kind == "targeted" and again.basis == "forced" and "cannot be attributed" in again.reason
    # a full suite the change requires still runs: the flag only stops choosing it for speed
    required = strategy.decide(runner, sel, p.universe_files, {}, full_required=True, full_requested=False,
                               workers=2, measured_full=None, measured_startup=None, full_runnable=True,
                               full_unusable=timings.full_unusable)
    assert required.kind == "full"


def _ctx(tmp_path: Path, universe: list[str], timings: cache.Timings) -> SimpleNamespace:
    p = SimpleNamespace(selected=[SimpleNamespace(test=t) for t in universe[:1]], universe_files=universe,
                        duplicates={}, full_suite_required=False)
    return SimpleNamespace(p=p, runner=parse_command(PY_CMD), timings=timings, log=lambda m: None, timeout_s=60.0,
                           timeout_explicit=False, executor=None, durations={}, workers=2, deadline=None,
                           deadline_hit=False, full_reached_all=False)


@pytest.mark.parametrize("reason", ["--full was requested",
                                    "the full suite is required for this change; it includes every selected test"])
def test_a_forced_full_suite_without_a_report_leaves_the_flag_alone(tmp_path: Path, monkeypatch, reason: str):
    """A run the change or `--full` forced says nothing about speed choices: nothing is marked."""
    timings = cache.Timings(tmp_path, "env")
    res = SimpleNamespace(exit_code=0, timed_out=False, stdout="", stderr="", duration_s=1.0, notes=[])
    monkeypatch.setattr(engine, "_process", lambda *a, **k: (res, None))
    monkeypatch.setattr(engine, "_run_batch", lambda ctx, b: [{"test": f, "status": "pass"} for f in b])
    monkeypatch.setattr(engine, "_row", lambda ctx, f, status, *a, **k: {"test": f, "status": status})
    rec: dict = {}
    ctx = _ctx(tmp_path, ["tests/test_a.py"], timings)
    rows = engine._run_full(ctx, rec, ["python", "-m", "pytest"], strategy.Decision("full", reason))  # type: ignore[arg-type]
    assert [r["test"] for r in rows] == ["tests/test_a.py"]          # still re-run on its own
    assert timings.full_unusable == "" and "reason" not in rec["full_suite"]
    assert "advisory" not in rec["full_suite"]


def test_a_later_trusted_full_pass_clears_the_flag(tmp_path: Path, monkeypatch):
    timings = cache.Timings(tmp_path, "env")
    timings.note_full_unusable("no per-test report was written")
    timings.save()
    res = SimpleNamespace(exit_code=0, timed_out=False, stdout="", stderr="", duration_s=1.0, notes=[])
    att = results.Attribution(trusted=True, done=True,
                              files={"tests/test_a.py": results.FileOutcome(tests=1, ran=1, seconds=0.2)})
    monkeypatch.setattr(engine, "_process", lambda *a, **k: (res, att))
    monkeypatch.setattr(engine, "_run_batch", lambda ctx, b: pytest.fail("nothing should run again"))
    monkeypatch.setattr(engine, "_row", lambda ctx, f, status, *a, **k: {"test": f, "status": status})
    ctx = _ctx(tmp_path, ["tests/test_a.py"], timings)
    engine._run_full(ctx, {}, ["python", "-m", "pytest"], strategy.Decision("full", "--full was requested"))  # type: ignore[arg-type]
    assert ctx.full_reached_all and timings.full_unusable == ""
    timings.save()
    assert cache.Timings(tmp_path, "env").full_unusable == ""


# -- 3: end to end ----------------------------------------------------------------
@needs_sandbox
def test_a_pre_existing_failure_elsewhere_does_not_hide_a_new_failing_unreached_file(tmp_path: Path):
    """The trusted-failing full path: the full suite fails (a test already failing at the base), and the new
    failing file it never collects is still run on its own and reported as a regression."""
    root = _marshmallow_like(tmp_path, {"tests/test_bad.py": "def test_bad():\n    assert 1 == 2\n"})
    new = "tests/mypy_test_cases/test_new.py"
    (root / new).write_text("from pkg.core import f\n\n\ndef test_new():\n    assert f() == 2\n")
    ev = _run(root, PY_CMD, "--full")["evidence"]
    assert ev["full_suite"]["status"] == "fail" and ev["full_suite"]["attributed"], ev["full_suite"]
    assert ev["full_suite"]["not_reached"] == [new]
    rows = {r["test"]: r for r in ev["results"]}
    assert rows[new]["status"] == "fail" and rows[new]["not_reached_by_full_suite"]
    assert rows["tests/test_bad.py"]["baseline"] == "fail"
    assert ev["verdict"] == "regression", ev["verdict"]


def _node_sandbox() -> bool:
    import shutil
    if not shutil.which("node"):
        return False
    try:
        from test_verify_adaptive import NODE_SANDBOX
    except Exception:  # noqa: BLE001
        return False
    return bool(NODE_SANDBOX)


@pytest.mark.skipif(not _node_sandbox(), reason="no node in the sandbox")
def test_node_a_selected_file_the_full_run_never_finishes_is_run_on_its_own(tmp_path: Path):
    """`node --test` with no paths uses node's own globs, which skip dot-directories; repo-ai's name match does
    not, so a new failing file under `test/.cases/` is selected, never run by the full suite, and run alone."""
    files = {"package.json": '{"name": "p", "type": "module", "scripts": {"test": "node --test"}}\n',
             "src/core.mjs": "export const f = () => 1;\n",
             "test/a.test.mjs": 'import test from "node:test";\nimport assert from "node:assert";\n'
                                'import { f } from "../src/core.mjs";\ntest("a", () => assert.equal(f(), 1));\n'}
    root = _project(tmp_path / "n", files, "node --test", record=False)
    new = "test/.cases/h.test.mjs"
    (root / new).parent.mkdir(parents=True)
    (root / new).write_text('import test from "node:test";\nimport assert from "node:assert";\n'
                            'import { f } from "../../src/core.mjs";\ntest("h", () => assert.equal(f(), 2));\n')
    targeted = _run(root, "node --test")["evidence"]
    assert targeted["verdict"] == "regression", targeted["verdict"]
    ev = _run(root, "node --test", "--full")["evidence"]
    assert ev["full_suite"]["status"] == "pass" and ev["full_suite"]["not_reached"] == [new], ev["full_suite"]
    row = next(r for r in ev["results"] if r["test"] == new)
    assert row["status"] == "fail" and row["not_reached_by_full_suite"]
    assert ev["verdict"] == "regression", ev["verdict"]
