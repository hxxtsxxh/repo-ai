"""journey-live-v1 (C21, more-itertools): one Claude Code Read of a 150 KB source file put a single event line over the
capture limit, so the live run was killed (-9) and its cost lost. A JSONL capture now replaces an over-long line by a
placeholder and keeps going; the overall limit still bounds memory."""
from __future__ import annotations

import json
import sys

import pytest

from repo_ai.providers import adapters
from repo_ai.providers.discovery import _capture

# live provider runs are POSIX-only (repo-ai refuses them on Windows); the child here also needs a POSIX environment
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="live provider capture is POSIX-only")

SCRIPT = ("import json, sys\n"
          "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's'}))\n"
          "print(json.dumps({'type': 'user', 'session_id': 's', 'content': 'x' * 100000}))\n"
          "print(json.dumps({'type': 'result', 'session_id': 's', 'total_cost_usd': 0.01, 'is_error': False}))\n")


def test_an_over_long_event_line_becomes_a_placeholder_and_the_run_completes(tmp_path):
    res = _capture([sys.executable, "-c", SCRIPT], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=65_536, separate_stderr=True, max_line=32_768)
    assert res.status == "complete" and res.returncode == 0, res.status
    lines = [json.loads(x) for x in res.output.decode().splitlines()]
    assert [x["type"] for x in lines] == ["system", "repo_ai_truncated", "result"]
    assert lines[1]["bytes"] > 100_000


def test_without_a_line_cap_the_same_stream_still_stops_at_the_limit(tmp_path):
    res = _capture([sys.executable, "-c", SCRIPT], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=65_536, separate_stderr=True)
    assert res.status == "output_limit"


def test_the_event_parser_counts_truncated_lines_and_still_sees_the_terminal_event(tmp_path):
    res = _capture([sys.executable, "-c", SCRIPT], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=65_536, separate_stderr=True, max_line=32_768)
    ev = adapters.parse_event_stream("claude", res.output)
    assert ev["truncated_events"] == 1 and ev["terminal_observed"] is True and ev["protocol_valid"] is True, ev


def test_a_long_terminal_result_line_is_kept_whole_with_its_cost(tmp_path):
    """Review of #125: a terminal event padded past the line cap must not lose the cost or the terminal status."""
    script = ("import json\n"
              "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's'}))\n"
              "print(json.dumps({'type': 'result', 'session_id': 's', 'total_cost_usd': 0.5, 'is_error': True,"
              " 'permission_denials': [{'tool_name': 'Write', 'tool_input': {'content': 'x' * 40000}}]}))\n")
    res = _capture([sys.executable, "-c", script], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=262_144, separate_stderr=True, max_line=32_768)
    ev = adapters.parse_event_stream("claude", res.output)
    assert res.status == "complete" and ev["terminal_observed"] and ev["truncated_events"] == 0
    assert ev["cost_usd"] == 0.5


def test_an_endless_run_of_dropped_lines_stops_at_the_read_cap(tmp_path):
    script = "import sys\nfor _ in range(5000):\n    sys.stdout.write('{\"type\":\"user\",\"x\":\"' + 'y' * 2000 + '\"}\\n')\n"
    res = _capture([sys.executable, "-c", script], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=4096, separate_stderr=True, max_line=1024)
    assert res.status == "output_limit"


def test_many_medium_tool_results_do_not_crowd_out_the_terminal_event(tmp_path):
    """Release review of 0.12.2 (H1): fifteen 20 KB tool results each fit the line cap but together filled the total
    and killed the run before its result event. Near the limit they now become placeholders."""
    script = ("import json\n"
              "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's'}))\n"
              "for i in range(15):\n"
              "    print(json.dumps({'type': 'user', 'session_id': 's', 'content': 'x' * 20000}))\n"
              "print(json.dumps({'type': 'result', 'session_id': 's', 'total_cost_usd': 0.07, 'is_error': False}))\n")
    res = _capture([sys.executable, "-c", script], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=262_144, separate_stderr=True, max_line=32_768)
    ev = adapters.parse_event_stream("claude", res.output)
    assert res.status == "complete", res.status
    assert ev["terminal_observed"] and ev["cost_usd"] == 0.07 and ev["truncated_events"] >= 1, ev


def test_a_large_init_event_is_kept_whole(tmp_path):
    script = ("import json\n"
              "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's', 'tools': ['T' * 40000]}))\n"
              "print(json.dumps({'type': 'result', 'session_id': 's', 'total_cost_usd': 0.01, 'is_error': False}))\n")
    res = _capture([sys.executable, "-c", script], tmp_path, {"PATH": "/usr/bin:/bin"}, timeout=20, max_timeout=30,
                   output_limit=262_144, separate_stderr=True, max_line=32_768)
    assert b'"subtype": "init"' in res.output and b"repo_ai_truncated" not in res.output
