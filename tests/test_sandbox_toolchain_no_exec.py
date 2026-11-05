"""Finding the directories a host sandbox must read for a toolchain never
runs a program found on PATH (the F2b review, 2026-10-25): a pyenv or asdf
shim, which may be any file named like one (a PATH entry inside the
repository), was run on the host to ask where its interpreter lives."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from repo_ai import sandbox


def _shim(tmp_path: Path, name: str = "python3") -> tuple[Path, Path]:
    root = tmp_path / "tool"
    (root / "shims").mkdir(parents=True)
    marker = tmp_path / "ran"
    shim = root / "shims" / name
    shim.write_text(f"#!/bin/sh\ntouch {marker}\necho /\n")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return root, marker


@pytest.mark.skipif(os.name == "nt", reason="POSIX shims")
def test_a_shim_on_path_is_never_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, marker = _shim(tmp_path)
    (root / "versions").mkdir()
    monkeypatch.setenv("PATH", f"{root / 'shims'}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PYENV_VERSION", "system")  # pyenv_target cannot decide: the old code ran the shim
    sandbox._toolchain_dirs_cached.cache_clear()
    dirs = sandbox._toolchain_dirs_cached("python", os.environ["PATH"], "")
    assert not marker.exists(), "the shim was run on the host"
    assert str((root / "versions").resolve()) in dirs


@pytest.mark.skipif(os.name == "nt", reason="POSIX shims")
def test_a_shim_with_no_versions_folder_adds_nothing_and_runs_nothing(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch):
    root, marker = _shim(tmp_path)
    monkeypatch.setenv("PATH", f"{root / 'shims'}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PYENV_VERSION", "system")
    sandbox._toolchain_dirs_cached.cache_clear()
    dirs = sandbox._toolchain_dirs_cached("python", os.environ["PATH"], "")
    assert not marker.exists()
    assert not any(d.startswith(str(root.resolve())) for d in dirs), dirs
