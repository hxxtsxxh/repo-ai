"""Offline provider discovery and explicit, network-denied help probes.

This module never runs an agent. Observing a documented headless flag does not
establish authentication, entitlement, hard budget enforcement, or live support.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..provider_names import PROVIDERS  # re-exported: defined where argument parsing can import it cheaply
# A provider that drives another provider's executable through a different transport (`opencode acp`: the Agent
# Client Protocol) is named after its transport; its executable keeps the vendor's name.
EXECUTABLES = {"opencode-acp": "opencode"}
MAX_OUTPUT = 65_536
MAX_EXECUTABLE = 512 * 1024 * 1024


@dataclass(frozen=True)
class ProbeResult:
    returncode: int
    status: str
    output: bytes
    # Populated only when `separate_stderr=True`: diagnostics are kept out of the
    # structured event channel so a CLI's stderr banner cannot corrupt (or forge) it.
    stderr: bytes = b""


def executable_name(provider: str) -> str:
    """The executable a provider runs (looked up on PATH): the provider's own name unless it is a transport variant."""
    return EXECUTABLES.get(provider, provider)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _repo_owned(path: str | Path, root: Path) -> bool:
    """Whether an executable path (as found, resolved, or with its directory resolved) lies inside the repository,
    also on a case-insensitive filesystem where `/REPO/bin` and `/repo/bin` are the same directory."""
    raw = Path(os.path.abspath(path))
    candidates = [raw]
    try:
        candidates += [raw.resolve(strict=True), raw.parent.resolve(strict=True) / raw.name]
    except (OSError, RuntimeError):
        pass
    root = root.resolve()
    for candidate in candidates:
        if _inside(candidate, root):
            return True
        for parent in candidate.parents:
            try:
                if os.path.samefile(parent, root):
                    return True
            except OSError:
                continue
    return False


def _identity(path: Path) -> str:
    """Hash a bounded regular entrypoint, refusing symlink/FIFO replacement."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EXECUTABLE:
            raise ValueError("unbounded or nonregular executable")
        digest = hashlib.sha256()
        total = 0
        while chunk := handle.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_EXECUTABLE:
                raise ValueError("executable grew beyond identity limit")
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("executable changed during hashing")
        return digest.hexdigest()


def _probe_env(scratch: Path) -> dict[str, str]:
    home = scratch / "home"
    return {
        "PATH": os.defpath, "HOME": str(home), "USERPROFILE": str(home),
        "TMPDIR": str(scratch / "tmp"), "TMP": str(scratch / "tmp"),
        "TEMP": str(scratch / "tmp"), "CODEX_HOME": str(home / ".codex"),
        "GEMINI_CLI_HOME": str(home / ".gemini"), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "LANG": "en_US.UTF-8", "TERM": "dumb", "NO_COLOR": "1", "CI": "1",
    }


# Where host unix sockets live on Linux, hidden from the bubblewrap probe (`--unshare-net` cuts abstract sockets, not
# path-based ones): D-Bus and the systemd user manager under /run, X11 and agents under /tmp, docker under /var/run,
# WSLg's X11 and Wayland, LXD and Incus, and the per-user agent and control sockets kept in these home directories.
# Other locations stay reachable (disclosed on the providers page).
_HIDDEN_ROOTS = ("/tmp", "/run", "/var/run", "/var/tmp", "/mnt/wslg", "/var/lib/lxd", "/var/snap/lxd",
                 "/var/lib/incus")
_HIDDEN_HOME = (".ssh", ".gnupg", ".1password", ".docker")


def _homes() -> list[str]:
    homes = [os.path.expanduser("~")]  # $HOME, and the account's home when HOME points elsewhere (sudo -E)
    try:
        import pwd
        homes.append(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError, OSError):
        pass
    return [h for h in dict.fromkeys(homes) if h not in {"", "/", "~"}]


def _hidden_dirs() -> list[str]:
    candidates = [*_HIDDEN_ROOTS, *(os.path.join(h, d) for h in _homes() for d in _HIDDEN_HOME)]
    # a tmpfs needs a real directory; a symlink such as /var/run -> /run is covered by its target
    return [d for d in dict.fromkeys(candidates) if os.path.isdir(d) and not os.path.islink(d)]


def _has_socket(directory: str) -> bool:
    """A unix socket directly inside `directory` (a runtime directory such as /run/user/<uid>): never bound back."""
    try:
        with os.scandir(directory) as entries:
            return any(stat.S_ISSOCK(e.stat(follow_symlinks=False).st_mode) for e in entries)
    except OSError:
        return True


# The only Mach services a probed program may look up on macOS: the per-user temporary directory, user and group
# lookups (getpwuid; the same facts /etc/passwd gives) and notifications. Everything else (the pasteboard, the
# keychain through securityd, WindowServer, login items) is denied. Measured 2026-11-01 on Darwin 25.5: with every
# lookup denied, the --version and --help output of codex, claude, bob, agy, opencode and opencode-acp was
# byte-identical to the unrestricted profile's; Apple's python3 shim needs the temporary-directory helper.
PROBE_MACH_ALLOW = ("com.apple.bsd.dirhelper", "com.apple.system.opendirectoryd.libinfo",
                    "com.apple.system.DirectoryService.libinfo_v1", "com.apple.system.notification_center")


def _sandbox_prefix(scratch: Path, expose: tuple[Path, ...] | list[Path] = ()) -> list[str] | None:
    """No supported network-denying boundary means no executable probe. `expose`: the files and directories the probed
    program needs (itself, its directory, its runtime's), bound back read-only on Linux when they lie under a hidden
    directory. A hidden directory itself is never bound back (an agent directly in /tmp is bound as a file)."""
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        # `open` (LaunchServices) and Apple events would start a program outside this sandbox, with the network and
        # outside the sweep; launchd job creation is denied as well (defence in depth: on Darwin 25.5 launchd already
        # refused `launchctl submit` from a sandboxed caller); cfprefsd writes preferences outside the scratch
        # directory on the caller's behalf; system services are denied but for PROBE_MACH_ALLOW
        allow = "".join(f"(global-name {json.dumps(n)})" for n in PROBE_MACH_ALLOW)
        profile = ("(version 1)(allow default)(deny lsopen)(deny appleevent-send)(deny job-creation)"
                   f"(deny user-preference-write)(deny mach-lookup)(allow mach-lookup {allow})"
                   "(deny network*)(deny file-write*)"
                   f"(allow file-write* (subpath {json.dumps(str(scratch.resolve()))}))")
        return ["/usr/bin/sandbox-exec", "-p", profile]
    if sys.platform.startswith("linux"):
        bwrap = shutil.which("bwrap", path=os.defpath)
        if bwrap:
            # host socket directories are hidden first; the program's own directories are bound back read-only (an
            # agent under /tmp still runs), then the scratch directory, writable
            # order: hidden directories; the program's directories (none holding a socket); hidden directories inside
            # those again (a bind brings back the host's whole subtree); the program's files; the scratch directory
            dirs = _hidden_dirs()
            hidden = [a for d in dirs for a in ("--tmpfs", d)]
            under = [p for p in dict.fromkeys(str(Path(x).resolve()) for x in expose)
                     if p not in dirs and any(p.startswith(d.rstrip("/") + "/") for d in dirs)]
            shown_dirs = [p for p in under if os.path.isdir(p) and not _has_socket(p)]
            shown_files = [p for p in under if os.path.isfile(p)]  # regular files only (never a socket)
            again = [d for d in dirs if any(d.startswith(p.rstrip("/") + "/") for p in shown_dirs)]
            back = [*(a for p in shown_dirs for a in ("--ro-bind", p, p)), *(a for d in again for a in ("--tmpfs", d)),
                    *(a for p in shown_files for a in ("--ro-bind", p, p))]
            return [bwrap, "--unshare-net", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
                    "--new-session", "--ro-bind", "/", "/", *hidden, *back, "--bind", str(scratch), str(scratch),
                    "--proc", "/proc", "--dev", "/dev", "--"]
    return None


def _stop(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        elif proc.poll() is None:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass


def _capture(argv: list[str], cwd: Path, env: dict[str, str], *,
             timeout: float = 5.0, output_limit: int = MAX_OUTPUT,
             separate_stderr: bool = False, max_timeout: float = 30.0) -> ProbeResult:
    """Bound memory, elapsed time, and process-group lifetime without a shell."""
    if not 0 < timeout <= max_timeout or not 0 < max_timeout <= 900 or not 0 < output_limit <= MAX_OUTPUT * 4:
        raise ValueError("invalid probe bounds")
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE if separate_stderr else subprocess.STDOUT,
                                start_new_session=True)
    except OSError:
        return ProbeResult(-1, "unavailable", b"")
    output = bytearray()
    errout = bytearray()
    overflow = threading.Event()
    finished = threading.Event()
    err_finished = threading.Event()
    if not separate_stderr:
        err_finished.set()

    stop_readers = threading.Event()
    read_failed = threading.Event()

    def read(pipe: Any, destination: bytearray, done: threading.Event) -> None:
        try:
            while not stop_readers.is_set():
                # POSIX pipes may be inherited by detached descendants outside
                # our process group. Never leave a blocked reader behind.
                if os.name == "posix" and not select.select([pipe], [], [], .05)[0]:
                    continue
                chunk = os.read(pipe.fileno(), 4096)
                if not chunk:
                    break
                remaining = max(0, output_limit - len(destination))
                destination.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
        except OSError:
            read_failed.set()
        finally:
            done.set()

    assert proc.stdout is not None
    reader = threading.Thread(target=read, args=(proc.stdout, output, finished), daemon=True)
    reader.start()
    err_reader = (threading.Thread(target=read, args=(proc.stderr, errout, err_finished), daemon=True)
                  if separate_stderr else None)
    if err_reader is not None:
        err_reader.start()
    deadline = time.monotonic() + timeout
    status = "complete"
    try:
        while not (finished.is_set() and err_finished.is_set() and proc.poll() is not None):
            if overflow.is_set():
                status = "output_limit"
                break
            if time.monotonic() >= deadline:
                status = "timeout"
                break
            if proc.poll() is not None:
                _stop(proc)  # a child must not keep inherited output pipes alive
            if finished.is_set():
                time.sleep(.01)
            else:
                finished.wait(.01)
    finally:
        _stop(proc)
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
        reader.join(timeout=.2)
        if err_reader is not None:
            err_reader.join(timeout=.2)
        if reader.is_alive() or (err_reader is not None and err_reader.is_alive()):
            status = "incomplete_capture"
        stop_readers.set()
        reader.join(timeout=.2)
        if err_reader is not None:
            err_reader.join(timeout=.2)
            if not err_reader.is_alive() and proc.stderr is not None:
                proc.stderr.close()
        if proc.stdout is not None and not reader.is_alive():
            proc.stdout.close()
    if overflow.is_set():
        status = "output_limit"
    if read_failed.is_set() or reader.is_alive() or (err_reader is not None and err_reader.is_alive()):
        status = "incomplete_capture"
    return ProbeResult(proc.returncode if proc.returncode is not None else -1, status, bytes(output), bytes(errout))


def _version(provider: str, output: bytes) -> str | None:
    line = output.decode("utf-8", "replace").splitlines()
    if not line:
        return None
    version = r"(\d+\.\d+\.\d+(?:[-+][\w.]+)?)"
    pattern = {"codex": rf"codex-cli {version}", "claude": rf"{version} \(Claude Code\)",
               "opencode": rf"opencode v?{version}", "opencode-acp": rf"opencode v?{version}"}.get(provider, version)
    match = re.fullmatch(pattern, line[0].strip())
    return match.group(1) if match else None


def _observed_modes(provider: str, output: bytes) -> list[str]:
    text = output.decode("utf-8", "replace")
    expected = {"codex": "codex exec", "claude": "claude", "bob": "bob run", "agy": "agy",
                "opencode": "opencode run", "opencode-acp": "opencode acp"}[provider]
    if provider in {"opencode", "opencode-acp"}:  # "USAGE" heading, usage line indented below it
        if not re.search(rf"(?m)^USAGE\s*\n\s+{re.escape(expected)}(?:\s|$)", text):
            return []
        if provider == "opencode-acp":  # an ACP server on stdio: non-interactive, and its protocol is the event stream
            return ["headless", "structured_events"]
    elif not re.search(rf"(?m)^Usage(?: of)?:? {re.escape(expected)}:?(?:\s|$)", text):
        return []
    flags = set(re.findall(r"(?m)^\s+(?:-\w, )?(--[\w-]+)(?=[\s,=]|$)", text))
    headless = provider in {"codex", "bob", "opencode"} or "--print" in flags
    modes = ["headless"] if headless else []
    event_flag = {"codex": "--json", "claude": "--output-format", "bob": "--format",
                  "agy": "--output-format", "opencode": "--format"}[provider]
    if event_flag in flags:
        modes.append("structured_events")
    if "--resume" in flags or re.search(r"(?m)^\s+resume\s", text):
        modes.append("native_resume_declared")
    if flags & {"--max-budget-usd", "--max-cost"}:
        modes.append("cost_limit_declared")
    return modes


def _one(provider: str, root: Path, probe: bool) -> dict[str, Any]:
    from .adapters import contract_for
    executable = shutil.which(executable_name(provider))
    profile: dict[str, Any] = {
        "provider": provider, "status": "NOT_INSTALLED", "stage": "NOT_INSTALLED",
        "executable": executable,
        "version": None, "identity_sha256": None, "authentication": "UNKNOWN", "modes": [],
        "contract": contract_for(provider).to_json(),
        "provenance": [], "limitations": ["No live model invocation; authentication, entitlement, prices and rate limits are unknown."],
    }
    if not executable:
        return profile
    raw = Path(os.path.abspath(executable))
    try:
        resolved = raw.resolve(strict=True)
        if _repo_owned(raw, root):
            profile["status"] = "UNTRUSTED_EXECUTABLE"
            profile["stage"] = "BLOCKED"
            profile["limitations"].append("Repository-owned executable or alias refused; it was not executed.")
            return profile
        identity = _identity(resolved)
    except (OSError, RuntimeError, ValueError):
        profile["status"] = "PROBE_FAILED"
        profile["stage"] = "FAILED"
        profile["limitations"].append("Executable identity could not be established.")
        return profile
    profile.update(status="PLANNING_ONLY", stage="DISCOVERED", executable=str(resolved), identity_sha256=identity)
    profile["provenance"].append({"kind": "entrypoint_sha256", "status": "observed", "sha256": identity})
    profile["limitations"].append("Entrypoint identity does not fingerprint imported runtime/package dependencies.")
    if not probe:
        profile["limitations"].append("Static discovery only; help/version were not executed.")
        return profile
    with tempfile.TemporaryDirectory(prefix="repo-ai-provider-probe-") as directory:
        scratch = Path(directory).resolve()
        for name in ("home", "tmp", "work", "home/.codex", "home/.gemini", "home/.claude"):
            (scratch / name).mkdir()
        runtime = shutil.which("node", path=os.environ.get("PATH", os.defpath))
        node_dir = [Path(runtime).resolve().parent] if runtime else []
        prefix = _sandbox_prefix(scratch, [resolved, resolved.parent, *node_dir])
        if prefix is None:
            profile["provenance"].append({"kind": "help_probe", "status": "NOT_RUN"})
            profile["limitations"].append("No supported network-denying probe sandbox; no subprocess was run.")
            return profile
        env = _probe_env(scratch)
        # Node CLIs use /usr/bin/env node. Its installation directory is selected
        # explicitly; inherited PATH hooks, cwd entries and injected Node options are not copied.
        if runtime:
            runtime_path = Path(runtime).resolve()
            if not _inside(runtime_path, root) and not _inside(Path(os.path.abspath(runtime)), root):
                env["PATH"] = str(runtime_path.parent) + os.pathsep + os.defpath
        commands = [["--version"], ["exec", "--help"] if provider == "codex" else
                    ["run", "--help"] if provider in {"bob", "opencode"} else
                    ["acp", "--help"] if provider == "opencode-acp" else ["--help"]]
        results: list[ProbeResult] = []
        for args in commands:
            result = _capture([*prefix, str(resolved), *args], scratch / "work", env)
            results.append(result)
            profile["provenance"].append({"kind": "help_probe", "argv": [executable_name(provider), *args],
                                          "status": result.status, "returncode": result.returncode,
                                          "output_bytes": len(result.output),
                                          "output_sha256": hashlib.sha256(result.output).hexdigest()})
            if result.status != "complete" or result.returncode != 0:
                break
        try:
            unchanged = raw.resolve(strict=True) == resolved and _identity(resolved) == identity
        except (OSError, RuntimeError, ValueError):
            unchanged = False
        if not unchanged:
            profile.update(status="PROBE_FAILED", stage="FAILED", modes=[])
            profile["limitations"].append("Executable changed during probing; observations were discarded.")
            return profile
        if len(results) != 2 or any(r.status != "complete" or r.returncode != 0 for r in results):
            profile["status"] = "PROBE_FAILED"
            profile["stage"] = "FAILED"
            profile["limitations"].append("Help/version probe failed or reached its resource limit; no runtime capability inferred.")
            return profile
        version = _version(provider, results[0].output)
        modes = _observed_modes(provider, results[1].output)
        if version is None or not modes:
            profile["status"] = "PROBE_FAILED"
            profile["stage"] = "FAILED"
            profile["limitations"].append("Unrecognized version/help format; no invocation support inferred.")
            return profile
        profile.update(version=version, modes=modes, stage="PROBED")
        profile["provenance"].append({"kind": "capabilities", "status": "help_observed"})
        profile["limitations"].append("Flags are declared by local help, not exercised live; provider execution requires explicit authorization.")
        if "cost_limit_declared" not in modes:
            profile["limitations"].append("No monetary limit discovered; a strict dollar budget cannot be assumed enforceable.")
    return profile


def discover(root: Path, probe: bool = False) -> list[dict[str, Any]]:
    """List installed entrypoints; explicit probes inspect help/version only.

    Neither mode reads provider credentials or accepts repository instructions
    as authority. No raw provider output is retained in returned profiles.
    """
    root = root.resolve()
    return [_one(provider, root, probe) for provider in PROVIDERS]
