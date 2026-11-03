"""Linux live runs without the host's network namespace (opt-in: REPO_AI_LINUX_EGRESS_PROXY=1; queue row 31).

A live provider needs the network, so its bubblewrap sandbox used to share the host's network namespace: abstract
unix sockets (an X11 or Xwayland server that grants local same-user access, D-Bus) and every service listening on the
host's network, loopback included (debugger ports, notebooks, databases, cloud metadata), stayed reachable. With this
option the sandbox gets its own network namespace (`--unshare-net`: only its own loopback; abstract sockets are per
namespace), and the provider reaches the internet only through this module:

- `EgressProxy`, in the repo-ai process outside the sandbox, listens on a unix socket in the run's scratch directory
  (bound into the sandbox). It accepts only `CONNECT host:443`, resolves the host once, refuses unless every address is
  public (no loopback, private, link-local, site-local, CGNAT, multicast or reserved address, cloud metadata at
  169.254.169.254 included, judged on the IPv4 address an IPv6 form embeds), connects to an address it checked (so a
  DNS answer cannot change between the check and the connection) and never to this host's own address. The tunnel
  carries any TCP to port 443 of a public host: TLS is not inspected, so sending data to, or being controlled from, a
  public host on 443 is possible by design. It also resolves any name the model asks for (DNS can carry data out).
- `FORWARDER` runs inside the sandbox as the provider's parent: it listens on the sandbox's own 127.0.0.1, forwards
  each connection to that unix socket, and starts the provider with HTTPS_PROXY/HTTP_PROXY pointing at it.

A provider whose HTTP client ignores HTTPS_PROXY cannot reach the network at all with this on (it fails closed), and a
network that requires an outbound proxy is not supported (the proxy connects directly). Not closed by this: unix
sockets on the filesystem outside the hidden directories (e.g. a Nix daemon socket), and services on port 443 of
another host's public address (on an IPv6 LAN every device has one). Not live-verified with the real Claude Code,
Codex or Bob CLIs on Linux.
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


_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")              # DNS64 synthesis: the embedded IPv4 address decides
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")      # local-use NAT64: refused
_V4_COMPAT = ipaddress.ip_network("::/96")
_HOST_LOCAL_V4 = frozenset({ipaddress.ip_address("168.63.129.16")})  # Azure's host-local WireServer


def _public_v4(address: ipaddress.IPv4Address) -> bool:
    return (address.is_global and not address.is_multicast and address not in _CGNAT
            and address not in _HOST_LOCAL_V4)


def public_address(text: str) -> bool:
    """Global unicast, judged on the IPv4 address an IPv6 form embeds (mapped, IPv4-compatible, 6to4, Teredo, NAT64),
    so the result does not depend on how a Python version classifies those ranges."""
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return _public_v4(address)
    if address.ipv4_mapped is not None:
        return _public_v4(address.ipv4_mapped)
    if address in _NAT64_LOCAL:
        return False
    if address in _NAT64:
        return _public_v4(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    if address in _V4_COMPAT:  # IPv4-compatible (deprecated), ::, ::1
        return False
    if address.sixtofour is not None or address.teredo is not None:
        return False  # tunnels that embed an IPv4 endpoint: refused rather than second-guessed
    return address.is_global and not address.is_multicast and not address.is_site_local


def allowed_addresses(infos: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """The getaddrinfo results to connect to: all of them must be public (`public_address`), else none (a name that
    also resolves to an internal address is refused outright rather than filtered, so it cannot be used to probe)."""
    out = []
    for info in infos:
        try:
            ok = public_address(str(info[4][0]))
        except (IndexError, TypeError):
            return []
        if not ok:
            return []
        out.append(info)
    return out


def _printable(text: str) -> str:
    return "".join(c if " " <= c <= "~" else "?" for c in text)[:200]


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
        server.bind(str(self.path))  # in the run's 0700 scratch directory
        os.chmod(self.path, 0o600)   # only this user may connect (the sandboxed provider runs as this user)
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
            return {"connections": self.connections, "cap_reached": self.connections > MAX_CONNECTIONS,
                    "allowed_hosts": sorted(set(self.allowed))[:MAX_RECORDED], "refused": self.refused[:MAX_RECORDED]}

    def _note(self, bucket: list[str], item: str) -> None:
        with self._lock:
            if len(bucket) < MAX_RECORDED:
                bucket.append(_printable(item))

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
        try:
            self._tunnel(client)
        except Exception:  # noqa: BLE001 - a model-controlled request must never kill the proxy thread noisily
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _tunnel(self, client: socket.socket) -> None:
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
            except (OSError, ValueError):  # ValueError: a name the resolver cannot encode (e.g. a label over 63)
                infos = []
            if not infos:
                self._note(self.refused, f"{host}:{port} (not a public address)")
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            upstream = self._connect(infos)  # one of exactly the addresses the policy checked
            if upstream is None:
                self._note(self.refused, f"{host}:{port} (no checked address accepted the connection, or it is "
                                         "this host's own address)")
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                return
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


    def _connect(self, infos: list[tuple[Any, ...]]) -> socket.socket | None:
        """The first checked address that accepts, in resolver order (a broken IPv6 route falls back to IPv4); never
        one of this host's own addresses (the proxy runs in the host's network namespace)."""
        for family, kind, proto, _, address in infos:
            upstream = socket.socket(family, kind, proto)
            upstream.settimeout(self._connect_timeout)
            try:
                upstream.connect(address)
                if upstream.getsockname()[0] == upstream.getpeername()[0]:
                    raise OSError("a connection to this host's own address")
                return upstream
            except OSError:
                upstream.close()
        return None


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
