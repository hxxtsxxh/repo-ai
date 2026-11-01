"""Every relative Markdown link in a tracked document resolves to a tracked file or directory.

Found missing: public docs linked 24 times to `docs/research/` and `docs/EXECUTION_LEDGER.md`, which live only in the
private development history."""
from __future__ import annotations

import posixpath
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
SKIP = ("benchmarks/skill-vet-fresh-v1/corpus/",)  # defanged third-party-style fixture skills, kept verbatim


def _tracked() -> set[str]:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return {p for p in out.decode("utf-8").split("\0") if p}


def test_relative_markdown_links_resolve():
    files = _tracked()
    dirs = set()
    for f in files:
        d = posixpath.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            d = posixpath.dirname(d)
    broken = []
    for f in sorted(files):
        if not f.endswith(".md") or f.startswith(SKIP) or not (ROOT / f).is_file():
            continue
        text = FENCE.sub("", (ROOT / f).read_text(encoding="utf-8", errors="replace"))
        for target in LINK.findall(text):
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("/"):
                continue  # a URL, mailto, or site-absolute path
            path = posixpath.normpath(posixpath.join(posixpath.dirname(f), target))
            if path not in files and path not in dirs:
                broken.append(f"{f}: {target}")
    assert not broken, "\n".join(broken)
