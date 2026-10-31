"""`opencode-acp`: OpenCode driven over the Agent Client Protocol, under exactly the `opencode` isolation.

Wiring, gating and the mapping of an ACP run into run_provider's result shape. No test calls a model; runs of a
scripted ACP agent through the host sandbox are in test_provider_acp_runtime.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import run_cli
from repo_ai.providers import adapters, catalog, discovery, opencode_cfg, registry
from repo_ai.providers.acp import AcpResult

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the ACP client is POSIX-only, as missions are")

FAKE = Path(__file__).parent / "fake_acp_agent.py"


def fake_acp_cli(tmp_path: Path, script: list, *, interpreter: str = sys.executable, name: str = "opencode") -> Path:
    """A stand-in `opencode` that speaks ACP over stdio (tests/fake_acp_agent.py, inlined so the executable is
    self-contained) and refuses to start unless invoked as `opencode acp`."""
    folder = tmp_path / "fake_bins"
    folder.mkdir(exist_ok=True)
    exe = folder / name
    exe.write_text(f"#!{interpreter} -I\nimport os\n"
                   f"os.environ['FAKE_ACP_SCRIPT'] = {json.dumps(script)!r}\n"
                   "os.environ['FAKE_ACP_EXPECT_ARGV'] = '[\"acp\"]'\n"
                   + FAKE.read_text(encoding="utf-8"), encoding="utf-8")
    exe.chmod(0o755)
    return exe


# ---------------------------------------------------------------- wiring

def test_contract_and_invocation_are_opencode_acp_with_the_prompt_off_argv(tmp_path):
    contract = adapters.contract_for("opencode-acp")
    assert contract.event_format == adapters.ACP_EVENT_FORMAT and contract.enforces_hard_usd_budget is False
    assert contract.sandbox_flags == adapters.contract_for("opencode").sandbox_flags
    argv = adapters.build_invocation("opencode-acp", "/x/opencode", "fix sk-1234567890abcdefghijklmnop", tmp_path)
    assert argv == ["/x/opencode", "acp"]
    assert adapters.acp_prompt("key sk-1234567890abcdefghijklmnop " + "x" * 9000).count("sk-1234567890") == 0
    assert len(adapters.acp_prompt("x" * 9000)) == 8000
    with pytest.raises(ValueError):
        adapters.build_invocation("opencode-acp", "/x/opencode", "fix", tmp_path, max_cost_usd=1.0)
    with pytest.raises(ValueError, match="ACP"):
        adapters.parse_event_stream("opencode-acp", b"{}")


def test_it_runs_the_opencode_executable_and_is_listed_everywhere_opencode_is():
    assert "opencode-acp" in discovery.PROVIDERS and discovery.executable_name("opencode-acp") == "opencode"
    assert discovery.executable_name("codex") == "codex"
    assert "opencode-acp" in registry.DEFAULT_ORDER
    from repo_ai.mission.runtime import LIVE_PROVIDERS
    assert "opencode-acp" in LIVE_PROVIDERS
    entry = next(p for p in catalog.load()["providers"] if p["id"] == "opencode-acp")
    assert entry["executables"] == ["opencode"] and entry["acp"] is True and entry["local_model"] is True
    assert adapters.setup_problems("opencode-acp") == opencode_cfg.setup_problems()


def test_live_sandbox_is_the_opencode_sandbox(tmp_path):
    ws, sc = tmp_path / "w", tmp_path / "s"
    ws.mkdir()
    sc.mkdir()
    kw = dict(allow_network=True, live=True, executable=Path("/usr/bin/true"), run_marker="com.repo-ai.run.x")
    assert adapters._execution_sandbox_prefix(ws, sc, provider="opencode-acp", **kw) == \
        adapters._execution_sandbox_prefix(ws, sc, provider="opencode", **kw)
    assert adapters.live_constraint_prompt("opencode-acp", "p", "a.py", ws) == \
        adapters.live_constraint_prompt("opencode", "p", "a.py", ws)


def test_off_macos_live_opencode_acp_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    assert adapters._execution_sandbox_prefix(tmp_path, tmp_path, allow_network=True, provider="opencode-acp",
                                              live=True) is None
    monkeypatch.setattr(registry.sys, "platform", "linux")
    assert registry._readiness("opencode-acp", {"stage": "DISCOVERED"}, True, False, False, None, True) == \
        "RUNTIME_UNSUPPORTED"


def test_discovery_reads_the_acp_subcommand_help():
    help_text = (b"DESCRIPTION\n  Start an Agent Client Protocol server\n\nUSAGE\n  opencode acp [flags]\n\n"
                 b"FLAGS\n  --login    Run auth login instead of starting the server\n")
    assert discovery._observed_modes("opencode-acp", help_text) == ["headless", "structured_events"]
    assert discovery._observed_modes("opencode-acp", b"USAGE\n  opencode run [message..]\n") == []
    assert discovery._version("opencode-acp", b"opencode v2.2.1\n") == "2.2.1"


# ---------------------------------------------------------------- gating

def test_live_run_without_configuration_never_starts_the_agent(tmp_path, monkeypatch):
    monkeypatch.delenv(opencode_cfg.MODEL_ENV, raising=False)
    marker = tmp_path / "started"
    exe = tmp_path / "bin" / "opencode"
    exe.parent.mkdir()
    exe.write_text(f"#!/bin/sh\ntouch {marker}\n")
    exe.chmod(0o755)
    (tmp_path / "root").mkdir()
    (tmp_path / "ws").mkdir()
    res = adapters.run_provider("opencode-acp", tmp_path / "root", tmp_path / "ws", "fix", write_paths=["a.py"],
                                executable=exe, timeout=10, simulated=False, allow_live=True)
    assert res["stage"] == "BLOCKED" and res["capture_status"] == "not_configured" and not marker.exists()


def test_routing_reports_setup_required_without_a_model(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(registry, "_isolated_ready", lambda provider: True)
    monkeypatch.delenv(opencode_cfg.MODEL_ENV, raising=False)
    profiles = [{"provider": p, "stage": "DISCOVERED" if p == "opencode-acp" else "NOT_INSTALLED",
                 "status": "PLANNING_ONLY"} for p in adapters.PROVIDERS]
    row = next(c for c in registry.route(tmp_path, run_authorized=True, profiles=profiles)["considered"]
               if c["provider"] == "opencode-acp")
    assert row["readiness"] == "SETUP_REQUIRED"
    monkeypatch.setenv(opencode_cfg.MODEL_ENV, "qwen3:8b")
    assert registry.route(tmp_path, run_authorized=True, profiles=profiles)["selected"] == "opencode-acp"


def test_agents_setup_without_a_model_runs_nothing(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = run_cli(tmp_path, "agents", "setup", "opencode-acp", "--json")
    assert proc.returncode == 2, proc.stderr
    value = json.loads(proc.stdout)
    assert value["provider"] == "opencode-acp" and value["model_invoked"] is False and not value["ready_to_try"]
    assert "acp_handshake" not in value and opencode_cfg.MODEL_ENV in " ".join(value["problems"])


class _Recorder:
    """Stands in for AcpClient: records how run_provider builds the agent process."""
    seen: dict = {}
    outcome: AcpResult | BaseException = AcpResult(stop_reason="end_turn", session_id="s1", messages=["done"])

    def __init__(self, argv, workspace, *, allowed_writes, env=None, cwd=None):
        _Recorder.seen = {"argv": argv, "workspace": workspace, "allowed": allowed_writes, "env": env, "cwd": cwd}

    def run(self, prompt, timeout_s):
        _Recorder.seen.update(prompt=prompt, timeout=timeout_s)
        if isinstance(_Recorder.outcome, BaseException):
            raise _Recorder.outcome
        return _Recorder.outcome


def _wired(tmp_path, monkeypatch):
    monkeypatch.setenv(opencode_cfg.MODEL_ENV, "qwen3:8b")
    monkeypatch.setattr(adapters, "AcpClient", _Recorder)
    prefixes = []

    def prefix(*a, **k):
        prefixes.append(k)
        return ["/usr/bin/sandbox-exec", "-p", "(version 1)"]
    monkeypatch.setattr(adapters, "_execution_sandbox_prefix", prefix)
    reaped = []
    monkeypatch.setattr(adapters, "_reap_provider_run", lambda marker: reaped.append(marker) or [])
    for name in ("root", "ws"):
        (tmp_path / name).mkdir()
    exe = tmp_path / "opencode"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe, prefixes, reaped


def test_the_agent_runs_inside_the_opencode_prefix_with_the_opencode_environment(tmp_path, monkeypatch):
    exe, prefixes, reaped = _wired(tmp_path, monkeypatch)
    _Recorder.outcome = AcpResult(stop_reason="end_turn", session_id="s1", messages=["Fixed ", "a.py"])
    res = adapters.run_provider("opencode-acp", tmp_path / "root", tmp_path / "ws", "fix a", write_paths=["a.py"],
                                executable=exe, timeout=10, simulated=False, allow_live=True)
    seen = _Recorder.seen
    assert seen["argv"] == ["/usr/bin/sandbox-exec", "-p", "(version 1)", str(exe.resolve()), "acp"]
    assert prefixes[0]["provider"] == "opencode-acp" and prefixes[0]["live"] is True
    assert seen["allowed"] == ["a.py"] and seen["cwd"] == (tmp_path / "ws").resolve()
    env = seen["env"]
    for key, value in opencode_cfg.environment(read_only=False).items():
        assert env[key] == value
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["permission"]["*"] == "deny"
    assert env["HOME"].endswith("/home") and str(Path.home()) not in env["HOME"]
    assert "CONSTRAINTS" in seen["prompt"] and "Shell commands are not available" in seen["prompt"]
    assert len(reaped) == 1
    assert res["stage"] == "READY" and res["verification_label"] == "LIVE_READY" and res["reasons"] == []
    assert res["returncode"] == 0 and res["capture_status"] == "complete"
    assert res["cost_usd"] == 0.0 and res["cost_status"] == "OBSERVED"
    assert res["events"]["cost_basis"] == "loopback_model_only" and res["events"]["report"] == "Fixed a.py"


def test_a_read_only_role_gets_the_read_only_policy_and_no_write_path(tmp_path, monkeypatch):
    exe, _, _ = _wired(tmp_path, monkeypatch)
    _Recorder.outcome = AcpResult(stop_reason="end_turn", session_id="s1", messages=["advice"])
    adapters.run_provider("opencode-acp", tmp_path / "root", tmp_path / "ws", "look", write_paths=[],
                          executable=exe, timeout=10, simulated=False, allow_live=True, constraints="READ-ONLY")
    assert _Recorder.seen["allowed"] == []
    assert json.loads(_Recorder.seen["env"]["OPENCODE_CONFIG_CONTENT"])["permission"].get("edit") is None


def test_cleanup_runs_even_when_the_client_raises(tmp_path, monkeypatch):
    exe, _, reaped = _wired(tmp_path, monkeypatch)
    _Recorder.outcome = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        adapters.run_provider("opencode-acp", tmp_path / "root", tmp_path / "ws", "fix", write_paths=["a.py"],
                              executable=exe, timeout=10, simulated=False, allow_live=True)
    assert len(reaped) == 1


def test_unconfirmed_cleanup_fails_a_live_run(tmp_path, monkeypatch):
    exe, _, _ = _wired(tmp_path, monkeypatch)
    monkeypatch.setattr(adapters, "_reap_provider_run", lambda marker: ["provider cleanup not confirmed: x"])
    _Recorder.outcome = AcpResult(stop_reason="end_turn", session_id="s1")
    res = adapters.run_provider("opencode-acp", tmp_path / "root", tmp_path / "ws", "fix", write_paths=["a.py"],
                                executable=exe, timeout=10, simulated=False, allow_live=True)
    assert res["stage"] == "FAILED" and "provider cleanup not confirmed: x" in res["reasons"]


# ---------------------------------------------------------------- AcpResult -> run_provider's result

def _result(**kw) -> dict:
    run = AcpResult(**{"session_id": "s1", **kw})
    return adapters._acp_run_result("opencode-acp", run, resolved=Path("/x/opencode"), identity="0" * 64,
                                    simulated=True, max_cost_usd=0.0, cleanup_problems=[])


def test_a_clean_turn_maps_to_the_common_shape():
    res = _result(stop_reason="end_turn", agent={"name": "OpenCode", "version": "2.2.1"},
                  messages=["Fixed it; key sk-1234567890abcdefghijklmnop"],
                  tool_calls=[{"toolCallId": "t1", "title": "read", "kind": "read", "status": "pending"},
                              {"toolCallId": "t1", "status": "completed"},
                              {"toolCallId": "t2", "title": "bash", "kind": "execute", "status": "failed"}],
                  permissions=[{"tool": "bash", "kind": "execute", "chosen": "rej", "why": "tool kind 'execute' is not allowed"},
                               {"tool": "edit", "kind": "edit", "chosen": "ok", "why": "tool kind 'edit' allowed once"}])
    assert res["stage"] == "SIMULATED" and res["reasons"] == [] and res["returncode"] == 0
    ev = res["events"]
    assert ev["event_format"] == "acp-jsonrpc" and ev["protocol_valid"] and ev["terminal_observed"]
    assert ev["session_id"] == "s1" and ev["stop_reason"] == "end_turn" and ev["agent"]["name"] == "OpenCode"
    assert ev["tool_calls"] == ["read"] and ev["tool_errors"] == ["bash"] and ev["denied_actions"] == ["bash"]
    assert ev["cost_usd"] == 0.0 and ev["cost_status"] == "OBSERVED" and ev["cost_basis"] == "network_denied"
    assert "sk-1234567890abcdefghijklmnop" not in json.dumps(res) and ev["summary"].startswith("Fixed it")
    for key in ("valid_jsonl", "events_count", "turns", "tokens", "rate_limited", "errors", "report", "output_sha256"):
        assert key in ev


@pytest.mark.parametrize("kw,needle,status", [
    ({"timed_out": True, "problems": ["the agent did not finish within the time limit"]}, "timeout", "timeout"),
    ({"problems": ["the agent exited while answering session/prompt"]}, "ACP: the agent exited", "protocol_incomplete"),
    ({"stop_reason": "end_turn", "refused": ["write refused (not an allowed regular file): /w/b.py"]},
     "ACP client refused an agent request", "complete"),
    ({"stop_reason": "refusal"}, "stop reason 'refusal'", "complete"),
    ({"stop_reason": "max_tokens"}, "not end_turn", "complete"),
    ({}, "without a stop reason", "protocol_incomplete"),
    ({"problems": ["session/prompt failed: rate limit exceeded"]}, "rate/usage limit", "protocol_incomplete"),
])
def test_problems_refusals_timeouts_and_stop_reasons_are_never_a_pass(kw, needle, status):
    res = _result(**kw)
    assert res["stage"] == "FAILED" and res["capture_status"] == status
    # returncode describes the protocol turn only (a refusal inside a clean end_turn is a reason, not an exit code)
    assert res["returncode"] == (0 if kw.get("stop_reason") == "end_turn" else 1)
    assert any(needle in r for r in res["reasons"]), res["reasons"]
    if kw.get("timed_out"):
        assert sum("time limit" in r or "timeout" in r for r in res["reasons"]) == 1


def test_a_usd_ceiling_cannot_be_satisfied_by_acp():
    run = AcpResult(session_id="s1", stop_reason="end_turn")
    res = adapters._acp_run_result("opencode-acp", run, resolved=Path("/x/opencode"), identity="0" * 64,
                                   simulated=False, max_cost_usd=1.0, cleanup_problems=[])
    assert res["stage"] == "FAILED" and any("unknown cost" in r for r in res["reasons"])


# ---------------------------------------------------------------- the handshake (no session, no model)

@pytest.mark.skipif(sys.platform != "darwin", reason="live OpenCode isolation is macOS seatbelt only")
def test_handshake_runs_initialize_only_inside_the_live_sandbox(tmp_path):
    # /usr/bin/python3: the live profile hides HOME, where a development venv may live
    exe = fake_acp_cli(tmp_path, [{"exit": 9}], interpreter="/usr/bin/python3")
    (tmp_path / "repo").mkdir()
    shake = adapters.acp_handshake("opencode-acp", tmp_path / "repo", executable=exe)
    assert shake["acp"] is True and shake["protocol_version"] == 1 and shake["agent"] == {"name": "fake"}
    assert shake["model_invoked"] is False and shake["cleanup_problems"] == []


def test_handshake_refuses_a_repository_owned_executable(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    exe = fake_acp_cli(tmp_path, [])
    owned = root / "opencode"
    owned.write_bytes(exe.read_bytes())
    owned.chmod(0o755)
    shake = adapters.acp_handshake("opencode-acp", root, executable=owned)
    assert shake["acp"] is False and "repository-owned" in shake["problem"]
    with pytest.raises(ValueError):
        adapters.acp_handshake("opencode", root, executable=exe)
