"""The integration contract (docs/VERIFY-AGENT-CONTRACT.md) as tests: errors
are errors, the JSON keys a consumer relies on are always present, and one
definition of "passed" drives the exit code and the gate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli

from repo_ai.verify import evidence, gate


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    (root / "calc").mkdir(parents=True)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b\n")
    _git(root, "init", "-q", "-b", "master")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")
    return root


@pytest.mark.parametrize("extra", [[], ["--run"]])
def test_a_base_that_does_not_resolve_is_an_error_not_an_empty_change(repo: Path, extra: list[str]):
    """`--base main` where the branch is `master` used to plan an empty change,
    and `--run` recorded a passing verdict for it."""
    proc = run_cli(repo, "verify", "--json", "--base", "main", "--test-command", "python -m unittest", *extra)
    assert proc.returncode != 0 and "does not resolve" in proc.stderr, (proc.returncode, proc.stderr[-300:])
    assert not (repo / ".repo-ai" / "state" / "evidence").exists()


def test_a_repository_without_commits_still_plans_against_nothing(tmp_path: Path):
    root = tmp_path / "fresh"
    (root / "calc").mkdir(parents=True)
    (root / "calc" / "core.py").write_text("X = 1\n")
    _git(root, "init", "-q", "-b", "main")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    proc = run_cli(root, "verify", "--json", "--test-command", "python -m unittest")
    assert proc.returncode == 0, proc.stderr
    assert any(f["path"] == "calc/core.py" for f in json.loads(proc.stdout)["changed_files"])


def test_evidence_json_has_the_same_keys_when_there_is_none(repo: Path):
    proc = run_cli(repo, "evidence", "--json")
    assert proc.returncode == 1
    out = json.loads(proc.stdout)  # add-only: later keys (X13b's stale_reason, environment_check) may follow
    assert {k: out[k] for k in ("current", "same_behaviour", "evidence")} == {
        "current": False, "same_behaviour": False, "evidence": None}
    assert out["stale_reason"] is None and out["environment_check"] == "not checked"


VERDICTS = ["regression", "full-suite-failed", "failing (not compared with the base)",
            "failing (only next to other test files: order-dependent or flaky)",
            "failing (tests that fail at the base now fail differently)",
            "failing (all failures pre-existing at the base)", "not verified: 1 selected test file(s) skip every test",
            "selected-passed; full suite REQUIRED but not run",
            "selected-passed; full suite failed (not required; its failures cannot be attributed)",
            "no tests ran: the selected files define none", "invalid: the source tree changed during the run",
            "selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected"]


@pytest.mark.parametrize("verdict", VERDICTS)
def test_one_definition_of_passed(verdict: str):
    passing = verdict in {"selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected"}
    assert evidence.is_passing(verdict) is passing
    assert verdict.startswith(gate.PASSING) is passing


def test_staged_files_count_when_there_is_no_base_commit(tmp_path: Path):
    """A repository with no commit yet (or an orphan branch): `git add`-ed files are the change."""
    from repo_ai.verify import changes
    root = tmp_path / "fresh"
    (root / "calc").mkdir(parents=True)
    (root / "calc" / "core.py").write_text("X = 1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    change = changes.detect(root, "HEAD")
    assert [f.path for f in change.files] == ["calc/core.py"]
    assert changes.fingerprint(root, "HEAD") == change.fingerprint
