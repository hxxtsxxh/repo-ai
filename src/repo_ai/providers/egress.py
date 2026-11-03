"""Linux live runs without the host's network namespace (opt-in: REPO_AI_LINUX_EGRESS_PROXY=1; queue row 31).

A live provider needs the network, so its bubblewrap sandbox used to share the host's network namespace: abstract
unix sockets (an X11 or Xwayland server that grants local same-user access, D-Bus) and every service listening on the
host's network, loopback included (debugger ports, notebooks, databases, cloud metadata), stayed reachable. With this
option the sandbox gets its own network namespace (`--unshare-net`: only its own loopback; abstract sockets are per
namespace), and the provider reaches the internet only through this module:

- `EgressProxy`, in the repo-ai process outside the sandbox, listens on a unix socket in the run's scratch directory
  (bound into the sandbox). It accepts only `CONNECT host:443`, resolves the host once, refuses unless every address is
  global unicast (no loopback, private, link-local, CGNAT, multicast or reserved address: cloud metadata at
  169.254.169.254 included), and connects to the address it checked, so a DNS answer cannot change between the check
  and the connection. TLS passes through untouched: it sees host names and byte counts, nothing else.
- `FORWARDER` runs inside the sandbox as the provider's parent: it listens on the sandbox's own 127.0.0.1, forwards
  each connection to that unix socket, and starts the provider with HTTPS_PROXY/HTTP_PROXY pointing at it.

A provider whose HTTP client ignores HTTPS_PROXY cannot reach the network at all with this on (it fails closed). Not
live-verified with the real Claude Code, Codex or Bob CLIs on Linux.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import threading
from pathlib import Path
from typing import Any, Callable

ENV_FLAG = "REPO_AI_LINUX_EGRESS_PROXY"
ALLOWED_PORTS = frozenset({443})
MAX_HEADER = 8192
MAX_CONNECTIONS = 512          # per run
CONNECT_TIMEOUT_S = 15.0
IDLE_TIMEOUT_S = 600.0
MAX_RECORDED = 50
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def parse_connect(head: bytes) -> tuple[str, int] | None:
    """(host, port) of a `CONNECT host:port HTTP/1.x` request head, or None. Host names only (no IP literals: the
    policy is applied to what the name resolves to, and a literal skips nothing), a port from ALLOWED_PORTS."""
    try:
        line = head.split(b"\r\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    parts = line.split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or parts[2] not in ("HTTP/1.1", "HTTP/1.0"):
        return None
    host, sep, port_text = parts[1].rpartition(":")
    if not sep or not port_text.isdigit() or not _HOST.fullmatch(host) or ".." in host:
        return None
    try:
        ipaddress.ip_address(host)
        return None  # an address literal: refused, so every connection goes through name resolution and the policy
    except ValueError:
        pass
    port = int(port_text)
    return (host.lower(), port) if port in ALLOWED_PORTS else None


def allowed_addresses(infos: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """The getaddrinfo results to connect to: all of them must be global unicast, else none (a name that also
    resolves to an internal address is refused outright rather than filtered, so it cannot be used to probe)."""
    out = []
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except (ValueError, IndexError, TypeError):
            return []
        if not address.is_global or address.is_multicast:
            return []
        out.append(info)
    return out


class EgressProxy:
    """A CONNECT-only proxy on a unix socket, for one run (a context manager). `resolve` is injectable for tests."""

    def __init__(self, path: Path, *, resolve: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
                 connect_timeout_s: float = CONNECT_TIMEOUT_S, idle_timeout_s: float = IDLE_TIMEOUT_S) -> None:
        self.path = path
        self._resolve = resolve
        self._connect_timeout = connect_timeout_s
        self._idle_timeout = idle_timeout_s
        self._server: socket.socket | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.connections = 0
        self.allowed: list[str] = []
        self.refused: list[str] = []

    def __enter__(self) -> EgressProxy:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o077)  # only this user may connect (the sandboxed provider runs as this user)
        try:
            server.bind(str(self.path))
        finally:
            os.umask(old)
        server.listen(64)
        server.settimeout(0.5)
        self._server = server
        threading.Thread(target=self._accept, name="repo-ai-egress", daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.close()
        try:
            self.path.unlink()
        except OSError:
            pass

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {"connections": self.connections, "allowed_hosts": sorted(set(self.allowed))[:MAX_RECORDED],
                    "refused": self.refused[:MAX_RECORDED]}

    def _note(self, bucket: list[str], item: str) -> None:
        with self._lock:
            if len(bucket) < MAX_RECORDED:
                bucket.append(item[:200])

    def _accept(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self.connections += 1
                over = self.connections > MAX_CONNECTIONS
            if over:
                client.close()
                continue
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        upstream = None
        try:
            client.settimeout(self._connect_timeout)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(1024)
                if not chunk or len(head) + len(chunk) > MAX_HEADER:
                    return
                head += chunk
            target = parse_connect(head)
            if target is None:
                self._note(self.refused, head.split(b"\r\n", 1)[0].decode("ascii", "replace"))
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            host, port = target
            try:
                infos = allowed_addresses(self._resolve(host, port, type=socket.SOCK_STREAM))
            except OSError:
                infos = []
            if not infos:
                self._note(self.refused, f"{host}:{port} (not a public address)")
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            family, kind, proto, _, address = infos[0]
            upstream = socket.socket(family, kind, proto)
            upstream.settimeout(self._connect_timeout)
            upstream.connect(address)  # exactly the address the policy checked
            self._note(self.allowed, host)
            rest = head.split(b"\r\n\r\n", 1)[1]
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
            client.settimeout(self._idle_timeout)
            upstream.settimeout(self._idle_timeout)
            back = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
            back.start()
            _pipe(client, upstream)
            back.join(self._idle_timeout)
        except OSError:
            pass
        finally:
            for s in (client, upstream):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


FORWARDER = Path(__file__).with_name("egress_forwarder.py")
SYSTEM_PYTHONS = ("/usr/bin/python3", "/usr/local/bin/python3")


def system_python() -> Path | None:
    """A system interpreter for the forwarder: outside HOME and the hidden directories, so the sandbox sees it
    without binding anything back (repo-ai's own interpreter may live in a hidden virtualenv)."""
    for candidate in SYSTEM_PYTHONS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return Path(candidate)
    return None
