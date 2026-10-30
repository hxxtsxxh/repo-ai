"""repo-ai test-outcome reporter (standalone: standard library only).

Copied into the disposable workspace and run *inside the sandbox* with the
project's own interpreter, wrapping one test-runner invocation exactly as
``rai_trace.py`` does:

    python rai_result.py --out OUT.jsonl -- -m unittest tests.test_a tests.test_b
    python rai_result.py --out OUT.jsonl -- -m pytest -q tests/test_a.py

It appends one JSON line per event, flushed as it happens, so a run that is
killed (a timeout, a hang) still shows which tests finished and which one
was running:

    {"e": "start", "id": ..., "mod": ..., "path": ...}
    {"e": "end", "id": ..., "mod": ..., "path": ..., "o": "pass|fail|error|skip", "msg": ..., "dur": ...}
    {"e": "collected", "path": ..., "ids": [...]}   (before the run: the tests of one file)
    {"e": "module", "path": ..., "ok": bool}       (pytest: a file it collected, or failed to)
    {"e": "done", "exit": N}

It records test ids, outcomes, the last line of each failure and durations;
nothing else (no arguments, values, environment or full output). The test
runner itself is unchanged: its own output still goes to stdout/stderr.

unittest: the base ``unittest.TestResult`` methods are wrapped, so every
result class that calls them (the standard text runner does) is seen.
pytest: a plugin object is passed to ``pytest.main``; under pytest-xdist the
controller receives every report, so workers need nothing.
"""

import json
import os
import runpy
import sys
import time
import traceback

_HERE = os.path.abspath(__file__)
_MAX_MSG = 300


class _Out:
    def __init__(self, path):
        self.fh = open(path, "a", encoding="utf-8")

    def emit(self, **event):
        try:
            self.fh.write(json.dumps(event, default=str) + "\n")
            self.fh.flush()
        except (OSError, ValueError):
            pass


def _last_line(exc_type, exc):
    try:
        lines = traceback.format_exception_only(exc_type, exc)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break reporting
        return exc_type.__name__ if exc_type else ""
    text = "".join(lines).strip().splitlines()
    return (text[-1] if text else "")[:_MAX_MSG]


def _module_file(mod):
    m = sys.modules.get(mod or "")
    f = getattr(m, "__file__", None) if m is not None else None
    return os.path.abspath(f) if isinstance(f, str) else ""


# --------------------------------------------------------------------------
# unittest
# --------------------------------------------------------------------------
state = {"stopped": False}


def _unittest_hooks(out):
    import unittest.result as ur

    started = {}

    def inner(result) -> bool:
        """A result object other than the outer runner's: a test that runs
        unittest itself (testing a decorator, a retry helper or a runner)
        records its own deliberate failures there, and they are not the
        outer run's tests."""
        outer = state.get("outer")
        return outer is not None and result is not outer

    import unittest.loader as ul
    import unittest.suite as us

    def tag(suite, name):
        """Mark each test with the module that loaded it: a TestCase class
        imported into another test module runs there too, and belongs to the
        file that was asked to run it, not to the file defining it."""
        stack = [suite]
        while stack:
            cur = stack.pop()
            if isinstance(cur, us.TestSuite):
                stack.extend(cur)
            elif getattr(cur, "_rai_mod", None) is None:
                try:
                    cur._rai_mod = name
                except Exception:  # noqa: BLE001
                    pass

    original_by_name = ul.TestLoader.loadTestsFromName

    def by_name(self, name, module=None):
        """Native unittest turns only an ImportError while loading a named
        module into a failed test; any other exception (a module that raises
        at import) aborts the whole run. Run alone, that one file fails; the
        other files of a batch still run. Make the batch behave the same."""
        try:
            suite = original_by_name(self, name, module)
        except Exception as exc:  # noqa: BLE001
            make = getattr(ul, "_make_failed_test", None)
            if make is None:
                raise
            suite, _ = make(name, exc, self.suiteClass, traceback.format_exc())
        # unittest names a name it could not load by its last part only ("test_gone" for
        # tests.test_a.A.test_gone): report the name that was asked for
        stack = [suite]
        while stack:
            cur = stack.pop()
            if isinstance(cur, us.TestSuite):
                stack.extend(cur)
            elif type(cur).__name__ == "_FailedTest":
                try:
                    cur._rai_name = name
                except Exception:  # noqa: BLE001
                    pass
        return suite
    ul.TestLoader.loadTestsFromName = by_name

    original_load = ul.TestLoader.loadTestsFromModule

    def load(self, module, *args, **kwargs):
        suite = original_load(self, module, *args, **kwargs)
        try:
            tag(suite, getattr(module, "__name__", ""))
        except Exception:  # noqa: BLE001
            pass
        return suite
    ul.TestLoader.loadTestsFromModule = load

    def ident(test):
        """(id, module) of a test, an import failure or a fixture failure."""
        cls = type(test)
        name = cls.__name__
        if name == "_FailedTest":  # a module (or name) that could not be imported or found
            mod = getattr(test, "_rai_name", None) or getattr(test, "_testMethodName", "") or ""
            return f"{mod}", mod
        if name == "_ErrorHolder":  # setUpModule / setUpClass / tearDown* failed
            desc = str(getattr(test, "description", "") or "")
            inner = desc[desc.find("(") + 1:desc.rfind(")")] if "(" in desc else desc
            return desc, inner
        try:
            tid = test.id()
        except Exception:  # noqa: BLE001
            tid = repr(test)
        return tid, getattr(test, "_rai_mod", None) or cls.__module__

    def wrap(method, outcome):
        original = getattr(ur.TestResult, method)

        def patched(self, test, *args):
            if inner(self):
                return original(self, test, *args)
            try:
                tid, mod = ident(test)
                msg = ""
                if outcome in {"fail", "error"} and args and isinstance(args[0], tuple) and len(args[0]) >= 2:
                    msg = _last_line(args[0][0], args[0][1])
                elif outcome == "skip" and args:
                    msg = str(args[0])[:_MAX_MSG]
                t0 = started.pop(tid, None)
                extra = {"load": True} if type(test).__name__ == "_FailedTest" else {}
                if method == "addExpectedFailure":
                    extra["xfail"] = True  # an expected failure, said explicitly (ProofLab counts it apart)
                out.emit(e="end", id=tid, mod=mod, path=_module_file(mod), o=outcome, msg=msg,
                         dur=round(time.monotonic() - t0, 4) if t0 is not None else None, **extra)
            except Exception:  # noqa: BLE001 - reporting must never change the test outcome
                pass
            return original(self, test, *args)
        setattr(ur.TestResult, method, patched)

    import unittest.runner as urun
    original_run = urun.TextTestRunner.run

    def run(self, test):
        """Before anything runs: every test id each file is about to run, so
        that a run cut short (a timeout) shows which files were complete."""
        if state.get("in_run"):  # a run started by a test: nothing of it is reported
            return original_run(self, test)
        state["in_run"] = True
        try:
            by_path, stack, n = {}, [test], 0
            while stack and n < 200000:
                cur = stack.pop()
                if isinstance(cur, us.TestSuite):
                    stack.extend(cur)
                    continue
                n += 1
                tid, mod = ident(cur)
                by_path.setdefault(_module_file(mod), set()).add(tid)
            if not stack:
                for path, ids in by_path.items():
                    out.emit(e="collected", path=path, ids=sorted(ids))
        except Exception:  # noqa: BLE001 - reporting must never change the test outcome
            pass
        return original_run(self, test)
    urun.TextTestRunner.run = run
    original_make = urun.TextTestRunner._makeResult

    def make(self):
        result = original_make(self)
        if state.get("in_run") and state.get("outer") is None:
            state["outer"] = result  # the outer runner's result: the only one reported
        return result
    urun.TextTestRunner._makeResult = make

    original_start = ur.TestResult.startTest

    def start(self, test):
        if inner(self):
            return original_start(self, test)
        try:
            tid, mod = ident(test)
            started[tid] = time.monotonic()
            out.emit(e="start", id=tid, mod=mod, path=_module_file(mod))
        except Exception:  # noqa: BLE001
            pass
        return original_start(self, test)
    ur.TestResult.startTest = start

    original_stop = ur.TestResult.stop

    def stop(self):
        if inner(self):
            return original_stop(self)
        state["stopped"] = True  # failfast or an interrupt: the remaining tests never run
        return original_stop(self)
    ur.TestResult.stop = stop

    wrap("addSuccess", "pass")
    wrap("addFailure", "fail")
    wrap("addError", "error")
    wrap("addSkip", "skip")
    wrap("addExpectedFailure", "skip")  # an expected failure verifies nothing, like a skip
    wrap("addUnexpectedSuccess", "fail")
    original_sub = ur.TestResult.addSubTest

    def sub(self, test, subtest, err):
        if err is not None and not inner(self):
            try:
                tid, mod = ident(test)
                failed = issubclass(err[0], test.failureException)
                out.emit(e="end", id=tid, mod=mod, path=_module_file(mod), o="fail" if failed else "error",
                         msg=_last_line(err[0], err[1]), dur=None, sub=str(subtest)[:_MAX_MSG])
            except Exception:  # noqa: BLE001
                pass
        return original_sub(self, test, subtest, err)
    ur.TestResult.addSubTest = sub


# --------------------------------------------------------------------------
# pytest
# --------------------------------------------------------------------------
def _report_msg(report):
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:  # a skip: (path, line, reason)
        return str(longrepr[2])[:_MAX_MSG]
    crash = getattr(longrepr, "reprcrash", None)
    text = str(getattr(crash, "message", "") or "") if crash is not None else str(longrepr or "")
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    return (lines[0] if crash is not None else lines[-1])[:_MAX_MSG]


class _PytestPlugin:
    def __init__(self, out):
        self.out = out
        self.root = ""
        self.worst = {}
        self.xfails = set()  # node ids reported as expected failures (pytest.xfail, xfail marks)

    def pytest_configure(self, config):
        self.root = str(getattr(config, "rootpath", "") or getattr(config, "rootdir", ""))

    def _path(self, location_file):
        return os.path.abspath(os.path.join(self.root, location_file)) if location_file else ""

    def pytest_collection_finish(self, session):
        """Every test id each file is about to run (see the unittest `run`)."""
        try:
            by_path = {}
            for item in session.items:
                # An inherited method location names its definition, not the
                # file pytest collected. Use the node identity consistently.
                by_path.setdefault(self._path(item.nodeid.split("::")[0]), []).append(item.nodeid)
            for path, ids in by_path.items():
                self.out.emit(e="collected", path=path, ids=ids)
        except Exception:  # noqa: BLE001
            pass

    def pytest_runtest_logstart(self, nodeid, location):
        self.out.emit(e="start", id=nodeid, mod="", path=self._path(nodeid.split("::")[0]))

    def pytest_runtest_logreport(self, report):
        when = report.when
        if report.failed:
            outcome = "fail" if when == "call" else "error"
        elif report.skipped:
            outcome = "skip"  # skipped, or failed as expected (xfail): neither verifies anything
        else:
            outcome = "pass"
        if report.skipped and hasattr(report, "wasxfail"):
            self.xfails.add(report.nodeid)
        rank = {"pass": 0, "skip": 1, "fail": 2, "error": 3}
        prev = self.worst.get(report.nodeid, ("pass", "", 0.0))
        dur = prev[2] + float(getattr(report, "duration", 0.0) or 0.0)
        if rank[outcome] > rank[prev[0]]:
            prev = (outcome, _report_msg(report), dur)
        self.worst[report.nodeid] = (prev[0], prev[1], dur)
        if when == "teardown":
            outcome, msg, dur = self.worst.pop(report.nodeid)
            extra = {"xfail": True} if report.nodeid in self.xfails else {}
            self.xfails.discard(report.nodeid)
            self.out.emit(e="end", id=report.nodeid, mod="", path=self._path(report.nodeid.split("::")[0]),
                          o=outcome, msg=msg, dur=round(dur, 4), **extra)

    def pytest_sessionfinish(self, session, exitstatus):
        if getattr(session, "shouldstop", False) or getattr(session, "shouldfail", False):
            state["stopped"] = True  # -x / --maxfail, or an interrupt: the remaining tests never ran

    def pytest_collectreport(self, report):
        nodeid = report.nodeid or ""
        if nodeid and "::" not in nodeid and nodeid.endswith(".py"):
            # a file pytest itself collected (or tried to): its own answer to python_files,
            # testpaths, norecursedirs, --ignore, collect_ignore, --doctest-modules
            self.out.emit(e="module", path=self._path(nodeid), ok=not report.failed)
        if report.failed:
            nodeid = report.nodeid or ""
            self.out.emit(e="end", id=nodeid, mod="", path=self._path(nodeid.split("::")[0]), o="error",
                          msg=_report_msg(report) or "collection error", dur=None, collect=True)


def main(argv):
    if "--" not in argv:
        sys.stderr.write("usage: rai_result.py --out FILE -- -m unittest|pytest [args]\n")
        return 2
    sep = argv.index("--")
    opts, target = argv[:sep], argv[sep + 1:]
    out = _Out(opts[opts.index("--out") + 1])
    code = 1
    try:
        if target[:2] == ["-m", "pytest"]:
            import pytest
            sys.argv = ["pytest", *target[2:]]
            code = int(pytest.main(target[2:], plugins=[_PytestPlugin(out)]))
            return code
        if target[:2] == ["-m", "unittest"]:
            _unittest_hooks(out)
        sys.argv = [target[1], *target[2:]] if target and target[0] == "-m" else list(target)
        try:
            if target and target[0] == "-m":
                runpy.run_module(target[1], run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(target[0], run_name="__main__")
            code = 0
        except SystemExit as exc:
            c = exc.code
            code = c if isinstance(c, int) else (0 if c is None else 1)
        return code
    finally:
        out.emit(e="done", exit=code, stopped=bool(state["stopped"]))


if __name__ == "__main__":
    # behave like `python -m ...` run from the working directory: cwd first, never this file's directory
    sys.path[:] = [os.getcwd()] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(_HERE)]
    raise SystemExit(main(sys.argv[1:]))
