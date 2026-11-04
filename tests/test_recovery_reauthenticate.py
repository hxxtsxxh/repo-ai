"""A provider that rejects its credential inside repo-ai's isolation gets the exact re-authentication step.

Found by journey-live-v1 amendment 4 (2026-11-04): the dedicated Claude login was revoked server-side while
`claude auth status` still reported it as logged in; both sessions ended BLOCKED at $0 and the advice said only
`repo-ai agents setup <provider>`."""
from __future__ import annotations

from repo_ai.mission import runtime
from repo_ai.providers import claude_auth

REVOKED = ("provider process exited with code 1; provider error event: authentication_failed; provider error event: "
           "Failed to authenticate: OAuth token revoked. Please log in again or contact your administrator.")


def _state(**provider) -> dict:
    return {"state": "INCONCLUSIVE", "effective_verdict": "BLOCKED", "cleanup_confirmed": True,
            "provider": {"stage": "BLOCKED", **provider}, "passport": {"negative": [REVOKED]}}


def test_a_revoked_dedicated_claude_login_names_the_login_command(tmp_path, monkeypatch):
    monkeypatch.setenv(claude_auth.CONFIG_DIR_ENV, str(tmp_path / "claude-provider"))
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="dedicated_config"))
    assert rec["category"] == "provider_unavailable" and rec["recoverable"] is True
    assert f"CLAUDE_CONFIG_DIR={tmp_path / 'claude-provider'} claude auth login" in rec["action"]
    assert "checks only locally" in rec["action"] and "retrying will fail the same way" in rec["action"]
    assert "handoff --to" in rec["action"]


def test_a_rejected_token_says_to_create_a_new_one():
    rec = runtime.classify_recovery(_state(name="claude", auth_mode="token_env"))
    assert "claude setup-token" in rec["action"] and "auth login" not in rec["action"]


def test_other_providers_get_their_own_setup_command_not_a_placeholder():
    rec = runtime.classify_recovery(_state(name="codex"))
    assert "`repo-ai agents setup codex`" in rec["action"] and "<provider>`" not in rec["action"].split("handoff")[0]


def test_a_provider_name_cannot_inject_text_into_the_advice():
    rec = runtime.classify_recovery(_state(name="co dex`, then echo"))
    assert "`repo-ai agents setup codexthenecho`" in rec["action"]
