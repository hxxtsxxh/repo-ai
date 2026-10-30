"""Missions run tests with the checkout's interpreter (PR #17 review): a src-layout package installed in editable mode
points the venv's `.pth` at the checkout, and a mission workspace must import the candidate's copy of it."""
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from repo_ai.mission import verification
from repo_ai.mission.runtime import commit_snapshot, git
from repo_ai.verify import isolate

PREF = "seatbelt" if sys.platform == "darwin" else "bwrap"
SITE = Path(sys.prefix) / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, env=env, capture_output=True, text=True).stdout


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """The user's checkout: src-layout `pkg` (VALUE = 1, buggy), a `.venv` with an editable `.pth` to its `src`."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root = tmp_path / "checkout"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("VALUE = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_v.py").write_text("import pkg\n\ndef test_v():\n    assert pkg.VALUE == 2, pkg.__file__\n")
    (root / ".gitignore").write_text(".venv/\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "b")
    subprocess.run([sys._base_executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True)
    site = next((root / ".venv" / "lib").glob("python*/site-packages"))
    for name in ("pytest", "_pytest", "pluggy", "iniconfig", "packaging", "py.py", "pygments"):
        src = SITE / name
        if src.exists():
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, site / name)
    (site / "_pkg_editable.pth").write_text(str((root / "src").resolve()) + "\n")  # hatchling-style editable
    return root


def test_a_mission_workspace_imports_the_candidates_copy_of_an_editable_package(checkout):
    with isolate.materialize_commit(checkout, "HEAD", label="mission-x", dependencies=True) as ws:
        (ws.path / "src" / "pkg" / "__init__.py").write_text("VALUE = 2\n")  # the provider's candidate fix
        _git(ws.path, "init", "-q")
        _git(ws.path, "add", "-A")
        _git(ws.path, "commit", "-qm", "c")
        obs = verification.observe(ws.path, "python -m pytest -q", sandbox_preference=PREF, project_root=checkout)
    assert obs["outcomes"] and set(obs["outcomes"].values()) == {"pass"}, obs["reasons"]
    assert obs["executor"]["interpreter"].startswith(str(checkout.resolve() / ".venv"))


def test_snapshot_names_are_literal_never_patterns(tmp_path):
    for name in ("pages/[id].py", "pages/i.py", "-rf.py", "with space.py", unicodedata.normalize("NFD", "café.py")):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n")
    (tmp_path / ".gitignore").write_text("*.py\n")
    tracked = ["pages/[id].py", "-rf.py", "with space.py", unicodedata.normalize("NFD", "café.py"), ".gitignore"]
    commit_snapshot(tmp_path, tracked, "m")
    listed = git(tmp_path, "-c", "core.quotepath=off", "ls-files", "-z").split("\0")
    assert "pages/i.py" not in listed  # `[id]` must not match the untracked, ignored `i.py`
    assert {"pages/[id].py", "-rf.py", "with space.py", ".gitignore"} <= set(listed)
