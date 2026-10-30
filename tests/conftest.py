"""Shared helpers: fixture repositories as real git repos, and a CLI runner."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SRC = Path(__file__).resolve().parent.parent / "src"


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", *args], cwd=cwd, check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_repo(tmp_path: Path, fixture: str, name: str | None = None, git: bool = True) -> Path:
    dest = tmp_path / (name or fixture)
    shutil.copytree(FIXTURES / fixture, dest)
    if git:
        _git(dest, "init", "-q", "-b", "main")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-qm", "initial")
    return dest


def commit_all(repo: Path, message: str = "change") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def default_sigint() -> None:
    """`preexec_fn` for a child a test interrupts with SIGINT. A shell starts a
    background job with SIGINT ignored, its children inherit that and Python
    keeps an inherited SIG_IGN, so the test's Ctrl-C would be dropped and the
    child would run to its own limit: the outcome would depend on how pytest was
    launched rather than on the code under test."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def evidence_environment(root: Path) -> dict:
    """Current identity for synthetic records in gate/history contract tests."""
    from types import SimpleNamespace

    from repo_ai import __version__
    from repo_ai.verify.cache import static_environment
    from repo_ai.verify.execute import interpreter

    found = interpreter(root, probe=False)
    assert found is not None
    ex = SimpleNamespace(is_container=False, python=found.python, node="node", site_dirs=[], links={})
    return {"repo_ai_version": __version__,
            "environment_static": static_environment(ex, SimpleNamespace(kind="pytest"))}


def cli_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("REPO_AI_", "CLAUDE_"))}
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["REPO_AI_NO_BACKGROUND"] = "1"  # tests never leave detached refreshes behind
    env.update(extra or {})
    return env


def run_cli(repo: Path | None, *args: str, stdin: str | None = None,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "repo_ai", *args]
    if repo is not None:
        cmd += ["-C", str(repo)]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", input=stdin,
                          check=False, env=cli_env(env), timeout=300)


def run_hook(repo: Path, event: str, payload: dict | str) -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, "-m", "repo_ai", "hook", "claude", event],
                          capture_output=True, text=True, encoding="utf-8", input=data,
                          check=False, cwd=repo,
                          env=cli_env({"CLAUDE_PROJECT_DIR": str(repo)}), timeout=60)


def snapshot(root: Path, skip: tuple[str, ...] = (".git", ".repo-ai/state")) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not any(rel == s or rel.startswith(s + "/") for s in skip):
            out[rel] = path.read_bytes()
    return out


@pytest.fixture
def pyweb(tmp_path: Path) -> Path:
    return make_repo(tmp_path, "pyweb")


@pytest.fixture
def tsmono(tmp_path: Path) -> Path:
    return make_repo(tmp_path, "tsmonorepo")


# --- platform gating for the mission/provider runtime -------------------------------------------------
# These tests execute candidates and tests inside a host sandbox (seatbelt on macOS, bwrap on Linux) and
# apply patches with POSIX O_NOFOLLOW/dir_fd. On a host without that they cannot run, which is a statement
# about the host, not a pass: they are SKIPPED with the reason, and the sandbox-bwrap CI job runs them with
# bubblewrap installed. Windows is unsupported for missions (refused at runtime by `safe application requires
# POSIX no-follow`).
_MISSION_NEEDS_SANDBOX = {
    "test_mission_cli", "test_mission_decision_chain", "test_mission_demo",
    "test_mission_diagnosis", "test_mission_explanation", "test_mission_partial_handoff",
    "test_mission_phase2_activation", "test_mission_recovery", "test_mission_roles", "test_mission_runtime",
    "test_mission_slices_c_through_j", "test_mission_tournament", "test_mission_verification",
    "test_provider_runtime", "test_mission_diff_fidelity", "test_mission_path_privacy", "test_mission_exercise", "test_mission_exercise_challenge",
    "test_mission_claims_runtime", "test_live_tournament", "test_mission_requirement_erasure_runtime",
    "test_mission_expect_fix", "test_mission_expect_fix_review", "test_mission_expect_fix_review_handoff",
    "test_mission_expect_fix_review_cli", "test_mission_after_init",
    "test_mission_after_init_review",
}
_MISSION_POSIX_ONLY = _MISSION_NEEDS_SANDBOX | {
    "test_eval_integrity", "test_mission_real_project_edges", "test_mission_apply_transaction",
    "test_provider_channels", "test_provider_probe", "test_mission_redteam", "test_mission_review_state",
    "test_mission_review_security", "test_abc_protocol", "test_abc_v2_protocol", "test_abc_v3_protocol", "test_abc_v4_protocol", "test_abc_v5_protocol",
}
_SANDBOX_STATE: list[bool] = []


def _host_has_sandbox() -> bool:
    if not _SANDBOX_STATE:
        sys.path.insert(0, str(Path(__file__).parent))
        from test_verify_engine import _host_sandbox
        _SANDBOX_STATE.append(bool(_host_sandbox()))
    return _SANDBOX_STATE[0]


def pytest_collection_modifyitems(config, items):
    if sys.platform == "win32":
        skip = pytest.mark.skip(reason="repo-ai missions are POSIX-only (O_NOFOLLOW/dir_fd, host sandbox); unsupported on Windows")
        for item in items:
            if Path(str(item.fspath)).stem in _MISSION_POSIX_ONLY:
                item.add_marker(skip)
        return
    targets = [i for i in items if Path(str(i.fspath)).stem in _MISSION_NEEDS_SANDBOX]
    if targets and not _host_has_sandbox():
        skip = pytest.mark.skip(reason="no host sandbox backend (bwrap/seatbelt) to run mission candidates in; "
                                       "covered by the sandbox-bwrap CI job")
        for item in targets:
            item.add_marker(skip)


@pytest.fixture()
def claude_fake_login(monkeypatch):
    """For tests that drive a *fake* `claude` in live mode: give it a token-mode login and skip the real
    `--help` flag preflight (covered by tests/test_provider_claude_isolation.py)."""
    from repo_ai.providers import adapters
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-token-for-tests")
    monkeypatch.setattr(adapters, "_claude_preflight", lambda executable, plan: None)
    monkeypatch.setattr(adapters, "_claude_isolation_probe", lambda *a, **k: [])
    monkeypatch.setattr(adapters, "_claude_init_problems", lambda init, read_only: [])
    monkeypatch.setattr(adapters, "_claude_init_event", lambda output: {"fake": True})
