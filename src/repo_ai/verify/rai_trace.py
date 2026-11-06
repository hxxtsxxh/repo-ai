"""repo-ai runtime evidence recorder (standalone: standard library only).

Copied into the workspace and run *inside the sandbox* with the project's own
interpreter, wrapping one test-runner invocation:

    python rai_trace.py --out OUT.json --root ROOT -- -m unittest tests.test_x

It records which code objects under ROOT started executing (function,
method, class body and module code, keyed "firstlineno:name" exactly as
``repo_ai.verify.changes.code_units`` keys them) and which files under ROOT
the process opened (data files, templates, fixtures), and the names of
programs it spawned (child processes run code it cannot see, so such a
record is marked incomplete). It records nothing else: no arguments,
values, environment or output.

Python 3.12+ uses ``sys.monitoring`` and disables each code location after
its first start, so the overhead is one callback per function, not per call.

``--per-test --watch a.py,b.py`` (with ``--lines``, for ``-m pytest`` only)
also records, per pytest node id, which lines of the watched files ran while
that test ran (its setup, call and teardown), and separately the watched lines
that ran outside any test (import, collection). Line events are re-armed for
all code at each test, which slows large suites. Attribution is by time
window, except for shared (session-, package-, module- or class-scoped)
fixtures: each run's setup lines are recorded apart (``fixture_lines``, per
run, so a parametrized or per-class fixture's runs stay separate) with the
runs each test's call had active (``fixture_uses``: its override chains and
what its body fetched). Teardown belongs to the test it runs after, a thread's
work to whichever test is running, and child processes are not seen
(``spawned`` says so).
Older interpreters fall back to ``sys.setprofile``. Code that runs in child
processes or in threads started before tracing is not seen.
"""

import atexit
import json
import os
import runpy
import sys
import threading

_HERE = os.path.abspath(__file__)
MAX_PER_TEST = 5000  # tests recorded per run; beyond this the per-test record is marked incomplete


def _fixture_key(fixturedef):
    return "%s::%s::%s" % (getattr(fixturedef, "baseid", ""), getattr(fixturedef, "argname", ""),
                           getattr(fixturedef, "scope", ""))


def _run_token(fixturedef, runs):
    return "%s@%x#%d" % (_fixture_key(fixturedef), id(fixturedef), runs.get(id(fixturedef), 0))


def _used(chain):
    """Of an override chain, the definitions actually used: the active (last) one, and further back only while the
    current one requests its own name (an override that ignores its parent never ran the parent's code)."""
    out = []
    for fixturedef in reversed(tuple(chain or ())):
        out.append(fixturedef)
        if getattr(fixturedef, "argname", None) not in (getattr(fixturedef, "argnames", ()) or ()):
            break
    return out


def _active_runs(item, runs):
    """Tokens of the shared fixture runs a test has active: every definition in its closure's override chains and
    every fixture its request fetched (getfixturevalue), each only while set up (cached_result)."""
    found = set()
    try:
        defs = []
        info = getattr(item, "_fixtureinfo", None)
        chains = getattr(info, "name2fixturedefs", None) or {}
        for name in getattr(item, "fixturenames", ()):
            defs.extend(_used(chains.get(name)))
        request = getattr(item, "_request", None)
        defs.extend((getattr(request, "_fixture_defs", None) or {}).values())
        for chain in (getattr(request, "_arg2fixturedefs", None) or {}).values():  # incl. getfixturevalue chains
            defs.extend(_used(chain))
        manager = getattr(getattr(item, "session", None), "_fixturemanager", None)
        seen, queue = set(), list(defs)
        while queue:  # what those fixtures depend on (set up before their own setup hook runs)
            fixturedef = queue.pop()
            if id(fixturedef) in seen:
                continue
            seen.add(id(fixturedef))
            defs.append(fixturedef)
            for name in getattr(fixturedef, "argnames", ()) or ():
                try:
                    chain = manager.getfixturedefs(name, item) if manager is not None else None
                except Exception:  # signature differs across pytest versions: credit what is known
                    chain = None
                queue.extend(_used(chain))
        for fixturedef in defs:
            if (getattr(fixturedef, "scope", "function") != "function"
                    and getattr(fixturedef, "cached_result", None) is not None and id(fixturedef) in runs):
                found.add(_run_token(fixturedef, runs))
    except Exception:  # an unusual item or pytest internals: credit nothing rather than break the run
        pass
    return found


def main(argv):
    if "--" not in argv:
        sys.stderr.write("usage: rai_trace.py --out FILE --root DIR -- -m module [args] | script [args]\n")
        return 2
    sep = argv.index("--")
    opts, target = argv[:sep], argv[sep + 1:]
    out = opts[opts.index("--out") + 1]
    want_lines = "--lines" in opts  # also record which lines ran (changed-line exercise measurement)
    per_test_on = want_lines and "--per-test" in opts and target[:2] == ["-m", "pytest"]
    watch = set(opts[opts.index("--watch") + 1].split(",")) if per_test_on and "--watch" in opts else set()
    per_test = {}  # pytest node id -> {watched path -> lines run during that test}
    outside = {}  # watched path -> lines run while no test was running (import, collection)
    current = [None]
    counts = {"collected": 0, "ran": 0, "collection_finished": 0}
    fixtures = [[]]  # stack of shared (non-function-scoped) fixture runs being set up
    fixture_lines = {}  # shared fixture run token -> {watched path -> lines run during its setup}
    uses = {}  # pytest node id -> tokens of the shared fixture runs active while its call ran
    runs = {}  # id(fixturedef) -> its current run number (a parametrized or class/module fixture runs repeatedly)
    traced = {}  # pytest node id -> its outcome in this run (the worst phase, as the verified run's shim reports it)
    pending = {}  # pytest node id -> its worst phase so far, committed to `traced` only at its teardown
    rank = {"pass": 0, "skip": 1, "fail": 2, "error": 3}
    root = os.path.realpath(opts[opts.index("--root") + 1])
    prefix = root.rstrip(os.sep) + os.sep
    seen = {}
    line_hits = {}
    opened = set()
    script = None  # set below: the script being run is loaded, not read as data
    roots = {}

    def rel(filename):
        if not filename or filename.startswith("<"):
            return None
        cached = roots.get(filename)
        if cached is not None:
            return cached or None
        real = os.path.realpath(filename)
        value = real[len(prefix):].replace(os.sep, "/") if real.startswith(prefix) and real != _HERE else ""
        roots[filename] = value
        return value or None

    def record(code):
        path = rel(code.co_filename)
        if path is not None:
            seen.setdefault(path, set()).add(f"{code.co_firstlineno}:{code.co_name}")

    def record_line(code, line):
        path = rel(code.co_filename)
        if path is not None:
            line_hits.setdefault(path, set()).add(line)
            if path in watch:
                if fixtures[0]:
                    # inside a shared fixture's setup (and every enclosing one): credited later to each test whose
                    # call ran with that fixture run active, not to the test that happened to trigger it
                    for token in fixtures[0]:
                        fixture_lines.setdefault(token, {}).setdefault(path, set()).add(line)
                    return
                test = current[0]
                if test is None:
                    outside.setdefault(path, set()).add(line)
                elif len(per_test) <= MAX_PER_TEST:
                    per_test.setdefault(test, {}).setdefault(path, set()).add(line)

    spawned = []

    def importing():
        """Is the code that called open() the import system (or runpy loading the
        script it runs)? Only the direct caller counts: a test's own read stays a
        read even when the test itself was started by runpy."""
        frame = sys._getframe(2)
        name = (frame.f_code.co_filename if frame is not None else "").replace("\\", "/")
        return name.startswith(("<frozen importlib", "<frozen runpy", "<frozen zipimport")) or name.endswith((
            "importlib/_bootstrap_external.py", "importlib/_bootstrap.py", "/runpy.py", "/pkgutil.py",
            "/zipimport.py"))

    def on_open(event, args):
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.spawn", "os.fork",
                     "os.forkpty"}:
            # a child process runs code this tracer cannot see: the record is incomplete
            try:
                head = args[0] if event != "subprocess.Popen" else (args[0] or (args[1] or [""])[0])
                spawned.append(os.path.basename(os.fsdecode(head if isinstance(head, (str, bytes)) else str(head)))[:60])
            except (TypeError, ValueError, IndexError):
                spawned.append(event)
            return
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            try:
                name = os.fsdecode(args[0])
            except (TypeError, ValueError):
                return
            if "__pycache__" not in name and not name.endswith((".pyc", ".pyo")):
                path = rel(os.path.abspath(name))
                # a source file opened by the import system is an import (already recorded as
                # executed code); opened by anything else, it is being read as data
                # (version checks, header checks), so it is recorded as opened
                if path is not None and path != script and (not path.endswith(".py") or not importing()):
                    opened.add(path)

    def write():
        data = {"version": 1, "units": {k: sorted(v) for k, v in sorted(seen.items())},
                "opened": sorted(opened), "spawned": sorted(set(spawned))[:20],
                # which interpreter traced, and how (a container image's Python may be older than 3.12)
                "python": list(sys.version_info[:3]), "line_events": "sys.monitoring" if mon is not None else "settrace"}
        if want_lines:
            data["lines"] = {k: sorted(v) for k, v in sorted(line_hits.items())}
        if per_test_on:
            data["per_test"] = {t: {k: sorted(v) for k, v in sorted(files.items())}
                                for t, files in sorted(per_test.items())}
            data["fixture_lines"] = {k: {p: sorted(v) for p, v in sorted(files.items())}
                                     for k, files in sorted(fixture_lines.items())}
            data["fixture_uses"] = {t: sorted(k for k in keys if k in fixture_lines)
                                    for t, keys in sorted(uses.items()) if any(k in fixture_lines for k in keys)}
            # every collected test ran (an early stop, -x or --maxfail, leaves some unrun)
            data["per_test_complete"] = (len(per_test) <= MAX_PER_TEST and counts["ran"] >= counts["collected"]
                                         and counts["collection_finished"] == 1)
            # every test this run saw, with its outcome, even those that ran no watched line (bounded)
            data["traced"] = dict(sorted(traced.items()))
            data["traced_complete"] = counts.get("traced_cut", 0) == 0
            # a shared fixture run no test's call claimed (it skipped or failed, or every user failed setup) still
            # ran its lines: they count as outside any test rather than nowhere
            claimed = {k for keys in uses.values() for k in keys}
            for token, files in fixture_lines.items():
                if token not in claimed:
                    for path, lines in files.items():
                        outside.setdefault(path, set()).update(lines)
            data["outside_tests"] = {k: sorted(v) for k, v in sorted(outside.items())}
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, out)

    atexit.register(write)
    sys.addaudithook(on_open)
    mon = getattr(sys, "monitoring", None)
    if mon is not None:
        tool = None
        for candidate in (4, 5, 3):
            try:
                mon.use_tool_id(candidate, "repo-ai")
                tool = candidate
                break
            except ValueError:
                continue
        if tool is not None:
            def on_start(code, offset):
                record(code)
                return mon.DISABLE
            mon.register_callback(tool, mon.events.PY_START, on_start)
            events = mon.events.PY_START
            if want_lines:
                def on_line(code, line):
                    record_line(code, line)
                    return mon.DISABLE
                mon.register_callback(tool, mon.events.LINE, on_line)
                events |= mon.events.LINE
            mon.set_events(tool, events)
        else:  # pragma: no cover - every tool id taken
            mon = None
    if mon is None:
        def profiler(frame, event, arg):
            if event == "call":
                record(frame.f_code)
        sys.setprofile(profiler)
        threading.setprofile(profiler)
    if want_lines and mon is None:
        def tracer(frame, event, arg):
            if rel(frame.f_code.co_filename) is None:
                return None
            def local(frame, event, arg):
                if event == "line":
                    record_line(frame.f_code, frame.f_lineno)
                return local
            record_line(frame.f_code, frame.f_lineno)
            return local
        sys.settrace(tracer)
        threading.settrace(tracer)

    if target and target[0] != "-m":
        script = rel(os.path.abspath(target[0]))
    sys.argv = list(target)
    if per_test_on:
        import pytest  # the project's own pytest, as `-m pytest` would load it

        import multiprocessing.process as _mpp
        _start = _mpp.BaseProcess.start

        def _counted_start(self, *a, **k):  # multiprocessing children run code this tracer cannot see
            spawned.append("multiprocessing")
            return _start(self, *a, **k)
        _mpp.BaseProcess.start = _counted_start

        class _PerTest:
            def pytest_collection_finish(self, session):
                counts["collected"] = len(session.items)
                counts["collection_finished"] = 1

            @pytest.hookimpl(hookwrapper=True)
            def pytest_fixture_setup(self, fixturedef, request):
                shared = getattr(fixturedef, "scope", "function") != "function"
                if shared:
                    runs[id(fixturedef)] = runs.get(id(fixturedef), 0) + 1
                    fixtures[0].append(_run_token(fixturedef, runs))
                    if mon is not None:
                        mon.restart_events()  # lines an enclosing setup or the test already ran fire again here
                try:
                    yield
                finally:
                    if shared:
                        fixtures[0].pop()
                        if mon is not None:
                            mon.restart_events()

            @pytest.hookimpl(hookwrapper=True)
            def pytest_runtest_call(self, item):
                # only a test whose setup succeeded gets here (a skipped test does not): the shared fixture runs
                # active now are the ones it ran with; again after the call for those its body requested
                uses.setdefault(item.nodeid, set()).update(_active_runs(item, runs))
                try:
                    yield
                finally:
                    uses[item.nodeid].update(_active_runs(item, runs))

            def pytest_runtest_logreport(self, report):
                # the same vocabulary as the verified run: a failed call is "fail", a failed setup or teardown
                # "error", a skip (or an expected failure) "skip"; a test's outcome is its worst phase
                nid = report.nodeid
                if report.failed:
                    outcome = "fail" if report.when == "call" else "error"
                elif report.skipped:
                    outcome = "skip"
                else:
                    outcome = "pass"
                if rank[outcome] >= rank[pending.get(nid, "pass")]:
                    pending[nid] = outcome
                if report.when != "teardown":
                    return  # a test stopped mid-call (pytest.exit) never reaches teardown: it did not finish
                worst = pending.pop(nid, outcome)
                if nid not in traced and len(traced) >= MAX_PER_TEST:
                    counts["traced_cut"] = 1
                    return
                traced[nid] = worst

            @pytest.hookimpl(hookwrapper=True)
            def pytest_runtest_protocol(self, item, nextitem):
                counts["ran"] += 1
                current[0] = item.nodeid
                if mon is not None:
                    mon.restart_events()  # lines disabled after their first hit fire again for this test
                try:
                    yield
                finally:
                    current[0] = None

        sys.argv = ["pytest", *target[2:]]
        raise SystemExit(pytest.main(target[2:], plugins=[_PerTest()]))
    if target and target[0] == "-m":
        sys.argv = [target[1], *target[2:]]
        runpy.run_module(target[1], run_name="__main__", alter_sys=True)
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(target[0])))
        runpy.run_path(target[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    # behave like `python -m ...` run from the working directory: cwd first, never this file's directory
    sys.path[:] = [os.getcwd()] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(_HERE)]
    raise SystemExit(main(sys.argv[1:]))
