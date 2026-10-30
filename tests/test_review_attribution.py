"""Regression tests: `repo-ai review` secret facts land on the right file and line.

Written by Session A's independent audit (25 cases); the verify/changes.py form-feed case is left
to Session A's own corrective PR, which owns that file."""
import os
import subprocess

import pytest

from repo_ai import review
from repo_ai.security import scan_text

KEY = "AKIAQWERTYUIOPASDFGH"
BASE = "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n"


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit(repo, files):
    for rel, text in files.items():
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c")


def secrets(repo):
    return sorted(f"{path}:{n}" for path, _, _ in review._numstat(repo, None)
                  for n, text in review._added_lines(repo, None, path) for _ in scan_text(path, text))


@pytest.mark.parametrize("trap", ["plus", "-diff", "color", "inter-hunk", "textconv", "external"])
def test_added_secret_is_reported_at_its_line(repo, trap):
    _commit(repo, {"a.py": BASE, **({".gitattributes": "*.py -diff\n"} if trap == "-diff" else {}),
                   **({".gitattributes": "*.py diff=t\n"} if trap == "textconv" else {})})
    if trap == "color":
        _git(repo, "config", "color.diff", "always")
    if trap == "inter-hunk":
        _git(repo, "config", "diff.interHunkContext", "5")
    if trap == "textconv":
        _git(repo, "config", "diff.t.textconv", "grep -v AKIA")
    if trap == "external":
        _git(repo, "config", "diff.external", "true")
    lines = BASE.splitlines(keepends=True)
    if trap == "plus":
        lines[1:1] = [f"++k = '{KEY}'\n", f"z = '{KEY.replace('Q', 'W')}'\n"]
        want = ["a.py:2", "a.py:3"]
    elif trap == "inter-hunk":
        lines[1:1] = ["x = 0\n"]
        lines[4:4] = [f"k = '{KEY}'\n"]
        want = ["a.py:5"]
    else:
        lines[1:1] = [f"k = '{KEY}'\n"]
        want = ["a.py:2"]
    if trap in {"external", "textconv"}:  # a pre-existing secret must not count as added
        _commit(repo, {"a.py": f"old = '{KEY.replace('Q', 'X')}'\n" + BASE})
        lines.insert(0, f"old = '{KEY.replace('Q', 'X')}'\n")
        want = ["a.py:3"]
    (repo / "a.py").write_text("".join(lines), encoding="utf-8")
    assert secrets(repo) == want


_NOT_ON_WINDOWS = pytest.mark.skipif(os.name == "nt", reason="Windows forbids this character in a file name")


@pytest.mark.parametrize("name", ["café.py", pytest.param("tab\t.py", marks=_NOT_ON_WINDOWS),
                                  pytest.param('q"t.py', marks=_NOT_ON_WINDOWS), "x{1}.py",
                                  pytest.param("l => r.py", marks=_NOT_ON_WINDOWS),
                                  pytest.param("*.py", marks=_NOT_ON_WINDOWS), "[a].py",
                                  pytest.param(":(exclude)z.py", marks=_NOT_ON_WINDOWS)])
@pytest.mark.parametrize("tracked", [False, True])
def test_unusual_names_are_attributed_literally(repo, name, tracked):
    _commit(repo, {"a.py": BASE, **({name: "x = 1\n"} if tracked else {})})
    (repo / "a.py").write_text(BASE.replace("b = 2\n", f"b = 2\nk = '{KEY}'\n"), encoding="utf-8")  # a.py:3
    (repo / name).write_text(f"x = 1\nt = '{KEY.replace('Q', 'Z')}'\n", encoding="utf-8")  # untracked, line 2
    assert secrets(repo) == sorted([f"{name}:2", "a.py:3"])


def test_line_separators_inside_a_line_do_not_shift_numbers(repo):
    _commit(repo, {"a.py": BASE})
    (repo / "a.py").write_text(BASE.replace("a = 1\n", f"a = 1\ns = 'x +y'\nk = '{KEY}'\n"), encoding="utf-8")
    assert secrets(repo) == ["a.py:3"]


def test_a_renamed_file_adds_nothing(repo):
    _commit(repo, {"old.py": f"k = '{KEY}'\n" + BASE})
    _git(repo, "mv", "old.py", "new.py")
    assert secrets(repo) == []

