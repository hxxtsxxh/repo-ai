"""Nothing selected is a pass only when the change cannot alter behaviour.

A behavioural code change that no test runs verified nothing: before this
fix, `verify --run` reported `nothing-selected`, a passing verdict (exit 0,
`evidence` "current", the completion gate silent) for an edit to code that
no test reaches, and for a change that requires the full suite when the full
suite could not be run. Every selection blind spot (a rename, D9; TypeScript
discovery, D10) ended in that same pass."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import CMD, _git, _write, needs_sandbox

from repo_ai.verify import evidence

PASSING = evidence.PASSING_VERDICTS


def test_nothing_selected_is_a_pass_only_for_a_change_without_behaviour():
    assert evidence.verdict([], None, 0, False, behavioural=False) == "nothing-selected"
    v = evidence.verdict([], None, 0, False, behavioural=True)
    assert v == evidence.NOT_VERIFIED_UNLINKED and not evidence.is_passing(v)
    for behavioural in (True, False):
        v = evidence.verdict([], {"status": "not-run"}, 0, True, behavioural=behavioural)
        assert v == evidence.NOT_VERIFIED_FULL_NOT_RUN and not evidence.is_passing(v)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    _write(root, {
        "calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
        "calc/unused.py": "def scale(a):\n    return a * 2\n", "tests/__init__.py": "", "README.md": "calc\n",
        "tests/test_core.py": ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                               "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"),
    })
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


@needs_sandbox
def test_a_behavioural_change_no_test_reaches_is_not_verified(tmp_path: Path):
    root = _project(tmp_path)
    assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    (root / "calc" / "unused.py").write_text("def scale(a):\n    return a * 3\n")
    out = run_cli(root, "verify", "--run", "--json", "--test-command", CMD)
    data = json.loads(out.stdout)
    assert data["evidence"]["verdict"] == evidence.NOT_VERIFIED_UNLINKED, data["evidence"]["verdict"]
    assert out.returncode == 1
    ev = json.loads(run_cli(root, "evidence", "--json").stdout)
    assert ev["current"] and not str(ev["evidence"]["verdict"]).startswith(PASSING)
    gate = run_cli(root, "verify", "--gate", stdin=json.dumps({"session_id": "s"}))
    assert '"block"' in gate.stdout, gate.stdout


@needs_sandbox
def test_a_documentation_only_change_is_still_nothing_to_run(tmp_path: Path):
    root = _project(tmp_path)
    (root / "README.md").write_text("calc, a calculator\n")
    out = run_cli(root, "verify", "--run", "--json", "--test-command", CMD)
    assert json.loads(out.stdout)["evidence"]["verdict"] == "nothing-selected" and out.returncode == 0


@needs_sandbox
def test_a_comment_only_python_change_is_still_nothing_to_run(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "unused.py").write_text("def scale(a):\n    # doubles\n    return a * 2\n")
    out = run_cli(root, "verify", "--run", "--json", "--test-command", CMD)
    assert json.loads(out.stdout)["evidence"]["verdict"] == "nothing-selected" and out.returncode == 0
