"""`isolate.snapshot` builds each entry's repository-relative path from its directory's prefix instead of
`Path(e.path).relative_to(root)` (most of the snapshot's time on a project with a virtualenv). Oracle: the previous
walk, kept here verbatim, must give the same records on a tree with nesting, links, skips and walked-only dirs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from repo_ai.verify import isolate


def _previous_walk(root: Path, skip: tuple[str, ...], keep: frozenset[str]) -> dict:
    stat: dict = {}
    root = root.resolve()
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except OSError:
            continue
        for e in entries:
            rel = Path(e.path).relative_to(root).as_posix()
            if isolate._skipped(rel, skip, e.is_dir(follow_symlinks=False), keep):
                continue
            st = e.stat(follow_symlinks=False)
            kind = "l" if e.is_symlink() else "d" if e.is_dir(follow_symlinks=False) else "f"
            if kind == "d":
                if not isolate._walked_only(rel, skip):
                    stat[rel] = ("d", st.st_mode)
                stack.append(Path(e.path))
            elif kind == "l":
                stat[rel] = ("l", os.readlink(e.path))
            else:
                stat[rel] = ("f", st.st_size, st.st_mtime_ns, st.st_mode, st.st_ino)
    return stat


def _tree(root: Path) -> list[str]:
    files = ["a.py", "pkg/__init__.py", "pkg/deep/x/y/z.py", ".venv/lib/site/mod.py", ".venv/bin/python3",
             ".repo-ai/state/evidence/e.json", "build/out.o", "naïve dir/ü.txt", "pkg/__pycache__/m.pyc"]
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(rel)
    (root / "empty").mkdir()
    if sys.platform != "win32":
        (root / "link").symlink_to("pkg/__init__.py")
        (root / "dirlink").symlink_to("pkg", target_is_directory=True)
    return files


@pytest.mark.parametrize("skip", [(".repo-ai/state/",),
                                  (".repo-ai/state/", "re:.*\\.pyc", "redir:\\.venv(/.*)?", "build/")])
def test_the_walk_records_exactly_what_the_previous_one_did(tmp_path, skip):
    files = _tree(tmp_path)
    keep = frozenset(f for f in files if not f.startswith(".venv"))
    snap = isolate.snapshot(tmp_path, files=sorted(keep), skip=skip)
    assert snap.stat == _previous_walk(tmp_path, skip, keep)
    assert "pkg/deep/x/y/z.py" in snap.stat and not any(k.startswith(".repo-ai/state/") for k in snap.stat)
