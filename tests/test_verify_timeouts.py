"""Time-outs cost their limit once (held-out-5: two hang mutations cost 91 s
and 111 s, almost half of that set's wall time, because the hung file was run
again after the full suite timed out, and container runs waited 15 s more).
End to end in the sandbox, on a fixture project."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from conftest import run_cli

from test_verify_adaptive import _sandbox

pytestmark = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")
CMD = "python -m unittest discover -s tests -t ."


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    files = {"calc/__init__.py": "", "calc/core.py": "def wait():\n    return 1\n\n\ndef add(a, b):\n    return a + b\n",
             "tests/__init__.py": "",
             "tests/test_a_add.py": ("import unittest\nfrom calc.core import add\n\n\nclass A(unittest.TestCase):\n"
                                     "    def test_add(self):\n        self.assertEqual(add(1, 1), 2)\n"),
             "tests/test_b_wait.py": ("import unittest\nfrom calc.core import wait\n\n\nclass W(unittest.TestCase):\n"
                                      "    def test_wait(self):\n        self.assertEqual(wait(), 1)\n"),
             "tests/test_c_more.py": ("import unittest\nfrom calc.core import add\n\n\nclass C(unittest.TestCase):\n"
                                      "    def test_more(self):\n        self.assertEqual(add(2, 2), 4)\n")}
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


def test_a_full_suite_timeout_is_attributed_without_running_the_hung_file_again(proj: Path):
    (proj / "calc" / "core.py").write_text("import time\n\n\ndef wait():\n    time.sleep(1000)\n\n\n"
                                           "def add(a, b):\n    return a + b\n")
    t = time.monotonic()
    proc = run_cli(proj, "verify", "--run", "--json", "--full", "--timeout", "6", "--test-command", CMD)
    took = time.monotonic() - t
    ev = json.loads(proc.stdout)["evidence"]
    rows = {r["test"]: r for r in ev["results"]}
    assert rows["tests/test_b_wait.py"]["status"] == "timeout", rows
    assert ev["full_suite"].get("timed_out_in") == ["tests/test_b_wait.py"]
    assert ev["verdict"] == "regression", ev["verdict"]
    runs_of_hung = ev["processes"].get("file", 0) + ev["processes"].get("batch", 0) + ev["processes"].get("rerun", 0)
    assert runs_of_hung <= 1  # only files that never started may run again, never the hung one
    assert took < 6 * 3 + 15, took  # the full suite's limit, a base check, overhead: not the limit twice


def test_a_timeout_does_not_disable_the_full_suite_for_later_runs(proj: Path):
    (proj / "calc" / "core.py").write_text("import time\n\n\ndef wait():\n    time.sleep(1000)\n\n\n"
                                           "def add(a, b):\n    return a + b\n")
    run_cli(proj, "verify", "--run", "--json", "--full", "--timeout", "6", "--test-command", CMD)
    timings = json.loads((proj / ".repo-ai" / "state" / "verify-timings.json").read_text())
    blob = json.dumps(timings)
    assert "full_unusable" not in blob or '"full_unusable": null' in blob or '"full_unusable": ""' in blob, blob[:400]
