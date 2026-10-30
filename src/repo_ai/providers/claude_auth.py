"""How a live Claude Code run authenticates inside repo-ai's isolation, without copying credentials.

Observed on macOS with Claude Code 2.1.314 (docs/engineering/INTEGRATIONS.md has the probe record):

* Claude Code keeps its OAuth login in the login keychain, under an item derived from the config directory
  (``CLAUDE_CONFIG_DIR``) and the account named by ``$USER``. A scratch ``HOME`` hides the login keychain, and a
  missing ``USER`` hides the item: both report "Not logged in". Copying ``~/.claude`` files never helped on macOS
  and is credential copying, so repo-ai no longer does it.
* A short-lived access token is refreshed by the CLI itself and written back to the keychain (an atomic
  ``login.keychain-db.sb-*`` replace) and to ``<config>/.claude.json``. A profile that denies those writes turns a
  routine refresh into "OAuth access token has expired".

Two supported ways to authenticate, chosen in this order:

``token_env``
    ``CLAUDE_CODE_OAUTH_TOKEN`` (from ``claude setup-token``) or ``ANTHROPIC_API_KEY`` is set in repo-ai's own
    environment. The provider runs with a scratch HOME and no keychain access at all. Strongest isolation.
``dedicated_config``
    A repo-ai-owned Claude config directory (default ``~/.local/share/repo-ai/claude-provider``, override
    ``REPO_AI_CLAUDE_CONFIG_DIR``) that the user logged in once with ``CLAUDE_CONFIG_DIR=<dir> claude auth login``.
    It is a separate login from the user's personal ``~/.claude`` (no personal hooks, plugins, MCP servers or
    memory). The provider runs with the real HOME but cannot read anything under it except that directory, the
    Claude installation and the keychain database files, and can write only the workspace, its scratch dir, that
    config directory (minus its customisation files) and the keychain database files.

In both modes the model gets only the file tools ``Read, Edit, Write, Glob, Grep`` (``Read, Glob, Grep`` for
read-only roles), confined to the workspace by ``--restricted``; no shell, web, MCP, subagents, skills, hooks,
plugins or user settings (``--safe-mode``, ``--strict-mcp-config``, ``--disable-slash-commands``,
``--permission-prompts none``). The OS sandbox stays the write boundary either way.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

CONFIG_DIR_ENV = "REPO_AI_CLAUDE_CONFIG_DIR"
TOKEN_ENV_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
EDIT_TOOLS = "Read,Edit,Write,Glob,Grep"
READ_TOOLS = "Read,Glob,Grep"
# Flags the isolated invocation depends on. A Claude Code whose --help lacks any of them is refused, never run
# with weaker isolation (version drift fails closed).
REQUIRED_FLAGS = ("--print", "--output-format", "--permission-mode", "--permission-prompts", "--restricted",
                  "--safe-mode", "--strict-mcp-config", "--tools", "--disable-slash-commands",
                  "--no-session-persistence", "--max-budget-usd")
# Inside the dedicated config dir: what would change the behaviour of later runs. Never writable by the provider.
CUSTOMISATION_PATHS = ("settings.json", "settings.local.json", "CLAUDE.md", "skills", "agents", "commands",
                       "plugins", "hooks", "output-styles", "rules")
KEYCHAIN_FILES = ("login.keychain-db", "metadata.keychain-db")
SENSITIVE_HOME_DIRS = (".ssh", ".aws", ".gnupg", ".config", ".local", "Library", ".kube", ".docker", ".netrc")


@dataclass(frozen=True)
class ClaudeAuthPlan:
    mode: str  # token_env | dedicated_config | none
    config_dir: Path | None
    env_vars: tuple[str, ...]  # names (never values) passed through to the provider
    problems: tuple[str, ...]

    @property
    def usable(self) -> bool:
        return self.mode != "none" and not self.problems

    def to_json(self) -> dict[str, object]:
        return {"mode": self.mode, "config_dir": str(self.config_dir) if self.config_dir else None,
                "env_vars": list(self.env_vars), "problems": list(self.problems)}


def default_config_dir(environ: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    from ..registry import registry_home
    return registry_home() / "claude-provider"


def login_command(config_dir: Path) -> str:
    return f"CLAUDE_CONFIG_DIR={config_dir} claude auth login"


def audit_config_dir(path: Path) -> list[str]:
    """What would make a dedicated config dir unsafe or unlike plain Claude Code. Empty means usable."""
    problems: list[str] = []
    if not path.is_dir():
        return [f"no dedicated Claude login for repo-ai; run once: {login_command(path)}"]
    if path.is_symlink():
        return [f"{path} is a symlink; use a real directory owned by repo-ai"]
    home = Path.home().resolve()
    resolved = path.resolve()
    if resolved == home or resolved in home.parents or too_broad(resolved) or \
            any(resolved == home / d or (home / d) in resolved.parents for d in (".ssh", ".aws", ".gnupg", "Library")):
        return [f"{path} is not a dedicated directory (it is, or contains/sits in, a sensitive HOME location)"]
    if resolved == home / ".claude":
        return [f"{path} is your personal Claude config; repo-ai needs its own: {login_command(default_config_dir())}"]
    for sub in ("skills", "agents", "commands", "output-styles", "hooks", "rules"):
        d = path / sub
        if d.is_dir() and any(p.is_file() for p in d.rglob("*")):
            problems.append(f"{path}/{sub} is not empty; repo-ai's Claude login must carry no customisations")
    try:
        installed = json.loads((path / "plugins" / "installed_plugins.json").read_text("utf-8"))
    except (OSError, ValueError):
        installed = {}
    if isinstance(installed, dict) and installed.get("plugins"):
        problems.append(f"{path}/plugins has installed plugins; remove them from repo-ai's Claude login")
    if (path / "CLAUDE.md").exists():
        problems.append(f"{path}/CLAUDE.md exists; remove it from repo-ai's Claude login")
    for settings in (path / "settings.json", path / "settings.local.json"):
        if not settings.is_file():
            continue
        try:
            data = json.loads(settings.read_text("utf-8"))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            problems.append(f"{settings} is not a JSON object")
        else:
            for key in ("hooks", "enabledPlugins", "mcpServers", "permissions", "apiKeyHelper", "env",
                        "awsAuthRefresh", "awsCredentialExport", "statusLine"):
                if data.get(key):
                    problems.append(f"{settings} sets `{key}`; remove it from repo-ai's Claude login")
    return problems


def plan(environ: Mapping[str, str] | None = None) -> ClaudeAuthPlan:
    """Decide how a live run authenticates. Reads no credential values, only which variables are set."""
    environ = os.environ if environ is None else environ
    present = tuple(v for v in TOKEN_ENV_VARS if environ.get(v))
    if present:
        return ClaudeAuthPlan("token_env", None, present, ())
    cfg = default_config_dir(environ)
    problems = audit_config_dir(cfg)
    if not environ.get("USER"):
        problems.append("USER is not set; Claude Code finds its keychain login by account name")
    if not cfg.is_dir():
        return ClaudeAuthPlan("none", cfg, (), tuple(problems))
    return ClaudeAuthPlan("dedicated_config", cfg.resolve(), (), tuple(problems))


def missing_flags(help_text: str) -> list[str]:
    flags = set(re.findall(r"(--[a-z][\w-]*)", help_text))
    return [f for f in REQUIRED_FLAGS if f not in flags]


def _install_roots(executable: Path) -> list[Path]:
    """Directories the Claude CLI loads code from: the resolved binary's directory (a native install keeps each
    version there) or, for an npm install, the package directory."""
    exe = executable.resolve()
    roots = [exe.parent]
    if "node_modules" in exe.parts:
        for parent in exe.parents:
            if parent.name == "node_modules":
                break
            if (parent / "package.json").is_file():
                roots.append(parent)
                break
    return [r for r in roots if not too_broad(r)] or [exe]


def too_broad(path: Path) -> bool:
    """HOME itself, any ancestor of it, or a top-level HOME directory that holds unrelated app data."""
    home = Path.home().resolve()
    p = path.resolve()
    return p == home or p in home.parents or (p.parent == home and p.name in SENSITIVE_HOME_DIRS)


def seatbelt_rules(workspace: Path, scratch: Path, executable: Path | None, auth: ClaudeAuthPlan,
                   extra_read: list[Path] | None = None) -> tuple[str, str]:
    """(read rules, extra write rules) for macOS sandbox-exec. Everything under HOME is unreadable except what
    the CLI needs; the caller's ``(deny file-write*)`` plus these allows is the write boundary."""
    home = Path.home().resolve()
    q = json.dumps
    installed = _install_roots(executable) if executable is not None else []
    allow_read = [workspace.resolve(), scratch.resolve(), *installed, *(extra_read or [])]
    rules = [f"(deny file-read* (subpath {q(str(home))}))", f"(allow file-read* (literal {q(str(home))}))",
             f"(allow file-read-metadata (subpath {q(str(home))}))"]
    rules += [f"(allow file-read* (subpath {q(str(p))}))" for p in allow_read]
    writes: list[str] = []
    if auth.mode == "dedicated_config" and auth.config_dir is not None:
        cfg = auth.config_dir.resolve()
        keychains = home / "Library" / "Keychains"
        rules.append(f"(allow file-read* (subpath {q(str(cfg))}))")
        rules.append(f"(allow file-read* (literal {q(str(keychains))}))")
        rules += [f"(allow file-read* (literal {q(str(keychains / n))}))" for n in KEYCHAIN_FILES]
        writes.append(f"(allow file-write* (subpath {q(str(cfg))}))")
        # the CLI's own token refresh replaces the keychain database atomically via a sibling temp file
        kc = re.escape(str(keychains))
        writes.append(f"(allow file-write* (regex {q('^' + kc + '/(login|metadata)[.]keychain-db([.]sb-[^/]+)?$')}))")
        # later rules win in SBPL: customisation files stay read-only even inside the writable config dir
        for name in CUSTOMISATION_PATHS:
            target = q(str(cfg / name))
            writes.append(f"(deny file-write* (literal {target}))(deny file-write* (subpath {target}))")
    return "".join(rules), "".join(writes)


def invocation_flags(*, read_only: bool) -> list[str]:
    return ["--permission-mode", "acceptEdits", "--permission-prompts", "none", "--restricted", "--safe-mode",
            "--strict-mcp-config", "--disable-slash-commands", "--tools", READ_TOOLS if read_only else EDIT_TOOLS]


__all__ = ["CONFIG_DIR_ENV", "ClaudeAuthPlan", "EDIT_TOOLS", "READ_TOOLS", "REQUIRED_FLAGS", "TOKEN_ENV_VARS",
           "audit_config_dir", "default_config_dir", "invocation_flags", "login_command", "missing_flags", "plan",
           "seatbelt_rules"]
