"""repo-ai's own git commands never start git's background maintenance or gc.

A commit through `mission.runtime.git` let git spawn `git maintenance run --auto` in the background, which wrote
`.git/objects/maintenance.lock` while a fixture repository was being copied (a macOS CI failure in
test_eval_integrity). The eval lab's `evals._git` commits and then copies `.git` the same way."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from repo_ai import evals
from repo_ai.mission import runtime

GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _repo_with_eager_maintenance(root: Path) -> Path:
    """A repository whose own config makes maintenance run in the foreground and write a commit-graph on the very
    next `maintenance run --auto` (what a commit triggers when maintenance.auto is on)."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, value in (("maintenance.autoDetach", "false"), ("maintenance.strategy", "none"),
                       ("maintenance.commit-graph.enabled", "true"), ("maintenance.commit-graph.auto", "1")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    (root / "a.txt").write_text("a\n")
    return root


def _maintenance_ran(root: Path) -> bool:
    objects = root / ".git" / "objects"
    return (objects / "info" / "commit-graph").exists() or (objects / "info" / "commit-graphs").exists() \
        or (objects / "maintenance.lock").exists()


def test_the_control_shows_a_commit_runs_maintenance_without_the_flags(tmp_path: Path):
    root = _repo_with_eager_maintenance(tmp_path / "control")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "x"], check=True, env={**os.environ, **GIT_ID})
    if not _maintenance_ran(root):
        pytest.skip("this git does not run auto-maintenance after a commit; the test below would prove nothing")


def test_mission_git_commits_start_no_maintenance(tmp_path: Path):
    root = _repo_with_eager_maintenance(tmp_path / "mission")
    runtime.git(root, "add", "-A")
    runtime.git(root, "commit", "-qm", "x")
    assert not _maintenance_ran(root)


def test_eval_lab_git_commits_start_no_maintenance(tmp_path: Path):
    root = _repo_with_eager_maintenance(tmp_path / "lab")
    evals._git(root, "add", "-A")
    evals._git(root, "commit", "-qm", "x")
    assert not _maintenance_ran(root)
