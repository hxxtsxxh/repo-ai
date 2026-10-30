"""`verify --paths`: a read-only plan for part of a change (a per-edit
preview for agent hooks, proposal P3). It is never evidence and never runs
anything."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    files = {"calc/__init__.py": "", "calc/a.py": "def f():\n    return 1\n", "calc/b.py": "def g():\n    return 2\n",
             "tests/__init__.py": "",
             "tests/test_a.py": "import unittest\nfrom calc.a import f\n\n\nclass A(unittest.TestCase):\n"
                                "    def test_f(self):\n        self.assertEqual(f(), 1)\n",
             "tests/test_b.py": "import unittest\nfrom calc.b import g\n\n\nclass B(unittest.TestCase):\n"
                                "    def test_g(self):\n        self.assertEqual(g(), 2)\n"}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "a.py").write_text("def f():\n    return 1 + 0\n")
    (root / "calc" / "b.py").write_text("def g():\n    return 2 + 0\n")
    return root


CMD = "python -m unittest discover -s tests -t ."


def _plan(repo: Path, *extra: str) -> dict:
    proc = run_cli(repo, "verify", "--json", "--test-command", CMD, *extra)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_a_path_scoped_plan_covers_only_that_file_and_says_it_is_partial(repo: Path):
    whole = _plan(repo)
    a = _plan(repo, "--paths", "calc/a.py")
    b = _plan(repo, "--paths", str(repo / "calc" / "b.py"))  # absolute paths inside the repository work too
    assert [f["path"] for f in a["changed_files"]] == ["calc/a.py"]
    assert a["scope"] == {"paths": ["calc/a.py"], "partial": True} and "evidence_status" not in a
    assert a["fingerprint"] != whole["fingerprint"]  # never mistaken for the whole change
    union = {s["test"] for s in a["selected"]} | {s["test"] for s in b["selected"]}
    assert union == {s["test"] for s in whole["selected"]} == {"tests/test_a.py", "tests/test_b.py"}


def test_paths_never_runs_or_records(repo: Path):
    for flag in ("--run", "--record"):
        proc = run_cli(repo, "verify", "--json", "--test-command", CMD, "--paths", "calc/a.py", flag)
        assert proc.returncode != 0 and "read-only" in (proc.stderr + proc.stdout)
    assert not (repo / ".repo-ai" / "state" / "evidence").exists()


def test_paths_outside_the_repository_are_refused(repo: Path, tmp_path: Path):
    proc = run_cli(repo, "verify", "--json", "--test-command", CMD, "--paths", str(tmp_path / "elsewhere.py"))
    assert proc.returncode != 0 and "outside the repository" in proc.stderr


def test_an_unchanged_path_gives_an_empty_plan(repo: Path):
    plan = _plan(repo, "--paths", "README.md,tests/test_a.py")
    assert plan["changed_files"] == [] and plan["selected"] == []
