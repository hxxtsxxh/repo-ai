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

from repo_ai.verify import cache, engine, strategy
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
@needs_sandbox
def test_an_edit_to_a_file_the_recorded_collection_leaves_out_is_named_untested(tmp_path: Path):
    root = _marshmallow_like(tmp_path)
    (root / OLD).write_text("from pkg.core import f\n\n\ndef test_old():\n    assert f() == 3\n")  # now fails alone
    out = _run(root, PY_CMD)
    ev, summary = out["evidence"], out["summary"]
    # what the project's own command runs is unchanged: the full suite, which passes without the file
    assert ev["full_suite"]["status"] == "pass" and OLD not in {r["test"] for r in ev["results"]}
    line = f"{OLD}: pytest's recorded collection never runs it; no test exercised this edit"
    assert ev["plan"]["uncertainty"][0] == line, ev["plan"]["uncertainty"]
    assert summary["untested_edits"] == [OLD]
    assert not any("test helper" in t for t in ev["plan"]["triggers"]), ev["plan"]["triggers"]
    text = run_cli(root, "verify", "--run", "--test-command", PY_CMD).stdout   # the reused record, as printed
    assert f"! {line}" in text, text
    assert text.index(f"! {line}") < text.index("evidence reused")


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
    decision = strategy.Decision("full", "the full suite (measured 1.0s as one process) is expected to be no slower")
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


def test_a_requested_full_suite_without_a_report_still_marks_it(tmp_path: Path, monkeypatch):
    """`--full` asked for it, but the fact learned (no usable report here) holds for later speed choices too."""
    timings = cache.Timings(tmp_path, "env")
    res = SimpleNamespace(exit_code=0, timed_out=False, stdout="", stderr="", duration_s=1.0, notes=[])
    monkeypatch.setattr(engine, "_process", lambda *a, **k: (res, None))
    monkeypatch.setattr(engine, "_run_batch", lambda ctx, b: [{"test": f, "status": "pass"} for f in b])
    monkeypatch.setattr(engine, "_row", lambda ctx, f, status, *a, **k: {"test": f, "status": status})
    p = SimpleNamespace(selected=[SimpleNamespace(test="tests/test_a.py")], universe_files=["tests/test_a.py"],
                        duplicates={}, full_suite_required=False)
    ctx = SimpleNamespace(p=p, runner=parse_command(PY_CMD), timings=timings, log=lambda m: None, timeout_s=60.0,
                          timeout_explicit=False, executor=None, durations={}, workers=2, deadline=None,
                          deadline_hit=False, full_reached_all=False)
    rec: dict = {}
    engine._run_full(ctx, rec, ["python", "-m", "pytest"], strategy.Decision("full", "--full was requested"))  # type: ignore[arg-type]
    assert timings.full_unusable
    assert "advisory" not in rec["full_suite"]          # a requested full suite is not advisory: it passed


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
