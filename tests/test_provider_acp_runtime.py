"""`opencode-acp` end to end with a scripted ACP agent in the host sandbox: the agent's own edits are judged by
validate_workspace_edits, failures never pass, and a mission reaches PASS only for a correct edit."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from repo_ai.mission import runtime
from repo_ai.providers import run_provider, validate_workspace_edits
from test_mission_runtime import bug as bug_fixture
from test_provider_opencode_acp import fake_acp_cli

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the ACP client is POSIX-only, as missions are")

FIXED = "def charge(amount, retries):\n    return amount\n"


@pytest.fixture
def bug(tmp_path: Path) -> Path:
    return bug_fixture.__wrapped__(tmp_path)


def _dirs(tmp_path: Path) -> tuple[Path, Path, set[str]]:
    """A repository and an isolated copy of it as the candidate workspace, as a mission materializes it."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "charge.py").write_text("def charge(amount, retries):\n    return amount * (retries + 1)\n")
    (root / "other.py").write_text("X = 1\n")
    (root / "test_charge.py").write_text("from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n")
    ws = tmp_path / "workspace"
    subprocess.run(["cp", "-R", str(root), str(ws)], check=True)
    return root, ws, {"charge.py", "other.py", "test_charge.py"}


def _run(tmp_path, ws, root, script, *, write_paths=("charge.py",), timeout=20.0):
    exe = fake_acp_cli(tmp_path, script)
    return run_provider("opencode-acp", root, ws, "Fix charge.py", write_paths=list(write_paths), executable=exe,
                        timeout=timeout, simulated=True)


def test_an_edit_the_agent_makes_itself_is_validated_like_any_provider_edit(tmp_path):
    root, ws, tracked = _dirs(tmp_path)
    res = _run(tmp_path, ws, root, [
        {"tool": {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "edit", "kind": "edit", "status": "pending"}},
        {"edit": "charge.py", "content": FIXED},
        {"tool": {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"}},
        {"say": "Fixed charge()."}])
    assert res["stage"] == "SIMULATED" and res["reasons"] == [], res
    assert res["events"]["tool_calls"] == ["edit"] and res["events"]["report"] == "Fixed charge()."
    assert res["cost_usd"] == 0.0 and res["cost_status"] == "OBSERVED"
    assert (ws / "charge.py").read_text() == FIXED
    assert validate_workspace_edits(root, ws, ["charge.py"], {"test_charge.py"}, tracked) == []


def test_an_edit_outside_the_write_paths_is_blocked_by_validation_not_by_acp(tmp_path):
    root, ws, tracked = _dirs(tmp_path)
    res = _run(tmp_path, ws, root, [{"edit": "charge.py", "content": FIXED}, {"edit": "other.py", "content": "X = 2\n"},
                                    {"edit": "test_charge.py", "content": "def test_retry():\n    assert True\n"}])
    # the agent's account of its turn is clean: ACP never saw these edits (OpenCode edits files itself)
    assert res["stage"] == "SIMULATED" and res["events"]["acp_writes"] == []
    problems = validate_workspace_edits(root, ws, ["charge.py"], {"test_charge.py"}, tracked)
    assert "provider modified unapproved path: other.py" in problems
    assert "provider modified unapproved path: test_charge.py" in problems
    assert any("frozen test" in p for p in problems)


def test_a_write_outside_the_workspace_is_stopped_by_the_os_sandbox(tmp_path):
    root, ws, _ = _dirs(tmp_path)
    escape = tmp_path / "escaped.py"
    res = _run(tmp_path, ws, root, [{"edit": str(escape), "content": "pwned"}])
    assert not escape.exists()
    assert res["stage"] == "FAILED" and any(r.startswith("ACP: ") for r in res["reasons"]), res["reasons"]


def test_a_write_request_off_the_list_is_refused_and_fails_the_run(tmp_path):
    root, ws, _ = _dirs(tmp_path)
    res = _run(tmp_path, ws, root, [{"method": "fs/write_text_file",
                                     "params": {"path": str(ws / "other.py"), "content": "X = 2\n"}}])
    assert (ws / "other.py").read_text() == "X = 1\n"
    assert res["stage"] == "FAILED" and any("ACP client refused" in r for r in res["reasons"])


def test_a_timeout_is_failed_and_bounded(tmp_path):
    root, ws, _ = _dirs(tmp_path)
    started = time.monotonic()
    res = _run(tmp_path, ws, root, [{"sleep": 60}], timeout=1.5)
    assert time.monotonic() - started < 20
    assert res["stage"] == "FAILED" and res["capture_status"] == "timeout" and res["events"]["timed_out"]
    assert any("timeout" in r for r in res["reasons"])


@pytest.mark.parametrize("script,needle", [
    ([{"exit": 3}], "ACP: the agent exited"),
    ([{"stop": "refusal"}], "stop reason 'refusal'"),
])
def test_a_dead_or_refusing_agent_is_failed(tmp_path, script, needle):
    root, ws, _ = _dirs(tmp_path)
    res = _run(tmp_path, ws, root, script)
    assert res["stage"] == "FAILED" and res["returncode"] == 1
    assert any(needle in r for r in res["reasons"]), res["reasons"]


def test_an_agent_not_invoked_as_opencode_acp_never_completes(tmp_path):
    """The fake refuses to start unless its arguments are exactly `acp`: this run passing proves the argv."""
    root, ws, _ = _dirs(tmp_path)
    assert _run(tmp_path, ws, root, [{"say": "ok"}])["stage"] == "SIMULATED"
    exe = fake_acp_cli(tmp_path, [{"say": "ok"}])
    from repo_ai.providers.acp import AcpClient
    wrong = AcpClient([str(exe), "run"], ws, allowed_writes=[]).run("x", 10)
    assert wrong.problems and not wrong.stop_reason


def test_a_mission_with_opencode_acp_passes_for_a_correct_edit(bug, tmp_path):
    cli = fake_acp_cli(tmp_path, [{"edit": "charge.py", "content": FIXED}, {"say": "done"}])
    planned = runtime.plan(bug, "Fix duplicate charge", agent="opencode-acp", write_paths=["charge.py"],
                           execute_local=True)
    result = runtime.execute(bug, planned, None, provider_executable=cli)
    assert result["effective_verdict"] == "PASS", result["passport"]["negative"]
    assert result["provider"]["name"] == "opencode-acp"
    assert result["provider"]["events"]["event_format"] == "acp-jsonrpc"


def test_a_mission_with_opencode_acp_blocks_an_edit_to_the_tests(bug, tmp_path):
    cli = fake_acp_cli(tmp_path, [{"edit": "test_charge.py", "content": "def test_retry():\n    assert True\n"}])
    planned = runtime.plan(bug, "Fix duplicate charge", agent="opencode-acp", write_paths=["charge.py"],
                           execute_local=True)
    result = runtime.execute(bug, planned, None, provider_executable=cli)
    assert result["effective_verdict"] != "PASS"
    assert any("unapproved" in r or "frozen test" in r for r in result["passport"]["negative"])
