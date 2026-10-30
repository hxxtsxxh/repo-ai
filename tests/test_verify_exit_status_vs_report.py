"""Adversarial review A: a test process that exits 0 is trusted over its own per-test report.

The change breaks `add` (test_a fails: AssertionError 3 != 2) and makes `finish()` end the
process with status 0 (`os._exit(0)`, as a daemonising helper whose parent/child branches are
swapped would). In one process (the full suite, which the engine picks on its own once times are
measured, or a batch), test_a's failure is in the per-test report, but the process exits 0 and the
engine reports the whole run as passing without reading the report (`_run_full`, `_run_batch`,
`_run_file` treat exit 0 as a pass outright)."""

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
    "calc/core.py": "import os\n\n\ndef add(a, b):\n    return a + b\n\n\ndef finish():\n    return 0\n",
    "tests/__init__.py": "",
    "tests/test_a.py": ("import unittest\nfrom calc.core import add\n\n\nclass A(unittest.TestCase):\n"
                        "    def test_add(self):\n        self.assertEqual(add(1, 1), 2)\n"),
    "tests/test_b.py": ("import unittest\nfrom calc.core import finish\n\n\nclass B(unittest.TestCase):\n"
                        "    def test_finish(self):\n        self.assertEqual(finish(), 0)\n"),
}
CHANGED = "import os\n\n\ndef add(a, b):\n    return a + b + 1\n\n\ndef finish():\n    os._exit(0)\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _project(tmp_path: Path, record: bool) -> Path:
    root = tmp_path / "p"
    for rel, text in BASE.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    if record:
        assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    (root / "calc" / "core.py").write_text(CHANGED)
    return root


def _verify(root: Path, *extra: str) -> dict:
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", CMD, *extra)
    return json.loads(proc.stdout)["evidence"]


PASSING = {"selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected"}


@needs_sandbox
def test_a_failure_in_the_full_suite_is_not_hidden_by_a_later_exit_status_0(tmp_path: Path):
    ev = _verify(_project(tmp_path, record=False), "--full")
    status = {r["test"]: r["status"] for r in ev["results"]}
    assert ev["verdict"] not in PASSING, (ev["verdict"], status, ev.get("full_suite"))
    assert status.get("tests/test_a.py") == "fail", status


@needs_sandbox
def test_the_engine_chosen_full_suite_does_not_pass_a_failing_change(tmp_path: Path):
    """No flag: after `--record` the engine picks the full suite on its own (it is faster)."""
    ev = _verify(_project(tmp_path, record=True))
    status = {r["test"]: r["status"] for r in ev["results"]}
    assert ev["verdict"] not in PASSING, (ev["verdict"], status, ev.get("strategy"))
