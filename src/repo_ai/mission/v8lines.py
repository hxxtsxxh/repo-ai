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
one's (a block that never ran inside a function that did). They are applied outermost first, so the innermost wins.
A character ran if its innermost range has a count above zero in any report the test file's processes wrote.

Lines are split on LF only (git's numbering); CR stays at the end of its line. A line is EXECUTABLE when, outside
comments, it has a letter, digit or underscore: blank lines, comment-only lines and punctuation-only lines (``}``,
``});``) are not. Comments are found by a small scanner that knows strings, template literals and, heuristically,
regular-expression literals; a misread regular expression can hide or expose a line. A line RAN when any of its
non-blank code characters lies in a range that ran: a line that only opens a block that never ran (``} else {``)
counts as run, as does a ``const f = () =>`` line whose function was never called.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from ..verify import isolate

MAX_FILES = 256                     # coverage files one test file's processes may write
MAX_FILE_BYTES = 64 * 1024 * 1024   # one coverage file
MAX_TOTAL_BYTES = 128 * 1024 * 1024  # all of one test file's coverage files together
_WORD = re.compile(r"\w")
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                   "instanceof", "yield", "await"}

Range = tuple[int, int, int]


class Unavailable(Exception):
    """The coverage of one test file cannot be used; the message says why."""


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


def read_reports(ws: Path, rel_dir: str, identity: tuple[int, int]) -> list[list[Any]]:
    """The ``result`` list of every coverage file in `ws/rel_dir`, the directory `prepare` created."""
    if _dir_identity(ws, rel_dir) != identity:
        raise Unavailable("the coverage directory was replaced during the run")
    try:
        with os.scandir(ws / rel_dir) as it:
            entries = list(it)
    except OSError:
        raise Unavailable("the coverage directory could not be listed") from None
    if len(entries) > MAX_FILES:
        raise Unavailable(f"more than {MAX_FILES} coverage files were written")
    names: list[str] = []
    for entry in entries:
        if entry.is_symlink():
            raise Unavailable("the coverage output contains a symbolic link")
        if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
            raise Unavailable("the coverage directory holds something other than coverage files")
        names.append(entry.name)
    if not names:
        raise Unavailable("no coverage was written")
    out: list[list[Any]] = []
    total = 0
    for name in sorted(names):
        try:
            raw = isolate.read_inside(ws, f"{rel_dir}/{name}", MAX_FILE_BYTES)
        except isolate.ReportTooLarge:
            raise Unavailable(f"a coverage file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB") from None
        if raw is None:
            raise Unavailable("a coverage file could not be read safely")
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise Unavailable(f"the coverage output is larger than {MAX_TOTAL_BYTES // (1024 * 1024)} MiB")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise Unavailable("a coverage file is not valid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise Unavailable("a coverage file has no result list")
        out.append(data["result"])
    return out


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _ranges(functions: Any, rel: str) -> list[Range]:
    """Every range of one script entry, in V8's order, validated."""
    bad = Unavailable(f"the coverage of {rel} is malformed")
    if not isinstance(functions, list):
        raise bad
    out: list[Range] = []
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
            out.append((start, end, count))
    if not out:
        raise bad
    return out


def scripts_for(reports: list[list[Any]], inside_root: str, wanted: set[str]) -> dict[str, list[list[Range]]]:
    """{repo-relative path: the ranges of each script entry for it} for the `wanted` files only. An entry for a
    wanted file that is malformed makes the whole coverage unavailable; other scripts are not looked at."""
    prefix = inside_root.rstrip("/") + "/"
    out: dict[str, list[list[Range]]] = {}
    for result in reports:
        for script in result:
            url = script.get("url") if isinstance(script, dict) else None
            if not isinstance(url, str) or not url.startswith("file://"):
                continue
            path = unquote(urlparse(url).path)
            if not path.startswith(prefix):
                continue
            rel = path[len(prefix):]
            if rel in wanted:
                out.setdefault(rel, []).append(_ranges(script.get("functions"), rel))
    return out


def _regex_can_start(text: str, last: int) -> bool:
    """Whether a `/` after the significant character at `last` (-1: none) starts a regular-expression literal."""
    if last < 0:
        return True
    c = text[last]
    if c in _REGEX_AFTER:
        return True
    if not (c.isalnum() or c in "_$"):
        return False
    start = last
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_$"):
        start -= 1
    return text[start:last + 1] in _REGEX_KEYWORDS


def code_mask(text: str) -> bytearray:
    """Per character: 1 for code (strings and template literals included), 0 inside a comment."""
    n = len(text)
    mask = bytearray(b"\x01") * n
    depths: list[int] = []  # brace depth inside each open `${ ... }` of a template literal
    in_template = False
    last = -1  # index of the last significant code character
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
            j = n if j < 0 else j + 2
            mask[i:j] = bytes(j - i)
            i = j
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
        if c == "/" and _regex_can_start(text, last):
            j, in_class = i + 1, False
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
                    break
                j += 1
            last, i = min(j, n - 1), j + 1
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


def _paint(entry: list[Range], length: int, has_bom: bool, rel: str) -> int:
    """One script entry as a bit set over UTF-16 units of the file (bit set: that unit ran)."""
    end = max(e for _, e, _ in entry)
    if end == length:
        shift = 0
    elif has_bom and end == length - 1:
        shift = 1  # an ES module: V8 compiled the source without its byte-order mark
    else:
        raise Unavailable(f"the coverage of {rel} does not match its text (V8 saw {end} UTF-16 units, the file "
                          f"has {length})")
    mark = bytearray(length)
    # outermost first (start ascending, end descending; V8's order breaks ties): an inner range overrides
    for start, stop, count in sorted(entry, key=lambda r: (r[0], -r[1])):
        mark[start + shift:stop + shift] = (b"\x01" if count > 0 else b"\x00") * (stop - start)
    return int.from_bytes(mark, "little")


def line_status(text: str, entries: list[list[Range]], rel: str = "the file") -> tuple[set[int], set[int]]:
    """(executable lines, executable lines that ran) of one file from every script entry for it."""
    pos = _units(text)
    length = pos[-1] if pos is not None else len(text)
    has_bom = text.startswith("﻿")
    ran_bits = 0
    for entry in entries:
        ran_bits |= _paint(entry, length, has_bom, rel)
    ran_units = ran_bits.to_bytes(length, "little") if length else b""
    mask = code_mask(text)
    executable: set[int] = set()
    ran: set[int] = set()
    line, word, hit = 1, False, False
    for idx, ch in enumerate(text):
        if ch == "\n":
            if word:
                executable.add(line)
                if hit:
                    ran.add(line)
            line, word, hit = line + 1, False, False
            continue
        if not mask[idx] or ch.isspace():
            continue
        word = word or bool(_WORD.match(ch))
        hit = hit or bool(ran_units[pos[idx] if pos is not None else idx])
    if word:
        executable.add(line)
        if hit:
            ran.add(line)
    return executable, ran
