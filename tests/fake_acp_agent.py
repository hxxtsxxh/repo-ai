"""A scripted ACP agent for tests: JSON-RPC over stdio, protocol version 1. The script (JSON in FAKE_ACP_SCRIPT)
lists client calls to make during session/prompt; replies are recorded to FAKE_ACP_LOG."""
import json
import os
import sys
import time

script = json.loads(os.environ.get("FAKE_ACP_SCRIPT", "[]"))
log_path = os.environ.get("FAKE_ACP_LOG")
version = int(os.environ.get("FAKE_ACP_VERSION", "1"))
next_id = 1000
log = []


def send(msg):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
    sys.stdout.flush()


def read():
    line = sys.stdin.readline()
    return json.loads(line) if line else None


def call(method, params):
    global next_id
    next_id += 1
    send({"id": next_id, "method": method, "params": params})
    while True:
        msg = read()
        if msg is None:
            sys.exit(0)
        if msg.get("id") == next_id:
            log.append({"method": method, "reply": msg})
            return msg


while True:
    msg = read()
    if msg is None:
        break
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        send({"id": rid, "result": {"protocolVersion": version, "agentCapabilities": {}, "agentInfo": {"name": "fake"}}})
    elif method == "session/new":
        send({"id": rid, "result": {"sessionId": "s1"}})
    elif method == "session/prompt":
        sid = params["sessionId"]
        for step in script:
            if step.get("sleep"):
                time.sleep(step["sleep"])
            elif step.get("say"):
                send({"method": "session/update", "params": {"sessionId": sid, "update": {
                    "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": step["say"]}}}})
            else:
                call(step["method"], {"sessionId": sid, **step.get("params", {})})
        if log_path:
            open(log_path, "w").write(json.dumps(log))
        send({"id": rid, "result": {"stopReason": "end_turn"}})
    elif method == "session/cancel":
        if log_path:
            open(log_path, "w").write(json.dumps(log + [{"method": "session/cancel"}]))
