"""`repo-ai agents conformance`: the handshake-only conformance kit for an ACP agent repo-ai has no adapter for.

It runs the named executable's `initialize` alone, in the network-denied probe sandbox, and never claims the agent
can execute through repo-ai."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import run_cli
from repo_ai.providers import adapters, discovery

FAKE = Path(__file__).parent / "fake_acp_agent.py"


def fake_agent(folder: Path, *, expect: list[str], version: int = 1) -> Path:
    """A stand-in ACP agent (tests/fake_acp_agent.py inlined), outside any repository."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "some-agent"
    exe.write_text(f"#!{sys.executable} -I\nimport os\n"
                   f"os.environ['FAKE_ACP_EXPECT_ARGV'] = {json.dumps(json.dumps(expect))}\n"
                   f"os.environ['FAKE_ACP_VERSION'] = '{version}'\n" + FAKE.read_text(encoding="utf-8"),
                   encoding="utf-8")
    exe.chmod(0o755)
    return exe


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


needs_sandbox = pytest.mark.skipif(discovery._sandbox_prefix(Path("/tmp")) is None,
                                   reason="no network-denying sandbox (seatbelt or bubblewrap) on this host")


@needs_sandbox
def test_an_acp_agent_passes_the_handshake_and_is_still_not_an_execution_provider(tmp_path, repo):
    exe = fake_agent(tmp_path / "bins", expect=["acp"])
    res = adapters.acp_conformance(str(exe), ["acp"], repo)
    assert res["verdict"] == "HANDSHAKE_CONFORMANT" and res["protocol_version"] == 1
    assert res["checks"]["answers_initialize_with_acp_1"] and res["checks"]["names_itself"]
    assert res["model_invoked"] is False and res["execution_support"] == "PLANNED"
    assert res["schema"] == adapters.ACP_CONFORMANCE_SCHEMA and res["identity"]


@needs_sandbox
def test_wrong_arguments_or_another_protocol_version_is_not_acp(tmp_path, repo):
    exe = fake_agent(tmp_path / "bins", expect=["acp"])
    res = adapters.acp_conformance(str(exe), ["serve"], repo)  # it exits before answering
    assert res["verdict"] == "NO_HANDSHAKE" and "unexpected arguments" in res.get("diagnostic_summary", "")
    v2 = fake_agent(tmp_path / "bins2", expect=["acp"], version=2)
    assert adapters.acp_conformance(str(v2), ["acp"], repo)["verdict"] == "NOT_ACP"


def test_a_relative_missing_or_repository_owned_executable_is_never_run(tmp_path, repo):
    assert adapters.acp_conformance("some-agent", [], repo)["verdict"] == "REFUSED"
    assert adapters.acp_conformance(str(tmp_path / "absent"), [], repo)["verdict"] == "REFUSED"
    owned = fake_agent(repo / "bin", expect=[])
    res = adapters.acp_conformance(str(owned), [], repo)
    assert res["verdict"] == "REFUSED" and "repository" in res["problem"]
    link = tmp_path / "outside-link"
    link.symlink_to(owned)
    assert adapters.acp_conformance(str(link), [], repo)["verdict"] == "REFUSED"


def test_without_a_sandbox_nothing_runs(tmp_path, repo, monkeypatch):
    exe = fake_agent(tmp_path / "bins", expect=["acp"])
    monkeypatch.setattr(adapters, "_sandbox_prefix", lambda scratch: None)
    res = adapters.acp_conformance(str(exe), ["acp"], repo)
    assert res["verdict"] == "NO_SANDBOX" and res["model_invoked"] is False


@needs_sandbox
def test_the_cli_reports_the_verdict_and_exits_by_it(tmp_path, repo):
    exe = fake_agent(tmp_path / "bins", expect=["acp"])
    ok = run_cli(repo, "agents", "conformance", "--acp-executable", str(exe), "--acp-arg", "acp", "--json")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["verdict"] == "HANDSHAKE_CONFORMANT"
    bad = run_cli(repo, "agents", "conformance", "--acp-executable", str(exe))
    assert bad.returncode == 1 and "NO_HANDSHAKE" in bad.stdout and "PLANNED" in bad.stdout
    usage = run_cli(repo, "agents", "conformance")
    assert usage.returncode == 2


# Independent review of the kit (PR #45).
def test_the_probe_sandbox_denies_launchservices_and_isolates_processes(tmp_path):
    prefix = discovery._sandbox_prefix(tmp_path)
    if prefix is None:
        pytest.skip("no sandbox on this host")
    if prefix[0] == "/usr/bin/sandbox-exec":  # `open` would start a program outside the sandbox, with the network
        for rule in ("(deny lsopen)", "(deny appleevent-send)", "(deny job-creation)", "(deny user-preference-write)",
                     'com.apple.pasteboard.1'):
            assert rule in prefix[2], rule
    else:
        assert {"--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts"} <= set(prefix)
        # host unix sockets live under /tmp and /run: hidden before the scratch directory is bound back in
        tmpfs = [prefix[i + 1] for i, a in enumerate(prefix) if a == "--tmpfs"]
        assert {"/tmp", "/run"} <= set(tmpfs)
        assert prefix.index("--bind") > max(i for i, a in enumerate(prefix) if a == "--tmpfs")


class _FakeClient:
    seen: dict = {}

    def __init__(self, argv, workspace, *, allowed_writes, env=None):
        _FakeClient.seen = {"argv": argv, "env": dict(env or {})}
        self.result = type("R", (), {"stderr": b"\x1b]0;title\x07boom"})()

    def probe(self, timeout_s=20.0):
        return {"acp": True, "protocol_version": 1, "agent": {"name": "\x1b[2Jfake\x1b[31m" + "x" * 500},
                "capabilities": {"\x1b[31mload": True}, "auth_methods": ["a\x07b"]}


def test_agent_supplied_text_is_stripped_of_terminal_escapes_and_bounded(tmp_path, repo, monkeypatch):
    exe = fake_agent(tmp_path / "bins", expect=[])
    monkeypatch.setattr(adapters, "_sandbox_prefix", lambda scratch: ["env"])
    monkeypatch.setattr(adapters, "AcpClient", _FakeClient)
    res = adapters.acp_conformance(str(exe), [], repo)
    printed = json.dumps(res, ensure_ascii=False)
    assert "\x1b" not in printed and "\x07" not in printed
    assert len(res["agent"]["name"]) <= 120 and res["verdict"] == "HANDSHAKE_CONFORMANT"


def test_a_non_mapping_agent_info_does_not_break_the_report(tmp_path, repo, monkeypatch):
    class Odd(_FakeClient):
        def probe(self, timeout_s=20.0):
            return {"acp": True, "protocol_version": 1, "agent": ["not", "a", "dict"], "capabilities": "nope"}
    exe = fake_agent(tmp_path / "bins", expect=[])
    monkeypatch.setattr(adapters, "_sandbox_prefix", lambda scratch: ["env"])
    monkeypatch.setattr(adapters, "AcpClient", Odd)
    res = adapters.acp_conformance(str(exe), [], repo)
    assert res["agent"] == {} and res["capabilities"] == [] and not res["checks"]["names_itself"]


def test_a_repository_owned_node_is_never_put_on_the_agents_path(tmp_path, repo, monkeypatch):
    (repo / "bin").mkdir()
    node = repo / "bin" / "node"
    node.write_text("#!/bin/sh\nexit 0\n")
    node.chmod(0o755)
    exe = fake_agent(tmp_path / "bins", expect=[])
    monkeypatch.setenv("PATH", f"{repo / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(adapters, "_sandbox_prefix", lambda scratch: ["env"])
    monkeypatch.setattr(adapters, "AcpClient", _FakeClient)
    adapters.acp_conformance(str(exe), [], repo)
    assert str(repo / "bin") not in _FakeClient.seen["env"]["PATH"]


def test_format_characters_are_stripped_and_unconfirmed_cleanup_is_not_a_pass(tmp_path, repo, monkeypatch):
    assert adapters._shown("a\u202eb\u200bc") == "abc"
    exe = fake_agent(tmp_path / "bins", expect=[])
    monkeypatch.setattr(adapters, "_sandbox_prefix", lambda scratch: ["/usr/bin/sandbox-exec", "-p", "(version 1)"])
    monkeypatch.setattr(adapters, "AcpClient", _FakeClient)
    monkeypatch.setattr(adapters, "_reap_provider_run", lambda marker: ["provider cleanup not confirmed: x"])
    res = adapters.acp_conformance(str(exe), [], repo)
    assert res["verdict"] == "CLEANUP_UNCONFIRMED" and res["cleanup_problems"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="bubblewrap probe (Linux)")
def test_a_host_unix_socket_under_tmp_is_not_reachable_from_the_linux_probe(tmp_path):
    """Path-based unix sockets ignore the network namespace; the probe hides /tmp and /run, where they live."""
    import socket
    import tempfile
    prefix = discovery._sandbox_prefix(tmp_path)
    if prefix is None:
        pytest.skip("no bubblewrap on this host")
    host_dir = Path(tempfile.mkdtemp(prefix="rai-host-sock-", dir="/tmp"))
    path = host_dir / "s"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    try:
        code = ("import socket,sys\ns=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)\n"
                f"try:\n s.connect({str(path)!r})\n print('reached')\nexcept OSError as e:\n print('blocked', type(e).__name__)")
        out = subprocess.run([*prefix, sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        assert "blocked" in out.stdout and "reached" not in out.stdout, (out.stdout, out.stderr[-400:])
    finally:
        srv.close()
        path.unlink(missing_ok=True)
        host_dir.rmdir()
