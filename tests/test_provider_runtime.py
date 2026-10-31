"""Contract and sandbox tests for the Universal Provider Runtime (Slice B)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import run_cli
from repo_ai.mission import runtime
from repo_ai.providers import (
    PROVIDER_CONTRACTS,
    STAGES,
    build_invocation,
    contract_for,
    discover,
    parse_event_stream,
    run_provider,
    validate_workspace_edits,
)
from test_mission_runtime import bug as bug_fixture

pytestmark = pytest.mark.usefixtures('claude_fake_login')


@pytest.fixture
def bug(tmp_path: Path) -> Path:
    return bug_fixture.__wrapped__(tmp_path)


def _make_fake_cli(tmp_path: Path, provider: str, body: str) -> Path:
    cli_dir = tmp_path / "fake_bins"
    cli_dir.mkdir(exist_ok=True)
    script = cli_dir / f"fake-{provider}"
    script.write_text(f"#!{sys.executable} -I\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def test_provider_contracts_and_lifecycle_stages_are_complete(tmp_path: Path) -> None:
    assert STAGES == (
        "NOT_INSTALLED",
        "DISCOVERED",
        "PROBED",
        "READY",
        "SIMULATED",
        "BLOCKED",
        "FAILED",
        "VERIFIED",
    )
    assert set(PROVIDER_CONTRACTS) == {"codex", "claude", "gemini", "bob", "agy", "opencode", "opencode-acp"}
    assert contract_for("opencode").enforces_hard_usd_budget is False
    assert contract_for("claude").enforces_hard_usd_budget is True
    assert contract_for("bob").enforces_hard_usd_budget is True
    assert contract_for("codex").enforces_hard_usd_budget is False
    assert contract_for("gemini").enforces_hard_usd_budget is False

    profiles = discover(tmp_path)
    for p in profiles:
        assert p["stage"] in STAGES
        assert p["contract"]["provider"] == p["provider"]


@pytest.mark.parametrize("provider", ["codex", "claude", "gemini", "bob"])
def test_build_invocation_and_budget_enforcement(tmp_path: Path, provider: str) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    argv = build_invocation(provider, f"/usr/local/bin/{provider}", "Fix token=sk-1234567890abcdefghijklmnop", ws)
    assert argv[0] == f"/usr/local/bin/{provider}"
    assert "sk-1234567890abcdefghijklmnop" not in " ".join(argv)

    if provider in {"claude", "bob"}:
        argv_budget = build_invocation(
            provider, f"/usr/local/bin/{provider}", "Fix bug", ws, max_cost_usd=0.25, simulated=False
        )
        flag = "--max-budget-usd" if provider == "claude" else "--max-cost"
        assert flag in argv_budget
        assert "0.2500" in argv_budget
    else:
        with pytest.raises(ValueError, match="does not enforce a hard USD CLI budget"):
            build_invocation(
                provider, f"/usr/local/bin/{provider}", "Fix bug", ws, max_cost_usd=0.25, simulated=False
            )


@pytest.mark.parametrize("provider", ["codex", "claude", "gemini", "bob"])
def test_parse_event_stream_redacts_and_aggregates(provider: str) -> None:
    stream = (
        json.dumps({"type": "init", "session_id": "sess-123", "tool": "edit_file"}) + "\n"
        + json.dumps({
            "type": "result",
            "usage": {"input_tokens": 120, "output_tokens": 45},
            "cost_usd": 0.0,
            "summary": "Repaired charge.py; stripped key=sk-1234567890abcdefghijklmnop",
        }) + "\n"
    ).encode("utf-8")
    parsed = parse_event_stream(provider, stream)
    assert parsed["valid_jsonl"] is True
    assert parsed["events_count"] == 2
    assert parsed["session_id"] == "sess-123"
    assert parsed["tokens"] == {"input_tokens": 120, "output_tokens": 45}
    assert parsed["tool_calls"] == ["edit_file"]
    assert "sk-1234567890abcdefghijklmnop" not in json.dumps(parsed)

    bad = parse_event_stream(provider, b"not json at all\n")
    assert bad["valid_jsonl"] is False


@pytest.mark.parametrize("provider", ["codex", "claude", "gemini", "bob"])
def test_run_provider_simulated_contract_and_guards(tmp_path: Path, provider: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()
    script = _make_fake_cli(
        tmp_path,
        provider,
        (
            "import json, os, pathlib\n"
            "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
            "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
            "print(json.dumps({'type': 'result', 'session_id': 's1', 'usage': {'input_tokens': 10, 'output_tokens': 5}, 'cost_usd': 0.0, 'summary': 'fixed'}))\n"
        ),
    )

    with pytest.raises(ValueError, match="live provider execution is blocked"):
        run_provider(provider, root, ws, "Fix charge.py", write_paths=["charge.py"], executable=script, simulated=False)

    res = run_provider(provider, root, ws, "Fix charge.py", write_paths=["charge.py"], executable=script, simulated=True)
    assert res["stage"] == "SIMULATED", res
    assert res["simulated"] is True
    assert res["events"]["valid_jsonl"] is True
    assert (ws / "charge.py").read_text().endswith("return amount\n")

    # Repository-owned executable is blocked
    repo_exe = root / provider
    repo_exe.write_text("#!/bin/sh\necho '{}'\n")
    repo_exe.chmod(0o755)
    blocked = run_provider(provider, root, ws, "Fix", write_paths=["charge.py"], executable=repo_exe, simulated=True)
    assert blocked["stage"] == "BLOCKED"


def test_provider_adapter_end_to_end_mission_execution_and_scope_violation(bug: Path, tmp_path: Path) -> None:
    good_cli = _make_fake_cli(
        tmp_path,
        "claude",
        (
            "import json, os, pathlib\n"
            "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
            "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
            "print(json.dumps({'type': 'result', 'session_id': 'claude-sim', 'cost_usd': 0.0, 'summary': 'repaired charge.py'}))\n"
        ),
    )
    proc = run_cli(
        bug,
        "do",
        "Repair duplicate charge in charge.py",
        "--agent",
        "claude",
        "--provider-executable",
        str(good_cli),
        "--allow-write",
        "charge.py",
        "--run",
        "--json",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["effective_verdict"] == "PASS"
    assert data["provider"]["name"] == "claude"
    assert data["provider"]["simulated"] is True
    assert data["provider"]["stage"] == "VERIFIED"
    assert "return amount * (retries + 1)" in (bug / "charge.py").read_text()

    # Provider attempting to modify frozen test file is rejected
    bad_cli = _make_fake_cli(
        tmp_path,
        "codex",
        (
            "import json, os, pathlib\n"
            "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
            "(ws / 'test_charge.py').write_text('def test_retry():\\n    assert True\\n')\n"
            "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"
        ),
    )
    planned = runtime.plan(bug, "Repair charge.py", agent="codex", write_paths=["charge.py"], execute_local=True)
    bad_res = runtime.execute(bug, planned, None, provider_executable=bad_cli)
    assert bad_res["effective_verdict"] != "PASS"
    assert bad_res["provider"]["stage"] in {"BLOCKED", "FAILED"}
    assert any("unapproved" in r or "frozen test" in r for r in bad_res["passport"]["negative"])
    assert validate_workspace_edits(bug, bug, ["charge.py"], {"test_charge.py"}, {"charge.py", "test_charge.py"}) == [
        "candidate workspace is inside root"
    ]


def test_provider_timeout_caps_simulated_short_and_live_long():
    from repo_ai.providers.adapters import LIVE_TIMEOUT_CAP, SIMULATED_TIMEOUT_CAP, provider_timeout
    assert provider_timeout(600, True) == SIMULATED_TIMEOUT_CAP
    assert provider_timeout(600, False) == 600
    assert provider_timeout(10_000, False) == LIVE_TIMEOUT_CAP
    assert provider_timeout(0, False) == 0.05


def test_capture_accepts_live_sized_timeout_only_with_explicit_ceiling(tmp_path):
    import sys

    from repo_ai.providers.discovery import _capture
    argv = [sys.executable, "-c", "print(1)"]
    with pytest.raises(ValueError):
        _capture(argv, tmp_path, {}, timeout=120.0)
    assert _capture(argv, tmp_path, {}, timeout=120.0, max_timeout=900.0).returncode == 0


_SLOW_CLI = (
    "import json, os, time\n"
    "time.sleep(float(os.environ.get('FAKE_SLEEP', '0') or 0) or {sleep})\n"
    "print(json.dumps({{'type': 'result', 'session_id': 's', 'cost_usd': 0.0, 'summary': 'done'}}))\n"
)


def _live_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    (tmp_path / "fakehome").mkdir(exist_ok=True)
    root = tmp_path / "repo"
    root.mkdir()
    ws = tmp_path / "workspace"
    ws.mkdir()
    return root, ws


def test_live_provider_is_killed_at_mission_budget_and_labeled_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    root, ws = _live_dirs(tmp_path, monkeypatch)
    script = _make_fake_cli(tmp_path, "claude", _SLOW_CLI.format(sleep=60))
    started = time.monotonic()
    res = run_provider("claude", root, ws, "Fix", write_paths=["charge.py"], executable=script,
                       timeout=1.5, simulated=False, allow_live=True)
    elapsed = time.monotonic() - started
    assert elapsed < 20, elapsed
    assert res["capture_status"] != "complete", res
    assert res["stage"] == "FAILED"
    assert res["verification_label"] == "LIVE_FAILED"
    assert any("terminated early" in r for r in res["reasons"]), res["reasons"]


def test_live_budget_is_not_clamped_to_simulated_cap_but_simulated_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from repo_ai.providers import adapters

    monkeypatch.setattr(adapters, "SIMULATED_TIMEOUT_CAP", 0.5)
    root, ws = _live_dirs(tmp_path, monkeypatch)
    script = _make_fake_cli(tmp_path, "claude", _SLOW_CLI.format(sleep=2))
    live = run_provider("claude", root, ws, "Fix", write_paths=["charge.py"], executable=script,
                        timeout=15, simulated=False, allow_live=True)
    assert live["capture_status"] == "complete", live
    assert live["stage"] == "READY" and live["verification_label"] == "LIVE_READY", live
    sim = run_provider("claude", root, ws, "Fix", write_paths=["charge.py"], executable=script,
                       timeout=15, simulated=True)
    assert sim["capture_status"] != "complete", sim
    assert sim["stage"] == "FAILED"


def test_live_constraint_prompt_lets_shell_only_providers_read_but_keeps_bob_shell_free(tmp_path):
    from repo_ai.providers.adapters import live_constraint_prompt
    bob = live_constraint_prompt("bob", "fix x", "a.py", tmp_path)
    codex = live_constraint_prompt("codex", "fix x", "a.py", tmp_path)
    assert "Do not run shell commands" in bob
    assert "Do not run shell commands" not in codex and "read-only" in codex
    for text in (bob, codex):
        assert "Edit ONLY a.py" in text and "Do not modify test files" in text


def test_codex_inner_sandbox_is_disabled_only_when_externally_sandboxed(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    alone = build_invocation("codex", "/usr/local/bin/codex", "Fix bug", ws)
    assert "--dangerously-bypass-approvals-and-sandbox" not in alone
    assert alone[alone.index("--sandbox") + 1] == "workspace-write"
    wrapped = build_invocation("codex", "/usr/local/bin/codex", "Fix bug", ws, externally_sandboxed=True)
    assert "--dangerously-bypass-approvals-and-sandbox" in wrapped and "--sandbox" not in wrapped
    for other in ("claude", "gemini", "bob"):
        assert "--dangerously-bypass-approvals-and-sandbox" not in build_invocation(
            other, f"/usr/local/bin/{other}", "Fix bug", ws, externally_sandboxed=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt profile is macOS-specific")
def test_outer_sandbox_denies_credential_reads_and_foreign_writes(tmp_path: Path) -> None:
    from repo_ai.providers.adapters import _execution_sandbox_prefix
    ws, sc = tmp_path / "ws", tmp_path / "sc"
    ws.mkdir()
    sc.mkdir()
    prefix = _execution_sandbox_prefix(ws, sc, allow_network=True)
    assert prefix is not None
    def run(*cmd):
        return subprocess.run([*prefix, *cmd], capture_output=True, text=True, timeout=20)
    assert run("/bin/sh", "-c", f"echo ok > {ws}/inside.txt").returncode == 0
    assert run("/bin/sh", "-c", f"echo no > {tmp_path}/outside.txt").returncode != 0
    assert not (tmp_path / "outside.txt").exists()
    ssh = Path.home() / ".ssh"
    if ssh.is_dir():
        assert run("/bin/ls", str(ssh)).returncode != 0
        assert subprocess.run(["/bin/ls", str(ssh)], capture_output=True).returncode == 0  # control: denial is the profile's
