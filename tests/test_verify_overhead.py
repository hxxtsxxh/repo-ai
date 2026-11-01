"""Lower fixed per-run overhead without weakening any check
(docs/VERIFY-NEXT-OVERHEAD.md). Each cheaper path is compared with the path it
replaces (an oracle), and the plan-to-copy check is shown to stay fresh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli

from repo_ai import gitbin
from repo_ai.verify import changes, engine, isolate


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    files = {"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n", "pkg/b.py": "def g():\n    return 2\n",
             "pkg/gone.py": "X = 1\n", "pkg/moved.py": "def h():\n    return 3\n" * 20,
             "data/blob.bin": "\0\1\2binary", "with space.py": "A = 1\n", "ünï.py": "B = 1\n",
             "tests/__init__.py": "",
             "tests/test_a.py": "import unittest\nfrom pkg.a import f\n\n\nclass A(unittest.TestCase):\n"
                                "    def test_f(self):\n        self.assertEqual(f(), 1)\n"}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode())
    posix = os.name != "nt"  # Windows: no newline in a file name, and symlinks need privileges
    if posix:
        (root / "link").symlink_to("pkg/a.py")
        (root / "new\nline.py").write_text("N = 1\n")
    sub = root / "vendored"  # an embedded repository: recorded as a gitlink
    sub.mkdir()
    (sub / "x.txt").write_text("x\n")
    _git(sub, "init", "-q", "-b", "main")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-qm", "sub")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    assert _git(root, "ls-files", "-s", "vendored").startswith("160000")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    # every kind of change at once
    (root / "pkg" / "a.py").write_text("def f():\n    return 10\n")
    (root / "pkg" / "gone.py").unlink()
    _git(root, "mv", "pkg/moved.py", "pkg/renamed.py")
    (root / "pkg" / "renamed.py").write_text("def h():\n    return 3\n" * 19 + "def h2():\n    return 4\n")
    (root / "data" / "blob.bin").write_bytes(b"\0\3\4binary")
    (root / "with space.py").write_text("A = 2\n")
    (root / "ünï.py").write_text("B = 2\n")
    if posix:
        (root / "new\nline.py").write_text("N = 2\n")
        (root / "link").unlink()
        (root / "link").symlink_to("pkg/b.py")
    (root / "pkg" / "fresh.py").write_text("C = 1\n")  # untracked
    (sub / "x.txt").write_text("y\n")  # the gitlink moves
    _git(sub, "commit", "-qam", "moved")
    return root


def test_batched_base_blobs_give_exactly_the_per_file_reads(repo: Path):
    change = changes.detect(repo, "HEAD")
    commit = change.base_commit
    seen = set()
    for f in change.files:
        seen.add((f.path, f.status))
        if f.status == "added":
            assert f.old_sha == ""
            continue
        old = changes.base_blob(repo, commit, f.old_path or f.path)
        assert f.old_sha == changes.sha(old), f.path  # the oracle: one `cat-file blob` per file
    expected = {("pkg/a.py", "modified"), ("pkg/gone.py", "deleted"), ("pkg/renamed.py", "renamed"),
                ("data/blob.bin", "modified"), ("with space.py", "modified"), ("ünï.py", "modified"),
                ("pkg/fresh.py", "added"), ("vendored", "modified")}
    if os.name != "nt":
        expected |= {("new\nline.py", "modified"), ("link", "modified")}
    assert expected <= seen


def test_both_fingerprints_from_one_listing_equal_the_separate_ones(repo: Path):
    exact, semantic = changes.fingerprints(repo, "HEAD")
    assert exact == changes.fingerprint(repo, "HEAD") == changes.detect(repo, "HEAD").fingerprint
    assert semantic == changes.semantic_fingerprint(repo, "HEAD")


def _layout(root: Path):
    from repo_ai.config import load_config
    from repo_ai.paths import detect_kind, resolve_layout
    return resolve_layout(root, load_config(root), prefer=detect_kind(root) or "standard")


MEDDLES = ["edit an unchanged tracked file", "commit (HEAD moves)", "add an untracked file",
           "delete a tracked file"] + (["retarget a symlink"] if os.name != "nt" else [])


@pytest.mark.parametrize("meddle", MEDDLES)
def test_a_tree_change_during_the_copy_is_caught_after_the_copy(repo: Path, monkeypatch, meddle: str):
    """The re-check after the copy reads the tree again: it never reuses the
    plan's listing, base or diff."""
    change = changes.detect(repo, "HEAD")
    real = isolate.materialize

    def meddling(root, **kw):
        if meddle.startswith("edit"):
            (repo / "pkg" / "b.py").write_text("def g():\n    return 20\n")
        elif meddle.startswith("commit"):
            _git(repo, "commit", "-q", "--allow-empty", "-m", "moved")
        elif meddle.startswith("add"):
            (repo / "pkg" / "late.py").write_text("L = 1\n")
        elif meddle.startswith("delete"):
            (repo / "pkg" / "b.py").unlink()
        else:
            (repo / "link").unlink()
            (repo / "link").symlink_to("pkg/gone.py")
        return real(root, **kw)
    monkeypatch.setattr(isolate, "materialize", meddling)
    with pytest.raises(engine.VerifyError, match="changed while the run was being prepared"):
        engine._prepare(repo, change, "run", lambda _: None, layout=_layout(repo))


def test_the_re_check_reads_git_after_the_copy(repo: Path, monkeypatch):
    change = changes.detect(repo, "HEAD")
    events: list[str] = []
    real_git, real_mat = changes._git, isolate.materialize
    monkeypatch.setattr(changes, "_git", lambda root, *a, **k: (events.append(a[0]), real_git(root, *a, **k))[1])
    monkeypatch.setattr(isolate, "materialize", lambda root, **kw: (events.append("COPY"), real_mat(root, **kw))[1])
    before, ws, semantic = engine._prepare(repo, change, "run", lambda _: None, layout=_layout(repo))
    ws.cleanup()
    after = events[events.index("COPY") + 1:]
    assert "diff" in after and "ls-files" in after  # fresh, not taken from the plan
    assert semantic == changes.semantic_fingerprint(repo, "HEAD")


def test_same_tree_is_remembered_by_commit_pair(repo: Path, tmp_path: Path, monkeypatch):
    head = _git(repo, "rev-parse", "HEAD").strip()
    first = _git(repo, "rev-parse", "HEAD~1").strip()
    cache = tmp_path / "pairs.json"
    assert engine._same_tree(repo, first, head, cache) is True  # only repo-ai's own files differ
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned")))
    assert engine._same_tree(repo, first, head, cache) is True  # answered from the cache


def test_an_empty_dot_git_directory_is_not_a_repository_root(repo: Path):
    """No shortcut on `.git` existing: an empty `sub/.git` inside a repository is not its root."""
    from repo_ai import cli
    sub = repo / "pkg" / "sub"
    (sub / ".git").mkdir(parents=True)
    assert cli.resolve_root(str(sub)) == repo.resolve()


def test_base_blobs_the_batch_did_not_answer_are_read_one_by_one(repo: Path, monkeypatch):
    """`cat-file --batch` stops at the first object it cannot read (a partial clone offline):
    every object it did not answer is read on its own, so no present blob is lost."""
    real = changes.subprocess.run

    def truncated(cmd, **kw):
        res = real(cmd, **kw)
        if cmd[:3] == [gitbin.git(), "cat-file", "--batch"]:
            first = res.stdout.split(b"\n", 1)[0].split(b" ")
            size = int(first[2]) if len(first) == 3 and first[2].isdigit() else 0
            keep = len(first[0]) + len(first[1]) + len(first[2]) + 3 + size + 1 if size else 0
            res = subprocess.CompletedProcess(cmd, 0, res.stdout[:keep], b"fatal: Could not read from remote")
        return res
    monkeypatch.setattr(changes.subprocess, "run", truncated)
    change = changes.detect(repo, "HEAD")
    for f in change.files:
        if f.status != "added":
            assert f.old_sha == changes.sha(changes.base_blob(repo, change.base_commit, f.old_path or f.path)), f.path


def test_same_tree_does_not_depend_on_rename_detection(repo: Path, tmp_path: Path):
    """A source file moved into repo-ai's own directory is a deleted source file."""
    _git(repo, "stash", "-u")
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / ".repo-ai").mkdir(exist_ok=True)
    _git(repo, "mv", "pkg/b.py", ".repo-ai/b.py")
    _git(repo, "commit", "-qm", "move a source file into repo-ai's directory")
    moved = _git(repo, "rev-parse", "HEAD").strip()
    assert engine._same_tree(repo, head, moved, tmp_path / "pairs.json") is False
    assert engine._same_tree(repo, head, moved, tmp_path / "pairs.json") is False  # cached, still False
