"""Adversarial review B: a tracked file flagged `--skip-worktree` (or
`--assume-unchanged`), the usual way to keep a local settings override out
of `git status`, is copied into the workspace with its working-tree
content, but `git diff` never reports it, so the change fingerprint ignores
it. Editing it after a passing run keeps the evidence `current` and lets
`verify --run` reuse the pass."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import CMD, needs_sandbox

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=ENV).stdout


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    files = {"calc/__init__.py": "", "calc/settings.py": "FACTOR = 1\n",
             "calc/core.py": "from calc.settings import FACTOR\n\n\ndef add(a, b):\n    return (a + b) * FACTOR\n",
             "tests/__init__.py": "",
             "tests/test_add.py": "import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@needs_sandbox
@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_an_edit_to_a_flagged_tracked_file_after_a_pass_is_not_covered(tmp_path: Path, flag: str):
    root = _project(tmp_path)
    _git(root, "update-index", flag, "calc/settings.py")      # a local override, kept out of `git status`
    (root / "calc" / "core.py").write_text(
        "from calc.settings import FACTOR\n\n\ndef add(a, b):\n    return (b + a) * FACTOR\n")
    assert run_cli(root, "verify", "--run", "--json", "--test-command", CMD).returncode == 0

    (root / "calc" / "settings.py").write_text("FACTOR = 2\n")  # breaks tests/test_add.py
    ev = json.loads(run_cli(root, "evidence", "--json").stdout)
    second = run_cli(root, "verify", "--run", "--json", "--test-command", CMD)
    fresh = run_cli(root, "verify", "--run", "--rerun", "--json", "--test-command", CMD)
    assert fresh.returncode == 1, fresh.stdout[-800:] + fresh.stderr   # the state really fails (the copy has it)
    assert not ev["current"], "evidence of the passing run is `current` for the edited state"
    assert second.returncode == 1, "verify --run reused a pass for a failing state"
