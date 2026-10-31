"""Mission workspaces hold the commit's tracked source, whatever `.gitattributes` says about `git archive` (found in
the review of #16): `export-ignore` used to drop files (often a whole `tests/`), `export-subst` rewrote `$Format$`."""
import os
import subprocess
from pathlib import Path

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
