"""Adversarial review B: `cache.environment_key` is meant to change when the
installed distributions change, but `isolate.site_dirs` asks the project
interpreter with `-I -S`. For a virtualenv on CPython 3.12, `-S` skips
`site.venv()`, so `sys.prefix` is the *base* interpreter and the
directories listed are the base installation's site-packages, never the
virtualenv's. Upgrading a package in the project's virtualenv (`pip install
-U dep`) leaves the key unchanged: `verify --run` reuses a pass recorded
with the old dependency (and base outcomes cached under it stay in use),
although the tests now fail."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import pytest
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import CMD, needs_sandbox

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=ENV).stdout


def _install(site: Path, version: str, body: str) -> None:
    """What `pip install depcalc==<version>` leaves in the virtualenv."""
    for old in site.glob("depcalc-*.dist-info"):
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
    (site / "depcalc.py").write_text(body)
    info = site / f"depcalc-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: depcalc\nVersion: {version}\n")
    (info / "RECORD").write_text("depcalc.py,,\n")


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    files = {"calc/__init__.py": "",
             "calc/core.py": "from depcalc import plus\n\n\ndef add(a, b):\n    return plus(a, b)\n",
             "tests/__init__.py": "",
             "tests/test_add.py": "import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "venv")], check=True)
    site = Path(subprocess.run([str(tmp_path / "venv" / "bin" / "python"), "-I", "-c",  # with `site`: the venv's
                                "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
                               capture_output=True, text=True, check=True).stdout.strip())
    assert (tmp_path / "venv") in site.parents
    _install(site, "1.0", "def plus(a, b):\n    return a + b\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root, site


@needs_sandbox
def test_upgrading_a_package_in_the_project_virtualenv_invalidates_reuse(tmp_path: Path):
    root, site = _project(tmp_path)
    env = {"VIRTUAL_ENV": str(tmp_path / "venv")}  # the project's virtualenv
    (root / "calc" / "core.py").write_text("from depcalc import plus\n\n\ndef add(a, b):\n    return plus(b, a)\n")
    first = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env=env)
    assert first.returncode == 0, first.stdout[-1500:] + first.stderr

    _install(site, "2.0", "def plus(a, b):\n    return a - b\n")  # `pip install -U depcalc`: new version
    second = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env=env)
    fresh = run_cli(root, "verify", "--run", "--rerun", "--json", "--test-command", CMD, env=env)
    assert fresh.returncode == 1, fresh.stdout[-800:]                 # the tests now fail
    out = json.loads(second.stdout)
    assert second.returncode == 1, f"verify --run reported {out['summary']['verdict']!r} " \
                                   f"(reused: {bool(out['evidence'].get('reused'))}) for a failing environment"


@pytest.mark.skipif(sys.platform == "win32", reason="a Windows virtualenv has Scripts/python.exe, and Windows has no "
                    "host sandbox whose site-packages this key describes")
def test_the_site_dirs_of_a_virtualenv_are_the_virtualenvs_own(tmp_path: Path):
    from repo_ai.verify import isolate
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "venv")], check=True)
    dirs = isolate.site_dirs(str(tmp_path / "venv" / "bin" / "python"))
    assert any(Path(d).resolve().is_relative_to((tmp_path / "venv").resolve()) for d in dirs), dirs
