"""Which path a refused or failed Claude Code tool call concerned (QUEUE row 11: record what each refusal is about).

Parsing only: synthetic stream-json events, nothing is run."""
from __future__ import annotations

import json

import pytest

from repo_ai.mission.runtime import sanitize_events
from repo_ai.providers import adapters
from repo_ai.providers.acp import AcpResult


def _stream(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def _result(**extra) -> dict:
    return {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01, "num_turns": 1,
            "session_id": "s1", "result": "done", **extra}


def _tool_use(call_id: str, name: str, tool_input: object) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}}


def _tool_error(call_id: object, text: str) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "is_error": True, "content": text}]}}


def _denied(*inputs: tuple[str, object]) -> dict:
    return adapters.parse_event_stream("claude", _stream(_result(permission_denials=[
        {"tool_name": name, "tool_input": tool_input} for name, tool_input in inputs])))


def test_permission_denials_name_the_path_they_concerned():
    out = _denied(("Read", {"file_path": "/proc/self/environ"}), ("Read", {"file_path": "/proc/1/cmdline"}),
                  ("Glob", {"pattern": "**/*", "path": "/proc"}), ("Read", {"file_path": "src/app.py"}))
    assert out["denied_actions"] == ["Read", "Read", "Glob", "Read"]
    assert out["denied_targets"] == ["Read /proc/self/environ", "Read /proc/1/cmdline", "Glob /proc pattern **/*",
                                     "Read src/app.py"]


@pytest.mark.parametrize("path,expected", [
    ("/Users/someone/.local/share/repo-ai/claude-provider/.credentials.json", "<path>/.credentials.json"),
    ("/home/someone/.ssh/id_ed25519", "<path>/id_ed25519"),
    ("/proc/self/root/home/someone/.ssh/id_ed25519", "<path>/id_ed25519"),
    ("/proc/1/cwd/../../home/someone/x", "<path>/x"),
    ("/proc/self/root", "<path>/root"),
    ("/proc/self/cwd", "<path>/cwd"),
    ("//home/someone/notes", "<path>/notes"),
    ("/./Users/someone/notes", "<path>/notes"),
    ("/users/someone/notes", "<path>/notes"),
    ("../../../home/someone/.aws/credentials", "<path>/credentials"),
    ("C:/Users/someone/notes", "<path>/notes"),
    ("C:\\Users\\someone\\notes", "<path>/notes"),
    ("/opt/someone/project/main.py", "<path>/main.py"),
    ("~someone/.netrc", "<path>"),
    ("/home/someone", "<path>"),
    ("/home/someone/", "<path>"),
])
def test_only_relative_and_short_proc_paths_are_kept(path, expected):
    out = _denied(("Read", {"file_path": path}))
    assert out["denied_targets"] == [f"Read {expected}"]
    assert "someone" not in json.dumps(out["denied_targets"])


def test_grep_patterns_are_search_text_and_never_recorded():
    out = _denied(("Grep", {"pattern": "alice@example.com", "path": "src"}), ("Grep", {"pattern": "bob"}))
    assert out["denied_targets"] == ["Grep src", "Grep"]
    assert "alice" not in json.dumps(out) and "bob" not in json.dumps(out["denied_targets"])


def test_failed_tool_results_are_matched_to_their_call():
    out = adapters.parse_event_stream("claude", _stream(
        _tool_use("t1", "Read", {"file_path": "/proc/self/environ"}),
        _tool_error("t1", "File is outside the allowed working directories"),
        _tool_use("t2", "Read", {"file_path": "src/app.py"}),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}},
        _tool_use("t3", "Glob", {"pattern": "**/*", "path": "/proc/1"}),
        _tool_error("t3", "denied"),
        _tool_error("unknown-id", "denied"),
        _tool_error(7, "denied"),
        _result(),
    ))
    assert out["tool_error_targets"] == ["Read /proc/self/environ", "Glob /proc/1 pattern **/*",
                                         adapters.UNMATCHED_CALL, adapters.UNMATCHED_CALL]
    assert out["denied_targets"] == []
    assert out["terminal_observed"] is True


def test_a_call_dropped_by_the_capture_is_unmatched_not_named_tool():
    out = adapters.parse_event_stream("claude", _stream(
        {"type": "repo_ai_truncated", "bytes": 40000, "lines": 1},
        _tool_error("t9", "denied"),
        _result(),
    ))
    assert out["tool_error_targets"] == ["<unmatched>"]


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


@pytest.mark.parametrize("denials", [5, True, "Read", {"tool_name": "Read"}])
def test_malformed_permission_denials_never_break_the_parse(denials):
    out = adapters.parse_event_stream("claude", _stream(_result(permission_denials=denials)))
    assert out["terminal_observed"] is True
    assert out["denied_actions"] == [] and out["denied_targets"] == []


def test_malformed_denial_entries_are_recorded_without_their_repr():
    out = adapters.parse_event_stream("claude", _stream(
        _tool_use(["not", "a", "string"], "Read", {"file_path": "x"}),
        _tool_use("t2", "Read", "not a dict"),
        _tool_error("t2", "denied"),
        _result(permission_denials=[{"tool_name": {"nested": 1}, "tool_input": ["x"]}, "junk", None]),
    ))
    assert out["denied_actions"] == ["tool"] and out["denied_targets"] == ["tool"]
    assert out["tool_error_targets"] == ["Read"]


def test_agy_non_list_denied_actions_never_break_the_parse():
    line = {"type": "result", "status": "success", "denied_actions": 3, "response": "ok"}
    out = adapters.parse_event_stream("agy", _stream(line))
    assert out["denied_actions"] == []


def test_lists_and_the_call_map_are_bounded():
    many = [("Read", {"file_path": f"/proc/{i}/environ"}) for i in range(50)]
    assert len(_denied(*many)["denied_targets"]) == 32
    blocks = [{"type": "tool_use", "id": f"c{i}", "name": "Read", "input": {"file_path": f"f{i}.py"}}
              for i in range(4200)]
    out = adapters.parse_event_stream("claude", _stream({"type": "assistant", "message": {"content": blocks}},
                                                        _tool_error("c4150", "x"), _tool_error("c4095", "x"),
                                                        _result()))
    assert out["tool_error_targets"] == ["<unmatched>", "Read f4095.py"]  # the first 4096 calls are mapped


def test_other_providers_and_acp_report_empty_lists():
    codex = adapters.parse_event_stream("codex", _stream({"type": "turn.completed", "usage": {}}))
    assert codex["denied_targets"] == [] and codex["tool_error_targets"] == []
    acp = adapters.acp_events("opencode-acp", AcpResult(), cost_basis="test")
    assert acp["denied_targets"] == [] and acp["tool_error_targets"] == []


def test_mission_state_gets_this_checkouts_prefixes_replaced():
    events = {"denied_targets": ["Read work/x.py", 3], "tool_error_targets": ["Read work/y.py"],
              "errors": ["failed in work/z"], "summary": "edited work/a.py", "tool_calls": ["work/kept"]}
    out = sanitize_events(events, {"work": "<workspace>"})
    assert out["denied_targets"] == ["Read <workspace>/x.py"]
    assert out["tool_error_targets"] == ["Read <workspace>/y.py"]
    assert out["errors"] == ["failed in <workspace>/z"] and out["summary"] == "edited <workspace>/a.py"
    assert out["tool_calls"] == ["work/kept"]
