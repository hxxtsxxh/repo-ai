"""Runtime evidence: for every test file, the code it actually executed.

Recorded by running each test file once, in its own sandboxed process, under
a tracer (Python: ``rai_trace.py``; Node: V8's built-in ``NODE_V8_COVERAGE``).
Each record is tied to the exact content of every file it describes, so
evidence about a file is used only while that file is byte-identical to what
was recorded. Missing or stale evidence is never treated as "no consumer":
the selector falls back to static analysis and lowers its confidence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .. import __version__
from . import isolate
from .execute import Executor
from .runner import TestRunner

TESTMAP_VERSION = 1
TRACER = Path(__file__).with_name("rai_trace.py")
RUN_DIR = ".repo-ai/run"
MAX_RECORD_BYTES = 256 * 1024 * 1024  # one test file's trace or V8 coverage output
HASHED_SUFFIXES = {".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx",
                   ".json", ".toml", ".cfg", ".ini", ".yaml", ".yml", ".txt", ".csv", ".xml", ".html",
                   ".md", ".rst", ".j2", ".jinja", ".tmpl", ".sql"}


@dataclass(slots=True)
class TestMap:
    __test__ = False  # not a pytest test class
    runner: dict[str, Any]
    commit: str = ""
    created: str = ""
    repo_ai_version: str = __version__
    backend: str = ""
    interpreter: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)
    tests: dict[str, dict[str, Any]] = field(default_factory=dict)
    # node: per file, every function range seen in any coverage report
    functions: dict[str, list[list[Any]]] = field(default_factory=dict)
    # pytest: the files its own full-suite run collected, and the collection configuration
    # and command that answer depended on ({"files": [...], "config": sha, "command": str})
    collected: dict[str, Any] = field(default_factory=dict)
    # behavioural files with uncommitted changes when it was recorded: its outcomes are then
    # those of that working tree, not of the base revision
    uncommitted: list[str] = field(default_factory=list)
    version: int = TESTMAP_VERSION

    def to_json(self) -> dict[str, Any]:
        return {"version": self.version, "created": self.created, "repo_ai_version": self.repo_ai_version,
                "commit": self.commit, "backend": self.backend, "interpreter": self.interpreter,
                "runner": self.runner, "file_hashes": self.file_hashes, "tests": self.tests,
                "functions": self.functions, "collected": self.collected, "uncommitted": self.uncommitted}

    def save(self, path: Path) -> None:
        from ..fsutil import atomic_write  # a temporary file per writer, removed on failure
        atomic_write(path, json.dumps(self.to_json(), separators=(",", ":"), sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> TestMap | None:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("version") != TESTMAP_VERSION:
            return None
        fields = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        try:
            return cls(**fields)
        except TypeError:
            return None

    # -- queries ------------------------------------------------------------
    def fresh(self, path: str, content_sha: str) -> bool:
        """Evidence about `path` is usable only for byte-identical content."""
        return bool(content_sha) and self.file_hashes.get(path) == content_sha

    def consumers_of_units(self, path: str, keys: set[str]) -> dict[str, list[str]]:
        """Python: test file -> changed code units it executed."""
        out: dict[str, list[str]] = {}
        for test, rec in self.tests.items():
            hit = sorted(keys & set((rec.get("units") or {}).get(path, [])))
            if hit:
                out[test] = hit
        return out

    def loaders_of(self, path: str) -> list[str]:
        """Tests that executed any code in `path` or opened it as data."""
        return sorted(t for t, rec in self.tests.items()
                      if path in (rec.get("units") or {}) or path in (rec.get("opened") or [])
                      or path in (rec.get("functions") or {}))

    def executed_units(self, path: str) -> set[str]:
        out: set[str] = set()
        for rec in self.tests.values():
            out.update((rec.get("units") or {}).get(path, []))
        return out

    def node_consumers(self, path: str, lines: set[int]) -> tuple[dict[str, list[str]], list[str]]:
        """Node: for each changed line, the innermost recorded function containing
        it; the tests that executed one of those functions; and the names of
        changed functions no test executed."""
        funcs = self.functions.get(path) or []
        owners: set[int] = set()
        for line in lines:
            containing = [i for i, (a, b, _) in enumerate(funcs) if a <= line <= b]
            if containing:
                owners.add(min(containing, key=lambda i: funcs[i][1] - funcs[i][0]))
        out: dict[str, list[str]] = {}
        executed: set[int] = set()
        for test, rec in self.tests.items():
            ran = set((rec.get("functions") or {}).get(path, []))
            executed |= ran
            hit = sorted(owners & ran)
            if hit:
                out[test] = [funcs[i][2] or "<module>" for i in hit]
        never = sorted({funcs[i][2] or "<module>" for i in owners - executed})
        return out, never

    def complete(self, test: str) -> bool:
        """A recording that can stand alone: the file passed, was traced, and ran
        no child process the tracer could not follow."""
        rec = self.tests.get(test) or {}
        return rec.get("status") in {"pass", "no-tests"} and bool(rec.get("traced")) and not rec.get("spawned")

    def duration(self, test: str) -> float | None:
        rec = self.tests.get(test)
        return float(rec["duration_s"]) if rec and rec.get("duration_s") is not None else None

    def baseline_failures(self) -> list[str]:
        return sorted(t for t, rec in self.tests.items() if rec.get("status") not in {"pass", "no-tests"})


def content_sha(data: bytes) -> str:
    from .changes import sha
    return sha(data)


def hash_files(root: Path, files: list[str] | None = None) -> dict[str, str]:
    """Content hashes of the files evidence can describe. `files` lists them
    (a workspace has no git metadata); otherwise git is asked."""
    out = files if files is not None else subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, timeout=60, check=False,
        stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace").split("\0")
    hashes = {}
    for rel in out:
        if not rel or rel.startswith((".repo-ai/", ".claude/", ".bob/")):
            continue
        p = root / rel
        if Path(rel).suffix.lower() not in HASHED_SUFFIXES or p.is_symlink() or not p.is_file():
            continue
        try:
            hashes[rel] = content_sha(p.read_bytes())
        except OSError:
            continue
    return hashes


def _prepare(ws: Path) -> Path:
    run = isolate.run_dir(ws, RUN_DIR)
    shutil.copy2(TRACER, run / "rai_trace.py")
    return run


def record(root: Path, runner: TestRunner, executor: Executor, test_files: list[str],
           workers: int = 4, timeout_s: float = 600.0,
           log: Callable[[str], None] = lambda _: None) -> TestMap:
    """Run each test file once under the tracer, in the sandbox, each in its
    own pristine clone of the executor's disposable workspace (`root` is the
    source repository, read only for its commit). This executes repository
    code: callers must have the user's explicit authorization."""
    if not runner.per_file:
        raise ValueError(f"the {runner.kind} runner cannot be split per file; no runtime evidence")
    if executor.workspace is None:
        raise ValueError("record() needs an executor bound to a disposable workspace")
    from .execute import release
    root = root.resolve()
    template = executor.workspace.path
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                            check=False, timeout=30, stdin=subprocess.DEVNULL).stdout.strip()
    # evidence describes the content the tests ran against: hash the template before anything runs
    hashes = hash_files(template, executor.workspace.files)
    tmap = TestMap(runner=runner.to_json(), commit=commit, backend=executor.backend.name,
                   created=time.strftime("%Y-%m-%dT%H:%M:%S"),
                   interpreter=executor.node if runner.kind == "node" else executor.python)

    def one(test: str) -> tuple[str, dict[str, Any], list[tuple[str, list[dict[str, Any]]]]]:
        ex = executor.fresh()  # a pristine copy per test file: no leftovers from other files
        try:
            ws = ex.workspace.path if ex.workspace else template
            _prepare(ws)
            inside = ex.inside_root
            argv = runner.file_argv(test)
            env: dict[str, str] = dict(runner.env)
            scripts: list[tuple[str, list[dict[str, Any]]]] = []
            if runner.kind == "node":
                env["NODE_V8_COVERAGE"] = f"{inside}/{RUN_DIR}/cov"
                res = ex.run(argv, cwd=runner.cwd, env=env, timeout_s=timeout_s, toolchain="node")
                units: dict[str, Any] = {}
                opened: list[str] = []
                spawned: list[str] = []  # node children inherit NODE_V8_COVERAGE: they are recorded
                scripts = _node_scripts(ws, inside)
            else:
                out_rel = f"{RUN_DIR}/trace.json"
                traced = ["python", f"{inside}/{RUN_DIR}/rai_trace.py", "--out", f"{inside}/{out_rel}",
                          "--root", inside, "--", *argv[1:]]
                res = ex.run(traced, cwd=runner.cwd, env=env, timeout_s=timeout_s)
                try:
                    raw = isolate.read_inside(ws, out_rel, MAX_RECORD_BYTES)
                    data = json.loads(raw.decode("utf-8")) if raw else {}
                except (ValueError, UnicodeDecodeError):  # ReportTooLarge is a ValueError
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                units = data.get("units") or {}
                opened = data.get("opened") or []
                spawned = data.get("spawned") or []
        finally:
            release([ex])
        status = "timeout" if res.timed_out else ("pass" if res.exit_code == 0 else "fail")
        if status == "fail" and res.exit_code == 5 and runner.kind in {"unittest", "pytest"}:
            status = "no-tests"  # a helper module the runner's pattern matched: it defines no test
        rec = {"status": status, "exit_code": res.exit_code, "duration_s": round(res.duration_s, 3),
               "units": units, "opened": opened, "spawned": spawned,
               "traced": bool(units) or runner.kind == "node"}
        log(f"  recorded {test}: {status} ({res.duration_s:.1f}s)")
        return test, rec, scripts

    results = run_parallel(one, list(test_files), workers)
    for test, rec, _ in results:
        tmap.tests[test] = rec
    if runner.kind == "node":
        _merge_node_coverage(template, tmap, [(test, scripts) for test, _, scripts in results])
    tmap.file_hashes = hashes
    return tmap


def run_parallel(fn: Callable[[Any], Any], items: list[Any], workers: int) -> list[Any]:
    """`map` over a thread pool that, when interrupted (Ctrl-C, SIGTERM),
    kills every sandboxed process first, so the pool can shut down at once."""
    from .. import sandbox
    sandbox.allow_runs()
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        return list(pool.map(fn, items))
    except BaseException:
        sandbox.terminate_all()
        pool.shutdown(wait=True, cancel_futures=True)
        sandbox.terminate_all()  # anything started between the two calls
        raise
    finally:
        pool.shutdown(wait=True)


def _node_scripts(ws: Path, inside: str) -> list[tuple[str, list[dict[str, Any]]]]:
    """(repo-relative script, V8 function records) for the repository's own
    scripts in one test file's coverage output (`<ws>/.repo-ai/run/cov`),
    read without following links the sandbox may have planted."""
    prefix = inside.rstrip("/") + "/"
    out: list[tuple[str, list[dict[str, Any]]]] = []
    try:
        names = sorted(n for n in os.listdir(ws / RUN_DIR / "cov") if n.endswith(".json"))
    except OSError:
        names = []
    for name in names:
        try:
            raw = isolate.read_inside(ws, f"{RUN_DIR}/cov/{name}", MAX_RECORD_BYTES)
            data = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for script in data.get("result") or []:
            url = str(script.get("url") or "")
            if not url.startswith("file://"):
                continue
            path = unquote(urlparse(url).path)
            if not path.startswith(prefix) or "/node_modules/" in path or f"/{RUN_DIR}/" in path:
                continue
            out.append((path[len(prefix):], script.get("functions") or []))
    return out


def _merge_node_coverage(template: Path, tmap: TestMap,
                         per_test_scripts: list[tuple[str, list[tuple[str, list[dict[str, Any]]]]]]) -> None:
    texts: dict[str, list[int]] = {}

    def line_of(path: str, offset: int) -> int:
        starts = texts.get(path)
        if starts is None:
            try:
                text = (template / path).read_text("utf-8", errors="replace")
            except OSError:
                text = ""
            starts = [0]
            for idx, ch in enumerate(text):
                if ch == "\n":
                    starts.append(idx + 1)
            texts[path] = starts
        import bisect
        return bisect.bisect_right(starts, offset)

    funcs: dict[str, dict[tuple[int, int, str], int]] = {}
    per_test: dict[str, dict[str, set[tuple[int, int, str]]]] = {}
    for test, scripts in per_test_scripts:
        for rel, functions in scripts:
            for fn in functions:
                ranges = fn.get("ranges") or []
                if not ranges:
                    continue
                first = ranges[0]
                key = (line_of(rel, int(first.get("startOffset", 0))),
                       line_of(rel, max(int(first.get("endOffset", 0)) - 1, 0)),
                       str(fn.get("functionName") or ""))
                funcs.setdefault(rel, {}).setdefault(key, 0)
                if int(first.get("count", 0)) > 0:
                    per_test.setdefault(test, {}).setdefault(rel, set()).add(key)
    for rel, keys in funcs.items():
        ordered = sorted(keys)
        tmap.functions[rel] = [list(k) for k in ordered]
        index = {k: n for n, k in enumerate(ordered)}
        for test, files in per_test.items():
            if rel in files:
                tmap.tests[test].setdefault("functions", {})[rel] = sorted(index[k] for k in files[rel])
