"""#56 (F2c): read-only `prove` commands never execute a repository interpreter on the host.

End-to-end through the CLI: an untracked, git-ignored `.venv/bin/python` stand-in records every
invocation in a canary file. `prove status`, `prove report` and `prove plan` must not run it; the
`verify` preview is the control. Fixed by the static interpreter resolution in 4efbac4; this is the
red-team probe from `redteam/prooflab-8288b2f` kept as a regression test.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the stand-in interpreter is a POSIX shell script")

SRC = str(Path(__file__).resolve().parents[1] / "src")
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null"]


def cli(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("REPO_AI_", "CLAUDE", "AI_AGENT", "VIRTUAL_ENV"))}
    env.update(PYTHONPATH=SRC, REPO_AI_NO_BACKGROUND="1", HOME=str(root.parent / "home"))
    return subprocess.run([sys.executable, "-m", "repo_ai", *args, "-C", str(root)], capture_output=True, text=True,
                          env=env, timeout=300, stdin=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("f2c")
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("def one():\n    return 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_one.py").write_text("from pkg import one\n\n\ndef test_one():\n    assert one() == 1\n")
    (root / ".gitignore").write_text(".venv/\n")
    (tmp_path / "home").mkdir()
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-qm", "c"]):
        subprocess.run([*GIT, *cmd], cwd=root, check=True, capture_output=True)
    assert cli(root, "init", "--agent", "none", "-q").returncode == 0
    pin = cli(root, "prove", "pin", "--claim", "one returns 1", "--scenario", "tests/test_one.py", "--from", "HEAD",
              "--test-command", "python -m pytest -q tests", "--json")
    assert pin.returncode == 0, pin.stderr[-400:]
    canary = tmp_path / "ran-on-host.txt"
    fake = root / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> '{canary}'\nexec '{sys.executable}' \"$@\"\n")
    fake.chmod(0o755)
    assert subprocess.run(["git", "check-ignore", "-q", ".venv/bin/python"], cwd=root).returncode == 0
    return root, canary


@pytest.mark.parametrize("args", [("prove", "status"), ("prove", "status", "--json"),
                                  ("prove", "report"), ("prove", "plan", "--json"),
                                  ("verify", "--json", "--test-command", "python -m pytest -q tests")])
def test_read_only_command_never_runs_a_repo_interpreter_on_the_host(repo, args):
    root, canary = repo
    canary.unlink(missing_ok=True)
    out = cli(root, *args)
    ran = canary.read_text() if canary.exists() else ""
    assert not ran, f"`repo-ai {' '.join(args)}` (exit {out.returncode}) executed .venv/bin/python on the host: {ran!r}"
