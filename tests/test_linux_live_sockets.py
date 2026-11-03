"""Queue rows 27 and 30, with real bubblewrap (the sandbox-bwrap CI jobs; a security-fixture module, so it runs only
with REPO_AI_SECURITY_FIXTURES=1): inside a live Codex/Claude sandbox, a unix socket in a host socket directory
(`/tmp`) or under HOME cannot be reached, while the network resolver still works and an install directory under HOME
is readable; an install directory that holds a socket is not bound back. The "provider" is the test's own Python."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from repo_ai.providers import adapters, claude_auth
from repo_ai.providers import discovery as d


def _bwrap_works() -> bool:
    bwrap = shutil.which("bwrap")
    if not sys.platform.startswith("linux") or not bwrap:
        return False
    return subprocess.run([bwrap, "--ro-bind", "/", "/", "true"], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(not _bwrap_works(), reason="needs a working bubblewrap (the sandbox-bwrap CI jobs)")

PROBE = textwrap.dedent("""
    import json, os, socket, sys
    out = {}
    for name, path in (("tmp_socket", sys.argv[1]), ("home_socket", sys.argv[2])):
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(path)
            out[name] = "connected"
        except OSError as e:
            out[name] = type(e).__name__
        finally:
            s.close()
    try:
        socket.getaddrinfo(sys.argv[3], 443)
        out["dns"] = "ok"
    except OSError as e:
        out["dns"] = type(e).__name__
    out["install_readable"] = os.path.isfile(sys.argv[4])
    out["run_entries"] = sorted(os.listdir("/run"))[:5]
    print(json.dumps(out))
""")


def _listen(path: Path) -> socket.socket:
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(1)
    return s


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_host_sockets_are_unreachable_and_the_resolver_works(provider, tmp_path):
    home = Path.home().resolve()
    host_tmp = Path(tempfile.mkdtemp(prefix="rai-live-sock-", dir="/tmp"))
    home_dir = Path(tempfile.mkdtemp(prefix=".rai-live-sock-", dir=home))
    install = Path(tempfile.mkdtemp(prefix=".rai-live-inst-", dir=home))
    listeners = []
    try:
        listeners = [_listen(host_tmp / "s"), _listen(home_dir / "s")]
        (install / "bin").mkdir()
        marker = install / "bin" / "agent"
        marker.write_text("#!/bin/sh\n")
        workspace, scratch = tmp_path / "ws", tmp_path / "scratch"
        workspace.mkdir()
        scratch.mkdir()
        plan = claude_auth.ClaudeAuthPlan(mode="token_env", config_dir=None, env_vars=(), problems=()) \
            if provider == "claude" else None
        prefix = adapters._execution_sandbox_prefix(workspace, scratch, allow_network=True, provider=provider,
                                                    live=True, executable=marker, claude_plan=plan)
        assert prefix is not None
        if os.environ.get("REPO_AI_EXPECT_BWRAP_FD") == "1":
            assert "--ro-bind-fd" in prefix, prefix
        script = scratch / "probe.py"
        script.write_text(PROBE)
        host = "github.com"
        result = d._capture([*prefix, sys.executable, "-I", str(script), str(host_tmp / "s"), str(home_dir / "s"),
                             host, str(marker)], workspace, d._probe_env(scratch), pass_fds=d.pinned_fds(prefix))
        assert result.returncode == 0, result.output[-2000:]
        import json
        out = json.loads(result.output.decode().strip().splitlines()[-1])
        assert out["tmp_socket"] != "connected" and out["home_socket"] != "connected", out
        assert out["install_readable"] is True, out
        if _resolves(host):
            assert out["dns"] == "ok", out  # hiding /run must not take the resolver configuration with it
    finally:
        for s in listeners:
            s.close()
        for p in (host_tmp, home_dir, install):
            shutil.rmtree(p, ignore_errors=True)


def test_an_install_directory_holding_a_socket_is_not_bound_back(tmp_path):
    home = Path.home().resolve()
    install = Path(tempfile.mkdtemp(prefix=".rai-live-inst-", dir=home))
    listener = None
    try:
        listener = _listen(install / "s")
        (install / "agent").write_text("#!/bin/sh\n")
        args, fds = adapters._live_linux_binds(shutil.which("bwrap"), [install])
        try:
            assert str(install) not in [args[i + 2] for i, a in enumerate(args) if a in ("--ro-bind", "--ro-bind-fd")]
        finally:
            d._close_all(tuple(fds))
    finally:
        if listener:
            listener.close()
        shutil.rmtree(install, ignore_errors=True)
