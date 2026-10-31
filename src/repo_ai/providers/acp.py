"""An Agent Client Protocol (ACP) client: one permission policy for every agent that speaks ACP.

ACP is JSON-RPC 2.0 over the agent's stdio, one JSON object per line (protocol version 1, as OpenCode 2.2.1 and
other agents implement it). The client starts a session in a workspace, sends one prompt, and answers the agent's
requests while it works:

* ``fs/read_text_file``: served only for a regular file inside the workspace (no link is followed out of it);
* ``fs/write_text_file``: served only for a path the run may write (``allowed_writes``), inside the workspace;
* ``session/request_permission``: answered by policy: an option that allows once is chosen only for a tool call of
  kind ``read``, ``search`` or ``edit`` (``think`` too); anything else (``execute``, ``fetch``, ``delete``, ``move``,
  ``other``) is rejected, and no option that allows *always* is ever chosen;
* terminals are not offered (``clientCapabilities.terminal`` is false) and any ``terminal/*`` call is refused.

ACP is a control channel, not a security boundary: an agent may also edit files itself. repo-ai therefore runs the
agent process inside the same OS sandbox as its other providers and checks the workspace afterwards
(``adapters.validate_workspace_edits``); this module never trusts the agent's own account of what it did.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL_VERSION = 1
MAX_LINE = 4_000_000          # one JSON-RPC message
MAX_READ = 2_000_000          # one file served to the agent
ALLOWED_KINDS = {"read", "search", "edit", "think"}


class AcpError(RuntimeError):
    pass


@dataclass
class AcpResult:
    stop_reason: str = ""
    session_id: str = ""
    agent: dict[str, Any] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)          # the agent's text, chunk by chunk
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    permissions: list[dict[str, Any]] = field(default_factory=list)  # what was asked and what the policy chose
    refused: list[str] = field(default_factory=list)            # client calls the policy refused
    writes: list[str] = field(default_factory=list)             # files written through fs/write_text_file
    problems: list[str] = field(default_factory=list)
    timed_out: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"stop_reason": self.stop_reason, "session_id": self.session_id, "agent": self.agent,
                "text": "".join(self.messages)[-20_000:], "tool_calls": self.tool_calls[:200],
                "permissions": self.permissions[:200], "refused": self.refused[:200], "writes": self.writes[:200],
                "problems": self.problems[:50], "timed_out": self.timed_out}


def _inside(workspace: Path, rel_or_abs: str) -> Path | None:
    """The workspace path an agent names (absolute, as ACP requires, or relative), never outside it."""
    p = Path(rel_or_abs)
    target = p if p.is_absolute() else workspace / p
    try:
        resolved = target.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    root = workspace.resolve()
    return resolved if resolved == root or root in resolved.parents else None


def choose_permission(request: Mapping[str, Any]) -> tuple[str | None, str]:
    """(optionId or None to cancel, why) for a ``session/request_permission`` request."""
    call = request.get("toolCall") or {}
    kind = str(call.get("kind") or "other")
    options = [o for o in request.get("options") or [] if isinstance(o, Mapping)]
    if kind not in ALLOWED_KINDS:
        reject = next((o for o in options if o.get("kind") == "reject_once"), None) or \
            next((o for o in options if str(o.get("kind", "")).startswith("reject")), None)
        return (str(reject["optionId"]) if reject else None), f"tool kind {kind!r} is not allowed"
    allow = next((o for o in options if o.get("kind") == "allow_once"), None)
    if allow is None:
        return None, "no option allows once (allow-always is never chosen)"
    return str(allow["optionId"]), f"tool kind {kind!r} allowed once"


class AcpClient:
    """One ACP agent process, driven to answer one prompt."""

    def __init__(self, argv: list[str], workspace: Path, *, allowed_writes: list[str], env: Mapping[str, str] | None = None,
                 cwd: Path | None = None, log: Callable[[str], None] = lambda _: None):
        self.argv = list(argv)
        self.workspace = workspace.resolve()
        self.allowed = {str(PurePosixPath(w)) for w in allowed_writes}
        self.env = dict(env) if env is not None else dict(os.environ)
        self.cwd = cwd or self.workspace
        self.log = log
        self.proc: subprocess.Popen[bytes] | None = None
        self._buf = b""
        self._next_id = 0
        self.result = AcpResult()

    # -- transport ---------------------------------------------------------------------------------------------
    def _send(self, msg: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write((json.dumps({"jsonrpc": "2.0", **msg}) + "\n").encode())
        self.proc.stdin.flush()

    def _read(self, deadline: float) -> dict[str, Any] | None:
        assert self.proc is not None and self.proc.stdout is not None
        while b"\n" not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            ready, _, _ = select.select([self.proc.stdout], [], [], min(left, 1.0))
            if not ready:
                if self.proc.poll() is not None:
                    return None
                continue
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                return None
            self._buf += chunk
            if len(self._buf) > MAX_LINE and b"\n" not in self._buf:
                raise AcpError("an ACP message exceeds the size bound")
        line, _, self._buf = self._buf.partition(b"\n")
        if not line.strip():
            return {}
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            self.result.problems.append("a line on the agent's stdout is not JSON-RPC")
            return {}
        return msg if isinstance(msg, dict) else {}

    def _request(self, method: str, params: dict[str, Any], deadline: float) -> Any:
        self._next_id += 1
        rid = self._next_id
        self._send({"id": rid, "method": method, "params": params})
        while True:
            msg = self._read(deadline)
            if msg is None:
                raise AcpError(f"the agent exited while answering {method}")
            if msg.get("id") == rid and "method" not in msg:
                if "error" in msg:
                    raise AcpError(f"{method} failed: {json.dumps(msg['error'])[:300]}")
                return msg.get("result")
            self._handle(msg)

    # -- the agent's calls ---------------------------------------------------------------------------------------
    def _reply(self, rid: Any, result: Any = None, error: str | None = None) -> None:
        if error is not None:
            self.result.refused.append(error)
            self._send({"id": rid, "error": {"code": -32000, "message": error}})
        else:
            self._send({"id": rid, "result": result})

    def _handle(self, msg: dict[str, Any]) -> None:
        method, params, rid = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if not method:
            return
        if method == "session/update":
            self._update(params.get("update") or {})
            return
        if rid is None:
            return  # an unknown notification
        if method == "fs/read_text_file":
            target = _inside(self.workspace, str(params.get("path", "")))
            if target is None or target.is_symlink() or not target.is_file():
                self._reply(rid, error=f"read refused (outside the workspace or not a file): {params.get('path')}")
                return
            data = target.read_bytes()[:MAX_READ].decode("utf-8", "replace")
            line, limit = params.get("line"), params.get("limit")
            if isinstance(line, int) and line > 0:
                rows = data.splitlines(keepends=True)[line - 1:]
                data = "".join(rows[:limit] if isinstance(limit, int) and limit > 0 else rows)
            self._reply(rid, {"content": data})
        elif method == "fs/write_text_file":
            target = _inside(self.workspace, str(params.get("path", "")))
            rel = target.relative_to(self.workspace).as_posix() if target is not None else ""
            if target is None or rel not in self.allowed or target.is_symlink():
                self._reply(rid, error=f"write refused (not an allowed path): {params.get('path')}")
                return
            target.write_text(str(params.get("content", "")), encoding="utf-8")
            self.result.writes.append(rel)
            self._reply(rid, None)
        elif method == "session/request_permission":
            option, why = choose_permission(params)
            self.result.permissions.append({"tool": (params.get("toolCall") or {}).get("title", ""),
                                            "kind": (params.get("toolCall") or {}).get("kind", ""),
                                            "chosen": option, "why": why})
            self._reply(rid, {"outcome": {"outcome": "selected", "optionId": option}} if option
                        else {"outcome": {"outcome": "cancelled"}})
        else:  # terminal/* and anything else the client never offered
            self._reply(rid, error=f"{method} is not offered by this client")

    def _update(self, update: dict[str, Any]) -> None:
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            if content.get("type") == "text":
                self.result.messages.append(str(content.get("text", "")))
        elif kind in {"tool_call", "tool_call_update"}:
            self.result.tool_calls.append({k: update.get(k) for k in ("toolCallId", "title", "kind", "status")
                                           if update.get(k) is not None})

    # -- capability probe (no session, no model call) ------------------------------------------------------------
    def probe(self, timeout_s: float = 20.0) -> dict[str, Any]:
        """The agent's answer to `initialize` alone: whether it speaks ACP 1, who it is, what it can do and how it
        authenticates. No session is created, so no model is called."""
        deadline = time.monotonic() + timeout_s
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            init = self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True}, "terminal": False}}, deadline) or {}
            return {"acp": init.get("protocolVersion") == PROTOCOL_VERSION, "protocol_version": init.get("protocolVersion"),
                    "agent": init.get("agentInfo") or {}, "capabilities": init.get("agentCapabilities") or {},
                    "auth_methods": [m.get("id") for m in init.get("authMethods") or [] if isinstance(m, dict)]}
        except TimeoutError:
            return {"acp": False, "problem": "no answer to initialize within the time limit"}
        except (AcpError, OSError) as exc:
            return {"acp": False, "problem": str(exc)[:300]}
        finally:
            self.close()

    # -- one run ---------------------------------------------------------------------------------------------------
    def run(self, prompt: str, timeout_s: float) -> AcpResult:
        deadline = time.monotonic() + timeout_s
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            init = self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True}, "terminal": False}}, deadline) or {}
            if init.get("protocolVersion") != PROTOCOL_VERSION:
                raise AcpError(f"the agent speaks ACP {init.get('protocolVersion')!r}, not {PROTOCOL_VERSION}")
            self.result.agent = dict(init.get("agentInfo") or {})
            session = self._request("session/new", {"cwd": str(self.workspace), "mcpServers": []}, deadline) or {}
            self.result.session_id = str(session.get("sessionId", ""))
            if not self.result.session_id:
                raise AcpError("the agent returned no session")
            done = self._request("session/prompt", {"sessionId": self.result.session_id,
                                                    "prompt": [{"type": "text", "text": prompt}]}, deadline) or {}
            self.result.stop_reason = str(done.get("stopReason", ""))
        except TimeoutError:
            self.result.timed_out = True
            self.result.problems.append("the agent did not finish within the time limit")
            if self.result.session_id:
                try:
                    self._send({"method": "session/cancel", "params": {"sessionId": self.result.session_id}})
                except OSError:
                    pass
        except (AcpError, OSError) as exc:
            self.result.problems.append(str(exc)[:500])
        finally:
            self.close()
        return self.result

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, 9)
            except OSError:
                self.proc.kill()
            self.proc.wait(timeout=5)
