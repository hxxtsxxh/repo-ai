"""Disposable execution workspaces: tests never run in the developer's tree.

`verify --run` and `--record` execute repository code. Even inside an
OS-enforced sandbox, a sandbox whose writable workspace *is* the repository
lets a test rewrite source files, uncommitted work or `.git`, and read ignored
secrets beside the code. So every execution gets a fresh copy instead.

**What the copy holds:**
- every tracked file and every untracked, non-ignored file, *as it is in the
  working tree*: staged and unstaged edits included, deleted files absent;
- symlinks only when they stay inside the copy.

**What stays out:**
- `.git`, `.repo-ai/` and other agent state;
- every git-ignored file, except a version file the project's build backend is declared to write
  (setuptools-scm `version_file`/`write_to`, hatch-vcs `version-file` in pyproject.toml): without it the package
  cannot be imported (`No module named 'humanize._version'`). Only that declared path, only a small `.py` file
  named like a version file, inside the repository, not a link and not credential-like;
- untracked files that look like credentials (`.env`, `*.pem`, `id_rsa`, …),
  listed as *withheld*.

**Dependencies:** ignored directories such as `node_modules` and a repository
`.venv` are exposed **read-only**, never copied and never writable.

**Editable installs:** an interpreter whose site-packages points at this
repository (`pip install -e .`) has those paths redirected to the copy, so the
tests import the code under verification, not the original.

**Integrity:** `snapshot()` before and after a run detects any change to the
source tree, `.git` and ignored files included. Copies use copy-on-write
clones where the filesystem supports them (APFS, btrfs, XFS) and plain copies
elsewhere; cleanup is unconditional.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .. import gitbin
from ..config import DEFAULT_SECRET_PATH_GLOBS
from ..security import path_is_secretlike

# never copied, whatever git says about them
STATE_PREFIXES = (".git/", ".repo-ai/", ".bob/", ".claude/settings.local.json")
# ignored directories that tests need to *read*: exposed read-only, never copied
DEPENDENCY_DIRS = ("node_modules",)
WS_MARKER = ".repo-ai-workspace.json"
STALE_AFTER_S = 6 * 3600


class IsolationError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# integrity snapshots
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Snapshot:
    """Metadata of every entry under the root, and the content hash of every
    working-tree file (tracked or untracked, not ignored)."""
    root: str
    stat: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    content: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0
    skip: tuple[str, ...] = ()
    head: str = ""  # the commit HEAD resolved to (refs themselves are not compared)

    def changes(self, other: Snapshot) -> list[str]:
        out = []
        for rel in sorted(set(self.stat) | set(other.stat)):
            a, b = self.stat.get(rel), other.stat.get(rel)
            if a != b:
                out.append(f"{rel}: " + ("created" if a is None else "deleted" if b is None else "modified"))
        for rel in sorted(set(self.content) | set(other.content)):
            if self.content.get(rel) != other.content.get(rel) and not any(o.startswith(rel + ":") for o in out):
                out.append(f"{rel}: content changed")
        return out


class ReportTooLarge(ValueError):
    pass


def read_inside(base: Path, rel: str, limit: int) -> bytes | None:
    """The bytes of `base/rel`, a file a sandboxed process may have written,
    or None when it is missing or is not a regular file. No symbolic link
    under `base` is followed and nothing but a regular file is opened: a
    test could replace its report with a FIFO (the read would block), a
    device (it would never end) or a link to a file outside the workspace.
    Raises `ReportTooLarge` past `limit` bytes."""
    import stat as st_
    parts = [x for x in PurePosixPath(rel).parts if x not in {"", "."}]
    if not parts or ".." in parts:
        return None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or os.open not in os.supports_dir_fd:  # Windows: check each component, then read
        cur = Path(base)
        for part in parts:
            cur = cur / part
            try:
                info = os.lstat(cur)
            except OSError:
                return None
            if st_.S_ISLNK(info.st_mode) or int(getattr(info, "st_reparse_tag", 0) or 0):
                return None
        if not st_.S_ISREG(info.st_mode):
            return None
        if info.st_size > limit:
            raise ReportTooLarge(rel)
        try:
            with open(cur, "rb") as fh:
                data = fh.read(limit + 1)
        except OSError:
            return None
        if len(data) > limit:
            raise ReportTooLarge(rel)
        return data
    fds: list[int] = []
    try:
        try:
            fds.append(os.open(base, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)))
            for part in parts[:-1]:
                fds.append(os.open(part, os.O_RDONLY | nofollow | getattr(os, "O_DIRECTORY", 0), dir_fd=fds[-1]))
            fd = os.open(parts[-1], os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0), dir_fd=fds[-1])
        except OSError:  # missing, a link (ELOOP) or not a directory
            return None
        fds.append(fd)
        info = os.fstat(fd)
        if not st_.S_ISREG(info.st_mode):
            return None
        if info.st_size > limit:
            raise ReportTooLarge(rel)
        chunks, total = [], 0
        while total <= limit:
            try:
                chunk = os.read(fd, min(1 << 20, limit + 1 - total))
            except OSError:
                return None
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > limit:
            raise ReportTooLarge(rel)
        return b"".join(chunks)
    finally:
        for f in reversed(fds):
            try:
                os.close(f)
            except OSError:
                pass


def _skipped(rel: str, skip: tuple[str, ...], is_dir: bool = False, keep: frozenset[str] = frozenset()) -> bool:
    """`rel` is left out by `skip`: a prefix (a directory, left out whole),
    `re:<regex>` for files whose whole path matches, or `redir:<regex>` for
    directories that are not recorded (`_walked_only`) but still walked, so
    a file there that no `re:` pattern matches is checked. A `re:` pattern
    never leaves out a file in `keep` (what git tracked or showed when the
    first snapshot was taken)."""
    for s in skip:
        if s.startswith("re:"):
            if not is_dir and rel not in keep and re.fullmatch(s[3:], rel):
                return True
        elif s.startswith("redir:"):
            continue
        elif (rel + "/").startswith(s) or rel.startswith(s):
            return True
    return False


def _walked_only(rel: str, skip: tuple[str, ...]) -> bool:
    return any(s.startswith("redir:") and re.fullmatch(s[6:], rel) for s in skip)


def snapshot(root: Path, files: list[str] | None = None,
             skip: tuple[str, ...] = (".repo-ai/state/",)) -> Snapshot:
    """`skip` is repo-ai's own state directory, which repo-ai itself writes
    (evidence, runtime records); tests never can. See `_skipped`."""
    started = time.monotonic()
    root = root.resolve()
    snap = Snapshot(str(root), skip=skip)
    listing = files if files is not None else worktree_files(root)[0]
    keep = frozenset(listing)  # tracked and visible files: always checked, whatever a pattern says
    # each directory carries its repository-relative prefix: building `rel` from it is what
    # `Path(e.path).relative_to(root).as_posix()` returned, without a Path per entry (that was most of
    # the snapshot's time on a project with a virtualenv: two snapshots per verify run)
    stack: list[tuple[str, str]] = [(str(root), "")]
    while stack:
        cur, prefix = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except OSError:
            continue
        for e in entries:
            rel = prefix + e.name
            is_dir = e.is_dir(follow_symlinks=False)
            if _skipped(rel, skip, is_dir, keep):
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            kind = "l" if e.is_symlink() else "d" if is_dir else "f"
            if kind == "d":
                if not _walked_only(rel, skip):
                    snap.stat[rel] = ("d", st.st_mode)
                stack.append((e.path, rel + "/"))
            elif kind == "l":
                snap.stat[rel] = ("l", os.readlink(e.path))
            else:
                snap.stat[rel] = ("f", st.st_size, st.st_mtime_ns, st.st_mode, st.st_ino)
    for rel in listing:
        if _skipped(rel, skip, keep=keep):
            continue
        p = root / rel
        if p.is_file() and not p.is_symlink():
            h = hashlib.sha256()
            try:
                with p.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
            except OSError:
                continue
            snap.content[rel] = h.hexdigest()
    snap.seconds = time.monotonic() - started
    return snap


# --------------------------------------------------------------------------
# what goes into a workspace
# --------------------------------------------------------------------------
def _git_list(root: Path, *args: str) -> list[str]:
    out = subprocess.run([gitbin.git(), *args], cwd=root, capture_output=True, timeout=120, check=False,
                         stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise IsolationError(f"git {args[0]} failed: {out.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return [p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def worktree_files(root: Path) -> tuple[list[str], list[str]]:
    """(files to copy, untracked files withheld as credential-like)."""
    tracked = set(_git_list(root, "ls-files", "-z", "--cached", "--recurse-submodules"))
    untracked = set(_git_list(root, "ls-files", "-z", "--others", "--exclude-standard"))
    withheld = sorted(p for p in untracked - tracked if path_is_secretlike(p, DEFAULT_SECRET_PATH_GLOBS))
    keep = sorted(p for p in (tracked | untracked) - set(withheld)
                  if not p.startswith(STATE_PREFIXES) and p not in STATE_PREFIXES
                  and ((root / p).is_symlink() or (root / p).is_file()))
    return keep, withheld


_VERSION_FILE = re.compile(r"_{0,2}version_{0,2}\.py|_version_info\.py")
MAX_VERSION_FILE = 65_536


def generated_version_files(root: Path) -> list[str]:
    """Version files pyproject.toml declares a build backend writes (setuptools-scm `version_file` / `write_to`,
    hatch-vcs `version-file`), which git usually ignores. Only such declared paths that exist as small regular
    `.py` files named like a version file, inside the repository, outside agent state, not credential-like."""
    try:
        text = (root / "pyproject.toml").read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        tool = tomllib.loads(text).get("tool") or {}
    except (tomllib.TOMLDecodeError, AttributeError):
        return []
    scm = tool.get("setuptools_scm") or {}
    hatch_vcs = (((tool.get("hatch") or {}).get("build") or {}).get("hooks") or {}).get("vcs") or {}
    declared = [scm.get("version_file"), scm.get("write_to"), hatch_vcs.get("version-file")]
    out: list[str] = []
    for raw in declared:
        if not isinstance(raw, str) or not raw:
            continue
        rel = PurePosixPath(raw.replace("\\", "/"))
        folded = str(rel).casefold()  # case-insensitive filesystems: `.REPO-AI/` is `.repo-ai/`
        if rel.is_absolute() or ".." in rel.parts or not _VERSION_FILE.fullmatch(rel.name) \
                or folded.startswith(tuple(p.casefold() for p in STATE_PREFIXES)) \
                or rel.parts[0].casefold() == ".git" or path_is_secretlike(str(rel), DEFAULT_SECRET_PATH_GLOBS):
            continue
        src = root / rel
        try:
            if src.is_symlink() or not src.is_file() or src.stat().st_size > MAX_VERSION_FILE \
                    or root.resolve() not in src.resolve().parents:
                continue
        except OSError:
            continue
        if str(rel) not in out:
            out.append(str(rel))
    return out


def _copy_generated(ws: Workspace, root: Path, present: set[str]) -> None:
    """Copy the declared version files that the copy does not already hold. Only into real directories of the copy
    (never through a link the copy holds), never over anything, and a failure leaves the file out instead of
    failing the run. A base copy gets the checkout's file: the version string is the working tree's."""
    for rel in generated_version_files(root):
        dst = ws.path / rel
        if rel in present or dst.exists() or dst.is_symlink():
            continue
        parent, blocked = ws.path, False
        for part in PurePosixPath(rel).parts[:-1]:
            parent = parent / part
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                blocked = True
                break
        if blocked:
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(root / rel, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as fh:
                data = fh.read(MAX_VERSION_FILE + 1)
            if len(data) > MAX_VERSION_FILE:
                continue
            with open(dst, "xb") as out:
                out.write(data)
        except OSError:
            continue
        ws.files.append(rel)
        ws.generated.append(rel)


def dependency_dirs(root: Path, files: list[str]) -> list[str]:
    """Ignored dependency directories beside a package manifest: the root's
    and each workspace package's `node_modules`."""
    manifests = {str(PurePosixPath(f).parent) for f in files if PurePosixPath(f).name == "package.json"}
    out: list[str] = []
    for d in sorted(manifests):
        rel = "node_modules" if d in {"", "."} else f"{d}/node_modules"
        p = root / rel
        if p.is_dir() and not p.is_symlink() and not any(rel.startswith(o + "/") for o in out):
            out.append(rel)
    return out


# --------------------------------------------------------------------------
# copying
# --------------------------------------------------------------------------
_clonefile: Any = None


def _clonefile_fn() -> Any:
    """macOS `clonefile(2)`, or False where it cannot be loaded."""
    global _clonefile
    if _clonefile is None:
        import ctypes
        try:
            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            fn = libc.clonefile
            fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
            fn.restype = ctypes.c_int
            _clonefile = fn
        except (OSError, AttributeError):
            _clonefile = False
    return _clonefile


def _clone(src: Path, dst: Path) -> bool:
    """Copy-on-write clone of one regular file; False when unsupported."""
    system = platform.system()
    if system == "Darwin":
        if not _clonefile_fn():
            return False
        # CLONE_NOFOLLOW | CLONE_NOOWNERCOPY
        return _clonefile(os.fsencode(src), os.fsencode(dst), 0x0001 | 0x0002) == 0
    if system == "Linux":
        import fcntl
        try:
            with open(src, "rb") as s, open(dst, "wb") as d:
                fcntl.ioctl(d.fileno(), 0x40049409, s.fileno())  # FICLONE
            shutil.copystat(src, dst)
            return True
        except OSError:
            try:
                os.unlink(dst)
            except OSError:
                pass
            return False
    return False


def _copy_file(src: Path, dst: Path, method: list[str]) -> None:
    if method[0] != "copy" and _clone(src, dst):
        method[0] = "clone"
        return
    if method[0] == "unknown":
        method[0] = "copy"
    shutil.copy2(src, dst, follow_symlinks=False)


@dataclass(slots=True)
class Workspace:
    """A disposable copy of the change under verification."""
    path: Path
    source: Path
    files: list[str]
    withheld: list[str] = field(default_factory=list)
    skipped_links: list[str] = field(default_factory=list)
    readonly: dict[str, str] = field(default_factory=dict)   # workspace rel -> source abs (dependency dirs)
    method: str = "copy"
    seconds: float = 0.0
    bytes: int = 0
    origin: str = "working tree"
    generated: list[str] = field(default_factory=list)  # declared, git-ignored version files copied in

    def summary(self) -> dict[str, Any]:
        return {"origin": self.origin, "files": len(self.files), "bytes": self.bytes,
                "method": self.method, "seconds": round(self.seconds, 3),
                "generated_version_files": self.generated,
                "withheld_credential_like": self.withheld[:50],
                "read_only_dependencies": sorted(self.readonly),
                "skipped_symlinks": self.skipped_links[:50]}

    def expose_dependencies(self, how: str) -> None:
        """`link`: a symlink to the source directory (host sandboxes, which allow
        it read-only). `mountpoint`: an empty directory a container mounts the
        source directory on, read-only."""
        for rel, src in self.readonly.items():
            target = self.path / rel
            if target.exists() or target.is_symlink():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if how == "link":
                os.symlink(src, target, target_is_directory=True)
            else:
                target.mkdir()

    def clone(self, label: str = "ws") -> Workspace:
        """Another disposable copy with identical content, taken from this one
        before anything ran in it: parallel test processes each get their own,
        so tests that use fixed files (a SQLite database in the working
        directory) cannot collide, just as when the suite runs one at a time."""
        started = time.monotonic()
        tree = _clone_tree(self.path, label, keep={*self.files, *self.readonly})
        if tree is not None:  # one copy-on-write clone of the whole tree (APFS): ~15x faster than file by file
            twin = Workspace(tree, self.source, list(self.files), withheld=list(self.withheld),
                             skipped_links=list(self.skipped_links), readonly=dict(self.readonly),
                             origin=f"{self.origin} (parallel copy)", method="clone")
            twin.bytes, twin.seconds = self.bytes, time.monotonic() - started
            return twin
        path = _new_dir(label)
        twin = Workspace(path, self.source, [], withheld=list(self.withheld),
                         skipped_links=list(self.skipped_links), readonly=dict(self.readonly),
                         origin=f"{self.origin} (parallel copy)")
        method = ["unknown"]
        try:
            for rel in self.files:
                src, dst = self.path / rel, path / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_symlink():
                    os.symlink(os.readlink(src), dst)
                elif src.is_file():
                    _copy_file(src, dst, method)
                else:
                    continue
                twin.files.append(rel)
        except BaseException:
            _remove(path)
            raise
        twin.method, twin.bytes = method[0] if method[0] != "unknown" else "copy", self.bytes
        twin.seconds = time.monotonic() - started
        return twin

    def cleanup(self) -> None:
        _remove(self.path)

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()


def run_dir(ws: Path, rel: str) -> Path:
    """Create `rel` (repo-ai's run directory, under `.repo-ai/`) inside a workspace. A repository that tracks a FILE
    named `.repo-ai` (ordinary source, kept in the workspace) leaves no room for it: say so, not ENOTDIR mid-run."""
    path = ws / rel
    try:
        path.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, NotADirectoryError) as exc:
        home = ws / rel.split("/", 1)[0]
        if os.path.lexists(home) and not home.is_dir():
            raise IsolationError(f"the repository tracks a file named {home.name}; sandboxed runs need a directory of "
                                 "that name in their workspace (out_dir does not move it), so repo-ai cannot run tests "
                                 "in this repository") from exc
        raise
    return path


def _remove(path: Path) -> None:
    def onerror(func, p, _exc):  # read-only files a test left behind
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    if path.exists():
        # never follow a link out of the workspace while deleting it
        if path.is_symlink():
            path.unlink()
            return
        shutil.rmtree(path, onerror=onerror)  # noqa: B026 - onerror is still supported through 3.14


def workspaces_root() -> Path:
    """A private (0700) per-user directory for workspaces, safe in a shared /tmp."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    base = Path(os.environ.get("REPO_AI_WORKSPACES") or Path(tempfile.gettempdir()) / f"repo-ai-ws-{uid}")
    try:
        base.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise IsolationError(f"cannot create the workspace directory {base}: {exc}") from exc
    st = base.lstat()
    if base.is_symlink() or (hasattr(os, "getuid") and st.st_uid != os.getuid()) \
            or (os.name == "posix" and st.st_mode & 0o077):
        raise IsolationError(f"{base} is not a private directory owned by you; refusing to use it")
    return base.resolve()


UNMARKED_GRACE_S = 3600.0
_swept = False


def sweep(max_age_s: float = STALE_AFTER_S) -> int:
    """Remove workspaces left by a process that no longer exists (a killed
    repo-ai). A copy is removed only when its owner is provably gone (its
    marker names a dead process) or it has had no marker for an hour: a copy
    another thread or process is creating right now has no marker yet and is
    never touched."""
    removed = 0
    try:
        base = workspaces_root()
    except IsolationError:
        return 0
    now = time.time()
    for d in base.iterdir():
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        try:
            info = json.loads((d / WS_MARKER).read_text("utf-8"))
            pid, created = int(info.get("pid", 0)), float(info.get("created", 0))
        except (OSError, ValueError):
            if now - mtime > UNMARKED_GRACE_S:
                _remove(d)
                removed += 1
            continue
        if pid == os.getpid() or (_alive(pid) and now - created < max_age_s):
            continue
        _remove(d)
        removed += 1
    return removed


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _clone_tree(src: Path, label: str, keep: set[str]) -> Path | None:
    """A new workspace directory cloned from `src` in one `clonefile(2)` call (macOS; a directory is cloned
    recursively, links as links), with its own ownership marker; None where unsupported, and the caller copies
    file by file. Then it holds exactly what a file-by-file copy would: the `keep` paths (listed files and
    dependency links) and the directories above them; anything else (an empty directory a dropped file left, a
    stray file) is removed, so a test run sees the shipped tree."""
    global _swept
    fn: Any = _clonefile_fn() if platform.system() == "Darwin" else None
    if not fn:
        return None
    if not _swept:
        _swept = True
        sweep()
    path = workspaces_root() / f"{label}-{uuid.uuid4().hex[:12]}"
    if fn(os.fsencode(src), os.fsencode(path), 0x0001 | 0x0002) != 0:  # e.g. not APFS: copy file by file
        _remove(path)
        return None
    try:
        (path / WS_MARKER).write_text(json.dumps({"pid": os.getpid(), "created": time.time()}), "utf-8")
        # decided by filesystem identity, not by name: on a case-insensitive disk `Docs/a.py` and `docs/b.py`
        # share one directory, and a lookup through the filesystem finds both where a string match would not
        def ident(p: Path) -> tuple[int, int] | None:
            try:
                st = os.lstat(p)
            except OSError:
                return None
            return st.st_dev, st.st_ino

        names = {*keep, WS_MARKER}
        dir_names = {"."} | {str(p) for k in names for p in PurePosixPath(k).parents if str(p) not in {"", "."}}
        by_ident: list[set[tuple[int, int]]] = []  # (files, dirs), built only when a name does not match

        def kept(p: Path, rel: str, is_dir: bool) -> bool:
            if rel in (dir_names if is_dir else names):
                return True  # the common case: the name as listed
            if not by_ident:
                files = {i for k in names if (i := ident(path / k)) is not None}
                dirs = {i for d in dir_names if (i := ident(path / d)) is not None}
                by_ident.extend((files, dirs))
            return ident(p) in by_ident[1 if is_dir else 0]

        for dirpath, dirnames, filenames in os.walk(path, topdown=False):
            rel_dir = os.path.relpath(dirpath, path)
            for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                if not kept(Path(dirpath, name), rel, False):
                    os.unlink(os.path.join(dirpath, name))
            if not kept(Path(dirpath), rel_dir, True):
                _remove(Path(dirpath))
    except OSError:  # something the template should not hold (a read-only directory): copy file by file
        _remove(path)
        return None
    except BaseException:
        _remove(path)
        raise
    return path


def _new_dir(label: str) -> Path:
    global _swept
    if not _swept:  # once per process: stale copies come from earlier processes
        _swept = True
        sweep()
    path = workspaces_root() / f"{label}-{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o700)
    (path / WS_MARKER).write_text(json.dumps({"pid": os.getpid(), "created": time.time()}), "utf-8")
    return path


def _place_links(ws: Workspace, root: Path, files: list[str]) -> None:
    """Record the read-only dependency directories. How they appear inside the
    sandbox is the backend's choice (`expose_dependencies`)."""
    for rel in dependency_dirs(root, files):
        if not (ws.path / rel).exists():
            ws.readonly[rel] = str((root / rel).resolve())


def materialize(root: Path, *, label: str = "ws", dependencies: bool = True,
                listing: tuple[list[str], list[str]] | None = None) -> Workspace:
    """A disposable copy of the working tree (see the module docstring).
    `listing`: `worktree_files(root)`, when the caller already has it."""
    started = time.monotonic()
    root = root.resolve()
    files, withheld = listing or worktree_files(root)
    path = _new_dir(label)
    ws = Workspace(path, root, [], withheld=withheld)
    method = ["unknown"]
    try:
        for rel in files:
            src = root / rel
            dst = path / rel
            if dst.parent != path:
                dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                target = os.readlink(src)
                resolved = (src.parent / target).resolve()
                if os.path.isabs(target) or (resolved != root and root not in resolved.parents):
                    ws.skipped_links.append(rel)
                    continue
                os.symlink(target, dst)
                ws.files.append(rel)
                continue
            if not src.is_file():
                continue
            _copy_file(src, dst, method)
            ws.files.append(rel)
            try:
                ws.bytes += src.stat().st_size
            except OSError:
                pass
        _copy_generated(ws, root, set(ws.files))
        _drop_state_paths(path)  # a tracked link `.claude -> conf` and `conf/settings.local.json` reach one too
        ws.files = [f for f in ws.files if (path / f).is_symlink() or (path / f).exists()]
        ws.generated = [f for f in ws.generated if (path / f).exists()]
        if dependencies:
            _place_links(ws, root, files)
    except BaseException:
        _remove(path)
        raise
    ws.method = method[0] if method[0] != "unknown" else "copy"
    ws.seconds = time.monotonic() - started
    return ws


def archived_file(root: Path, commit: str, rel: str) -> bytes | None:
    """The bytes `materialize_commit` writes for tracked file `rel`: `git archive` applies the checkout's
    line-ending settings (core.autocrlf), so this can differ from the raw blob; a file the archive leaves out
    (export-ignore) is restored with `checkout_bytes`."""
    import io
    import tarfile
    archive = subprocess.run([gitbin.git(), "archive", "--format=tar", "--end-of-options", commit, rel],
                             cwd=root.resolve(), capture_output=True, timeout=60, check=False,
                             stdin=subprocess.DEVNULL)
    if archive.returncode != 0:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            member = tar.getmember(rel)
            if not member.isfile() or member.size > 2_000_000:
                return None
            fh = tar.extractfile(member)
            return fh.read() if fh is not None else None
    except KeyError:  # left out of the archive (export-ignore): the workspace holds the checkout bytes
        return checkout_bytes(root, commit, rel)
    except tarfile.TarError:
        return None


# no fsmonitor daemon or untracked cache for the user's repository (`check-attr --stdin` starts the daemon)
_QUIET_GIT = ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"]


def _git_lines(root: Path, args: list[str], stdin: bytes | None = None) -> bytes | None:
    proc = subprocess.run([gitbin.git(), *_QUIET_GIT, *args], cwd=root, input=stdin, capture_output=True, timeout=120,
                          check=False)
    return proc.stdout if proc.returncode == 0 else None


def _check_attr(root: Path, commit: str, names: list[str], paths: list[str]) -> dict[str, dict[str, str]]:
    """Attributes of `paths` as `commit` defines them (`--source`, git >= 2.40; else the working tree's)."""
    data = b"".join(p.encode("utf-8", "surrogateescape") + b"\0" for p in paths)
    out = _git_lines(root, ["check-attr", "--source", commit, "-z", "--stdin", *names], data)
    if out is None:
        out = _git_lines(root, ["check-attr", "-z", "--stdin", *names], data) or b""
    fields = out.split(b"\0")
    attrs: dict[str, dict[str, str]] = {}
    for i in range(0, len(fields) - 2, 3):
        attrs.setdefault(fields[i].decode("utf-8", "surrogateescape"), {})[fields[i + 1].decode()] = fields[i + 2].decode()
    return attrs


def checkout_bytes(root: Path, commit: str, rel: str) -> bytes | None:
    """The bytes a checkout writes for tracked file `rel` of `commit`: git's own conversion (line endings, `ident`,
    `core.eol`, the same as `git archive`), never a re-implementation of it."""
    proc = subprocess.run([gitbin.git(), *_QUIET_GIT, "cat-file", "--filters", "--end-of-options", f"{commit}:{rel}"], cwd=root,
                          capture_output=True, timeout=120, check=False, stdin=subprocess.DEVNULL)
    return proc.stdout if proc.returncode == 0 else None


def _restore_export_attributes(root: Path, commit: str, path: Path, have: set[str]) -> dict[str, int]:
    """`git archive` honours `export-ignore` (a tracked file, often a whole `tests/`, is left out) and `export-subst`
    (`$Format:…$` is replaced), so the archive is not the commit's tracked source. Those files are checked out from
    a temporary index (`git checkout-index`, one process: git's own conversion and modes, and it never writes through
    a symlinked directory). Every restored link is then held to the archive's rule (it resolves inside the
    workspace), after all of them exist, so one link cannot redirect another. Returns the restored paths and sizes."""
    import tempfile
    listing = _git_lines(root, ["ls-tree", "-r", "-z", "--full-tree", "--end-of-options", commit])
    if listing is None:
        raise IsolationError("could not list the base revision's tracked files")
    modes: dict[str, str] = {}
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, _, name = entry.partition(b"\t")
        mode, kind, _sha = meta.decode().split()
        rel = name.decode("utf-8", "surrogateescape")
        pure = PurePosixPath(rel)
        if kind != "blob" or mode not in {"100644", "100755", "120000"} or pure.is_absolute() or ".." in pure.parts \
                or rel.startswith(STATE_PREFIXES):
            continue
        modes[rel] = mode
    present = [p for p in modes if p in have and modes[p] != "120000"]
    subst = [p for p, a in _check_attr(root, commit, ["export-subst"], present).items()
             if a.get("export-subst") == "set"] if present else []
    targets = sorted({p for p in modes if p not in have} | set(subst))
    if not targets:
        return {}
    with tempfile.TemporaryDirectory(prefix="repo-ai-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        for args, stdin in ((["read-tree", commit], None),
                            (["--work-tree", str(path), "checkout-index", "-f", "-z", "--stdin"],
                             b"".join(t.encode("utf-8", "surrogateescape") + b"\0" for t in targets))):
            proc = subprocess.run([gitbin.git(), *_QUIET_GIT, *args], cwd=root, env=env, input=stdin, capture_output=True,
                                  timeout=300, check=False)
            if proc.returncode != 0:  # stderr alone is not failure (an LFS smudge filter reports progress there)
                raise IsolationError("could not restore the base revision's export-ignore/export-subst files: "
                                     + proc.stderr.decode("utf-8", "replace")[:300])
    missing = [t for t in targets if modes[t] != "120000" and not (path / t).is_file()]
    if missing:
        raise IsolationError(f"could not restore the base revision's file {missing[0][:200]}")
    base = path.resolve()
    # every link in the workspace, archived or restored: a restored link can redirect an archived one
    links = sorted({t for t in targets if modes[t] == "120000"} | {h for h in have if (path / h).is_symlink()})
    changed = True
    while changed:  # removing one link can change where another resolves
        changed = False
        for rel in list(links):
            target = path / rel
            if target.is_symlink() and (os.path.isabs(os.readlink(target)) or base not in target.resolve().parents):
                target.unlink()
                links.remove(rel)
                changed = True
    restored: dict[str, int] = {}
    for rel in targets:
        target = path / rel
        if not (target.is_symlink() or target.is_file()):
            continue  # a link removed above, as the archive skips it
        if not target.parent.resolve().is_relative_to(base):
            raise IsolationError(f"a restored file would leave the workspace: {rel[:200]}")
        restored[rel] = target.lstat().st_size if not target.is_symlink() else 0
    return restored


def _drop_state_paths(path: Path) -> None:
    """Remove whatever exists at a state path (`STATE_PREFIXES`) in a materialized workspace, however it got there.
    The archive filter compares names as text; on a case-insensitive filesystem a tracked link `A -> .claude` and a
    file `a/settings.local.json` write `.claude/settings.local.json` without either name matching."""
    for prefix in STATE_PREFIXES:
        target = path / prefix.rstrip("/")
        if prefix.endswith("/"):  # a state DIRECTORY: a tracked regular file named `.bob` or `.repo-ai` is source
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                _remove(target)
        elif target.parent.is_symlink() and (target.exists() or target.is_symlink()):
            # `.claude -> conf` leading to a settings file: remove the route, keep conf's own file
            target.parent.unlink()
        elif target.is_symlink() or target.is_file():
            target.unlink()


def materialize_commit(root: Path, commit: str, *, label: str = "base", dependencies: bool = True) -> Workspace:
    """The tracked files of `commit` (git archive: no hooks or filters run),
    with the same read-only dependency directories as the working tree."""
    import io
    import tarfile
    started = time.monotonic()
    root = root.resolve()
    archive = subprocess.run([gitbin.git(), "archive", "--format=tar", "--end-of-options", commit], cwd=root,
                             capture_output=True, timeout=300, check=False, stdin=subprocess.DEVNULL)
    if archive.returncode != 0:
        raise IsolationError("could not materialise the base revision")
    path = _new_dir(label)
    ws = Workspace(path, root, [], origin=f"commit {commit[:12]}")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            members = []
            for m in tar.getmembers():
                rel = PurePosixPath(m.name)
                # also a state DIRECTORY entry itself (`.repo-ai`, no trailing slash), or an empty one would appear; a
                # tracked regular FILE named `.bob` or `.repo-ai` is ordinary source and is kept
                if rel.is_absolute() or ".." in rel.parts or str(rel).startswith(STATE_PREFIXES) or \
                        (m.isdir() and str(rel) + "/" in STATE_PREFIXES):
                    continue
                if m.issym():
                    resolved = (path / rel.parent / m.linkname).resolve()
                    if os.path.isabs(m.linkname) or path.resolve() not in resolved.parents:
                        ws.skipped_links.append(m.name)
                        continue
                elif not (m.isfile() or m.isdir()):
                    continue
                members.append(m)
            try:
                tar.extractall(path, members=members, filter="data")
            except TypeError:  # pragma: no cover - Python without extraction filters
                tar.extractall(path, members=members)  # noqa: S202 - members validated above
        ws.files = sorted(m.name for m in members if m.isfile() or m.issym())
        ws.bytes = sum(m.size for m in members if m.isfile())
        restored = _restore_export_attributes(root, commit, path, set(ws.files))
        ws.bytes += sum(restored.values())
        _copy_generated(ws, root, set(ws.files) | set(restored))  # the checkout's version file (see the docstring)
        _drop_state_paths(path)
        ws.generated = [f for f in ws.generated if (path / f).exists()]
        # links removed by the restore and anything written into a state path are gone: list only what is there
        ws.files = sorted(f for f in set(ws.files) | set(restored) if (path / f).is_symlink() or (path / f).exists())
        if dependencies:
            _place_links(ws, root, ws.files)
    except BaseException:
        _remove(path)
        raise
    ws.method = "git archive"
    ws.seconds = time.monotonic() - started
    return ws


# --------------------------------------------------------------------------
# editable installs
# --------------------------------------------------------------------------
_MAPPING = re.compile(r"(?m)^MAPPING\s*(?::[^=\n]*)?=\s*(\{.*?\})\s*$", re.S)


def editable_redirects(site_dirs: list[str], source: Path) -> list[str]:
    """Repository-relative directories an editable install puts on sys.path
    (`.pth` path lines, setuptools `__editable__` finders). Read as text;
    nothing in site-packages is executed."""
    source = source.resolve()
    found: list[str] = []

    def add(raw: str) -> None:
        try:
            p = Path(raw).resolve()
        except (OSError, ValueError):
            return
        if p == source or source in p.parents:
            rel = p.relative_to(source).as_posix()
            if rel not in found:
                found.append(rel)

    for site in site_dirs:
        d = Path(site)
        if not d.is_dir():
            continue
        for pth in sorted(d.glob("*.pth")):
            try:
                lines = pth.read_text("utf-8", errors="replace").splitlines()[:200]
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if line and not line.startswith(("#", "import ", "import\t")):
                    add(line if os.path.isabs(line) else str(d / line))
        for finder in sorted(d.glob("__editable__*finder.py")):
            try:
                m = _MAPPING.search(finder.read_text("utf-8", errors="replace"))
                mapping = ast.literal_eval(m.group(1)) if m else {}
            except (OSError, ValueError, SyntaxError):
                mapping = {}
            for target in (mapping.values() if isinstance(mapping, dict) else []):
                if isinstance(target, str):
                    add(str(Path(target).parent))
    return found


_SITE_DIRS = r"""
import json, os, sys, sysconfig
def paths(**v):
    if not v:
        p = sysconfig.get_paths()
    else:  # an explicit scheme: some defaults (macOS framework builds before 3.11) ignore {base}
        names = sysconfig.get_scheme_names()
        scheme = "venv" if "venv" in names else ("nt" if os.name == "nt" else "posix_prefix")
        p = sysconfig.get_paths(scheme=scheme, vars=v)
    return [p["purelib"], p["platlib"]]
exe_dir = os.path.dirname(os.path.abspath(sys.executable))
prefix = os.path.dirname(exe_dir)
cfg = next((c for c in (os.path.join(exe_dir, "pyvenv.cfg"), os.path.join(prefix, "pyvenv.cfg"))
            if os.path.isfile(c)), "")
out = []
if cfg:  # a virtualenv: what site.venv() would add, which -S skips
    out += paths(base=prefix, platbase=prefix)
    with open(cfg, encoding="utf-8", errors="replace") as fh:
        system = any(k.strip().lower() == "include-system-site-packages" and v.strip().lower() == "true"
                     for k, _, v in (line.partition("=") for line in fh))
    if system:
        out += paths()
else:
    out += paths()
print(json.dumps(sorted(set(out))))
"""


@dataclass(slots=True)
class VenvLayout:
    """A virtualenv as its metadata describes it (`static_venv`)."""
    prefix: str        # the virtualenv itself
    base_prefix: str   # the installation `home` names: where its standard library is
    home: str
    site_dirs: list[str]


_CFG_VERSION = re.compile(r"(\d+)\.(\d+)(?:[.\w+-]*)")


def static_venv(python: str) -> VenvLayout | None:
    """What `sys.prefix`, `sys.base_prefix` and `site_dirs` would report for a
    virtualenv's interpreter, read from its `pyvenv.cfg` (as text) and its
    directory layout, for an interpreter that must never run on the host.
    None when the metadata is missing, or disagrees with the layout (no
    base interpreter of that version, no standard library beside it, no
    site-packages for it): such a candidate is refused, never executed to
    find out. The base prefix is where the standard library is (as
    `getpath` finds it), never merely the parent of `home`: the file is the
    repository's, and must not open up a wider directory to the sandbox."""
    exe = Path(os.path.abspath(python))
    venv = exe.parent.parent if exe.parent.name.lower() in {"bin", "scripts"} else exe.parent
    try:  # a regular file only, never through a link: a FIFO would block, a device never end
        raw = read_inside(venv, "pyvenv.cfg", 64 * 1024)
    except ReportTooLarge:
        return None
    if raw is None:
        return None
    cfg = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            cfg[key.strip().lower()] = value.strip()
    home = cfg.get("home", "")
    version = _CFG_VERSION.fullmatch(cfg.get("version") or cfg.get("version_info") or "")
    if not version or not home or not os.path.isabs(home):
        return None
    xy = f"{version.group(1)}.{version.group(2)}"
    windows = os.name == "nt"
    base_exe = Path(home) / ("python.exe" if windows else f"python{xy}")
    if not base_exe.is_file():
        return None
    landmark = Path("Lib", "os.py") if windows else Path("lib", f"python{xy}", "os.py")
    base = next((b for b in dict.fromkeys((Path(home).parent, base_exe.resolve().parent.parent, Path(home)))
                 if (b / landmark).is_file()), None)
    if base is None:
        return None
    if windows:
        sites = [venv / "Lib" / "site-packages"]
    else:
        try:  # lib/python3.13t for a free-threaded build
            names = sorted(e.name for e in os.scandir(venv / "lib") if re.fullmatch(rf"python{re.escape(xy)}t?", e.name))
        except OSError:
            names = []
        sites = [venv / "lib" / n / "site-packages" for n in names]
    found = [str(s) for s in sites if s.is_dir() and not s.is_symlink()]
    if not found:
        return None
    if cfg.get("include-system-site-packages", "").lower() == "true":
        system = ([base / "Lib" / "site-packages"] if windows else
                  [base / "lib" / f"python{xy}" / "site-packages", base / "lib" / f"python{xy}" / "dist-packages",
                   base / "local" / "lib" / f"python{xy}" / "dist-packages", base / "lib" / "python3" / "dist-packages"])
        found += [str(s) for s in system if s.is_dir()]
    return VenvLayout(str(venv), str(base), home, found)


def site_dirs(python: str) -> list[str]:
    """The interpreter's site-packages, asked with `-I -S` so no `.pth` file
    or site hook runs. `-S` also skips `site.venv()`, so a virtualenv's own
    site-packages are derived here from its `pyvenv.cfg`, as `site` would."""
    try:
        out = subprocess.run([python, "-I", "-S", "-c", _SITE_DIRS],
                             capture_output=True, text=True, timeout=20, check=False,
                             stdin=subprocess.DEVNULL, cwd="/")
        data = json.loads(out.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [d for d in data if isinstance(d, str)]

