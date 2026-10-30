"""Adversarial review A: a change that marks its now-failing tests as expected failures passes.

T20: a file whose tests all skip with the change is run at the base, and if they ran there the
verdict is "not verified". Marking the broken tests `@unittest.expectedFailure` (or pytest
`xfail`, `pytestmark = pytest.mark.xfail`) is the same move with the same effect: no test of the
file verifies anything. `rai_result` reports an expected failure as "pass"
(`wrap("addExpectedFailure", "pass")`; pytest: `wasxfail` -> "pass"), so the file passes and
`_check_skips` never looks at it. Control: the same change with `@unittest.skip` is not verified."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import needs_sandbox

CMD = "python -m unittest discover -s tests -t ."
BASE = {
    "calc/__init__.py": "",
    "calc/core.py": "def add(a, b):\n    return a + b\n",
    "tests/__init__.py": "",
    "tests/test_a.py": ("import unittest\nfrom calc.core import add\n\n\nclass A(unittest.TestCase):\n"
                        "    def test_add(self):\n        self.assertEqual(add(1, 1), 2)\n"),
}
PASSING = {"selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _verify(tmp_path: Path, decorator: str) -> dict:
    root = tmp_path / decorator.strip("@").replace(".", "_")
    for rel, text in BASE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 1\n")
    (root / "tests" / "test_a.py").write_text(BASE["tests/test_a.py"].replace(
        "    def test_add", f"    {decorator}\n    def test_add"))
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", CMD)
    return json.loads(proc.stdout)["evidence"]


@needs_sandbox
def test_control_a_change_that_skips_its_broken_test_is_not_verified(tmp_path: Path):
    ev = _verify(tmp_path, "@unittest.skip('later')")
    assert ev["verdict"] not in PASSING, ev["verdict"]


@needs_sandbox
def test_a_change_that_marks_its_broken_test_an_expected_failure_is_not_a_pass(tmp_path: Path):
    ev = _verify(tmp_path, "@unittest.expectedFailure")
    assert ev["verdict"] not in PASSING, (ev["verdict"], [(r["test"], r["status"]) for r in ev["results"]])
