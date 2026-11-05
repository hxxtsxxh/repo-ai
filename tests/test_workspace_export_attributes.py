"""Mission workspaces hold the commit's tracked source, whatever `.gitattributes` says about `git archive` (found in
the review of #16): `export-ignore` used to drop files (often a whole `tests/`), `export-subst` rewrote `$Format$`."""
import os
import subprocess
import sys

import pytest

from repo_ai.verify import isolate


def _git(root, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=root, check=True, env=env, capture_output=True).stdout


def _repo(tmp_path, files, attributes):
    root = tmp_path / "r"
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    (root / ".gitattributes").write_text(attributes)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "b")
    return root


def test_export_ignore_and_export_subst_do_not_change_the_workspace(tmp_path):
    root = _repo(tmp_path, {"a.py": b"x = 1\n", "tests/test_a.py": b"def test_a():\n    assert True\n",
                            "version.txt": b"$Format:%H$\n", "tools/run.sh": b"#!/bin/sh\necho hi\n",
                            "win/build.bat": b"echo one\necho two\n"},
                 "tests/ export-ignore\nversion.txt export-subst\ntools/run.sh export-ignore\n"
                 "win/build.bat export-ignore eol=crlf\n.gitattributes export-ignore\n")
    (root / "tools" / "run.sh").chmod(0o755)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "exec bit")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert {"a.py", "tests/test_a.py", "version.txt", "tools/run.sh", "win/build.bat", ".gitattributes"} <= set(ws.files)
        assert (ws.path / "tests" / "test_a.py").read_bytes() == b"def test_a():\n    assert True\n"
        assert (ws.path / "version.txt").read_bytes() == b"$Format:%H$\n"  # as committed, not substituted
        assert os.access(ws.path / "tools" / "run.sh", os.X_OK)
        assert (ws.path / "win" / "build.bat").read_bytes() == b"echo one\r\necho two\r\n"  # as a checkout writes it


def test_a_repository_without_export_attributes_is_unchanged(tmp_path):
    root = _repo(tmp_path, {"a.py": b"x = 1\n"}, "*.py text\n")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert sorted(ws.files) == [".gitattributes", "a.py"]


def test_a_mission_on_a_repository_that_export_ignores_its_tests(tmp_path):
    from repo_ai.mission.runtime import execute, plan
    from test_mission_after_init import _project
    from test_mission_runtime import replay
    root = _project(tmp_path)
    (root / ".gitattributes").write_text("test_charge.py export-ignore\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "packaging attributes")
    p = plan(root, "Fix duplicate charge", agent="replay", write_paths=["charge.py"], execute_local=True)
    result = execute(root, p, replay(root, tmp_path))
    assert result["effective_verdict"] == "PASS", result.get("passport", {}).get("negative")


def test_a_provider_mission_on_a_repository_that_export_ignores_gitignore(tmp_path):
    from repo_ai.mission import runtime
    from test_mission_after_init import _project
    from test_provider_runtime import _make_fake_cli
    root = _project(tmp_path, gitignore="__pycache__/\n")
    (root / ".gitattributes").write_text(".gitignore export-ignore\n.gitattributes export-ignore\n")
    _git(root, "add", ".gitattributes")
    _git(root, "commit", "-qm", "packaging attributes")
    cli = _make_fake_cli(tmp_path, "codex", (
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"))
    planned = runtime.plan(root, "Fix duplicate charge", agent="codex", write_paths=["charge.py"], execute_local=True)
    result = runtime.execute(root, planned, None, provider_executable=cli)
    assert result["effective_verdict"] == "PASS", result["passport"]["negative"]


COMBOS = {
    "ident.txt": (b"$Id$\nline\n", "ident.txt export-ignore ident\n"),
    "eolcrlf.txt": (b"one\ntwo\n", "eolcrlf.txt export-ignore text eol=crlf\n"),
    "nul.txt": (b"a\x00b\nc\n", "nul.txt export-ignore text eol=crlf\n"),
    "already.txt": (b"one\r\ntwo\r\n", "already.txt export-ignore text=auto\n"),
    "lonecr.txt": (b"one\rtwo\n", "lonecr.txt export-ignore text=auto\n"),
    "plain.txt": (b"one\ntwo\n", "plain.txt export-ignore text\n"),
}


@pytest.mark.parametrize("config", [[], ["core.autocrlf", "true"], ["core.eol", "crlf"]])
def test_restored_bytes_equal_what_a_checkout_writes(tmp_path, config):
    files = {name: data for name, (data, _) in COMBOS.items()}
    root = _repo(tmp_path, files, "".join(attr for _, attr in COMBOS.values()))
    if config:
        _git(root, "config", *config)
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", *(["-c", f"{config[0]}={config[1]}"] if config else []), str(root), str(clone))
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        for name in COMBOS:
            assert (ws.path / name).read_bytes() == (clone / name).read_bytes(), (name, config)


def test_an_export_ignored_symlink_is_restored_under_the_archive_rules(tmp_path):
    root = _repo(tmp_path, {"data/d.txt": b"x\n"}, "tests/ export-ignore\n")
    (root / "tests").mkdir()
    (root / "tests" / "fx").symlink_to("../data/d.txt")
    (root / "tests" / "out").symlink_to("/etc/hosts")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "links")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert (ws.path / "tests" / "fx").is_symlink() and (ws.path / "tests" / "fx").read_bytes() == b"x\n"
        assert not (ws.path / "tests" / "out").exists() and not (ws.path / "tests" / "out").is_symlink()


def test_a_missing_object_is_an_isolation_error_not_a_crash(tmp_path):
    root = _repo(tmp_path, {"a.py": b"x = 1\n", "tests/t.py": b"y = 2\n"}, "tests/ export-ignore\n")
    sha = _git(root, "rev-parse", "HEAD:tests/t.py").decode().strip()
    (root / ".git" / "objects" / sha[:2] / sha[2:]).unlink()
    with pytest.raises(isolate.IsolationError):
        with isolate.materialize_commit(root, "HEAD", dependencies=False):
            pass


@pytest.mark.skipif(sys.platform in {"darwin", "win32"}, reason="the filesystem refuses names that are not UTF-8")
def test_a_name_that_is_not_utf8_does_not_crash(tmp_path):
    root = _repo(tmp_path, {"a.py": b"x = 1\n"}, "*.py text\n")
    (root / os.fsdecode(b"caf\xe9.txt")).write_bytes(b"latin-1 name\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "odd name")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert os.fsdecode(b"caf\xe9.txt") in ws.files


def test_restored_links_cannot_redirect_each_other_outside(tmp_path):
    """Review of #22: links were checked one at a time, so a later link (`c`) could make an earlier one (`a`) point
    outside the workspace once both existed."""
    root = _repo(tmp_path, {"keep.py": b"x = 1\n"}, "x/ export-ignore\n")
    (root / "x" / "y" / "z").mkdir(parents=True)
    (root / "x" / "y" / "z" / "a").symlink_to("c/../../..")
    (root / "x" / "y" / "z" / "c").symlink_to("../..")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "chained links")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        base = ws.path.resolve()
        for link in (p for p in ws.path.rglob("*") if p.is_symlink()):
            assert base in link.resolve().parents, f"{link} -> {os.readlink(link)} leaves the workspace"


def test_a_large_export_ignored_tests_directory_is_restored_in_one_process(tmp_path):
    import time
    files = {f"tests/test_{i}.py": f"def test_{i}():\n    assert {i} == {i}\n".encode() for i in range(2000)}
    root = _repo(tmp_path, {"a.py": b"x = 1\n", **files}, "tests/ export-ignore\n")
    started = time.monotonic()
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert len([f for f in ws.files if f.startswith("tests/")]) == 2000
    assert time.monotonic() - started < 30, "restore must not cost a process per file"


def test_a_smudge_filter_that_reports_on_stderr_does_not_fail_the_restore(tmp_path):
    """Review round 3 of #22: git-lfs prints progress on stderr; only a nonzero exit is a failure."""
    root = _repo(tmp_path, {"a.py": b"x = 1\n", "t.txt": b"payload\n"}, "t.txt export-ignore filter=noisy\n")
    _git(root, "config", "filter.noisy.smudge", "echo Downloading >&2; cat")
    _git(root, "config", "filter.noisy.clean", "cat")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert (ws.path / "t.txt").read_bytes() == b"payload\n"


def test_the_restore_leaves_no_fsmonitor_daemon_behind(tmp_path):
    root = _repo(tmp_path, {"a.py": b"x = 1\n", "tests/t.py": b"y = 2\n"}, "tests/ export-ignore\n")
    _git(root, "config", "core.fsmonitor", "true")
    with isolate.materialize_commit(root, "HEAD", dependencies=False) as ws:
        assert "tests/t.py" in ws.files
    assert not (root / ".git" / "fsmonitor--daemon.ipc").exists()
