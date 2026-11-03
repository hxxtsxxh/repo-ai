"""Queue row 31 with real bubblewrap and the network (a security-fixture module: CI only, REPO_AI_SECURITY_FIXTURES=1).
A live sandbox with its own network namespace reaches the internet only through the egress proxy: proxied HTTPS to a
public host works, a direct connection does not, the proxy refuses loopback and metadata targets, and a host abstract
unix socket and a host loopback service are unreachable from inside. The "provider" is curl or the system python."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from repo_ai.providers import adapters, egress


def _bwrap_works() -> bool:
    bwrap = shutil.which("bwrap")
    if not sys.platform.startswith("linux") or not bwrap:
        return False
    return subprocess.run([bwrap, "--ro-bind", "/", "/", "true"], capture_output=True, check=False).returncode == 0


_WORKS = _bwrap_works() and egress.system_python() is not None and shutil.which("curl") is not None
if os.environ.get("REPO_AI_EXPECT_BWRAP") == "1" and not _WORKS:
    raise RuntimeError("REPO_AI_EXPECT_BWRAP=1 but bubblewrap, a system python3 or curl is missing")
pytestmark = pytest.mark.skipif(not _WORKS, reason="needs bubblewrap, a system python3 and curl (CI)")


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


@pytest.fixture
def sandbox(tmp_path):
    ws, sc = tmp_path / "ws", tmp_path / "scratch"
    ws.mkdir()
    sc.mkdir()
    curl = Path(shutil.which("curl")).resolve()
    with egress.EgressProxy(sc / "egress.sock") as proxy:
        shutil.copy2(egress.FORWARDER, sc / "egress_forwarder.py")
        prefix = adapters._execution_sandbox_prefix(ws, sc, allow_network=True, provider="codex", live=True,
                                                    executable=curl, own_network=True)
        assert prefix is not None and "--unshare-net" in prefix

        def run(*argv: str, timeout: float = 60) -> subprocess.CompletedProcess:
            full = [*prefix, str(egress.system_python()), "-I", str(sc / "egress_forwarder.py"),
                    str(sc / "egress.sock"), "--", *argv]
            return subprocess.run(full, cwd=ws, capture_output=True, text=True, timeout=timeout,
                                  pass_fds=adapters.pinned_fds(prefix))
        yield run, proxy


def test_proxied_https_to_a_public_host_works_and_a_direct_connection_does_not(sandbox):
    run, proxy = sandbox
    if not _resolves("github.com"):
        pytest.skip("the host itself cannot resolve github.com")
    ok = run("curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30", "https://github.com")
    assert ok.returncode == 0 and ok.stdout.strip() in {"200", "301", "302"}, (ok.stdout, ok.stderr)
    assert "github.com" in proxy.summary()["allowed_hosts"]
    direct = run("curl", "-sS", "--noproxy", "*", "--max-time", "10", "https://github.com")
    assert direct.returncode != 0, direct.stdout


@pytest.mark.parametrize("url,why", [("https://localhost", "(not a public address)"),   # resolved, then refused
                                     ("https://127.0.0.1", "CONNECT 127.0.0.1:443"),     # a literal: refused unparsed
                                     ("https://169.254.169.254", "CONNECT 169.254.169.254:443")])
def test_the_proxy_refuses_loopback_and_metadata_targets(sandbox, url, why):
    run, proxy = sandbox
    out = run("curl", "-sS", "--max-time", "10", url)
    assert out.returncode != 0
    assert any(why in r for r in proxy.summary()["refused"]), proxy.summary()
    assert not proxy.summary()["allowed_hosts"]


def test_host_abstract_socket_and_loopback_service_are_unreachable(sandbox):
    run, _ = sandbox
    abstract = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    abstract.bind("\0repo-ai-egress-test")
    abstract.listen(1)
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(1)
    port = tcp.getsockname()[1]
    try:
        probe = ("import socket, sys\nr = []\n"
                 "s = socket.socket(socket.AF_UNIX)\ntry:\n    s.connect('\\0repo-ai-egress-test'); r.append('abstract')\n"
                 "except OSError:\n    pass\n"
                 "t = socket.socket()\nt.settimeout(3)\ntry:\n    t.connect(('127.0.0.1', int(sys.argv[1]))); r.append('tcp')\n"
                 "except OSError:\n    pass\nprint(','.join(r) or 'none')\n")
        out = run(str(egress.system_python()), "-I", "-c", probe, str(port))
        assert out.stdout.strip() == "none", (out.stdout, out.stderr)
    finally:
        abstract.close()
        tcp.close()


def test_the_forwarder_returns_the_providers_exit_status(sandbox):
    run, _ = sandbox
    out = run(str(egress.system_python()), "-I", "-c", "import sys; sys.exit(7)")
    assert out.returncode == 7
