"""The change under verification: files and code objects that differ from a
base revision (working tree, staged and untracked files included).

For Python, a changed line is mapped to the code objects that own it: the
function, method, class body or module code that the interpreter would run
for that line. That is the same unit the runtime tracer records, so static
diffs and runtime evidence join exactly. Other languages are mapped at file
level here; runtime function ranges refine them in ``select``.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import CodeType

from .. import gitbin
from ..gitinfo import safe_ref

PY_SUFFIXES = {".py"}
JS_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx"}
MAX_TEXT = 4_000_000


class ChangeError(RuntimeError):
    pass


@dataclass(slots=True)
class CodeUnit:
    """A Python code object: the unit of runtime evidence."""
    name: str          # co_name ("<module>" for module code)
    firstlineno: int
    lines: frozenset[int]
    span: tuple[int, int]  # first..last line, nested code included

    @property
    def key(self) -> str:
        return f"{self.firstlineno}:{self.name}"


@dataclass(slots=True)
class ChangedFile:
    path: str
    status: str                       # added | modified | deleted | renamed
    old_path: str = ""
    binary: bool = False
    behavioral: bool = True           # False: only comments/whitespace changed (Python: AST equal)
    why_not_behavioral: str = ""
    old_lines: list[tuple[int, int]] = field(default_factory=list)  # changed ranges in the base file
    new_lines: list[tuple[int, int]] = field(default_factory=list)  # changed ranges in the working file
    insertions: list[int] = field(default_factory=list)  # base line after which lines were inserted
    units: list[str] = field(default_factory=list)       # changed code-unit keys (base version)
    unit_names: list[str] = field(default_factory=list)  # human-readable names of those units
    new_units: list[str] = field(default_factory=list)   # units that exist only in the new version
    old_sha: str = ""
    new_sha: str = ""

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.path).suffix.lower()

    def to_json(self) -> dict[str, object]:
        return {"path": self.path, "status": self.status, "old_path": self.old_path or None,
                "binary": self.binary, "behavioral": self.behavioral,
                "changed_units": self.unit_names, "new_units": self.new_units,
                "old_line_ranges": self.old_lines, "new_line_ranges": self.new_lines}


@dataclass(slots=True)
class Change:
    root: Path
    base: str            # the revision compared against
    base_commit: str     # its full commit id ("" when the repository has no commits)
    files: list[ChangedFile]
    fingerprint: str     # identifies this exact change (base + every changed file's content)
    withheld: list[str] = field(default_factory=list)  # untracked credential-like files: not part of it

    def paths(self) -> list[str]:
        return [f.path for f in self.files]


# --------------------------------------------------------------------------
# git plumbing (no shell; refs validated)
# --------------------------------------------------------------------------
def _git(root: Path, *args: str, binary: bool = False, check: bool = False):
    proc = subprocess.run([gitbin.git(), *args], cwd=root, capture_output=True, timeout=60,
                          check=False, stdin=subprocess.DEVNULL)
    if check and proc.returncode != 0:
        raise ChangeError(f"git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def resolve_base(root: Path, base: str = "HEAD") -> str:
    if not safe_ref(base):
        raise ChangeError(f"not a valid git revision: {base!r}")
    out = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", base + "^{commit}").strip()
    if out:
        return out
    # "" means "compare with nothing" (every file is new). That is only right for HEAD in a
    # repository with no commit yet; a base that does not resolve (`--base main` where the
    # branch is `master`) must not silently become "no base" and an empty change.
    has_commits = bool(_git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip())
    if base != "HEAD" or has_commits:
        raise ChangeError(f"the base revision {base!r} does not resolve to a commit in this repository")
    return ""


def _new_files(root: Path, commit: str) -> list[str]:
    """Paths that count as added without a diff entry: untracked files and,
    when there is no base commit (a repository with no commit yet, an orphan
    branch), every staged file too (there is nothing to diff them against)."""
    out = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    if not commit:
        out += _git(root, "ls-files", "--cached", "-z").split("\0")
    return list(dict.fromkeys(p for p in out if p))


def _flagged(root: Path, commit: str) -> list[tuple[str, str]]:
    """(path, status) of tracked files whose working-tree content differs
    from `commit` although `git diff` does not say so, because the workspace
    copies (and the tests read) the bytes as they are:
    - files marked `--assume-unchanged` or `--skip-worktree`: git trusts the
      flag and never looks. A flagged file that is absent counts as deleted,
      except a skip-worktree file in a sparse checkout (it is meant to be
      absent, and is not copied either);
    - with line-ending conversion configured (`core.autocrlf`, or a
      `.gitattributes`), a file whose line endings differ from what a
      checkout writes: git compares it after converting it back.
    """
    config = dict(line.partition(" ")[::2] for line in _git(
        root, "config", "--get-regexp", r"^core\.(sparsecheckout|autocrlf|eol|attributesfile)$").lower().splitlines())
    sparse = config.get("core.sparsecheckout", "").strip() == "true"
    flagged: list[str] = []
    attributes: list[str] = []
    for e in _git(root, "ls-files", "-v", "-z").split("\0"):  # one listing of the index serves both
        if len(e) > 2 and e[1] == " ":
            if e[0].islower() or (e[0] == "S" and not sparse):
                flagged.append(e[2:])
            if e.endswith(".gitattributes") and (e[2:] == ".gitattributes" or e.endswith("/.gitattributes")):
                attributes.append(e[2:])
    eol = _eol_drift(root, config, attributes)
    out: dict[str, str] = {}
    present = []
    for p in flagged:
        if (root / p).is_symlink() or (root / p).is_file():
            present.append(p)
        elif base_blob(root, commit, p) is not None:
            out[p] = "deleted"
    odd = [p for p in present if "\n" in p or "\r" in p]  # cannot go through --stdin-paths: count as changed
    plain = [p for p in present if p not in odd]
    ids: dict[str, str] = {}
    if plain:
        proc = subprocess.run([gitbin.git(), "hash-object", "--no-filters", "--stdin-paths"], cwd=root,
                              capture_output=True, timeout=120, check=False,
                              input="\n".join(plain).encode("utf-8", "surrogateescape") + b"\n")
        ids = dict(zip(plain, proc.stdout.decode("ascii", "replace").split(), strict=False))
    at_base = _base_ids(root, commit, set(plain)) if plain else {}
    for p in odd:
        out[p] = "modified" if base_blob(root, commit, p) is not None else "added"
    for p in plain:
        if not ids.get(p) or at_base.get(p) != ids[p]:
            out[p] = "modified" if p in at_base else "added"
    for p in eol:
        out.setdefault(p, "modified")
    return sorted(out.items())


def _base_ids(root: Path, commit: str, wanted: set[str]) -> dict[str, str]:
    if not commit or not wanted:
        return {}
    listing = subprocess.run([gitbin.git(), "ls-tree", "-r", "-z", "--full-tree", "--end-of-options", commit],
                             cwd=root, capture_output=True, timeout=120, check=False,
                             stdin=subprocess.DEVNULL).stdout.decode("utf-8", "surrogateescape")
    out: dict[str, str] = {}
    for line in listing.split("\0"):
        meta, _, path = line.partition("\t")
        parts = meta.split(" ")
        if path in wanted and len(parts) == 3:
            out[path] = parts[2]
    return out


def _eol_attributes(root: Path, paths: list[str]) -> bool:
    """Whether an attributes file can set `text` or `eol`: a tracked
    `.gitattributes` (`paths`), or the repository's own `info/attributes`."""
    git = root / ".git"
    info = (git / "info" / "attributes") if git.is_dir() else \
        Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "info/attributes").strip() or root)
    for f in [root / p for p in paths] + [info]:
        try:
            text = f.read_text("utf-8", errors="replace") if f.is_file() else ""
        except OSError:
            continue
        if re.search(r"(^|\s)(-?text|eol=|-?crlf)\b", text):
            return True
    return False


def _eol_drift(root: Path, config: dict[str, str], attributes: list[str]) -> list[str]:
    """Tracked text files whose working-tree line endings are not the ones a
    checkout writes (only when conversion is configured: otherwise any such
    edit is an ordinary content change `git diff` reports)."""
    autocrlf, core_eol = config.get("core.autocrlf", "").strip(), config.get("core.eol", "").strip()
    if autocrlf not in {"true", "input"} and not config.get("core.attributesfile") \
            and not _eol_attributes(root, attributes):
        return []  # nothing converts line endings here: `ls-files --eol` (it reads every file) is not needed
    listing = _git(root, "ls-files", "--eol", "-z")
    out = []
    for entry in listing.split("\0"):
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if not path or len(fields) < 3 or fields[0] != "i/lf":
            continue  # only text the index stores with LF: its checkout form is known
        work, attr = fields[1], " ".join(fields[2:])
        if "-text" in attr or work not in {"w/lf", "w/crlf", "w/mixed"}:
            continue
        if "eol=crlf" in attr:
            want = "crlf"
        elif "eol=lf" in attr:
            want = "lf"
        elif autocrlf == "true" or (core_eol == "crlf" and "text" in attr):
            want = "crlf"
        else:
            want = "lf"
        if work != f"w/{want}":
            out.append(path)
    return out


def base_blob(root: Path, commit: str, path: str) -> bytes | None:
    if not commit:
        return None
    proc = subprocess.run([gitbin.git(), "cat-file", "blob", f"{commit}:{path}"], cwd=root,
                          capture_output=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    return proc.stdout if proc.returncode == 0 else None


_NULL_ID = "0" * 40


def _raw_diff(root: Path, commit: str) -> list[tuple[str, str, str, str]]:
    """(status, path, old path, old blob id) of every path that differs from
    `commit` in the working tree: the same entries as `--name-status`, with
    the base side's object id, so that every base blob is read in one batch."""
    out = _git(root, "diff", "--raw", "--no-abbrev", "-M", "-z", "--no-ext-diff", "--ignore-submodules=untracked", "--end-of-options", commit)
    parts = out.split("\0")
    entries = []
    i = 0
    while i < len(parts) - 1:
        head = parts[i]
        if not head.startswith(":"):
            i += 1
            continue
        fields = head[1:].split(" ")
        if len(fields) < 5:
            i += 1
            continue
        old_mode, old_id, code = fields[0], fields[2], fields[4]
        if code.startswith(("R", "C")):
            old_path, new_path = parts[i + 1], parts[i + 2]
            i += 3
        else:
            old_path, new_path = "", parts[i + 1]
            i += 2
        if old_mode == "160000" or set(old_id) <= {"0"}:  # a gitlink or no base side: no blob
            old_id = ""
        entries.append((code, new_path, old_path, old_id))
    return entries


def _blobs(root: Path, ids: list[str]) -> dict[str, bytes | None]:
    """Blob contents by object id, read with one `git cat-file --batch`.
    Anything that is not a blob (or is missing) maps to None, like
    `base_blob`."""
    want = sorted({i for i in ids if i and all(c in "0123456789abcdef" for c in i)})
    if not want:
        return {}
    proc = subprocess.run([gitbin.git(), "cat-file", "--batch"], cwd=root, input=("\n".join(want) + "\n").encode(),
                          capture_output=True, timeout=120, check=False)
    out: dict[str, bytes | None] = {}
    data, pos = proc.stdout, 0
    for oid in want:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        header = data[pos:nl].decode("ascii", "replace").split(" ")
        pos = nl + 1
        if len(header) == 3 and header[2].isdigit():
            size = int(header[2])
            body = data[pos:pos + size]
            pos += size + 1  # the content, then a newline
            out[header[0]] = body if header[1] == "blob" and len(body) == size else None
        else:  # "<id> missing" (or ambiguous)
            out[oid] = None
    # an object the batch never answered (it stops at the first object it cannot read, e.g. in a
    # partial clone whose promisor is unreachable) is read on its own, as `base_blob` would
    for oid in want:
        if oid not in out:
            proc = subprocess.run([gitbin.git(), "cat-file", "blob", oid], cwd=root, capture_output=True, timeout=60,
                                  check=False, stdin=subprocess.DEVNULL)
            out[oid] = proc.stdout if proc.returncode == 0 else None
    return {i: out.get(i) for i in want}


def _is_binary(data: bytes | None) -> bool:
    return data is not None and b"\0" in data[:8192]


def _decode(data: bytes | None) -> str:
    # a UTF-8 BOM is valid in a source file but makes str-based parsing fail; it
    # sits before line 1, so removing it changes no line numbers
    return (data or b"").decode("utf-8", "replace")[:MAX_TEXT].removeprefix("\ufeff")


def sha(data: bytes | None) -> str:
    """Content hash, neutral to CRLF/LF: a Windows checkout with autocrlf has CRLF
    in the working tree and LF in the repository for the same content."""
    return hashlib.sha256((data or b"").replace(b"\r\n", b"\n")).hexdigest() if data is not None else ""


def content_id(root: Path, rel: str) -> str:
    """What identifies a working-tree path in a fingerprint: a symbolic link
    by its target, a file by its whole content (every byte, read in chunks;
    parsing reads only the first `MAX_TEXT`), anything else as absent. Two
    states that differ anywhere never share it: line endings included, since
    the workspace copies the bytes the tests read (a CRLF golden file is not
    the LF one). Unlike `sha`, it never compares the working tree with a
    repository blob, so a checkout's line-ending conversion cannot matter."""
    path = root / rel
    try:
        if path.is_symlink():
            return "link:" + hashlib.sha256(os.readlink(path).encode("utf-8", "surrogateescape")).hexdigest()
        if path.is_dir() and (path / ".git").exists():
            return _submodule_id(root, rel)
        if not path.is_file():
            return ""
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _submodule_id(root: Path, rel: str) -> str:
    """A checked-out submodule by its HEAD and the content of every file in
    it that the workspace copies (`isolate.worktree_files` lists them with
    `--recurse-submodules`): an edit inside it changes the state."""
    head = _git(root / rel, "rev-parse", "--verify", "--quiet", "HEAD").strip()
    h = hashlib.sha256(f"submodule:{head}".encode())
    listed = _git(root, "ls-files", "-z", "--cached", "--recurse-submodules", "--", rel).split("\0")
    for f in sorted(p for p in listed if p and p != rel):
        h.update(f"\0{f}\0{content_id(root, f)}".encode())
    return "sub:" + h.hexdigest()


# --------------------------------------------------------------------------
# Python code units
# --------------------------------------------------------------------------
def code_units(source: str, filename: str = "<file>") -> list[CodeUnit] | None:
    """Every code object in a Python source, with the lines it owns (its own
    bytecode lines, not those of nested functions) and its overall span.
    None when the source does not compile (then the file is mapped whole)."""
    try:
        top = compile(source, filename, "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return None
    units: list[CodeUnit] = []
    stack: list[CodeType] = [top]
    while stack:
        code = stack.pop()
        own = frozenset(line for _, _, line in code.co_lines() if line)
        nested = [c for c in code.co_consts if isinstance(c, CodeType)]
        stack.extend(nested)
        units.append(CodeUnit(code.co_name, code.co_firstlineno, own, (0, 0)))
    # spans: own lines plus every nested unit's span (computed bottom-up by line ranges)
    by_first = sorted(units, key=lambda u: (u.firstlineno, u.name))
    out = []
    for unit in by_first:
        lines = unit.lines or frozenset({unit.firstlineno})
        out.append(CodeUnit(unit.name, unit.firstlineno, unit.lines,
                            (min(lines | {unit.firstlineno}), max(lines))))
    # widen spans to include nested units that start inside them
    out.sort(key=lambda u: (u.span[0], -u.span[1]))
    for i, outer in enumerate(out):
        lo, hi = outer.span
        for inner in out[i + 1:]:
            if outer.name == "<module>" or lo <= inner.firstlineno <= hi:
                hi = max(hi, inner.span[1])
        out[i] = CodeUnit(outer.name, outer.firstlineno, outer.lines, (lo, hi))
    return out


def owners(units: list[CodeUnit], lines: set[int]) -> list[CodeUnit]:
    """Units that own any of `lines`; a line with no bytecode (comment, blank,
    part of a multi-line expression) falls to the innermost unit whose span
    contains it."""
    found: dict[str, CodeUnit] = {}
    for line in lines:
        direct = [u for u in units if line in u.lines]
        if not direct:
            spans = [u for u in units if u.span[0] <= line <= u.span[1] and u.name != "<module>"]
            if spans:
                direct = [min(spans, key=lambda u: u.span[1] - u.span[0])]
        for unit in direct:
            found[unit.key] = unit
    return sorted(found.values(), key=lambda u: (u.firstlineno, u.name))


def _ast_equal(old: str, new: str) -> bool | None:
    try:
        return ast.dump(ast.parse(old)) == ast.dump(ast.parse(new))
    except (SyntaxError, ValueError, RecursionError):
        return None


# --------------------------------------------------------------------------
# the change
# --------------------------------------------------------------------------
def _ranges(opcodes) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[int]]:
    old, new, ins = [], [], []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        if i2 > i1:
            old.append((i1 + 1, i2))
        else:
            ins.append(i1)  # inserted after base line i1 (0 = top of file)
        if j2 > j1:
            new.append((j1 + 1, j2))
    return old, new, ins


MANAGED_START, MANAGED_END = "# >>> repo-ai managed >>>", "# <<< repo-ai managed <<<"


def _only_managed_block(ops, old_lines: list[str], new_lines: list[str]) -> bool:
    """Every added or removed line lies inside repo-ai's managed block."""
    def inside(lines: list[str]) -> set[int]:
        out, on = set(), False
        for i, line in enumerate(lines):
            if line.strip() == MANAGED_START:
                on = True
            if on:
                out.add(i)
            if line.strip() == MANAGED_END:
                on = False
        return out
    old_in, new_in = inside(old_lines), inside(new_lines)
    changed = False
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        changed = True
        removed = set(range(i1, i2))
        added = {j for j in range(j1, j2) if new_lines[j].strip()}
        if not removed <= old_in or not added <= new_in:
            return False
    return changed


_NEWLINE = re.compile(r"\r\n|\r|\n")


def _lines(text: str) -> list[str]:
    """Lines as Python numbers them: universal newlines only (not the form
    feeds, U+2028 and other separators str.splitlines() also splits on)."""
    lines = _NEWLINE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _describe(path: str, old: bytes | None, new: bytes | None, status: str, old_path: str = "") -> ChangedFile:
    cf = ChangedFile(path=path, status=status, old_path=old_path, old_sha=sha(old), new_sha=sha(new))
    if _is_binary(old) or _is_binary(new):
        cf.binary = True
        return cf
    old_text, new_text = _decode(old), _decode(new)
    # "\n" only, as the interpreter numbers lines: str.splitlines() also splits on form feeds,
    # U+2028 and other separators, which shifted every later line and the code units it maps to
    old_lines = _lines(old_text)
    new_lines = _lines(new_text)
    ops = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes()
    cf.old_lines, cf.new_lines, cf.insertions = _ranges(ops)
    if PurePosixPath(path).name == ".gitignore" and _only_managed_block(ops, old_lines, new_lines):
        cf.behavioral = False  # `repo-ai init` adding its own state directory changes no test
        cf.why_not_behavioral = "only repo-ai's own managed block in .gitignore changed"
    if PurePosixPath(path).suffix.lower() in PY_SUFFIXES:
        units: list[CodeUnit] | None = None
        if old is not None and new is not None:
            equal = _ast_equal(old_text, new_text)
            if equal:
                cf.behavioral = False
        if old is not None:
            units = code_units(old_text, path)
            if units is not None:
                touched = {line for a, b in cf.old_lines for line in range(a, b + 1)}
                for after in cf.insertions:  # an insertion changes the code around it
                    touched.update({after, after + 1} - {0})
                if new is None or status == "renamed":  # a moved module: every import of the old path breaks
                    touched = set(range(1, len(old_lines) + 1))
                hit = owners(units, touched) if touched else []
                cf.units = [u.key for u in hit]
                cf.unit_names = [u.name for u in hit]
        if new is not None:
            new_units = code_units(new_text, path) or []
            old_names = set(cf.unit_names)
            fresh = owners(new_units, {line for a, b in cf.new_lines for line in range(a, b + 1)})
            cf.new_units = sorted({u.name for u in fresh if u.name not in old_names})
            # definition-time code (module or class body) changed in the new version, e.g. a new
            # top-level def or class attribute: that code runs at import, so the base module or
            # class-body unit it lands in counts as changed
            if old is not None and units is not None:
                fresh_names = {u.name for u in fresh}
                try:
                    classes = {n.name for n in ast.walk(ast.parse(new_text)) if isinstance(n, ast.ClassDef)}
                except (SyntaxError, ValueError, RecursionError):
                    classes = set()
                for unit in units:
                    is_body = unit.name == "<module>" or unit.name in classes
                    if is_body and unit.name in fresh_names and unit.key not in cf.units:
                        cf.units.append(unit.key)
                        cf.unit_names.append(unit.name)
    if status == "renamed":  # the same content under another path still breaks every import of the old one
        cf.behavioral, cf.why_not_behavioral = True, ""
    return cf


def detect(root: Path, base: str = "HEAD", paths: list[str] | None = None) -> Change:
    """Working tree (staged, unstaged and untracked) against `base`."""
    root = root.resolve()
    commit = resolve_base(root, base)
    files: list[ChangedFile] = []
    if commit:
        raw = _raw_diff(root, commit)
        blobs = _blobs(root, [old_id for _, _, _, old_id in raw])
        for code, path, old_path, old_id in raw:
            if code.startswith(("R", "C")):
                files.append(_describe(path, blobs.get(old_id), _read(root, path), "renamed", old_path))
            elif code.startswith("D"):
                files.append(_describe(path, blobs.get(old_id), None, "deleted"))
            elif code.startswith("A"):
                files.append(_describe(path, None, _read(root, path), "added"))
            else:
                files.append(_describe(path, blobs.get(old_id), _read(root, path), "modified"))
    known = {f.path for f in files}
    for path, status in _flagged(root, commit):
        if path not in known:
            files.append(_describe(path, base_blob(root, commit, path), _read(root, path), status))
    untracked = _new_files(root, commit)
    known = {f.path for f in files}
    from ..config import DEFAULT_SECRET_PATH_GLOBS
    from ..security import path_is_secretlike
    withheld: list[str] = []
    for path in untracked:
        if path and path not in known and not path.startswith((".repo-ai/", ".claude/", ".bob/")):
            if path_is_secretlike(path, DEFAULT_SECRET_PATH_GLOBS):
                withheld.append(path)  # never copied into a test workspace: no test can see it
                continue
            files.append(_describe(path, None, _read(root, path), "added"))
    files = [f for f in files if not f.path.startswith((".repo-ai/", ".bob/"))]
    if paths is not None:
        wanted = set(paths)
        files = [f for f in files if f.path in wanted or f.old_path in wanted]
    files.sort(key=lambda f: f.path)
    for f in files:  # identity of the whole file (or link), not only the part that was read
        if f.status != "deleted":
            f.new_sha = content_id(root, f.path)
    digest = hashlib.sha256(commit.encode())
    for f in files:
        digest.update(f"\0{f.status}\0{f.path}\0{f.old_path}\0{f.new_sha}".encode())
    return Change(root, base, commit, files, digest.hexdigest(), sorted(withheld))


def fingerprint(root: Path, base: str = "HEAD") -> str:
    """`detect(root, base).fingerprint` without describing the change (no
    diffs, no parsing, no base blobs): what a run checks right after copying
    the working tree, to confirm the copy is the change it planned."""
    root = root.resolve()
    return _digest(root, base, lambda path: content_id(root, path))


def semantic_fingerprint(root: Path, base: str = "HEAD") -> str:
    """Like `fingerprint`, but a rewrite that cannot change behaviour keeps
    it: a Python file counts by its syntax tree (comments, whitespace,
    quote style and line wrapping ignored), a JavaScript or TypeScript file
    by `_js_tokens` when it can be tokenised conservatively. Every other
    file, and any file that fails to parse, counts by its exact bytes. The
    completion gate uses it so that a formatter run after verification
    (another Stop hook, an editor on save) does not ask for verification
    again; the run itself always uses the exact fingerprint."""
    root = root.resolve()
    return _digest(root, base, lambda path: _semantic_content(root, path))


def fingerprints(root: Path, base: str = "HEAD") -> tuple[str, str]:
    """(`fingerprint`, `semantic_fingerprint`) from one listing of the
    working tree: what a run checks right after copying it."""
    root = root.resolve()
    commit, listing = _listing(root, base)
    return (_digest_of(commit, listing, lambda path: content_id(root, path)),
            _digest_of(commit, listing, lambda path: _semantic_content(root, path)))


def _semantic_content(root: Path, path: str) -> str:
    exact = content_id(root, path)
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in PY_SUFFIXES | JS_SUFFIXES or not exact or exact.startswith("link:"):
        return exact
    data = _read(root, path)
    if data is None or len(data) >= MAX_TEXT or _is_binary(data):
        return exact
    if suffix in PY_SUFFIXES:
        try:  # from bytes: the interpreter's own decoding (an encoding declaration, a BOM)
            return "ast:" + hashlib.sha256(ast.dump(ast.parse(data)).encode()).hexdigest()
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return exact
    try:
        text = data.decode("utf-8").removeprefix("\ufeff")
    except UnicodeDecodeError:
        return exact
    tokens = _js_tokens(text)
    return exact if tokens is None else "tok:" + hashlib.sha256("\0".join(tokens).encode()).hexdigest()


def _digest(root: Path, base: str, content) -> str:
    root = root.resolve()
    commit, listing = _listing(root, base)
    return _digest_of(commit, listing, content)


def _listing(root: Path, base: str) -> tuple[str, list[tuple[str, str, str]]]:
    """(base commit, [(path, status, old path)]) of the working tree's change,
    read now (never cached). The untracked listing does not depend on the
    base, so it runs while the base is resolved and diffed."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        untracked = pool.submit(_git, root, "ls-files", "--others", "--exclude-standard", "-z")
        commit = resolve_base(root, base)
        entries: list[tuple[str, str, str]] = []
        if commit:
            out = _git(root, "diff", "--name-status", "-M", "-z", "--no-ext-diff", "--ignore-submodules=untracked", "--end-of-options", commit)
            parts = out.split("\0")
            i = 0
            while i < len(parts) - 1:
                code = parts[i]
                if not code:
                    i += 1
                    continue
                if code.startswith(("R", "C")):
                    entries.append((parts[i + 2], "renamed", parts[i + 1]))
                    i += 3
                    continue
                path = parts[i + 1]
                i += 2
                entries.append((path, "deleted" if code.startswith("D") else "added" if code.startswith("A")
                                else "modified", ""))
        others = untracked.result()
    known = {e[0] for e in entries}
    for path, status in _flagged(root, commit):
        if path not in known:
            entries.append((path, status, ""))
    known = {e[0] for e in entries}
    from ..config import DEFAULT_SECRET_PATH_GLOBS
    from ..security import path_is_secretlike
    # no base commit (a new repository, an orphan branch): staged files are the change too
    staged = _git(root, "ls-files", "--cached", "-z").split("\0") if not commit else []
    for path in dict.fromkeys(others.split("\0") + staged):
        if path and path not in known and not path.startswith((".repo-ai/", ".claude/", ".bob/")) \
                and not path_is_secretlike(path, DEFAULT_SECRET_PATH_GLOBS):
            entries.append((path, "added", ""))
    return commit, sorted(e for e in entries if not e[0].startswith((".repo-ai/", ".bob/")))


def _digest_of(commit: str, listing: list[tuple[str, str, str]], content) -> str:
    digest = hashlib.sha256(commit.encode())
    for path, status, old_path in listing:
        digest.update(f"\0{status}\0{path}\0{old_path}\0{'' if status == 'deleted' else content(path)}".encode())
    return digest.hexdigest()


_JS_PUNCT = set("{}()[];,<>+-*%&|^!~?:=.@#")
_JS_JOINING = set("+-*/%&|^!<>=?.:")  # punctuators that can form a longer one with a neighbour
_JS_REGEX_AFTER = set("(),=:[!&|?{};+-*%<>~^/")  # `)` too: `if (x) /re/.test(y)`
_JS_REGEX_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case",
                      "do", "else", "yield", "await"}


def _js_tokens(text: str) -> list[str] | None:
    """A conservative JavaScript/TypeScript token stream for `semantic_fingerprint`:
    spaces and tabs inside a line and comments are dropped, a quoted string
    with no backslash counts by its content (so the quote style does not
    matter), and line breaks are kept (as one token per run: automatic
    semicolon insertion depends on them). Whitespace between two
    operator characters that could join into one, or between a number and
    a dot, is kept (`a + +b` is not `a ++b`). Anything this does not handle exactly (template literals,
    regular-expression literals, JSX, unterminated strings or comments) returns
    None, so the file counts by its bytes: a false "same" would let the gate
    accept evidence for a different program, a false "different" only asks
    for verification again."""
    if any(mark in text for mark in ("</", "/>", "<!--", "-->")):
        return None  # JSX (spaces in its text are content) or HTML-like comments
    out: list[str] = []
    i, n = 0, len(text)
    gap = False   # whitespace or a comment since the last token
    while i < n:
        c = text[i]
        if c in " \t\f\v\ufeff\u00a0":
            gap = True
            i += 1
            continue
        if c in "\r\n\u2028\u2029":
            if out and out[-1] != "\n":
                out.append("\n")
            gap = False
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            gap = True
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                return None
            if any(ch in text[i:j] for ch in "\r\n\u2028\u2029"):
                if out and out[-1] != "\n":
                    out.append("\n")
                gap = False
            else:
                gap = True
            i = j + 2
            continue
        prev = out[-1] if out else "\n"
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] in "\\\r\n":
                    return None
                j += 1
            if j >= n:
                return None
            out.append("s:" + text[i + 1:j])
            i = j + 1
            gap = False
            continue
        if c == "`":
            return None
        if c == "/":
            if prev == "\n" or prev in _JS_REGEX_KEYWORDS or (prev.startswith("p:") and prev[2:] in _JS_REGEX_AFTER):
                return None  # could start a regular expression
            if gap and prev.startswith("p:") and prev[2:] in _JS_JOINING:
                out.append(" ")
            out.append("p:/")
            i += 1
            gap = False
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "._"):
                j += 1
            out.append("n:" + text[i:j])
            i = j
            gap = False
            continue
        if c.isalpha() or c in "_$" or ord(c) > 127:
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_$" or ord(text[j]) > 127) \
                    and text[j] not in "\u2028\u2029\u00a0\ufeff":
                j += 1
            out.append(text[i:j])
            i = j
            gap = False
            continue
        if c in _JS_PUNCT:
            if gap and ((prev.startswith("p:") and prev[2:] in _JS_JOINING and c in _JS_JOINING)
                        or (c == "." and prev.startswith("n:"))):
                out.append(" ")
            out.append("p:" + c)
            i += 1
            gap = False
            continue
        return None
    return out


def _read(root: Path, rel: str) -> bytes | None:
    path = root / rel
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes()[:MAX_TEXT]
    except OSError:
        return None
