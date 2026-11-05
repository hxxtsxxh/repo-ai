"""`agents setup claude` notes a plaintext credentials file in repo-ai's dedicated Claude login on macOS.

Observed 2026-11-04: a revoked login failing inside a run made Claude Code write `.credentials.json` into the
dedicated config directory (the login before lived only in the Keychain). It is reported, never read or removed,
and never makes the login unusable."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repo_ai.providers import claude_auth

_WATCH: dict[str, list[str] | None] = {"events": None}


def _hook(event: str, args: tuple) -> None:
    events = _WATCH["events"]
    if events is not None and event == "open" and args and str(args[0]).endswith(".credentials.json"):
        events.append(str(args[0]))


sys.addaudithook(_hook)  # an audit hook cannot be removed: it records only while a test switches it on


def test_a_plaintext_credentials_file_is_noted_on_macos_and_never_opened(tmp_path):
    (tmp_path / ".credentials.json").write_text("not json and never read")
    _WATCH["events"] = seen = []
    try:
        note = claude_auth.plaintext_credentials_note(tmp_path, platform="darwin")
        plan = claude_auth.plan({claude_auth.CONFIG_DIR_ENV: str(tmp_path), "USER": "someone"}, platform="darwin")
    finally:
        _WATCH["events"] = None
    assert note and ".credentials.json" in note and "Keychain" in note
    assert "move it aside" in note and "live or an old token" in note
    assert plan.notes == (note,)
    assert seen == []  # catches open(), Path.read_text/read_bytes/open and os.open alike


def test_the_audit_hook_would_catch_a_read(tmp_path):
    cred = tmp_path / ".credentials.json"
    cred.write_text("x")
    _WATCH["events"] = seen = []
    try:
        cred.read_text()
    finally:
        _WATCH["events"] = None
    assert seen == [str(cred)]


def test_no_note_elsewhere_or_without_a_regular_file(tmp_path):
    assert claude_auth.plaintext_credentials_note(tmp_path, platform="darwin") is None
    (tmp_path / ".credentials.json").write_text("x")
    assert claude_auth.plaintext_credentials_note(tmp_path, platform="linux") is None
    other = tmp_path / "other"
    other.mkdir()
    os.symlink(tmp_path / ".credentials.json", other / ".credentials.json")
    assert claude_auth.plaintext_credentials_note(other, platform="darwin") is None
    folder = tmp_path / "folder"
    (folder / ".credentials.json").mkdir(parents=True)
    assert claude_auth.plaintext_credentials_note(folder, platform="darwin") is None


def test_the_note_never_makes_the_plan_unusable(tmp_path):
    cfg = tmp_path / "claude-provider"
    cfg.mkdir()
    (cfg / ".credentials.json").write_text("x")
    plan = claude_auth.plan({claude_auth.CONFIG_DIR_ENV: str(cfg), "USER": "someone"}, platform="darwin")
    assert plan.mode == "dedicated_config" and plan.notes and not plan.problems and plan.usable
    assert plan.to_json()["notes"] == list(plan.notes)


def test_a_token_user_is_told_about_a_plaintext_token_left_in_the_dedicated_directory(tmp_path):
    cfg = tmp_path / "claude-provider"
    cfg.mkdir()
    (cfg / ".credentials.json").write_text("x")
    plan = claude_auth.plan({claude_auth.CONFIG_DIR_ENV: str(cfg), "CLAUDE_CODE_OAUTH_TOKEN": "set"}, platform="darwin")
    assert plan.mode == "token_env" and plan.usable and plan.notes


def test_the_note_shows_the_home_relative_form(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX shell form")
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / ".credentials.json").write_text("x")
    note = claude_auth.plaintext_credentials_note(cfg, platform="darwin")
    assert note is not None and note.startswith("~/cfg/.credentials.json exists")


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="POSIX, not root")
def test_an_unreadable_login_directory_is_a_problem_not_a_crash(tmp_path):
    cfg = tmp_path / "claude-provider"
    (cfg / "skills").mkdir(parents=True)
    cfg.chmod(0)
    try:
        problems = claude_auth.audit_config_dir(cfg)
    finally:
        cfg.chmod(0o700)
    assert problems and "could not be inspected" in problems[0]


def test_agents_setup_prints_and_exports_the_note(tmp_path):
    if sys.platform != "darwin":
        pytest.skip("the note is macOS-only")
    cfg = tmp_path / "claude-provider"
    cfg.mkdir()
    (cfg / ".credentials.json").write_text("x")
    src = str(Path(claude_auth.__file__).resolve().parents[2])  # this checkout, whatever the cwd
    env = {**os.environ, claude_auth.CONFIG_DIR_ENV: str(cfg), "USER": "someone",
           "PYTHONPATH": os.pathsep.join(p for p in (src, os.environ.get("PYTHONPATH", "")) if p)}
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env.pop("ANTHROPIC_API_KEY", None)
    base = [sys.executable, "-m", "repo_ai.cli", "agents", "setup", "claude"]
    text = subprocess.run(base, env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert "note: " in text.stdout and ".credentials.json exists" in text.stdout
    data = json.loads(subprocess.run([*base, "--json"], env=env, capture_output=True, text=True, timeout=60,
                                     cwd=tmp_path).stdout)
    assert data["notes"] and data["credential_read"] is False
