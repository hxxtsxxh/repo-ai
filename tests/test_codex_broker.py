"""The Codex credential broker: the token stays outside the sandbox; Codex reaches the model through loopback only."""
from __future__ import annotations

import base64
import http.client
import http.server
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from repo_ai.providers import codex_broker as cb

REAL = "sk-test-real-credential-0123456789abcdef"


def _jwt(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _auth(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "login" / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------- reading the login

def test_login_modes(tmp_path):
    up = cb.upstream_from_login(_auth(tmp_path, {"OPENAI_API_KEY": REAL}))
    assert up.mode == "api_key" and up.url == cb.API_UPSTREAM and up.headers == {"Authorization": f"Bearer {REAL}"}
    assert REAL not in repr(up)
    access = _jwt(int(time.time()) + 3600)
    up = cb.upstream_from_login(_auth(tmp_path, {"OPENAI_API_KEY": None,
                                                 "tokens": {"access_token": access, "account_id": "acct-1"}}))
    assert up.mode == "chatgpt" and up.url == cb.CHATGPT_UPSTREAM
    assert up.headers == {"Authorization": f"Bearer {access}", "chatgpt-account-id": "acct-1"}


@pytest.mark.parametrize("data,needle", [
    ({"tokens": {"access_token": _jwt(int(time.time()) - 10)}}, "expired"),
    ({"tokens": {"access_token": _jwt(int(time.time()) + 30)}}, "expired"),
    ({"OPENAI_API_KEY": None, "tokens": {}}, "neither"),
    ([], "JSON object"),
])
def test_unusable_logins_are_refused(tmp_path, data, needle):
    with pytest.raises(cb.BrokerError, match=needle):
        cb.upstream_from_login(_auth(tmp_path, data))


def test_a_linked_or_missing_auth_file_is_refused(tmp_path):
    target = _auth(tmp_path, {"OPENAI_API_KEY": REAL})
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(cb.BrokerError):
        cb.upstream_from_login(link)
    with pytest.raises(cb.BrokerError):
        cb.upstream_from_login(tmp_path / "nope.json")


def test_only_https_or_loopback_upstreams():
    with pytest.raises(cb.BrokerError):
        cb.Upstream("http://example.com/v1/responses", "api_key", {})


# ---------------------------------------------------------------- the proxy

class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: list[dict] = []
    reply: tuple[int, dict, bytes] = (200, {"Content-Type": "text/event-stream"}, b"data: one\n\ndata: two\n\n")

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": self.rfile.read(n)})
        code, headers, body = type(self).reply
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def upstream():
    class Handler(_Upstream):
        seen: list[dict] = []
        reply = _Upstream.reply
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, Handler
    server.shutdown()
    server.server_close()


def _post(broker, *, key=None, path="/v1/responses", body=b'{"model":"m","stream":true}', headers=None):
    port = int(broker.base_url.rsplit(":", 1)[1].split("/")[0])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, body=body, headers={"Authorization": f"Bearer {key or broker.key}",
                                                     "Content-Type": "application/json", "originator": "codex_exec",
                                                     **(headers or {})})
    resp = conn.getresponse()
    out = resp.status, resp.getheader("Content-Type"), resp.read()
    conn.close()
    return out


def _up(server, path="/v1/responses"):
    return cb.Upstream(f"http://127.0.0.1:{server.server_address[1]}{path}", "chatgpt",
                       {"Authorization": f"Bearer {REAL}", "chatgpt-account-id": "acct-1"})


def test_a_request_is_forwarded_with_the_real_credential_and_streamed_back(upstream):
    server, handler = upstream
    with cb.Broker(_up(server), timeout_s=10) as broker:
        status, ctype, body = _post(broker)
        summary = broker.summary()
    assert (status, ctype, body) == (200, "text/event-stream", b"data: one\n\ndata: two\n\n")
    (seen,) = handler.seen
    assert seen["path"] == "/v1/responses" and seen["body"] == b'{"model":"m","stream":true}'
    assert seen["headers"]["authorization"] == f"Bearer {REAL}" and seen["headers"]["chatgpt-account-id"] == "acct-1"
    assert seen["headers"]["originator"] == "codex_exec"
    assert summary == {"mode": "chatgpt", "requests": 1, "statuses": [200], "refused": []}
    assert REAL not in json.dumps(summary)


@pytest.mark.parametrize("kw,code", [({"key": "wrong"}, 401), ({"path": "/v1/models"}, 404),
                                     ({"path": "/v1/responses/../x"}, 404)])
def test_wrong_keys_and_paths_never_reach_the_upstream(upstream, kw, code):
    server, handler = upstream
    with cb.Broker(_up(server), timeout_s=10) as broker:
        status, _, body = _post(broker, **kw)
    assert status == code and b"repo-ai broker" in body and not handler.seen


def test_get_is_refused(upstream):
    server, handler = upstream
    with cb.Broker(_up(server), timeout_s=10) as broker:
        port = int(broker.base_url.rsplit(":", 1)[1].split("/")[0])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/v1/responses", headers={"Authorization": f"Bearer {broker.key}"})
        assert conn.getresponse().status == 405
    assert not handler.seen


def test_an_oversized_body_and_too_many_requests_are_refused(upstream):
    server, handler = upstream
    with cb.Broker(_up(server), timeout_s=10, max_requests=1) as broker:
        port = int(broker.base_url.rsplit(":", 1)[1].split("/")[0])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.putrequest("POST", "/v1/responses")
        conn.putheader("Authorization", f"Bearer {broker.key}")
        conn.putheader("Content-Length", str(cb.MAX_BODY + 1))
        conn.endheaders()
        assert conn.getresponse().status == 413
        conn.close()
        assert _post(broker)[0] == 429  # the oversized one counted against the limit
    assert not handler.seen


def test_a_redirect_is_never_followed_with_the_credential(upstream):
    server, handler = upstream
    handler.reply = (302, {"Location": f"http://127.0.0.1:{server.server_address[1]}/elsewhere"}, b"")
    with cb.Broker(_up(server), timeout_s=10) as broker:
        status, _, _ = _post(broker)
    assert status == 302 and [s["path"] for s in handler.seen] == ["/v1/responses"]


def test_upstream_errors_are_passed_back_and_an_unreachable_one_is_502(upstream):
    server, handler = upstream
    handler.reply = (401, {"Content-Type": "application/json"}, b'{"error":"bad token"}')
    with cb.Broker(_up(server), timeout_s=10) as broker:
        assert _post(broker)[:3] == (401, "application/json", b'{"error":"bad token"}')
        assert broker.summary()["statuses"] == [401]
    dead = cb.Upstream("http://127.0.0.1:9/v1/responses", "api_key", {"Authorization": "Bearer x"})
    with cb.Broker(dead, timeout_s=5) as broker:
        assert _post(broker)[0] == 502


def test_the_config_points_codex_at_the_broker_and_overrides_the_users_provider(upstream):
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    server, _ = upstream
    with cb.Broker(_up(server), timeout_s=10) as broker:
        cfg = tomllib.loads(broker.config_toml('model = "gpt-5"\nmodel_provider = "openai"\n'
                                               'preferred_auth_method = "chatgpt"\n'))
        assert cfg["model"] == "gpt-5" and cfg["model_provider"] == cb.PROVIDER_ID
        assert "preferred_auth_method" not in cfg
        provider = cfg["model_providers"][cb.PROVIDER_ID]
        assert provider["base_url"] == broker.base_url and provider["env_key"] == cb.KEY_ENV
        assert provider["wire_api"] == "responses"


def test_the_proxy_stops_with_the_run(upstream):
    server, _ = upstream
    with cb.Broker(_up(server), timeout_s=10) as broker:
        port = int(broker.base_url.rsplit(":", 1)[1].split("/")[0])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    with pytest.raises(OSError):
        conn.request("POST", "/v1/responses", body=b"{}")
        conn.getresponse()


# ---------------------------------------------------------------- a brokered live run (fake codex, fake upstream)

FAKE_CODEX = r'''#!{python} -I
import json, os, socket, urllib.request
home = os.environ["CODEX_HOME"]
cfg = open(os.path.join(home, "config.toml")).read()
base = cfg.split('base_url = "')[1].split('"')[0]
req = urllib.request.Request(base + "/responses", data=b'{{"model":"m"}}', method="POST",
                             headers={{"Authorization": "Bearer " + os.environ["REPO_AI_BROKER_KEY"],
                                       "Content-Type": "application/json"}})
report = {{"f": sorted(os.listdir(home)), "k": "OPENAI_API_KEY" in os.environ, "c": {real!r} in cfg,
           "u": urllib.request.urlopen(req, timeout=10).read().decode()[:9]}}
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3).close()
    report["n"] = "reachable"
except OSError:
    report["n"] = "denied"
print(json.dumps({{"type": "thread.started", "thread_id": "t"}}))
print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": json.dumps(report)}}}}))
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 1, "output_tokens": 1}}}}))
'''


@pytest.mark.skipif(sys.platform != "darwin", reason="the broker needs the macOS seatbelt loopback rule")
def test_a_brokered_run_has_no_token_inside_and_no_route_out(tmp_path, upstream, monkeypatch):
    from repo_ai.providers import adapters
    server, handler = upstream
    login = tmp_path / "login"
    _auth(tmp_path, {"OPENAI_API_KEY": REAL})
    (login / "config.toml").write_text('model = "gpt-5"\n')
    monkeypatch.setenv(adapters.CODEX_HOME_ENV, str(login))
    monkeypatch.setenv(cb.ENV_FLAG, "1")
    monkeypatch.setenv("OPENAI_API_KEY", REAL)  # even a key in the environment must not reach the sandbox
    monkeypatch.setattr(cb, "API_UPSTREAM", f"http://127.0.0.1:{server.server_address[1]}/v1/responses")
    exe = tmp_path / "bin" / "codex"
    exe.parent.mkdir()
    exe.write_text(FAKE_CODEX.format(python="/usr/bin/python3", real=REAL))  # the live profile hides a venv in HOME
    exe.chmod(0o755)
    (tmp_path / "root").mkdir()
    (tmp_path / "ws").mkdir()
    res = adapters.run_provider("codex", tmp_path / "root", tmp_path / "ws", "fix", write_paths=[],
                                executable=exe, timeout=30, simulated=False, allow_live=True)
    assert "codex_broker" in res, res
    text = json.dumps(res)
    assert REAL not in text
    assert res["codex_broker"]["requests"] == 1 and res["codex_broker"]["statuses"] == [200], res
    (seen,) = handler.seen
    assert seen["headers"]["authorization"] == f"Bearer {REAL}"
    report = json.loads(res["events"]["summary"])  # what the fake saw from inside the sandbox
    assert report["f"] == ["config.toml"] and not report["k"] and not report["c"]  # no token file, key or credential
    assert report["u"] == "data: one"  # the upstream's stream came back through the broker
    assert report["n"] == "denied"  # and no other host is reachable
    assert res["stage"] == "READY", res["reasons"]


def test_a_broker_without_a_usable_login_blocks_the_run(tmp_path, monkeypatch):
    from repo_ai.providers import adapters
    if sys.platform != "darwin":
        expected = "seatbelt"
    else:
        expected = "neither"
        _auth(tmp_path, {"OPENAI_API_KEY": None})
        monkeypatch.setenv(adapters.CODEX_HOME_ENV, str(tmp_path / "login"))
    monkeypatch.setenv(cb.ENV_FLAG, "1")
    (tmp_path / "root").mkdir()
    (tmp_path / "ws").mkdir()
    res = adapters.run_provider("codex", tmp_path / "root", tmp_path / "ws", "fix", write_paths=[],
                                executable=sys.executable, timeout=10, simulated=False, allow_live=True)
    assert res["stage"] == "BLOCKED" and any(expected in r for r in res["reasons"]), res["reasons"]
    assert os.environ.get(cb.ENV_FLAG) == "1"
