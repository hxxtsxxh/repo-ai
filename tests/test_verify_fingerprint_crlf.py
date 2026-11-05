"""Adversarial review B: `changes.content_id` (the exact fingerprint) maps
CRLF to LF, so two working trees whose bytes differ only in line endings
share a fingerprint, although the workspace copy keeps the bytes the tests
read. Converting a changed fixture to CRLF after a passing run (an editor
on Windows settings, `unix2dos`) keeps the evidence `current` and lets
`verify --run` reuse the pass, while the tests now fail."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import CMD, needs_sandbox

from repo_ai.verify import changes

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=ENV).stdout


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
             "tests/__init__.py": "", "tests/golden.txt": "3\n",
             "tests/test_golden.py": (
                 "import unittest\nfrom pathlib import Path\nfrom calc.core import add\n\n\n"
                 "class T(unittest.TestCase):\n    def test_golden(self):\n"
                 "        golden = (Path(__file__).parent / 'golden.txt').read_bytes()\n"
                 "        self.assertEqual(golden, f'{add(1, 2)}\\n'.encode())\n")}
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


def test_states_whose_bytes_differ_only_in_line_endings_do_not_share_a_fingerprint(tmp_path: Path):
    root = _project(tmp_path)
    (root / "tests" / "golden.txt").write_bytes(b"3\n\n")
    lf = changes.detect(root).fingerprint
    (root / "tests" / "golden.txt").write_bytes(b"3\r\n\r\n")
    assert changes.detect(root).fingerprint != lf


@needs_sandbox
def test_a_crlf_conversion_after_a_pass_is_not_covered_by_its_evidence(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 1\n")  # a behaviour change...
    (root / "tests" / "golden.txt").write_bytes(b"4\n")                       # ...with its golden file
    assert run_cli(root, "verify", "--run", "--json", "--test-command", CMD).returncode == 0

    (root / "tests" / "golden.txt").write_bytes(b"4\r\n")                    # an editor saves it with CRLF
    ev = json.loads(run_cli(root, "evidence", "--json").stdout)
    second = run_cli(root, "verify", "--run", "--json", "--test-command", CMD)
    fresh = run_cli(root, "verify", "--run", "--rerun", "--json", "--test-command", CMD)
    assert fresh.returncode == 1, fresh.stdout[-800:]                         # the copy has CRLF: it fails
    assert not ev["current"], "evidence of the LF run is `current` for the CRLF state"
    assert second.returncode == 1, "verify --run reused a pass for a failing state"
