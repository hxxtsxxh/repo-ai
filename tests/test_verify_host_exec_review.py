# Vendored from the defensive review of integration/corrective-20261025 (2026-10-25): repo-ai never runs
# a program inside the repository on the host, nor a version-manager shim the repository's version file steers.
"""Invariant 2 (F2b): repo-ai never executes on the host a program located
inside the repository (or reached through PATH entries named like shims), and
the sandbox reads for an in-repo virtualenv are limited to the virtualenv and
its validated base installation."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from repo_ai import sandbox
from repo_ai.prove import experiment
from repo_ai.verify import execute, isolate

XY = f"{sys.version_info[0]}.{sys.version_info[1]}"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX layout")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _script(path: Path, marker: Path, then: str = f'exec {sys.executable} "$@"') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho \"$PWD\" >> {marker}\n{then}\n")
    path.chmod(0o755)


def _base(tmp_path: Path, marker: Path) -> Path:
    home = tmp_path / "base" / "bin"
    _script(home / f"python{XY}", marker)
    (tmp_path / "base" / "lib" / f"python{XY}").mkdir(parents=True)
    (tmp_path / "base" / "lib" / f"python{XY}" / "os.py").write_text("")
    return home


def _repo(tmp_path: Path, name: str = "Repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    (root / ".gitignore").write_text(".venv/\n.tools/\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "c")
    return root


def _isolate_path(monkeypatch, *front: Path) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("PYENV_VERSION", raising=False)
    monkeypatch.delenv("PYENV_ROOT", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([*map(str, front), "/usr/bin", "/bin"]))


# ---------------------------------------------------------------------------
def test_a_version_manager_shim_on_path_is_not_run_on_the_host_from_the_repository(tmp_path, monkeypatch):
    """execute._real_executable still runs a PATH shim (outside the repository)
    on the host when pyenv's files cannot decide the version (always so for
    asdf, whose installs live in installs/, not versions/). The shim inherits
    the process cwd (the repository), so a version file committed there
    decides what runs; this shim, like asdf's `path:` versions, runs the
    interpreter the repository names."""
    host_marker = tmp_path / "shim-ran-on-host"
    repo_marker = tmp_path / "repo-program-ran-on-host"
    asdf = tmp_path / "asdf"
    _script(asdf / "shims" / "python3", host_marker,
            then='if [ -x "$PWD/.tools/bin/python3" ]; then exec "$PWD/.tools/bin/python3" "$@"; fi\n'
                 f'exec {sys.executable} "$@"')
    root = _repo(tmp_path)
    (root / ".tool-versions").write_text("python path:.tools\n")
    _script(root / ".tools" / "bin" / "python3", repo_marker)
    _isolate_path(monkeypatch, asdf / "shims")
    monkeypatch.chdir(root)
    execute.interpreter(root)
    assert not repo_marker.exists(), "a program inside the repository ran on the host (via a PATH shim)"
    assert not host_marker.exists(), "a PATH shim was run on the host, with the repository as its cwd"


def test_prove_python_version_never_runs_an_in_repo_interpreter_spelled_in_another_case(tmp_path, monkeypatch):
    (tmp_path / "CaseProbe").write_text("")
    if not (tmp_path / "caseprobe").exists():
        pytest.skip("case-sensitive filesystem")
    marker = tmp_path / "ran"
    home = _base(tmp_path, tmp_path / "base-ran")
    root = _repo(tmp_path, "Repo")
    venv = root / ".venv"
    _script(venv / "bin" / "python", marker)
    (venv / "lib" / f"python{XY}" / "site-packages").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"home = {home}\nversion = {XY}.1\n")
    other = tmp_path / "REPO" / ".venv"  # the same directory, as an active VIRTUAL_ENV may spell it
    _isolate_path(monkeypatch)
    monkeypatch.setenv("VIRTUAL_ENV", str(other))
    found = execute.interpreter(root)
    assert found is not None and not marker.exists()  # execute.py itself reads it statically
    experiment.python_version(found.python, root)  # what `repo-ai prove` records as the environment
    assert not marker.exists(), f"prove ran the repository's {found.python} on the host"


def test_prove_python_version_symlinked_root_spelling(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    root = _repo(tmp_path, "r")
    link = tmp_path / "lnk"
    link.symlink_to(root)
    _script(root / ".venv" / "bin" / "python", marker)
    experiment.python_version(str(link / ".venv" / "bin" / "python"), root)
    assert not marker.exists()


# ---------------------------------------------------------------------------
def test_path_entry_inside_repository_named_shims_is_never_run(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    root = _repo(tmp_path, "r")
    _script(root / "tool" / "shims" / "python3", marker)
    _isolate_path(monkeypatch, root / "tool" / "shims")
    monkeypatch.chdir(tmp_path)
    execute.interpreter(root)
    sandbox._toolchain_dirs_cached.cache_clear()
    sandbox._toolchain_dirs_cached("python", os.environ["PATH"], "")
    assert not marker.exists()


def test_symlink_outside_that_leads_back_into_the_repository_is_not_run(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    root = _repo(tmp_path, "r")
    _script(root / ".tools" / "py", marker)
    out = tmp_path / "outbin"
    out.mkdir()
    (out / "python3").symlink_to(root / ".tools" / "py")
    _isolate_path(monkeypatch, out)
    monkeypatch.chdir(tmp_path)
    execute.interpreter(root)
    assert not marker.exists()


def test_virtual_env_through_a_linked_parent_is_not_run(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    home = _base(tmp_path, tmp_path / "base-ran")
    root = _repo(tmp_path, "r")
    venv = root / ".venv"
    _script(venv / "bin" / "python", marker)
    (venv / "lib" / f"python{XY}" / "site-packages").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"home = {home}\nversion = {XY}.1\n")
    link = tmp_path / "lnk"
    link.symlink_to(root)
    _isolate_path(monkeypatch)
    monkeypatch.setenv("VIRTUAL_ENV", str(link / ".venv"))
    execute.interpreter(root)
    assert not marker.exists()


def test_planted_venv_without_metadata_is_refused_and_not_run(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    root = _repo(tmp_path, "r")
    _script(root / ".venv" / "bin" / "python", marker)
    _isolate_path(monkeypatch)
    found = execute.interpreter(root)
    assert found is None or ".venv" not in found.python
    assert not marker.exists()


# ---------------------------------------------------------------------------
def test_static_reads_are_limited_to_the_venv_and_validated_base(tmp_path, monkeypatch):
    home = _base(tmp_path, tmp_path / "base-ran")
    secret = tmp_path / "secret"
    (secret / "bin").mkdir(parents=True)
    (secret / "bin" / "python").write_text("")
    root = _repo(tmp_path, "r")
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(secret / "bin" / "python")  # bin/python -> elsewhere
    (venv / "lib" / f"python{XY}" / "site-packages").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"home = {home}\nversion = {XY}.1\n")
    layout = isolate.static_venv(str(venv / "bin" / "python"))
    assert layout is not None
    reads = execute._static_prefixes(str(venv / "bin" / "python"), layout)
    allowed = {str(venv), str(venv.resolve()), str(tmp_path / "base"), str((tmp_path / "base").resolve())}
    assert set(reads) <= allowed | {str(home), str(home.resolve())}, reads
    assert not any(str(secret.resolve()) in r for r in reads), reads


def test_static_reads_home_pointing_elsewhere_is_not_added(tmp_path):
    marker = tmp_path / "base-ran"
    real_home = _base(tmp_path, marker)
    farm = tmp_path / "farm"  # `home` names a directory holding only a link to the base interpreter
    farm.mkdir()
    (farm / f"python{XY}").symlink_to(real_home / f"python{XY}")
    (farm / "notes.txt").write_text("private")
    root = _repo(tmp_path, "r")
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(farm / f"python{XY}")
    (venv / "lib" / f"python{XY}" / "site-packages").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"home = {farm}\nversion = {XY}.1\n")
    layout = isolate.static_venv(str(venv / "bin" / "python"))
    assert layout is not None
    reads = execute._static_prefixes(str(venv / "bin" / "python"), layout)
    assert str(farm) not in reads and str(farm.resolve()) not in reads, reads
