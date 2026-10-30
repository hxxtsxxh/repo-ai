"""OpenCode against a loopback model endpoint: configuration, gating, stream parsing and the OS boundary.

No test calls a model. Seatbelt tests run real `sandbox-exec` probes.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from repo_ai.providers import adapters, opencode_cfg, registry
from repo_ai.providers.discovery import ProbeResult


def _ev(type_: str, **part) -> dict:
    return {"type": type_, "timestamp": 1, "sessionID": "ses_1", "part": {"sessionID": "ses_1", **part}}


def _stream(*events: dict) -> bytes:
    return "\n".join(json.dumps(e) for e in events).encode()


OBSERVED_OK = _stream(  # shape observed from OpenCode 2.2.1 (docs/engineering/INTEGRATIONS.md)
    _ev("step_start", type="step-start"),
    _ev("tool_use", type="tool", tool="read", state={"status": "completed", "input": {"path": "calc.py"}}),
    _ev("step_finish", type="step-finish", reason="tool-calls", cost=0, tokens={"input": 3129, "output": 427}),
    _ev("step_start", type="step-start"),
    _ev("tool_use", type="tool", tool="edit", state={"status": "completed"}),
    _ev("step_finish", type="step-finish", reason="tool-calls", cost=0, tokens={"input": 463, "output": 389}),
    _ev("step_start", type="step-start"),
    _ev("text", type="text", text="Fixed add()."),
)


# ---------------------------------------------------------------- configuration

@pytest.mark.parametrize("url,ok", [
    ("http://127.0.0.1:11434/v1", True), ("http://localhost:1234/v1", True), ("http://[::1]:8080/v1", True),
    ("https://api.openai.com/v1", False), ("http://10.0.0.5:11434/v1", False), ("http://127.0.0.1.evil.com/v1", False),
    ("http://user:pw@127.0.0.1:11434/v1", False), ("file:///etc/passwd", False), ("not a url", False),
])
def test_only_loopback_endpoints_are_accepted(url, ok):
    assert (opencode_cfg.loopback_port(url) is not None) is ok
    problems = opencode_cfg.setup_problems({opencode_cfg.MODEL_ENV: "qwen3:8b", opencode_cfg.BASE_URL_ENV: url})
    assert (not problems) is ok


def test_missing_model_is_setup_required_with_guidance():
    problems = opencode_cfg.setup_problems({})
    assert problems and opencode_cfg.MODEL_ENV in problems[0]


def test_odd_model_names_are_refused():
    assert opencode_cfg.setup_problems({opencode_cfg.MODEL_ENV: "x\"}, \"permission\": {\"*\": \"allow"})


def test_policy_denies_every_tool_not_explicitly_allowed():
    cfg = json.loads(opencode_cfg.config_content("qwen3:8b", opencode_cfg.DEFAULT_BASE_URL, read_only=False))
    perm = cfg["permission"]
    assert perm["*"] == "deny" and perm["external_directory"] == "deny"
    assert {k for k, v in perm.items() if v == "allow"} == {"read", "edit", "glob", "grep", "list"}
    for tool in ("bash", "execute", "webfetch", "websearch", "task", "skill"):  # incl. 2.2.1's undocumented `execute`
        assert perm.get(tool, perm["*"]) == "deny"
    ro = json.loads(opencode_cfg.config_content("m", opencode_cfg.DEFAULT_BASE_URL, read_only=True))["permission"]
    assert "edit" not in ro or ro["edit"] == "deny"


def test_environment_blocks_project_config_and_carries_no_secret():
    env = opencode_cfg.environment({opencode_cfg.MODEL_ENV: "qwen3:8b", "OPENAI_API_KEY": "sk-secret"},
                                   read_only=False)
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1" and "sk-secret" not in json.dumps(env)


def test_invocation_is_standalone_json_and_prompt_stays_a_prompt(monkeypatch):
    monkeypatch.setenv(opencode_cfg.MODEL_ENV, "qwen3:8b")
    argv = adapters.build_invocation("opencode", "/x/opencode", "--auto", Path("."))
    assert argv[:5] == ["/x/opencode", "run", "--standalone", "--format", "json"]
    assert argv[argv.index("--model") + 1] == "repoai-local/qwen3:8b"
    assert argv[-2:] == ["--", "--auto"] and argv.count("--auto") == 1


def test_no_usd_ceiling_can_be_promised():
    with pytest.raises(ValueError):
        adapters.build_invocation("opencode", "/x/opencode", "p", Path("."), max_cost_usd=1.0)


# ---------------------------------------------------------------- stream parsing

def test_observed_stream_parses_as_a_valid_protocol():
    ev = adapters.parse_event_stream("opencode", OBSERVED_OK)
    assert ev["protocol_valid"] and ev["terminal_observed"] and ev["session_id"] == "ses_1"
    assert ev["tool_calls"] == ["read", "edit"] and ev["turns"] == 2
    assert ev["tokens"] == {"input_tokens": 3592, "output_tokens": 816}
    assert ev["cost_status"] == "OBSERVED" and ev["cost_usd"] == 0 and ev["summary"] == "Fixed add()."


def test_a_run_that_stops_without_a_final_text_is_not_terminal():
    ev = adapters.parse_event_stream("opencode", _stream(_ev("step_start", type="step-start")))
    assert not ev["terminal_observed"] and not ev["protocol_valid"]


def test_denied_tools_and_errors_are_recorded():
    stream = _stream(
        _ev("step_start"),
        _ev("tool_use", tool="read", state={"status": "error", "error": "Permission denied: external_directory"}),
        _ev("step_finish", reason="tool-calls", cost=0, tokens={"input": 1, "output": 1}),
        {"type": "error", "sessionID": "ses_1", "error": {"type": "provider.no-route", "message": "Model unavailable"}},
    )
    ev = adapters.parse_event_stream("opencode", stream)
    assert ev["denied_actions"] == ["read"] and ev["tool_errors"] == ["read"]
    assert "Model unavailable" in ev["errors"] and not ev["protocol_valid"]


# ---------------------------------------------------------------- gating

def test_live_run_without_configuration_never_starts_the_cli(tmp_path, monkeypatch):
    monkeypatch.delenv(opencode_cfg.MODEL_ENV, raising=False)
    marker = tmp_path / "started"
    exe = tmp_path / "bin" / "opencode"
    exe.parent.mkdir()
    exe.write_text(f"#!/bin/sh\ntouch {marker}\n")
    exe.chmod(0o755)
    (tmp_path / "root").mkdir()
    (tmp_path / "ws").mkdir()
    res = adapters.run_provider("opencode", tmp_path / "root", tmp_path / "ws", "fix", write_paths=["a.py"],
                                executable=exe, timeout=10, simulated=False, allow_live=True)
    assert res["stage"] == "BLOCKED" and res["capture_status"] == "not_configured" and not marker.exists()


def test_routing_reports_setup_required_without_a_model(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(registry, "_isolated_ready", lambda provider: True)
    monkeypatch.delenv(opencode_cfg.MODEL_ENV, raising=False)
    profiles = [{"provider": p, "stage": "DISCOVERED" if p == "opencode" else "NOT_INSTALLED",
                 "status": "PLANNING_ONLY"} for p in adapters.PROVIDERS]
    row = next(c for c in registry.route(tmp_path, run_authorized=True, profiles=profiles)["considered"]
               if c["provider"] == "opencode")
    assert row["readiness"] == "SETUP_REQUIRED"
    monkeypatch.setenv(opencode_cfg.MODEL_ENV, "qwen3:8b")
    assert registry.route(tmp_path, run_authorized=True, profiles=profiles)["selected"] == "opencode"


def test_off_macos_live_opencode_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    assert adapters._execution_sandbox_prefix(tmp_path, tmp_path, allow_network=True, provider="opencode",
                                              live=True) is None


# ---------------------------------------------------------------- OS boundary

@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")
def test_profile_allows_loopback_only_and_hides_home(tmp_path):
    ws, sc = tmp_path / "w", tmp_path / "s"
    ws.mkdir()
    sc.mkdir()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    threading.Thread(target=lambda: [server.accept()[0].close() for _ in range(2)], daemon=True).start()
    prefix = adapters._execution_sandbox_prefix(ws, sc, allow_network=True, provider="opencode", live=True,
                                                executable=Path("/usr/bin/nc"))
    assert prefix is not None
    nc = ["/usr/bin/nc", "-z", "-G", "3", "-w", "3"]
    assert subprocess.run([*prefix, *nc, "127.0.0.1", str(port)], capture_output=True, timeout=20).returncode == 0
    assert subprocess.run([*prefix, *nc, "1.1.1.1", "443"], capture_output=True, timeout=20).returncode != 0
    secret = Path.home() / f".repo_ai_oc_secret_{tmp_path.name}"
    secret.write_text("s")
    try:
        assert subprocess.run([*prefix, "/bin/cat", str(secret)], capture_output=True, timeout=20).returncode != 0
        assert subprocess.run([*prefix, "/bin/sh", "-c", f"echo x > {ws}/ok"], timeout=20).returncode == 0
    finally:
        secret.unlink()
        server.close()


def test_verbose_opencode_streams_get_a_larger_bounded_capture(tmp_path, monkeypatch):
    monkeypatch.setenv(opencode_cfg.MODEL_ENV, "qwen3:8b")
    seen = {}

    def fake_capture(argv, cwd, env, **kw):
        seen.update(kw)
        return ProbeResult(0, "complete", OBSERVED_OK, b"")
    monkeypatch.setattr(adapters, "_capture", fake_capture)
    monkeypatch.setattr(adapters, "_execution_sandbox_prefix", lambda *a, **k: ["/usr/bin/env"])
    (tmp_path / "root").mkdir()
    (tmp_path / "ws").mkdir()
    exe = tmp_path / "opencode"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    res = adapters.run_provider("opencode", tmp_path / "root", tmp_path / "ws", "fix", write_paths=["a.py"],
                                executable=exe, timeout=10, simulated=False, allow_live=True)
    assert seen["output_limit"] == adapters.MAX_OUTPUT * 4 and res["stage"] == "READY"
