"""Coding Performance Research Lab (`repo-ai eval coding`).

Answers one question with controlled experiments: does repo-ai make Claude
Code better at *completing* programming tasks, compared with plain Claude
Code? (`evals.py` measures localization; this module measures task
outcomes.)

**Arms.** Built from independent feature flags, so any ablation is one
flag away:

==========  ================================================================
baseline    plain Claude Code: no repo-ai file, hook, rule or skill
core        index + hooks + CLAUDE.md block + curated skills (packets,
            impact) + approved project rules
full        core + generated skills + subagents + outcome recording +
            orchestration aids (skeptic) + approved third-party skills
==========  ================================================================

**Fairness.** For every arm:
- the same frozen snapshot, prompt, model, effort, turn and time limits;
- the same Claude settings file: OS sandbox for Bash, no network, reads
  of the home directory and the task suite denied, identical permission
  rules;
- the same dedicated, audited Claude config directory, so personal
  `~/.claude` skills, hooks and memory cannot leak in;
- `--setting-sources project,local`.

Arm order is randomised per task by seed. Each run gets a fresh disposable
workspace. Each run's `system/init` event is checked against what that arm
should have loaded; a mismatch marks the run `isolation_violation` and
excludes it.

**Hidden tests.** They stay in the suite until the agent has exited. The
suite is outside every readable path: the Bash sandbox denies it and
permission rules deny the file tools. Grading (the agent's code plus the
hidden tests) runs inside the strongest available sandbox backend.

**Money.** Live runs need an explicit `--max-cost-usd`. Claude Code checks
`--max-budget-usd` between API calls, so a run can end one call past its
cap: each run is therefore reserved R = cap + margin (default 1.25 x cap).
A task's arms start only if every remaining arm's reservation still fits,
so the money charged never exceeds the budget while every run costs at most
R; a run that costs more stops the experiment. Reported costs are charged as
reported, and runs with no reported cost (or a crash) are charged R. A budget
of planned runs x R is guaranteed to complete; planned runs x cap is not.
Results are appended as they finish, so an interrupted experiment resumes
where it stopped.
"""

from __future__ import annotations

import json
import math

import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import gitbin
from . import __version__, evals, integrity
from .evals import Base, Task

FEATURES = ("hooks", "packet", "rules", "skills", "agents", "outcomes", "orchestration",
            "thirdparty")
ARM_FEATURES: dict[str, frozenset[str]] = {
    "baseline": frozenset(),
    "core": frozenset({"hooks", "packet", "rules"}),
    "full": frozenset(FEATURES),
}
# Feature attribution: each ablation removes exactly these features from Full.
ABLATIONS: dict[str, tuple[frozenset[str], str]] = {
    "packets": (frozenset({"packet"}), "context packets, the CLAUDE.md block and curated skills"),
    "rules": (frozenset({"rules"}), "adaptive memory: learned project rules"),
    "skills": (frozenset({"skills"}), "generated skills"),
    "thirdparty": (frozenset({"thirdparty"}), "approved external skills"),
    "outcomes": (frozenset({"outcomes"}), "outcome-aware retrieval (episode recording and the prior)"),
    "subagents": (frozenset({"agents", "orchestration"}), "subagents and orchestration (skeptic)"),
}
RESULTS_ENV = "REPO_AI_LAB_HOME"


def lab_home() -> Path:
    from .registry import registry_home
    env = os.environ.get(RESULTS_ENV)
    return Path(env) if env else registry_home() / "lab"


def eval_config_dir() -> Path:
    env = os.environ.get("REPO_AI_EVAL_CLAUDE_CONFIG")
    if env:
        return Path(env)
    from .registry import registry_home
    return registry_home() / "claude-eval"


# --------------------------------------------------------------------------
# arms
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Arm:
    name: str
    features: frozenset[str]
    thirdparty_only: tuple[str, ...] | None = None  # tournaments: one candidate per arm

    @property
    def uses_repo_ai(self) -> bool:
        return bool(self.features)

    def config_toml(self) -> str:
        f = self.features
        lines = [
            "# written by repo-ai eval coding for this arm",
            'agents = ["claude"]',
            f"write_claude_hooks = {str('hooks' in f).lower()}",
            f"write_claude_md = {str('packet' in f).lower()}",
            f"write_claude_skills = {str('packet' in f or 'skills' in f).lower()}",
            f'skills_mode = "{"auto" if "skills" in f else ("curated" if "packet" in f else "off")}"',
            f"write_claude_rules = {str('rules' in f).lower()}",
            f'learning_policy = "{"safe-auto" if "rules" in f else "off"}"',
            f"write_claude_agents = {str('agents' in f).lower()}",
            f'learning_signals = "{"outcomes" if "outcomes" in f else "off"}"',
            f"skeptic_reviewer = {str('orchestration' in f).lower()}",
            f'orchestration = "{"suggest" if "orchestration" in f else "off"}"',
            "flight_recorder = true",
        ]
        return "\n".join(lines) + "\n"


def make_arms(names: list[str], ablate: str | None = None) -> list[Arm]:
    arms = []
    expanded: list[str] = []
    for name in names:  # `ablations` = Full plus every named ablation
        expanded += ["full", *[f"full-{a}" for a in ABLATIONS]] if name == "ablations" else [name]
    for name in dict.fromkeys(expanded):
        if name.startswith("full-") and name[5:] in ABLATIONS:  # e.g. full-subagents
            arms.append(Arm(name, ARM_FEATURES["full"] - ABLATIONS[name[5:]][0]))
        elif name.startswith("full-") and name[5:] in FEATURES:  # e.g. full-hooks (one feature)
            arms.append(Arm(name, ARM_FEATURES["full"] - {name[5:]}))
        elif name in ARM_FEATURES:
            arms.append(Arm(name, ARM_FEATURES[name]))
        else:
            raise SystemExit(f"error: unknown arm {name!r} (baseline, core, full, ablations, "
                             f"full-<{'|'.join(ABLATIONS)}>, full-<feature>)")
    if ablate:
        removed = ABLATIONS[ablate][0] if ablate in ABLATIONS else (
            frozenset({ablate}) if ablate in FEATURES else None)
        if removed is None:
            raise SystemExit(f"error: unknown feature {ablate!r} ({', '.join([*ABLATIONS, *FEATURES])})")
        arms = [Arm("full", ARM_FEATURES["full"]), Arm(f"full-{ablate}", ARM_FEATURES["full"] - removed)]
    return arms


# --------------------------------------------------------------------------
# isolation
# --------------------------------------------------------------------------
def audit_config_dir(path: Path) -> list[str]:
    """Problems that would contaminate experiments from the eval config dir."""
    problems = []
    if not path.is_dir():
        return [f"{path} does not exist; run: CLAUDE_CONFIG_DIR={path} claude  (then /login, then /exit)"]
    for sub in ("skills", "agents", "commands", "output-styles"):
        d = path / sub
        if d.is_dir() and any(d.rglob("*.md")):
            problems.append(f"{path}/{sub} is not empty: personal customisations would leak into every arm")
    # Claude Code fetches the official marketplace *catalog* on first login; that
    # loads nothing. Installed plugins (or their cached code) would load.
    try:
        installed = json.loads((path / "plugins" / "installed_plugins.json").read_text("utf-8"))
    except (OSError, ValueError):
        installed = {}
    cache = path / "plugins" / "cache"
    if (installed.get("plugins") if isinstance(installed, dict) else None) or \
            (cache.is_dir() and any(cache.iterdir())):
        problems.append(f"{path}/plugins has installed plugins: they would load into every arm")
    for name in ("CLAUDE.md",):
        if (path / name).exists():
            problems.append(f"{path}/{name} exists (user memory would load in every arm)")
    settings = path / "settings.json"
    if settings.is_file():
        try:
            data = json.loads(settings.read_text("utf-8"))
        except ValueError:
            data = {}
        for key in ("hooks", "enabledPlugins", "mcpServers", "permissions"):
            if data.get(key):
                problems.append(f"{settings} sets `{key}`; remove it so arms stay identical")
    return problems


def toolchain_read_dirs() -> list[str]:
    from .sandbox import _toolchain_dirs
    dirs: set[str] = set()
    for tc in ("python", "node", "java"):
        dirs.update(_toolchain_dirs(tc))
    return sorted(dirs)


def carve_out(allowed: list[str], denied: list[Path]) -> list[str]:
    """`allowRead` re-opens paths inside `denyRead`, so an allowed directory
    that contains a denied path (repo-ai installed from a wheel ships the
    suite inside its own environment, which the agent must be able to read to
    run `repo-ai`) is replaced by everything beside the path down to it: the
    denied path and its ancestors are never allowed."""
    out: list[str] = []
    for a in allowed:
        base = Path(a).resolve()
        inside = [d.resolve() for d in denied if d.resolve() != base and d.resolve().is_relative_to(base)]
        if any(d.resolve() == base or base.is_relative_to(d.resolve()) for d in denied):
            continue  # an allowed directory inside a denied one: drop it
        if not inside:
            out.append(str(base))
            continue
        frontier = [base]
        while frontier:
            cur = frontier.pop()
            try:
                children = sorted(cur.iterdir())
            except OSError:
                continue
            for child in children:
                c = child.resolve() if not child.is_symlink() else child
                if any(c == d for d in inside):
                    continue  # the denied path itself
                if any(d.is_relative_to(c) for d in inside):
                    frontier.append(c)  # an ancestor of a denied path: descend, never allow
                else:
                    out.append(str(child))
    return sorted(dict.fromkeys(out))


def arm_settings(workspace_root: Path, suite: Path, extra_denied: list[Path]) -> dict[str, Any]:
    """One settings file for every arm. The suite (hidden tests, reference
    solutions) and the home directory are unreadable to Bash (OS sandbox)
    and to the file tools (permission rules)."""
    home = str(Path.home().resolve())
    denied = [home, str(suite.resolve()), *[str(p.resolve()) for p in extra_denied]]
    allow_read = [str(workspace_root.resolve()),
                  *carve_out(toolchain_read_dirs(), [Path(d) for d in denied[1:]])]
    return {
        "sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                    "filesystem": {"denyRead": denied, "allowRead": allow_read,
                                   "allowWrite": [str(workspace_root.resolve())]},
                    "network": {"allowedDomains": []}},
        "permissions": {"deny": [f"Read(/{d}/**)" for d in denied]
                        + ["WebFetch", "WebSearch"]},
        "autoMemoryEnabled": False,
        "includeCoAuthoredBy": False,
    }


def suite_denied(suite: Path) -> list[Path]:
    """Denied to every run beside the suite itself: the lab home (hidden tests
    at grading, kept workspaces, the canary) and a repository-kept suite's
    authoring notes (the fixes)."""
    return [lab_home(), *[p for p in (suite.parent / "authoring",) if p.is_dir()]]


def preflight_settings(settings: dict[str, Any], claude_cmd: list[str],
                       config_dir: Path | None) -> list[str]:
    """Claude Code silently ignores invalid settings in `-p` mode, which
    would silently drop the sandbox. `claude doctor` (no model call)
    validates project settings: refuse to run if it reports any problem."""
    probe = Path(tempfile.mkdtemp(prefix="repo-ai-preflight-"))
    try:
        (probe / ".claude").mkdir()
        (probe / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        subprocess.run([gitbin.git(), "init", "-q"], cwd=probe, check=False, timeout=30)
        env = {k: v for k, v in os.environ.items() if not k.startswith("REPO_AI_")}
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        try:
            proc = subprocess.run([*claude_cmd, "doctor"], cwd=probe, capture_output=True,
                                  text=True, timeout=90, check=False, env=env,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return [f"could not run `claude doctor` to validate settings: {exc}"]
        text = proc.stdout + proc.stderr
        if "Invalid settings" in text:
            tail = text[text.index("Invalid settings"):].splitlines()[1:8]
            return ["Claude Code rejects the experiment settings: " + "; ".join(t.strip() for t in tail)]
        if proc.returncode != 0:
            return [f"`claude doctor` exited {proc.returncode}"]
        return []
    finally:
        shutil.rmtree(probe, ignore_errors=True)


# Plugins compiled into Claude Code itself (registered for every session, e.g.
# cc-plugin-agents-md in 2.1.30x): part of "plain Claude Code", identical in
# every arm. Anything else (marketplace or user plugins) is contamination.
BUILTIN_PLUGIN_PREFIX = "cc-plugin-"


def plugin_names(init: dict[str, Any]) -> list[str]:
    return sorted(str(p.get("name", p)) if isinstance(p, dict) else str(p) for p in init.get("plugins") or [])


def check_isolation(arm: Arm, init: dict[str, Any], hook_events: int) -> list[str]:
    """What the run actually loaded must match what the arm should have."""
    skills = [str(s) for s in init.get("skills") or []] + \
        [str(s) for s in init.get("slash_commands") or []]
    agents = [str(a.get("name", a)) if isinstance(a, dict) else str(a) for a in init.get("agents") or []]
    problems = []
    has_repo_ai = any(s.lstrip("/").startswith("repo-") for s in skills)
    if not init:
        problems.append("no system/init event: cannot verify what loaded")
        return problems
    if not arm.uses_repo_ai:
        if has_repo_ai:
            problems.append("baseline loaded repo-ai skills")
        if any(a.startswith("repo-") for a in agents):
            problems.append("baseline loaded repo-ai subagents")
        if hook_events:
            problems.append(f"baseline ran {hook_events} hook event(s)")
    else:
        if "packet" in arm.features and not has_repo_ai:
            problems.append(f"{arm.name} did not load repo-ai skills")
        if "agents" in arm.features and not any(a.startswith("repo-") for a in agents):
            problems.append(f"{arm.name} did not load repo-ai subagents")
        if "hooks" in arm.features and hook_events == 0:
            problems.append(f"{arm.name} ran no hooks")
        if "agents" not in arm.features and any(a.startswith("repo-") for a in agents):
            problems.append(f"{arm.name} loaded subagents it should not have")
    foreign = [n for n in plugin_names(init) if not n.startswith(BUILTIN_PLUGIN_PREFIX)]
    if foreign:
        problems.append(f"non-built-in plugins loaded (must be none): {', '.join(foreign)[:120]}")
    mcp = init.get("mcp_servers") or []
    if mcp:
        names = [str(m.get("name", m)) if isinstance(m, dict) else str(m) for m in mcp]
        problems.append(f"MCP servers loaded (must be none): {', '.join(names)[:120]}")
    return problems


# --------------------------------------------------------------------------
# options and runner
# --------------------------------------------------------------------------
@dataclass(slots=True)
class LabOptions:
    arms: list[Arm]
    max_cost_usd: float = 0.0
    max_cost_per_run: float = 0.5
    max_turns: int = 30
    timeout_s: int = 900
    model: str | None = None
    effort: str | None = None
    seed: int = 0
    repeat: int = 1
    claude_cmd: list[str] = field(default_factory=lambda: ["claude"])
    config_dir: Path | None = None
    results_dir: Path | None = None
    keep_workspaces: bool = False
    used_workspaces: list[Path] = field(default_factory=list)  # denied to every later run
    blind: bool = False  # pre-registered runs: no pass/fail is shown until the experiment ends
    # Money held back per pending run: the cap plus the largest single API call it
    # may still make after crossing the cap (Claude checks the cap between calls).
    reserve_per_run: float | None = None  # default RESERVATION_FACTOR x max_cost_per_run
    max_invalid_rate: float = 0.2  # stopping rule: stop when more attempts than this are invalid
    dry_run: bool = False
    grading_backend: str = "auto"
    fake: bool = False  # deterministic fake client: no budget needed, results flagged FAKE
    task_order: str = "suite"  # recorded: "suite" (as selected) or "interleave" (interleave_by_base)


def claude_argv(opts: LabOptions, prompt: str, budget: float, settings_file: Path) -> list[str]:
    argv = [*opts.claude_cmd, "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--include-hook-events", "--max-turns", str(opts.max_turns),
            "--max-budget-usd", f"{budget:.2f}", "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--setting-sources", "project,local",
            "--settings", str(settings_file), "--no-session-persistence",
            "--strict-mcp-config",  # no MCP servers at all (not even claude.ai connectors)
            "--allowedTools", *evals.ALLOWED_TOOLS, "--disallowedTools", *evals.DISALLOWED_TOOLS]
    if opts.model:
        argv += ["--model", opts.model]
    if opts.effort:
        argv += ["--effort", opts.effort]
    return argv


def _stream(argv: list[str], cwd: Path, env: dict[str, str], timeout: float,
            cancel: threading.Event) -> tuple[list[tuple[float, str]], int, bool]:
    """Run, collecting (seconds-since-start, line). Kills the process group
    on timeout or cancellation."""
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            encoding="utf-8", errors="replace", start_new_session=True)
    lines: list[tuple[float, str]] = []
    timed_out = False

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append((time.monotonic() - started, line.rstrip("\n")))
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(0.5)
        if time.monotonic() - started > timeout or cancel.is_set():
            timed_out = not cancel.is_set()
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                thread.join(5)
                if not thread.is_alive():
                    break
            break
    try:
        code = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = proc.wait()
    try:  # whatever the agent started in its session does not outlive the run
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    return lines, code, timed_out


def _init_event(lines: list[tuple[float, str]]) -> tuple[dict[str, Any], int]:
    init: dict[str, Any] = {}
    hooks = 0
    for _, line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "system":
            if ev.get("subtype") == "init" and not init:
                init = ev
            elif str(ev.get("subtype", "")).startswith("hook_"):
                hooks += 1
    return init, hooks


def _first_edit_s(lines: list[tuple[float, str]]) -> float | None:
    for t, line in lines:
        if '"tool_use"' in line and any(f'"name":"{n}"' in line.replace(" ", "") for n in evals.EDIT_TOOLS):
            return round(t, 1)
    return None


# Untracked outputs of running Python code and its test tools. Only these, and
# only when untracked: a modified tracked file, a stray module-level .pyc (which
# Python can import without its source) or anything else is still an edit.
_ARTIFACT_DIRS = {".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}
_BYTECODE_NAME = re.compile(r"^[^/]+\.(?:cpython|pypy)[\w.-]*\.pyc$")


def is_execution_artifact(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if any(p in _ARTIFACT_DIRS for p in parts[:-1]):
        return True
    if len(parts) >= 2 and parts[-2] == "__pycache__":
        return bool(_BYTECODE_NAME.match(parts[-1]))
    return parts[-1] == ".coverage" or parts[-1].startswith(".coverage.")


def _no_bytecode(directory: str, names: list[str]) -> set[str]:
    """copytree filter: drop __pycache__ directories (interpreter caches; Python
    rebuilds them from source). Module-level .pyc files are kept: they are
    agent edits, and Python prefers a module's source over them anyway."""
    return {n for n in names if n == "__pycache__"}


def _setup_workspace(task: Task, suite: Path, ws: Path, arm: Arm) -> str:
    evals.materialize(task, suite, ws)
    if not arm.uses_repo_ai:
        return ""
    (ws / ".repo-ai").mkdir(exist_ok=True)
    (ws / ".repo-ai" / "config.toml").write_text(arm.config_toml(), encoding="utf-8")
    started = time.monotonic()
    init = evals._cli(["init", "--agent", "claude", "-q"], ws)
    if init.returncode != 0:
        raise RuntimeError(f"repo-ai init failed: {init.stderr.strip()[-300:]}")
    if "thirdparty" in arm.features:
        _install_portfolio(ws, arm.thirdparty_only)
    evals._git(ws, "add", "-A")
    evals._git(ws, "commit", "-qm", f"repo-ai ({arm.name})")
    return f"{time.monotonic() - started:.2f}"


def _repo_ai_shim(root: Path) -> Path:
    shim = root / "repo-ai-bin"
    target = Path(sys.executable).parent / ("repo-ai.exe" if os.name == "nt" else "repo-ai")
    if not (shim / target.name).exists() and target.exists():
        shim.mkdir(exist_ok=True)
        try:
            (shim / target.name).symlink_to(target)
        except OSError:
            shutil.copy2(target, shim / target.name)
    return shim


def _install_portfolio(ws: Path, only: tuple[str, ...] | None = None) -> None:
    """Approved third-party skills from the user's portfolio (skills_net)."""
    from .portfolio import install_locked_into
    install_locked_into(ws, only=only)


def grade(task: Task, base: Base, suite: Path, ws: Path, backend_pref: str) -> dict[str, Any]:
    """Visible tests (regressions) then hidden tests, inside the sandbox."""
    from . import sandbox
    toolchain = _toolchain(base)
    out: dict[str, Any] = {"backend": None}
    try:
        backend = _grading_backend(backend_pref, toolchain, base)
    except sandbox.SandboxUnavailable as exc:
        return {"backend": None, "error": f"no sandbox for grading: {exc}", "success": False,
                "visible_ok": False}
    out["backend"] = backend.name
    if task.visible_after_hidden:  # updated upstream tests in place; see evals.regression_commands
        try:
            evals.install_hidden(task, ws)
        except evals.SuiteError as exc:
            out.update(success=False, error=str(exc))
            return out
    visible = _run_cmds(backend, evals.regression_commands(task, base), ws, toolchain,
                        task.timeout_s * 2)
    out["visible_ok"] = visible.ok
    try:
        evals.install_hidden(task, ws)
    except evals.SuiteError as exc:
        out.update(success=False, error=str(exc))
        return out
    hidden = _run_cmds(backend, task.commands, ws, toolchain, task.timeout_s * 2)
    out["success"] = hidden.ok
    out["hidden_pass_fraction"] = pass_fraction(hidden.stdout + "\n" + hidden.stderr, hidden.ok)
    out["grading_s"] = round(hidden.duration_s + visible.duration_s, 2)
    return out


def grading_sandbox_problems(tasks: list[Task], bases: dict[str, Base], pref: str) -> list[str]:
    from . import sandbox
    problems = []
    for name in sorted({t.base for t in tasks}):
        base = bases[name]
        if evals.missing_toolchain(base):
            continue  # those tasks are skipped anyway
        try:
            _grading_backend(pref, _toolchain(base), base)
        except sandbox.SandboxUnavailable as exc:
            problems.append(f"{name} ({_toolchain(base)}): {exc}")
    return problems


def _toolchain(base: Base) -> str:
    if "javac" in base.toolchain or "java" in base.toolchain:
        return "java"
    if "node" in base.toolchain:
        return "node"
    return "python"


def _grading_backend(pref: str, toolchain: str, base: Base):
    from . import sandbox
    backend = sandbox.get_backend(pref, toolchain=toolchain)
    if isinstance(backend, sandbox.ContainerBackend):
        needed = {"make"} if any("make" in " ".join(c) for c in base.visible_tests) else set()
        if needed and not _image_has(backend, toolchain, needed):
            host = [n for n in ("bwrap", "seatbelt") if sandbox.BACKENDS[n]().available()[0]]
            if host:
                return sandbox.get_backend(host[0])
    return backend


_IMAGE_TOOLS: dict[tuple[str, str], bool] = {}


def _image_has(backend, toolchain: str, tools: set[str]) -> bool:
    from . import sandbox
    key = (toolchain, ",".join(sorted(tools)))
    if key not in _IMAGE_TOOLS:
        probe = Path(tempfile.mkdtemp(prefix="repo-ai-probe-"))
        try:
            res = backend.run(["sh", "-c", " && ".join(f"command -v {t}" for t in sorted(tools))],
                              probe, limits=sandbox.Limits(timeout_s=60), toolchain=toolchain)
            _IMAGE_TOOLS[key] = res.ok
        finally:
            shutil.rmtree(probe, ignore_errors=True)
    return _IMAGE_TOOLS[key]


def _run_cmds(backend, commands: list[list[str]], ws: Path, toolchain: str, timeout: float):
    """All of a task's commands in one sandboxed shell (they share {out})."""
    from . import sandbox
    container = isinstance(backend, sandbox.ContainerBackend)
    out_dir = ws / ".grade-out"
    out_dir.mkdir(exist_ok=True)
    steps = []
    for argv in commands:
        expanded = []
        for token in argv:
            if token == "{python}":
                expanded.append("python3")
            elif token == "{node}":
                expanded.append("node")
            elif token == "{out}":
                expanded.append("/work/.grade-out" if container else str(out_dir))
            elif token.startswith("{glob:"):
                expanded.extend(sorted(p.relative_to(ws).as_posix()
                                       for p in ws.glob(token[6:-1]) if p.is_file()))
            else:
                expanded.append(token)
        steps.append(shlex.join(expanded))
    script = "set -e\n" + "\n".join(steps)
    return backend.run(["sh", "-c", script], ws, limits=sandbox.Limits(timeout_s=timeout),
                       toolchain=toolchain)


def pass_fraction(output: str, ok: bool) -> float:
    """Partial credit from common runners' summaries; 1.0/0.0 otherwise."""
    import re
    if ok:
        return 1.0
    m = re.search(r"Ran (\d+) tests?.*?FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?", output, re.S)
    if m:
        total = int(m.group(1))
        bad = int(m.group(2) or 0) + int(m.group(3) or 0)
        return round(max(total - bad, 0) / total, 3) if total else 0.0
    m_pass, m_fail = re.search(r"# pass (\d+)", output), re.search(r"# fail (\d+)", output)
    if m_pass and m_fail:
        p, f = int(m_pass.group(1)), int(m_fail.group(1))
        return round(p / (p + f), 3) if p + f else 0.0
    passed = len(re.findall(r"(?m)^PASS\b", output))
    failed = len(re.findall(r"(?m)^FAIL\b", output))
    if passed + failed:
        return round(passed / (passed + failed), 3)
    return 0.0


# --------------------------------------------------------------------------
# one run
# --------------------------------------------------------------------------
def _workspace_changes(ws: Path, pristine_git: Path) -> tuple[list[str], list[str]]:
    """(changed tracked files, untracked files) in `ws`. Never with the workspace's own .git, which the agent could
    have written (a clean filter in its config runs on `git diff`): with the copy taken before the run, and with no
    fsmonitor or hook either."""
    quiet = ["--git-dir", str(pristine_git), "--work-tree", str(ws), "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=" + os.devnull]
    changed = subprocess.run([gitbin.git(), *quiet, "diff", "--name-only", "HEAD"], cwd=ws, capture_output=True,
                             text=True, check=False, timeout=60).stdout.split()
    untracked = subprocess.run([gitbin.git(), *quiet, "ls-files", "--others", "--exclude-standard"], cwd=ws,
                               capture_output=True, text=True, check=False, timeout=60).stdout.split()
    return changed, untracked


def run_one(task: Task, base: Base, suite: Path, arm: Arm, opts: LabOptions, root: Path,
            budget: float, cancel: threading.Event) -> dict[str, Any]:
    ws = root / f"{task.id}-{arm.name}-{uuid.uuid4().hex[:6]}"
    row: dict[str, Any] = {"task": task.id, "arm": arm.name, "features": sorted(arm.features),
                           "category": task.category, "language": task.language,
                           "difficulty": task.difficulty, "fake": opts.fake}
    pristine_git = root / f"git-{ws.name}"
    try:
        row["setup_s"] = float(_setup_workspace(task, suite, ws, arm) or 0)
        # the agent can write its workspace's .git (config filters, hooks, fsmonitor): the host's git reads a copy
        # taken before it ran, outside the workspace
        shutil.copytree(ws / ".git", pristine_git, symlinks=True)
        # outside the workspace: the agent may read and write only its own workspace
        settings_file = root / f"settings-{uuid.uuid4().hex[:6]}.json"
        # earlier runs' workspace paths are denied: a process left behind by one
        # arm can write only its own (finished) workspace, which no later arm may read
        settings_file.write_text(json.dumps(arm_settings(ws, suite, [*suite_denied(suite),
                                                                     *opts.used_workspaces]),
                                            indent=1))
        opts.used_workspaces.append(ws)
        argv = claude_argv(opts, task.prompt, budget, settings_file)
        # fake mode: an empty config directory, so even a real client has no login and cannot bill
        config_dir = Path(tempfile.mkdtemp(prefix="repo-ai-fake-config-", dir=root)) if opts.fake \
            else (opts.config_dir or eval_config_dir())
        env = evals.agent_env({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "REPO_AI_NO_BACKGROUND": "1",
                               "DISABLE_AUTOUPDATER": "1",  # one Claude Code version per experiment
                               "CLAUDE_CONFIG_DIR": str(config_dir)},
                              allow_api_key=not opts.fake)  # fake mode can never bill
        # hooks call `repo-ai` by name: put only the build under test first on PATH
        # (not its whole bin directory, which would also change the agent's python3)
        env["PATH"] = os.pathsep.join([str(_repo_ai_shim(root)), env.get("PATH", "")])
        # a decoy hidden-test tree with a fresh token, in the lab home every agent is denied
        canary, canary_root = integrity.plant_canary(lab_home(), task.id,
                                                     [Path(i["src"]).name for i in task.hidden])
        started = time.monotonic()
        try:
            lines, exit_code, timed_out = _stream(argv, ws, env, opts.timeout_s, cancel)
        finally:
            integrity.remove_canary(canary_root)
        row["wall_s"] = round(time.monotonic() - started, 1)
        row["exit"] = exit_code
        row["timed_out"] = timed_out
        row["cancelled"] = cancel.is_set()
        init, hook_events = _init_event(lines)
        row["claude_code_version"] = init.get("claude_code_version")
        row["model"] = init.get("model")
        row["isolation_problems"] = check_isolation(arm, init, hook_events)
        row["plugins_loaded"] = plugin_names(init)  # recorded so reports can show what every arm had
        row["mcp_servers_loaded"] = len(init.get("mcp_servers") or [])
        row["hook_events"] = hook_events
        metrics = evals.parse_stream([line for _, line in lines], ws, task.gold_files)
        row.update(metrics)
        row["tool_calls"] = sum(metrics["tool_uses"].values())
        row["first_edit_s"] = _first_edit_s(lines)
        row["repo_ai_context_tokens_est"] = evals._flight_tokens(ws) if arm.uses_repo_ai else 0
        changed, untracked = _workspace_changes(ws, pristine_git)
        # Running the code (tests, an import) leaves untracked bytecode and tool
        # caches: execution artifacts, not edits. Tracked files are always edits.
        artifacts = sorted(p for p in set(untracked) - set(changed) if is_execution_artifact(p))
        touched = sorted((set(changed) | set(untracked)) - set(artifacts))
        row["files_changed"] = touched
        row["execution_artifacts"] = len(artifacts)
        row["execution_artifact_sample"] = artifacts[:10]
        row["unnecessary_edits"] = sorted(set(touched) - set(task.gold_files)
                                          - {p for p in touched if "test" in p})
        # proof of access only; content similarity is a recorded diagnostic
        verdict = integrity.assess([line for _, line in lines],
                                   integrity.protected_paths(suite, task.dir, *suite_denied(suite)), canary,
                                   canary_root, evals.hidden_materials(task), ws, git_dir=pristine_git)
        row["contaminated"] = verdict["contaminated"]
        row["hidden_access_attempts"] = verdict["hidden_access_attempts"]
        row["hidden_content_match"] = verdict["hidden_content_match"]
        # Grade a fresh copy: a process the agent left behind can still touch `ws`,
        # never the copy (and never the hidden tests installed into it).
        # Under the lab home, which every agent is denied (hidden tests go here).
        graded = lab_home() / "grading" / f"{ws.name}-{uuid.uuid4().hex[:8]}"
        graded.parent.mkdir(parents=True, exist_ok=True)
        from .sandbox import check_workspace
        check_workspace(ws)
        # Graded from source only: bytecode an agent left (or planted with a header
        # matching the source's mtime and size) would otherwise be imported instead.
        shutil.copytree(ws, graded, symlinks=True, ignore=_no_bytecode)
        check_workspace(graded)  # the copy is what runs: check it, not only the original
        try:
            row.update(grade(task, base, suite, graded, opts.grading_backend))
        finally:
            shutil.rmtree(graded, ignore_errors=True)
        row["regression"] = not row.get("visible_ok", True)
        row["abandoned"] = not touched and not row.get("success")
    except Exception as exc:  # noqa: BLE001 - a broken run is a result, not a crash
        row.update(error=f"{type(exc).__name__}: {exc}", success=False)
    finally:
        shutil.rmtree(pristine_git, ignore_errors=True)
        if opts.keep_workspaces and ws.exists():
            # kept under the lab home, which every arm is denied: a later arm
            # can never read an earlier arm's solution
            kept = lab_home() / "kept-workspaces" / ws.name
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ws), str(kept))
            row["workspace"] = str(kept)
        else:
            shutil.rmtree(ws, ignore_errors=True)
    row["valid"] = not row.get("isolation_problems") and not row.get("contaminated") \
        and "error" not in row and not row.get("cancelled")
    return row


# --------------------------------------------------------------------------
# experiment
# --------------------------------------------------------------------------
def experiment_dir(exp_id: str) -> Path:
    return lab_home() / "experiments" / exp_id


def load_runs(exp_id_or_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(exp_id_or_path)
    if not path.exists():
        path = experiment_dir(exp_id_or_path)
    if path.is_dir():
        meta = json.loads((path / "experiment.json").read_text("utf-8"))
        raw = [json.loads(line) for line in (path / "runs.jsonl").read_text("utf-8").splitlines()
               if line.strip()] if (path / "runs.jsonl").exists() else []
        finished = {(r.get("task"), r.get("arm"), int(r.get("rep", 0))) for r in raw if not r.get("reservation")}
        runs = [r for r in raw if not r.get("reservation")]
        # a reservation with no result is an attempt that crashed or was killed: reported, never hidden
        runs += [{"task": r["task"], "arm": r["arm"], "rep": int(r.get("rep", 0)), "valid": False,
                  "crashed": True, "error": "attempt did not finish (crash or kill); charged its cap",
                  "category": "", "success": False}
                 for r in raw if r.get("reservation")
                 and (r.get("task"), r.get("arm"), int(r.get("rep", 0))) not in finished]
        return meta, runs
    raise SystemExit(f"error: no experiment {exp_id_or_path!r}")


def list_experiments() -> list[dict[str, Any]]:
    base = lab_home() / "experiments"
    out = []
    for d in sorted(base.glob("*/experiment.json")) if base.is_dir() else []:
        try:
            meta = json.loads(d.read_text("utf-8"))
        except ValueError:
            continue
        runs = (d.parent / "runs.jsonl")
        meta["runs_recorded"] = sum(1 for line in runs.read_text("utf-8").splitlines()
                                    if line.strip() and '"reservation": true' not in line) \
            if runs.exists() else 0
        out.append(meta)
    return out


def run_experiment(suite: Path, tasks: list[Task], bases: dict[str, Base], opts: LabOptions,
                   resume: str | None = None, log: Any = print) -> dict[str, Any]:
    if opts.fake and (not opts.claude_cmd or Path(opts.claude_cmd[0]).name in {"claude", "claude.exe"}):
        # fake mode skips the budget, config audit and preflight: never with the real client
        raise SystemExit("error: fake mode needs a fake client command, not the real `claude`")
    if not opts.fake and not opts.dry_run and opts.max_cost_usd <= 0:
        raise SystemExit("error: live coding experiments need an explicit, positive --max-cost-usd "
                         "(model usage is billable; nothing has been run)")
    if opts.max_cost_per_run <= 0 or opts.max_turns <= 0 or opts.timeout_s <= 0:
        raise SystemExit("error: --max-cost-per-run, --max-turns and --timeout must be positive")
    if not opts.fake:
        problems = audit_config_dir(opts.config_dir or eval_config_dir())
        if problems and not opts.dry_run:
            raise SystemExit("error: the eval Claude config directory is not clean:\n  "
                             + "\n  ".join(problems))
        if not opts.dry_run:
            sample = arm_settings(Path(tempfile.gettempdir()), suite, suite_denied(suite))
            bad = preflight_settings(sample, opts.claude_cmd, opts.config_dir or eval_config_dir())
            if bad:
                raise SystemExit("error: settings preflight failed (the OS sandbox would be "
                                 "silently dropped):\n  " + "\n  ".join(bad))
    missing_tools = {t.id: evals.missing_toolchain(bases[t.base]) for t in tasks
                     if evals.missing_toolchain(bases[t.base])}
    if missing_tools and not opts.fake and not opts.dry_run:
        # a task skipped for a missing tool would silently leave the schedule: refuse instead
        raise SystemExit("error: toolchain missing on this host; nothing was run:\n  " + "\n  ".join(
            f"{tid}: {', '.join(tools)}" for tid, tools in sorted(missing_tools.items())))
    sandbox_problems = grading_sandbox_problems(tasks, bases, opts.grading_backend)
    if sandbox_problems and not opts.dry_run:
        # never pay for a run that could not be graded in isolation
        raise SystemExit("error: no sandbox for grading (model-written code is never run unsandboxed); "
                         "nothing was run:\n  " + "\n  ".join(sandbox_problems))
    exp_id = resume or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    edir = opts.results_dir or experiment_dir(exp_id)
    if not opts.dry_run:  # a dry run records nothing: it must not look like an experiment
        edir.mkdir(parents=True, exist_ok=True)
    meta_path = edir / "experiment.json"
    runs_path = edir / "runs.jsonl"
    planned = len(tasks) * len(opts.arms) * opts.repeat
    protocol = {"arms": {a.name: sorted(a.features) for a in opts.arms}, "seed": opts.seed,
                "model": opts.model or "(claude default)", "effort": opts.effort,
                "max_turns": opts.max_turns, "timeout_s": opts.timeout_s,
                "max_cost_per_run_usd": opts.max_cost_per_run, "repeat": opts.repeat,
                "reservation_per_run_usd": round(reservation(opts), 4),
                "repo_ai_version": __version__,  # one build per experiment (pre-registered)
                "tasks": [t.id for t in tasks], "fake": opts.fake, "blind": opts.blind}
    if resume and meta_path.exists():
        # a resumed experiment must be the same experiment: never mix protocols
        old = json.loads(meta_path.read_text("utf-8"))
        # keys added after an experiment began default to what that version did
        legacy = {"repeat": protocol["repeat"], "reservation_per_run_usd": round(
            old.get("max_cost_per_run_usd", 0) * RESERVATION_FACTOR, 4)}
        changed = [k for k, v in protocol.items() if old.get(k, legacy.get(k)) != v]
        if changed:
            raise SystemExit(f"error: --resume {exp_id} with a different protocol ({', '.join(changed)}); "
                             "resume with exactly the original arms, tasks, model, effort, caps and seed")
    done, spent = ledger_state(runs_path, reservation(opts))
    meta = {"id": exp_id, "suite": suite.name, "arms": {a.name: sorted(a.features) for a in opts.arms},
            "repo_ai_version": __version__,
            "seed": opts.seed, "model": opts.model or "(claude default)", "effort": opts.effort,
            "max_turns": opts.max_turns, "timeout_s": opts.timeout_s, "repeat": opts.repeat,
            "budget_usd": opts.max_cost_usd, "max_cost_per_run_usd": opts.max_cost_per_run,
            "reservation_per_run_usd": round(reservation(opts), 4),
            "completion_budget_usd": completion_budget(planned, reservation(opts)),
            "planned_runs": planned, "worst_case_usd": completion_budget(planned, reservation(opts)),
            "tasks": [t.id for t in tasks], "fake": opts.fake, "blind": opts.blind,
            "task_order": opts.task_order, "max_invalid_rate": opts.max_invalid_rate,
            "schedule": schedule(tasks, opts.arms, opts.repeat, opts.seed),
            "permissions": {"mode": "dontAsk", "allowed": list(evals.ALLOWED_TOOLS),
                            "disallowed": list(evals.DISALLOWED_TOOLS)},
            "cost_note": "reported costs are Claude Code client-side estimates, not billing",
            "started": meta_started(meta_path)}
    if not opts.dry_run:
        meta_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    if opts.dry_run:
        root = Path(tempfile.gettempdir())
        meta["example_argv"] = claude_argv(opts, "<task prompt>", opts.max_cost_per_run,
                                           root / "settings.json")
        meta["example_settings"] = arm_settings(root, suite, suite_denied(suite))
        meta["dry_run"] = True
        meta["sandbox_problems"] = sandbox_problems
        meta["missing_toolchains"] = missing_tools
        return meta
    cancel = threading.Event()
    previous = signal.signal(signal.SIGINT, lambda *_: cancel.set()) \
        if threading.current_thread() is threading.main_thread() else None
    root = Path(tempfile.mkdtemp(prefix="repo-ai-lab-"))
    stopped = ""
    try:
        for rep in range(opts.repeat):
            for index, task in enumerate(tasks):
                if cancel.is_set():
                    stopped = stopped or "cancelled"  # keep a stopping rule's own reason
                    break
                base = bases[task.base]
                if evals.missing_toolchain(base):
                    continue
                full_order = arm_order(task.id, rep, opts.arms, opts.seed, index)  # pre-registered
                order = [a for a in full_order if (task.id, a.name, rep) not in done]
                if not order:
                    continue
                gated = not opts.fake or opts.max_cost_usd > 0  # a fake run with a budget tests the gate
                reserve = reservation(opts)  # cap + one call: what a run can cost at most
                if gated and opts.max_cost_usd - spent + 1e-9 < len(order) * reserve:
                    stopped = "budget"
                    break
                for arm in order:
                    if gated:  # a crash mid-run must never hide what it may have cost
                        with runs_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps({"reservation": True, "task": task.id, "arm": arm.name,
                                                 "rep": rep, "reserved_usd": reserve}) + "\n")
                    # every arm gets the same cap; the reservation above keeps the total inside the budget
                    row = run_one(task, base, suite, arm, opts, root, opts.max_cost_per_run, cancel)
                    row["rep"] = rep
                    row["order"] = [a.name for a in full_order]
                    protocol_problem = _protocol_drift(row, opts, runs_path)
                    if protocol_problem:
                        row.setdefault("isolation_problems", []).append(protocol_problem)
                        row["valid"] = False
                    spent += _charge(row, reservation(opts)) if gated else 0.0
                    with runs_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, sort_keys=True) + "\n")
                    cost = row.get("reported_cost_usd")
                    if gated and isinstance(cost, (int, float)) and cost > reserve + 1e-9:
                        # the reservation assumption failed: stop before anything else is spent
                        stopped = f"run cost ${cost:.4f} above its reservation ${reserve:.4f}"
                        cancel.set()
                    if protocol_problem and "version" in protocol_problem:
                        stopped = "claude-code-version-changed"  # pre-registered stopping rule
                        cancel.set()
                    outcome = "done" if opts.blind else ("PASS" if row.get("success") else "fail")
                    log(f"  {task.id} [{arm.name}] {outcome}"
                        f"{'' if row['valid'] else ' (invalid: ' + _why_invalid(row) + ')'}"
                        f"  spent ${spent:.2f}")
                    attempts, invalid = _invalid_rate(runs_path)
                    if attempts >= 9 and invalid / attempts > opts.max_invalid_rate:
                        stopped = f"invalid-rate {invalid}/{attempts} above {opts.max_invalid_rate:.0%}"
                        cancel.set()  # pre-registered stopping rule: fix the setup before spending more
                    if cancel.is_set():
                        break
            if stopped:
                break
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
        shutil.rmtree(root, ignore_errors=True)
    meta["stopped"] = stopped or None
    meta["spent_usd_charged"] = round(spent, 4)
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


RESERVATION_FACTOR = 1.25


def reservation(opts: LabOptions) -> float:
    """Worst-case cost of one run as the budget gate counts it."""
    if opts.reserve_per_run is not None:
        if opts.reserve_per_run < opts.max_cost_per_run:
            raise SystemExit("error: --reserve-per-run must be at least --max-cost-per-run")
        return float(opts.reserve_per_run)
    return opts.max_cost_per_run * RESERVATION_FACTOR


def completion_budget(planned_runs: int, reserve: float) -> float:
    """The smallest budget that is *guaranteed* to complete every planned run,
    provided no run costs more than its reservation: the gate never starts a
    task unless each of its remaining runs' reservation fits, so in the worst
    case (every run costing its full reservation) the last task needs the
    whole of planned_runs x reserve."""
    return _cents_up(planned_runs * reserve)


def _cents_up(usd: float) -> float:
    """Round a budget *up* to the cent: rounding down could leave it short."""
    return math.ceil(round(usd * 100, 6)) / 100


def recommended_budget(planned_runs: int, arms_per_task: int, cost_per_run_upper: float,
                       reserve: float) -> float:
    """The smallest budget that completes the experiment if runs cost at most
    `cost_per_run_upper` on average (an upper estimate, e.g. from calibration):
    everything before the last task at that cost, plus full reservations for
    the last task's arms (the gate demands them before starting it)."""
    return _cents_up((planned_runs - arms_per_task) * cost_per_run_upper + arms_per_task * reserve)


CAP_CHOICES = (0.75, 1.00, 1.50, 2.00)


def preregistered_limits(runs: list[dict[str, Any]], planned_runs: int = 150,
                         arms_per_task: int = 3) -> dict[str, Any]:
    """The main experiment's limits from calibration runs, by the rules fixed
    in docs/PREREGISTRATION.md §9 (Amendment 1). Pure arithmetic: no choice
    is left to whoever reads the calibration results."""
    costed = [r for r in runs if isinstance(r.get("reported_cost_usd"), (int, float))]
    out: dict[str, Any] = {"runs": len(runs), "runs_with_cost": len(costed),
                           "runs_without_cost": len(runs) - len(costed)}
    if not costed:
        return {**out, "problem": "no calibration run reported a cost"}
    costs = [float(r["reported_cost_usd"]) for r in costed]
    by_arm: dict[str, list[float]] = {}
    for r in costed:
        by_arm.setdefault(str(r.get("arm")), []).append(float(r["reported_cost_usd"]))
    def p90(xs: list[float]) -> float:  # the report's nearest-rank p90 (_cost_distribution)
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]
    arm_p90 = max(p90(v) for v in by_arm.values())
    arm_mean = max(sum(v) / len(v) for v in by_arm.values())
    cap = next((c for c in CAP_CHOICES if c >= 2 * arm_p90 - 1e-9 and c > max(costs)), None)
    turns = [int(r["turns"]) for r in runs if isinstance(r.get("turns"), int)]
    hit_turns = any(r.get("subtype") == "error_max_turns" for r in runs)
    max_turns = 30 if not hit_turns and max(turns, default=0) <= 24 else \
        50 if not hit_turns and max(turns, default=0) <= 40 else 80
    walls = [float(r["wall_s"]) for r in runs if isinstance(r.get("wall_s"), (int, float))]
    timeout = max(1800, math.ceil(2 * max(walls, default=0)))
    calls = [float(r["max_call_cost_usd_est"]) for r in runs
             if isinstance(r.get("max_call_cost_usd_est"), (int, float))]
    out.update(per_arm_p90_max=round(arm_p90, 4), per_arm_mean_max=round(arm_mean, 4),
               cost_max=round(max(costs), 4), overall_p90=round(p90(costs), 4),
               max_call_cost_usd_est=round(max(calls), 4) if calls else None,
               turns_max=max(turns, default=None), max_turns_hit=hit_turns,
               wall_max_s=max(walls, default=None), max_turns=max_turns, timeout_s=timeout)
    if cap is None:
        return {**out, "max_cost_per_run": None,
                "problem": "no pre-registered cap fits the calibration costs: stop and re-register"}
    margin = max((RESERVATION_FACTOR - 1) * cap,  # the default margin, or two of the largest calls
                 math.ceil(round(2 * max(calls, default=0.0) * 20, 6)) / 20)  # rounded up to $0.05
    reserve = round(cap + margin, 4)
    upper = min(reserve, max(2 * arm_mean, p90(costs)))
    rec = (planned_runs - arms_per_task) * upper + arms_per_task * reserve
    out.update(max_cost_per_run=cap, reserve_margin=margin, reserve_per_run=reserve,
               reserve_flag_needed=reserve > cap * RESERVATION_FACTOR + 1e-9,
               mean_cost_upper=round(upper, 4),
               guaranteed_budget=completion_budget(planned_runs, reserve),
               recommended_budget=math.ceil(round(rec / 5, 6)) * 5)
    return out


def _invalid_rate(runs_path: Path) -> tuple[int, int]:
    attempts = invalid = 0
    for line in runs_path.read_text("utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("reservation") or r.get("cancelled"):
            continue
        attempts += 1
        invalid += not r.get("valid")
    return attempts, invalid


def arm_order(task_id: str, rep: int, arms: list[Arm], seed: int,
              index: int | None = None) -> list[Arm]:
    """The arm order for one (task, repetition): a pure function of the
    protocol, so it can be pre-registered and a resumed experiment keeps it.

    With the task's position `index` in the experiment (as `run_experiment`
    passes it), orders are balanced: all permutations of the arms are used
    about equally often (a seeded Latin-square-style cycle), and repetitions of
    a task get different orders. Arm position matters for cost (prompt caching
    across consecutive runs), so balance reduces that nuisance variance."""
    from itertools import permutations
    if index is None:
        order = list(arms)
        random.Random(f"{seed}:{task_id}:{rep}").shuffle(order)
        return order
    perms = [list(p) for p in permutations(arms)]
    random.Random(f"{seed}:perms").shuffle(perms)
    shift = max(1, len(perms) // 2)
    return perms[(index + rep * shift) % len(perms)]


def interleave_by_base(tasks: list[Task], seed: int) -> list[Task]:
    """An execution order in which every prefix is spread across the bases, so
    an early budget stop still leaves a comparison over as many projects as
    possible instead of all of one project and none of another: round-robin
    over the bases that still have tasks (a seeded base order in each round),
    each base's tasks in a seeded order. A pure function of the task set and
    the seed, so it can be pre-registered (the order is recorded as `tasks`)."""
    groups: dict[str, list[Task]] = {}
    for t in sorted(tasks, key=lambda t: t.id):
        groups.setdefault(t.base, []).append(t)
    for base, items in groups.items():
        random.Random(f"{seed}:interleave:{base}").shuffle(items)
    out: list[Task] = []
    rnd = 0
    while any(groups.values()):
        bases = sorted(b for b, items in groups.items() if items)
        random.Random(f"{seed}:interleave:round:{rnd}").shuffle(bases)
        out += [groups[b].pop(0) for b in bases]
        rnd += 1
    return out


def schedule(tasks: list[Task], arms: list[Arm], repeat: int, seed: int) -> list[dict[str, Any]]:
    return [{"rep": rep, "task": t.id, "order": [a.name for a in arm_order(t.id, rep, arms, seed, i)]}
            for rep in range(repeat) for i, t in enumerate(tasks)]


def ledger_state(runs_path: Path, per_run: float) -> tuple[set[tuple[str, str, int]], float]:
    """(attempts already complete, money already spent) from runs.jsonl.
    A reservation without a finished row is a run that crashed or was killed:
    it is charged the full cap (it may have spent it) and runs again."""
    done: set[tuple[str, str, int]] = set()
    spent = 0.0
    open_reservations: dict[tuple[str, str, int], float] = {}
    if not runs_path.exists():
        return done, spent
    for line in runs_path.read_text("utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        key = (r.get("task", ""), r.get("arm", ""), int(r.get("rep", 0)))
        if r.get("reservation"):
            open_reservations[key] = float(r.get("reserved_usd", per_run))
            continue
        open_reservations.pop(key, None)
        if not r.get("cancelled"):
            done.add(key)
        spent += _charge(r, per_run)
    spent += sum(open_reservations.values())
    return done, spent


def _protocol_drift(row: dict[str, Any], opts: LabOptions, runs_path: Path) -> str:
    """Pre-registered invariants: the model the run actually used, and one
    Claude Code version for the whole experiment."""
    if opts.fake:
        return ""
    if opts.model and row.get("model") and opts.model.startswith("claude-") and row["model"] != opts.model:
        return f"model {row['model']} instead of {opts.model}"
    version = row.get("claude_code_version")
    if version and runs_path.exists():
        for line in runs_path.read_text("utf-8").splitlines():
            try:
                prev = json.loads(line)
            except ValueError:
                continue
            seen = prev.get("claude_code_version")
            if seen and not prev.get("reservation"):
                return "" if seen == version else f"Claude Code version changed {seen} -> {version}"
    return ""


def meta_started(meta_path: Path) -> str:
    try:
        return json.loads(meta_path.read_text("utf-8")).get("started", "")
    except (OSError, ValueError):
        return time.strftime("%Y-%m-%dT%H:%M:%S")


def _charge(row: dict[str, Any], per_run: float) -> float:
    """Reported cost, or `per_run` (the full reservation) when none was
    reported. (Fake runs report their own fake cost; the caller only charges
    them when a budget is set.)"""
    cost = row.get("reported_cost_usd")
    return per_run if cost is None else max(float(cost), 0.0)


def _why_invalid(row: dict[str, Any]) -> str:
    if row.get("error"):
        return str(row["error"])[:80]
    if row.get("isolation_problems"):
        return "; ".join(row["isolation_problems"])[:80]
    if row.get("contaminated"):
        return "hidden material in workspace"
    return "cancelled"


# --------------------------------------------------------------------------
# statistics and reports
# --------------------------------------------------------------------------
def _median(vals: list[Any]) -> float | None:
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    mid = len(vals) // 2
    return round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2, 3)


def _cost_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    costs = sorted(float(r["reported_cost_usd"]) for r in rows
                   if isinstance(r.get("reported_cost_usd"), (int, float)))
    turns = sorted(int(r["turns"]) for r in rows if isinstance(r.get("turns"), int))
    if not costs:
        return {}
    def q(xs: list[Any], f: float) -> Any:
        return xs[min(len(xs) - 1, int(round(f * (len(xs) - 1))))]
    return {"cost_p50": round(q(costs, 0.5), 4), "cost_p90": round(q(costs, 0.9), 4),
            "cost_max": round(costs[-1], 4),
            "cost_cap_hits": sum(1 for r in rows if r.get("subtype") == "error_max_budget_usd"),
            "turns_p90": q(turns, 0.9) if turns else None, "turns_max": turns[-1] if turns else None,
            "max_turns_hits": sum(1 for r in rows if r.get("subtype") == "error_max_turns"),
            "wall_max_s": max((r["wall_s"] for r in rows if isinstance(r.get("wall_s"), (int, float))),
                              default=None),
            # the reservation margin has to cover one call past the cap (estimated per call)
            "call_cost_max_est": max((r["max_call_cost_usd_est"] for r in rows
                                      if isinstance(r.get("max_call_cost_usd_est"), (int, float))),
                                     default=None)}


def _sd(vals: list[Any]) -> float | None:
    xs = [float(v) for v in vals if isinstance(v, (int, float))]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return round((sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5, 2)


def _mean(vals: list[Any]) -> float | None:
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 3) if vals else None


def summarize(runs: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    from .stats import wilson
    valid = [r for r in runs if r.get("valid")]
    arms = sorted({r["arm"] for r in runs}, key=lambda a: (["baseline", "core", "full"] + [a]).index(a))
    per_arm: dict[str, Any] = {}
    for arm in arms:
        rows = [r for r in valid if r["arm"] == arm]
        n = len(rows)
        per_arm[arm] = {
            "n": n,
            "excluded": sum(1 for r in runs if r["arm"] == arm and not r.get("valid")),
            "success_rate": round(sum(1 for r in rows if r.get("success")) / n, 3) if n else None,
            "success_wilson95": [round(v, 3) for v in wilson(sum(1 for r in rows if r.get("success")), n)]
            if n else None,
            "sd_tokens": _sd([(r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
                              for r in rows if r.get("input_tokens") is not None]),
            "sd_tool_calls": _sd([r.get("tool_calls") for r in rows]),
            "mean_cache_read_tokens": _mean([r.get("cache_read_tokens") for r in rows]),
            "mean_uncached_input_tokens": _mean([r.get("uncached_input_tokens") for r in rows]),
            "hidden_pass_mean": _mean([r.get("hidden_pass_fraction") for r in rows]),
            "regression_rate": round(sum(1 for r in rows if r.get("regression")) / n, 3) if n else None,
            "abandoned_rate": round(sum(1 for r in rows if r.get("abandoned")) / n, 3) if n else None,
            "timeouts": sum(1 for r in rows if r.get("timed_out")),
            "mean_tokens": _mean([(r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
                                  for r in rows if r.get("input_tokens") is not None]),
            "median_wall_s": _median([r.get("wall_s") for r in rows]),
            "median_tool_calls": _median([r.get("tool_calls") for r in rows]),
            "median_test_commands": _median([r.get("test_commands") for r in rows]),
            "median_turns": _median([r.get("turns") for r in rows]),
            "median_first_edit_s": _median([r.get("first_edit_s") for r in rows]),
            "median_reads_before_edit": _median([r.get("files_read_before_first_edit") for r in rows]),
            "mean_cost_usd": _mean([r.get("reported_cost_usd") for r in rows]),
            # the cost distribution (for choosing --max-cost-per-run): every attempt with a cost
            **_cost_distribution([r for r in runs if r["arm"] == arm]),
            "mean_repo_ai_context_tokens": _mean([r.get("repo_ai_context_tokens_est") for r in rows]),
            "mean_setup_s": _mean([r.get("setup_s") for r in rows]),
            "unnecessary_edit_rate": round(sum(1 for r in rows if r.get("unnecessary_edits")) / n, 3)
            if n else None,
        }
    comparisons = []
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            comparisons.append(compare_arms(valid, a, b, seed))
    _holm_family(comparisons)  # family-wise error control across the comparisons of this experiment
    outcome_comparisons = {name: _holm_family([compare_arms([as_outcome(r) for r in valid], a, b, seed)
                                                 for i, a in enumerate(arms) for b in arms[i + 1:]])
                           for name, as_outcome in OUTCOMES.items()}
    for arm in arms:
        rows = [r for r in valid if r["arm"] == arm]
        for name, as_outcome in OUTCOMES.items():
            per_arm[arm][f"{name}_rate"] = round(sum(1 for r in rows if as_outcome(r)["success"]) / len(rows),
                                                 3) if rows else None
    categories: dict[str, dict[str, Any]] = {}
    for r in valid:
        c = categories.setdefault(r["category"], {})
        s = c.setdefault(r["arm"], [0, 0])
        s[0] += int(bool(r.get("success")))
        s[1] += 1
    attempts = [r for r in runs if not r.get("cancelled")]
    calibration = bool(attempts) and all(str(r.get("task", "")).startswith("cal-") for r in attempts)
    return {"arms": per_arm, "comparisons": comparisons, "outcome_comparisons": outcome_comparisons,
            # calibration exists only to set the main run's limits, by the pre-registered rule
            **({"preregistered_limits": preregistered_limits(attempts)} if calibration else {}),
            "outcomes": {arm: outcome_counts(runs, arm) for arm in arms},
            "sensitivity": sensitivity(runs, seed),
            "by_category": {k: {arm: f"{v[0]}/{v[1]}" for arm, v in d.items()}
                            for k, d in sorted(categories.items())},
            "runs": len(runs), "valid_runs": len(valid),
            "fake": any(r.get("fake") for r in runs)}


# Outcomes derived from what grading records, analysed beside `success` (all
# hidden tests pass): the grader is unchanged. `correct_no_regression` is
# success as SEALED_V2.md defines it: hidden tests pass and the runnable
# visible suite still passes.
OUTCOMES = {
    "correct_no_regression": lambda r: {**r, "success": bool(r.get("success")) and not r.get("regression")},
    "regression_free": lambda r: {**r, "success": not r.get("regression")},
}


def _holm_family(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Holm across one outcome's comparisons (each outcome is its own family)."""
    from .stats import holm
    raw = {f"{c['a']}|{c['b']}": c.get("permutation_p") if c.get("permutation_p") is not None
           else c.get("mcnemar_p") for c in comparisons if c.get("pairs")}
    adjusted = holm({k: float(v) for k, v in raw.items() if v is not None})
    for c in comparisons:
        key = f"{c['a']}|{c['b']}"
        if key in adjusted:
            c["p_holm"] = adjusted[key]
            if c.get("verdict_class") in {"improvement", "regression"} and adjusted[key] >= 0.05:
                c["verdict_class"] = "inconclusive"
                c["verdict"] = f"inconclusive: not significant after Holm correction (p={adjusted[key]})"
    return comparisons


CONTINUOUS = (("tokens", lambda r: None if r.get("input_tokens") is None
                else (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)),
              ("uncached_input_tokens", lambda r: r.get("uncached_input_tokens")),
              ("cache_read_tokens", lambda r: r.get("cache_read_tokens")),
              ("cost_usd", lambda r: r.get("reported_cost_usd")),
              ("tool_calls", lambda r: r.get("tool_calls")),
              ("turns", lambda r: r.get("turns")),
              ("wall_s", lambda r: r.get("wall_s")))


def compare_arms(valid: list[dict[str, Any]], a: str, b: str, seed: int) -> dict[str, Any]:
    """Paired by task. Repetitions of a task are averaged first (the task is
    the unit of analysis, see `stats.compare_clustered`); with one repetition
    this is the paired Bonett-Price interval and exact McNemar test. Continuous
    metrics: per-task means, then paired Wilcoxon and bootstrap intervals."""
    from . import stats
    by_key: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for r in valid:
        by_key.setdefault((r["task"], int(r.get("rep", 0))), {})[r["arm"]] = r
    by_task: dict[str, list[dict[str, dict[str, Any]]]] = {}
    for (task, _), d in sorted(by_key.items()):
        if a in d and b in d:
            by_task.setdefault(task, []).append(d)
    success = {task: [(int(bool(d[a].get("success"))), int(bool(d[b].get("success")))) for d in reps]
               for task, reps in by_task.items()}
    out: dict[str, Any] = {"a": a, "b": b, **stats.compare_clustered(success, label_a=a, label_b=b, seed=seed)}
    # a task with a valid run in only one arm cannot be compared: listed, never silently dropped
    out["unpaired_tasks"] = sorted({t for (t, _), d in by_key.items() if (a in d) != (b in d)})
    if not success:
        return out
    metrics = {}
    for name, get in CONTINUOUS:
        xs: list[float] = []
        ys: list[float] = []
        for reps in by_task.values():
            vals: list[tuple[float, float]] = []
            for d in reps:
                x, y = get(d[a]), get(d[b])
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    vals.append((float(x), float(y)))
            if vals:  # one value per task: the mean over its repetitions
                xs.append(sum(x for x, _ in vals) / len(vals))
                ys.append(sum(y for _, y in vals) / len(vals))
        if xs:
            metrics[name] = stats.compare_continuous(xs, ys, seed=seed)
    out["metrics"] = metrics
    out["median_token_delta"] = (metrics.get("tokens") or {}).get("median_diff")
    out["median_cost_delta_usd"] = (metrics.get("cost_usd") or {}).get("median_diff")
    out["regressions"] = sorted(t for (t, _), d in by_key.items() if a in d and b in d
                                and d[a].get("success") and not d[b].get("success"))
    # sensitivity: the ordinary (unclustered) paired analysis, labelled as such
    flat = [p for reps in success.values() for p in reps]
    out["unclustered"] = {k: v for k, v in stats.compare_binary(flat, label_a=a, label_b=b).items()
                          if k in {"pairs", "diff", "ci95", "mcnemar_p", "verdict"}}
    return out


def sensitivity(runs: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    """Pre-registered sensitivity analyses of the primary comparisons."""
    as_failures = [{**r, "valid": True, "success": False} if not r.get("valid") and not r.get("cancelled")
                   else r for r in runs]
    rep0 = [r for r in runs if int(r.get("rep", 0)) == 0]
    out = {}
    composite = OUTCOMES["correct_no_regression"]
    # a workspace file identical to a hidden test: a diagnostic, never proof (integrity.py)
    matched = [{**r, "valid": False} if (r.get("hidden_content_match") or {}).get("identical_files") else r
               for r in runs]
    for name, rows in (("invalid_as_failures", as_failures), ("repetition_0_only", rep0),
                       ("content_match_as_invalid", matched),
                       ("correct_no_regression_invalid_as_failures",
                        [composite(r) if r.get("valid") else r for r in as_failures])):
        valid = [r for r in rows if r.get("valid")]
        arms = sorted({r["arm"] for r in rows}, key=lambda a: (["baseline", "core", "full"] + [a]).index(a))
        out[name] = [{k: c.get(k) for k in ("a", "b", "tasks", "diff", "ci95", "permutation_p", "mcnemar_p",
                                             "verdict")}
                     for i, a in enumerate(arms) for b in arms[i + 1:]
                     for c in [compare_arms(valid, a, b, seed)]]
    return out


def outcome_counts(runs: list[dict[str, Any]], arm: str) -> dict[str, int]:
    """Every attempt, accounted for: nothing is silently excluded. Budget,
    turn and time limits are *valid failures* (intention to treat)."""
    rows = [r for r in runs if r.get("arm") == arm]
    counts = {"attempts": len(rows), "valid": 0, "success": 0, "failure": 0,
              "stopped_by_cost_cap": 0, "stopped_by_max_turns": 0, "timed_out": 0,
              "invalid_isolation": 0, "invalid_contamination": 0, "errors": 0, "crashed": 0,
              "cancelled": 0}
    for r in rows:
        if r.get("valid"):
            counts["valid"] += 1
            counts["success" if r.get("success") else "failure"] += 1
            counts["stopped_by_cost_cap"] += r.get("subtype") == "error_max_budget_usd"
            counts["stopped_by_max_turns"] += r.get("subtype") == "error_max_turns"
            counts["timed_out"] += bool(r.get("timed_out"))
        elif r.get("cancelled"):
            counts["cancelled"] += 1
        elif r.get("crashed"):
            counts["crashed"] += 1
        elif r.get("contaminated"):
            counts["invalid_contamination"] += 1
        elif r.get("isolation_problems"):
            counts["invalid_isolation"] += 1
        else:
            counts["errors"] += 1
    return counts


def stats_min_pairs() -> int:
    from .stats import MIN_PAIRS
    return MIN_PAIRS


def render_report(meta: dict[str, Any], summary: dict[str, Any]) -> str:
    arms = list(summary["arms"])
    head = {"baseline": "Plain Claude", "core": "repo-ai Core", "full": "repo-ai Full"}

    def cell(arm: str, key: str, fmt: str = "{}") -> str:
        a = summary["arms"].get(arm, {})
        v = a.get(key)
        if not a.get("n"):
            return "Not run"
        return "n/a" if v is None else fmt.format(v)
    fake = " **(FAKE CLIENT — not model evidence)**" if summary.get("fake") else ""
    lines = [f"## Coding experiment {meta.get('id')}{fake}",
             f"model: {meta.get('model')}, max turns {meta.get('max_turns')}, seed {meta.get('seed')}; "
             f"runs: {summary['valid_runs']} valid of {summary['runs']}; charged "
             f"${meta.get('spent_usd_charged', 0):.2f} of ${meta.get('budget_usd', 0):.2f} "
             "(Claude Code estimates, not billing)", "",
             "| Metric | " + " | ".join(head.get(a, a) for a in arms) + " |",
             "|---|" + "---|" * len(arms)]
    rows = [("Task success rate", "success_rate", "{:.0%}"),
            ("Correct with no regression", "correct_no_regression_rate", "{:.0%}"),
            ("Regression-free", "regression_free_rate", "{:.0%}"),
            ("Hidden tests passed (mean fraction)",
            "hidden_pass_mean", "{:.0%}"), ("Average tokens", "mean_tokens", "{:,.0f}"),
            ("Median runtime (s)", "median_wall_s", "{}"), ("Median tool calls", "median_tool_calls", "{}"),
            ("Median test runs by the agent", "median_test_commands", "{}"),
            ("Estimated model cost (mean $)", "mean_cost_usd", "${}"),
            ("Regression rate", "regression_rate", "{:.0%}"), ("Sample size (valid runs)", "n", "{}"),
            ("Median time to first edit (s)", "median_first_edit_s", "{}"),
            ("repo-ai context injected (tokens, est.)", "mean_repo_ai_context_tokens", "{}"),
            ("repo-ai setup time (s)", "mean_setup_s", "{}"),
            ("Cost p50 ($)", "cost_p50", "{}"),
            ("Cost p90 ($)", "cost_p90", "{}"), ("Cost max ($)", "cost_max", "{}"),
            ("Runs stopped by the cost cap", "cost_cap_hits", "{}"),
            ("Turns p90", "turns_p90", "{}"), ("Turns max", "turns_max", "{}"),
            ("Runs stopped by max turns", "max_turns_hits", "{}"),
            ("Timeouts", "timeouts", "{}"), ("Longest run (s)", "wall_max_s", "{}"),
            ("Largest single API call ($, est.)", "call_cost_max_est", "{}")]
    for label, key, fmt in rows:
        lines.append(f"| {label} | " + " | ".join(cell(a, key, fmt) for a in arms) + " |")
    lines.append("")
    if summary.get("outcomes"):
        lines.append("Every attempt (budget, turn and time limits count as failures; nothing is dropped):")
        keys = ["attempts", "valid", "success", "failure", "stopped_by_cost_cap", "stopped_by_max_turns",
                "timed_out", "invalid_isolation", "invalid_contamination", "errors", "crashed", "cancelled"]
        lines.append("| | " + " | ".join(head.get(a, a) for a in arms) + " |")
        lines.append("|---|" + "---|" * len(arms))
        for k in keys:
            lines.append(f"| {k.replace('_', ' ')} | " + " | ".join(
                str(summary["outcomes"].get(a, {}).get(k, 0)) for a in arms) + " |")
        planned = len(meta.get("tasks") or []) * int(meta.get("repeat") or 1)
        if planned:
            lines.append(f"| not attempted (of {planned} planned) | " + " | ".join(
                str(max(0, planned - summary["outcomes"].get(a, {}).get("attempts", 0))) for a in arms) + " |")
        lines.append("")
    lines.append("Success rates: " + "; ".join(
        f"{head.get(a, a)} {summary['arms'][a]['success_rate']:.0%} "
        f"(95% Wilson {summary['arms'][a]['success_wilson95'][0]:.0%}–{summary['arms'][a]['success_wilson95'][1]:.0%})"
        for a in arms if summary["arms"][a].get("n")))
    lines.append("")
    for c in summary["comparisons"]:
        if not c.get("pairs"):
            lines.append(f"- {c['a']} vs {c['b']}: not evaluated")
            continue
        lines.append(f"- **{c['b']} vs {c['a']}**: success {c['success_b']:.0%} vs {c['success_a']:.0%}, "
                     f"diff {c['diff']:+.0%} (95% CI {c['ci95'][0]:+.0%}…{c['ci95'][1]:+.0%}, "
                     "task-clustered Bonett-Price; "
                     + (f"permutation p={c['permutation_p']}" if c.get("permutation_p") is not None
                        else f"McNemar p={c['mcnemar_p']}")
                     + (f", Holm p={c['p_holm']}" if c.get("p_holm") is not None else "")
                     + f"; {c.get('tasks', c['pairs'])} tasks, {c['pairs']} paired runs) → **{c['verdict']}**"
                     + (f"; regressions: {', '.join(c['regressions'])}" if c["regressions"] else ""))
        if c.get("unpaired_tasks"):
            lines.append(f"  - not compared (a valid run in one arm only): {', '.join(c['unpaired_tasks'])}")
        for name, m in (c.get("metrics") or {}).items():
            if name in {"tokens", "cost_usd", "tool_calls", "wall_s", "cache_read_tokens"}:
                rough = ", bootstrap: rough for n<10" if m["pairs"] < stats_min_pairs() else ""
                lines.append(f"  - {name}: median paired diff {m['median_diff']:+g} "
                             f"(95% CI {m['median_diff_ci95'][0]:+g}…{m['median_diff_ci95'][1]:+g}{rough}; "
                             f"lower in {m['lower_in_b']}/{m['pairs']}; Wilcoxon p={m['wilcoxon_p']})")
    labels = {"correct_no_regression": "correct with no regression (hidden tests and visible suite pass)",
              "regression_free": "regression-free (visible suite passes)"}
    for name, comps in (summary.get("outcome_comparisons") or {}).items():
        for c in comps:
            if c.get("pairs"):
                lines.append(f"- {labels.get(name, name)}, **{c['b']} vs {c['a']}**: {c['success_b']:.0%} vs "
                             f"{c['success_a']:.0%}, diff {c['diff']:+.0%} (95% CI {c['ci95'][0]:+.0%}…"
                             f"{c['ci95'][1]:+.0%}; permutation p={c.get('permutation_p')}"
                             + (f", Holm p={c['p_holm']}" if c.get("p_holm") is not None else "")
                             + f"; {c.get('tasks', c['pairs'])} tasks) → **{c['verdict']}**")
    sens = summary.get("sensitivity") or {}
    if sens:
        lines.append("\nSensitivity analyses (pre-registered):")
        for name, rows in sens.items():
            for c in rows:
                if c.get("tasks"):
                    lines.append(f"  - {name.replace('_', ' ')}: {c['b']} vs {c['a']} diff {c['diff']:+.0%} "
                                 f"(95% CI {c['ci95'][0]:+.0%}…{c['ci95'][1]:+.0%}) → {c['verdict']}")
        for c in summary["comparisons"]:
            u = c.get("unclustered")
            if u and u.get("pairs") and c.get("runs_per_task", 1) != 1:
                lines.append(f"  - unclustered (runs as independent; for comparison only): {c['b']} vs {c['a']} "
                             f"diff {u['diff']:+.0%} (95% CI {u['ci95'][0]:+.0%}…{u['ci95'][1]:+.0%}), "
                             f"n={u['pairs']} runs")
    lim = summary.get("preregistered_limits")
    if lim:
        lines.append("\nMain-experiment limits by the pre-registered rule (PREREGISTRATION.md §9):")
        if lim.get("problem"):
            lines.append(f"  - **{lim['problem']}**")
        else:
            lines.append(f"  - per-run cap C = ${lim['max_cost_per_run']:.2f} (largest per-arm p90 "
                         f"${lim['per_arm_p90_max']}, most expensive run ${lim['cost_max']})")
            lines.append(f"  - reservation R = ${lim['reserve_per_run']:.2f} (margin ${lim['reserve_margin']:.2f}; "
                         f"largest single call ${lim['max_call_cost_usd_est']}, est.)"
                         + ("; pass --reserve-per-run" if lim["reserve_flag_needed"] else ""))
            lines.append(f"  - max turns T = {lim['max_turns']} (most turns used {lim['turns_max']}"
                         f"{', turn limit hit' if lim['max_turns_hit'] else ''}); timeout {lim['timeout_s']} s")
            lines.append(f"  - guaranteed-completion budget ${lim['guaranteed_budget']:.2f}; recommended "
                         f"${lim['recommended_budget']} (147 runs at ${lim['mean_cost_upper']} + 3 reservations)")
    lines.append("\n_Equal observed rates are not evidence of equivalence: equivalence is claimed "
                 "only when the 90% interval lies within ±10 points (TOST). Pilots (n<10) are never "
                 "called significant._")
    if summary["by_category"]:
        lines.append("\nby category (successes/valid runs): " + "; ".join(
            f"{cat} " + ", ".join(f"{a}={v}" for a, v in d.items())
            for cat, d in summary["by_category"].items()))
    return "\n".join(lines) + "\n"


def regressions(runs: list[dict[str, Any]], a: str = "baseline", b: str = "full") -> list[dict[str, Any]]:
    """Tasks the candidate arm failed that the reference arm passed, with
    evidence for a diagnosis (Regression Investigator)."""
    by_task: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for r in runs:
        if r.get("valid"):
            by_task.setdefault((r["task"], int(r.get("rep", 0))), {})[r["arm"]] = r
    out = []
    for (task, rep), d in sorted(by_task.items()):
        if a in d and b in d and d[a].get("success") and not d[b].get("success"):
            ra, rb = d[a], d[b]
            signals = []
            if (rb.get("repo_ai_context_tokens_est") or 0) > 1500:
                signals.append(f"large injected context (~{rb['repo_ai_context_tokens_est']} tokens)")
            if rb.get("first_edit") and rb.get("first_edit_in_gold") is False:
                signals.append(f"first edit outside the gold files ({rb['first_edit']})")
            if (rb.get("subagent_calls") or 0) > (ra.get("subagent_calls") or 0):
                signals.append(f"more subagent calls ({rb.get('subagent_calls')} vs {ra.get('subagent_calls')})")
            if rb.get("timed_out") or rb.get("subtype") in {"error_max_turns", "error_max_budget_usd"}:
                signals.append(f"stopped early ({rb.get('subtype') or 'timeout'})")
            if (rb.get("turns") or 0) > 1.5 * (ra.get("turns") or 1):
                signals.append(f"many more turns ({rb.get('turns')} vs {ra.get('turns')})")
            if rb.get("unnecessary_edits"):
                signals.append(f"edits outside the task: {', '.join(rb['unnecessary_edits'][:3])}")
            if rb.get("regression"):
                signals.append("broke visible tests")
            skills_used = {k: v for k, v in (rb.get("tool_uses") or {}).items() if k == "Skill"}
            if skills_used:
                signals.append(f"invoked skills {skills_used}")
            out.append({"task": task, "rep": rep, "reference": a, "candidate": b,
                        "signals": signals or ["no distinguishing signal: may be model variability "
                                               "(repeat the task to check)"]})
    return out
