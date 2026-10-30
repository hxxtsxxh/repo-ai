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


def main(argv):
    if "--" not in argv:
        sys.stderr.write("usage: rai_trace.py --out FILE --root DIR -- -m module [args] | script [args]\n")
        return 2
    sep = argv.index("--")
    opts, target = argv[:sep], argv[sep + 1:]
    out = opts[opts.index("--out") + 1]
    want_lines = "--lines" in opts  # also record which lines ran (changed-line exercise measurement)
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
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.spawn"}:
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
                "opened": sorted(opened), "spawned": sorted(set(spawned))[:20]}
        if want_lines:
            data["lines"] = {k: sorted(v) for k, v in sorted(line_hits.items())}
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
