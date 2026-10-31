"""`repo-ai agents conformance`: the handshake-only conformance kit for an ACP agent repo-ai has no adapter for.

It runs the named executable's `initialize` alone, in the network-denied probe sandbox, and never claims the agent
can execute through repo-ai."""
from __future__ import annotations

import json
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
