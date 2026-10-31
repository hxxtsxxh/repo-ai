"""Parallel workspace copies are one copy-on-write clone of the whole tree where the filesystem allows it (APFS),
with the same content as the file-by-file copy and their own ownership marker."""
import json
import os
import platform
import subprocess

import pytest

from repo_ai.verify import isolate


def _repo(tmp_path):
    root = tmp_path / "r"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("x = 1\n")
    (root / "run.sh").write_text("#!/bin/sh\n")
    (root / "run.sh").chmod(0o755)
    (root / "link").symlink_to("pkg/a.py")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "b"]):
        subprocess.run(["git", *args], cwd=root, check=True, env=env, capture_output=True)
    return root


def _tree(path):
    out = {}
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, path)
            if rel == isolate.WS_MARKER:
                continue
            out[rel] = ("link", os.readlink(p)) if os.path.islink(p) else (open(p, "rb").read(), os.access(p, os.X_OK))
    return out


def test_a_parallel_copy_has_the_same_content_and_its_own_marker(tmp_path):
    root = _repo(tmp_path)
    with isolate.materialize(root, dependencies=False) as ws:
        twin = ws.clone("t")
        try:
            assert twin.path != ws.path and sorted(twin.files) == sorted(ws.files)
            assert _tree(twin.path) == _tree(ws.path)
            marker = json.loads((twin.path / isolate.WS_MARKER).read_text())
            assert marker["pid"] == os.getpid()
            if platform.system() == "Darwin":
                assert twin.method == "clone"
        finally:
            twin.cleanup()
        assert not twin.path.exists()


def test_a_failed_tree_clone_falls_back_to_copying_file_by_file(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(isolate, "_clone_tree", lambda src, label, keep: None)
    with isolate.materialize(root, dependencies=False) as ws:
        twin = ws.clone("t")
        try:
            assert _tree(twin.path) == _tree(ws.path)
        finally:
            twin.cleanup()


@pytest.mark.skipif(platform.system() != "Darwin", reason="clonefile(2) is macOS")
def test_writes_in_a_copy_never_reach_the_template(tmp_path):
    root = _repo(tmp_path)
    with isolate.materialize(root, dependencies=False) as ws:
        twin = ws.clone("t")
        try:
            (twin.path / "pkg" / "a.py").write_text("x = 2\n")
            assert (ws.path / "pkg" / "a.py").read_text() == "x = 1\n"
        finally:
            twin.cleanup()


def test_a_copy_holds_only_listed_files_not_what_a_dropped_file_left(tmp_path):
    """Review of #28: a dropped file's empty directory (prove experiments) must not reach a run: `pkg.sub` would
    import as a namespace package in the copy although the change removed it."""
    root = _repo(tmp_path)
    (root / "pkg" / "sub").mkdir()
    (root / "pkg" / "sub" / "only.py").write_text("y = 1\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "sub"], cwd=root, check=True, env=env)
    with isolate.materialize(root, dependencies=False) as ws:
        (ws.path / "pkg" / "sub" / "only.py").unlink()  # what a dropped file leaves: an empty directory
        ws.files.remove("pkg/sub/only.py")
        (ws.path / "stray.txt").write_text("not listed")
        twin = ws.clone("t")
        try:
            assert not (twin.path / "pkg" / "sub").exists() and not (twin.path / "stray.txt").exists()
            assert (twin.path / "pkg" / "a.py").is_file() and (twin.path / "link").is_symlink()
        finally:
            twin.cleanup()
