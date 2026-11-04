"""Which path a refused or failed Claude Code tool call concerned (QUEUE row 11: record what each refusal is about).

Parsing only: synthetic stream-json events, nothing is run."""
from __future__ import annotations

import json

from repo_ai.providers import adapters


def _stream(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def _result(**extra) -> dict:
    return {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01, "num_turns": 1,
            "session_id": "s1", "result": "done", **extra}


def _tool_use(call_id: str, name: str, tool_input: dict) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}}


def _tool_error(call_id: str, text: str) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "is_error": True, "content": text}]}}


def test_permission_denials_name_the_path_they_concerned():
    out = adapters.parse_event_stream("claude", _stream(_result(permission_denials=[
        {"tool_name": "Read", "tool_use_id": "t1", "tool_input": {"file_path": "/proc/self/environ"}},
        {"tool_name": "Grep", "tool_use_id": "t2", "tool_input": {"pattern": "TOKEN", "path": "/proc"}},
    ])))
    assert out["denied_actions"] == ["Read", "Grep"]
    assert out["denied_targets"] == ["Read /proc/self/environ", "Grep TOKEN in /proc"]


def test_home_paths_are_scrubbed_to_the_file_name():
    out = adapters.parse_event_stream("claude", _stream(_result(permission_denials=[
        {"tool_name": "Read", "tool_input": {"file_path": "/Users/someone/.local/share/repo-ai/claude-provider/"
                                                          ".credentials.json"}},
        {"tool_name": "Read", "tool_input": {"file_path": "/home/someone/.ssh/id_ed25519"}},
    ])))
    assert out["denied_targets"] == ["Read <path>/.credentials.json", "Read <path>/id_ed25519"]
    assert "someone" not in json.dumps(out)


def test_failed_tool_results_are_matched_to_their_call():
    out = adapters.parse_event_stream("claude", _stream(
        _tool_use("t1", "Read", {"file_path": "/proc/self/environ"}),
        _tool_error("t1", "File is outside the allowed working directories"),
        _tool_use("t2", "Read", {"file_path": "src/app.py"}),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}},
        _tool_use("t3", "Glob", {"pattern": "**/*", "path": "/proc/1"}),
        _tool_error("t3", "denied"),
        _tool_error("unknown-id", "denied"),
        _result(),
    ))
    assert out["tool_error_targets"] == ["Read /proc/self/environ", "Glob **/* in /proc/1", "tool"]
    assert out["denied_targets"] == []
    assert out["terminal_observed"] is True


def test_the_record_never_carries_tool_content_or_results():
    out = adapters.parse_event_stream("claude", _stream(
        _tool_use("t1", "Write", {"file_path": "notes.txt", "content": "private body text"}),
        _tool_error("t1", "the error message body"),
        _result(permission_denials=[{"tool_name": "Edit", "tool_input": {"file_path": "a.py", "old_string": "x1",
                                                                          "new_string": "secret body"}}]),
    ))
    assert out["tool_error_targets"] == ["Write notes.txt"]
    assert out["denied_targets"] == ["Edit a.py"]
    text = json.dumps(out)
    assert "private body text" not in text and "secret body" not in text and "error message body" not in text


def test_lists_are_bounded_and_other_providers_report_none():
    many = [{"tool_name": "Read", "tool_input": {"file_path": f"/proc/{i}/environ"}} for i in range(50)]
    out = adapters.parse_event_stream("claude", _stream(_result(permission_denials=many)))
    assert len(out["denied_targets"]) == 32
    codex = adapters.parse_event_stream("codex", _stream({"type": "turn.completed", "usage": {}}))
    assert codex["denied_targets"] == [] and codex["tool_error_targets"] == []
