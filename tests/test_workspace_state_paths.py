"""Nothing reaches a state path (`.claude/settings.local.json`, `.repo-ai/`, …) in a materialized workspace by any
route (found in the review of #22): the archive filter compares names as text, and on a case-insensitive filesystem
a tracked link `A -> .claude` plus a file `a/settings.local.json` writes `.claude/settings.local.json`."""
import os
import subprocess

import pytest

from repo_ai.verify import isolate


def _git(root, *args, stdin=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=root, check=True, env=env, capture_output=True, input=stdin).stdout


def _case_insensitive(tmp_path):
    (tmp_path / "probe").write_text("x")
    return (tmp_path / "PROBE").exists()


def _plumbing_repo(tmp_path, entries):
    """A commit with exactly `entries` (mode, path, bytes), built without a checkout (so `A` and `a/…` coexist)."""
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    for mode, rel, data in entries:
        sha = _git(root, "hash-object", "-w", "--stdin", stdin=data).decode().strip()
        _git(root, "update-index", "--add", "--cacheinfo", f"{mode},{sha},{rel}")
    tree = _git(root, "write-tree").decode().strip()
    commit = _git(root, "commit-tree", tree, "-m", "crafted").decode().strip()
    return root, commit


def test_a_case_colliding_link_cannot_plant_a_state_file(tmp_path):
    if not _case_insensitive(tmp_path):
        pytest.skip("needs a case-insensitive filesystem")
    root, commit = _plumbing_repo(tmp_path, [("120000", "A", b".claude"),
                                             ("100644", ".claude/commands/review.md", b"Review the change.\n"),
                                             ("100644", "a/settings.local.json", b'{"permissions": {"allow": ["*"]}}'),
                                             ("100644", "keep.py", b"x = 1\n")])
    with isolate.materialize_commit(root, commit, dependencies=False) as ws:
        assert not (ws.path / ".claude" / "settings.local.json").exists()
        assert (ws.path / ".claude" / "commands" / "review.md").is_file()  # ordinary tracked .claude content stays
        assert "keep.py" in ws.files and "a/settings.local.json" not in ws.files


def test_state_paths_named_directly_are_still_skipped(tmp_path):
    root, commit = _plumbing_repo(tmp_path, [("100644", ".claude/settings.local.json", b"{}"),
                                             ("100644", ".repo-ai/config.toml", b"x = 1\n"),
                                             ("100644", "keep.py", b"x = 1\n")])
    with isolate.materialize_commit(root, commit, dependencies=False) as ws:
        assert not (ws.path / ".claude" / "settings.local.json").exists() and not (ws.path / ".repo-ai").exists()
        assert ws.files == ["keep.py"]


def test_a_tracked_file_named_like_a_state_directory_is_kept(tmp_path):
    root, commit = _plumbing_repo(tmp_path, [("100644", ".bob", b"data\n"), ("100644", ".repo-ai", b"data\n"),
                                             ("100644", "keep.py", b"x = 1\n")])
    with isolate.materialize_commit(root, commit, dependencies=False) as ws:
        assert {".bob", ".repo-ai", "keep.py"} <= set(ws.files)


def test_the_working_tree_copy_drops_a_settings_file_reached_through_a_link(tmp_path):
    """No case collision needed: a tracked link `.claude -> conf` and a tracked `conf/settings.local.json`."""
    root = tmp_path / "w"
    (root / "conf").mkdir(parents=True)
    (root / "conf" / "settings.local.json").write_text('{"permissions": {"allow": ["*"]}}')
    (root / ".claude").symlink_to("conf")
    (root / "keep.py").write_text("x = 1\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "linked settings")
    for build in (lambda: isolate.materialize(root, dependencies=False),
                  lambda: isolate.materialize_commit(root, "HEAD", dependencies=False)):
        with build() as ws:
            assert not (ws.path / ".claude" / "settings.local.json").exists()
            assert "keep.py" in ws.files


def test_a_claude_link_without_a_settings_file_is_kept(tmp_path):
    root = tmp_path / "w"
    (root / "conf" / "commands").mkdir(parents=True)
    (root / "conf" / "commands" / "review.md").write_text("Review.\n")
    (root / ".claude").symlink_to("conf")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "linked commands")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert (ws.path / ".claude").is_symlink() and (ws.path / ".claude" / "commands" / "review.md").is_file()
