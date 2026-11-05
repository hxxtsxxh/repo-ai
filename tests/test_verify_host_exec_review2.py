# Vendored from the defensive re-check of the corrective integration (2026-10-25): repo-ai never runs on the host a
# program or module the repository chose (a version-manager shim, a repository module shadowing the standard library).
"""e2f6abf / 358674b and the grep: no host subprocess runs a program located inside
the repository or chosen by a repository file."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import repo_ai

from repo_ai import hooks, sandbox
from repo_ai.prove import experiment
from repo_ai.verify import execute

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX layout")
SRC = str(Path(repo_ai.__file__).resolve().parents[1])


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _script(path: Path, marker: Path, then: str = "echo v0.0.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho \"$PWD\" >> {marker}\n{then}\n")
    path.chmod(0o755)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "Repo"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n")
    (root / ".gitignore").write_text(".venv/\n.tools/\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "c")
    return root


def _isolate_path(monkeypatch, *front: Path) -> None:
    for k in ("VIRTUAL_ENV", "PYENV_VERSION", "PYENV_ROOT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([*map(str, front), "/usr/bin", "/bin"]))


def test_prove_environment_never_runs_a_node_version_manager_shim(tmp_path, monkeypatch):
    """asdf's node shim obeys the repository's `.tool-versions` (which may say `nodejs path:<dir in repo>`):
    the Python fix in e2f6abf skips such a shim; prove's node branch runs `node --version` on the host."""
    root = _repo(tmp_path)
    marker = tmp_path / "ran"
    shim = tmp_path / "asdf" / "shims" / "node"
    _script(shim, marker)
    (root / ".tool-versions").write_text(f"nodejs path:{root / '.tools' / 'node'}\n")
    monkeypatch.chdir(root)
    executor = SimpleNamespace(backend=SimpleNamespace(name="seatbelt"), is_container=False, node=str(shim),
                               python=sys.executable)
    runner = SimpleNamespace(language="node")
    env = experiment.environment(executor, runner, root)
    assert not marker.exists(), f"the node shim ran on the host ({env.get('node')!r}) from {marker.read_text()!r}"


def test_toolchain_dirs_never_run_a_node_shim(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    shims = tmp_path / "asdf" / "shims"
    for t in ("node", "npm"):
        _script(shims / t, marker)
    _isolate_path(monkeypatch, shims)
    sandbox._toolchain_dirs_cached.cache_clear()
    sandbox._toolchain_dirs("node")
    sandbox._toolchain_dirs_cached.cache_clear()
    assert not marker.exists()


def test_pyenv_version_linked_into_the_repository_is_not_run(tmp_path, monkeypatch):
    """`.python-version` picks a pyenv version whose directory links into the repository."""
    root = _repo(tmp_path)
    marker = tmp_path / "ran"
    pyroot = tmp_path / "pyenv"
    _script(pyroot / "shims" / "python3", marker)
    inrepo = root / ".tools" / "py"
    _script(inrepo / "bin" / "python3", marker, then=f'exec {sys.executable} "$@"')
    (pyroot / "versions").mkdir(parents=True)
    (pyroot / "versions" / "evil").symlink_to(inrepo)
    (root / ".python-version").write_text("evil\n")
    _isolate_path(monkeypatch, pyroot / "shims")
    monkeypatch.setenv("PYENV_ROOT", str(pyroot))
    monkeypatch.chdir(root)
    execute.interpreter(root)
    assert not marker.exists(), marker.read_text()


def test_pyenv_version_with_traversal_is_not_run(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    marker = tmp_path / "ran"
    pyroot = tmp_path / "pyenv"
    _script(pyroot / "shims" / "python3", marker)
    _script(root / ".tools" / "bin" / "python3", marker, then=f'exec {sys.executable} "$@"')
    (pyroot / "versions").mkdir(parents=True)
    for v in ("../../Repo/.tools", "/abs", "system"):
        (root / ".python-version").write_text(v + "\n")
        _isolate_path(monkeypatch, pyroot / "shims")
        monkeypatch.setenv("PYENV_ROOT", str(pyroot))
        monkeypatch.chdir(root)
        execute.interpreter(root)
        assert not marker.exists(), (v, marker.read_text())


def test_background_refresh_never_imports_repository_modules(tmp_path, monkeypatch):
    """`python -m repo_ai refresh` started with cwd=root puts the repository first on sys.path:
    a repository `json.py` (or any module repo-ai imports) runs on the host, unsandboxed."""
    root = _repo(tmp_path)
    marker = tmp_path / "shadowed"
    for mod in ("json", "argparse", "sqlite3", "tomllib", "dataclasses", "subprocess", "shlex"):
        (root / f"{mod}.py").write_text(f"open({str(marker)!r}, 'a').write({mod!r} + '\\n')\n"
                                        f"raise SystemExit(0)\n")
    monkeypatch.delenv("REPO_AI_NO_BACKGROUND", raising=False)
    monkeypatch.setenv("PYTHONPATH", SRC)
    monkeypatch.chdir(tmp_path)
    started = hooks.spawn_refresh(root, force=True)
    assert started
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.2)
    assert not marker.exists(), "repository module(s) ran on the host: " + marker.read_text()
