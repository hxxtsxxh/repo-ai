"""Queue row 31, the egress proxy's decisions (no socket, no network, no process): which CONNECT requests it parses,
which resolved addresses it connects to, and that the Linux live prefix gets its own network namespace."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from repo_ai.providers import adapters, egress


@pytest.mark.parametrize("head,want", [
    (b"CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: x\r\n\r\n", ("api.anthropic.com", 443)),
    (b"CONNECT Chatgpt.COM:443 HTTP/1.0\r\n\r\n", ("chatgpt.com", 443)),
    (b"CONNECT example.com:80 HTTP/1.1\r\n\r\n", None),             # only 443
    (b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n", None),              # address literals are refused
    (b"CONNECT 169.254.169.254:443 HTTP/1.1\r\n\r\n", None),
    (b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n", None),
    (b"GET http://example.com/ HTTP/1.1\r\n\r\n", None),            # CONNECT only
    (b"CONNECT a..b:443 HTTP/1.1\r\n\r\n", None),
    (b"CONNECT -bad.example:443 HTTP/1.1\r\n\r\n", None),
    (b"CONNECT example.com:443 HTTP/2\r\n\r\n", None),
    (b"CONNECT ex\xffample.com:443 HTTP/1.1\r\n\r\n", None),
])
def test_parse_connect(head, want):
    assert egress.parse_connect(head) == want


def _info(address: str) -> tuple:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (address, 443))


@pytest.mark.parametrize("addresses,allowed", [
    (["93.184.216.34"], True),
    (["2606:2800:220:1:248:1893:25c8:1946"], True),
    (["127.0.0.1"], False),
    (["10.0.0.5"], False),
    (["192.168.1.1"], False),
    (["172.16.0.1"], False),
    (["169.254.169.254"], False),                  # cloud metadata
    (["100.64.0.1"], False),                       # CGNAT
    (["::1"], False),
    (["fe80::1"], False),
    (["fd00::1"], False),
    (["224.0.0.1"], False),
    (["93.184.216.34", "10.0.0.5"], False),        # a name that also resolves internally is refused outright
])
def test_allowed_addresses(addresses, allowed):
    infos = [_info(a) for a in addresses]
    assert (egress.allowed_addresses(infos) == infos) is allowed


def test_it_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv(egress.ENV_FLAG, raising=False)
    assert not egress.enabled()
    monkeypatch.setenv(egress.ENV_FLAG, "1")
    assert egress.enabled()


@pytest.mark.skipif(sys.platform == "win32", reason="the Linux sandbox uses POSIX open flags")
def test_the_live_prefix_gets_its_own_network_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    monkeypatch.setattr(adapters.shutil, "which", lambda name, path=None: "/usr/bin/bwrap" if name == "bwrap" else None)
    ws, sc = tmp_path / "w", tmp_path / "s"
    ws.mkdir()
    sc.mkdir()
    shared = adapters._execution_sandbox_prefix(ws, sc, allow_network=True, provider="codex", live=True,
                                                executable=Path("/usr/bin/true"), dry_run=True)
    own = adapters._execution_sandbox_prefix(ws, sc, allow_network=True, provider="codex", live=True,
                                             executable=Path("/usr/bin/true"), dry_run=True, own_network=True)
    assert "--unshare-net" not in shared and "--unshare-net" in own


@pytest.mark.parametrize("address,public", [
    ("64:ff9b::a00:1", False),          # NAT64 of 10.0.0.1
    ("64:ff9b::a9fe:a9fe", False),      # NAT64 of 169.254.169.254
    ("64:ff9b::5db8:d822", True),       # NAT64 of a public address (DNS64 for an IPv4-only host)
    ("64:ff9b:1::1", False),            # local-use NAT64
    ("::127.0.0.1", False),             # IPv4-compatible
    ("::ffff:10.0.0.1", False),         # IPv4-mapped
    ("fec0::1", False),                 # site-local
    ("2002:a00:1::1", False),           # 6to4
    ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),  # Teredo
    ("168.63.129.16", False),           # Azure host-local
    ("fe80::1%eth0", False),
])
def test_public_address_judges_embedded_ipv4(address, public):
    """Review of #119: these passed `is_global` on some or all Python versions."""
    assert egress.public_address(address) is public


def test_refused_request_lines_are_recorded_printable(tmp_path):
    proxy = egress.EgressProxy(tmp_path / "x.sock")
    proxy._note(proxy.refused, "CONNECT \x1b[31mevil:443 HTTP/1.1")
    assert proxy.summary()["refused"] == ["CONNECT ?[31mevil:443 HTTP/1.1"]


def test_the_isolation_probe_runs_through_the_forwarder(tmp_path, monkeypatch):
    seen = []

    def fake_capture(cmd, *a, **k):
        seen.append(cmd)
        from repo_ai.providers.discovery import ProbeResult
        return ProbeResult(1, "complete", b"", b"")
    monkeypatch.setattr(adapters, "_capture", fake_capture)
    head = ["/usr/bin/python3", "-I", "/s/egress_forwarder.py", "/s/egress.sock", "--"]
    adapters._claude_isolation_probe(["/usr/bin/bwrap", "--"], ["/x/claude", "-p", "hi"], tmp_path, {},
                                     read_only=False, head=head)
    cmd = seen[0]
    assert cmd[2:7] == head and cmd[7:10] == ["/x/claude", "--model", adapters.ISOLATION_PROBE_MODEL]


def test_routing_is_not_ready_without_a_system_python(monkeypatch):
    from repo_ai.providers import registry
    monkeypatch.setattr(registry.sys, "platform", "linux")
    monkeypatch.setenv(egress.ENV_FLAG, "1")
    monkeypatch.setattr(egress, "system_python", lambda: None)
    assert registry._isolated_ready("codex") is False


def test_run_provider_builds_the_live_prefix_with_its_own_network(tmp_path, monkeypatch):
    """The wiring: with the flag on Linux, run_provider starts the proxy and asks for an own-network prefix."""
    import contextlib

    class Sentinel(Exception):
        pass

    @contextlib.contextmanager
    def dummy_proxy(path):
        yield type("P", (), {"summary": lambda self: {"connections": 0}})()
    seen = {}

    def capture_prefix(*a, **k):
        seen.update(k)
        raise Sentinel()
    monkeypatch.setenv(egress.ENV_FLAG, "1")
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    monkeypatch.setattr(egress, "system_python", lambda: Path("/usr/bin/python3"))
    monkeypatch.setattr(egress, "EgressProxy", dummy_proxy)
    monkeypatch.setattr(adapters, "_execution_sandbox_prefix", capture_prefix)
    exe = tmp_path / "codex"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    root, ws = tmp_path / "root", tmp_path / "ws"
    root.mkdir()
    ws.mkdir()
    with pytest.raises(Sentinel):
        adapters.run_provider("codex", root, ws, "Fix", write_paths=["m.py"], executable=exe, simulated=False,
                              allow_live=True, max_cost_usd=0.0)
    assert seen.get("own_network") is True
