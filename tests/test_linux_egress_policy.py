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
