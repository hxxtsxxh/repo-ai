"""Cancellation and cleanup of sandboxed processes: the windows a Ctrl-C or
SIGTERM can hit, processes that outlive the test process, and reports the
sandbox can replace with something other than a file.

Signals are only ever sent to a child Python process started by the test
(never to the test runner), in a temporary workspace, and every test kills
whatever it started by a unique token.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from conftest import default_sigint

from repo_ai import sandbox
from repo_ai.verify import results


def _host_backend() -> str:
    for name in ("seatbelt", "bwrap"):
        try:
            sandbox.get_backend(name, toolchain="python")
            return name
        except sandbox.SandboxUnavailable:
            continue
    return ""


HOST = _host_backend()
needs_host_sandbox = pytest.mark.skipif(not HOST, reason="no host sandbox backend (seatbelt, bwrap)")


def _alive(token: str) -> list[str]:
    out = subprocess.run(["pgrep", "-f", token], capture_output=True, text=True).stdout.split()
    return [p for p in out if p != str(os.getpid())]


def _kill(token: str) -> None:
    subprocess.run(["pkill", "-9", "-f", token], capture_output=True)


@needs_host_sandbox
def test_a_signal_while_the_process_is_starting_never_leaves_it_running(tmp_path: Path):
    """The signal arrives while `Popen` waits for the child's exec (the child is
    slow to start, as on a loaded machine): before the fix the child was never
    registered, so terminate_all() missed it."""
    token = f"{int(time.time() * 1000) % 100000 + 200000}"
    script = tmp_path / "e1.py"
    script.write_text(textwrap.dedent(f"""
        import json, os, signal, sys, time
        from pathlib import Path
        from repo_ai import sandbox
        orig = sandbox._preexec
        def slow(limits):
            inner = orig(limits)
            def apply():
                os.kill(os.getppid(), signal.SIGINT)  # reaches the parent while it waits on the exec pipe
                time.sleep(0.5)
                inner()
            return apply
        sandbox._preexec = slow
        out = {{}}
        try:
            sandbox.get_backend({HOST!r}, toolchain="python").run(
                ["/bin/sleep", "{token}"], Path(sys.argv[1]), limits=sandbox.Limits(timeout_s=60))
            out["returned"] = True
        except KeyboardInterrupt:
            out["stopped"] = sandbox.terminate_all()
        out["live"] = sandbox.live_count()
        print(json.dumps(out))
    """))
    ws = tmp_path / "ws"
    ws.mkdir()
    try:
        for _ in range(3):  # one pass is not a guarantee; three keep the test fast
            proc = subprocess.run([sys.executable, str(script), str(ws)], capture_output=True, text=True,
                                  timeout=60, preexec_fn=default_sigint)
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            assert out.get("live") == 0 and not out.get("returned"), (out, proc.stderr[-500:])
            time.sleep(0.5)
            assert _alive(f"sleep {token}") == []
    finally:
        _kill(f"sleep {token}")


@needs_host_sandbox
def test_a_background_process_holding_the_output_does_not_stall_the_run(tmp_path: Path):
    """The test process exits 0 but a process it left in its group still has
    stdout open: the run ends when the test process does (not at the limit),
    with its exit code, and nothing is left."""
    token = f"{uuid.uuid4().int % 100000 + 300000}"
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = sandbox.get_backend(HOST, toolchain="python")
    try:
        t = time.monotonic()
        res = backend.run(["/bin/sh", "-c", f"/bin/sleep {token} & echo started; exit 0"], ws,
                          limits=sandbox.Limits(timeout_s=60))
        took = time.monotonic() - t
        assert not res.timed_out and res.exit_code == 0 and "started" in res.stdout
        assert took < 15, took
        time.sleep(0.5)
        assert _alive(f"sleep {token}") == []
    finally:
        _kill(f"sleep {token}")


@needs_host_sandbox
@pytest.mark.skipif(not os.path.exists("/usr/bin/perl"), reason="needs perl for POSIX::setsid")
def test_a_detached_process_holding_the_output_does_not_hang_the_run(tmp_path: Path):
    """A grandchild that calls setsid and clears its environment (so neither
    the process group nor the marker finds it) and keeps stdout open: the run
    still returns, within its limit plus the drain time."""
    token = f"{uuid.uuid4().int % 100000 + 400000}"
    ws = tmp_path / "ws"
    ws.mkdir()
    code = f'use POSIX; if (fork()) {{ exit 0 }} POSIX::setsid(); %ENV=(); exec("/bin/sleep", "{token}");'
    try:
        t = time.monotonic()
        sandbox.get_backend(HOST, toolchain="python").run(["/usr/bin/perl", "-e", code], ws,
                                                          limits=sandbox.Limits(timeout_s=3))
        assert time.monotonic() - t < 3 + sandbox.DRAIN_S + 5
    finally:
        _kill(f"sleep {token}")  # it stays confined by the profile; the test removes it


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs and POSIX symlinks")
@pytest.mark.parametrize("kind", ["fifo", "dev-zero", "host-file", "linked-dir"])
def test_a_report_replaced_by_something_other_than_a_file_is_not_read(tmp_path: Path, kind: str):
    ws = tmp_path / "ws"
    run = ws / ".repo-ai" / "run"
    run.mkdir(parents=True)
    report = run / "outcomes.jsonl"
    secret = tmp_path / "host.txt"
    secret.write_text('{"e": "done"}\n')
    if kind == "fifo":
        os.mkfifo(report)
    elif kind == "dev-zero":
        report.symlink_to("/dev/zero")
    elif kind == "host-file":
        report.symlink_to(secret)
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "outcomes.jsonl").write_text('{"e": "done"}\n')
        os.rmdir(run)
        run.symlink_to(outside)
    t = time.monotonic()
    events, problem = results._events(report)
    assert time.monotonic() - t < 2
    assert events == [] and problem == "no per-test report was written"


def test_a_cancelled_container_run_removes_its_container(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []
    backend = sandbox.PodmanBackend()
    monkeypatch.setattr(backend, "available", lambda: (True, ""))
    monkeypatch.setattr(backend, "has_image", lambda toolchain: True)
    monkeypatch.setattr(backend, "_cli", lambda: "/fake/podman")
    monkeypatch.setattr(sandbox, "check_workspace", lambda ws: None)

    def fake_popen(cmd, **kw):
        calls.append(cmd)
        raise KeyboardInterrupt  # Ctrl-C while the client starts

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    monkeypatch.setattr(sandbox.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox, "_tell_guardian", lambda line: None)
    with pytest.raises(KeyboardInterrupt):
        backend.run(["python", "-c", "pass"], tmp_path, limits=sandbox.Limits(timeout_s=10))
    removed = [c for c in calls if c[1:3] == ["rm", "-f"]]
    assert len(removed) == 1 and removed[0][-1].startswith("repo-ai-")
    assert removed[0][3:5] == ["-t", "0"]  # podman: removed at once, not after a stop timeout
    assert sandbox.live_count() == 0


@needs_host_sandbox
def test_killing_the_parent_outright_leaves_no_test_process(tmp_path: Path):
    """SIGKILL of the process that started the run: nothing in it can clean
    up, and a seatbelt test process leads its own session. The guardian
    removes it (here /bin/sleep, whose environment macOS hides from `ps`, so
    the run marker alone would not find it)."""
    script = tmp_path / "parent.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from repo_ai import sandbox
        sandbox.get_backend({HOST!r}, toolchain="python").run(
            ["/bin/sleep", sys.argv[2]], Path(sys.argv[1]), limits=sandbox.Limits(timeout_s=60))
    """))
    ws = tmp_path / "ws"
    ws.mkdir()
    for _ in range(3):
        token = f"{uuid.uuid4().int % 100000 + 500000}"
        try:
            parent = subprocess.Popen([sys.executable, str(script), str(ws), token])
            deadline = time.monotonic() + 20
            while not _alive(f"sleep {token}") and time.monotonic() < deadline:
                time.sleep(0.1)
            assert _alive(f"sleep {token}"), "the test process never started"
            parent.kill()
            parent.wait()
            deadline = time.monotonic() + 10
            while _alive(f"sleep {token}") and time.monotonic() < deadline:
                time.sleep(0.2)
            assert _alive(f"sleep {token}") == []
        finally:
            _kill(f"sleep {token}")


@pytest.mark.skipif(os.name != "posix", reason="the guardian is POSIX-only")
def test_killing_the_parent_outright_removes_its_containers(tmp_path: Path):
    log = tmp_path / "calls.log"
    cli = tmp_path / "fake-podman"
    cli.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n")
    cli.chmod(0o755)
    script = tmp_path / "parent.py"
    script.write_text(textwrap.dedent(f"""
        import time
        from repo_ai import sandbox
        sandbox._tell_guardian("+c repo-ai-left0001 {cli}")
        sandbox._tell_guardian("+c repo-ai-done0001 {cli}")
        sandbox._tell_guardian("-c repo-ai-done0001")  # finished normally: not removed again
        print("ready", flush=True)
        time.sleep(60)
    """))
    parent = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    assert parent.stdout.readline().strip() == "ready"
    parent.kill()
    parent.wait()
    deadline = time.monotonic() + 10
    while not log.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)
    assert log.read_text().split("\n")[:-1] == ["rm -f repo-ai-left0001"]


@needs_host_sandbox
def test_endless_output_costs_bounded_host_memory(tmp_path: Path):
    """A test that prints without end must not grow the host process (before,
    `communicate()` kept every byte: 600 MB of output took it past 2 GB)."""
    script = tmp_path / "out.py"
    script.write_text(textwrap.dedent(f"""
        import json, resource, sys
        from pathlib import Path
        from repo_ai import sandbox
        def rss():
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return r if sys.platform == "darwin" else r * 1024
        before = rss()
        res = sandbox.get_backend({HOST!r}, toolchain="python").run(
            ["/bin/sh", "-c", "head -c 200000000 /dev/zero"], Path(sys.argv[1]), limits=sandbox.Limits(timeout_s=60))
        print(json.dumps({{"grew": rss() - before, "exit": res.exit_code, "tail": len(res.stdout)}}))
    """))
    ws = tmp_path / "ws"
    ws.mkdir()
    proc = subprocess.run([sys.executable, str(script), str(ws)], capture_output=True, text=True, timeout=120)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["exit"] == 0 and out["tail"] <= sandbox.OUTPUT_TAIL
    assert out["grew"] < 64 * 1024 * 1024, out


@needs_host_sandbox
@pytest.mark.skipif(not os.path.exists("/usr/bin/perl"), reason="needs perl to fork in a loop")
def test_a_forking_group_member_does_not_survive_a_passing_run(tmp_path: Path):
    """The test exits 0 and leaves a fork loop in its process group (no setsid):
    one killpg races the forks; the group is killed until it is gone."""
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = sandbox.get_backend(HOST, toolchain="python")
    for _ in range(3):
        token = f"{uuid.uuid4().int % 100000 + 600000}"
        code = (f'if (fork()) {{ exit 0 }} open(STDOUT, ">/dev/null"); open(STDERR, ">/dev/null"); '
                f'while (1) {{ if (!fork()) {{ exec("/bin/sleep", "{token}") }} select(undef, undef, undef, 0.01) }}')
        try:
            res = backend.run(["/usr/bin/perl", "-e", code], ws, limits=sandbox.Limits(timeout_s=30))
            assert res.exit_code == 0
            time.sleep(0.5)
            assert _alive(f"sleep {token}") == []
        finally:
            _kill(token)  # the fork loop and its sleeps all carry the token


@pytest.mark.skipif(os.name != "posix", reason="the guardian is POSIX-only")
def test_the_guardian_kills_a_registered_group_whose_leader_already_exited(tmp_path: Path):
    """The parent dies while a registered test group's leader has exited but a
    member is still running in the group: the guardian kills the group."""
    token = f"{uuid.uuid4().int % 100000 + 700000}"
    script = tmp_path / "parent.py"
    script.write_text(textwrap.dedent(f"""
        import os, subprocess, time
        from repo_ai import sandbox
        leader = subprocess.Popen(["/bin/sh", "-c", "/bin/sleep {token} & sleep 0.3"], start_new_session=True)
        sandbox._tell_guardian(f"+g {{leader.pid}}")
        leader.wait()            # the leader is gone; its member is still in the group
        time.sleep(0.5)          # the guardian has read the registration
        print("ready", flush=True)
        os._exit(9)              # the parent dies without unregistering
    """))
    try:
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
        assert "ready" in proc.stdout, proc.stderr[-500:]
        deadline = time.monotonic() + 10
        while _alive(f"sleep {token}") and time.monotonic() < deadline:
            time.sleep(0.2)
        assert _alive(f"sleep {token}") == []
    finally:
        _kill(f"sleep {token}")
