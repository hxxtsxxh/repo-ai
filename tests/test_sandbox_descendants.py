"""macOS seatbelt: no process a run started outlives it, however it left the
run's process group (threat model T7, T23).

Before the fix, a test process that detached (`setsid`, a double fork, a
cleared environment) and was one of Apple's own binaries (`/bin/sleep`, whose
environment `ps -E` does not show) survived every run: pass, failure,
time-out, cancellation, and the parent being killed. Each run is now found by
its own sandbox profile (`_seatbelt_procs`).

Every live test identifies what it started by a unique sleep duration and, if
anything is left, kills exactly those pids (never by pattern).
"""

from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from conftest import cli_env, default_sigint

from repo_ai import _seatbelt_procs as procs
from repo_ai import sandbox


def _seatbelt() -> bool:
    try:
        sandbox.get_backend("seatbelt")
        return True
    except sandbox.SandboxUnavailable:
        return False


needs_seatbelt = pytest.mark.skipif(not _seatbelt(), reason="macOS seatbelt only")


def _token() -> str:
    return str(779000 + uuid.uuid4().int % 1000)  # a sleep of about nine days: only this test's


def _sleeping(token: str) -> list[int]:
    out = subprocess.run(["pgrep", "-x", "-f", f"/bin/sleep {token}"], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def _gone(token: str, within: float = 3.0) -> bool:
    deadline = time.monotonic() + within
    while _sleeping(token) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not _sleeping(token)


def _remove(token: str) -> None:
    for pid in _sleeping(token):  # only `/bin/sleep <token>`: what this test started
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


DETACH = "import subprocess; subprocess.Popen(['/bin/sleep', '{t}'], start_new_session=True, " \
         "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
DAEMON = textwrap.dedent("""
    import os
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            os.chdir("/")
            fd = os.open("/dev/null", os.O_RDWR)
            for i in (0, 1, 2):
                os.dup2(fd, i)
            os.execve("/bin/sleep", ["/bin/sleep", "{t}"], {{}})
        os._exit(0)
    os.wait()
""")


def _run(code: str, ws: Path, timeout_s: float = 30) -> sandbox.Result:
    return sandbox.get_backend("seatbelt").run([sys.executable, "-c", code], ws,
                                               limits=sandbox.Limits(timeout_s=timeout_s))


# -- live: the run's own processes, wherever they went ---------------------------
@needs_seatbelt
@pytest.mark.parametrize("exit_code", [0, 3])
def test_a_detached_apple_binary_does_not_survive_a_passing_or_failing_run(tmp_path: Path, exit_code: int):
    token = _token()
    try:
        res = _run(DETACH.format(t=token) + f"; raise SystemExit({exit_code})", tmp_path)
        assert res.exit_code == exit_code and not res.timed_out, res
        assert _gone(token), "a detached /bin/sleep survived the run"
        assert not any("could not be confirmed" in n for n in res.notes), res.notes
    finally:
        _remove(token)


@needs_seatbelt
def test_a_double_fork_daemon_does_not_survive_the_run(tmp_path: Path):
    """setsid, a second fork (its parent exits: launchd adopts it), chdir /,
    closed descriptors, an empty environment, exec of an Apple binary."""
    token = _token()
    try:
        res = _run(DAEMON.format(t=token), tmp_path)
        assert res.exit_code == 0, res.stderr[-500:]
        assert _gone(token)
    finally:
        _remove(token)


@needs_seatbelt
def test_a_detached_process_does_not_survive_a_time_out(tmp_path: Path):
    token = _token()
    try:
        res = _run(DETACH.format(t=token) + "; import time; time.sleep(60)", tmp_path, timeout_s=2)
        assert res.timed_out
        assert _gone(token)
    finally:
        _remove(token)


@needs_seatbelt
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_a_detached_process_does_not_survive_cancellation(tmp_path: Path, sig: int):
    """The process running the sandbox is cancelled (as `verify --run` is: SIGTERM
    raises KeyboardInterrupt there) while the test is running."""
    token = _token()
    hang = DETACH.format(t=token) + "; import time; time.sleep(60)"
    script = tmp_path / "parent.py"
    script.write_text(textwrap.dedent(f"""
        import json, signal, sys
        from pathlib import Path
        from repo_ai import sandbox
        def interrupt(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
        out = {{}}
        try:
            sandbox.get_backend("seatbelt").run(
                [sys.executable, "-c", {hang!r}],
                Path(sys.argv[1]), limits=sandbox.Limits(timeout_s=60))
        except KeyboardInterrupt:
            out["stopped"] = sandbox.terminate_all()
        out["problems"] = getattr(sandbox, "cleanup_problems", list)()
        print(json.dumps(out))
    """))
    ws = tmp_path / "ws"
    ws.mkdir()
    try:
        parent = subprocess.Popen([sys.executable, str(script), str(ws)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=cli_env(), preexec_fn=default_sigint)
        deadline = time.monotonic() + 20
        while not _sleeping(token) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert _sleeping(token), "the test never started its process"
        parent.send_signal(sig)
        out, err = parent.communicate(timeout=30)
        assert _gone(token), "a detached /bin/sleep survived the cancellation"
        result = json.loads(out.strip().splitlines()[-1])
        # interrupted (the run's own cleanup ran before terminate_all), and confirmed clean
        assert "stopped" in result and result["problems"] == [], (result, err[-500:])
    finally:
        _remove(token)


@needs_seatbelt
def test_a_detached_process_does_not_survive_its_parent_being_killed(tmp_path: Path):
    """SIGKILL of the process that started the run: the guardian finds the
    run's processes by their sandbox."""
    token = _token()
    hang = DETACH.format(t=token) + "; import time; time.sleep(60)"
    script = tmp_path / "parent.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from repo_ai import sandbox
        sandbox.get_backend("seatbelt").run(
            [sys.executable, "-c", {hang!r}],
            Path(sys.argv[1]), limits=sandbox.Limits(timeout_s=60))
    """))
    ws = tmp_path / "ws"
    ws.mkdir()
    try:
        parent = subprocess.Popen([sys.executable, str(script), str(ws)], env=cli_env())
        deadline = time.monotonic() + 20
        while not _sleeping(token) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert _sleeping(token), "the test never started its process"
        parent.kill()
        parent.wait()
        assert _gone(token, within=10)
    finally:
        _remove(token)


@needs_seatbelt
def test_processes_outside_the_run_are_never_killed(tmp_path: Path):
    """An unsandboxed process of the same user, and a process in another
    seatbelt sandbox (another run's profile, as a parallel session has) both
    outlive a run whose own detached process is killed."""
    mine, other, theirs = _token(), _token(), _token()
    other_profile = sandbox.SeatbeltBackend.profile(tmp_path, "python", False,
                                                    run_id=procs.PREFIX + uuid.uuid4().hex)
    outside = [subprocess.Popen(["/bin/sleep", other]),
               subprocess.Popen(["/usr/bin/sandbox-exec", "-p", other_profile, "/bin/sleep", theirs],
                                start_new_session=True)]
    try:
        deadline = time.monotonic() + 10
        while not (_sleeping(other) and _sleeping(theirs)) and time.monotonic() < deadline:
            time.sleep(0.05)
        res = _run(DETACH.format(t=mine), tmp_path)
        assert res.exit_code == 0
        assert _gone(mine)
        time.sleep(0.3)
        assert all(p.poll() is None for p in outside), "a process outside the run was killed"
        assert _sleeping(other) and _sleeping(theirs)
    finally:
        for p in outside:
            p.kill()
            p.wait()
        for t in (mine, other, theirs):
            _remove(t)


@needs_seatbelt
def test_a_detached_sleep_does_not_survive_verify_run(tmp_path: Path):
    """End to end: `repo-ai verify --run` on a project whose test detaches
    `/bin/sleep` (survived every run before the fix)."""
    token = _token()
    root = tmp_path / "proj"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
             "tests/__init__.py": "",
             "tests/test_add.py": textwrap.dedent(f"""
                 import subprocess, unittest
                 from calc.core import add
                 class T(unittest.TestCase):
                     def test_add(self):
                         {DETACH.format(t=token)}
                         self.assertEqual(add(1, 2), 3)
             """)}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    cli = cli_env({"REPO_AI_WORKSPACES": str(tmp_path / "workspaces")})
    try:
        assert subprocess.run([sys.executable, "-m", "repo_ai", "init", "-C", str(root), "--agent", "none", "-q"],
                              env=cli, capture_output=True, timeout=120).returncode == 0
        proc = subprocess.run([sys.executable, "-m", "repo_ai", "verify", "-C", str(root), "--run", "--json",
                               "--sandbox", "seatbelt", "--test-command", "python -m unittest discover -s tests -t ."],
                              env=cli, capture_output=True, text=True, timeout=300)
        assert proc.returncode in (0, 1), proc.stderr[-1500:]
        assert "sandbox_cleanup_unconfirmed" not in json.loads(proc.stdout)
        assert _gone(token), "a detached /bin/sleep survived `verify --run`"
    finally:
        _remove(token)


# -- the identity check and the sweep, on a fake process table -----------------------
class FakeTable:
    """pid -> (start time, run it belongs to: a domain, False, or None = undecided)."""

    def __init__(self, rows: dict[int, tuple[tuple[int, int], object]]):
        self.rows = dict(rows)
        self.killed: list[int] = []
        self.reads: dict[int, int] = {}

    def pids(self):
        return list(self.rows)

    def belongs(self, pid, runs, control):
        which = self.rows[pid][1] if pid in self.rows else False
        return which if which in runs or which in (False, None) else False

    def started(self, pid):
        self.reads[pid] = self.reads.get(pid, 0) + 1
        return self.rows[pid][0] if pid in self.rows else None

    def kill(self, pid, sig):
        if pid not in self.rows:
            raise ProcessLookupError(pid)
        if sig:
            self.killed.append(pid)
            del self.rows[pid]

    def sweep(self, runs, **kw):
        return procs.sweep(runs, "control", list_pids=self.pids, belongs=self.belongs, start_of=self.started,
                           kill=self.kill, **kw)


RUN = procs.PREFIX + "a" * 32


def test_the_sweep_kills_only_the_runs_processes_and_confirms():
    table = FakeTable({100: ((1, 0), RUN), 101: ((1, 1), False), 102: ((1, 2), procs.PREFIX + "b" * 32),
                       os.getpid(): ((1, 3), RUN), 1: ((0, 0), RUN)})
    killed, problems = table.sweep({RUN})
    assert (killed, problems) == (1, [])
    assert table.killed == [100]  # never another run's, an unsandboxed one, itself or launchd


def test_a_reused_pid_is_never_signalled():
    """The run's process ends between the identity check and the kill, and an
    unrelated process gets its pid: the start time read again before the kill
    differs, so nothing is signalled; the next pass sees an unrelated process."""
    table = FakeTable({4242: ((100, 1), RUN)})
    real_started = table.started

    def started(pid):
        when = real_started(pid)
        if pid == 4242 and table.reads[pid] == 3:  # just before the kill: now someone else's
            table.rows[4242] = ((200, 5), False)
            return (200, 5)
        return when
    table.started = started
    killed, problems = table.sweep({RUN})
    assert table.killed == [] and killed == 0 and problems == []
    assert 4242 in table.rows  # the unrelated process is still there


def test_a_process_that_cannot_be_killed_or_decided_is_reported_not_assumed():
    table = FakeTable({7: ((1, 0), RUN)})

    def refuse(pid, sig):
        if sig:
            raise PermissionError(errno.EPERM, "not permitted")
    table.kill = refuse
    killed, problems = table.sweep({RUN}, budget_s=0.2)
    assert killed == 0 and len(problems) == 1 and "pid 7" in problems[0]

    undecided = FakeTable({8: ((1, 0), None)})
    killed, problems = undecided.sweep({RUN}, budget_s=0.2)
    assert undecided.killed == [] and len(problems) == 1 and "pid 8" in problems[0]

    killed, problems = procs.sweep({RUN}, "control", list_pids=lambda: None)
    assert problems == ["the process table could not be read"]


def test_a_forking_process_is_swept_until_a_pass_finds_none():
    """Each kill leaves a child the process forked meanwhile: the sweep goes on
    until a pass finds nothing (that pass confirms the cleanup)."""
    table = FakeTable({10: ((1, 0), RUN)})
    real_kill = table.kill

    def kill(pid, sig):
        real_kill(pid, sig)
        if sig and pid < 14:
            table.rows[pid + 1] = ((2, pid), RUN)  # forked just before it died
    table.kill = kill
    killed, problems = table.sweep({RUN})
    assert table.killed == [10, 11, 12, 13, 14] and problems == []


def test_identity_needs_this_runs_domain_allowed_and_the_control_denied(monkeypatch):
    """sandbox_check answers 0 (allowed) or 1 (denied). An unsandboxed process
    allows everything; another app's sandbox may allow every domain; neither is
    one of the run's processes."""
    answers = {}

    def check(pid, op, ftype, arg=None):
        boxed, allowed = answers[pid]
        if op is None:
            return boxed
        return 0 if (arg.decode() in allowed or "*" in allowed) else 1
    monkeypatch.setattr(procs, "_libs", lambda: (None, None))
    monkeypatch.setattr(procs, "_check", check)
    monkeypatch.setattr(procs, "started", lambda pid: (1, 0))
    answers.update({1: (1, {RUN}), 2: (0, {"*"}), 3: (1, {"*"}), 4: (1, set()), 5: (-1, set())})
    assert procs.run_of(1, {RUN}, "control") == RUN
    assert procs.run_of(2, {RUN}, "control") is False  # not sandboxed
    assert procs.run_of(3, {RUN}, "control") is False  # a sandbox allowing every domain
    assert procs.run_of(4, {RUN}, "control") is False  # another sandbox
    assert procs.run_of(5, {RUN}, "control") is None   # an error while it still exists: undecided


def test_without_the_identity_check_the_cleanup_is_reported_unconfirmed(monkeypatch):
    monkeypatch.setattr(sandbox._procs, "available", lambda: False)
    monkeypatch.setattr(sandbox, "_IDENTIFIED", [])
    scanned = []
    monkeypatch.setattr(sandbox, "_reap_marked", lambda markers: scanned.append(markers) or 0)
    monkeypatch.setattr(sandbox, "_tell_guardian", lambda line: None)
    monkeypatch.setattr(sandbox, "_CLEANUP_PROBLEMS", [])
    monkeypatch.setattr(sandbox, "_LIVE_RUNS", {RUN})
    problems = sandbox._reap_runs({RUN}, {"m"})
    assert scanned == [{"m"}] and len(problems) == 1 and "could not be confirmed" in problems[0]
    assert sandbox.cleanup_problems() == problems
    assert sandbox._LIVE_RUNS == {RUN}  # still registered: cancellation and the guardian try again


def test_the_profile_carries_its_run_identity_and_refuses_anything_else(tmp_path: Path):
    prof = sandbox.SeatbeltBackend.profile(tmp_path, "python", False, run_id=RUN)
    assert f'(allow user-preference-read (preference-domain "{RUN}"))' in prof
    assert "preference-domain" not in sandbox.SeatbeltBackend.profile(tmp_path, "python", False)
    with pytest.raises(ValueError):
        sandbox.SeatbeltBackend.profile(tmp_path, "python", False, run_id=RUN + '")) (allow default')


@pytest.mark.skipif(os.name != "posix", reason="host runs are POSIX")
def test_other_host_backends_never_use_the_seatbelt_sweep(monkeypatch, tmp_path: Path):
    """bwrap has a PID namespace: neither the sandbox sweep nor the marker scan
    runs for it (calling `_run_host` directly with a trivial command)."""
    def refuse(*a, **k):
        raise AssertionError("seatbelt cleanup ran for bwrap")
    monkeypatch.setattr(sandbox, "_reap_runs", refuse)
    monkeypatch.setattr(sandbox, "_reap_marked", refuse)
    res = sandbox._run_host(["/bin/sh", "-c", "exit 0"], tmp_path, sandbox.Limits(timeout_s=10), {}, "bwrap")
    assert res.exit_code == 0 and res.notes == []


def test_a_pid_reused_while_it_is_classified_is_never_taken_for_the_runs():
    """The classifier saw the run's process, which then ended; an unrelated
    process got its pid before its start time was read. The start time read
    before the classification differs from the one after: never killed."""
    table = FakeTable({4242: ((100, 1), RUN)})
    real_belongs = table.belongs

    def belongs(pid, runs, control):
        which = real_belongs(pid, runs, control)
        if pid == 4242 and table.rows[pid][1] == RUN:
            table.rows[4242] = ((200, 5), False)  # gone, and its pid is now someone else's
        return which
    table.belongs = belongs
    killed, problems = table.sweep({RUN})
    assert table.killed == [] and killed == 0 and problems == []


def test_the_sweep_runs_on_its_time_budget_and_never_reports_zero_processes():
    """Processes of the run keep ending just before each kill: no pass is clean,
    so the cleanup is unconfirmed when the budget runs out, and the problem
    says what happened rather than "0 process(es)"."""
    table = FakeTable({})
    n = [0]

    def pids():  # one pid, a new process of the run each pass (never this test's own pid)
        n[0] += 1
        table.rows, table.reads = {7: ((n[0], 0), RUN)}, {}
        return list(table.rows)
    table.pids = pids
    real_started = table.started

    def started(pid):
        when = real_started(pid)
        return (-1, -1) if table.reads[pid] >= 3 else when  # changed by the time of the kill
    table.started = started
    t = time.monotonic()
    killed, problems = table.sweep({RUN}, budget_s=0.3)
    assert 0.3 <= time.monotonic() - t < 3 and n[0] > 3  # passes until the budget, not a fixed count
    assert killed == 0 and len(problems) == 1 and "0 process" not in problems[0], problems


def test_an_unrecognised_probe_leaves_every_cleanup_unconfirmed(monkeypatch):
    """When the identity check cannot recognise a probe run's own process, an
    empty sweep proves nothing: the marker scan runs and the cleanup is
    reported unconfirmed, and the sweep is never trusted."""
    monkeypatch.setattr(sandbox, "_IDENTIFIED", [])
    monkeypatch.setattr(sandbox, "_identify_probe", lambda: "a probe run was not recognised as its own (answer False)")
    monkeypatch.setattr(sandbox._procs, "available", lambda: True)
    monkeypatch.setattr(sandbox._procs, "sweep", lambda *a, **k: (_ for _ in ()).throw(AssertionError("trusted")))
    scanned = []
    monkeypatch.setattr(sandbox, "_reap_marked", lambda markers: scanned.append(markers) or 0)
    monkeypatch.setattr(sandbox, "_tell_guardian", lambda line: None)
    monkeypatch.setattr(sandbox, "_CLEANUP_PROBLEMS", [])
    monkeypatch.setattr(sandbox, "_LIVE_RUNS", {RUN})
    problems = sandbox._reap_runs({RUN}, {"m"})
    assert scanned == [{"m"}] and len(problems) == 1 and "not recognised" in problems[0]
    assert sandbox._LIVE_RUNS == {RUN}


@pytest.mark.skipif(not (sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists()), reason="macOS")
def test_the_probe_run_is_recognised_as_its_own_on_this_mac():
    assert sandbox._identify_probe() == ""


def test_the_process_module_imports_without_ctypes():
    code = ("import sys; sys.modules['ctypes'] = None; sys.path.insert(0, sys.argv[1]); "
            "import repo_ai._seatbelt_procs as p; print(p.available(), p.pids(), p.started(1))")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(Path(sandbox.__file__).parents[1])],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.split() == ["False", "None", "None"], out.stderr


@pytest.mark.skipif(os.name != "posix", reason="the guardian is POSIX")
def test_the_guardian_program_runs_its_process_module_in_a_namespace_of_its_own():
    """The guardian's own helpers (`started` reads `ps`) and the module's
    (`started` reads proc_pidinfo) never replace each other. With nothing
    registered it ends at once, having signalled nothing."""
    code = sandbox._guardian_code()
    assert code.startswith("PROCS_SOURCE = ")
    out = subprocess.run([sys.executable, "-I", "-c", code + "\nassert _procs['started'] is not started\n"
                          "assert _procs['sweep'].__kwdefaults__['start_of'] is _procs['started']\n",
                          "0" * 16, procs.PREFIX + "c" * 32],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, cwd="/")
    assert out.returncode == 0, out.stderr
