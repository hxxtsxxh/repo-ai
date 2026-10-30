"""`repo-ai review` reports facts about the lines a change adds (secrets on added lines, for one). An
adversarial review of the same parser in the capability adapter showed that repository content and
config could hide added lines: a line starting with `++`, `*.py -diff` in `.gitattributes`, colour or
inter-hunk context forced by config, and file names that look like pathspecs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from repo_ai.review import _added_lines


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "a.py").write_text("x = 1\ny = 2\nz = 3\nw = 4\nv = 5\n", "utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


SECRET = 'TOKEN = "ghp_' + "a" * 36 + '"'


@pytest.mark.parametrize("trap", ["none", "plus", "gitattributes", "color", "inter-hunk"])
def test_an_added_line_is_never_hidden(repo, trap):
    if trap == "gitattributes":
        (repo / ".gitattributes").write_text("*.py -diff\n", "utf-8")
        _git(repo, "add", ".gitattributes")
        _git(repo, "commit", "-qm", "attrs")
    if trap == "color":
        _git(repo, "config", "color.diff", "always")
    if trap == "inter-hunk":
        _git(repo, "config", "diff.interHunkContext", "5")
    body = "x = 1\ns = '''\n++ docs\n'''\ny = 2\nz = 3\nw = 4\nv = 5\n" if trap == "plus" else \
        "x = 1\ny = 2\nz = 3\nw = 4\nv = 5\n"
    (repo / "a.py").write_text(body + SECRET + "\n", "utf-8")
    added = dict(_added_lines(repo, None, "a.py"))
    last = len(body.splitlines()) + 1
    assert added.get(last) == SECRET


def test_unchanged_lines_are_not_added(repo):
    (repo / "a.py").write_text("x = 1\ny = 20\nz = 3\nw = 4\nv = 5\n", "utf-8")
    assert _added_lines(repo, None, "a.py") == [(2, "y = 20")]


@pytest.mark.skipif(os.name == "nt", reason="Windows forbids ':' in a file name")
def test_a_new_or_pathspec_named_file_is_entirely_new(repo):
    (repo / ":(exclude)b.py").write_text("one\ntwo\n", "utf-8")
    assert _added_lines(repo, None, ":(exclude)b.py") == [(1, "one"), (2, "two")]
