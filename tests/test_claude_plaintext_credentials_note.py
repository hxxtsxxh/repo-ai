"""`agents setup claude` notes a plaintext credentials file in repo-ai's dedicated Claude login on macOS.

Observed 2026-11-04: a revoked login failing inside a run made Claude Code write `.credentials.json` into the
dedicated config directory (the login before lived only in the Keychain). It is reported, never read or removed,
and never makes the login unusable."""
from __future__ import annotations

import os

from repo_ai.providers import claude_auth


def test_a_plaintext_credentials_file_is_noted_on_macos_without_being_read(tmp_path, monkeypatch):
    cred = tmp_path / ".credentials.json"
    cred.write_text("not json and never read")
    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda f, *a, **k: opened.append(str(f)) or real_open(f, *a, **k))
    note = claude_auth.plaintext_credentials_note(tmp_path, platform="darwin")
    assert note and ".credentials.json" in note and "Keychain" in note and "delete" in note
    assert str(cred) not in opened


def test_no_note_elsewhere_or_without_a_regular_file(tmp_path):
    assert claude_auth.plaintext_credentials_note(tmp_path, platform="darwin") is None
    (tmp_path / ".credentials.json").write_text("x")
    assert claude_auth.plaintext_credentials_note(tmp_path, platform="linux") is None
    other = tmp_path / "other"
    other.mkdir()
    os.symlink(tmp_path / ".credentials.json", other / ".credentials.json")
    assert claude_auth.plaintext_credentials_note(other, platform="darwin") is None


def test_the_note_never_makes_the_plan_unusable(tmp_path, monkeypatch):
    cfg = tmp_path / "claude-provider"
    cfg.mkdir()
    (cfg / ".credentials.json").write_text("x")
    monkeypatch.setattr(claude_auth.sys, "platform", "darwin")
    plan = claude_auth.plan({claude_auth.CONFIG_DIR_ENV: str(cfg), "USER": "someone"})
    assert plan.mode == "dedicated_config" and plan.notes and not plan.problems and plan.usable
    assert plan.to_json()["notes"] == list(plan.notes)
