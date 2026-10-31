"""Codex credential broker: the login's token stays outside the sandbox (opt-in, macOS seatbelt only).

Without it, repo-ai copies the Codex login's `auth.json` into the run's scratch CODEX_HOME, where Codex's model
(which has a shell and the network) can read it. With `REPO_AI_CODEX_BROKER=1`, Codex instead gets a per-run dummy
key and a model provider whose `base_url` is a loopback proxy in the repo-ai process. The proxy checks the dummy key,
replaces it with the login's credential and forwards the request to the upstream API. The sandbox then admits
loopback traffic only: nothing inside it holds the token, and nothing inside it can reach another host.

The proxy accepts only `POST /v1/responses` carrying this run's dummy key, a bounded body and a bounded number of
requests, and only while the run lasts. Upstream redirects are never followed, since following one would send the
credential to another host. Tokens are never refreshed here: an expired ChatGPT token is refused with a message.

The model inside has a shell and can read the dummy key, so it can send its own requests through the proxy. Each
body is therefore vetted (`vet_request`), so that the upstream cannot be made to contact another host on the model's
behalf:
- only local tool types (functions run by Codex itself) are allowed, and the hosted `web_search` tool is removed;
- no URL other than a `data:` URL may appear in the input (a remote image or file URL would be fetched upstream);
- the model is pinned to the one the first request named, which Codex sends before any model output exists;
- nothing that brings in server-side state (a stored prompt with its own tools, a stored conversation or response, a
  background run that would outlive this one) is accepted, and duplicate JSON keys are refused, so the upstream
  parses exactly what was vetted (the vetted object is what is forwarded, re-serialised).

Evidence: docs/engineering/evidence/CODEX-BROKER-SPIKE-2026-10-31.md. An offline spike came first, then two live runs
on 2026-10-31 with a ChatGPT login on Codex 0.165: the ChatGPT backend accepted the forwarded requests. An API-key
login is not yet live-verified.
"""
from __future__ import annotations

import base64
import hmac
import http.client
import http.server
import json
import os
import re
import secrets
import stat
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ENV_FLAG = "REPO_AI_CODEX_BROKER"
KEY_ENV = "REPO_AI_BROKER_KEY"
PROVIDER_ID = "repo_ai_broker"
API_UPSTREAM = "https://api.openai.com/v1/responses"
CHATGPT_UPSTREAM = "https://chatgpt.com/backend-api/codex/responses"
MAX_AUTH_FILE = 1 << 20
MAX_BODY = 16 << 20           # one Responses request (the whole conversation so far)
MAX_REQUESTS = 256            # per run: a model calling the proxy itself spends quota, so this is bounded too
MAX_RECORDED = 50
EXPIRY_MARGIN_S = 120
# request headers Codex sends that the upstream may use; Authorization is always replaced, never forwarded
FORWARD_HEADERS = ("content-type", "accept", "openai-beta", "originator", "session_id", "conversation_id",
                   "user-agent", "version")
LOCAL_TOOL_TYPES = frozenset({"function", "custom", "local_shell"})  # executed by Codex, inside the sandbox
REMOVED_TOOL_TYPES = ("web_search",)  # hosted search: queries and fetches leave from the upstream (`web_search*`)
SERVER_STATE_KEYS = ("prompt", "conversation", "previous_response_id", "background")  # Codex sends none of these
MODEL_NAME = re.compile(r"[A-Za-z0-9._:/@+-]{1,128}")  # it is recorded in the run's summary: bounded and plain
MAX_CONCURRENT = 4
SOCKET_TIMEOUT_S = 60.0


class BrokerError(ValueError):
    pass


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


@dataclass(frozen=True)
class Upstream:
    url: str
    mode: str                                                   # api_key | chatgpt
    headers: dict[str, str] = field(repr=False)                 # the credential: never logged or returned

    def __post_init__(self) -> None:
        parts = urlsplit(self.url)
        if parts.scheme != "https" and parts.hostname not in {"127.0.0.1", "localhost"}:
            raise BrokerError("the broker forwards only to an https upstream")


def _jwt_exp(token: str) -> int | None:
    """The `exp` claim of a JWT, unverified (only to refuse a token that has already expired)."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    exp = claims.get("exp") if isinstance(claims, dict) else None
    return exp if isinstance(exp, int) else None


def upstream_from_login(auth_path: Path, *, now: float | None = None) -> Upstream:
    """The upstream and credential of a Codex login's `auth.json` (a regular file, never followed through a link)."""
    if auth_path.is_symlink():  # also where O_NOFOLLOW does not exist (Windows)
        raise BrokerError("the Codex login's auth.json is a link; refusing to follow it")
    try:
        fd = os.open(auth_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise BrokerError("the Codex login has no readable auth.json") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_AUTH_FILE:
            raise BrokerError("the Codex login's auth.json is not a regular file of a sane size")
        raw = os.read(fd, MAX_AUTH_FILE)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise BrokerError("the Codex login's auth.json is not JSON") from exc
    if not isinstance(data, dict):
        raise BrokerError("the Codex login's auth.json is not a JSON object")
    key = data.get("OPENAI_API_KEY")
    if isinstance(key, str) and key.strip():
        return Upstream(API_UPSTREAM, "api_key", {"Authorization": f"Bearer {key.strip()}"})
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
    access, account = tokens.get("access_token"), tokens.get("account_id")
    if not isinstance(access, str) or not access:
        raise BrokerError("the Codex login has neither an API key nor a ChatGPT access token")
    exp = _jwt_exp(access)
    if exp is not None and exp - (time.time() if now is None else now) < EXPIRY_MARGIN_S:
        raise BrokerError("the Codex login's access token has expired or is about to; run `codex login` for that "
                          "CODEX_HOME (the broker never refreshes a token)")
    headers = {"Authorization": f"Bearer {access}"}
    if isinstance(account, str) and account:
        headers["chatgpt-account-id"] = account
    return Upstream(CHATGPT_UPSTREAM, "chatgpt", headers)


def _tools_ok(tools: Any) -> tuple[list[Any], str]:
    """(the tools to forward, a refusal reason or "")."""
    if not isinstance(tools, list):
        return [], "tools is not a list"
    kept: list[Any] = []
    for tool in tools:
        kind = tool.get("type") if isinstance(tool, dict) else None
        if not isinstance(kind, str):
            return [], "a tool without a type"
        if kind.startswith(REMOVED_TOOL_TYPES):
            continue
        if kind == "namespace":  # a group of tools (Codex's sub-agents): every member must be local too
            members, why = _tools_ok(tool.get("tools", []))
            if why:
                return [], why
            if _remote_url({k: v for k, v in tool.items() if k != "tools"}):
                return [], "a remote URL on a tool group"
            kept.append({**tool, "tools": members})
        elif kind in LOCAL_TOOL_TYPES:
            kept.append(tool)
        else:
            return [], f"tool type {kind[:40]!r} would run at the upstream"
    return kept, ""


def _remote_url(value: Any) -> bool:
    """Anything in the input that names a remote resource for the upstream to fetch."""
    if isinstance(value, dict):
        return any((("url" in str(k).lower() or k == "file_id") and isinstance(v, str) and not v.startswith("data:"))
                   or _remote_url(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_remote_url(v) for v in value)
    return False


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):  # parsers differ on which duplicate wins: never let one be vetted, another used
        raise ValueError("duplicate key")
    return dict(pairs)


def vet_request(body: bytes, pinned_model: str | None) -> tuple[bytes, str, str]:
    """(the body to forward, re-serialised from the vetted object; its model; a refusal reason or "")."""
    try:
        data = json.loads(body, object_pairs_hook=_unique)
    except (ValueError, RecursionError):
        return b"", "", "the body is not JSON without duplicate keys"
    if not isinstance(data, dict):
        return b"", "", "the body is not a JSON object"
    model = data.get("model")
    if not isinstance(model, str) or not MODEL_NAME.fullmatch(model):
        return b"", "", "no model named, or not a plain model name"
    if pinned_model is not None and model != pinned_model:
        return b"", "", f"model {model[:60]!r} is not this run's model"
    present = [k for k in SERVER_STATE_KEYS if data.get(k) not in (None, False)]
    if present:
        return b"", "", f"server-side state is not brokered ({', '.join(present)})"
    if "instructions" in data and not isinstance(data["instructions"], str):
        return b"", "", "instructions is not text"
    try:
        if _remote_url({k: v for k, v in data.items() if k != "tools"}):
            return b"", "", "a remote URL or file reference in the request (the upstream would fetch it)"
        if "tools" in data:
            tools, why = _tools_ok(data["tools"])
            if why:
                return b"", "", why
            data["tools"] = tools
    except RecursionError:
        return b"", "", "the request is nested too deeply"
    # ASCII escapes: valid JSON for any string the parser accepted (a lone surrogate cannot be UTF-8 encoded)
    return json.dumps(data, separators=(",", ":")).encode(), model, ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a 3xx is returned as an HTTPError, so the credential never reaches the redirect's host


class _Handler(http.server.BaseHTTPRequestHandler):
    server: _Server
    timeout = SOCKET_TIMEOUT_S  # a client that stalls mid-request cannot hold a thread forever

    def log_message(self, *args: Any) -> None:  # nothing about requests reaches a log
        pass

    def _refuse(self, code: int, why: str) -> None:
        self.server.broker._record(refused=f"{code} {why}")
        body = json.dumps({"error": {"message": f"repo-ai broker: {why}", "type": "broker_refused"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._refuse(405, "only POST /v1/responses is brokered")

    do_PUT = do_DELETE = do_PATCH = do_GET

    def do_HEAD(self) -> None:
        self.server.broker._record(refused="405 HEAD")
        self.send_response(405)
        self.end_headers()

    def do_POST(self) -> None:
        broker = self.server.broker
        if self.path != "/v1/responses":
            self._refuse(404, "only POST /v1/responses is brokered")
            return
        expected = f"Bearer {broker.key}".encode()
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected):
            self._refuse(401, "wrong broker key")
            return
        if not broker._take_request():
            self._refuse(429, "request limit for this run reached")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self._refuse(413, "request body missing or too large")
            return
        if not broker._slots.acquire(timeout=SOCKET_TIMEOUT_S):
            self._refuse(503, "too many concurrent requests")
            return
        try:
            self._forward(broker, length)
        finally:
            broker._slots.release()

    def _forward(self, broker: Broker, length: int) -> None:
        try:
            body = self.rfile.read(length)
        except OSError:  # stalled or gone (the socket timeout)
            return
        if len(body) != length:
            return
        body, model, why = vet_request(body, broker._model())
        if why:
            self._refuse(400, why)
            return
        if not broker._pin(model):  # two concurrent first requests: the pin is taken once
            self._refuse(400, f"model {model[:60]!r} is not this run's model")
            return
        headers = {name: value for name in FORWARD_HEADERS if (value := self.headers.get(name))}
        headers.update(broker.upstream.headers)
        request = urllib.request.Request(broker.upstream.url, data=body, headers=headers, method="POST")
        try:
            response: Any = broker._open(request)
        except urllib.error.HTTPError as exc:  # the upstream's own error answer (4xx/5xx, or a refused redirect)
            response = exc
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, ValueError):
            self._refuse(502, "upstream unreachable")
            return
        status = getattr(response, "status", None) or response.getcode()
        broker._record(status=int(status))
        try:
            self.send_response(int(status))
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/octet-stream"))
            self.end_headers()  # HTTP/1.0 and no length: the body ends when the connection closes (SSE streams)
            while chunk := response.read(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException, ValueError):
            pass  # Codex went away mid-stream (the run ended or timed out), or the upstream broke off
        finally:
            response.close()


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    broker: Broker


class Broker:
    """One run's proxy: `with Broker(upstream, timeout_s=...) as b:` then point Codex at `b.base_url`/`b.key`."""

    def __init__(self, upstream: Upstream, *, timeout_s: float, max_requests: int = MAX_REQUESTS):
        self.upstream = upstream
        self.key = secrets.token_urlsafe(32)
        self.timeout_s = timeout_s
        self.max_requests = max_requests
        self.requests = 0
        self.statuses: list[int] = []
        self.refused: list[str] = []
        self.model: str | None = None
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Broker:
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.broker = self
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def config_toml(self, model_keys: str = "") -> str:
        """Codex's config.toml for the run: the user's plain model keys, but always this broker as the provider."""
        kept = [line for line in model_keys.splitlines()
                if line.strip() and not line.startswith(("model_provider", "preferred_auth_method"))]
        return "\n".join([*kept, f'model_provider = "{PROVIDER_ID}"', "", f"[model_providers.{PROVIDER_ID}]",
                          'name = "repo-ai broker"', f'base_url = "{self.base_url}"', f'env_key = "{KEY_ENV}"',
                          'wire_api = "responses"', "request_max_retries = 0", "stream_max_retries = 0", ""])

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {"mode": self.upstream.mode, "model": self.model, "requests": self.requests,
                    "statuses": self.statuses[:MAX_RECORDED], "refused": self.refused[:MAX_RECORDED]}

    def _model(self) -> str | None:
        with self._lock:
            return self.model

    def _pin(self, model: str) -> bool:
        with self._lock:
            if self.model is None:
                self.model = model
            return self.model == model

    def _take_request(self) -> bool:
        with self._lock:
            if self.requests >= self.max_requests:
                return False
            self.requests += 1
            return True

    def _record(self, *, status: int | None = None, refused: str | None = None) -> None:
        with self._lock:
            if status is not None and len(self.statuses) < MAX_RECORDED:
                self.statuses.append(status)
            if refused is not None and len(self.refused) < MAX_RECORDED:
                self.refused.append(refused)

    def _open(self, request: urllib.request.Request) -> Any:
        return self._opener.open(request, timeout=self.timeout_s)
