"""The per-test progress watchdog (docs/VERIFY-WATCHDOG.md): a hung test ends
its run after a budget derived from measured times instead of the whole
limit, is reported as the test that did not finish, and is never a pass; a
legitimately slow test is not cut; without measurements or with an explicit
`--timeout` nothing changes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import run_cli

from repo_ai.verify import watchdog


# -- the reader (no sandbox) --------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _watch(tmp_path: Path, budgets: dict, start=None, cap=60.0):
    run = tmp_path / "ws" / ".repo-ai" / "run"
    run.mkdir(parents=True)
    clock = Clock()
    w = watchdog.Watch(run / "outcomes.jsonl", str(tmp_path / "ws"), budgets, start, cap, clock=clock)
    return w, run / "outcomes.jsonl", clock


def _emit(report: Path, **ev) -> None:
    with report.open("a") as fh:
        fh.write(json.dumps(ev) + "\n")


def test_a_stall_is_reported_only_after_the_open_tests_budget(tmp_path: Path):
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": 7.0})
    path = str(tmp_path / "ws" / "tests" / "test_a.py")
    _emit(report, e="start", id="t1", path=path)
    assert w() == ""
    clock.t += 6.9
    assert w() == ""
    clock.t += 0.2
    assert "budget 7s" in w() and "tests/test_a.py" in w()


def test_any_event_resets_the_clock(tmp_path: Path):
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": 7.0})
    path = str(tmp_path / "ws" / "tests" / "test_a.py")
    for i in range(5):
        _emit(report, e="start", id=f"t{i}", path=path)
        clock.t += 5.0
        assert w() == ""
        _emit(report, e="end", id=f"t{i}", path=path, o="pass")
        clock.t += 1.0
        assert w() == ""


def test_an_unmeasured_file_never_triggers_it(tmp_path: Path):
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": None})
    _emit(report, e="start", id="t1", path=str(tmp_path / "ws" / "tests" / "test_a.py"))
    clock.t += 1000
    assert w() == ""  # the hard limit applies


def test_before_the_first_event_only_a_measured_start_up_counts(tmp_path: Path):
    w, _, clock = _watch(tmp_path, {"tests/test_a.py": 7.0}, start=None)
    clock.t += 1000
    assert w() == ""
    w2, report2, clock2 = _watch(tmp_path / "b", {"tests/test_a.py": 7.0}, start=9.0)
    clock2.t += 100
    assert w2() == ""  # no report yet (a container still starting): only the hard limit
    report2.write_text("")  # the reporter has started: the start-up budget counts from here
    assert w2() == ""
    clock2.t += 9.5
    assert "budget 9s" in w2()


def test_between_tests_the_largest_budget_applies_and_only_if_all_are_known(tmp_path: Path):
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": 7.0, "tests/test_b.py": 20.0})
    path = str(tmp_path / "ws" / "tests" / "test_a.py")
    _emit(report, e="start", id="t1", path=path)
    _emit(report, e="end", id="t1", path=path, o="pass")
    assert w() == ""
    clock.t += 19
    assert w() == ""  # a setUpClass of test_b may take up to its budget
    clock.t += 2
    assert "budget 20s" in w()
    w2, report2, clock2 = _watch(tmp_path / "c", {"tests/test_a.py": 7.0, "tests/test_b.py": None})
    _emit(report2, e="end", id="t1", path=path, o="pass")
    w2()
    clock2.t += 1000
    assert w2() == ""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and FIFOs")
@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_a_report_replaced_by_something_else_stops_the_watch(tmp_path: Path, kind: str):
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": 7.0}, start=1.0)
    if kind == "symlink":
        other = tmp_path / "other.jsonl"
        other.write_text("")
        report.symlink_to(other)
    else:
        os.mkfifo(report)
    clock.t += 1000
    assert w() == "" and w.broken  # the hard limit applies; the watchdog never blocks or follows it


def test_budgets_have_a_floor_and_never_exceed_the_limit():
    assert watchdog.budget(0.1, 60) == watchdog.FLOOR_S
    assert watchdog.budget(10.0, 60) == 32.0
    assert watchdog.budget(100.0, 60) == 60
    assert watchdog.budget(None, 60) is None


def test_the_start_budget_grows_with_what_the_process_collects():
    """Before its first event a process imports and collects every file it was
    given: a 300-file full suite must not get the start-up budget of a 3-file
    batch (a slow collection would be cut as a hang)."""
    from types import SimpleNamespace
    from repo_ai.verify import engine
    files = [f"tests/test_{i}.py" for i in range(300)]
    ctx = SimpleNamespace(runner=SimpleNamespace(kind="pytest"), timeout_explicit=False,
                          watch_s={f: 0.3 for f in files})
    w = engine._watch(ctx, Path("/nonexistent/run/outcomes.jsonl"), "/ws", files, 600.0)
    assert w is not None and w.start_budget is not None and w.start_budget >= 3 * 0.3 * 300, w.start_budget
    ctx.watch_s[files[0]] = None  # an unmeasured file: no start budget at all
    assert engine._watch(ctx, Path("/nonexistent/run/outcomes.jsonl"), "/ws", files, 600.0).start_budget is None


def test_base_and_confirmation_runs_keep_the_hard_limit():
    """Budgets are learned from the change's code: a base run cut by one would
    read as failing at the base and could make a new failure look pre-existing."""
    from types import SimpleNamespace
    from repo_ai.verify import engine
    ctx = SimpleNamespace(runner=SimpleNamespace(kind="unittest"), timeout_explicit=False,
                          watch_s={"tests/test_a.py": 1.0})
    report = Path("/nonexistent/run/outcomes.jsonl")
    assert engine._watch(ctx, report, "/ws", ["tests/test_a.py"], 60.0, "file") is not None
    for phase in ("base", "confirm"):
        assert engine._watch(ctx, report, "/ws", ["tests/test_a.py"], 60.0, phase) is None


def test_a_batch_share_never_sets_a_files_watchdog_budget(tmp_path: Path):
    """A session fixture paid by the first file of a batch made the other files'
    shares small; a later batch where one of them came first was cut."""
    from repo_ai.verify import cache
    t = cache.Timings(tmp_path, "env")
    t.note_file("tests/test_b.py", 2.0, own_process=False)
    assert t.peak_s("tests/test_b.py") is None and t.file_s("tests/test_b.py") == 2.0
    t.note_file("tests/test_b.py", 21.0)
    t.note_file("tests/test_b.py", 2.0, own_process=False)
    assert t.peak_s("tests/test_b.py") == 21.0


def test_a_report_too_large_to_follow_stops_the_watch_instead_of_tripping_it(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watchdog, "MAX_READ", 4096)
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": 7.0}, start=7.0)
    path = str(tmp_path / "ws" / "tests" / "test_a.py")
    for i in range(200):  # healthy: an event every 0.5 s, well past the cap
        _emit(report, e="start", id=f"t{i}", path=path)
        _emit(report, e="end", id=f"t{i}", path=path, o="pass")
        clock.t += 0.5
        assert w() == "", i
    assert w.broken


def test_forged_events_only_delay_until_the_hard_limit(tmp_path: Path):
    """A test that keeps writing events while it hangs only gets the hard
    limit (the watchdog is never the reason a run lasts longer); one that
    floods start events or a giant line stops the watch."""
    w, report, clock = _watch(tmp_path, {"tests/test_a.py": 7.0})
    path = str(tmp_path / "ws" / "tests" / "test_a.py")
    with report.open("a") as fh:
        for i in range(watchdog.MAX_OPEN + 1):
            fh.write(json.dumps({"e": "start", "id": f"x{i}", "path": path}) + "\n")
    assert [w() for _ in range(4)] == [""] * 4 and w.broken  # read at most 1 MiB per poll
    w2, report2, _ = _watch(tmp_path / "b", {"tests/test_a.py": 7.0})
    report2.write_text("[" * 100_000 + "\n" + "{" * (watchdog.MAX_LINE + 1))
    assert w2() == "" and w2.broken


def test_node_and_opaque_runners_keep_the_hard_limit():
    """Phase 1 covers unittest and pytest only: a node run, an opaque runner and an explicit
    `--timeout` never get a watchdog, whatever was measured."""
    from types import SimpleNamespace
    from repo_ai.verify import engine
    report = Path("/nonexistent/run/outcomes.jsonl")
    for kind in ("node", "jest", "vitest", "mocha", "custom", ""):
        ctx = SimpleNamespace(runner=SimpleNamespace(kind=kind), timeout_explicit=False,
                              watch_s={"tests/a.test.js": 1.0})
        assert engine._watch(ctx, report, "/ws", ["tests/a.test.js"], 60.0, "file") is None, kind
    ctx = SimpleNamespace(runner=SimpleNamespace(kind="pytest"), timeout_explicit=True,
                          watch_s={"tests/test_a.py": 1.0})
    assert engine._watch(ctx, report, "/ws", ["tests/test_a.py"], 60.0, "file") is None
    assert engine._watch(None, None, "/ws", [], 60.0, "file") is None  # no report: nothing to watch


def test_windows_paths_map_to_budgets_case_insensitively(tmp_path: Path, monkeypatch):
    """On Windows the reported path may use backslashes and another case; it still maps to the
    file's budget, and a path outside the workspace maps to none (the hard limit)."""
    w, _, _ = _watch(tmp_path, {"tests/test_a.py": 7.0})
    w.prefix = "C:\\ws\\"
    monkeypatch.setattr(watchdog.os, "name", "nt")
    assert w._file("C:\\WS\\Tests\\test_A.py", "") == "tests/test_a.py"
    assert w._file("C:\\other\\tests\\test_a.py", "") == ""


def test_a_fixture_torn_down_in_a_later_files_test_gets_the_earlier_files_budget(tmp_path: Path):
    """pytest tears a session or package fixture down in the last test that uses its scope, which can
    belong to a fast file: the open test gets the largest budget of the files already reported, and
    none (the hard limit) when one of them is unmeasured."""
    a, b = str(tmp_path / "ws" / "tests" / "test_api.py"), str(tmp_path / "ws" / "tests" / "test_util.py")
    w, report, clock = _watch(tmp_path, {"tests/test_api.py": 30.0, "tests/test_util.py": 5.0})
    _emit(report, e="start", id="tests/test_api.py::t", path=a)
    _emit(report, e="end", id="tests/test_api.py::t", path=a, o="pass")
    _emit(report, e="start", id="tests/test_util.py::u", path=b)
    assert w() == ""
    clock.t += 10  # the session fixture of test_api is being torn down inside test_util's last test
    assert w() == ""
    clock.t += 21
    assert "budget 30s" in w()

    (tmp_path / "ws").rename(tmp_path / "ws-old")
    w, report, clock = _watch(tmp_path, {"tests/test_api.py": None, "tests/test_util.py": 5.0})
    _emit(report, e="start", id="tests/test_api.py::t", path=a)
    _emit(report, e="end", id="tests/test_api.py::t", path=a, o="pass")
    _emit(report, e="start", id="tests/test_util.py::u", path=b)
    clock.t += 100
    assert w() == ""  # an unmeasured file was seen: only the hard limit applies


def test_a_run_that_skipped_most_tests_never_sets_the_peak(monkeypatch):
    """A file skipped for a while would otherwise decay its peak (0.8 per run) toward a skipped run's
    time, and its budget toward the floor, cutting it once its tests run again."""
    from types import SimpleNamespace
    from repo_ai.verify import engine
    from repo_ai.verify.cache import Timings
    timings = Timings.__new__(Timings)
    timings.env, timings.dirty = {}, False
    res = SimpleNamespace(exit_code=0, timed_out=False, stdout="", stderr="", duration_s=0.2, notes=[])
    monkeypatch.setattr(engine, "_process", lambda *a, **k: (res, None))
    monkeypatch.setattr(engine, "_limit", lambda *a, **k: 60.0)
    monkeypatch.setattr(engine, "_empty", lambda *a, **k: False)
    monkeypatch.setattr(engine, "_row", lambda *a, **k: {})
    ctx = SimpleNamespace(runner=SimpleNamespace(file_argv=lambda t: ["x", t]), timings=timings, log=lambda m: None,
                          executor=None,
                          skips={"tests/test_slow.py": (10, 9)})
    engine._run_file(ctx, "tests/test_slow.py")
    assert timings.peak_s("tests/test_slow.py") is None and timings.file_s("tests/test_slow.py")
    ctx.skips["tests/test_slow.py"] = (10, 0)
    engine._run_file(ctx, "tests/test_slow.py")
    assert timings.peak_s("tests/test_slow.py") == 0.2


def test_an_inherited_pytest_test_counts_against_the_file_that_collected_it(tmp_path: Path):
    w, report, clock = _watch(tmp_path, {"tests/test_base.py": 5.0, "tests/test_child.py": 30.0})
    _emit(report, e="start", id="tests/test_child.py::TestChild::test_x",
          path=str(tmp_path / "ws" / "tests" / "test_base.py"))  # pytest's location: where it is defined
    clock.t += 10
    assert w() == ""  # the child's budget, not the base file's


# -- end to end, sandboxed ------------------------------------------------------
from test_verify_adaptive import _sandbox  # noqa: E402

needs_sandbox = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


BASE = {"calc/__init__.py": "", "calc/core.py": "import time\n\n\ndef wait(s=0.0):\n    time.sleep(s)\n    return 1\n\n\n"
                                                 "def add(a, b):\n    return a + b\n",
        "tests/__init__.py": "",
        "tests/test_a_add.py": ("import unittest\nfrom calc.core import add\n\n\nclass A(unittest.TestCase):\n"
                                "    def test_add(self):\n        self.assertEqual(add(1, 1), 2)\n"),
        "tests/test_b_wait.py": ("import unittest\nfrom calc.core import wait\n\n\nclass W(unittest.TestCase):\n"
                                 "    def test_wait(self):\n        self.assertEqual(wait(), 1)\n"),
        "tests/test_c_slow.py": ("import unittest\nfrom calc.core import wait\n\n\nclass S(unittest.TestCase):\n"
                                 "    def test_slow(self):\n        self.assertEqual(wait(1.0), 1)\n")}
CMD = "python -m unittest discover -s tests -t ."


def _project(tmp_path: Path, files: dict[str, str] = BASE, cmd: str = CMD) -> Path:
    root = tmp_path / "p"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    assert run_cli(root, "verify", "--record", "--test-command", cmd).returncode == 0  # measured times
    return root


def _run(root: Path, *extra: str, cmd: str = CMD) -> tuple[dict, float]:
    t = time.monotonic()
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", cmd, *extra)
    took = time.monotonic() - t
    assert proc.returncode in (0, 1), proc.stderr[-800:]
    return json.loads(proc.stdout)["evidence"], took


@needs_sandbox
def test_a_hung_test_ends_its_run_early_and_is_reported_not_passed(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text(BASE["calc/core.py"].replace("time.sleep(s)", "time.sleep(1000 + s)"))
    ev, took = _run(root)
    rows = {r["test"]: r for r in ev["results"]}
    hung = [t for t, r in rows.items() if r["status"] == "timeout"]
    assert "tests/test_b_wait.py" in hung, rows
    assert any("no test started or finished" in m for m in rows["tests/test_b_wait.py"]["failures"].values()), rows
    assert ev["verdict"] == "regression"
    assert took < 30, took  # the old floor alone was 30 s per hanging process


@needs_sandbox
def test_a_slow_but_legitimate_test_is_not_cut(tmp_path: Path):
    root = _project(tmp_path)
    # three times slower than measured, still well inside its budget (3 x peak + 2 s)
    (root / "calc" / "core.py").write_text(BASE["calc/core.py"].replace("time.sleep(s)", "time.sleep(s * 3)"))
    ev, _ = _run(root)
    assert not [r for r in ev["results"] if r["status"] == "timeout"], ev["results"]


@needs_sandbox
def test_a_hang_in_set_up_class_is_cut_between_tests(tmp_path: Path):
    files = dict(BASE)
    files["tests/test_b_wait.py"] = ("import unittest\nfrom calc.core import wait\n\n\nclass W(unittest.TestCase):\n"
                                     "    @classmethod\n    def setUpClass(cls):\n        wait()\n\n"
                                     "    def test_wait(self):\n        self.assertTrue(True)\n")
    root = _project(tmp_path, files)
    (root / "calc" / "core.py").write_text(BASE["calc/core.py"].replace("time.sleep(s)", "time.sleep(1000 + s)"))
    ev, took = _run(root)
    rows = {r["test"]: r for r in ev["results"]}
    assert rows["tests/test_b_wait.py"]["status"] in {"timeout", "fail"}, rows
    assert not ev["verdict"].startswith(("selected-", "nothing")), ev["verdict"]
    assert took < 40, took


def _sandbox_imports(module: str) -> bool:
    """Whether the sandbox's interpreter can import `module` (a container image
    such as python:3.12-slim has no pytest)."""
    import tempfile
    from repo_ai.sandbox import SandboxUnavailable
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        try:
            ex = get_executor(Path(d), "auto", "python")
            with isolate.materialize(Path(d)) as ws:
                return ex.in_workspace(ws).run(["python", "-c", f"import {module}"], timeout_s=60).exit_code == 0
        except SandboxUnavailable:
            return False


@needs_sandbox
@pytest.mark.skipif(not _sandbox_imports("pytest"), reason="pytest is not installed in the sandbox")
def test_pytest_busy_spin_is_cut(tmp_path: Path):
    files = {"calc/__init__.py": "", "calc/core.py": "def spin(n=0):\n    return n\n",
             "tests/test_a.py": "from calc.core import spin\n\n\ndef test_a():\n    assert spin() == 0\n",
             "tests/test_b.py": "def test_b():\n    assert True\n"}
    cmd = "python -m pytest -q tests"
    root = _project(tmp_path, files, cmd)
    (root / "calc" / "core.py").write_text("def spin(n=0):\n    while True:\n        n += 1\n")
    ev, took = _run(root, cmd=cmd)
    rows = {r["test"]: r for r in ev["results"]}
    assert rows["tests/test_a.py"]["status"] == "timeout", rows
    assert ev["verdict"] == "regression" and took < 30, (ev["verdict"], took)


@needs_sandbox
def test_an_explicit_timeout_turns_the_watchdog_off(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text(BASE["calc/core.py"].replace("time.sleep(s)", "time.sleep(1000 + s)"))
    ev, took = _run(root, "--timeout", "12")
    rows = {r["test"]: r for r in ev["results"]}
    assert rows["tests/test_b_wait.py"]["status"] == "timeout"
    assert not any("no test started or finished" in m for m in rows["tests/test_b_wait.py"]["failures"].values())
    assert took >= 12, took


@needs_sandbox
def test_a_hang_already_present_at_the_base_is_pre_existing(tmp_path: Path):
    """The base run gets the same watchdog: a file that hangs at the base too
    is not reported as a new failure."""
    files = dict(BASE)
    files["tests/test_d_hang.py"] = ("import time\nimport unittest\nfrom calc.core import add\n\n\n"
                                     "class H(unittest.TestCase):\n    def test_hang(self):\n"
                                     "        if add(0, 0) == 0 and __import__('os').path.exists('HANG'):\n"
                                     "            time.sleep(1000)\n")
    root = _project(tmp_path, files)
    (root / "HANG").write_text("")  # committed below: the file hangs at the base revision as well
    _git(root, "add", "HANG")
    _git(root, "commit", "-qm", "the hang is part of the base")
    (root / "calc" / "core.py").write_text(BASE["calc/core.py"].replace("return a + b", "return b + a"))
    ev, took = _run(root, "--full")
    rows = {r["test"]: r for r in ev["results"]}
    assert rows.get("tests/test_d_hang.py", {}).get("status") == "timeout", rows
    assert ev["verdict"] != "regression", (ev["verdict"], rows["tests/test_d_hang.py"].get("classification"))
