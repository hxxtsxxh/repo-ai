"""Safe file mutation: managed blocks, ownership markers, plans, atomic writes.

Every file repo-ai touches outside its own directories goes through a
`Plan`. A plan records the before/after content of each change, so the same
code path serves `--dry-run`, `--diff`, the real write, and the backup that
makes a bad write recoverable. Nothing is written until `apply()`.

Ownership rules:

* A **managed block** lives between BEGIN/END markers inside a shared file
  (CLAUDE.md, AGENTS.md, .gitignore, .bobignore). Text outside the markers is
  never modified, byte for byte.
* A **managed file** carries a marker line with a checksum of its own body.
  If the checksum no longer matches, a human edited it and repo-ai treats the
  file as theirs: it will not overwrite or delete it.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

MARKER_RE = re.compile(r"^[ \t]*(?:<!--|#)[ \t]*repo-ai:managed\b([^\n]*?)(?:-->)?[ \t]*$", re.M)
_SHA_RE = re.compile(r"\bsha=([0-9a-f]{12,64})\b")


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------
# `python -m repo_ai`, except that the working directory never joins sys.path: with `-m`, Python puts it
# first, so a repository's own `argparse.py` or `json.py` (the working directory is often the repository)
# would be imported in place of the standard library's, unsandboxed (the defensive review, 2026-10-25).
# `-P` does the same from Python 3.11; this works from 3.10.
SELF = ("import sys; sys.path[:] = [p for p in sys.path if p not in ('', '.')]; import runpy; "
        "runpy.run_module('repo_ai', run_name='__main__', alter_sys=True)")


def self_argv(*args: str) -> list[str]:
    """The argv that runs this repo-ai (the interpreter it runs in) with `args`."""
    import sys
    return [sys.executable, "-c", SELF, *args]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(text: str, n: int = 16) -> str:
    return sha256(text)[:n]


# --------------------------------------------------------------------------
# line endings
# --------------------------------------------------------------------------
def detect_eol(text: str | None) -> str:
    """The file's dominant line ending: CRLF only when most lines use it."""
    if not text:
        return "\n"
    crlf = text.count("\r\n")
    return "\r\n" if crlf and crlf * 2 >= text.count("\n") else "\n"


def to_eol(text: str, eol: str) -> str:
    text = text.replace("\r\n", "\n")
    return text if eol == "\n" else text.replace("\n", eol)


def lf(text: str | None) -> str | None:
    return None if text is None else text.replace("\r\n", "\n")


def same_modulo_eol(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and lf(a) == lf(b)


# --------------------------------------------------------------------------
# managed files
# --------------------------------------------------------------------------
def _without_marker(text: str) -> str:
    return MARKER_RE.sub("", text, count=1)


def stamp_managed(body: str, kind: str, comment: str = "html", **attrs: str) -> str:
    """Insert an ownership marker whose sha covers the rest of the file.

    For Markdown with YAML front matter the marker goes right after the
    closing `---` so the front matter stays the first thing in the file.
    """
    extra = "".join(f" {k}={v}" for k, v in sorted(attrs.items()))
    digest = short_hash(body)
    marker = (f"<!-- repo-ai:managed kind={kind}{extra} sha={digest} -->" if comment == "html"
              else f"# repo-ai:managed kind={kind}{extra} sha={digest}")
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end != -1:
            cut = end + len("\n---\n")
            return body[:cut] + marker + "\n" + body[cut:]
    if body.startswith("#!"):
        first, _, rest = body.partition("\n")
        return f"{first}\n{marker}\n{rest}"
    return f"{marker}\n{body}"


def managed_state(text: str | None) -> str:
    """'absent' | 'foreign' (no marker) | 'pristine' | 'modified'."""
    if text is None:
        return "absent"
    text = text.replace("\r\n", "\n")  # a CRLF checkout (git autocrlf) is still ours
    match = MARKER_RE.search(text)
    if not match:
        return "foreign"
    sha = _SHA_RE.search(match.group(1) or "")
    if not sha:
        return "modified"
    body = text[:match.start()] + text[match.end() + 1:] if text[match.end():match.end() + 1] == "\n" \
        else text[:match.start()] + text[match.end():]
    return "pristine" if short_hash(body, len(sha.group(1))) == sha.group(1) else "modified"


def marker_attrs(text: str) -> dict[str, str]:
    match = MARKER_RE.search((text or "").replace("\r\n", "\n"))
    if not match:
        return {}
    return dict(re.findall(r"(\w[\w-]*)=([^\s>]+)", match.group(1) or ""))


# --------------------------------------------------------------------------
# managed blocks inside shared files
# --------------------------------------------------------------------------
def find_block(text: str, begin: str, end: str) -> tuple[int, int] | None:
    start = text.find(begin)
    if start == -1:
        return None
    stop = text.find(end, start + len(begin))
    if stop == -1:
        return None
    return start, stop + len(end)


def get_block(text: str, begin: str, end: str) -> str | None:
    span = find_block(text, begin, end)
    return text[span[0]:span[1]] if span else None


def upsert_block(text: str | None, begin: str, end: str, block: str,
                 position: str = "end") -> str:
    """Insert or replace one managed block; everything else is untouched.

    The block is written with the file's own line endings, so a CRLF file
    stays CRLF and removing the block later restores the original bytes.
    """
    if not block.startswith(begin) or not block.rstrip().endswith(end):
        raise ValueError("block must start with BEGIN and end with END markers")
    eol = detect_eol(text)
    block = to_eol(block.rstrip("\r\n"), eol)
    if not text:
        return block + eol
    span = find_block(text, begin, end)
    if span:
        return text[:span[0]] + block + text[span[1]:]
    if position == "start":
        return block + eol + eol + text
    if text.endswith(eol + eol):
        sep = ""
    elif text.endswith(eol):
        sep = eol
    else:
        sep = eol + eol
    return text + sep + block + eol


def remove_block(text: str, begin: str, end: str) -> str:
    """Remove a managed block and the blank line we added around it."""
    span = find_block(text, begin, end)
    if not span:
        return text
    eol = detect_eol(text)
    head, tail = text[:span[0]], text[span[1]:]
    if tail.startswith(eol):
        tail = tail[len(eol):]
    elif tail.startswith("\n"):
        tail = tail[1:]
    if head.endswith(eol + eol):
        head = head[:-len(eol)]
    return head + tail


def strip_managed_blocks(text: str) -> str:
    """Remove every repo-ai managed block (used before indexing a shared
    instruction file, so repo-ai never learns from its own output)."""
    out = text
    for begin, end in KNOWN_BLOCKS:
        while True:
            new = remove_block(out, begin, end)
            if new == out:
                break
            out = new
    return out


# Registered by the adapters; listed here so the indexer can strip them
# without importing adapter code.
KNOWN_BLOCKS: list[tuple[str, str]] = [
    ("<!-- BEGIN repo-ai -->", "<!-- END repo-ai -->"),
    ("<!-- BEGIN repo-ai:claude -->", "<!-- END repo-ai:claude -->"),
    ("# --- begin repo-ai managed block ---", "# --- end repo-ai managed block ---"),
    ("# >>> repo-ai managed >>>", "# <<< repo-ai managed <<<"),
]


# --------------------------------------------------------------------------
# atomic IO
# --------------------------------------------------------------------------
def read_text(path: Path) -> str | None:
    """Exact file text: line endings are preserved (no newline translation)."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            return fh.read()
    except (IsADirectoryError, PermissionError, NotADirectoryError):
        return None


RETRY_SHARING_VIOLATIONS = os.name == "nt"


def _replace(tmp: str, path: Path) -> None:
    """os.replace, retried briefly on Windows: a reader holding the target open
    (another session's gate or `repo-ai evidence`) makes it fail with a sharing
    violation for as long as the file stays open."""
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not RETRY_SHARING_VIOLATIONS or attempt == 19:
                raise
            time.sleep(0.025)


def atomic_write(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = None
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is None:
            mode = 0o666 & ~_umask()  # what open() would have produced
        if executable:
            mode |= 0o111 & ~_umask()
        os.chmod(tmp, mode)
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


# --------------------------------------------------------------------------
# containment
# --------------------------------------------------------------------------
class UnsafePath(RuntimeError):
    """A write or delete would leave the repository (symlink or outside path)."""


def ensure_inside(root: Path, path: Path) -> None:
    """Refuse targets outside `root`, or reached through a symlink.

    A repository can commit `.claude -> ~/.claude`; following it would let a
    clone rewrite global settings. Every existing component between the root
    and the target (and the target itself) must be a real directory/file.
    """
    root_abs = Path(os.path.abspath(root))
    target = Path(os.path.abspath(path))
    try:
        rel = target.relative_to(root_abs)
    except ValueError as exc:
        raise UnsafePath(f"refusing to touch {path}: outside the repository") from exc
    current = root_abs
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafePath(f"refusing to write through a symlink: {current.relative_to(root_abs)} "
                             f"-> {os.readlink(current)}")
    resolved_root = root_abs.resolve()
    resolved = target.parent.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise UnsafePath(f"refusing to touch {path}: resolves outside the repository")


# --------------------------------------------------------------------------
# plans
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Change:
    path: Path
    before: str | None
    after: str | None
    executable: bool = False
    note: str = ""
    shared: bool = False  # a human-owned file repo-ai edits in place

    @property
    def action(self) -> str:
        if self.before is None and self.after is None:
            return "unchanged"
        if self.before is None:
            return "create"
        if self.after is None:
            return "delete"
        return "unchanged" if self.before == self.after else "update"


@dataclass(slots=True)
class Plan:
    root: Path
    changes: dict[Path, Change] = field(default_factory=dict)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    removed_dirs: list[Path] = field(default_factory=list)
    removed_trees: list[Path] = field(default_factory=list)

    def current(self, path: Path) -> str | None:
        """Content as it will be after the changes planned so far."""
        if path in self.changes:
            return self.changes[path].after
        return read_text(path)

    def write(self, path: Path, content: str, executable: bool = False, note: str = "",
              shared: bool = False) -> Change:
        prior = self.changes.get(path)
        before = prior.before if prior else read_text(path)
        change = Change(path, before, content, executable, note,
                        shared or bool(prior and prior.shared))
        self.changes[path] = change
        return change

    def write_shared(self, path: Path, content: str, note: str = "") -> Change:
        """Edit a file a human owns (CLAUDE.md, settings.json, .gitignore...).
        Its pre-repo-ai bytes are recorded so uninstall can restore them."""
        return self.write(path, content, note=note, shared=True)

    def delete(self, path: Path, note: str = "", shared: bool = False) -> None:
        prior = self.changes.get(path)
        before = prior.before if prior else read_text(path)
        if before is None and prior is None:
            return
        self.changes[path] = Change(path, before, None, False, note,
                                    shared or bool(prior and prior.shared))

    def restore_originals(self, ledger: "Originals") -> None:
        """Where removing repo-ai's material leaves content equivalent to the
        recorded pre-install file, write the recorded bytes back exactly."""
        for change in self.changes.values():
            if not change.shared:
                continue
            original = ledger.get(self.rel(change.path))
            if original is None:
                continue
            if change.after is None:
                empty = "{}" if change.path.suffix == ".json" else ""
                if not original.strip() or equivalent(change.path, empty, original):
                    change.after = original  # it existed (empty) before repo-ai
                continue
            if change.after != original and equivalent(change.path, change.after, original):
                change.after = original

    def remove_dir_if_empty(self, path: Path) -> None:
        if path not in self.removed_dirs:
            self.removed_dirs.append(path)

    def delete_tree(self, path: Path) -> None:
        """Remove a whole directory that repo-ai owns (index, caches)."""
        if path.is_dir() and path not in self.removed_trees:
            self.removed_trees.append(path)

    def write_if_changed(self, path: Path, content: str, volatile: re.Pattern[str] | None = None) -> None:
        """Skip writes whose only difference is a volatile timestamp, so
        identical inputs leave generated files byte-identical on disk."""
        current = lf(self.current(path))  # a CRLF checkout of identical text is unchanged
        if current is not None and (current == content or volatile is not None and
                                    volatile.sub("<ts>", current) == volatile.sub("<ts>", content)):
            return
        self.write(path, content)

    def skip(self, path: Path, reason: str) -> None:
        self.skipped.append((path, reason))

    # -- inspection ----------------------------------------------------------
    def effective(self) -> list[Change]:
        return [c for c in self.changes.values() if c.action != "unchanged"]

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def summary_lines(self) -> list[str]:
        lines = []
        for change in sorted(self.effective(), key=lambda c: self.rel(c.path)):
            note = f"  ({change.note})" if change.note else ""
            lines.append(f"  {change.action:7s} {self.rel(change.path)}{note}")
        for path in self.removed_trees:
            suffix = "/" if path.is_dir() else ""
            lines.append(f"  delete  {self.rel(path)}{suffix}  (repo-ai state)")
        for path, reason in self.skipped:
            lines.append(f"  skip    {self.rel(path)}  ({reason})")
        return lines

    def diff(self, exclude: tuple[str, ...] = ()) -> str:
        chunks: list[str] = []
        for change in sorted(self.effective(), key=lambda c: self.rel(c.path)):
            rel = self.rel(change.path)
            if exclude and rel.startswith(exclude):
                continue
            try:
                ensure_inside(self.root, change.path)
            except UnsafePath as exc:
                chunks.append(f"# refused, not shown: {exc}\n")
                continue
            before = (change.before or "").splitlines(keepends=True)
            after = (change.after or "").splitlines(keepends=True)
            chunks.extend(difflib.unified_diff(
                before, after,
                fromfile=f"a/{rel}" if change.before is not None else "/dev/null",
                tofile=f"b/{rel}" if change.after is not None else "/dev/null",
            ))
            if chunks and not chunks[-1].endswith("\n"):
                chunks.append("\n")
        return "".join(chunks)

    # -- execution -------------------------------------------------------------
    def apply(self, backup_root: Path | None = None, keep_backups: int = 8,
              originals: "Originals | None" = None) -> list[Change]:
        applied: list[Change] = []
        effective = self.effective()
        for change in effective:
            ensure_inside(self.root, change.path)
        for tree in self.removed_trees:
            ensure_inside(self.root, tree)
        if originals is not None:
            originals.record(self, effective)
        backup_dir = None
        if backup_root is not None and any(c.before is not None for c in effective):
            backup_dir = backup_root / time.strftime("%Y%m%dT%H%M%S") / f"{os.getpid()}"
            for change in effective:
                if change.before is None:
                    continue
                target = backup_dir / self.rel(change.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="") as fh:
                    fh.write(change.before)
            _prune_backups(backup_root, keep_backups)
        for change in effective:
            if change.after is None:
                try:
                    change.path.unlink()
                except FileNotFoundError:
                    pass
            else:
                atomic_write(change.path, change.after, change.executable)
            applied.append(change)
        for tree in self.removed_trees:
            if self.root not in tree.parents:
                continue
            if tree.is_dir() and not tree.is_symlink():
                shutil.rmtree(tree, ignore_errors=True)
            else:
                try:
                    tree.unlink()
                except FileNotFoundError:
                    pass
        for directory in sorted(self.removed_dirs, key=lambda p: -len(p.parts)):
            _rmdir_empty_chain(directory, self.root)
        return applied


# --------------------------------------------------------------------------
# originals ledger
# --------------------------------------------------------------------------
def equivalent(path: Path, a: str, b: str) -> bool:
    """Same content up to formatting repo-ai may have introduced.

    JSON compares parsed values (key order included); other text compares
    after normalising line endings and trailing newlines at end of file.
    """
    if path.suffix == ".json":
        import json
        try:
            pa, pb = json.loads(a or "{}"), json.loads(b or "{}")
        except ValueError:
            return False
        return pa == pb and json.dumps(pa) == json.dumps(pb)  # dumps keeps key order
    return (a or "").replace("\r\n", "\n").rstrip("\n") == (b or "").replace("\r\n", "\n").rstrip("\n")


def _has_repo_ai_material(change: Change) -> bool:
    """A file that already carries repo-ai output (an install made before the
    ledger existed) is not a clean original; uninstall falls back to removal."""
    before = change.before or ""
    if change.path.suffix == ".json":
        return "repo-ai" in before
    return any(begin in before for begin, _ in KNOWN_BLOCKS) or \
        re.search(r"(?m)^# repo-ai\s*$", before) is not None


class Originals:
    """Pre-install bytes of every human-owned file repo-ai edited.

    Stored in the machine-local state directory. Only consulted when the
    content left after removing repo-ai's material is *equivalent* to the
    recording, so later human edits are never reverted.
    """

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        try:
            import json
            raw = json.loads(path.read_text("utf-8"))
            if isinstance(raw, dict):
                self.data = {k: v for k, v in raw.get("files", {}).items() if isinstance(v, str)}
        except (OSError, ValueError):
            pass

    def get(self, rel: str) -> str | None:
        return self.data.get(rel)

    def record(self, plan: "Plan", changes: list[Change]) -> None:
        added = False
        for change in changes:
            rel = plan.rel(change.path)
            if change.shared and change.before is not None and rel not in self.data \
                    and change.after is not None and not _has_repo_ai_material(change):
                self.data[rel] = change.before
                added = True
        if added:
            import json
            atomic_write(self.path, json.dumps({"version": 1, "files": self.data},
                                               indent=1, sort_keys=True) + "\n")


def _prune_backups(backup_root: Path, keep: int) -> None:
    try:
        sets = sorted(p for p in backup_root.iterdir() if p.is_dir())
    except OSError:
        return
    for old in sets[:-keep] if len(sets) > keep else []:
        shutil.rmtree(old, ignore_errors=True)


def _rmdir_empty_chain(directory: Path, stop: Path) -> None:
    """Remove `directory` and then its parents while they are empty, never
    past `stop`, and never through a symlink: a committed `.claude/skills ->
    ../../elsewhere` must not let cleanup remove directories outside."""
    current = directory
    while current != stop and stop in current.parents:
        if not _real_path_under(stop, current):
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _real_path_under(root: Path, path: Path) -> bool:
    """Every component from `root` down to `path` exists as a real directory
    (no symlinks), and `path` resolves inside `root`."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False
