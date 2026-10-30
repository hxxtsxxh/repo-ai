"""Isolated execution for untrusted code (eval grading, skill trials).

A temporary directory, git worktree or virtualenv is **not** a security
boundary. Untrusted code (code an agent wrote, a third-party skill's
script) runs only through a backend that the operating system enforces:

==========  ==============================================================
podman      rootless container: ``--network=none``, read-only root, tmpfs
            /tmp, every capability dropped, ``no-new-privileges``, pids,
            memory and CPU limits; only the disposable workspace is
            mounted. Strongest; the default when available.
docker      the same flags, through Docker.
bwrap       Linux bubblewrap: new user/pid/net/ipc namespaces, read-only
            system binds, the workspace as the only writable bind, empty
            ``$HOME``.
seatbelt    macOS ``sandbox-exec`` profile: no network, no reads of the
            home directory or temp areas except the workspace and declared
            toolchains, writes only in the workspace; CPU-time and file-size
            rlimits. Weaker than a container (shared kernel, same user),
            documented as such.
==========  ==============================================================

There is no unsandboxed fallback. If no backend is available, a caller
gets ``SandboxUnavailable`` and must fall back to static inspection.

Every backend clears the environment (no host credentials, tokens or SSH
agent socket), kills the whole process tree on timeout or cancellation,
and refuses workspaces that contain symlinks pointing outside themselves.
"""

from __future__ import annotations

import functools
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import _seatbelt_procs as _procs

# Pinned by tag here; `sandbox doctor` records the resolved digest.
DEFAULT_IMAGES = {
    "python": "docker.io/library/python:3.12-slim",
    "node": "docker.io/library/node:24-slim",
    "java": "docker.io/library/eclipse-temurin:17-jdk",
}
SAFE_ENV = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0", "NO_COLOR": "1", "CI": "1"}
OUTPUT_TAIL = 8000
CONTAINER_GRACE_S = 5.0  # a container run's limit: the tests' limit plus this, for the client to start it


class SandboxUnavailable(RuntimeError):
    pass


class SandboxViolation(RuntimeError):
    pass


@dataclass(slots=True)
class Limits:
    timeout_s: float = 300.0
    cpus: float = 2.0
    memory_mb: int = 2048
    pids: int = 512
    file_size_mb: int = 512
    tmpfs_mb: int = 512
    network: bool = False  # never True unless the caller has explicit authorization
    # Optional progress check, polled about every 0.5 s while the command runs: a non-empty
    # answer (why the run has stalled) ends it exactly like a time-out. Never a pass.
    watch: Any = None


@dataclass(slots=True)
class Result:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    backend: str
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_json(self) -> dict[str, Any]:
        return {"exit_code": self.exit_code, "duration_s": round(self.duration_s, 2),
                "timed_out": self.timed_out, "backend": self.backend,
                "stdout_tail": self.stdout[-2000:], "stderr_tail": self.stderr[-2000:],
                "notes": self.notes}


def check_workspace(workspace: Path, allowed_links: dict[str, str] | None = None) -> None:
    """Refuse a workspace with symlinks that leave it (or any symlink to an
    absolute path): the backend mounts only the workspace, but a seatbelt or
    bwrap run would otherwise follow them. `allowed_links` maps workspace-relative
    paths to the one target each may point at (read-only dependency
    directories the caller also declares as read-only)."""
    root = workspace.resolve()
    allowed = dict(allowed_links or {})
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            entry = Path(dirpath) / name
            if entry.is_symlink():
                target = os.readlink(entry)
                rel = entry.relative_to(root).as_posix()
                if rel in allowed and target == allowed[rel]:
                    continue
                resolved = (entry.parent / target).resolve()
                if os.path.isabs(target) or (resolved != root and root not in resolved.parents):
                    raise SandboxViolation(
                        f"workspace symlink escapes the sandbox: {entry.relative_to(root)} -> {target}")


# --------------------------------------------------------------------------
# live processes: everything started here can be stopped on cancellation
# --------------------------------------------------------------------------
_LIVE_LOCK = threading.Lock()
_LIVE_GROUPS: set[int] = set()
_LIVE_CONTAINERS: dict[str, str] = {}  # name -> container CLI
_CANCELLED = threading.Event()
_STOPPED = [0]  # process groups and containers stopped by cancellations in this process


# --------------------------------------------------------------------------
# the guardian: cleanup even when this process itself is killed (SIGKILL)
# --------------------------------------------------------------------------
# Nothing in a process that is SIGKILLed can clean up, and a seatbelt test process
# leads its own session (no PID namespace, no parent-death signal on macOS); a
# container keeps running when its client dies. So the first sandboxed run starts
# one guardian: repo-ai's own code (never repository code, `python -I`, cwd /),
# holding the read end of a pipe only this process can write. This process
# tells it each test process group and container it starts and ends. When the
# pipe closes (this process exited, however), it kills the groups still
# registered whose leader is now an orphan, every process of the seatbelt runs
# still registered (found by their sandbox, `_seatbelt_procs`, wherever they
# went), what carries this process's run markers (the fallback where that
# check is unavailable: macOS hides the environment of Apple's own binaries, so
# markers alone miss `/bin/sh`), and removes the containers still registered.
_OWNER = uuid.uuid4().hex[:16]   # the prefix of every run marker this process issues
# seatbelt: the control preference domain no run's profile allows (`_seatbelt_procs.run_of`)
_CONTROL = _procs.PREFIX + uuid.uuid4().hex
_GUARD_LOCK = threading.Lock()
_GUARDIAN: list[Any] = []        # [write fd or None, Popen]
_PROCS_STUB = "def available():\n    return False\n"
_GUARDIAN_CODE = r"""
import os, signal, subprocess, sys, time
owner, control, containers, groups, runs = sys.argv[1], sys.argv[2], {}, {}, set()
_procs = {"__name__": "_seatbelt_procs"}
exec(PROCS_SOURCE, _procs)  # its own namespace: its names never meet the ones below

def ps(*args):
    try:
        return subprocess.run(["ps", *args], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None  # e.g. no process slot left to fork `ps`

def started(pid):
    out = ps("-o", "lstart=", "-p", str(pid))
    return out.strip() if out else None

for line in sys.stdin:  # until the owner's end of the pipe closes
    op, _, rest = line.rstrip("\n").partition(" ")
    if op == "+c":
        name, _, cli = rest.partition(" ")
        containers[name] = cli
    elif op == "-c":
        containers.pop(rest, None)
    elif op == "+g" and rest.isdigit():
        groups[int(rest)] = started(int(rest))  # identity of the leader, read once, now
    elif op == "-g" and rest.isdigit():
        groups.pop(int(rest), None)
    elif op == "+s" and rest:
        runs.add(rest)
    elif op == "-s":
        runs.discard(rest)

def group_exists(g):
    try:
        os.killpg(g, 0)
        return True
    except OSError:
        return False

def ours(g, when):
    # the registered leader itself (same start time), or a group whose leader is gone but which
    # still exists: a pid is never reused while a process group with that id exists
    now = started(g)
    if now is None and ps("-o", "pid=", "-p", "1") is None:
        return group_exists(g)  # cannot run ps at all (process limit): act on the group alone
    if now and when is None:
        # its start time could not be read at registration (no process slot for `ps`):
        # an orphan of this user that leads its own group, as registered
        out = (ps("-o", "ppid=,uid=", "-p", str(g)) or "").split()
        return len(out) == 2 and out[0] == "1" and out[1] == str(os.getuid())
    if now:
        return now == when
    return group_exists(g)

def marked():
    needle, me = "REPO_AI_SANDBOX_RUN=" + owner, str(os.getuid())
    rows = (ln.split(None, 2) for ln in (ps("-axww", "-E", "-o", "pid=,uid=,command=") or "").splitlines())
    return [int(r[0]) for r in rows if len(r) == 3 and r[1] == me and r[0].isdigit() and needle in r[2]]

def kill_group(g):
    for _ in range(40):  # again until it is gone: one killpg races a member that is forking
        try:
            os.killpg(g, signal.SIGKILL)
        except OSError:
            return
        time.sleep(0.005)

for attempt in range(3):  # a child between fork and exec is registered a moment later
    for g, when in list(groups.items()):
        if ours(g, when):
            kill_group(g)
    if runs and _procs["available"]():
        try:
            _procs["sweep"](runs, control)
        except Exception:
            pass
    for pid in marked():
        for kill in (os.killpg, os.kill):  # a test process leads its own group
            try:
                kill(pid, signal.SIGKILL)
            except Exception:
                pass
    if attempt < 2:
        time.sleep(0.5)
for name, cli in containers.items():
    try:
        subprocess.run([cli, "rm", "-f", *(["-t", "0"] if os.path.basename(cli).startswith("podman") else []),
                        name], capture_output=True, timeout=60)
    except Exception:
        pass
"""


def _guardian_code() -> str:
    """The guardian's program: the source of `_seatbelt_procs` (standard library
    only), run in a namespace of its own, and the loop above, so that it needs
    no import of repo-ai (`python -I`, cwd /)."""
    try:
        procs = Path(_procs.__file__).read_text("utf-8")
    except (OSError, TypeError):  # e.g. loaded from an archive: the marker scan remains
        procs = _PROCS_STUB
    return f"PROCS_SOURCE = {procs!r}\n" + _GUARDIAN_CODE


def _guardian() -> int | None:
    """The write end of the guardian's pipe, starting it on first use."""
    with _GUARD_LOCK:
        if _GUARDIAN:
            return _GUARDIAN[0]
        if os.name != "posix":
            _GUARDIAN.extend([None, None])
            return None
        r, w = os.pipe()  # not inheritable: no test process ever holds the write end
        try:
            proc = subprocess.Popen([sys.executable, "-I", "-c", _guardian_code(), _OWNER, _CONTROL], stdin=r,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd="/",
                                    start_new_session=True, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        except OSError:
            os.close(r)
            os.close(w)
            _GUARDIAN.extend([None, None])
            return None
        os.close(r)
        _GUARDIAN.extend([w, proc])
        return w


def _tell_guardian(line: str) -> None:
    w = _guardian()
    if w is None:
        return
    try:
        os.write(w, (line + "\n").encode())
    except OSError:  # the guardian is gone: cancellation in this process still works
        pass


class Cancelled(RuntimeError):
    pass


def allow_runs() -> None:
    """Start of an operation: runs may start again after an earlier cancellation."""
    _CANCELLED.clear()


def _check_cancelled() -> None:
    if _CANCELLED.is_set():
        raise Cancelled("cancelled: no further sandboxed process is started")


def terminate_all() -> int:
    """Kill every sandboxed process group and container still running (Ctrl-C,
    SIGTERM), and refuse to start new ones until `allow_runs()`. Returns how
    many were stopped."""
    _CANCELLED.set()
    with _LIVE_LOCK:
        groups, containers = list(_LIVE_GROUPS), dict(_LIVE_CONTAINERS)
        _STOPPED[0] += len(groups) + len(containers)
    for pgid in groups:
        for kill in (os.killpg, os.kill):  # the group, and the process itself
            try:
                kill(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    with _LIVE_LOCK:
        markers, runs = set(_ISSUED_MARKERS), set(_LIVE_RUNS)
    if runs:  # seatbelt (no PID namespace): every process of a run not yet cleaned up, wherever it is now
        _reap_runs(runs, markers)
    for name, cli in containers.items():
        try:
            subprocess.run([cli, "rm", "-f", *(["-t", "0"] if Path(cli).name.startswith("podman") else []), name],
                           capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    return len(groups) + len(containers)


def stopped_total() -> int:
    return _STOPPED[0]


def cleanup_problems() -> list[str]:
    """Why the end of a seatbelt run could not be confirmed to have stopped
    every process it started (empty when every cleanup was confirmed)."""
    with _LIVE_LOCK:
        return list(_CLEANUP_PROBLEMS)


def live_count() -> int:
    with _LIVE_LOCK:
        return len(_LIVE_GROUPS) + len(_LIVE_CONTAINERS)


CAPTURE_BYTES = 64 * 1024  # per stream: the last part is kept, the rest is counted and dropped


class _Capture:
    """The last `CAPTURE_BYTES` of a pipe, read by a daemon thread, so that a
    test printing endlessly costs bounded host memory (`communicate()` kept
    everything). The thread ends when every writer of the pipe has closed it;
    a writer that left the run (detached, environment cleared) can keep it
    alive, and is then abandoned rather than waited for."""

    def __init__(self, stream) -> None:
        self.buf = bytearray()
        self.total = 0
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.thread.start()

    def _read(self, stream) -> None:
        try:
            while True:
                chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                if not chunk:
                    break
                self.total += len(chunk)
                self.buf += chunk
                if len(self.buf) > 2 * CAPTURE_BYTES:
                    del self.buf[:-CAPTURE_BYTES]
        except (OSError, ValueError):
            pass

    def done(self, timeout: float = 0.0) -> bool:
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def value(self) -> bytes:
        return bytes(self.buf[-CAPTURE_BYTES:])


def _tail(data: bytes | str | None) -> str:
    if data is None:
        return ""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return text[-OUTPUT_TAIL:]


class Backend:
    name = "none"

    def available(self) -> tuple[bool, str]:  # pragma: no cover - interface
        return False, "no backend"

    def run(self, argv: list[str], workspace: Path, *, limits: Limits, toolchain: str = "python",
            env: dict[str, str] | None = None) -> Result:  # pragma: no cover - interface
        raise SandboxUnavailable("no sandbox backend")


# --------------------------------------------------------------------------
# containers
# --------------------------------------------------------------------------
_CLI_PROBES: dict[tuple[str, str], tuple[float, Any]] = {}
_PROBE_TTL_S = 30.0


class ContainerBackend(Backend):
    binary = "podman"

    def __init__(self, images: dict[str, str] | None = None):
        self.name = self.binary
        self.images = {**DEFAULT_IMAGES, **(images or {})}

    def _cli(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> tuple[bool, str]:
        cli = self._cli()
        if not cli:
            return False, f"{self.binary} not installed"
        cached = _CLI_PROBES.get((cli, "info"))
        if cached is not None and time.monotonic() - cached[0] < _PROBE_TTL_S:
            return cached[1]  # one `info` call per command, not one per question
        result = self._probe(cli)
        _CLI_PROBES[(cli, "info")] = (time.monotonic(), result)
        return result

    def _probe(self, cli: str) -> tuple[bool, str]:
        try:
            proc = subprocess.run([cli, "info", "--format", "{{.Host.Arch}}"] if self.binary == "podman"
                                  else [cli, "info", "--format", "{{.Architecture}}"],
                                  capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"{self.binary} not responding: {exc}"
        if proc.returncode != 0:
            return False, f"{self.binary} not running ({proc.stderr.strip()[:120]})"
        return True, f"{self.binary} ({proc.stdout.strip()})"

    def _inspect(self, toolchain: str) -> tuple[bool, str]:
        """(the image is present locally, its identity), asked once per image
        per command (`_PROBE_TTL_S`). podman: the digest; docker: the image id."""
        cli = self._cli()
        image = self.images.get(toolchain, "")
        if not cli or not image:
            return False, ""
        cached = _CLI_PROBES.get((cli, image))
        if cached is not None and time.monotonic() - cached[0] < _PROBE_TTL_S:
            return cached[1]
        fmt = "{{.Digest}}" if self.binary == "podman" else "{{.Id}}"
        proc = subprocess.run([cli, "image", "inspect", "--format", fmt, image],
                              capture_output=True, text=True, timeout=30, check=False)
        result = (proc.returncode == 0, proc.stdout.strip() if proc.returncode == 0 else "")
        _CLI_PROBES[(cli, image)] = (time.monotonic(), result)
        return result

    def has_image(self, toolchain: str) -> bool:
        return self._inspect(toolchain)[0]

    def image_digest(self, toolchain: str) -> str:
        return self._inspect(toolchain)[1]

    def _user_args(self) -> list[str]:
        return []

    def argv_for(self, argv: list[str], workspace: Path, name: str, limits: Limits,
                 toolchain: str, env: dict[str, str],
                 ro_mounts: tuple[tuple[str, str], ...] = ()) -> list[str]:
        image = self.images.get(toolchain)
        if not image:
            raise SandboxUnavailable(f"no container image configured for toolchain {toolchain!r}")
        cmd = [self._cli() or self.binary, "run", "--rm", "--name", name,
               "--network", "none" if not limits.network else "slirp4netns",
               "--read-only", "--tmpfs", f"/tmp:rw,size={limits.tmpfs_mb}m,mode=1777",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", str(limits.pids), "--memory", f"{limits.memory_mb}m",
               "--cpus", str(limits.cpus), "--ulimit", f"fsize={limits.file_size_mb * 1024 * 1024}",
               "--ipc", "private", "--pull", "never",
               "-v", f"{workspace.resolve()}:/work:rw", "-w", "/work",
               "-e", "HOME=/tmp", *self._user_args()]
        for host, inside in ro_mounts:  # dependency directories: read-only
            cmd += ["-v", f"{host}:{inside}:ro"]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        return cmd + [image, *argv]

    def run(self, argv: list[str], workspace: Path, *, limits: Limits, toolchain: str = "python",
            env: dict[str, str] | None = None,
            ro_mounts: tuple[tuple[str, str], ...] = ()) -> Result:
        ok, why = self.available()
        if not ok:
            raise SandboxUnavailable(why)
        if not self.has_image(toolchain):
            raise SandboxUnavailable(f"image for {toolchain} not present locally "
                                     f"({self.images.get(toolchain)}); run `repo-ai sandbox pull`")
        check_workspace(workspace)
        name = f"repo-ai-{uuid.uuid4().hex[:12]}"
        cli = self._cli() or self.binary
        cmd = self.argv_for(argv, workspace, name, limits, toolchain, {**SAFE_ENV, **(env or {})}, ro_mounts)
        started = time.monotonic()
        _tell_guardian(f"+c {name} {cli}")
        with _LIVE_LOCK:
            _check_cancelled()
            _LIVE_CONTAINERS[name] = cli
        leftover = False
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                    env=_host_env())
            out_c, err_c = _Capture(proc.stdout), _Capture(proc.stderr)
            # the limit is the tests' own; the grace covers the client starting the container
            deadline = started + limits.timeout_s + CONTAINER_GRACE_S
            while True:
                try:
                    proc.wait(timeout=max(0.01, min(0.5, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    stalled = _stalled(limits)
                    if time.monotonic() >= deadline or stalled:
                        self._remove(cli, name)  # SIGKILL now: no stop timeout
                        proc.kill()
                        proc.wait()
                        out_c.done(DRAIN_S)
                        err_c.done(DRAIN_S)
                        return Result(124, _tail(out_c.value()), _tail(err_c.value()),
                                      time.monotonic() - started, True, self.name,
                                      ["timed out; container removed", *([f"watchdog: {stalled}"] if stalled else [])])
            out_c.done(DRAIN_S)
            err_c.done(DRAIN_S)
            return Result(proc.returncode, _tail(out_c.value()), _tail(err_c.value()),
                          time.monotonic() - started, False, self.name)
        except BaseException:  # cancelled: the client was killed, the container may still run
            if proc is not None and proc.poll() is None:
                proc.kill()
            try:
                self._remove(cli, name)
            except BaseException:  # noqa: BLE001 - interrupted again: stays registered for terminate_all()
                leftover = True
            raise
        finally:
            if not leftover:
                with _LIVE_LOCK:
                    _LIVE_CONTAINERS.pop(name, None)
                _tell_guardian(f"-c {name}")

    def _remove(self, cli: str, name: str) -> None:
        """Remove the container at once (SIGKILL): `podman rm -f` would first wait
        out a 10 s stop timeout for a process that ignores SIGTERM (pytest as PID 1)."""
        force = ["rm", "-f", "-t", "0"] if Path(cli).name.startswith("podman") else ["rm", "-f"]
        subprocess.run([cli, *force, name], capture_output=True, timeout=60, check=False,
                       stdin=subprocess.DEVNULL, env=_host_env())

    def pull(self, toolchain: str) -> bool:
        cli = self._cli()
        image = self.images.get(toolchain)
        if not cli or not image:
            return False
        return subprocess.run([cli, "pull", image], timeout=1800, check=False).returncode == 0


class PodmanBackend(ContainerBackend):
    binary = "podman"


class DockerBackend(ContainerBackend):
    binary = "docker"

    def _user_args(self) -> list[str]:
        # rootful docker: never run as container root. With --cap-drop ALL root
        # also lacks DAC_OVERRIDE, so it could not write the host-owned workspace.
        # (Rootless podman already maps container root to the invoking user.)
        if hasattr(os, "getuid"):
            return ["--user", f"{os.getuid()}:{os.getgid()}"]
        return []


def _host_env() -> dict[str, str]:
    """Environment for the container CLI itself (needs PATH and its socket
    configuration), never passed into the container."""
    keep = ("PATH", "HOME", "XDG_RUNTIME_DIR", "CONTAINER_HOST", "CONTAINER_CONNECTION",
            "DOCKER_HOST", "TMPDIR")
    return {k: v for k, v in os.environ.items() if k in keep}


# --------------------------------------------------------------------------
# host process sandboxes
# --------------------------------------------------------------------------
def _toolchain_dirs(toolchain: str) -> list[str]:
    """Directories a host-sandboxed command needs to read to run at all
    (once per process and PATH). Found from paths and pyenv's files only:
    nothing found on PATH is run."""
    return list(_toolchain_dirs_cached(toolchain, os.environ.get("PATH", ""),
                                       os.environ.get("JAVA_HOME", "")))


@functools.lru_cache(maxsize=16)
def _toolchain_dirs_cached(toolchain: str, _path: str, _java_home: str) -> tuple[str, ...]:
    dirs = {sys.base_prefix, sys.prefix, str(Path(sys.executable).resolve().parent.parent)}
    for tool in {"python": ["python3"], "node": ["node", "npm"],
                 "java": ["java", "javac"]}.get(toolchain, []) + ["sh", "git", "make"]:
        found = shutil.which(tool)
        if found:
            real = Path(found).resolve()
            if "shims" in real.parts:  # pyenv/asdf shim: where its interpreter lives, read, never run
                direct = pyenv_target(Path(found))
                if direct is not None:
                    dirs.add(str(direct.resolve().parent.parent))
                    continue
                # the version cannot be decided from pyenv's files: the shim's own installations, read-only. A shim
                # is never run on the host, since any file on PATH can be named like one (one inside the repository)
                versions = real.parent.parent / "versions"
                if versions.is_dir() and not versions.is_symlink():
                    dirs.add(str(versions.resolve()))
                continue
            if real.parent.parent in (Path("/opt/homebrew"), Path("/usr/local")):
                continue  # covered by the code directories in SYSTEM_READS, not etc/ or var/
            dirs.add(str(real.parent.parent))
    if toolchain == "java":  # /usr/bin/java is a launcher stub: use the JDK itself
        home = os.environ.get("JAVA_HOME", "")
        if not home and Path("/usr/libexec/java_home").exists():
            try:
                home = subprocess.run(["/usr/libexec/java_home"], capture_output=True, text=True,
                                      timeout=10, check=False).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                home = ""
        if home and (Path(home) / "bin" / "java").exists():
            dirs.add(str(Path(home).resolve()))
    return tuple(sorted(d for d in dirs if d and d != "/"))


def pyenv_target(shim: Path, cwd: Path | None = None) -> Path | None:
    """The interpreter a pyenv shim would run, found the way pyenv itself
    decides (PYENV_VERSION, the nearest `.python-version`, the global version
    file) without starting the shim, which costs about half a second. None
    when it cannot be decided this way (the caller then asks the shim)."""
    if shim.parent.name != "shims":
        return None
    root = Path(os.environ.get("PYENV_ROOT") or shim.parent.parent)
    version = os.environ.get("PYENV_VERSION", "").split(":")[0].strip()
    if not version:
        cur = (cwd or Path.cwd()).resolve()
        for d in (cur, *cur.parents):
            f = d / ".python-version"
            if f.is_file():
                version = next((ln.strip() for ln in f.read_text("utf-8", "replace").splitlines()
                                if ln.strip() and not ln.startswith("#")), "")
                break
    if not version:
        f = root / "version"
        if f.is_file():
            version = next((ln.strip() for ln in f.read_text("utf-8", "replace").splitlines()
                            if ln.strip() and not ln.startswith("#")), "")
    if not version or version == "system" or "/" in version or ".." in version:
        return None
    exe = root / "versions" / version / "bin" / shim.name
    return exe if exe.is_file() else None


def _safe_reads(paths: tuple[str, ...]) -> list[str]:
    """Extra read-only directories a caller asks for (a project's virtualenv):
    absolute, existing, never the filesystem root or the home directory
    itself, so a sandboxed run cannot be handed the user's whole home."""
    home = str(Path.home().resolve())
    out = []
    for raw in paths:
        try:
            real = str(Path(raw).resolve())
        except OSError:
            continue
        if os.path.isabs(raw) and Path(real).is_dir() and real not in {"/", home} \
                and Path(real).anchor != real and not home.startswith(real.rstrip("/\\") + os.sep):
            out.append(real)
    return out


def _preexec(limits: Limits):
    def apply() -> None:  # pragma: no cover - runs in the child
        import resource
        if hasattr(signal, "pthread_sigmask"):  # the parent blocks these around the start (`_run_host`)
            signal.pthread_sigmask(signal.SIG_UNBLOCK, _CANCEL_SIGNALS)
        os.setsid()  # own process group: the whole tree is killed on timeout
        cpu = int(limits.timeout_s) + 5
        for res, value in ((resource.RLIMIT_CPU, cpu),
                           (resource.RLIMIT_FSIZE, limits.file_size_mb * 1024 * 1024),
                           (resource.RLIMIT_CORE, 0)):
            try:
                resource.setrlimit(res, (value, value))
            except (ValueError, OSError):
                pass
    return apply


RUN_MARKER = "REPO_AI_SANDBOX_RUN"


_ISSUED_MARKERS: set[str] = set()  # every seatbelt run marker this process issued
_LIVE_RUNS: set[str] = set()       # seatbelt runs (preference domains) not yet confirmed cleaned up
_CLEANUP_PROBLEMS: list[str] = []


def _reap_runs(runs: set[str], markers: set[str]) -> list[str]:
    """Kill every process of these seatbelt runs, wherever it went (`setsid`, a
    double fork, launchd as its parent, a cleared environment, an Apple binary):
    each is found by the run's own sandbox profile (`_seatbelt_procs`). Returns
    why that could not be confirmed; a run confirmed clean is forgotten (and
    the guardian told), one that is not stays registered for `terminate_all()`
    and the guardian. Where the sandbox cannot be asked, the environment marker
    scan is the fallback, and the cleanup is never reported as confirmed."""
    if not runs:
        return []
    why_not = _identification_problem()
    if not why_not:
        _, problems = _procs.sweep(runs, _CONTROL)
    else:
        _reap_marked(markers)
        problems = [f"the processes of the run could not be enumerated by their sandbox ({why_not}; "
                    "only the environment-marker scan ran)"]
    if problems:
        problems = ["cleanup of the seatbelt run could not be confirmed: " + p for p in problems]
        with _LIVE_LOCK:
            _CLEANUP_PROBLEMS.extend(p for p in problems if p not in _CLEANUP_PROBLEMS)
        return problems
    with _LIVE_LOCK:
        _LIVE_RUNS.difference_update(runs)
        _ISSUED_MARKERS.difference_update(markers)
    for run in runs:
        _tell_guardian(f"-s {run}")
    return []


_IDENTIFIED: list[str] = []  # the self-identification's answer, once per process: "" when it works


def _identification_problem() -> str:
    """Why the run's processes cannot be found by their sandbox here ("" when
    they can). A sweep that finds nothing proves nothing unless the same check
    has recognised a process of a run: so once, a probe run (`/bin/sleep` under
    a profile with its own domain) must be identified as that run's, and as no
    other's. Any other answer (a macOS whose sandbox_check behaves otherwise,
    say) leaves the cleanup unconfirmed instead of confirmed by an empty sweep."""
    with _LIVE_LOCK:
        if _IDENTIFIED:
            return _IDENTIFIED[0]
    why = _identify_probe() if _procs.available() else "the sandbox cannot be asked on this system"
    with _LIVE_LOCK:
        if not _IDENTIFIED:
            _IDENTIFIED.append(why)
        return _IDENTIFIED[0]


def _identify_probe() -> str:
    probe, other = _procs.PREFIX + uuid.uuid4().hex, _procs.PREFIX + uuid.uuid4().hex
    try:
        with tempfile.TemporaryDirectory(prefix="repo-ai-probe-") as tmp:
            prof = SeatbeltBackend.profile(Path(tmp), "python", False, run_id=probe)
            proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", prof, "/bin/sleep", "30"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                answer: object = None
                for _ in range(200):  # until sandbox-exec has applied the profile and exec'd
                    answer = _procs.run_of(proc.pid, {probe}, _CONTROL)
                    if answer == probe or proc.poll() is not None:
                        break
                    time.sleep(0.01)
                if answer != probe:
                    return f"a probe run was not recognised as its own (answer {answer!r})"
                if _procs.run_of(proc.pid, {other}, _CONTROL) is not False:
                    return "a probe run was taken for another run"
                return ""
            finally:
                proc.kill()
                proc.wait()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return f"the probe run could not start ({exc})"


def _reap_marked(marker: str | set[str]) -> int:
    """Kill processes that left the run's process group (`setsid`, daemonising
    test servers) but still carry its environment marker: the fallback of
    `_reap_runs` where the sandbox cannot be asked. It misses a process that
    clears its environment and every Apple binary (macOS `ps -E` shows no
    environment for them), so it never confirms a cleanup. `marker` may be a
    set: every run this process started (cancellation)."""
    if not hasattr(os, "getuid"):
        return 0
    markers = {marker} if isinstance(marker, str) else set(marker)
    if not markers:
        return 0
    try:
        out = subprocess.run(["ps", "-axww", "-E", "-o", "pid=,uid=,command="], capture_output=True,
                             text=True, timeout=20, check=False, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    needles, me, killed = [f"{RUN_MARKER}={m}" for m in markers], os.getuid(), 0
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] == str(me) and parts[0].isdigit() and any(n in parts[2] for n in needles):
            try:
                os.kill(int(parts[0]), signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError, OSError):
                pass
    return killed


_CANCEL_SIGNALS = {getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP") if hasattr(signal, n)}
DRAIN_S = 5.0  # after the test process ended: how long its output may stay open


def _run_host(cmd: list[str], workspace: Path, limits: Limits, env: dict[str, str],
              backend: str, run_id: str = "") -> Result:
    """`run_id`: seatbelt's per-run preference domain, allowed by this run's
    profile only, by which every process of the run is found at its end."""
    started = time.monotonic()
    marker = _OWNER + uuid.uuid4().hex[:16]
    env = {**env, RUN_MARKER: marker}
    _guardian()  # started before the signals are masked below: it must not inherit that mask
    if backend == "seatbelt":
        with _LIVE_LOCK:
            _ISSUED_MARKERS.add(marker)
            if run_id:
                _LIVE_RUNS.add(run_id)
        if run_id:  # before the start: a run the guardian does not know of could outlive a SIGKILL
            _tell_guardian(f"+s {run_id}")
    # A cancellation signal handled between the fork and the registration below would leave a
    # process nothing knows about (the child has not exec'd yet, so it has no marker either): in
    # the main thread, where Python runs signal handlers, the signals wait until it is registered.
    masked = None
    if hasattr(signal, "pthread_sigmask") and threading.current_thread() is threading.main_thread():
        masked = signal.pthread_sigmask(signal.SIG_BLOCK, _CANCEL_SIGNALS)
    try:
        with _LIVE_LOCK:  # registered before terminate_all() can miss it
            _check_cancelled()
            proc = subprocess.Popen(cmd, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, env=env, preexec_fn=_preexec(limits))
            _LIVE_GROUPS.add(proc.pid)  # setsid: the child's pid is its process group
        try:
            _tell_guardian(f"+g {proc.pid}")
        except Exception:  # noqa: BLE001 - the guardian is a safety net; the run's own cleanup still holds
            pass
    except BaseException:
        if masked is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, masked)
        raise
    out_c, err_c = _Capture(proc.stdout), _Capture(proc.stderr)
    notes: list[str] = []
    runs = {run_id} if backend == "seatbelt" and run_id else set()
    mark = marker if backend == "seatbelt" else None
    reap = (lambda: _reap_runs(runs, {marker})) if runs else ((lambda: _reap_marked(marker)) if mark else None)
    result: Result | None = None
    try:
        if masked is not None:  # a pending signal is handled here, inside the cleanup below
            signal.pthread_sigmask(signal.SIG_SETMASK, masked)
            masked = None
        deadline = started + limits.timeout_s
        timed_out = False
        while True:
            # wake on end-of-file (the readers finish when every writer closed the pipes: no
            # polling delay on the common path), or every 0.5 s to check the leader and the limit
            pending = out_c if not out_c.done() else err_c  # wait on a pipe still open (no busy loop)
            pending.done(max(0.0, min(0.5, deadline - time.monotonic())))
            if out_c.done() and err_c.done():
                try:
                    proc.wait(timeout=max(0.01, deadline - time.monotonic()))
                    break
                except subprocess.TimeoutExpired:
                    timed_out = True
                    break
            if proc.poll() is not None:
                break  # the leader ended; its output may still be held (handled below)
            if time.monotonic() >= deadline:
                timed_out = True
                break
            stalled = _stalled(limits)
            if stalled:
                timed_out = True
                notes.append(f"watchdog: {stalled}")
                break
        if timed_out:
            _kill_group(proc.pid, reap, leader=proc)
            _settle(out_c, err_c, notes)
            result = Result(124, _tail(out_c.value()), _tail(err_c.value()), time.monotonic() - started, True,
                            backend, ["timed out; process group killed", *notes])
            return result
        if not (out_c.done(0.2) and err_c.done(0.2)):
            # the test process ended but something it started keeps its output open (a
            # daemonised server, say): end the run now instead of waiting for the limit
            _kill_group(proc.pid, reap)
            if _settle(out_c, err_c, notes):
                notes.insert(0, "a process the tests started kept running after they ended; it was killed")
        result = Result(proc.returncode, _tail(out_c.value()), _tail(err_c.value()),
                        time.monotonic() - started, False, backend, notes)
        return result
    except BaseException:  # cancelled while waiting: never leave the tree running
        _kill_group(proc.pid, reap, leader=proc)
        raise
    finally:
        _kill_group(proc.pid, None, leader=proc)  # whatever the outcome, nothing in the group outlives it
        with _LIVE_LOCK:  # before the (slower) scan: a pid is never signalled after reuse
            _LIVE_GROUPS.discard(proc.pid)
        _tell_guardian(f"-g {proc.pid}")
        if runs:  # no PID namespace: every process of the run, wherever it went; said when unconfirmed
            problems = _reap_runs(runs, {marker})
            if result is not None:
                result.notes.extend(p for p in problems if p not in result.notes)
        elif mark:
            _reap_marked(marker)
        for pipe, cap in ((proc.stdout, out_c), (proc.stderr, err_c)):
            # never close a pipe its reader is still blocked on: close() would wait for the
            # reader's lock (a deadlock); an abandoned daemon reader keeps it until the writer goes
            if pipe and cap.done():
                try:
                    pipe.close()
                except OSError:
                    pass


def _stalled(limits: Limits) -> str:
    """The progress check's answer; a failing check never ends a run."""
    if limits.watch is None:
        return ""
    try:
        return str(limits.watch() or "")
    except Exception:  # noqa: BLE001 - the watchdog can only shorten a run, never break one
        return ""


def _settle(out_c: _Capture, err_c: _Capture, notes: list[str]) -> bool:
    """Wait (bounded) for the output pipes to close after the group was
    killed. False, with a note, when a process outside the group still holds
    them: the run does not wait for it."""
    deadline = time.monotonic() + DRAIN_S
    closed = out_c.done(max(0.0, deadline - time.monotonic())) and err_c.done(max(0.0, deadline - time.monotonic()))
    if not closed:
        notes.append("a process the tests started left the run's process group and still holds its output; "
                     "the run did not wait for it")
    return closed


def _kill_group(pgid: int, reap=None, leader: subprocess.Popen | None = None) -> None:
    """SIGKILL the whole group, again until it is gone (bounded): one
    `killpg` races a member that is forking at that moment. Then `reap()`:
    what left the group (seatbelt)."""
    for _ in range(40):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            break
        except (PermissionError, OSError):
            if leader is not None and leader.poll() is None:
                leader.kill()
            break
        if leader is not None:
            leader.poll()  # reap the leader: a zombie still counts as a member
        time.sleep(0.005)
    if reap is not None:
        reap()


def _minimal_env(workspace: Path, toolchain: str, extra: dict[str, str]) -> dict[str, str]:
    path = os.pathsep.join(dict.fromkeys(
        [str(Path(p)) + "/bin" for p in _toolchain_dirs(toolchain)]
        + ["/usr/local/bin", "/usr/bin", "/bin"]))
    home = workspace / ".sandbox-home"
    home.mkdir(exist_ok=True)
    env = {**SAFE_ENV, "PATH": path, "HOME": str(home), "TMPDIR": str(home)}
    dev = _developer_dir()
    if dev:  # macOS /usr/bin shims (git, make) find the toolchain without searching the disk
        env["DEVELOPER_DIR"] = dev
    return {**env, **extra}


@functools.lru_cache(maxsize=1)
def _developer_dir() -> str:
    if platform.system() != "Darwin":
        return ""
    if os.environ.get("DEVELOPER_DIR"):
        return os.environ["DEVELOPER_DIR"]
    link = Path("/private/var/db/xcode_select_link")  # what `xcode-select -p` reads (it takes ~0.8s)
    try:
        if link.is_symlink() and link.resolve().is_dir():
            return str(link.resolve())
    except OSError:
        pass
    try:
        out = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, text=True,
                             timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out if out and Path(out).is_dir() else ""


class SeatbeltBackend(Backend):
    name = "seatbelt"

    def available(self) -> tuple[bool, str]:
        if platform.system() != "Darwin":
            return False, "macOS only"
        if not Path("/usr/bin/sandbox-exec").exists():
            return False, "sandbox-exec missing"
        return True, "macOS sandbox-exec (shared kernel; weaker than a container)"

    # Read-only system locations a toolchain needs; nothing user-owned.
    _BREW = ("bin", "sbin", "lib", "libexec", "Cellar", "opt", "share", "include", "Frameworks")
    SYSTEM_READS = ("/usr/bin", "/usr/sbin", "/usr/lib", "/usr/libexec", "/usr/share", "/bin", "/sbin",
                    "/System", "/Library/Frameworks", "/Library/Java", "/Library/Developer/CommandLineTools",
                    "/private/etc", "/private/var/db/timezone", "/private/var/db/dyld", "/dev",
                    "/private/var/select", "/private/var/db/xcode_select_link",
                    *(f"/opt/homebrew/{d}" for d in _BREW), *(f"/usr/local/{d}" for d in _BREW))
    # single configuration files a Homebrew toolchain reads at start-up (Node's OpenSSL fails to
    # start without its openssl.cnf, whichever OpenSSL major it links: @1.1, @3, @4); never the
    # directories around them (`private/` keys)
    SYSTEM_READ_FILE_GLOBS = ("/opt/homebrew/etc/openssl*/openssl.cnf", "/usr/local/etc/openssl*/openssl.cnf")

    @staticmethod
    def profile(workspace: Path, toolchain: str, network: bool, extra_reads: tuple[str, ...] = (),
                run_id: str = "") -> str:
        """Deny by default. Allowed: exec and fork, signals inside this
        sandbox only, path metadata (stat), reads of system and toolchain
        directories and the workspace, writes to the workspace only. Denied
        by omission: other reads (home, /Users, /Volumes, temp roots), all
        Mach services (LaunchServices `open`, Apple Events, pasteboard),
        signals to processes outside the sandbox, and the network.
        `run_id`: a preference domain only this run's profile allows. It grants
        nothing (preferences are read through cfprefsd, a Mach service that
        stays denied); it is how the run's processes are recognised at its end
        (`_seatbelt_procs`)."""
        ws = str(workspace.resolve())
        reads = sorted({*SeatbeltBackend.SYSTEM_READS, *_toolchain_dirs(toolchain), ws,
                        *_safe_reads(extra_reads)})
        reads = [d for d in reads if Path(d).exists() or d == ws]
        import glob as _glob
        files = sorted({f for pattern in SeatbeltBackend.SYSTEM_READ_FILE_GLOBS for f in _glob.glob(pattern)
                        if Path(f).is_file() and '"' not in f})
        read_rules = "".join(f'\n  (subpath "{d}")' for d in reads) + "".join(f'\n  (literal "{f}")' for f in files)
        # stat() only on the ancestors of what is readable (path resolution), nothing else
        ancestors = sorted({str(p) for d in [*reads, *files] for p in Path(d).parents})
        meta_rules = "".join(f'\n  (literal "{a}")' for a in ancestors)
        if run_id and not (run_id.startswith(_procs.PREFIX) and run_id[len(_procs.PREFIX):].isalnum()):
            raise ValueError(f"not a run id: {run_id!r}")
        identity = f'(allow user-preference-read (preference-domain "{run_id}"))\n' if run_id else ""
        return f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow file-read-metadata{meta_rules})
(allow file-read* (literal "/") (literal "/etc") (literal "/var") (literal "/tmp"){read_rules})
(allow file-write*
  (subpath "{ws}")
  (literal "/dev/null") (literal "/dev/tty") (literal "/dev/dtracehelper") (regex #"^/dev/fd/"))
(allow file-ioctl (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/fd/"))
(allow ipc-posix-shm* ipc-posix-sem*)
{identity}{"(allow network*)" if network else ""}
"""

    def run(self, argv: list[str], workspace: Path, *, limits: Limits, toolchain: str = "python",
            env: dict[str, str] | None = None, extra_reads: tuple[str, ...] = (),
            allowed_links: dict[str, str] | None = None) -> Result:
        ok, why = self.available()
        if not ok:
            raise SandboxUnavailable(why)
        check_workspace(workspace, allowed_links)
        run_id = _procs.PREFIX + uuid.uuid4().hex
        prof = self.profile(workspace, toolchain, limits.network, extra_reads, run_id=run_id)
        cmd = ["/usr/bin/sandbox-exec", "-p", prof, *argv]
        return _run_host(cmd, workspace, limits, _minimal_env(workspace, toolchain, env or {}),
                         self.name, run_id=run_id)


def _hides_temp(path: str) -> bool:
    """A directory whose bind would re-expose a shared temporary root under the run's private `/tmp`:
    the root itself (`/tmp`, `/var/tmp`, `/dev/shm`, the resolved temp dir) or any ancestor of one.
    A specific directory below one (a virtualenv in /tmp/x) is fine."""
    roots = {"/tmp", "/var/tmp", "/dev/shm"}
    for raw in ("/tmp", "/var/tmp", tempfile.gettempdir()):
        try:
            roots.add(str(Path(raw).resolve()))
        except OSError:
            pass
    p = path.rstrip("/") or "/"
    return any(p == r or r.startswith(p + "/") or (p == "/" and r) for r in roots)


class BwrapBackend(Backend):
    name = "bwrap"

    def available(self) -> tuple[bool, str]:
        if platform.system() != "Linux":
            return False, "Linux only"
        exe = shutil.which("bwrap")
        if not exe:
            return False, "bubblewrap (bwrap) not installed"
        # the same namespaces and mounts a real run uses: /proc and /dev can fail where the
        # namespaces alone succeed (inside containers, under AppArmor userns restrictions)
        probe = subprocess.run([exe, "--unshare-all", "--die-with-parent", "--new-session", "--ro-bind", "/", "/",
                                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "true"],
                               capture_output=True, timeout=20, check=False)
        if probe.returncode != 0:
            return False, "bwrap cannot create namespaces here (" + \
                probe.stderr.decode("utf-8", "replace").strip()[:120] + ")"
        return True, "bubblewrap namespaces"

    def run(self, argv: list[str], workspace: Path, *, limits: Limits, toolchain: str = "python",
            env: dict[str, str] | None = None, extra_reads: tuple[str, ...] = (),
            allowed_links: dict[str, str] | None = None) -> Result:
        ok, why = self.available()
        if not ok:
            raise SandboxUnavailable(why)
        check_workspace(workspace, allowed_links)
        ws = str(workspace.resolve())
        cmd = [shutil.which("bwrap") or "bwrap", "--unshare-all", "--die-with-parent",
               "--new-session", "--clearenv",
               # first, so read-only toolchain binds below /tmp (a venv there) are not hidden by it
               "--tmpfs", "/tmp"]
        if limits.network:
            cmd.append("--share-net")
        for system_dir in ("/usr", "/bin", "/lib", "/lib64", "/sbin", "/etc/alternatives",
                           "/etc/ssl", "/opt"):
            if Path(system_dir).exists():
                cmd += ["--ro-bind", system_dir, system_dir]
        for tool_dir in [*_toolchain_dirs(toolchain), *_safe_reads(extra_reads)]:
            if Path(tool_dir).exists() and not tool_dir.startswith(("/usr", "/bin", "/lib")) \
                    and not _hides_temp(tool_dir):
                cmd += ["--ro-bind", tool_dir, tool_dir]
        cmd += ["--proc", "/proc", "--dev", "/dev",
                "--bind", ws, ws, "--chdir", ws]
        menv = _minimal_env(workspace, toolchain, env or {})
        for key, value in menv.items():
            cmd += ["--setenv", key, value]
        return _run_host([*cmd, *argv], workspace, limits, menv, self.name)


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------
BACKENDS: dict[str, type[Backend]] = {"podman": PodmanBackend, "docker": DockerBackend, "bwrap": BwrapBackend,
            "seatbelt": SeatbeltBackend}
AUTO_ORDER = ("podman", "docker", "bwrap", "seatbelt")


def get_backend(preference: str = "auto", images: dict[str, str] | None = None,
                toolchain: str | None = None) -> Backend:
    """The strongest available backend. `toolchain` requires a container
    image for it (or a host backend)."""
    names = AUTO_ORDER if preference == "auto" else (preference,)
    reasons = []
    for name in names:
        cls = BACKENDS.get(name)
        if cls is None:
            raise SandboxUnavailable(f"unknown sandbox backend {name!r}")
        backend: Backend = cls(images) if issubclass(cls, ContainerBackend) else cls()
        ok, why = backend.available()
        if ok and isinstance(backend, ContainerBackend) and toolchain and \
                not backend.has_image(toolchain):
            ok, why = False, f"image for {toolchain} not pulled"
        if ok:
            return backend
        reasons.append(f"{name}: {why}")
    raise SandboxUnavailable("no sandbox backend available (" + "; ".join(reasons) + "). "
                             "Untrusted code is never run unsandboxed; only static inspection "
                             "is possible.")


def status(images: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows = []
    for name in AUTO_ORDER:
        cls = BACKENDS[name]
        backend: Backend = cls(images) if issubclass(cls, ContainerBackend) else cls()
        ok, why = backend.available()
        row: dict[str, Any] = {"backend": name, "available": ok, "detail": why}
        if ok and isinstance(backend, ContainerBackend):
            row["images"] = {tc: {"image": img, "present": backend.has_image(tc),
                                  "digest": backend.image_digest(tc) if backend.has_image(tc) else ""}
                             for tc, img in backend.images.items()}
        rows.append(row)
    return rows
