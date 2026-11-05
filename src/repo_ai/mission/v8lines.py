"""The changed lines one Node test file ran, from V8's own coverage output (``NODE_V8_COVERAGE``).

The output is written by the test process, which runs untrusted repository code, so it is read as hostile input:
only from the directory repo-ai created for it (checked to be the same directory, never through a symbolic link),
with a bound on the number of files and on their size, and validated field by field. Anything unexpected raises
`Unavailable` with a reason; the caller then reports that test file's lines as unavailable, never as "not run".
A test can still write a coverage file that claims lines ran: like every tracer record, this one is informational.

Offsets. V8 counts ``startOffset``/``endOffset`` in UTF-16 code units of the script source it compiled (checked:
an astral character such as an emoji is two units, CR of CRLF is one). A CommonJS module keeps a leading byte-order
mark in that source; an ES module does not. Each script's outermost range covers the whole source, so its end must
equal the file's length in UTF-16 units, or that length minus one for a file that starts with a byte-order mark the
loader dropped; any other length (a wrapper, a transpiled or altered source) makes the coverage unavailable.

Ranges. Within a script, ranges are properly nested or disjoint, and an inner range's count replaces the outer
one's (a block that never ran inside a function that did). One sweep over the ranges sorted outermost first keeps a
stack of the open ones, so the innermost wins. Each entry (every process that loaded the file writes one: a whole
`node --test` suite writes one per test file) is folded into one per-file "ran" bit map as soon as its coverage file
is parsed, so memory does not grow with the number of entries; an entry whose ran runs equal an earlier one's is not
painted again. A character ran if its innermost range has a count above zero in any entry. Work is bounded: one
entry with more ranges than four per UTF-16 unit of its text is refused, as is a run with more than 2,000,000
ranges for the watched files, more coverage files than the caller allows, a file over 32 MiB or 2 GiB in all; an
optional deadline is checked between files and entries.

Lines are split on LF only (git's numbering); CR stays at the end of its line. A line is EXECUTABLE when, outside
comments, it has a letter, digit or underscore: blank lines, comment-only lines and punctuation-only lines (``}``,
``});``) are not. The change-exercise assurance uses the same definition. Comments are found by a small scanner that
knows strings, template literals and, heuristically, regular-expression literals (a ``/`` after ``)``, ``]``, an
identifier, a number, ``++`` or ``--`` is a division, except after the ``)`` of ``if``, ``while``, ``for`` or
``with``; a regular expression must close on its line); a ``/*`` with no
closing ``*/`` is not taken as a comment, so a misread cannot hide the rest of the file, but it can still hide or
expose a line. A line RAN when any of its
non-blank code characters lies in a range that ran: a line that only opens a block that never ran (``} else {``)
counts as run, as does a ``const f = () =>`` line whose function was never called.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import stat
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from ..verify import isolate

MAX_FILES = 256                         # coverage files one test file's processes may write (see `files_allowed`)
MAX_FILES_CEILING = 20_000              # coverage files any run may write
MAX_FILE_BYTES = 32 * 1024 * 1024       # one coverage file (each is parsed, folded and dropped before the next)
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # all of one run's coverage files together
MAX_TOTAL_RANGES = 2_000_000            # ranges of the watched files over a whole run
RANGES_PER_UNIT = 4                     # more ranges in one entry than this per UTF-16 unit of the text is not V8
_WORD = re.compile(r"\w")
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_CONDITION_KEYWORDS = {"if", "while", "for", "with"}
_REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                   "instanceof", "yield", "await"}

Range = tuple[int, int, int]
Entry = tuple[Range, ...]


class Unavailable(ValueError):
    """The coverage cannot be used; the message says why."""


def _check(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise Unavailable("no time was left to read its coverage")


def _dir_identity(ws: Path, rel_dir: str) -> tuple[int, int]:
    """(device, inode) of `ws/rel_dir`, refusing a symbolic link or a non-directory at any component."""
    parts = [p for p in PurePosixPath(rel_dir).parts if p not in {"", "."}]
    if not parts or ".." in parts:
        raise Unavailable("the coverage directory is not inside the workspace")
    cur = Path(ws)
    info = None
    for part in parts:
        cur = cur / part
        try:
            info = os.lstat(cur)
        except OSError:
            raise Unavailable("no coverage was written") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Unavailable("the coverage directory was replaced by something that is not a directory")
    assert info is not None
    return info.st_dev, info.st_ino


def prepare(ws: Path, rel_dir: str) -> tuple[int, int]:
    """Create the (empty) coverage directory before the run; its identity, to check after the run."""
    path = isolate.run_dir(ws, rel_dir)
    ident = _dir_identity(ws, rel_dir)
    if any(path.iterdir()):
        raise Unavailable("the coverage directory was not empty before the run")
    return ident


def files_allowed(test_files: int) -> int:
    """Coverage files a run of `test_files` test files may write: a process per file and a few children each."""
    return min(MAX_FILES_CEILING, max(MAX_FILES, 4 * test_files + 16))


class Folded:
    """What one run's coverage says about the watched files: an `Accumulator` per watched file, and which wanted
    files (watched or merely required to be present) had at least one valid entry."""

    def __init__(self, accumulators: dict[str, Accumulator], seen: set[str]) -> None:
        self.accumulators = accumulators
        self.seen = seen


def fold(ws: Path, rel_dir: str, identity: tuple[int, int], inside_root: str, texts: dict[str, str], *,
         present: set[str] | None = None, deadline: float | None = None, lenient: bool = False,
         max_files: int = MAX_FILES) -> Folded:
    """Read every coverage file in `ws/rel_dir` (the directory `prepare` created) and fold the entries for the
    watched files (`texts`: repo-relative path -> its text) into their accumulators; `present`: other files whose
    having an entry is recorded in `seen` (the test file itself). Each coverage file is parsed, folded and dropped
    before the next is read. `lenient` (the assurance, where less coverage can only mean more lines reported as never
    run): a malformed coverage file or entry, or an entry that does not fit its text, is skipped instead of making
    everything unavailable; the directory, link, size, count, range and time checks still apply."""
    if _dir_identity(ws, rel_dir) != identity:
        raise Unavailable("the coverage directory was replaced during the run")
    try:
        with os.scandir(ws / rel_dir) as it:
            entries = list(itertools.islice(it, max_files + 1))
    except OSError:
        raise Unavailable("the coverage directory could not be listed") from None
    if len(entries) > max_files:
        raise Unavailable(f"more than {max_files} coverage files were written")
    names: list[str] = []
    for entry in entries:
        if entry.is_symlink():
            raise Unavailable("the coverage output contains a symbolic link")
        if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
            raise Unavailable("the coverage directory holds something other than coverage files")
        names.append(entry.name)
    if not names:
        raise Unavailable("no coverage was written")
    accs = {rel: Accumulator(text, rel, lenient) for rel, text in texts.items()}
    wanted = set(texts) | set(present or ())
    seen: set[str] = set()
    total = ranges = 0
    for name in sorted(names):
        _check(deadline)
        try:
            raw = isolate.read_inside(ws, f"{rel_dir}/{name}", MAX_FILE_BYTES)
        except isolate.ReportTooLarge:
            raise Unavailable(f"a coverage file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB") from None
        if raw is None:
            raise Unavailable("a coverage file could not be read safely")
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise Unavailable(f"the coverage output is larger than {MAX_TOTAL_BYTES // (1024 ** 3)} GiB")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            if lenient:
                continue
            raise Unavailable("a coverage file is not valid JSON") from None
        del raw
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            if lenient:
                continue
            raise Unavailable("a coverage file has no result list")
        found = scripts_for([data["result"]], inside_root, wanted, lenient=lenient)
        del data
        for rel, items in found.items():
            seen.add(rel)
            acc = accs.get(rel)
            for item in items:
                ranges += len(item)
                if ranges > MAX_TOTAL_RANGES:
                    raise Unavailable(f"the coverage output has more than {MAX_TOTAL_RANGES} ranges for the "
                                      "watched files")
                if acc is not None:
                    _check(deadline)
                    acc.add(item)
    return Folded(accs, seen)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _ranges(functions: Any, rel: str) -> Entry:
    """Every distinct range of one script entry, in V8's order, validated."""
    bad = Unavailable(f"the coverage of {rel} is malformed")
    if not isinstance(functions, list):
        raise bad
    out: dict[Range, None] = {}
    for fn in functions:
        ranges = fn.get("ranges") if isinstance(fn, dict) else None
        if not isinstance(ranges, list):
            raise bad
        for r in ranges:
            if not isinstance(r, dict):
                raise bad
            start, end, count = _int(r.get("startOffset")), _int(r.get("endOffset")), _int(r.get("count"))
            if start is None or end is None or count is None or start > end:
                raise bad
            out[(start, end, count)] = None
    if not out:
        raise bad
    return tuple(out)


def scripts_for(reports: list[list[Any]], inside_root: str, wanted: set[str], *,
                lenient: bool = False) -> dict[str, list[Entry]]:
    """{repo-relative path: the distinct script entries for it} for the `wanted` files only. An entry for a wanted
    file that is malformed makes the whole coverage unavailable; other scripts, and entries whose URL does not parse,
    are not looked at."""
    prefix = inside_root.rstrip("/") + "/"
    out: dict[str, dict[Entry, None]] = {}
    for result in reports:
        for script in result:
            url = script.get("url") if isinstance(script, dict) else None
            if not isinstance(url, str) or not url.startswith("file://"):
                continue
            try:
                path = unquote(urlparse(url).path)
            except ValueError:
                continue
            if not path.startswith(prefix):
                continue
            rel = path[len(prefix):]
            if rel in wanted:
                try:
                    entry = _ranges(script.get("functions"), rel)
                except Unavailable:
                    if lenient:
                        continue
                    raise
                out.setdefault(rel, {})[entry] = None
    return {rel: list(items) for rel, items in out.items()}


def _regex_can_start(text: str, last: int) -> bool:
    """Whether a `/` after the significant character at `last` (-1: none) starts a regular-expression literal."""
    if last < 0:
        return True
    c = text[last]
    if c in "+-" and last > 0 and text[last - 1] == c:
        return False  # `x++ / 2`: a postfix increment or decrement is an operand
    if c in _REGEX_AFTER:
        return True
    return _word_at(text, last) in _REGEX_KEYWORDS


def _word_at(text: str, last: int) -> str:
    """The identifier or keyword ending at index `last` ("" when none does)."""
    if last < 0 or not (text[last].isalnum() or text[last] in "_$"):
        return ""
    start = last
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_$"):
        start -= 1
    return text[start:last + 1]


def _regex_end(text: str, i: int) -> int:
    """Index of the `/` closing the regular expression opened at `i`, or -1 when none closes it on its line."""
    j, in_class, n = i + 1, False, len(text)
    while j < n and text[j] != "\n":
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return j
        j += 1
    return -1


def code_mask(text: str) -> bytearray:
    """Per character: 1 for code (strings and template literals included), 0 inside a comment."""
    n = len(text)
    mask = bytearray(b"\x01") * n
    depths: list[int] = []  # brace depth inside each open `${ ... }` of a template literal
    in_template = False
    last = -1  # index of the last significant code character
    parens: list[bool] = []  # open `(`: whether it follows if / while / for / with
    statement_paren = -2  # index of the last `)` that closed such a condition: a `/` right after it is a regex
    i = 0
    while i < n:
        c = text[i]
        if in_template:
            if c == "\\":
                i += 2
            elif c == "`":
                in_template, last, i = False, i, i + 1
            elif c == "$" and text.startswith("${", i):
                depths.append(0)
                in_template, last, i = False, i + 1, i + 2
            else:
                i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            mask[i:j] = bytes(j - i)
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j >= 0:  # an unclosed `/*` is a misread (it would be a syntax error): it hides nothing
                mask[i:j + 2] = bytes(j + 2 - i)
                i = j + 2
                continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            last, i = min(j, n - 1), j + 1
            continue
        if c == "`":
            in_template, i = True, i + 1
            continue
        if c == "/" and (last == statement_paren or _regex_can_start(text, last)):
            j = _regex_end(text, i)
            if j >= 0:
                last, i = j, j + 1
                continue
        if depths:
            if c == "{":
                depths[-1] += 1
            elif c == "}":
                if depths[-1] == 0:
                    depths.pop()
                    in_template, i = True, i + 1
                    continue
                depths[-1] -= 1
        if c == "(":
            parens.append(_word_at(text, last) in _CONDITION_KEYWORDS)
        elif c == ")" and parens and parens.pop():
            statement_paren = i
        if not c.isspace():
            last = i
        i += 1
    return mask


def _units(text: str) -> list[int] | None:
    """UTF-16 offset of each character (and of the end), or None when every character is one unit."""
    if not any(ord(ch) > 0xFFFF for ch in text):
        return None
    out = [0] * (len(text) + 1)
    u = 0
    for idx, ch in enumerate(text):
        out[idx] = u
        u += 2 if ord(ch) > 0xFFFF else 1
    out[len(text)] = u
    return out


def _sweep(entry: Entry, shift: int) -> list[tuple[int, int]]:
    """The [start, end) runs of one script entry whose innermost range ran, shifted into file units."""
    out: list[tuple[int, int]] = []
    stack: list[tuple[int, bool]] = []  # open ranges: (end, ran), innermost last
    cursor = 0

    def advance(to: int) -> None:
        nonlocal cursor
        while stack and stack[-1][0] <= to:
            end, ran = stack.pop()
            if end > cursor:
                if ran:
                    out.append((cursor + shift, end + shift))
                cursor = end
        if stack and to > cursor:
            if stack[-1][1]:
                out.append((cursor + shift, to + shift))
            cursor = to
        cursor = max(cursor, to)

    # outermost first (start ascending, end descending; V8's order breaks ties, so a later twin wins)
    for start, stop, count in sorted(entry, key=lambda r: (r[0], -r[1])):
        advance(start)
        stack.append((stop, count > 0))
    advance(max(stop for _, stop, _ in entry))
    return out


class Accumulator:
    """One watched file's "ran" bit map over its UTF-16 units, folded entry by entry."""

    def __init__(self, text: str, rel: str = "the file", lenient: bool = False) -> None:
        self.text, self.rel, self.lenient = text, rel, lenient
        self.pos = _units(text)
        self.length = self.pos[-1] if self.pos is not None else len(text)
        self.has_bom = text.startswith("\ufeff")
        self.ran = bytearray(self.length)
        self.entries = 0  # entries folded in
        self._patterns: set[bytes] = set()

    def add(self, entry: Entry) -> None:
        """Fold one script entry in. Strict: an entry that does not fit the text is `Unavailable`; lenient: it is
        skipped (less coverage only reports more lines as never run)."""
        if len(entry) > RANGES_PER_UNIT * self.length + 64:
            if self.lenient:
                return
            raise Unavailable(f"the coverage of {self.rel} has more ranges than its text can hold")
        end = max(e for _, e, _ in entry)
        if end == self.length:
            shift = 0
        elif self.has_bom and end == self.length - 1:
            shift = 1  # an ES module: V8 compiled the source without its byte-order mark
        elif self.lenient:
            return
        else:
            raise Unavailable(f"the coverage of {self.rel} does not match its text (V8 saw {end} UTF-16 units, the "
                              f"file has {self.length})")
        runs = _sweep(entry, shift)  # disjoint and in order
        self.entries += 1
        key = hashlib.blake2b(repr(runs).encode(), digest_size=16).digest()
        if key in self._patterns:
            return
        self._patterns.add(key)
        for start, stop in runs:
            self.ran[start:stop] = b"\x01" * (stop - start)

    def line_status(self) -> tuple[set[int], set[int]]:
        """(executable lines, executable lines any code of which ran)."""
        if not self.entries:
            return executable_lines(self.text), set()
        executable, hit, _ = _scan(self.text, bytes(self.ran), self.pos)
        return executable, hit

    def never_run(self) -> tuple[set[int], set[int]]:
        """(executable lines, executable lines with a code character that never ran in any entry): the assurance's
        block-precise view, where a never-taken branch on an otherwise executed line (``while (c) n++;``) still
        counts. A file no entry covers never ran at all."""
        if not self.entries:
            executable = executable_lines(self.text)
            return executable, set(executable)
        executable, _, miss = _scan(self.text, bytes(self.ran), self.pos)
        return executable, miss


def _scan(text: str, ran: bytes | None, pos: list[int] | None) -> tuple[set[int], set[int], set[int]]:
    """(executable lines, those with a code character that ran, those with a code character that did not)."""
    mask = code_mask(text)
    executable: set[int] = set()
    hit_lines: set[int] = set()
    miss_lines: set[int] = set()
    line, word, hit, miss = 1, False, False, False

    def close() -> None:
        if word:
            executable.add(line)
            if hit:
                hit_lines.add(line)
            if miss:
                miss_lines.add(line)

    for idx, ch in enumerate(text):
        if ch == "\n":
            close()
            line, word, hit, miss = line + 1, False, False, False
            continue
        if not mask[idx] or ch.isspace() or (idx == 0 and ch == "\ufeff"):
            continue
        word = word or bool(_WORD.match(ch))
        if ran is not None and ran[pos[idx] if pos is not None else idx]:
            hit = True
        else:
            miss = True
    close()
    return executable, hit_lines, miss_lines


def executable_lines(text: str) -> set[int]:
    """The lines this module (and the change-exercise assurance) treats as executable."""
    return _scan(text, None, None)[0]


def _accumulate(text: str, entries: list[Entry], rel: str, deadline: float | None, lenient: bool) -> Accumulator:
    acc = Accumulator(text, rel, lenient)
    for entry in entries:
        _check(deadline)
        acc.add(entry)
    return acc


def line_status(text: str, entries: list[Entry], rel: str = "the file",
                deadline: float | None = None) -> tuple[set[int], set[int]]:
    """(executable lines, executable lines any code of which ran) of one file from the given script entries."""
    return _accumulate(text, entries, rel, deadline, False).line_status()


def never_run(text: str, entries: list[Entry], rel: str = "the file",
              deadline: float | None = None) -> tuple[set[int], set[int]]:
    """`Accumulator.never_run` over the given entries; an entry that does not fit the text is skipped."""
    return _accumulate(text, entries, rel, deadline, True).never_run()
