"""Sandbox escape tests, run against every backend available on this host.

Each test asks the sandbox to do something it must not be able to do:
- read a canary file outside the workspace;
- reach the network;
- see a secret from the parent environment;
- write outside the workspace;
- follow a symlink out of the workspace;
- outlive its timeout.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from repo_ai import sandbox


def _backends() -> list[str]:
    names = []
    for name in sandbox.AUTO_ORDER:
        try:
            sandbox.get_backend(name, toolchain="python")
            names.append(name)
        except sandbox.SandboxUnavailable:
            continue
    return names


AVAILABLE = _backends()
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="no sandbox backend on this host")


@pytest.fixture(params=AVAILABLE or ["none"])
def backend(request):
    return sandbox.get_backend(request.param, toolchain="python")


def _py(code: str) -> list[str]:
    return ["python3", "-c", code]


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def test_runs_code_in_the_workspace(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    (ws / "a.txt").write_text("inside\n")
    res = backend.run(_py("print(open('a.txt').read().strip()); open('b.txt','w').write('x')"),
                      ws, limits=sandbox.Limits(timeout_s=60))
    assert res.ok, res.stderr
    assert res.stdout.strip() == "inside" and (ws / "b.txt").read_text() == "x"


def test_cannot_read_outside_the_workspace(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    canary = tmp_path / "canary-secret.txt"
    canary.write_text("TOP-SECRET-CANARY\n")
    res = backend.run(_py(f"print(open({str(canary)!r}).read())"), ws,
                      limits=sandbox.Limits(timeout_s=60))
    assert "TOP-SECRET-CANARY" not in res.stdout and not res.ok


def test_cannot_read_the_home_directory(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    home = Path.home()
    res = backend.run(_py(f"import os; print(os.listdir({str(home)!r}))"), ws,
                      limits=sandbox.Limits(timeout_s=60))
    assert not res.ok or "Library" not in res.stdout


def test_no_network(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    code = ("import socket\ns=socket.socket(); s.settimeout(3)\n"
            "try:\n    s.connect(('1.1.1.1', 443)); print('CONNECTED')\n"
            "except Exception as e:\n    print('blocked', type(e).__name__)")
    res = backend.run(_py(code), ws, limits=sandbox.Limits(timeout_s=60))
    assert "CONNECTED" not in res.stdout


def test_environment_is_not_inherited(backend, tmp_path: Path, monkeypatch):
    ws = _ws(tmp_path)
    monkeypatch.setenv("REPO_AI_FAKE_TOKEN", "sk-test-should-not-leak")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/fake-agent.sock")
    res = backend.run(_py("import os; print(sorted(os.environ))"), ws,
                      limits=sandbox.Limits(timeout_s=60))
    assert res.ok, res.stderr
    assert "REPO_AI_FAKE_TOKEN" not in res.stdout and "SSH_AUTH_SOCK" not in res.stdout


def test_cannot_write_outside_the_workspace(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    target = tmp_path / "escaped.txt"
    backend.run(_py(f"open({str(target)!r}, 'w').write('x')"), ws,
                limits=sandbox.Limits(timeout_s=60))
    assert not target.exists()


def test_symlink_escape_is_refused(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    (ws / "link").symlink_to(secret)
    with pytest.raises(sandbox.SandboxViolation):
        backend.run(_py("print(open('link').read())"), ws, limits=sandbox.Limits(timeout_s=60))


def test_timeout_kills_the_process_tree(backend, tmp_path: Path):
    ws = _ws(tmp_path)
    code = ("import subprocess,time\n"
            "subprocess.Popen(['python3','-c','import time; time.sleep(60); open(\"late\",\"w\")'])\n"
            "time.sleep(60)")
    started = time.monotonic()
    res = backend.run(_py(code), ws, limits=sandbox.Limits(timeout_s=3))
    assert res.timed_out and time.monotonic() - started < 40
    time.sleep(1)
    assert not (ws / "late").exists()


def test_no_backend_means_no_execution(monkeypatch):
    for name in sandbox.BACKENDS:
        monkeypatch.setattr(sandbox.BACKENDS[name], "available", lambda self: (False, "test"))
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.get_backend("auto")


@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt profile is macOS-only")
def test_seatbelt_profile_denies_home_and_temp():
    prof = sandbox.SeatbeltBackend.profile(Path("/private/tmp/ws-x"), "python", network=False)
    assert "(deny default)" in prof and "network" not in prof  # denied by default
    assert f'(subpath "{Path.home().resolve()}")' not in prof  # never the whole home directory
    assert '(subpath "/private/tmp")' not in prof and '(subpath "/private/var/folders")' not in prof
    assert '(subpath "/private/tmp/ws-x")' in prof
    assert os.path.exists("/usr/bin/sandbox-exec")


def test_docker_never_runs_as_container_root(tmp_path: Path):
    argv = sandbox.DockerBackend().argv_for(["true"], tmp_path, "x", sandbox.Limits(), "python", {})
    if hasattr(os, "getuid"):
        assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "--cap-drop" in argv and argv[argv.index("--network") + 1] == "none"


def test_cannot_signal_processes_outside_the_sandbox(backend, tmp_path: Path):
    res = backend.run(["sh", "-c", f"kill -0 {os.getpid()} && echo SIGNALLED || echo denied"],
                      _ws(tmp_path), limits=sandbox.Limits(timeout_s=30))
    assert "SIGNALLED" not in res.stdout


def test_cannot_read_shared_user_directories(backend, tmp_path: Path):
    res = backend.run(["sh", "-c", "ls /Users/Shared /Volumes >/dev/null 2>&1 && echo LISTED || echo denied"],
                      _ws(tmp_path), limits=sandbox.Limits(timeout_s=30))
    assert "LISTED" not in res.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS LaunchServices")
def test_seatbelt_cannot_reach_launchservices(tmp_path: Path):
    """`open x.command` would run a script outside the sandbox via LaunchServices.
    Probed with lsappinfo (read-only) so no application is ever launched."""
    sb = sandbox.SeatbeltBackend()
    if not sb.available()[0]:
        pytest.skip("no sandbox-exec")
    res = sb.run(["sh", "-c", "/usr/bin/lsappinfo front"], _ws(tmp_path), limits=sandbox.Limits(timeout_s=30))
    assert "ASN:" not in res.stdout  # no Mach connection to launchservicesd
    prof = sb.profile(tmp_path, "python", False)
    assert "(deny default)" in prof and "mach-lookup" not in prof and "(allow default)" not in prof


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
def test_seatbelt_hides_home_metadata_and_service_data(tmp_path: Path):
    sb = sandbox.SeatbeltBackend()
    if not sb.available()[0]:
        pytest.skip("no sandbox-exec")
    probe = (f"stat {Path.home()} >/dev/null 2>&1 && ls {Path.home()} >/dev/null 2>&1 && echo HOME; "
             "ls /opt/homebrew/etc /usr/local/etc /opt/homebrew/var >/dev/null 2>&1 && echo DATA; echo done")
    res = sb.run(["sh", "-c", probe], _ws(tmp_path), limits=sandbox.Limits(timeout_s=30))
    assert "HOME" not in res.stdout and "DATA" not in res.stdout and "done" in res.stdout
