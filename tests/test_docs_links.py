"""Relative links in tracked Markdown files resolve to a tracked file or directory, as GitHub renders them.

Covers inline links (with or without a title or angle brackets) and reference definitions; skips URLs, site-absolute
paths, fenced and inline code, and the Starlight site pages (resolved against page URLs, checked by
site/scripts/check-links.mjs). Anchors are not checked. Found missing: public docs linked 24 times to `docs/research/`
and `docs/EXECUTION_LEDGER.md`, which live only in the private development history."""
from __future__ import annotations

import os
import posixpath
import re
import time
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
# linear: a target cannot contain "(" or ")", and a title is one quoted or parenthesised run
INLINE = re.compile(r"""\]\(\s*(<[^>\n]+>|[^()\s]+)(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^)\n]*\)))?\s*\)""")
REFDEF = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:\s*(<[^>\n]+>|\S+)", re.M)  # not a footnote ([^1]: text)
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[`~]*[ \t]*$", re.S | re.M)
CODE = re.compile(r"(`+)(?!`)[^\n]+?(?<!`)\1")
SKIP = ("benchmarks/skill-vet-fresh-v1/corpus/",  # defanged third-party-style fixture skills, kept verbatim
        "site/src/content/")  # Starlight pages: links resolve against the page URL, not the file


def _tracked() -> set[str]:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    if out.returncode:
        if os.environ.get("CI"):
            pytest.fail("git ls-files failed on CI: " + out.stderr.decode("utf-8", "replace")[:200])
        pytest.skip("git ls-files failed: " + out.stderr.decode("utf-8", "replace")[:200])
    return {p for p in out.stdout.decode("utf-8").split("\0") if p}


def targets(text: str) -> list[str]:
    text = CODE.sub("", FENCE.sub("", text))
    found = [m.group(1) for m in INLINE.finditer(text)] + [m.group(1) for m in REFDEF.finditer(text)]
    return [t[1:-1] if t.startswith("<") else t for t in found]


def _relative(target: str) -> str | None:
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith(("/", "//")):
        return None  # an anchor, URL, mailto, or site-absolute path
    return unquote(target)


def test_the_parser_reads_the_link_forms_github_renders():
    md = ('[a](x.md) [b](<y z.md> "t") [c](w.md \'t\') [d](v.md#h) [e](u.md?plain=1) [f](https://e.x) [g](#top)\n'
          "[h](t.md (title))\n`[no](inline.md)`\n```\n[no](fenced.md)\n```\n  ~~~~\n  [no](indented.md)\n  ~~~~\n"
          "[r]: ref.md\n[^1]: A footnote, not a link.\n")
    found = [_relative(t) for t in targets(md) if _relative(t)]
    assert found == ["x.md", "y z.md", "w.md", "v.md", "u.md", "t.md", "ref.md"]
    assert _relative("my%20file.md") == "my file.md"


def test_the_parser_is_linear_on_pathological_lines():
    start = time.perf_counter()
    targets("](" * 50_000)
    targets('](a "' + " " * 50_000)
    targets("```\n" * 5_000)
    assert time.perf_counter() - start < 3.0


def test_relative_markdown_links_resolve():
    files = _tracked()
    dirs = {"."}
    for f in files:
        d = posixpath.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            d = posixpath.dirname(d)
    broken, checked = [], 0
    for f in sorted(files):
        if not f.endswith(".md") or f.startswith(SKIP) or not (ROOT / f).is_file():
            continue
        for target in targets((ROOT / f).read_text(encoding="utf-8", errors="replace")):
            rel = _relative(target)
            if rel is None:
                continue
            checked += 1
            path = posixpath.normpath(posixpath.join(posixpath.dirname(f), rel))
            # a trailing slash after a file name is a 404 on GitHub
            if not (path in dirs or (path in files and not rel.endswith("/"))):
                broken.append(f"{f}: {target}")
    assert checked > 100, checked  # the scan actually reads links
    assert not broken, "\n".join(broken)
