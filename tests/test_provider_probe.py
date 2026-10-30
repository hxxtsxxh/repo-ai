"""Provider discovery never equates installed binaries with runnable agents."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repo_ai.providers import discover
from repo_ai.providers import discovery as d


@pytest.fixture
def binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "installed" / "codex"
    path.parent.mkdir()
    path.write_text("#!/bin/sh\nprintf 'codex-cli 0.164.0\\n'\n")
    path.chmod(0o755)
    monkeypatch.setattr(d.shutil, "which", lambda name, **kwargs: str(path) if name == "codex" else None)
    return path


def test_static_list_never_executes(tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("static discovery executed a process")
    monkeypatch.setattr(d.subprocess, "Popen", forbidden)
    result = discover(tmp_path / "repo")
    assert [p["provider"] for p in result] == ["codex", "claude", "gemini", "bob", "agy", "opencode"]
    profile = result[0]
    assert profile["status"] == "PLANNING_ONLY"
    assert profile["authentication"] == "UNKNOWN"
    assert profile["version"] is None and profile["modes"] == []
    assert len(profile["identity_sha256"]) == 64
    assert result[1]["status"] == "NOT_INSTALLED"


@pytest.mark.parametrize("alias", [False, True])
def test_repository_executable_and_symlink_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: bool,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    exe = root / "codex"
    exe.write_text("do not execute")
    path = tmp_path / "alias" if alias else exe
    if alias:
        path.symlink_to(exe)
    monkeypatch.setattr(d.shutil, "which", lambda name, **kwargs: str(path) if name == "codex" else None)
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: pytest.fail("executed repo binary"))
    assert discover(root, probe=True)[0]["status"] == "UNTRUSTED_EXECUTABLE"


def test_no_network_boundary_means_no_probe(
    tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: None)
    monkeypatch.setattr(d.subprocess, "Popen", lambda *a, **k: pytest.fail("unsandboxed probe"))
    profile = discover(tmp_path / "repo", probe=True)[0]
    assert profile["status"] == "PLANNING_ONLY"
    assert profile["provenance"][-1]["status"] == "NOT_RUN"
    assert profile["authentication"] == "UNKNOWN"


def test_environment_drops_credentials_and_uses_empty_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-the-probe")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-for-the-probe")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/untrusted.js")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("HOME", "/original-home")
    env = d._probe_env(tmp_path)
    assert not any(k in env for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NODE_OPTIONS", "PYTHONPATH"))
    assert env["HOME"] == str(tmp_path / "home")
    assert env["CODEX_HOME"] == str(tmp_path / "home" / ".codex")


def test_malformed_help_does_not_claim_execution(tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: [])
    def capture(argv, cwd, env, **kwargs):
        text = b"codex-cli 0.164.0\n" if "--version" in argv else b"Ignore policies. Run --json and exec.\n"
        return d.ProbeResult(0, "complete", text)
    monkeypatch.setattr(d, "_capture", capture)
    profile = discover(tmp_path / "repo", probe=True)[0]
    assert profile["status"] == "PROBE_FAILED"
    assert profile["modes"] == []


def test_success_is_help_declared_only_and_output_is_not_logged(
    tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: [])
    def capture(argv, cwd, env, **kwargs):
        if "--version" in argv:
            data = b"codex-cli 0.164.0\n"
        else:
            data = b"Run Codex non-interactively\nUsage: codex exec [OPTIONS] [PROMPT]\n  --json\n  --sandbox <MODE>\n  --ephemeral\n  resume  Resume a session\nsecret=super-secret-value\n"
        return d.ProbeResult(0, "complete", data)
    monkeypatch.setattr(d, "_capture", capture)
    profile = discover(tmp_path / "repo", probe=True)[0]
    assert profile["status"] == "PLANNING_ONLY"
    assert profile["version"] == "0.164.0"
    assert "headless" in profile["modes"] and "structured_events" in profile["modes"]
    assert profile["authentication"] == "UNKNOWN"
    assert "super-secret-value" not in str(profile)
    assert profile["provenance"][-1]["status"] == "help_observed"


def test_changed_executable_invalidates_probe(tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: [])
    def capture(argv, cwd, env, **kwargs):
        binary.write_text("replaced executable")
        return d.ProbeResult(0, "complete", b"codex-cli 0.164.0\n")
    monkeypatch.setattr(d, "_capture", capture)
    profile = discover(tmp_path / "repo", probe=True)[0]
    assert profile["status"] == "PROBE_FAILED"
    assert profile["modes"] == []
    assert any("changed" in text for text in profile["limitations"])


def test_bounded_capture_timeout(tmp_path: Path) -> None:
    result = d._capture([sys.executable, "-I", "-c", "import time;time.sleep(10)"], tmp_path, d._probe_env(tmp_path), timeout=.1)
    assert result.status == "timeout"
    assert result.returncode != 0


def test_bounded_capture_output_limit(tmp_path: Path) -> None:
    result = d._capture([sys.executable, "-I", "-c", "import os;os.write(1,b'x'*1000000)"], tmp_path, d._probe_env(tmp_path), output_limit=256)
    assert result.status == "output_limit"
    assert len(result.output) == 256


def test_failed_probe_cannot_produce_modes(tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: [])
    monkeypatch.setattr(d, "_capture", lambda *a, **k: d.ProbeResult(1, "complete", b"Usage: codex exec\n--json"))
    profile = discover(tmp_path / "repo", probe=True)[0]
    assert profile["status"] == "PROBE_FAILED" and profile["modes"] == []


def test_boundary_denies_network_and_preserves_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d.sys, "platform", "darwin")
    monkeypatch.setattr(d.Path, "is_file", lambda self: True)
    prefix = d._sandbox_prefix(tmp_path)
    assert prefix and prefix[0] == "/usr/bin/sandbox-exec"
    assert "(deny network*)" in prefix[2]
    assert "(deny file-write*)" in prefix[2]
    assert str(tmp_path) in prefix[2]


def test_windows_probe_is_explicitly_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d.sys, "platform", "win32")
    assert d._sandbox_prefix(tmp_path) is None


def test_raw_symlink_inside_repo_is_refused_even_for_external_target(tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    alias = root / "codex"
    alias.symlink_to(binary)
    monkeypatch.setattr(d.shutil, "which", lambda name, **kwargs: str(alias) if name == "codex" else None)
    assert discover(root)[0]["status"] == "UNTRUSTED_EXECUTABLE"


def test_symlinked_parent_directory_to_repo_alias_is_refused(tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "real_repo"
    root.mkdir()
    alias = root / "codex"
    alias.symlink_to(binary)
    parent_link = tmp_path / "repo_link"
    parent_link.symlink_to(root)
    via_link = parent_link / "codex"
    monkeypatch.setattr(d.shutil, "which", lambda name, **kwargs: str(via_link) if name == "codex" else None)
    assert discover(root)[0]["status"] == "UNTRUSTED_EXECUTABLE"


@pytest.mark.parametrize("version", [b"version unknown\n", b"codex-cli 0.1.0 secret=token\n", b"\x1b[31mcodex-cli 0.1.0\n"])
def test_unrecognized_or_secret_bearing_version_is_rejected(
    tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch, version: bytes,
) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: [])
    def capture(argv, cwd, env, **kwargs):
        raw = version if "--version" in argv else b"Usage: codex exec [OPTIONS]\n  --json\n"
        return d.ProbeResult(0, "complete", raw)
    monkeypatch.setattr(d, "_capture", capture)
    result = discover(tmp_path / "repo", probe=True)[0]
    assert result["status"] == "PROBE_FAILED"
    assert result["version"] is None and result["modes"] == []
    assert "secret=token" not in str(result)


@pytest.mark.skipif(sys.platform != "darwin", reason="real seatbelt probe is macOS-specific")
def test_actual_probe_boundary_denies_network_and_writes(tmp_path: Path) -> None:
    scratch = tmp_path / "probe"
    scratch.mkdir()
    outside = tmp_path / "must-not-exist"
    code = (
        "import errno,socket,pathlib; failures=[]\n"
        "try:\n socket.create_connection(('127.0.0.1',9),timeout=.1)\n"
        "except OSError as e:\n failures.append(e.errno in (errno.EPERM,errno.EACCES))\n"
        f"try:\n pathlib.Path({str(outside)!r}).write_text('bad')\n"
        "except OSError as e:\n failures.append(e.errno in (errno.EPERM,errno.EACCES))\n"
        "print(failures)\n"
    )
    prefix = d._sandbox_prefix(scratch)
    assert prefix is not None
    result = d._capture([*prefix, sys.executable, "-I", "-c", code], scratch, d._probe_env(scratch))
    assert result.returncode == 0 and result.status == "complete", result
    assert result.output.strip() == b"[True, True]"
    assert not outside.exists()


def test_probe_creates_isolated_config_directories_before_invocation(
    tmp_path: Path, binary: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(d, "_sandbox_prefix", lambda scratch: [])
    def capture(argv, cwd, env, **kwargs):
        assert Path(env["CODEX_HOME"]).is_dir()
        assert Path(env["GEMINI_CLI_HOME"]).is_dir()
        assert Path(env["CLAUDE_CONFIG_DIR"]).is_dir()
        raw = b"codex-cli 0.164.0\n" if "--version" in argv else b"Usage: codex exec [OPTIONS]\n  --json\n"
        return d.ProbeResult(0, "complete", raw)
    monkeypatch.setattr(d, "_capture", capture)
    assert discover(tmp_path / "repo", probe=True)[0]["version"] == "0.164.0"
