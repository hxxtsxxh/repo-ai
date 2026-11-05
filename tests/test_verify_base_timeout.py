"""Adversarial review A: a base run that times out makes a new failure look pre-existing.

The change makes a test fail fast that takes 8 s (and passes) at the base. With `--timeout 5`
the base re-run of that test hits the limit: it never reported the test failing, yet
`_file_outcome` turns any untrusted base process (a time-out included) into "fail", so the new
failure is classified "already failing at the base (individual tests not compared)" and the
verdict is "failing (all failures pre-existing at the base)". The base was never observed to
fail; it could not be compared (`_base_full` and `_check_skips` already treat a base time-out as
"could not tell")."""

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
    "tests/test_a.py": ("import time\nimport unittest\nfrom calc.core import add\n\n\nclass A(unittest.TestCase):\n"
                        "    def test_add(self):\n        r = add(1, 1)\n        if r == 2:\n"
                        "            time.sleep(8)  # the slow, passing path at the base\n"
                        "        self.assertEqual(r, 2)\n"),
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@needs_sandbox
def test_a_base_run_cut_by_the_limit_is_not_a_base_failure(tmp_path: Path):
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
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 1\n")
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--timeout", "5", "--test-command", CMD)
    ev = json.loads(proc.stdout)["evidence"]
    row = {r["test"]: r for r in ev["results"]}["tests/test_a.py"]
    assert row["status"] == "fail"
    assert row.get("baseline") != "fail", (row.get("classification"), ev["verdict"])
    assert ev["verdict"] != "failing (all failures pre-existing at the base)", ev["verdict"]
