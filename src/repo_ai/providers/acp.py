"""An Agent Client Protocol (ACP) client: one permission policy for every agent that speaks ACP.

ACP is JSON-RPC 2.0 over the agent's stdio, one JSON object per line (protocol version 1, as OpenCode 2.2.1 and
other agents implement it). The client starts a session in a workspace, sends one prompt, and answers the agent's
requests while it works:

* ``fs/read_text_file``: served only for a regular file inside the workspace, opened with no link followed and
  refused when hard-linked (it may also be named outside);
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
import stat
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


def _relative(workspace: Path, rel_or_abs: object) -> str | None:
    """The workspace-relative path an agent names (absolute, as ACP requires, or relative), normalised lexically
    and never resolved: links are refused when the file is opened, so nothing is checked and then followed."""
    if not isinstance(rel_or_abs, str) or not rel_or_abs or "\0" in rel_or_abs:
        return None
    raw = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(str(workspace), rel_or_abs)
    rel = os.path.relpath(os.path.normpath(raw), str(workspace))
    if rel in {".", ".."} or rel.startswith("../") or os.path.isabs(rel):
        return None
    return PurePosixPath(rel).as_posix()


def _open_inside(workspace: Path, rel: str, flags: int) -> int:
    """An fd for `rel` opened one component at a time from the workspace with O_NOFOLLOW: a link anywhere on the
    path (planted before or raced in during the call) fails the open instead of leading out. Non-blocking, so a
    FIFO cannot hang the client; the caller checks the result is a regular file."""
    parts = rel.split("/")
    fd = os.open(str(workspace), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644, dir_fd=fd)
    finally:
        os.close(fd)


def choose_permission(request: Mapping[str, Any]) -> tuple[str | None, str]:
    """(optionId or None to cancel, why) for a ``session/request_permission`` request. The tool call's `kind` is
    the agent's own word, which is why this policy is never the boundary (see the module docstring)."""
    raw_call = request.get("toolCall")
    call: Mapping[str, Any] = raw_call if isinstance(raw_call, Mapping) else {}
    kind = str(call.get("kind") or "other")
    options = [o for o in request.get("options") or [] if isinstance(o, Mapping) and isinstance(o.get("optionId"), str)]
    reject = next((o for o in options if o.get("kind") == "reject_once"), None) or \
        next((o for o in options if str(o.get("kind", "")).startswith("reject")), None)
    if kind not in ALLOWED_KINDS:
        return (reject["optionId"] if reject else None), f"tool kind {kind!r} is not allowed"
    allow = next((o for o in options if o.get("kind") == "allow_once"), None)
    if allow is None:  # allow-always is never chosen
        return (reject["optionId"] if reject else None), "no option allows once (allow-always is never chosen)"
    return allow["optionId"], f"tool kind {kind!r} allowed once"


class AcpClient:
    """One ACP agent process, driven to answer one prompt."""

    def __init__(self, argv: list[str], workspace: Path, *, allowed_writes: list[str], env: Mapping[str, str] | None = None,
                 cwd: Path | None = None, log: Callable[[str], None] = lambda _: None):
        self.argv = list(argv)
        self.workspace = workspace.resolve()
        self.allowed = {str(PurePosixPath(w)) for w in allowed_writes}
        # never the user's whole environment (it may hold credentials); a provider passes what the agent needs
        self.env = dict(env) if env is not None else {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        self.cwd = cwd or self.workspace
        self.log = log
        self.proc: subprocess.Popen[bytes] | None = None
        self._buf = b""
        self._next_id = 0
        self._deadline = 0.0
        self.result = AcpResult()

    # -- transport ---------------------------------------------------------------------------------------------
    def _send(self, msg: dict[str, Any]) -> None:
        """Write one message within the run's deadline: an agent that stops reading its stdin cannot hang us."""
        assert self.proc is not None and self.proc.stdin is not None
        data = memoryview((json.dumps({"jsonrpc": "2.0", **msg}) + "\n").encode())
        fd = self.proc.stdin.fileno()
        while data:
            left = self._deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            _, ready, _ = select.select([], [fd], [], min(left, 1.0))
            if ready:
                try:
                    data = data[os.write(fd, data):]
                except BlockingIOError:
                    continue

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
        except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
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
    def _reply(self, rid: Any, result: Any = None, error: str | None = None, code: int = -32000) -> None:
        if error is not None:
            self.result.refused.append(error)
            self._send({"id": rid, "error": {"code": code, "message": error}})
        else:
            self._send({"id": rid, "result": result})

    def _handle(self, msg: dict[str, Any]) -> None:
        """One message from the agent. A malformed one is answered (or recorded) as malformed, never a crash."""
        try:
            self._dispatch(msg)
        except (TimeoutError, OSError):
            raise
        except Exception as exc:  # noqa: BLE001 - whatever a hostile agent sends
            self.result.problems.append(f"malformed message from the agent: {type(exc).__name__}")
            if msg.get("id") is not None and msg.get("method"):
                self._reply(msg.get("id"), error="malformed request", code=-32602)

    def _dispatch(self, msg: dict[str, Any]) -> None:
        method, rid = msg.get("method"), msg.get("id")
        raw = msg.get("params")
        params: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if not method:
            return
        if method == "session/update":
            self._update(params.get("update"))
            return
        if rid is None:
            return  # an unknown notification
        if method == "fs/read_text_file":
            rel = _relative(self.workspace, params.get("path"))
            raw = self._read_file(rel) if rel is not None else None
            if raw is None:
                self._reply(rid, error=f"read refused (outside the workspace, a link or not a file): {params.get('path')}")
                return
            data = raw.decode("utf-8", "replace")
            line, limit = params.get("line"), params.get("limit")
            if isinstance(line, int) and line > 0:
                rows = data.splitlines(keepends=True)[line - 1:]
                data = "".join(rows[:limit] if isinstance(limit, int) and limit > 0 else rows)
            self._reply(rid, {"content": data})
        elif method == "fs/write_text_file":
            rel = _relative(self.workspace, params.get("path"))
            content = params.get("content")
            if rel is None or rel not in self.allowed or not isinstance(content, str) or len(content) > MAX_READ \
                    or not self._write_file(rel, content.encode("utf-8")):
                self._reply(rid, error=f"write refused (not an allowed regular file): {params.get('path')}")
                return
            self.result.writes.append(rel)
            self._reply(rid, {})
        elif method == "session/request_permission":
            option, why = choose_permission(params)
            self.result.permissions.append({"tool": (params.get("toolCall") or {}).get("title", ""),
                                            "kind": (params.get("toolCall") or {}).get("kind", ""),
                                            "chosen": option, "why": why})
            self._reply(rid, {"outcome": {"outcome": "selected", "optionId": option}} if option
                        else {"outcome": {"outcome": "cancelled"}})
        else:  # terminal/* and anything else the client never offered
            self._reply(rid, error=f"{method} is not offered by this client", code=-32601)

    def _read_file(self, rel: str) -> bytes | None:
        try:
            fd = _open_inside(self.workspace, rel, os.O_RDONLY)
        except OSError:
            return None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:  # a hard link may name a file outside
                return None
            chunks, size = [], 0
            while size < MAX_READ:
                chunk = os.read(fd, min(65536, MAX_READ - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _write_file(self, rel: str, data: bytes) -> bool:
        try:
            fd = _open_inside(self.workspace, rel, os.O_WRONLY | os.O_CREAT)
        except OSError:
            return False
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:  # a hard link may name a file outside
                return False
            os.ftruncate(fd, 0)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            return True
        finally:
            os.close(fd)

    def _update(self, update: Any) -> None:
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content")
            if isinstance(content, dict) and content.get("type") == "text":
                self.result.messages.append(str(content.get("text", "")))
        elif kind in {"tool_call", "tool_call_update"}:
            self.result.tool_calls.append({k: update.get(k) for k in ("toolCallId", "title", "kind", "status")
                                           if update.get(k) is not None})

    # -- capability probe (no session, no model call) ------------------------------------------------------------
    def probe(self, timeout_s: float = 20.0) -> dict[str, Any]:
        """The agent's answer to `initialize` alone: whether it speaks ACP 1, who it is, what it can do and how it
        authenticates. No session is created, so no model is called."""
        deadline = self._deadline = time.monotonic() + timeout_s
        self._start()
        try:
            init = self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True}, "terminal": False}}, deadline) or {}
            return {"acp": init.get("protocolVersion") == PROTOCOL_VERSION, "protocol_version": init.get("protocolVersion"),
                    "agent": init.get("agentInfo") or {}, "capabilities": init.get("agentCapabilities") or {},
                    "auth_methods": [m.get("id") for m in init.get("authMethods") or [] if isinstance(m, dict)]}
        except TimeoutError:
            return {"acp": False, "problem": "no answer to initialize within the time limit"}
        except (AcpError, OSError, AttributeError, TypeError, ValueError) as exc:
            return {"acp": False, "problem": str(exc)[:300]}
        finally:
            self.close()

    # -- one run ---------------------------------------------------------------------------------------------------
    def _start(self) -> None:
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        assert self.proc.stdin is not None
        os.set_blocking(self.proc.stdin.fileno(), False)

    def run(self, prompt: str, timeout_s: float) -> AcpResult:
        deadline = self._deadline = time.monotonic() + timeout_s
        self._start()
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
                self._deadline = time.monotonic() + 1.0  # a short grace to say so, never a hang
                try:
                    self._send({"method": "session/cancel", "params": {"sessionId": self.result.session_id}})
                except (OSError, TimeoutError):
                    pass
        except (AcpError, OSError, AttributeError, TypeError, ValueError) as exc:
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
            pass
        try:  # always: a child the agent started must not outlive the run
            os.killpg(self.proc.pid, 9)
        except OSError:
            pass
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
