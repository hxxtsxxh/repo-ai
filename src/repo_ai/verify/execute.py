"""Authorized execution of test commands, always through an OS-enforced
sandbox (``repo_ai.sandbox``) and always in a disposable workspace
(``isolate``): no network, writes confined to the copy, a clean environment,
and the whole process tree killed on timeout or cancellation.

The developer's repository is never the sandbox's workspace. An executor
refuses to run until it is bound to a workspace (`in_workspace`).

Two kinds of backend:

* **host** (bwrap on Linux, seatbelt on macOS) runs the project's own
  interpreter, so its installed dependencies are available. The interpreter's
  prefix (a virtualenv, for example) and dependency directories such as
  `node_modules` are readable, never writable.
* **container** (podman/docker) runs a pinned image with only the standard
  library: stronger isolation, but third-party dependencies are missing.

There is no unsandboxed fallback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import sandbox
from .isolate import (IsolationError, VenvLayout, Workspace, editable_redirects, run_dir, site_dirs, static_venv,
                      workspaces_root)

HOST_BACKENDS = ("bwrap", "seatbelt")
RUN_HOME = ".repo-ai/run/home"
CONTAINER_BACKENDS = ("podman", "docker")
_APPLE_DEVELOPER_LINK = Path("/private/var/db/xcode_select_link")
_APPLE_CLT_ROOT = Path("/Library/Developer/CommandLineTools")


@dataclass(slots=True)
class Executor:
    backend: sandbox.Backend
    root: Path                      # the disposable workspace on the host (once bound)
    python: str = "python3"         # interpreter inside the sandbox
    node: str = "node"
    extra_reads: list[str] = field(default_factory=list)
    timeout_s: float = 600.0
    site_dirs: list[str] = field(default_factory=list)       # the project interpreter's site-packages
    links: dict[str, str] = field(default_factory=dict)      # workspace rel -> read-only source dir
    pythonpath: list[str] = field(default_factory=list)      # editable-install redirects (inside paths)
    workspace: Workspace | None = None
    # the checkout the interpreter's editable installs point at, when it is not the workspace's own source (a mission
    # workspace is materialized from a workspace, but the venv's `.pth` names the checkout)
    editable_source: Path | None = None

    def in_workspace(self, ws: Workspace) -> Executor:
        """This executor, bound to a disposable workspace."""
        bound = Executor(self.backend, ws.path, self.python, self.node, [*self.extra_reads], self.timeout_s,
                         [*self.site_dirs], dict(ws.readonly), [], ws, self.editable_source)
        if bound.is_container:
            ws.expose_dependencies("mountpoint")
        else:
            ws.expose_dependencies("link")
            bound.extra_reads += [d for d in ws.readonly.values() if d not in bound.extra_reads]
            bound.pythonpath = [bound.inside_root if rel in {"", "."} else f"{bound.inside_root}/{rel}"
                                for rel in editable_redirects(self.site_dirs, self.editable_source or ws.source)
                                if (ws.path / rel).is_dir()]
        return bound

    @property
    def inside_root(self) -> str:
        return "/work" if self.is_container else str(self.root.resolve())

    @property
    def is_container(self) -> bool:
        return isinstance(self.backend, sandbox.ContainerBackend)

    def argv(self, argv: list[str]) -> list[str]:
        """Substitute the runner's `python`/`node` tokens with this sandbox's."""
        head = {"python": self.python, "node": self.node}.get(argv[0], argv[0]) if argv else ""
        return [head, *argv[1:]] if argv else []

    def fresh(self) -> Executor:
        """An executor on a new pristine clone of this executor's workspace."""
        if self.workspace is None:
            raise IsolationError("a clone needs an executor bound to a disposable workspace")
        return self.in_workspace(self.workspace.clone("par"))

    def _env(self, env: dict[str, str] | None) -> dict[str, str]:
        out = dict(env or {})
        if self.pythonpath:
            out["PYTHONPATH"] = os.pathsep.join([p for p in [out.get("PYTHONPATH", "")] if p] + self.pythonpath)
        return out

    def run(self, argv: list[str], *, cwd: str = "", env: dict[str, str] | None = None,
            timeout_s: float | None = None, toolchain: str = "python", watch=None) -> sandbox.Result:
        if self.workspace is None or self.root.resolve() != self.workspace.path.resolve() \
                or workspaces_root() not in self.root.resolve().parents:
            raise IsolationError("refusing to run tests outside a disposable workspace")
        cmd = self.argv(argv)
        if cwd:  # the runner's directory, entered without a shell string
            cmd = ["sh", "-c", 'cd "$1" && shift && exec "$@"', "sh", cwd, *cmd]
        limits = sandbox.Limits(timeout_s=timeout_s or self.timeout_s, memory_mb=4096, pids=1024, watch=watch)
        if self.is_container:
            mounts = tuple((src, f"/work/{rel}") for rel, src in sorted(self.links.items()))
            return self.backend.run(cmd, self.root, limits=limits, toolchain=toolchain,  # type: ignore[call-arg]
                                    env=self._env(env), ro_mounts=mounts)
        # HOME and TMPDIR inside the disposable workspace
        run_dir(self.root, RUN_HOME)
        inside_home = f"{self.inside_root}/{RUN_HOME}"
        res = self.backend.run(cmd, self.root, limits=limits, toolchain=toolchain,  # type: ignore[call-arg]
                               env={"HOME": inside_home, "TMPDIR": inside_home, **self._env(env)},
                               extra_reads=tuple(self.extra_reads), allowed_links=self.links)
        _raise_if_not_started(res)
        return res


def _raise_if_not_started(res: sandbox.Result) -> None:
    """The sandbox could not start the command at all (a missing runner, a
    denied interpreter): an environment problem, never a test failure."""
    text = res.stderr.lstrip()[:400]
    # bubblewrap reports its own setup failures (namespaces, /proc, /dev, uid map) as "bwrap: ..."
    # with exit 1 before anything runs; a container or an AppArmor userns policy causes them.
    bwrap_setup = (res.backend == "bwrap" and res.exit_code == 1 and text.startswith("bwrap: ")
                   and not res.stdout.strip())
    if (res.exit_code == 71 and text.startswith("sandbox-exec:")) or bwrap_setup \
            or (res.backend == "bwrap" and text.startswith("bwrap: execvp")):
        raise sandbox.SandboxUnavailable("the sandbox could not start the test command ("
                                         + text.splitlines()[0][:200] + "); nothing was verified")


def release(executors: list[Executor]) -> None:
    """Delete the clones `fresh` made."""
    for ex in executors:
        if ex.workspace is not None:
            ex.workspace.cleanup()


@dataclass(slots=True)
class Interpreter:
    python: str
    reads: list[str]                    # directories the sandbox must be able to read
    site_dirs: list[str] | None = None  # None: ask the interpreter (`isolate.site_dirs`)


def interpreter(root: Path, *, probe: bool = True) -> Interpreter | None:
    """The interpreter the project's tests should use: an active virtualenv,
    a repository-local `.venv`/`venv`, or the first `python3` on PATH. One
    inside the repository is never executed on the host, whether git tracks
    it (`_committed`: never chosen) or not (an ignored `.venv` can be planted
    by a patch or an archive as easily as made by the developer): its
    prefixes and site-packages are read from its `pyvenv.cfg` and layout
    (`isolate.static_venv`), and it is refused when those are unusable."""
    candidates = []
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidates.append(Path(venv) / "bin" / "python")
    candidates += [root / ".venv" / "bin" / "python", root / "venv" / "bin" / "python"]
    found = shutil.which("python3")
    if found:
        candidates.append(Path(found))
    for cand in candidates:
        if not cand.exists() or _committed(root, cand):
            continue
        if not _inside(root, cand):
            real = _real_executable(str(cand))
            if real is None:  # a version-manager shim whose interpreter cannot be read from its files
                continue
            if real != str(cand) and _committed(root, Path(real)):
                continue  # a system launcher/manager must not redirect into tracked repository code
            if not _inside(root, Path(real)):
                # Freshness readers need the same selection, without executing
                # even an external interpreter. Prefix probing is for execution only.
                return Interpreter(real, _prefixes(real) if probe else [])
            cand = Path(real)  # a launcher outside that leads back in
        layout = static_venv(str(cand))
        if layout is not None:
            return Interpreter(str(cand), _static_prefixes(str(cand), layout), layout.site_dirs)
    return None


def project_python(root: Path) -> tuple[str, list[str]]:
    """The interpreter (`interpreter`) and the directories it needs to read."""
    found = interpreter(root)
    return (found.python, found.reads) if found else ("python3", [])


def _inside(root: Path, python: Path) -> bool:
    """`python`, as given, through its directory's links or fully resolved,
    lies inside the repository. Directories are compared by identity, so
    another spelling of the root (case on macOS, a linked parent) is still
    the root. Fails closed."""
    try:
        top = os.stat(root)
    except OSError:
        return True
    for path in dict.fromkeys((python.absolute(), python.parent.resolve() / python.name, python.resolve())):
        for parent in path.parents:
            try:
                if os.path.samestat(os.stat(parent), top):
                    return True
            except OSError:
                continue
    return False


def _committed(root: Path, python: Path) -> bool:
    """The interpreter belongs to a virtualenv that git tracks or has staged:
    that is the repository's own code (any clone can ship a `.venv/bin/python`
    script), so it is never executed on the host, where nothing is sandboxed
    yet, and never chosen. Matched case-insensitively (macOS: `.VENV` is
    `.venv`). An untracked virtualenv is taken to be the developer's (a venv
    planted by a patch or a `git reset` cannot be told apart), so it is
    chosen but, like anything inside the repository, never executed on the
    host (`interpreter`; threat model T24). Fails closed: when git cannot
    say, the interpreter is not used."""
    top = root.resolve()
    for path in dict.fromkeys((python.absolute(), python.parent.resolve() / python.name, python.resolve())):
        try:
            rel = path.relative_to(top)
        except ValueError:
            continue
        venv = rel.parent.parent.as_posix() if rel.parent.name.lower() in {"bin", "scripts"} else rel.parent.as_posix()
        spec = ":(icase,literal)" + (venv if venv not in {"", "."} else rel.as_posix())  # macOS: `.VENV` is `.venv`
        try:
            out = subprocess.run(["git", "ls-files", "-z", "--", spec], cwd=top, capture_output=True, timeout=60,
                                 check=False, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return True
        if out.returncode != 0 or out.stdout.strip(b"\0"):
            return True
    return False


def _real_executable(python: str) -> str | None:
    """The interpreter itself, not a launcher: a pyenv/asdf shim is a shell
    script that costs about half a second per test process. A virtualenv's
    `bin/python` is kept as is (it is what activates the environment). None
    for a shim whose interpreter pyenv's files do not name: a shim is never
    run on the host, since the version file it obeys is the repository's
    (`.python-version`, asdf's `.tool-versions`) and can name a program
    inside it."""
    if sys.platform == "darwin" and python == "/usr/bin/python3":
        return _apple_python_target()
    if "shims" not in Path(python).resolve().parts:
        return python
    direct = sandbox.pyenv_target(Path(python))
    return str(direct) if direct is not None else None


def _apple_python_target() -> str | None:
    """Resolve Apple's launcher without executing it or xcode-select.

    The launcher invokes xcrun, which needs access to the Xcode developer
    directory. Use the selected interpreter itself instead of broadening the
    sandbox to the Xcode bundle. Keep this uncached: freshness reads must see
    selection changes too. Invalid explicit selections never fall back.
    """
    try:
        selected = os.environ.get("DEVELOPER_DIR")
        if selected:
            developer = Path(selected)
            if not developer.is_absolute():
                return None
            if developer.suffix == ".app":
                developer = developer / "Contents" / "Developer"
        elif _APPLE_DEVELOPER_LINK.is_symlink() or _APPLE_DEVELOPER_LINK.exists():
            developer = _APPLE_DEVELOPER_LINK.resolve(strict=True)
        else:
            developer = _APPLE_CLT_ROOT
        target = (developer / "usr" / "bin" / "python3").resolve(strict=True)
        if target == Path("/usr/bin/python3").resolve() or not target.is_file():
            return None
        return str(target)
    except (OSError, RuntimeError):
        return None


def _prefixes(python: str) -> list[str]:
    try:  # -I -S: no .pth file, site hook or PYTHON* variable runs on the host
        out = subprocess.run([python, "-I", "-S", "-c", "import sys;print(sys.prefix);print(sys.base_prefix)"],
                             capture_output=True, text=True, timeout=20, check=False,
                             stdin=subprocess.DEVNULL).stdout.split()
    except (OSError, subprocess.SubprocessError):
        out = []
    dirs = {str(Path(p).resolve()) for p in out if p}
    dirs.add(str(Path(python).resolve().parent.parent))
    # the interpreter is executed by the path we were given: when that path is a symlink farm
    # (GitHub's macOS toolcache -> /Library/Frameworks/Python.framework), the sandbox must be
    # able to read the farm too, not only the resolved framework
    dirs.add(str(Path(python).absolute().parent.parent))
    home = str(Path.home().resolve())
    # never open up the whole home directory, only the interpreter's own prefixes
    return sorted(d for d in dirs if d not in {"/", home})


def _static_prefixes(python: str, layout: VenvLayout) -> list[str]:
    """`_prefixes` without running the interpreter: the virtualenv, the base
    installation, and `home` itself (the path the virtualenv's interpreter
    is reached through, a symbolic link farm on some hosts). The paths the
    repository controls (`home`, where `bin/python` links to) are kept only
    when they are the virtualenv or the validated base installation, or lie
    inside one: a link must not open up another directory to the sandbox."""
    anchors = {Path(p).resolve() for p in (layout.prefix, layout.base_prefix)}
    dirs = {layout.prefix, str(Path(layout.prefix).resolve()), layout.base_prefix,
            str(Path(layout.base_prefix).resolve())}
    for extra in (layout.home, str(Path(python).resolve().parent.parent)):
        real = Path(extra).resolve()
        if any(real == a or a in real.parents for a in anchors):
            dirs.add(extra)
    home = str(Path.home().resolve())
    return sorted(d for d in dirs if d not in {"/", home})


def get_executor(root: Path, preference: str = "auto", language: str = "python",
                 timeout_s: float = 600.0, image: str = "", interpreter_root: Path | None = None) -> Executor:
    """Host sandboxes first (the project's own environment), then containers.
    `image`: a local container image with the project's dependencies (only
    with a container backend; never pulled). `interpreter_root`: the checkout
    whose virtualenv the tests use when `root` is a disposable workspace (a
    workspace never holds the project's `.venv`)."""
    if image and preference not in CONTAINER_BACKENDS:
        raise sandbox.SandboxUnavailable("--image needs --sandbox podman or --sandbox docker")
    order = (*HOST_BACKENDS, *CONTAINER_BACKENDS) if preference == "auto" else (preference,)
    reasons = []
    for name in order:
        try:
            backend = sandbox.get_backend(name, images={language: image} if image else None, toolchain=language)
        except sandbox.SandboxUnavailable as exc:
            if image and "not pulled" in str(exc):
                reasons.append(f"{name}: image {image} is not present locally (repo-ai never pulls it)")
            else:
                reasons.append(str(exc).split(" (")[0] if name == "auto" else f"{name}: unavailable")
            continue
        if isinstance(backend, sandbox.ContainerBackend):
            return Executor(backend, root, python="python", node="node", timeout_s=timeout_s)
        found = interpreter(interpreter_root or root) if language == "python" else Interpreter(sys.executable, [], [])
        python, reads = (found.python, found.reads) if found else ("python3", [])
        sites = [] if found is None else found.site_dirs if found.site_dirs is not None else site_dirs(python)
        found_node = shutil.which("node")
        node = found_node or "node"
        if language == "node":
            if not found_node:  # never derive a read directory from a bare name (it resolves against the cwd)
                raise sandbox.SandboxUnavailable("node is not on PATH, so the tests cannot run; nothing was run")
            reads = [str(Path(found_node).resolve().parent.parent)]
        if language == "python" and not Path(python).is_absolute():
            raise sandbox.SandboxUnavailable("no Python interpreter found for the tests; nothing was run")
        return Executor(backend, root, python=python, node=node, extra_reads=reads, timeout_s=timeout_s,
                        site_dirs=sites, editable_source=interpreter_root.resolve() if interpreter_root else None)
    raise sandbox.SandboxUnavailable("no sandbox backend available for running tests ("
                                     + "; ".join(reasons) + "); nothing was run")
