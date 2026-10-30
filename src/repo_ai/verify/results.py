"""Per-test outcomes from structured runner output, and when to trust them.

Each sandboxed test process can be wrapped so it reports every test's
outcome as it happens (``rai_result.py`` for unittest and pytest,
``rai_reporter.mjs`` for ``node --test``). From that report one process can
stand for many test files: which files passed, which tests failed, which test
was still running when a timeout hit. That replaces re-running a failing batch
file by file.

The report is written by the process under test, so it is read as untrusted
data: bounded in size, every field type-checked, and **trusted only when it
agrees with the process itself**: the run finished (not killed), the report
is complete, its failures agree with the exit code, and every failure maps
to a test file the process was asked to run. Anything else returns an
untrusted attribution, and the engine falls back to running files one by
one, exactly as without this module.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .runner import TestRunner

RESULT_SHIM = Path(__file__).with_name("rai_result.py")
NODE_REPORTER = Path(__file__).with_name("rai_reporter.mjs")
RUN_DIR = ".repo-ai/run"
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 400_000
_SUBTESTS_FAILED = re.compile(r"^\d+ subtests? failed$")
_TOO_LARGE = "the per-test report is too large to trust"
_MALFORMED = "the per-test report is malformed"


@dataclass(slots=True)
class FileOutcome:
    status: str = "pass"                                  # pass | fail
    failing: dict[str, str] = field(default_factory=dict)  # test id -> first line of the failure
    ran: int = 0                                          # tests that finished
    tests: int = 0                                        # test outcomes reported (not files or suites)
    skipped: int = 0                                      # ... of which skipped
    hung: list[str] = field(default_factory=list)         # tests started and never finished (timeout)
    missing: set[str] = field(default_factory=set)        # requested names that do not exist (unittest)
    seconds: float = 0.0                                  # sum of reported test durations
    test_seconds: dict[str, float] = field(default_factory=dict)  # failing test id -> its reported duration


@dataclass(slots=True)
class Attribution:
    trusted: bool
    reason: str = ""
    files: dict[str, FileOutcome] = field(default_factory=dict)  # repo-relative test file -> outcome
    unmapped: list[str] = field(default_factory=list)            # failing ids no requested file owns
    done: bool = False
    stopped: bool = False                                        # the runner stopped before running every test
    order: list[str] = field(default_factory=list)               # files in the order their first test started
    finished: set[str] = field(default_factory=set)              # node: files whose child process completed
    collected: dict[str, set[str]] = field(default_factory=dict)  # file -> the test ids it was about to run
    ended: dict[str, set[str]] = field(default_factory=dict)      # file -> the test ids that ended
    modules: set[str] = field(default_factory=set)               # pytest: repo-relative files it collected

    def complete(self, f: str) -> bool:
        """Every test the file was about to run ended (False when unknown)."""
        ids = self.collected.get(f)
        return ids is not None and bool(ids) and ids <= self.ended.get(f, set())

    def failing_files(self) -> list[str]:
        return sorted(f for f, o in self.files.items() if o.status != "pass")


def can_instrument(runner: TestRunner, argv: list[str]) -> bool:
    """Whether this invocation can report per-test outcomes."""
    if not argv:
        return False
    if runner.kind in {"unittest", "pytest"}:
        return argv[0] == "python" and argv[1:3] in (["-m", "unittest"], ["-m", "pytest"])
    if runner.kind == "node":
        # a project's own reporter choice would pair with ours ambiguously: leave it alone
        return argv[0] == "node" and "--test" in argv and not any(
            a.startswith(("--test-reporter", "--test-reporter-destination")) for a in argv)
    return False


def instrument(runner: TestRunner, argv: list[str], ws: Path, inside_root: str, name: str,
               native: bool = False) -> tuple[list[str], Path]:
    """`argv` wrapped to write a per-test report; (new argv, host path of the
    report). The reporter is copied into the workspace's run directory.
    Unless `native` (the project's own full-suite command, run as is), a
    pytest run of several files continues past a file that fails to collect,
    as each file would when run alone."""
    run = ws / RUN_DIR
    run.mkdir(parents=True, exist_ok=True)
    out_rel = f"{RUN_DIR}/{name}.jsonl"
    inside = f"{inside_root}/{out_rel}"
    if runner.kind == "node":
        shutil.copy2(NODE_REPORTER, run / NODE_REPORTER.name)
        i = argv.index("--test")
        wrapped = [*argv[:i], f"--test-reporter={_file_url(f'{inside_root}/{RUN_DIR}/{NODE_REPORTER.name}')}",
                   f"--test-reporter-destination={inside}", "--test-reporter=spec",
                   "--test-reporter-destination=stdout", *argv[i:]]
    else:
        shutil.copy2(RESULT_SHIM, run / RESULT_SHIM.name)
        rest = argv[1:]
        if runner.kind == "pytest" and not native and "--continue-on-collection-errors" not in rest:
            rest = [*rest[:2], "--continue-on-collection-errors", *rest[2:]]  # after "-m pytest"
        wrapped = ["python", f"{inside_root}/{RUN_DIR}/{RESULT_SHIM.name}", "--out", inside, "--", *rest]
    return wrapped, ws / out_rel


def _file_url(path: str) -> str:
    """A module specifier node accepts on every platform (a bare Windows path
    is not a valid ESM specifier)."""
    from pathlib import PurePosixPath, PureWindowsPath
    if path.startswith("/"):
        return PurePosixPath(path).as_uri()
    return PureWindowsPath(path).as_uri()


def _events(path: Path) -> tuple[list[dict], str]:
    from .isolate import ReportTooLarge, read_inside
    # the report is `<workspace>/.repo-ai/run/<name>.jsonl`: read without following links from the workspace
    base, rel = (path.parents[2], f"{RUN_DIR}/{path.name}") if path.parent.as_posix().endswith(RUN_DIR) \
        else (path.parent, path.name)
    try:
        data = read_inside(base, rel, MAX_REPORT_BYTES)
    except ReportTooLarge:
        return [], _TOO_LARGE
    if data is None:
        return [], "no per-test report was written"
    out: list[dict] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            return out, _MALFORMED
        if not isinstance(ev, dict) or ev.get("e") not in {"start", "end", "done", "file_done", "collected", "module"}:
            return out, _MALFORMED
        out.append(ev)
        if len(out) > MAX_EVENTS:
            return out, _TOO_LARGE
    return out, ""


def _str(v: object, limit: int = 2000) -> str:
    return v[:limit] if isinstance(v, str) else ""


def _norm_path(path: str) -> str:
    """Forward slashes everywhere; case-insensitive on Windows."""
    path = path.replace("\\", "/")
    return path.lower() if os.name == "nt" else path


class _Mapper:
    """Maps what a report names (an absolute path inside the sandbox, a
    module name) to a repo-relative test file."""

    def __init__(self, runner: TestRunner, files: list[str], inside_root: str):
        self.files = set(files)
        self.prefix = _norm_path(inside_root).rstrip("/") + "/"
        self.by_module: dict[str, str] = {}
        if runner.kind == "unittest":
            for f in files:
                try:
                    rel = runner._rel(f)
                except ValueError:
                    continue
                top = runner.top if runner.top not in {"", "."} else ""
                if top and rel.startswith(top.rstrip("/") + "/"):
                    rel = rel[len(top.rstrip("/")) + 1:]
                parts = PurePosixPath(rel).with_suffix("").parts
                if parts and parts[-1] == "__init__":
                    parts = parts[:-1]
                if parts:
                    self.by_module[".".join(parts)] = f

    def file(self, ev: dict) -> str:
        path = _str(ev.get("path"))
        if path.startswith("file://"):
            path = path[7:]
        path = _norm_path(path)
        if path.startswith(self.prefix):
            rel = path[len(self.prefix):]
            if rel in self.files:
                return rel
            if os.name == "nt":
                hit = [f for f in self.files if f.lower() == rel]
                if len(hit) == 1:
                    return hit[0]
        mod = _str(ev.get("mod"))
        name = mod
        while name:
            if name in self.by_module:
                return self.by_module[name]
            name = name.rpartition(".")[0]
        if mod:
            # unittest names a module that failed to import by its last component(s) only
            # ("pydantic_utils" for tests.pydantic_utils): accept a unique suffix match
            hits = {f for m, f in self.by_module.items() if m == mod or m.endswith("." + mod)}
            if len(hits) == 1:
                return hits.pop()
        return ""


def parse(report: Path, runner: TestRunner, files: list[str], inside_root: str, *, exit_code: int,
          timed_out: bool, owners: dict[str, list[str]] | None = None) -> Attribution:
    """The outcome of each of `files` (the test files the process was asked
    to run, repo-relative) according to the process's report. `owners`: test
    id -> the files it failed in, when the process was asked to run named
    tests (a re-run of failures): the outcome belongs to each of them."""
    events, problem = _events(report)
    att = Attribution(trusted=False, files={f: FileOutcome() for f in files})
    if problem and not events:
        att.reason = problem
        return att
    mapper = _Mapper(runner, files, inside_root)
    open_tests: set[tuple[str, str]] = set()
    file_level_failures: dict[str, str] = {}
    for ev in events:
        kind = ev.get("e")
        if kind == "done":
            att.done = True
            att.stopped = ev.get("stopped") is True
            continue
        if kind == "file_done":
            f_done = mapper.file(ev)
            if f_done:
                att.finished.add(f_done)
            continue
        if kind == "module":
            path = _norm_path(_str(ev.get("path"), 4000))
            if path.startswith(mapper.prefix):
                att.modules.add(path[len(mapper.prefix):])
            continue
        if kind == "collected":
            f_col = mapper.file(ev)
            ids = ev.get("ids")
            if f_col and isinstance(ids, list):
                att.collected.setdefault(f_col, set()).update(_str(i, 1000) for i in ids[:200000])
            continue
        tid = _str(ev.get("id"), 1000)
        mapped = mapper.file(ev)
        targets = [f for f in (owners or {}).get(tid, []) if f in att.files] or ([mapped] if mapped else [])
        if kind == "start":
            open_tests.update((f, tid) for f in targets)
            for f in targets:
                if f not in att.order:
                    att.order.append(f)
            continue
        outcome = _str(ev.get("o"))
        if outcome not in {"pass", "fail", "error", "skip"}:
            att.reason = _MALFORMED
            return att
        if not targets:
            if outcome in {"fail", "error"}:
                att.unmapped.append(tid)
            continue
        msg = _str(ev.get("msg"), 300)
        dur = ev.get("dur")
        counted = ev.get("file") is not True and ev.get("suite") is not True and ev.get("collect") is not True
        for f in targets:
            open_tests.discard((f, tid))
            att.ended.setdefault(f, set()).add(tid)
            fo = att.files[f]
            if counted and not ev.get("sub"):
                fo.tests += 1
                fo.skipped += outcome == "skip"
            if isinstance(dur, (int, float)) and dur >= 0:
                fo.seconds += float(dur) / (1000.0 if runner.kind == "node" else 1.0)
            if outcome not in {"fail", "error"}:
                if counted:  # node's per-file wrapper and suites are not tests: a file of only those ran none
                    fo.ran += 1
                continue
            if runner.kind == "node" and _SUBTESTS_FAILED.match(msg):
                continue  # a parent failing only because a subtest did: the subtest is the failure
            if ev.get("file") is True:
                file_level_failures[f] = msg or "the test file failed outside any test"
                continue
            fo.status = "fail"
            fo.failing.setdefault(tid, msg)
            if isinstance(dur, (int, float)) and dur >= 0:
                fo.test_seconds[tid] = float(dur) / (1000.0 if runner.kind == "node" else 1.0)
            if ev.get("load") is True and "has no attribute" in msg:
                fo.missing.add(tid)  # a test or class that is not defined in this revision
    for f, msg in file_level_failures.items():
        fo = att.files[f]
        if fo.status == "pass":  # the file failed outside its tests: loading it, or at exit
            fo.status = "fail"
            fo.failing["<file>"] = msg
    for (f, tid) in sorted(open_tests):
        att.files[f].hung.append(tid)
    any_failure = any(o.status != "pass" for o in att.files.values())
    if problem:
        att.reason = problem
    elif att.unmapped:
        att.reason = f"{len(att.unmapped)} failure(s) could not be attributed to a requested test file"
    elif timed_out:
        att.reason = "the process timed out"
    elif not att.done:
        att.reason = "the per-test report is incomplete (the process ended early)"
    elif att.stopped or (runner.kind == "pytest" and exit_code == 2):
        att.reason = "the runner stopped before running every test (failfast, -x/--maxfail, or interrupted)"
    elif exit_code == 0 and any_failure:
        att.reason = "the report shows failures but the process exited 0"
    elif exit_code != 0 and not any_failure:
        att.reason = f"the process exited {exit_code} without a failing test in its report"
    elif any(o.hung for o in att.files.values()):
        att.reason = "tests started and never finished"
    else:
        att.trusted = True
    return att


def hides_failure(att: Attribution | None) -> str:
    """Why a process's exit status 0 cannot be taken at its word, or "": its
    own per-test report shows a failing test or one that never finished, or
    ends before the runner did (code under test called `os._exit(0)`, a
    fixture raised `SystemExit(0)`). With no report at all (the reporter
    never started) the exit status is all there is."""
    if att is None or att.reason == "no per-test report was written":
        return ""
    if att.unmapped or any(o.status != "pass" for o in att.files.values()):
        return "its per-test report shows failing tests"
    if any(o.hung for o in att.files.values()):
        return "its per-test report shows tests that never finished"
    # a report cut at the size limit (a very large suite) or unreadable proves nothing either way:
    # only one that was read whole and stops short of the runner's end contradicts the exit status
    if not att.done and att.reason not in {_TOO_LARGE, _MALFORMED}:
        return "its per-test report ends before the test runner finished"
    return ""


def rerun_ids(runner: TestRunner, file: str, ids: list[str], inside_root: str) -> list[str] | None:
    """Arguments that re-run exactly these failing tests of `file` with this
    runner, or None when tests are not individually addressable (node, a
    failure outside any test, unittest discovery from a nested top level)."""
    if not ids or "<file>" in ids:
        return None
    if runner.kind == "unittest" and runner.top in {"", "."}:
        try:
            module = ".".join(PurePosixPath(runner._rel(file)).with_suffix("").parts)
        except ValueError:
            return None
        out = []
        for tid in ids:
            # a sub-test reports its parent id; a fixture failure ("setUpClass (mod.Class)") or an
            # import failure (a bare module name) is not a single test: re-run the whole file.
            # So is a test whose id is not `<this file's module>.<Class>.<method>`: a doctest or a
            # FunctionTestCase from `load_tests` (unittest would *call* the named function), or a
            # class imported from another module (its id names that module, whose context differs)
            if " " in tid or "(" in tid or not tid.startswith(module + ".") \
                    or tid[len(module) + 1:].count(".") < 1:
                return None
            out.append(tid)
        return out
    if runner.kind == "pytest":
        out = []
        for tid in ids:
            path, sep, rest = tid.partition("::")
            if not sep or not rest:
                return None  # a collection error names the file only
            if PurePosixPath(path).name != PurePosixPath(file).name:
                return None  # not collected from this file (a doctest module, a plugin's item)
            # node ids are relative to pytest's rootdir; the re-run names the file relative to the
            # runner's working directory instead
            try:
                rel = runner._rel(file)
            except ValueError:
                return None
            out.append(f"{rel}::{rest}")
        return out
    return None
