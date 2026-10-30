"""F2b (T24 residual): an interpreter inside the repository is never executed
on the host, even when git ignores it. A `.venv/bin/python` planted by a
patch or an archive is indistinguishable from the developer's own
virtualenv, so its prefixes and site-packages are read from `pyvenv.cfg` and
the directory layout instead of asked from the interpreter; a virtualenv
whose metadata is missing or inconsistent is refused, never run."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import CMD, _git, needs_sandbox

from repo_ai.verify import execute, isolate

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX virtualenv layout (bin/python)")
XY = f"{sys.version_info[0]}.{sys.version_info[1]}"


def _script(path: Path, marker: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch {marker}\nexec {sys.executable} \"$@\"\n")
    path.chmod(0o755)


def _repo(tmp_path: Path, cfg: str | None = "default", lib: str = f"python{XY}") -> tuple[Path, Path, Path]:
    """A repository with an untracked, git-ignored `.venv` whose interpreter
    (and its base interpreter) touch a marker when executed."""
    root = tmp_path / "r"
    marker = tmp_path / "executed-on-the-host"
    home = tmp_path / "base" / "bin"
    _script(home / f"python{XY}", marker)
    (tmp_path / "base" / "lib" / f"python{XY}").mkdir(parents=True)
    (tmp_path / "base" / "lib" / f"python{XY}" / "os.py").write_text("")  # its standard library
    venv = root / ".venv"
    _script(venv / "bin" / "python", marker)
    (venv / "lib" / lib / "site-packages").mkdir(parents=True)
    if cfg == "default":
        cfg = f"home = {home}\ninclude-system-site-packages = false\nversion = {XY}.1\n"
    if cfg is not None:
        (venv / "pyvenv.cfg").write_text(cfg)
    (root / ".gitignore").write_text(".venv/\n")
    (root / "a.py").write_text("x = 1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root, venv, marker


def test_an_ignored_repository_virtualenv_is_chosen_but_never_executed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, venv, marker = _repo(tmp_path)
    python, reads = execute.project_python(root)
    assert python == str(venv / "bin" / "python")  # the developer's virtualenv
    assert not marker.exists(), "an interpreter inside the repository was executed on the host"
    assert str(venv) in reads and str((tmp_path / "base").resolve()) in reads, reads
    found = execute.interpreter(root)
    assert found is not None and found.site_dirs == [str(venv / "lib" / f"python{XY}" / "site-packages")]
    assert not marker.exists()


def test_an_active_virtualenv_inside_the_repository_is_read_statically(tmp_path: Path, monkeypatch):
    root, venv, marker = _repo(tmp_path)
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    found = execute.interpreter(root)
    assert found is not None and found.python == str(venv / "bin" / "python")
    assert not marker.exists()


def test_system_site_packages_come_from_the_base_installation(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, venv, marker = _repo(tmp_path, cfg=None)
    home = tmp_path / "base" / "bin"
    (venv / "pyvenv.cfg").write_text(f"home = {home}\ninclude-system-site-packages = true\nversion_info = {XY}.1.final.0\n")
    base_site = tmp_path / "base" / "lib" / f"python{XY}" / "site-packages"
    base_site.mkdir(parents=True)
    found = execute.interpreter(root)
    assert found is not None and str(base_site) in found.site_dirs, found
    assert not marker.exists()


@pytest.mark.parametrize("cfg,lib", [
    (None, f"python{XY}"),                                                # no pyvenv.cfg at all
    ("include-system-site-packages = false\nversion = 3.12.1\n", f"python{XY}"),  # no home
    ("home = {home}\nversion = 3.99.0\n", f"python{XY}"),                 # the version disagrees with the layout
    ("home = {home}\n", f"python{XY}"),                                   # no version
    ("home = {home}\nversion = {xy}.1\n", "python2.7"),                   # no site-packages for that version
    ("home = /nonexistent/bin\nversion = {xy}.1\n", f"python{XY}"),       # no base interpreter
])
def test_a_virtualenv_with_missing_or_inconsistent_metadata_is_refused_without_execution(
        tmp_path: Path, monkeypatch, cfg, lib):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    home = tmp_path / "base" / "bin"
    root, venv, marker = _repo(tmp_path, cfg=None if cfg is None else cfg.format(home=home, xy=XY), lib=lib)
    python, _reads = execute.project_python(root)
    assert not marker.exists(), "a virtualenv with unusable metadata was executed on the host"
    assert python != str(venv / "bin" / "python")  # the next candidate (python3 on PATH)


def test_a_home_without_a_standard_library_is_refused(tmp_path: Path, monkeypatch):
    """`home` is the repository's word: a directory that merely holds a
    `python3.X` file (`~/.local/bin`) must not make its parent readable."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, venv, marker = _repo(tmp_path, cfg=None)
    bare = tmp_path / "bare" / "bin"
    _script(bare / f"python{XY}", marker)
    (venv / "pyvenv.cfg").write_text(f"home = {bare}\nversion = {XY}.1\n")
    python, reads = execute.project_python(root)
    assert not marker.exists() and python != str(venv / "bin" / "python")
    assert str(tmp_path / "bare") not in reads


def test_a_pyvenv_cfg_that_is_not_a_regular_file_is_refused(tmp_path: Path, monkeypatch):
    import os
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, venv, marker = _repo(tmp_path, cfg=None)
    os.mkfifo(venv / "pyvenv.cfg")  # reading it would block
    python, _reads = execute.project_python(root)
    assert not marker.exists() and python != str(venv / "bin" / "python")


def test_an_outside_interpreter_that_resolves_into_the_repository_is_not_executed(tmp_path: Path, monkeypatch):
    root, _venv, marker = _repo(tmp_path)
    planted = root / "tools" / "python"
    _script(planted, marker)
    outside = tmp_path / "elsewhere" / "bin"
    outside.mkdir(parents=True)
    (outside / "python").symlink_to(planted)
    monkeypatch.setenv("VIRTUAL_ENV", str(outside.parent))  # no pyvenv.cfg there: refused
    found = execute.interpreter(root)
    assert not marker.exists()
    assert found is None or Path(found.python).resolve() != planted.resolve()


def test_the_static_layout_matches_the_probe_for_a_real_virtualenv(tmp_path: Path):
    """The same answer `-I -S` gives, for a virtualenv outside any repository."""
    import subprocess
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "venv")], check=True)
    py = str(tmp_path / "venv" / "bin" / "python")
    layout = isolate.static_venv(py)
    assert layout is not None
    assert [str(Path(d).resolve()) for d in layout.site_dirs] == [str(Path(d).resolve()) for d in isolate.site_dirs(py)]
    assert set(execute._prefixes(py)) <= set(execute._static_prefixes(py, layout))


@needs_sandbox
def test_a_statically_read_repository_virtualenv_runs_the_tests_in_the_sandbox(tmp_path: Path):
    """The tests import a package installed only in the project's own,
    git-ignored `.venv` (a real one): the static layout is enough to run them."""
    import json
    import subprocess
    root = tmp_path / "proj"
    for rel, text in {".gitignore": ".venv/\n", "calc/__init__.py": "",
                      "calc/core.py": "from depcalc import plus\n\n\ndef add(a, b):\n    return plus(a, b)\n",
                      "tests/__init__.py": "",
                      "tests/test_add.py": "import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                                           "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True)
    layout = isolate.static_venv(str(root / ".venv" / "bin" / "python"))
    assert layout is not None
    Path(layout.site_dirs[0], "depcalc.py").write_text("def plus(a, b):\n    return a + b\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("from depcalc import plus\n\n\ndef add(a, b):\n    return plus(b, a)\n")
    out = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env={"VIRTUAL_ENV": ""})
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr
    assert json.loads(out.stdout)["evidence"]["interpreter"] == str(root / ".venv" / "bin" / "python")


def test_where_the_interpreter_links_to_never_widens_what_the_sandbox_reads(tmp_path: Path, monkeypatch):
    """The F2b review: `bin/python` is the repository's file, so where it links to (here a directory with
    nothing to do with the base installation) must not become readable in the sandbox."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    root, venv, marker = _repo(tmp_path)
    elsewhere = tmp_path / "private" / "bin"
    _script(elsewhere / "python", marker)
    (venv / "bin" / "python").unlink()
    (venv / "bin" / "python").symlink_to(elsewhere / "python")
    layout = isolate.static_venv(str(venv / "bin" / "python"))
    assert layout is not None
    reads = execute._static_prefixes(str(venv / "bin" / "python"), layout)
    assert not any(Path(d).resolve() == (tmp_path / "private").resolve() for d in reads), reads
    assert str((tmp_path / "base").resolve()) in {str(Path(d).resolve()) for d in reads}
    assert not marker.exists()
