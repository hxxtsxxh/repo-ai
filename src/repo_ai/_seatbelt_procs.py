"""Find and kill every process of one macOS seatbelt run, wherever it went.

A seatbelt test process can leave everything the run tracks: `setsid` (a new
process group and session), a double fork (reparented to launchd), a cleared
environment, `chdir("/")`, closed descriptors, and an exec of one of Apple's
own binaries (whose environment `ps -E` does not show). What it can never leave
is its sandbox: the profile is inherited by every descendant, and a sandboxed
process cannot apply another one (`sandbox_apply` fails with EPERM).

So each run's profile carries one rule that grants nothing usable,
``(allow user-preference-read (preference-domain "com.repo-ai.run.<id>"))``
(preference reads go through cfprefsd, a Mach service the profile denies), and
the run's processes are those for which ``sandbox_check(pid, ...)`` answers:
sandboxed, that domain allowed, and a control domain with the same prefix
denied. An unsandboxed process allows every domain and another app's sandbox
denies a random one, so neither matches. Same user, no privileges.

Standard library only: the guardian (`sandbox._GUARDIAN_CODE`) runs this file's
source with ``python -I`` when the process that started the runs is gone.
"""

from __future__ import annotations

import os
import signal
import sys
import time

try:  # not every Python has ctypes; without it the run's processes cannot be found this way
    import ctypes
except ImportError:  # pragma: no cover
    ctypes = None  # type: ignore[assignment]

PREFIX = "com.repo-ai.run."
_PROC_PIDTBSDINFO = 3
_SZOMB = 5
_FILTER_NONE = 0
_FILTER_PREFERENCE_DOMAIN = 6
_CHECK_NO_REPORT = 0x40000000  # do not log a denial for a question


_BSDINFO: list = []


def _bsdinfo():
    """struct proc_bsdinfo, <sys/proc_info.h> (defined on first use: ctypes may be absent)."""
    if not _BSDINFO:
        c = ctypes

        class BsdInfo(c.Structure):
            _fields_ = [("pbi_flags", c.c_uint32), ("pbi_status", c.c_uint32), ("pbi_xstatus", c.c_uint32),
                        ("pbi_pid", c.c_uint32), ("pbi_ppid", c.c_uint32), ("pbi_uid", c.c_uint32),
                        ("pbi_gid", c.c_uint32), ("pbi_ruid", c.c_uint32), ("pbi_rgid", c.c_uint32),
                        ("pbi_svuid", c.c_uint32), ("pbi_svgid", c.c_uint32), ("rfu_1", c.c_uint32),
                        ("pbi_comm", c.c_char * 16), ("pbi_name", c.c_char * 32), ("pbi_nfiles", c.c_uint32),
                        ("pbi_pgid", c.c_uint32), ("pbi_pjobc", c.c_uint32), ("e_tdev", c.c_uint32),
                        ("e_tpgid", c.c_uint32), ("pbi_nice", c.c_int32), ("pbi_start_tvsec", c.c_uint64),
                        ("pbi_start_tvusec", c.c_uint64)]
        _BSDINFO.append(BsdInfo)
    return _BSDINFO[0]


_LIBS: list = []


def _libs():
    """(libproc, libsystem_sandbox), or None where they cannot be loaded."""
    if not _LIBS:
        try:
            if sys.platform != "darwin" or ctypes is None:
                raise OSError("not macOS, or no ctypes")
            proc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            sb = ctypes.CDLL("/usr/lib/system/libsystem_sandbox.dylib", use_errno=True)
            # variadic: only the fixed arguments are declared (arm64 passes the rest on the stack)
            sb.sandbox_check.restype = ctypes.c_int
            sb.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
            proc.proc_listallpids.restype = ctypes.c_int
            proc.proc_pidinfo.restype = ctypes.c_int
            _LIBS.append((proc, sb))
        except (OSError, AttributeError):
            _LIBS.append(None)
    return _LIBS[0]


def available() -> bool:
    return _libs() is not None


def pids() -> list[int] | None:
    """Every process id on the machine (any user), or None when unreadable."""
    libs = _libs()
    if libs is None:
        return None
    size = 4096
    for _ in range(4):
        buf = (ctypes.c_int * size)()
        n = libs[0].proc_listallpids(buf, ctypes.sizeof(buf))
        if n < 0:
            return None
        if n < size:
            return [buf[i] for i in range(n) if buf[i] > 0]
        size *= 4
    return None


def started(pid: int) -> tuple[int, int] | None:
    """The process's start time (seconds, microseconds): with the pid, its
    identity. None when it is gone, a zombie, or another user's (unreadable)."""
    libs = _libs()
    if libs is None:
        return None
    info = _bsdinfo()()
    n = libs[0].proc_pidinfo(pid, _PROC_PIDTBSDINFO, ctypes.c_uint64(0), ctypes.byref(info), ctypes.sizeof(info))
    if n != ctypes.sizeof(info) or info.pbi_status == _SZOMB:
        return None
    return int(info.pbi_start_tvsec), int(info.pbi_start_tvusec)


def _check(pid: int, operation: bytes | None, ftype: int, arg: bytes | None = None) -> int:
    sb = _libs()[1]
    if arg is None:
        return sb.sandbox_check(pid, operation, ftype)
    return sb.sandbox_check(pid, operation, ftype | _CHECK_NO_REPORT, arg)


def run_of(pid: int, runs: frozenset[str] | set[str], control: str) -> str | None | bool:
    """Which of `runs` (preference domains) the process belongs to; False when
    none; None when it could not be decided (the process still exists)."""
    if _libs() is None:
        return None
    boxed = _check(pid, None, _FILTER_NONE)
    if boxed == 0:
        return False  # not sandboxed: never one of ours
    if boxed == 1:
        if _check(pid, b"user-preference-read", _FILTER_PREFERENCE_DOMAIN, control.encode()) == 1:
            for run in runs:
                if _check(pid, b"user-preference-read", _FILTER_PREFERENCE_DOMAIN, run.encode()) == 0:
                    return run
            return False
        if _check(pid, b"user-preference-read", _FILTER_PREFERENCE_DOMAIN, control.encode()) == 0:
            return False  # its sandbox allows any domain: not ours (ours denies the control)
    return None if started(pid) is not None else False  # an error, or it ended meanwhile


def sweep(runs, control: str, *, list_pids=pids, belongs=run_of, start_of=started, kill=os.kill,
          budget_s: float = 3.0) -> tuple[int, list[str]]:
    """SIGKILL every process of `runs`, pass after pass until a pass finds none
    or the time budget runs out.

    A pass that finds no process of the runs confirms the cleanup: only a
    process of a run can start another one (the sandbox is inherited, and the
    run's own `sandbox-exec` has ended). A process's start time is read before
    it is classified and again after: a pid that ended and was reused by an
    unrelated process meanwhile is never taken for the run's. It is read once
    more just before the kill, for the same reason.

    Returns (processes killed, problems); problems is empty only when the
    cleanup was confirmed."""
    runs = frozenset(runs)
    if not runs:
        return 0, []
    me, killed, deadline = os.getpid(), 0, time.monotonic() + budget_s
    left: list[int] = []
    while True:
        table = list_pids()
        if table is None:
            return killed, ["the process table could not be read"]
        found, left = [], []
        for pid in table:
            if pid in (0, 1, me):
                continue
            when = start_of(pid)
            which = belongs(pid, runs, control)
            if which is False:
                continue
            if when is None:  # gone, a zombie, or another user's (a setuid program it ran)
                if which and _exists(pid, kill):
                    left.append(pid)  # one of ours that cannot be identified for a kill: not confirmed
                continue
            if start_of(pid) != when:
                left.append(pid)  # it ended while it was being classified: decided by the next pass
            elif which is None:
                left.append(pid)
            else:
                found.append((pid, when))
        if not found and not left:
            return killed, []
        for pid, when in found:
            if start_of(pid) != when:
                continue  # it ended; the pid may already be someone else's (the next pass decides)
            try:
                kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))  # Windows has no SIGKILL
                killed += 1
            except ProcessLookupError:
                pass
            except OSError:
                left.append(pid)
            else:
                left.append(pid)  # confirmed only by a later pass that no longer finds it
        if time.monotonic() >= deadline:
            break
        time.sleep(0 if found else 0.01)  # a zombie is reaped, an undecided answer settles
    left = sorted(set(left))
    if not left:  # every one it found ended before the kill, and the budget ran out
        return killed, ["processes of the run were still appearing when the cleanup's time budget ran out"]
    return killed, [f"{len(left)} process(es) of the run may still be running"
                    f" (pid {', '.join(map(str, left[:5]))}{' …' if len(left) > 5 else ''})"]


def _exists(pid: int, kill) -> bool:
    try:
        kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True  # EPERM: it exists, as another user
