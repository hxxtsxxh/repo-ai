"""A provider that rejects its credential inside repo-ai's isolation gets the exact re-authentication step.

Found by journey-live-v1 amendment 4 (2026-11-04): the dedicated Claude login was revoked server-side while
`claude auth status` still reported it as logged in; both sessions ended BLOCKED at $0 and the advice said only
`repo-ai agents setup <provider>`."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from repo_ai.mission import runtime
from repo_ai.providers import claude_auth

REVOKED = ("provider process exited with code 1; provider error event: authentication_failed; provider error event: "
           "Failed to authenticate: OAuth token revoked. Please log in again or contact your administrator.")


def _state(negative: str = REVOKED, **provider) -> dict:
    return {"state": "INCONCLUSIVE", "effective_verdict": "BLOCKED", "cleanup_confirmed": True,
            "provider": {"stage": "BLOCKED", **provider}, "passport": {"negative": [negative]}}


def test_a_revoked_default_dedicated_login_names_the_login_command(monkeypatch):
    monkeypatch.delenv(claude_auth.CONFIG_DIR_ENV, raising=False)
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="dedicated_config", auth_config_source="default"))
    assert rec["category"] == "provider_unavailable" and rec["recoverable"] is True
    assert claude_auth.login_command(claude_auth.default_config_dir()) in rec["action"]
    assert "checks only locally" in rec["action"] and "retrying will fail the same way" in rec["action"]
    assert "handoff --to" in rec["action"]


def test_a_run_that_used_the_env_dir_is_advised_with_the_variable_not_todays_default(tmp_path, monkeypatch):
    # the advice is computed later (status, why), perhaps without the variable the run had
    monkeypatch.delenv(claude_auth.CONFIG_DIR_ENV, raising=False)
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="dedicated_config", auth_config_source="env"))
    assert 'CLAUDE_CONFIG_DIR="${REPO_AI_CLAUDE_CONFIG_DIR:?set it to the directory the run used}" claude auth login' \
        in rec["action"]
    assert "the run used" in rec["action"] and str(claude_auth.default_config_dir()) not in rec["action"]


def test_a_default_dir_run_ignores_an_override_set_when_the_advice_is_shown(monkeypatch):
    monkeypatch.setenv(claude_auth.CONFIG_DIR_ENV, "/work/other-cfg")
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="dedicated_config", auth_config_source="default"))
    assert "/work/other-cfg" not in rec["action"] and "claude-provider claude auth login" in rec["action"]


def test_an_old_record_without_the_config_source_names_no_directory(monkeypatch):
    monkeypatch.setenv(claude_auth.CONFIG_DIR_ENV, "/work/other-cfg")
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="dedicated_config"))
    assert "CLAUDE_CONFIG_DIR" not in rec["action"] and "`repo-ai agents setup claude`" in rec["action"]
    assert "checks only locally" in rec["action"]


def test_a_preflight_setup_problem_is_not_told_to_log_in_again():
    for problem in ("settings.json sets `hooks`; remove it from repo-ai's Claude login",
                    "USER is not set", "/x/.claude is your personal Claude config"):
        negative = f"claude not authenticated for isolated execution: {problem}"
        rec = runtime.classify_recovery(_state(negative, name="claude", auth_mode="dedicated_config"))
        assert rec["category"] == "provider_unavailable"
        assert "auth login" not in rec["action"] and "revoked" not in rec["action"]
        assert "`repo-ai agents setup claude`" in rec["action"]


def test_a_rejected_oauth_token_says_to_create_a_new_one():
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="token_env",
                                           auth_env_vars=["CLAUDE_CODE_OAUTH_TOKEN"]))
    assert "claude setup-token" in rec["action"] and "auth login" not in rec["action"]


def test_a_rejected_api_key_is_not_told_to_run_setup_token():
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="token_env",
                                           auth_env_vars=["CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"]))
    assert "ANTHROPIC_API_KEY" in rec["action"] and "setup-token" not in rec["action"]


def test_other_providers_get_their_own_setup_command_not_a_placeholder():
    rec = runtime.classify_recovery(_state(name="codex"))
    assert "`repo-ai agents setup codex`" in rec["action"]


def test_a_provider_name_cannot_inject_text_into_the_advice():
    rec = runtime.classify_recovery(_state(name="co dex`, then echo"))
    assert "`repo-ai agents setup codexthenecho`" in rec["action"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell form; Windows shows the path as is")
def test_login_commands_are_pasteable_and_show_no_account_path(tmp_path):
    home = Path.home()
    assert claude_auth.login_command(home / ".local/share/repo-ai/claude-provider") == \
        "CLAUDE_CONFIG_DIR=~/.local/share/repo-ai/claude-provider claude auth login"
    spaced = tmp_path / "My Disk" / "claude cfg"
    if home.resolve() not in spaced.resolve().parents:
        assert claude_auth.login_command(spaced) == f"CLAUDE_CONFIG_DIR='{spaced}' claude auth login"
    assert claude_auth.shell_path(home / "a b") == "~/'a b'"


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell form; Windows shows the path as is")
def test_no_tilde_form_when_home_is_root_or_empty(monkeypatch):
    for value in ("/", ""):
        monkeypatch.setenv("HOME", value)
        assert claude_auth.shell_path(Path("/Users/x/.local/share/c")) == "/Users/x/.local/share/c"


def test_the_config_source_is_recorded_without_the_path():
    assert claude_auth.config_source({claude_auth.CONFIG_DIR_ENV: "/somewhere"}) == "env"
    assert claude_auth.config_source({}) == "default"


def test_windows_shows_the_path_as_is(monkeypatch):
    monkeypatch.setattr(claude_auth.os, "name", "nt")
    assert claude_auth.shell_path(Path("C:/Users/x/cfg dir")) == str(Path("C:/Users/x/cfg dir"))
