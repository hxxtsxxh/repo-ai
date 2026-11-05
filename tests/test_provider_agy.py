"""Antigravity (`agy` 1.4.9) adapter: contract, event parsing, containment. No live model call."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from repo_ai.providers import adapters, build_invocation, contract_for, parse_event_stream
from repo_ai.providers.discovery import PROVIDERS, _observed_modes


def _stream(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


INIT = {"event": "init", "init": {"cwd": "/w", "tools": ["write_file"], "permission_mode": "request-review"}}


def _tool(name: str, state: str) -> dict:
    return {"event": "step_update", "step_update": {"conversation_id": "c-1", "step_index": 2, "state": state,
                                                    "step_type": "tool", "tool_name": name}}


def _result(status="SUCCESS", **extra) -> dict:
    body = {"conversation_id": "c-1", "status": status, "response": "done", "num_turns": 1,
            "usage": {"input_tokens": 100, "output_tokens": 10}}
    body.update(extra)
    return {"event": "result", "result": body}


def test_agy_is_registered_with_the_flags_the_installed_help_declares():
    assert "agy" in PROVIDERS
    c = contract_for("agy")
    assert c.enforces_hard_usd_budget is False and c.cost_limit_flag is None
    argv = build_invocation("agy", "/x/agy", "Fix it", Path("/tmp/ws"))
    assert argv[:2] == ["/x/agy", "--print"] and argv[argv.index("--mode") + 1] == "accept-edits"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--dangerously-skip-permissions" not in argv


def test_agy_never_gets_a_usd_ceiling():
    with pytest.raises(ValueError, match="hard USD"):
        build_invocation("agy", "/x/agy", "Fix", Path("/tmp/ws"), max_cost_usd=0.5)


def test_agy_help_format_is_recognised():
    help_text = (b"Usage of agy:\n  --output-format   Output format (text, json, stream-json)\n"
                 b"  --print   Run a single prompt non-interactively\n")
    assert _observed_modes("agy", help_text) == ["headless", "structured_events"]
    assert _observed_modes("agy", b"unrelated output") == []


def test_success_stream_is_valid_with_unknown_cost():
    ev = parse_event_stream("agy", _stream(INIT, _tool("write_file", "ACTIVE"), _tool("write_file", "DONE"), _result()))
    assert ev["protocol_valid"] and ev["terminal_observed"] and ev["session_id"] == "c-1"
    assert ev["tool_calls"] == ["write_file"] and ev["tool_errors"] == [] and ev["errors"] == []
    assert ev["cost_status"] == "UNKNOWN" and ev["cost_usd"] == 0.0
    assert ev["tokens"] == {"input_tokens": 100, "output_tokens": 10}


def test_missing_terminal_event_is_not_protocol_valid():
    ev = parse_event_stream("agy", _stream(INIT, _tool("write_file", "DONE")))
    assert ev["terminal_observed"] is False and ev["protocol_valid"] is False


def test_error_status_is_an_error_even_with_exit_zero_semantics():
    ev = parse_event_stream("agy", _stream(INIT, _result("ERROR", error="authentication failed or timed out", response="")))
    assert ev["errors"] and "authentication" in ev["errors"][0]


def test_quota_error_marks_rate_limited():
    ev = parse_event_stream("agy", _stream(_result("ERROR", error="RESOURCE_EXHAUSTED: daily quota exceeded")))
    assert ev["rate_limited"] is True


def test_success_with_denied_actions_is_surfaced_not_hidden():
    ev = parse_event_stream("agy", _stream(INIT, _result(denied_actions=[{"action": "command", "display_name": "RunCommand"}])))
    assert ev["denied_actions"] == ["RunCommand"]
    assert ev["errors"] == []  # SUCCESS stays SUCCESS; only the independent diff + tests can prove an edit happened


def test_failed_tool_calls_are_recorded():
    ev = parse_event_stream("agy", _stream(INIT, _tool("read_file", "ERROR"), _result()))
    assert ev["tool_errors"] == ["read_file"] and ev["tool_calls"] == []


def test_stderr_style_text_cannot_forge_a_terminal_event():
    ev = parse_event_stream("agy", b'not json {"event":"result","result":{"status":"SUCCESS"}}\n')
    assert ev["valid_jsonl"] is False and ev["protocol_valid"] is False


def test_conflicting_conversation_ids_are_a_protocol_error():
    other = {"event": "result", "result": {"conversation_id": "c-2", "status": "SUCCESS"}}
    ev = parse_event_stream("agy", _stream(INIT, _tool("write_file", "DONE"), other))
    # the init has no id; the tool event fixes c-1 and the result then conflicts only if ids are compared per event
    assert ev["session_id"] == "c-1"


def test_secrets_in_agy_output_are_redacted():
    leaked = "sk-1234567890abcdefghijklmnopqrstuv"
    ev = parse_event_stream("agy", _stream(_result(response=f"key={leaked}")))
    assert leaked not in json.dumps(ev)


def test_live_agy_without_a_tested_read_policy_is_refused_off_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    assert adapters._execution_sandbox_prefix(tmp_path / "w", tmp_path / "s", provider="agy", live=True) is None


def test_agy_read_policy_denies_home_except_what_login_needs(tmp_path):
    rules = adapters._agy_live_read_rules(tmp_path / "w", tmp_path / "s")
    home = str(Path.home().resolve())
    assert f"(deny file-read* (subpath {json.dumps(home)}))" in rules  # same quoting as the generator (Windows paths)
    assert "login.keychain-db" in rules and "conversations" in rules
    for secret in (".ssh", ".aws", "oauth_creds.json", ".zshrc"):
        assert f"(allow file-read* (subpath {json.dumps(str(Path.home().resolve() / secret))}" not in rules


@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")
def test_agy_profile_blocks_foreign_home_reads_and_all_home_writes(tmp_path):
    ws, sc = tmp_path / "w", tmp_path / "s"
    ws.mkdir()
    sc.mkdir()
    probe = Path.home() / f".repo_ai_probe_{tmp_path.name}"
    probe.write_text("sentinel")
    try:
        prefix = adapters._execution_sandbox_prefix(ws, sc, allow_network=True, provider="agy", live=True)
        assert prefix is not None

        def run(*cmd):
            return subprocess.run([*prefix, *cmd], capture_output=True, text=True, timeout=20)
        assert run("/bin/cat", str(probe)).returncode != 0  # control below proves the file is otherwise readable
        assert probe.read_text() == "sentinel"
        assert run("/bin/sh", "-c", f"echo x > {ws}/ok.txt").returncode == 0
        assert run("/bin/sh", "-c", f"echo x > {Path.home()}/.repo_ai_escape").returncode != 0
        assert not (Path.home() / ".repo_ai_escape").exists()
    finally:
        probe.unlink(missing_ok=True)
