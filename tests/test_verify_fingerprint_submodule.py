"""Adversarial review B: the change fingerprint ignores the content of a
submodule, although the workspace copy includes it (`ls-files
--recurse-submodules`). A second edit inside a submodule therefore keeps
the fingerprint, so passing evidence stays `current` and `verify --run`
reuses it for a state whose tests fail."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import CMD, needs_sandbox

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "protocol.file.allow=always", *args], cwd=repo, check=True,
                          capture_output=True, text=True, env=ENV).stdout


def _project(tmp_path: Path) -> Path:
    lib = tmp_path / "lib"
    (lib / "calc").mkdir(parents=True)
    (lib / "calc" / "__init__.py").write_text("")
    (lib / "calc" / "core.py").write_text("def add(a, b):\n    return a + b\n")
    _git(lib, "init", "-q", "-b", "main")
    _git(lib, "add", "-A")
    _git(lib, "commit", "-qm", "lib")
    app = tmp_path / "app"
    app.mkdir()
    _git(app, "init", "-q", "-b", "main")
    _git(app, "submodule", "add", "-q", str(lib), "vendor")
    (app / "tests").mkdir()
    (app / "tests" / "__init__.py").write_text("")
    (app / "tests" / "test_add.py").write_text(
        "import sys, unittest\nsys.path.insert(0, 'vendor')\nfrom calc.core import add\n\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")
    _git(app, "add", "-A")
    _git(app, "commit", "-qm", "base")
    assert run_cli(app, "init", "--agent", "none", "-q").returncode == 0
    _git(app, "add", "-A")
    _git(app, "commit", "-qm", "init")
    return app


@needs_sandbox
def test_a_second_edit_inside_a_submodule_is_not_covered_by_the_first_runs_evidence(tmp_path: Path):
    app = _project(tmp_path)
    core = app / "vendor" / "calc" / "core.py"
    core.write_text("def add(a, b):\n    return b + a\n")              # edit 1: still correct
    first = run_cli(app, "verify", "--run", "--json", "--test-command", CMD)
    assert first.returncode == 0, first.stdout + first.stderr

    core.write_text("def add(a, b):\n    return a - b\n")              # edit 2: breaks tests/test_add.py
    second = run_cli(app, "verify", "--run", "--json", "--test-command", CMD)
    fresh = run_cli(app, "verify", "--run", "--rerun", "--json", "--test-command", CMD)
    assert fresh.returncode == 1 and json.loads(fresh.stdout)["summary"]["verdict"] == "regression"  # it fails
    assert second.returncode == 1, ("verify --run reported a pass for a failing state: "
                                    + json.loads(second.stdout)["summary"]["verdict"]
                                    + (" (reused)" if json.loads(second.stdout)["evidence"].get("reused") else ""))


@needs_sandbox
def test_evidence_is_not_current_after_a_second_edit_inside_a_submodule(tmp_path: Path):
    app = _project(tmp_path)
    core = app / "vendor" / "calc" / "core.py"
    core.write_text("def add(a, b):\n    return b + a\n")
    assert run_cli(app, "verify", "--run", "--json", "--test-command", CMD).returncode == 0
    core.write_text("def add(a, b):\n    return a - b\n")
    ev = json.loads(run_cli(app, "evidence", "--json").stdout)
    assert not (ev["current"] and ev["evidence"]["verdict"].startswith("selected-and-full-suite-passed")), \
        "evidence reports a passing run as current for a different (failing) submodule state"
