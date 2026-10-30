"""A renamed (moved) source module is a behavioural change even when its
content is unchanged: every import of the old path breaks. Before this fix a
staged `git mv` of a Python or JavaScript module selected nothing, so `verify
--run` reported `nothing-selected` (a passing verdict) and the completion gate
stayed silent for a change that breaks the tests (found by the held-out-6
scenario U5 on development projects)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import CMD, NODE_SANDBOX, _git, _write, needs_sandbox

PASSING = ("selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected")


def _commit_init(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def _py(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    _write(root, {
        "calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
        "calc/other.py": "def neg(a):\n    return -a\n", "tests/__init__.py": "",
        "tests/test_core.py": ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                               "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"),
        "tests/test_other.py": ("import unittest\nfrom calc.other import neg\n\n\nclass T(unittest.TestCase):\n"
                                "    def test_neg(self):\n        self.assertEqual(neg(1), -1)\n"),
    })
    _commit_init(root)
    return root


def _mv(root: Path, old: str, new: str) -> None:
    subprocess.run(["git", "mv", old, new], cwd=root, check=True, capture_output=True)


def test_a_renamed_python_module_is_behavioural_and_selects_its_importers(tmp_path: Path):
    root = _py(tmp_path)
    _mv(root, "calc/core.py", "calc/core_moved.py")
    plan = json.loads(run_cli(root, "verify", "--json", "--test-command", CMD).stdout)
    assert "tests/test_core.py" in [s["test"] for s in plan["selected"]], plan
    moved = next(f for f in plan["changed_files"] if f["path"] == "calc/core_moved.py")
    assert moved["behavioral"] is True, moved


@needs_sandbox
def test_a_staged_rename_that_breaks_imports_is_not_a_pass(tmp_path: Path):
    root = _py(tmp_path)
    assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    _mv(root, "calc/core.py", "calc/core_moved.py")
    out = json.loads(run_cli(root, "verify", "--run", "--json", "--test-command", CMD).stdout)
    verdict = out["evidence"]["verdict"]
    assert not verdict.startswith(PASSING) and verdict == "regression", verdict
    assert "tests/test_core.py" in [f["test_file"] for f in out["summary"]["new_failures"]], out["summary"]
    gate = run_cli(root, "verify", "--gate", stdin=json.dumps({"session_id": "s"}))
    assert '"block"' in gate.stdout, gate.stdout


@pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")
def test_a_staged_rename_of_a_javascript_module_is_not_a_pass(tmp_path: Path):
    root = tmp_path / "p"
    _write(root, {
        "src/add.js": "exports.add = (a, b) => a + b;\n", "src/neg.js": "exports.neg = (a) => -a;\n",
        "test/add.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                             "const { add } = require('../src/add');\ntest('add', () => assert.equal(add(1, 2), 3));\n"),
        "test/neg.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                             "const { neg } = require('../src/neg');\ntest('neg', () => assert.equal(neg(1), -1));\n"),
    })
    _commit_init(root)
    assert run_cli(root, "verify", "--record", "--test-command", "node --test").returncode == 0
    _mv(root, "src/add.js", "src/add_moved.js")
    out = json.loads(run_cli(root, "verify", "--run", "--json", "--test-command", "node --test").stdout)
    verdict = out["evidence"]["verdict"]
    assert verdict == "regression", (verdict, out["plan"]["selected"])
