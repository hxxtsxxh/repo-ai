"""Shared helpers for the 7fa342d red-team probes (same style as ../test_redteam_*.py).

Differences from the earlier helpers: AI_AGENT is stripped from a "terminal" environment
(7fa342d counts it as an agent shell), and `shipped()` runs a snippet against the real
working tree on the host (fixture code written by the probe itself) to show what the
candidate as shipped does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import repo_ai

_TESTS = Path(repo_ai.__file__).resolve().parents[2] / "tests"
sys.path.insert(0, str(_TESTS))
from conftest import cli_env  # noqa: E402
from test_verify_engine import _host_sandbox  # noqa: E402,F401

AGENT_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "REPO_AI_IN_HOOK", "REPO_AI_AGENT",
              "CI", "GITHUB_ACTIONS", "AI_AGENT")
PT = ["--test-command", "python -m pytest -q tests"]
UT = ["--test-command", "python -m unittest discover -s tests -t ."]


def cli(root: Path, *args: str, agent: bool = False) -> subprocess.CompletedProcess:
    env = {k: v for k, v in cli_env().items() if k not in AGENT_VARS}
    if agent:
        env["CLAUDECODE"] = "1"
    return subprocess.run([sys.executable, "-m", "repo_ai", *args, "-C", str(root)], capture_output=True, text=True,
                          env=env, timeout=600, check=False)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={**cli_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def make_repo(root: Path, files: dict[str, str]) -> Path:
    write(root, files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    assert cli(root, "init", "--agent", "none", "-q").returncode == 0
    git(root, "add", "-A")
    git(root, "commit", "-qm", "repo-ai init")
    return root


def pin(root: Path, scenario: str, outside: Path | None, *extra: str, agent: bool = False
        ) -> subprocess.CompletedProcess:
    where = ["--file", str(outside)] if outside is not None else []
    return cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", scenario, *where, *extra, agent=agent)


def run(root: Path, *extra: str, agent: bool = False) -> tuple[int, dict]:
    proc = cli(root, "prove", "run", "c", "--json", *extra, agent=agent)
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def pin_and_run(root: Path, scenario: str, outside: Path | None, *pin_extra: str, run_extra: tuple[str, ...] = (),
                agent: bool = False) -> tuple[int, dict]:
    p = pin(root, scenario, outside, *pin_extra, agent=agent)
    assert p.returncode == 0, p.stderr
    return run(root, *run_extra, agent=agent)


def shipped(root: Path, code: str) -> subprocess.CompletedProcess:
    """Run `code` against the candidate exactly as the working tree ships it."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("REPO_AI_", "CLAUDE"))}
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # no __pycache__ in the working tree (it would join the change)
    return subprocess.run([sys.executable, "-I", "-B", "-c", f"import sys; sys.path.insert(0, {str(root)!r}); {code}"],
                          cwd=root, capture_output=True, text=True, timeout=60, env=env, check=False)


def summary(pp: dict) -> str:
    rec = (pp.get("evidence") or [{}])[0]
    subj = pp.get("subject") or {}
    return (f"verdict {pp['verdict']['state']} level {pp['verdict'].get('level')} "
            f"(record {((rec.get('claim') or {}).get('level'))}); subject {subj.get('files')} declared "
            f"{subj.get('declared')} left_out {subj.get('left_out')}; regressions "
            f"{(pp.get('regressions') or {}).get('state')}; edited {(pp.get('edited_tests') or {}).get('state')}; "
            f"reasons {pp['verdict'].get('reasons')}")
