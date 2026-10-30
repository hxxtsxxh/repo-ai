"""A virtualenv the repository itself commits is the repository's code: verify
never executes it on the host (it would run unsandboxed before any sandbox
starts), and never picks it as the interpreter the tests run with."""

from __future__ import annotations

import sys
from pathlib import Path

from test_verify_adaptive import _git

from repo_ai.verify.execute import project_python


def _repo_with_venv(tmp_path: Path, commit_it: bool) -> tuple[Path, Path]:
    root = tmp_path / "r"
    (root / ".venv" / "bin").mkdir(parents=True)
    marker = tmp_path / "executed-on-the-host"
    py = root / ".venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\ntouch {marker}\nexec python3 \"$@\"\n")
    py.chmod(0o755)
    xy = f"{sys.version_info[0]}.{sys.version_info[1]}"  # the metadata a real virtualenv has (read, never run)
    windows = sys.platform == "win32"
    home = Path(sys.base_prefix) if windows else Path(sys.base_prefix) / "bin"
    (root / ".venv" / "pyvenv.cfg").write_text(f"home = {home}\nversion = {xy}.0\n")
    (root / ".venv" / ("Lib" if windows else f"lib/python{xy}") / "site-packages").mkdir(parents=True)
    (root / "a.py").write_text("x = 1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "a.py", *([".venv"] if commit_it else []))
    _git(root, "commit", "-qm", "base")
    return root, marker


def test_a_committed_virtualenv_is_never_executed_or_chosen(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, marker = _repo_with_venv(tmp_path, commit_it=True)
    python, _reads = project_python(root)
    assert not marker.exists()
    assert Path(python).resolve() != (root / ".venv" / "bin" / "python").resolve()


def test_an_untracked_local_virtualenv_is_still_the_project_interpreter(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, marker = _repo_with_venv(tmp_path, commit_it=False)
    python, _reads = project_python(root)
    assert python == str(root / ".venv" / "bin" / "python")
    assert not marker.exists()  # chosen, but read from its metadata, never executed on the host (F2b)


def test_an_active_virtualenv_that_the_repository_commits_is_not_trusted_either(tmp_path: Path, monkeypatch):
    root, marker = _repo_with_venv(tmp_path, commit_it=True)
    monkeypatch.setenv("VIRTUAL_ENV", str(root / ".venv"))
    python, _reads = project_python(root)
    assert not marker.exists() and Path(python).resolve() != (root / ".venv" / "bin" / "python").resolve()


def _case_insensitive(tmp_path: Path) -> bool:
    (tmp_path / "CaseProbe").write_text("")
    return (tmp_path / "caseprobe").exists()


def test_a_committed_virtualenv_spelled_in_another_case_is_not_trusted_either(tmp_path: Path, monkeypatch):
    import pytest
    if not _case_insensitive(tmp_path):
        pytest.skip("the filesystem is case-sensitive: `.VENV` is not `.venv` here")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root = tmp_path / "r"
    (root / ".VENV" / "bin").mkdir(parents=True)
    marker = tmp_path / "executed-on-the-host"
    py = root / ".VENV" / "bin" / "python"
    py.write_text(f"#!/bin/sh\ntouch {marker}\nexec python3 \"$@\"\n")
    py.chmod(0o755)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    python, _reads = project_python(root)
    assert not marker.exists()
    assert Path(python).resolve() != py.resolve()
