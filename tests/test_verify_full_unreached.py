"""A selected test file the full suite never reached is run on its own, never
passed by the full suite's exit status.

Found reviewing C16 (#152), and older than it: a project whose own test
command leaves a directory out (pytest's `norecursedirs`, a unittest package
whose `load_tests` hides a module) got `selected-and-full-suite-passed` for a
NEW failing test file there whenever the full suite ran (`--full`, the tie
rule, a remembered full suite), because the full suite's report is pre-filled
with an empty outcome for every test file and an empty outcome read as
"defines no test". The selection alone reported `regression`.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import run_cli

from repo_ai.verify import cache, engine, evidence, results

PY_CMD = "python -m pytest -q tests"
UT_CMD = "python -m unittest discover -s tests -t ."
FAILING_NEW = "from pkg.core import f\n\n\ndef test_new():\n    assert f() == 2\n"


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
    return json.loads(proc.stdout)["evidence"]


def _pytest_project(tmp_path: Path, extra: dict[str, str] | None = None, record: bool = True) -> Path:
    pytest.importorskip("pytest")
    files = {
        "pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = ".git docs tests/mypy_test_cases"\n',
        "pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n\n\ndef g():\n    return 1\n",
        "tests/test_ok.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
        "tests/test_two.py": "from pkg.core import f\n\n\ndef test_g():\n    assert f() + 1 == 2\n",
        **(extra or {})}
    return _project(tmp_path / "p", files, PY_CMD, record)


def _row(ev: dict, test: str) -> dict:
    return next(r for r in ev["results"] if r["test"] == test)


NEW = "tests/mypy_test_cases/test_new.py"


@needs_sandbox
def test_a_new_failing_file_the_full_suite_does_not_collect_is_a_regression_with_full(tmp_path: Path):
    root = _pytest_project(tmp_path)
    (root / NEW).parent.mkdir(parents=True)
    (root / NEW).write_text(FAILING_NEW)
    assert _run(root, PY_CMD)["verdict"] == "regression"            # the selection alone: as before
    ev = _run(root, PY_CMD, "--full")
    assert ev["strategy"]["kind"] == "full" and ev["full_suite"]["status"] == "pass"
    assert ev["verdict"] == "regression", ev["verdict"]             # was selected-and-full-suite-passed
    row = _row(ev, NEW)
    assert row["status"] == "fail" and row["not_reached_by_full_suite"] and row["shape"] != "full"
    assert ev["full_suite"]["not_reached"] == [NEW]


@needs_sandbox
def test_a_remembered_full_suite_runs_the_uncollected_file_too_and_is_then_forgotten(tmp_path: Path):
    root = _pytest_project(tmp_path)
    (root / NEW).parent.mkdir(parents=True)
    (root / NEW).write_text(FAILING_NEW)
    first = _run(root, PY_CMD)
    env = first["environment"]
    path = root / ".repo-ai" / "state" / cache.TIMINGS_FILE

    def edit(full: float, kind: str | None) -> None:
        data = json.loads(path.read_text())
        e = data["envs"][env]
        e["full"] = full
        e.setdefault("files", {})[NEW] = 0.3
        e.pop("full_unusable", None)
        if kind:
            e["choices"] = {k: {"k": kind, "n": 1} for k in e.get("choices") or {}}
        path.write_text(json.dumps(data))

    edit(5.0, None)
    measured = _run(root, PY_CMD)                                 # the selection, remembered under its key
    assert measured["strategy"]["basis"] == "compared" and measured["strategy"]["kind"] == "targeted"
    est_t = measured["strategy"]["est_targeted_s"]
    edit(round(est_t + 0.4, 3), "full")                           # the rule alone would run the selection
    ev = _run(root, PY_CMD)
    assert ev["strategy"]["basis"] == "kept" and ev["strategy"]["kind"] == "full", ev["strategy"]
    assert ev["verdict"] == "regression", ev["verdict"]
    assert _row(ev, NEW)["not_reached_by_full_suite"]
    choices = json.loads(path.read_text())["envs"][env].get("choices") or {}
    assert all(v.get("k") != "full" for v in choices.values()), choices   # not remembered again


@needs_sandbox
def test_an_existing_file_the_full_suite_does_not_collect_is_compared_not_left_unverified(tmp_path: Path):
    old = "tests/mypy_test_cases/test_old.py"
    # without --record the file is a test by its name (after one, the recorded collection leaves it out and an
    # edit to it counts as a helper change that requires the full suite); it passed at the base
    root = _pytest_project(tmp_path, {old: "from pkg.core import g\n\n\ndef test_old():\n    assert g() == 1\n"},
                           record=False)
    (root / old).write_text("from pkg.core import g\n\n\ndef test_old():\n    assert g() == 3\n")
    ev = _run(root, PY_CMD, "--full")
    assert ev["full_suite"]["status"] == "pass"
    row = _row(ev, old)
    assert row["status"] == "fail" and row["not_reached_by_full_suite"]
    assert ev["verdict"] == "regression", ev["verdict"]             # was not verified (defines no test)


@needs_sandbox
def test_a_unittest_module_discovery_does_not_load_is_run_on_its_own(tmp_path: Path):
    """unittest shares the pre-filled report: a package whose `load_tests` returns nothing hides its modules
    from discovery, while the selection runs them by name."""
    files = {
        "pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n", "tests/__init__.py": "",
        "tests/test_ok.py": "import unittest\nfrom pkg.core import f\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_f(self):\n        self.assertEqual(f(), 1)\n"}
    root = _project(tmp_path / "u", files, UT_CMD)
    hidden = root / "tests" / "hidden"
    hidden.mkdir()
    (hidden / "__init__.py").write_text(
        "import unittest\n\n\ndef load_tests(loader, standard_tests, pattern):\n    return unittest.TestSuite()\n")
    (hidden / "test_new.py").write_text("import unittest\nfrom pkg.core import f\n\n\nclass T(unittest.TestCase):\n"
                                        "    def test_new(self):\n        self.assertEqual(f(), 2)\n")
    ev = _run(root, UT_CMD, "--full")
    assert ev["full_suite"]["status"] == "pass"
    assert ev["verdict"] == "regression", ev["verdict"]             # was selected-and-full-suite-passed
    assert _row(ev, "tests/hidden/test_new.py")["not_reached_by_full_suite"]


# -- the decision of what was reached, and when the extra run cannot happen -----------
def test_only_files_with_no_sign_of_being_run_are_unreached():
    att = results.Attribution(trusted=True, done=True, files={
        "a": results.FileOutcome(tests=1, ran=1),                   # ran a test
        "b": results.FileOutcome(),                                 # pre-filled, nothing else: unreached
        "c": results.FileOutcome(),                                 # collected by pytest, defines none
        "d": results.FileOutcome(status="fail", failing={"<file>": "ImportError"}),  # failed to load
        "e": results.FileOutcome(),                                 # node: its child process finished
        "f": results.FileOutcome(),                                 # ids collected before the run
    })
    att.modules.add("c")
    att.finished.add("e")
    att.collected["f"] = {"f::t"}
    assert engine.unreached(att, ["a", "b", "c", "d", "e", "f", "g"]) == ["b", "g"]


def _stub_ctx(per_file: bool, deadline: float | None) -> SimpleNamespace:
    return SimpleNamespace(runner=SimpleNamespace(per_file=per_file), deadline=deadline, deadline_hit=False,
                           log=lambda _m: None)


@pytest.mark.parametrize("per_file,deadline", [(True, "spent"), (False, None)])
def test_when_the_unreached_files_cannot_run_alone_the_verdict_is_not_verified(per_file, deadline):
    rows = [{"test": "tests/a.py", "status": "pass", "shape": "full"},
            {"test": "tests/x/b.py", "status": "no-tests", "shape": "full"}]
    rec: dict = {"full_suite": {"status": "pass"}, "execution": ""}
    ctx = _stub_ctx(per_file, time.monotonic() - 1 if deadline else None)
    out = engine._run_unreached(ctx, rec, rows, ["tests/x/b.py"], "")  # type: ignore[arg-type]
    b = next(r for r in out if r["test"] == "tests/x/b.py")
    assert "not run by the full suite" in b["not_reached"] and "not_reached" not in out[0]
    assert rec["full_suite"]["not_reached"] == ["tests/x/b.py"]
    assert ctx.deadline_hit is bool(deadline)
    v = evidence.verdict(out, rec["full_suite"], 2, False)
    assert v.startswith("not verified: 1 selected test file(s) were not run by the full suite"), v
    assert v != "selected-and-full-suite-passed"


def test_a_not_reached_file_outranks_pre_existing_failures_but_not_a_regression():
    pre = {"test": "tests/a.py", "status": "fail", "baseline": "fail", "shape": "full"}
    gap = {"test": "tests/x/b.py", "status": "no-tests", "not_reached": "not run by the full suite (...)"}
    full = {"status": "fail", "attributed": True}
    assert evidence.verdict([pre, gap], full, 2, False).startswith("not verified: 1 selected")
    new = {"test": "tests/c.py", "status": "fail", "baseline": "pass", "shape": "full"}
    assert evidence.verdict([pre, gap, new], full, 3, False) == "regression"


@pytest.mark.parametrize("envs", [[1], "x", None, 3])
def test_a_timings_file_whose_environments_are_not_a_mapping_is_ignored(tmp_path: Path, envs):
    (tmp_path / cache.TIMINGS_FILE).write_text(json.dumps({"version": 1, "envs": envs}))
    t = cache.Timings(tmp_path, "e")
    assert t.full_s is None and t.choice("k") is None
    t.note_full(1.0)
    t.save()
    assert cache.Timings(tmp_path, "e").full_s == 1.0


def test_a_damaged_environment_entry_does_not_break_saving(tmp_path: Path):
    envs = {f"k{i}": ("x" if i % 2 else {"t": "x"}) for i in range(cache.MAX_TIMING_ENVS + 2)}
    (tmp_path / cache.TIMINGS_FILE).write_text(json.dumps({"version": 1, "envs": envs}))
    t = cache.Timings(tmp_path, "e")
    t.note_full(1.0)
    t.save()
    assert len(json.loads((tmp_path / cache.TIMINGS_FILE).read_text())["envs"]) == cache.MAX_TIMING_ENVS
