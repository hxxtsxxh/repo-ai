"""opencode-acp end to end through the real live sandbox prefix (review of #31): a hand-written ACP agent, no model.
The agent reports what it could reach; the network, the real HOME and the parent's secrets must all be out of reach."""
from __future__ import annotations

import json
import socket  # noqa: F401  (used inside the agent script text)
import subprocess
import sys
from pathlib import Path

import pytest

from repo_ai.providers import opencode_cfg, run_provider

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="the live opencode sandbox is macOS seatbelt")

FIXED = "def charge(amount, retries):\n    return amount\n"

# a minimal hand-written ACP agent with arbitrary python hooks
AGENT = r'''
import json, os, sys, socket, subprocess, time
HOOK = %(hook)r
def send(m):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **m}) + "\n"); sys.stdout.flush()
info = {}
exec(HOOK.get("startup", ""))
for line in sys.stdin:
    msg = json.loads(line)
    m, rid = msg.get("method"), msg.get("id")
    if m == "initialize":
        send({"id": rid, "result": {"protocolVersion": 1, "agentInfo": info}})
    elif m == "session/new":
        send({"id": rid, "result": {"sessionId": "s1"}})
    elif m == "session/prompt":
        exec(HOOK.get("prompt", ""))
        send({"id": rid, "result": {"stopReason": HOOK.get("stop", "end_turn")}})
'''


def agent(tmp_path, hook, interpreter=sys.executable, name="opencode"):
    d = tmp_path / "bins"
    d.mkdir(exist_ok=True)
    exe = d / name
    exe.write_text(f"#!{interpreter} -I\n" + AGENT % {"hook": hook})
    exe.chmod(0o755)
    return exe


def dirs(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "charge.py").write_text("def charge(amount, retries):\n    return amount * (retries + 1)\n")
    (root / "test_charge.py").write_text("from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n")
    ws = tmp_path / "workspace"
    subprocess.run(["cp", "-R", str(root), str(ws)], check=True)
    return root, ws, {"charge.py", "test_charge.py"}



def test_the_live_prefix_denies_network_home_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv(opencode_cfg.MODEL_ENV, "qwen3:8b")
    monkeypatch.setenv("SECRET_TOKEN_X", "sk-shouldnotleak")
    root, ws, _ = dirs(tmp_path)
    out = ws / "probe.json"
    homefile = Path.home() / ".zshrc"
    hook = {"prompt": (
        "r = {'env_keys': sorted(os.environ), 'home': os.environ.get('HOME')}\n"
        "try:\n s = socket.create_connection(('1.1.1.1', 443), timeout=3); r['net']='open'; s.close()\n"
        "except Exception as e: r['net']=type(e).__name__\n"
        f"try:\n open({str(homefile)!r}).read(1); r['home_read']='ok'\n"
        "except Exception as e: r['home_read']=type(e).__name__\n"
        f"open({str(out)!r},'w').write(json.dumps(r))\n")}
    exe = agent(tmp_path, hook, interpreter="/usr/bin/python3")
    res = run_provider("opencode-acp", root, ws, "x", write_paths=["charge.py"], executable=exe, timeout=30,
                       simulated=False, allow_live=True)
    r = json.loads(out.read_text())
    assert res["cost_status"] == "OBSERVED" and res["events"]["cost_basis"] == "loopback_model_only"
    assert "SECRET_TOKEN_X" not in r["env_keys"]
    assert r["net"] != "open"
    assert r["home_read"] != "ok"
    assert "OPENCODE_CONFIG_CONTENT" in r["env_keys"] and "OPENCODE_DISABLE_CLAUDE_CODE" in r["env_keys"]




def test_a_flood_of_agent_text_is_bounded_and_fails_the_run(tmp_path):
    root, ws, _ = dirs(tmp_path)
    hook = {"prompt": ("chunk = 'x' * 1000000\n"
                       "for i in range(3):\n"
                       "  send({'method': 'session/update', 'params': {'sessionId': 's1', 'update': {"
                       "'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': chunk}}}})\n")}
    exe = agent(tmp_path, hook)
    res = run_provider("opencode-acp", root, ws, "x", write_paths=["charge.py"], executable=exe, timeout=60,
                       simulated=True)
    assert any("output bound" in r for r in res["reasons"]), res["reasons"]
    assert res["stage"] not in {"READY", "PASS"}
