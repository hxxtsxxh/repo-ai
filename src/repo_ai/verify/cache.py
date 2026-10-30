"""What verification may safely remember between runs, and when it must
forget: the identity of the test environment, base-revision outcomes, and
measured run times. All local (the repository's repo-ai state directory),
never committed, never sent anywhere.

**Environment identity** (`environment_key`) is what a test outcome can
depend on besides the source: repo-ai's version (its reporters), the
sandbox backend and container image digest, the interpreter or Node binary
(path, size, modification time), the installed distributions it sees and
the read-only dependency directories (`node_modules` and its lock markers):
every entry in them, by path, type, size, modification and change time, so a
package edited in place counts as well as one added, removed or upgraded,
and the test command with every rule applied to it. Any change gives a new key, and
nothing recorded under the old key is used.

**Base outcomes** (`BaselineCache`) are keyed by that identity plus the base
revision's *tree*. A base outcome is only ever used to classify a failure as
new or pre-existing, so the two directions are not equally safe:
- a cached **pass** can only make a failure look new: it is used after one
  observation;
- a cached **fail** could hide a new failure as pre-existing: it is used
  only after two independent base runs agreed and none disagreed. A test
  that has both passed and failed at the same base is marked flaky and is
  always re-run.

**Timings** (`Timings`) feed the cost model (`strategy`). A wrong timing can
make a run slower, never make a result wrong.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .. import __version__

BASELINE_FILE = "verify-baseline.json"
TIMINGS_FILE = "verify-timings.json"
MAX_BASELINE_ENTRIES = 20_000
MAX_TIMING_ENVS = 8
_LOCK_MARKERS = (".package-lock.json", ".modules.yaml", ".yarn-state.yml", ".yarn-integrity")


def _stat_id(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return f"{path}:missing"
    return f"{path}:{st.st_size}:{st.st_mtime_ns}"


# how a base outcome is derived: entries recorded under other rules are never reused (2: a base run cut by
# the time limit is no longer recorded as failing, and an exit status 0 no longer outranks the report)
RULES = "base-outcome-rules/2"


# past this many entries a dependency directory is not identified at all: its key never matches,
# so nothing recorded under it is reused (a cost, never a wrong result)
MAX_TREE_ENTRIES = 400_000
# written by the runs themselves, never read as an input: bytecode, and tool caches at the top
_SKIP_ANYWHERE = frozenset({"__pycache__"})
_SKIP_AT_TOP = frozenset({".cache", ".vite"})


def _tree_id(path: str) -> str:
    """Every entry under `path`, by relative path, type, size, modification
    and change time (symbolic links by their target, never followed). An
    in-place edit changes the modification time, and the change time even
    where the modification time is set back (`touch -r`; nothing but the
    kernel sets it). Copying the tree changes it too: that only costs a
    re-run. About 6 µs an entry when the metadata is cached."""
    digest, count, stack = hashlib.sha256(), 0, [""]
    while stack:
        rel = stack.pop()
        try:
            entries = sorted(os.scandir(os.path.join(path, rel) if rel else path), key=lambda e: e.name)
        except OSError:
            if not rel:
                return f"{path}:unreadable"
            digest.update(f"{rel}\0unreadable\n".encode())
            continue
        for e in entries:
            if e.name in _SKIP_ANYWHERE or (not rel and e.name in _SKIP_AT_TOP):
                continue
            count += 1
            if count > MAX_TREE_ENTRIES:
                return f"{path}:too-large:{uuid.uuid4().hex}"
            sub = f"{rel}/{e.name}" if rel else e.name
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                digest.update(f"{sub}\0gone\n".encode())
                continue
            if e.is_symlink():
                try:
                    kind = "l:" + os.readlink(e.path)
                except OSError:
                    kind = "l?"
            elif e.is_dir(follow_symlinks=False):
                kind = "d"
                stack.append(sub)
            else:
                kind = "f"
            digest.update(f"{sub}\0{kind}\0{st.st_size}\0{st.st_mtime_ns}\0{st.st_ctime_ns}\n".encode())
    return f"{path}:{digest.hexdigest()[:16]}"


def runner_identity(runner) -> dict[str, Any]:
    data = runner.to_json()
    return {k: data[k] for k in sorted(data) if k not in {"source", "notes"}}


def environment_key(executor, runner, links: dict[str, str] | None = None) -> str:
    """Everything besides the source that a test outcome can depend on.
    `links`: the read-only dependency directories (workspace-relative ->
    source), when the executor is not yet bound to a workspace."""
    parts: list[str] = [__version__, executor.backend.name, json.dumps(runner_identity(runner), sort_keys=True)]
    toolchain = "node" if runner.kind == "node" else "python"
    if executor.is_container:
        backend = executor.backend
        images = getattr(backend, "images", {}) or {}
        parts.append(str(images.get(toolchain, "")))
        try:
            parts.append(str(backend.image_digest(toolchain)))
        except Exception:  # noqa: BLE001 - no digest: identity by reference only
            parts.append("no-digest")
    else:
        binary = executor.node if toolchain == "node" else executor.python
        parts.append(_stat_id(binary))
        for d in executor.site_dirs:
            parts.append(_tree_id(d))
    for rel, src in sorted((links if links is not None else executor.links).items()):
        parts.append(f"{rel}->{_tree_id(src)}")
        for marker in _LOCK_MARKERS:
            p = os.path.join(src, marker)
            if os.path.exists(p):
                parts.append(_stat_id(p))
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]


STATIC_ENV_VERSION = 1
_MAX_STATIC_PATHS = 64


def _file_id(path: str) -> str:
    """A binary or a metadata file by what `stat` says (following links: a
    re-pointed `bin/python` is another interpreter)."""
    try:
        st = os.stat(path)
    except OSError:
        return f"{path}:missing"
    return f"{path}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}:{st.st_ino}"


def _static_digest(files: list[str], dirs: list[str]) -> tuple[str, str]:
    """(interpreter id, digest) of the recorded paths, by metadata only."""
    interpreter_id = hashlib.sha256("\0".join(_file_id(f) for f in files).encode()).hexdigest()[:24]
    trees = "\0".join(_tree_id(d) for d in dirs)
    return interpreter_id, hashlib.sha256(f"{interpreter_id}\0{trees}".encode()).hexdigest()[:32]


def static_environment(executor, runner, links: dict[str, str] | None = None) -> dict[str, Any]:
    """The part of the environment identity that can be checked again from
    paths alone (no interpreter, no repository code): recorded with evidence
    so `repo-ai evidence` and the completion gate can tell that installed
    packages or the interpreter changed after the run (X13b). The binary and
    a virtualenv's `pyvenv.cfg` by `stat`; the site-packages and read-only
    dependency directories by `_tree_id`. A container's image is not
    re-checked (that would need the container engine)."""
    node = runner.kind == "node"
    files: list[str] = []
    dirs: list[str] = []
    unchecked: list[str] = []
    if executor.is_container:
        unchecked.append("container image")
    else:
        binary = executor.node if node else executor.python
        files.append(binary)
        if not node:
            exe = Path(os.path.abspath(binary))
            files += [str(c) for c in dict.fromkeys((exe.parent / "pyvenv.cfg", exe.parent.parent / "pyvenv.cfg"))
                      if c.is_file()]
        dirs += executor.site_dirs
    dirs += [src for _, src in sorted((links if links is not None else executor.links).items())]
    dirs = [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]  # a listed site directory may not exist
    interpreter_id, digest = _static_digest(files, dirs)
    return {"version": STATIC_ENV_VERSION, "toolchain": "node" if node else "python",
            "interpreter": files[0] if files else "", "interpreter_id": interpreter_id,
            "files": files, "dirs": dirs, "digest": digest, **({"unchecked": unchecked} if unchecked else {})}


def static_environment_change(recorded: object) -> tuple[str, str]:
    """(status, detail) of a recorded `static_environment` now:
    "unchanged", "changed" (detail: what) or "not recorded" (a record
    written before it existed). Paths only: `stat`, `scandir` and `readlink`
    of the recorded paths, nothing opened or executed, so the completion
    gate can afford it on every stop. Anything unreadable is "changed"."""
    if recorded is None:
        return "not recorded", "the record does not identify its test environment (written before 2026-10-25)"
    if not isinstance(recorded, dict) or recorded.get("version") != STATIC_ENV_VERSION:
        return "changed", "the recorded environment identity has an unknown form"
    files, dirs = recorded.get("files"), recorded.get("dirs")
    if not (isinstance(files, list) and isinstance(dirs, list) and len(files) + len(dirs) <= _MAX_STATIC_PATHS
            and all(isinstance(p, str) and os.path.isabs(p) for p in files + dirs)):
        return "changed", "the recorded environment identity has an unknown form"
    gone = [p for p in files + dirs if not os.path.exists(p)]
    if gone:
        return "changed", f"{gone[0]} no longer exists"
    interpreter_id, digest = _static_digest(files, dirs)
    if digest == recorded.get("digest"):
        return "unchanged", ""
    if interpreter_id != recorded.get("interpreter_id"):
        return "changed", f"the interpreter changed ({files[0] if files else '?'})"
    return "changed", "installed packages or dependency directories changed"


def tree_of(root: Path, commit: str) -> str:
    """The base commit's tree id ("" when unknown): two commits with the same
    tree have the same base outcomes."""
    if not commit:
        return ""
    try:
        out = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "--end-of-options", f"{commit}^{{tree}}"],
                             cwd=root, capture_output=True, text=True, timeout=30, check=False,
                             stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out if len(out) >= 40 else ""


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("version") == 1 else {}


def _save(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), "utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # a cache that cannot be written only costs time


class BaselineCache:
    """Outcomes of tests (or whole test files) at a base tree, per environment."""

    def __init__(self, state_dir: Path, env_key: str, base_tree: str):
        self.path = state_dir / BASELINE_FILE
        self.env_key = env_key
        self.base_tree = base_tree
        self.enabled = bool(env_key and base_tree)
        self._data = _load(self.path) if self.enabled else {}
        self._entries: dict[str, dict[str, Any]] = self._data.get("entries") or {}
        self.hits = 0
        self.dirty = False

    def _key(self, scope: str, ident: str) -> str:
        return hashlib.sha256(f"{RULES}\0{self.env_key}\0{self.base_tree}\0{scope}\0{ident}".encode()).hexdigest()[:32]

    def get(self, scope: str, ident: str) -> tuple[str, list[str]] | None:
        """("pass" | "fail", failing ids) when the cache may be used for it."""
        if not self.enabled:
            return None
        e = self._entries.get(self._key(scope, ident))
        if not isinstance(e, dict) or e.get("flaky"):
            return None
        if e.get("o") == "pass" and int(e.get("n", 0)) >= 1:
            self.hits += 1
            return "pass", []  # see `source` for where it was observed
        if e.get("o") == "fail" and int(e.get("n", 0)) >= 2:
            self.hits += 1
            return "fail", [str(x) for x in e.get("ids") or []][:200]
        return None

    def source(self, scope: str, ident: str) -> str:
        """Where a usable entry was first observed: "recorded" (a `--record`
        run of the clean base) or "cached" (an earlier base re-check)."""
        e = self._entries.get(self._key(scope, ident))
        return "recorded" if isinstance(e, dict) and e.get("src") == "record" else "cached"

    def put(self, scope: str, ident: str, outcome: str, ids: list[str] | None = None, src: str = "") -> None:
        if not self.enabled or outcome not in {"pass", "fail"}:
            return
        key = self._key(scope, ident)
        e = self._entries.get(key)
        ids_sorted = sorted(ids or [])[:200]
        if isinstance(e, dict) and not e.get("flaky"):
            if e.get("o") == outcome and (outcome == "pass" or e.get("ids") == ids_sorted):
                e["n"] = int(e.get("n", 0)) + 1
                e["t"] = int(time.time())
            else:
                e.update({"flaky": True, "t": int(time.time())})  # disagreeing runs: never trusted again
        elif not isinstance(e, dict):
            self._entries[key] = {"o": outcome, "n": 1, "ids": ids_sorted, "t": int(time.time()),
                                  **({"src": src} if src else {})}
        self.dirty = True

    def save(self) -> None:
        if not (self.enabled and self.dirty):
            return
        entries = self._entries
        if len(entries) > MAX_BASELINE_ENTRIES:
            keep = sorted(entries.items(), key=lambda kv: -int(kv[1].get("t", 0)))[:MAX_BASELINE_ENTRIES]
            entries = dict(keep)
        _save(self.path, {"version": 1, "entries": entries})


class Timings:
    """Measured wall times per environment: the full suite as one process,
    each test file run alone, and the fixed cost of one sandboxed process."""

    def __init__(self, state_dir: Path, env_key: str):
        self.path = state_dir / TIMINGS_FILE
        self.env_key = env_key
        self._data = _load(self.path) or {"version": 1, "envs": {}}
        envs = self._data.setdefault("envs", {})
        self.env: dict[str, Any] = envs.get(env_key) if isinstance(envs.get(env_key), dict) else {}
        self.dirty = False

    @property
    def full_s(self) -> float | None:
        v = self.env.get("full")
        return float(v) if isinstance(v, (int, float)) and v > 0 else None

    @property
    def startup_s(self) -> float | None:
        v = self.env.get("startup")
        return float(v) if isinstance(v, (int, float)) and v > 0 else None

    @property
    def targeted_ratio(self) -> float | None:
        """Measured / estimated wall time of passing selection runs: parallel
        processes contend for the machine, which the per-file sum ignores."""
        v = self.env.get("ratio")
        return float(v) if isinstance(v, (int, float)) and v > 0 else None

    def note_ratio(self, ratio: float) -> None:
        if 0.05 < ratio < 50:
            self.env["ratio"] = self._blend(self.env.get("ratio"), ratio)
            self.dirty = True

    @property
    def full_unusable(self) -> str:
        """Why the full suite's result cannot be attributed in this environment
        ("" when it can): it is then never chosen only for speed."""
        v = self.env.get("full_unusable")
        return v if isinstance(v, str) else ""

    def note_full_unusable(self, why: str) -> None:
        self.env["full_unusable"] = why[:200]
        self.dirty = True

    def file_s(self, test: str) -> float | None:
        v = (self.env.get("files") or {}).get(test)
        return float(v) if isinstance(v, (int, float)) and v > 0 else None

    @staticmethod
    def _blend(old: Any, new: float) -> float:
        return round(new if not isinstance(old, (int, float)) or old <= 0 else 0.5 * float(old) + 0.5 * new, 3)

    def note_full(self, seconds: float) -> None:
        self.env["full"] = self._blend(self.env.get("full"), seconds)
        self.dirty = True

    def note_file(self, test: str, seconds: float, own_process: bool = True) -> None:
        files = self.env.setdefault("files", {})
        files[test] = self._blend(files.get(test), seconds)
        self.dirty = True
        if not own_process:
            # a share of a batch: costs the batch paid once (a session fixture, a heavy import) were
            # charged to whichever file came first, so it says nothing about the file's own worst case
            return
        # the slowest recent time of the file in a process of its own (decaying slowly): what a
        # watchdog budget is based on, so one fast run never shrinks it the way it moves the blend
        peaks = self.env.setdefault("peaks", {})
        old = peaks.get(test)
        prev = 0.8 * float(old) if isinstance(old, (int, float)) and old > 0 else 0.0
        peaks[test] = round(max(seconds, prev), 3)
        self.dirty = True

    def peak_s(self, test: str) -> float | None:
        v = (self.env.get("peaks") or {}).get(test)
        return float(v) if isinstance(v, (int, float)) and v > 0 else None

    def note_startup(self, seconds: float) -> None:
        if seconds > 0:
            self.env["startup"] = self._blend(self.env.get("startup"), seconds)
            self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        envs = self._data.setdefault("envs", {})
        self.env["t"] = int(time.time())
        envs[self.env_key] = self.env
        if len(envs) > MAX_TIMING_ENVS:
            for k in sorted(envs, key=lambda k: int((envs[k] or {}).get("t", 0)))[:len(envs) - MAX_TIMING_ENVS]:
                envs.pop(k, None)
        _save(self.path, self._data)
