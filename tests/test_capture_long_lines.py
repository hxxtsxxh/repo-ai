"""journey-live-v1 (C21, more-itertools): one Claude Code Read of a 150 KB source file put a single event line over the
capture limit, so the live run was killed (-9) and its cost lost. A JSONL capture now replaces an over-long line by a
placeholder and keeps going; the overall limit still bounds memory."""
from __future__ import annotations

import json
import sys

from repo_ai.providers import adapters
from repo_ai.providers.discovery import _capture

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
