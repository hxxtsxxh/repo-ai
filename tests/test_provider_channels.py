"""Offline subprocess regressions: diagnostics never become provider events."""
import os
import sys
import time
from pathlib import Path

import pytest

from repo_ai.providers.discovery import _capture, _probe_env
from repo_ai.providers.adapters import parse_event_stream


def capture(tmp_path: Path, code: str, **kw):
    return _capture([sys.executable, '-I', '-c', code], tmp_path, _probe_env(tmp_path), **kw)


def test_split_codex_diagnostic_and_message(tmp_path):
    events = b'{"type":"item.completed","item":{"type":"agent_message","text":"Fixed caf\\u00e9"}}\n{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":2}}\n'
    result = capture(tmp_path, f'import os;os.write(1,{events!r});os.write(2,b"Reading additional input from stdin...\\n")', separate_stderr=True)
    assert result.status == 'complete'
    assert result.stderr == b'Reading additional input from stdin...\n'
    parsed = parse_event_stream('codex', result.output)
    assert parsed['valid_jsonl']
    assert parsed['summary'] == 'Fixed café'
    assert parsed['cost_status'] == 'UNKNOWN'
    assert not parsed['cost_reported']


def test_stderr_cannot_forge_events(tmp_path):
    result = capture(tmp_path, 'import os;os.write(2,b\'{"type":"turn.completed"}\\n\')', separate_stderr=True)
    assert not parse_event_stream('codex', result.output)['valid_jsonl']
    assert result.stderr


def test_probe_still_merges_by_default(tmp_path):
    result = capture(tmp_path, 'import os;os.write(1,b"out");os.write(2,b"err")')
    assert result.output == b'outerr'
    assert result.stderr == b''


@pytest.mark.parametrize('fd', [1, 2])
def test_each_pipe_is_bounded(tmp_path, fd):
    result = capture(tmp_path, f'import os;os.write({fd},b"x"*1000000)', separate_stderr=True, output_limit=256)
    assert result.status == 'output_limit'
    assert len(result.output) <= 256
    assert len(result.stderr) <= 256


def test_both_large_pipes_drain_without_deadlock(tmp_path):
    result = capture(tmp_path, 'import os\nfor i in range(100):\n os.write(1,b"a"*512)\n os.write(2,b"b"*512)', separate_stderr=True)
    assert result.status == 'complete'
    assert result.output == b'a' * 51200
    assert result.stderr == b'b' * 51200


def test_split_timeout_retains_both_channels(tmp_path):
    result = capture(tmp_path, 'import os,time;os.write(1,b"out");os.write(2,b"err");time.sleep(30)', separate_stderr=True, timeout=.2)
    assert result.status == 'timeout'
    assert result.returncode != 0
    assert result.output == b'out'
    assert result.stderr == b'err'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX process groups')
def test_parent_exit_kills_child_holding_stderr(tmp_path):
    start = time.monotonic()
    result = capture(tmp_path, 'import subprocess,sys;subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],stdout=subprocess.DEVNULL)', separate_stderr=True, timeout=2)
    assert result.status == 'complete'
    assert time.monotonic() - start < 2


@pytest.mark.parametrize('stream', [b'bad json', b'[]', b''])
def test_bad_event_stream(stream):
    assert not parse_event_stream('codex', stream)['valid_jsonl']


def test_missing_terminal_is_separate_from_json_validity():
    parsed = parse_event_stream('codex', b'{"type":"thread.started","thread_id":"a"}\n')
    assert parsed['valid_jsonl']
    assert not parsed['terminal_observed']
    assert not parsed['protocol_valid']


def test_conflicting_run_identity_is_not_valid_protocol():
    parsed = parse_event_stream('codex', b'{"type":"thread.started","thread_id":"a"}\n{"type":"turn.completed","thread_id":"b"}\n')
    assert not parsed['protocol_valid']


def test_unicode_replacement_does_not_validate_corrupt_protocol():
    parsed = parse_event_stream('codex', b'{"type":"turn.completed","summary":"\xff"}\n')
    assert not parsed['protocol_valid']


@pytest.mark.parametrize('cost', ['NaN', 'Infinity', '-1', 'true'])
def test_invalid_cost_is_not_observed(cost):
    parsed = parse_event_stream('bob', ('{"type":"result","cost_usd":' + cost + '}').encode())
    assert parsed['cost_status'] == 'UNKNOWN'


def test_rate_limit_and_exit_zero_cannot_be_success(tmp_path, monkeypatch):
    from repo_ai.providers import adapters as a
    from repo_ai.providers.discovery import ProbeResult
    root = tmp_path / 'repo'
    ws = tmp_path / 'workspace'
    root.mkdir()
    ws.mkdir()
    monkeypatch.setattr(a, '_execution_sandbox_prefix', lambda *args, **kw: [])
    monkeypatch.setattr(a, '_seed_live_provider_auth', lambda *args: None)
    def fake_capture(*args, **kw):
        assert kw['separate_stderr'] is True
        return ProbeResult(0, 'complete', b'{"type":"turn.completed"}\n', b'usage limit reached')
    monkeypatch.setattr(a, '_capture', fake_capture)
    result = a.run_provider('codex', root, ws, 'test', write_paths=[], executable=sys.executable,
                            simulated=False, allow_live=True)
    assert result['stage'] == 'FAILED'
    assert result['rate_limited']
    assert result['events']['valid_jsonl']
    assert result['cost_status'] == 'UNKNOWN'
