"""Plugin Firewall: static vetting of what a Claude Code plugin repository *runs*.

`skills vet` inspects SKILL.md directories. A plugin keeps its most powerful
behaviour elsewhere, and all of it runs unsandboxed with the user's
permissions once the plugin is enabled:
- hooks (shell commands on lifecycle events; `http`, `prompt` and `agent` hooks);
- hooks modules (JavaScript inside the Claude Code process);
- MCP and LSP servers (spawned processes, or remote URLs);
- monitors (background commands);
- `bin/` (on the Bash tool's PATH);
- plugin and project settings (status lines, helpers, permission modes);
- marketplace entries (`command` sources, unpinned refs);
- npm lifecycle scripts (run on a manual `npm install`, not on the plugin path).

For every executable component this module:
1. resolves the command string (exec or shell form, `${CLAUDE_PLUGIN_ROOT}`);
2. maps the interpreter to a script *inside the repository*;
3. reads that script and up to two hops of local `require`/`import`/`source`;
4. applies the firewall's rules plus plugin-layer rules;
5. records as **dynamic-unknown** anything it cannot resolve statically: package
   runners (`npx`, `uvx`, `docker run`), computed paths, compiled or minified
   files, programs the plugin does not ship.

Nothing is executed, installed or enabled. A source is read through a
`Source` that never follows symlinks; GitHub blobs are checked against their
git blob SHA at a pinned commit.

Results keep seven dimensions apart (skill content, plugin configuration,
executable source, dynamic unknowns, source integrity, licence,
installation authorization). The verdict uses the firewall's vocabulary:
- `blocked`: any critical finding;
- `review`: any high finding, or anything dynamic-unknown;
- `eligible`: no known problem, which is *not* proof of safety.

A claim of trust in the content never raises a verdict; it is itself a
finding. repo-ai never installs or enables plugins, so authorization is
always `not-authorized`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import unicodedata
from types import SimpleNamespace
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .firewall import (_HIDDEN_CHARS, _INJECTION, _NEVER_DOWNGRADE, _RULES, COPYLEFT, MAX_FILE, PERMISSIVE,
                       SEVERITY_ORDER, Finding, _detect_license, _negated_before, line_contexts)
from .security import redact_text

SCHEMA = "repo-ai.plugin-vet/1"
MAX_FOLLOW_DEPTH = 2
MAX_FILES_PER_COMPONENT = 40
MAX_FILES_TOTAL = 2000
MAX_BIN_FILES = 60
MINIFIED_BYTES = 200_000
MAX_PLUGIN_ROOTS = 80

AUTO_RUN = {"hook", "hooks-module", "monitor", "mcp", "lsp", "status-line", "helper"}

# --------------------------------------------------------------------------
# sources: a local directory or a pinned GitHub tree, never following links
# --------------------------------------------------------------------------


class Source:
    """Read-only view of a repository. `kind()` is file | symlink | submodule
    | special | None; symlinks are reported, never followed."""

    label = ""
    integrity = "unverified"
    truncated = False

    def paths(self) -> list[str]:
        raise NotImplementedError

    def kind(self, path: str) -> str | None:
        raise NotImplementedError

    def link_target(self, path: str) -> str:
        return ""

    def read(self, path: str) -> bytes | None:
        raise NotImplementedError

    def size(self, path: str) -> int:
        return 0

    def executable(self, path: str) -> bool:
        return False

    def text(self, path: str) -> str | None:
        data = self.read(path)
        if data is None or b"\x00" in data[:8192]:
            return None
        return data.decode("utf-8", "replace")


class LocalSource(Source):
    def __init__(self, root: Path, label: str = ""):
        self.root = root
        self.label = label or f"local:{root.name}"
        self.integrity = "local-unverified"
        self._kinds: dict[str, str] = {}
        self._sizes: dict[str, int] = {}
        self._exec: set[str] = set()
        self._links: dict[str, str] = {}
        self.truncated = False
        count = 0
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules"}]
            for name in [*dirnames, *filenames]:
                full = Path(dirpath) / name
                rel = full.relative_to(root).as_posix()
                st = os.lstat(full)
                if stat.S_ISLNK(st.st_mode):
                    self._kinds[rel] = "symlink"
                    self._links[rel] = os.readlink(full)
                elif name in dirnames:
                    continue
                elif stat.S_ISREG(st.st_mode):
                    self._kinds[rel] = "file"
                    self._sizes[rel] = st.st_size
                    if st.st_mode & stat.S_IXUSR:
                        self._exec.add(rel)
                else:
                    self._kinds[rel] = "special"
                count += 1
                if count > 20_000:
                    self.truncated = True
                    return
            # a symlinked directory is listed, not descended into
            dirnames[:] = [d for d in dirnames if self._kinds.get(
                (Path(dirpath) / d).relative_to(root).as_posix()) != "symlink"]

    def paths(self) -> list[str]:
        return sorted(self._kinds)

    def kind(self, path: str) -> str | None:
        return self._kinds.get(path)

    def link_target(self, path: str) -> str:
        return self._links.get(path, "")

    def size(self, path: str) -> int:
        return self._sizes.get(path, 0)

    def executable(self, path: str) -> bool:
        return path in self._exec

    def read(self, path: str) -> bytes | None:
        if self._kinds.get(path) != "file":
            return None
        try:
            fd = os.open(str(self.root / path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
        except OSError:
            return None
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_FILE + 1)
        return None if len(data) > MAX_FILE else data


class GitHubSource(Source):
    """A repository tree at a pinned commit. Each blob read is checked against
    its git blob SHA-1; a mismatch is recorded and the content discarded."""

    def __init__(self, client, owner: str, repo: str, commit: str, tree: list[dict[str, Any]], under: str = ""):
        self.client, self.owner, self.repo, self.commit = client, owner, repo, commit
        self.prefix = under.strip("/") + "/" if under.strip("/") else ""
        self.label = f"github:{owner}/{repo}@{commit[:12]}" + (f"/{self.prefix.rstrip('/')}" if self.prefix else "")
        self.integrity = "verified-blob-sha"
        self.mismatches: list[str] = []
        self.errors: list[str] = []
        self._entries = {e["path"][len(self.prefix):]: e for e in tree
                         if e.get("type") in ("blob", "commit") and e.get("path", "").startswith(self.prefix)}
        self._cache: dict[str, bytes | None] = {}

    def paths(self) -> list[str]:
        return sorted(self._entries)

    def kind(self, path: str) -> str | None:
        e = self._entries.get(path)
        if e is None:
            return None
        mode = str(e.get("mode", "100644"))
        if mode == "120000":
            return "symlink"
        if e.get("type") == "commit" or mode == "160000":
            return "submodule"
        return "file"

    def size(self, path: str) -> int:
        return int((self._entries.get(path) or {}).get("size") or 0)

    def executable(self, path: str) -> bool:
        return str((self._entries.get(path) or {}).get("mode")) == "100755"

    def _fetch(self, path: str) -> bytes | None:
        import base64

        from .firewall import _from_tarball
        from .radar import RadarError
        e = self._entries[path]
        if int(e.get("size") or 0) > MAX_FILE:
            return None
        cand = SimpleNamespace(owner=self.owner, repo=self.repo, commit=self.commit)
        data = _from_tarball(self.client, cand, self.prefix + path) if self.kind(path) == "file" else None
        if data is None:
            try:
                blob = self.client.get("api.github.com",
                                       f"/repos/{self.owner}/{self.repo}/git/blobs/{e['sha']}", ttl=-1)
            except RadarError as exc:
                self.errors.append(f"{path}: {exc}")
                return None
            data = base64.b64decode(blob.get("content", ""))
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest() != e["sha"]:
            self.mismatches.append(path)
            self.integrity = "failed"
            return None
        return data

    def link_target(self, path: str) -> str:
        if self.kind(path) != "symlink":
            return ""
        if path not in self._cache:
            self._cache[path] = self._fetch(path)
        data = self._cache[path]
        return data.decode("utf-8", "replace") if data else ""

    def read(self, path: str) -> bytes | None:
        if self.kind(path) != "file":
            return None
        if path not in self._cache:
            self._cache[path] = self._fetch(path)
        return self._cache[path]


# --------------------------------------------------------------------------
# report model
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Component:
    kind: str          # hook | hooks-module | mcp | lsp | monitor | bin | settings | lifecycle |
    #                    marketplace | status-line | helper | installer | prompt-text
    name: str
    declared_in: str
    plugin: str = "."
    event: str = ""
    command: str = ""
    resolved: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(f.severity == "critical" for f in self.findings):
            return "blocked"
        if any(f.severity == "high" for f in self.findings) or self.unknown:
            return "review"
        return "eligible"

    @property
    def executable(self) -> bool:
        return self.kind not in {"settings", "prompt-text", "marketplace"} or bool(self.command)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "plugin": self.plugin, "declared_in": self.declared_in,
                "event": self.event, "command": self.command, "auto_runs": self.kind in AUTO_RUN,
                "resolved": self.resolved, "dynamic_unknown": self.unknown, "notes": self.notes,
                "verdict": self.verdict, "findings": [f.to_json() for f in self.findings]}


UNSUPPORTED_RULES = {"binary-file", "binary", "bundle-unreviewable", "minified-unreviewable", "listing-truncated",
                     "absolute-path", "backslash-path"}
_TEXT_EXT = (".md", ".mdx", ".markdown", ".txt", ".rst")


def _evidence_kind(c: Component, f: Finding) -> str:
    if f.rule in UNSUPPORTED_RULES:
        return "unsupported"
    if c.kind == "prompt-text" or f.file.lower().endswith(_TEXT_EXT):
        return "quoted"
    return "observed" if f.severity == "critical" else "risky"


@dataclass(slots=True)
class PluginReport:
    source: str
    integrity: str
    plugins: list[str] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)   # repository-level (structure, licence)
    license: str = ""
    skills: dict[str, Any] = field(default_factory=dict)
    files_read: int = 0

    @property
    def verdict(self) -> str:
        votes = [c.verdict for c in self.components]
        if any(f.severity == "critical" for f in self.findings) or "blocked" in votes \
                or self.integrity == "failed":
            return "blocked"
        if any(f.severity == "high" for f in self.findings) or "review" in votes:
            return "review"
        if self.components or self.plugins:  # experimental static inspection never approves a plugin
            return "review"
        if self.skills.get("verdict") in ("blocked", "review"):
            return str(self.skills["verdict"])
        return "eligible"

    def evidence(self) -> dict[str, Any]:
        """What kind of evidence the findings are, kept apart: something a component would do, a risk,
        text that only mentions or instructs, behaviour that could not be resolved, and formats the
        analyser cannot read. Counting is reporting only; the verdict is unchanged by it."""
        counts = {"observed": 0, "risky": 0, "quoted": 0, "unsupported": 0}
        for c in self.components:
            for f in c.findings:
                counts[_evidence_kind(c, f)] += 1
        counts["unsupported"] += sum(1 for f in self.findings if f.rule in UNSUPPORTED_RULES)
        return {**counts, "unresolved": sum(1 for c in self.components if c.unknown),
                "note": "observed: a component would do this; risky: a lesser risk in a component; quoted: "
                        "text (prompts, docs) that mentions or instructs it; unresolved: what runs could not "
                        "be determined; unsupported: content the analyser cannot read"}

    def dimensions(self) -> dict[str, Any]:
        execs = [c for c in self.components if c.executable]
        unresolved = [c for c in execs if c.unknown]
        config = [c for c in self.components if c.kind in {"settings", "marketplace"}]
        lic = self.license.upper()
        return {
            "skill_content": self.skills or {"status": "none", "skills": 0},
            "plugin_config": {"status": "inspected" if self.plugins or config else "none",
                              "plugins": len(self.plugins), "config_files": sorted(
                                  {c.declared_in for c in self.components})},
            "executable_source": {"status": "none" if not execs else (
                "partial" if unresolved else "inspected"), "components": len(execs),
                "resolved_files": sorted({p for c in execs for p in c.resolved}),
                "unresolved_components": len(unresolved)},
            "dynamic_unknown": [{"component": f"{c.kind}:{c.name}", "plugin": c.plugin, "reasons": c.unknown}
                                for c in self.components if c.unknown],
            "evidence": self.evidence(),
            "source_integrity": {"status": self.integrity},
            "license": {"spdx": self.license or "missing", "status": (
                "permissive" if lic in PERMISSIVE else "copyleft" if lic in COPYLEFT else
                "missing" if not lic else "other")},
            "authorization": {"status": "not-authorized",
                              "note": "repo-ai never installs or enables plugins; enabling one is your "
                                      "decision in Claude Code (/plugin)"},
        }

    def to_json(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "source": self.source, "verdict": self.verdict,
                "dimensions": self.dimensions(), "plugins": self.plugins,
                "components": [c.to_json() for c in self.components],
                "findings": [f.to_json() for f in self.findings], "files_read": self.files_read,
                "note": "static inspection only; nothing was installed or executed. A clean result means no "
                        "known problem, not proof of safety"}


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------
# (severity, kind, category, rule, pattern, applies-to) over resolved source and command strings
_SOURCE_RULES: list[tuple[str, str, str, str, re.Pattern[str]]] = [
    ("high", "confirmed", "exec", "model-respawn",
     re.compile(r"""["']claude["']\s*,\s*\[[^\]]*["'](-p|--print)["']|\bclaude\s+(-{1,2}[\w-]+(\s+[\w.:-]+)?\s+)*"""
                r"""(-p|--print)\b""")),
    ("high", "confirmed", "exec", "permission-auto-approve",
     re.compile(r"""["']?(behavior|permissionDecision|decision)["']?\s*:\s*["'](allow|approve)["']|"""
                r"""["']?setMode["']?\s*[:,(]\s*\{?[^\n]{0,40}(acceptEdits|bypassPermissions|dontAsk)""")),
    ("high", "suspected", "exec", "dynamic-code",
     re.compile(r"""(?<![\w.])eval\s*\(|\bnew\s+Function\s*\(|\bvm\.runIn\w*Context\s*\(|\bexec\s*\(\s*compile\(|"""
                r"""\bexec\s*\(\s*(requests|urllib|base64)""")),
    ("critical", "suspected", "exfiltration", "env-dump-to-network",
     re.compile(r"""(\bfetch\s*\(|requests\.(post|put)|urlopen\s*\(|https?\.request\s*\(|axios\.(post|put))"""
                r"""[^\n]{0,200}(process\.env\b(?![.\[])|os\.environ\b(?![.\[]))""")),
    ("medium", "confirmed", "exec", "writes-outside-project",
     re.compile(r"""(homedir\(\)|expanduser\(|\$HOME\b|\$\{HOME\}|["']~/)[^\n]{0,80}(write|appendFile|>>?|mkdir|"""
                r"""copyFile|rename)|(writeFileSync|writeFile|appendFileSync|open\()[^\n]{0,60}"""
                r"""(homedir\(\)|expanduser\(|\$HOME|~/)""")),
]
_ESCALATE_IN_CODE = {("obfuscation", "decode-and-run"), ("remote-exec", "xargs-shell"),
                     ("remote-exec", "executes-asset"), ("remote-exec", "process-substitution-into-shell")}
_NETWORK_SRC = re.compile(
    r"""\bfetch\s*\(|\bhttps?\.(request|get)\s*\(|\brequests\.(get|post|put|patch|delete)\s*\(|\burlopen\s*\(|"""
    r"""\burllib\.request\b|\baxios(\.\w+)?\s*\(|\bnet\.connect\s*\(|\bnew\s+WebSocket\s*\(|\bXMLHttpRequest\b|"""
    r"""\b(curl|wget)\s+[-"'$hH]|\bInvoke-WebRequest\b|\bhttpx\.\w+\s*\(""")
_URL_HOST = re.compile(r"https?://([A-Za-z0-9.-]+)")
_TRANSCRIPT = re.compile(r"transcript_path|transcriptPath|\.jsonl\b[^\n]{0,40}transcript")
_SPAWN = re.compile(r"""\bchild_process\b|\bspawn(Sync)?\s*\(|\bexec(Sync|File|FileSync)?\s*\(|\bsubprocess\.|"""
                    r"""\bos\.system\s*\(|\bPopen\s*\(""")
_FILE_WRITE = re.compile(r"""--write\b|\bwriteFileSync\s*\(|\bfs\.writeFile\s*\(|\.write_text\s*\(|"""
                         r"""\bopen\([^)\n]*["'][wa]\+?["']""")
_ENV_FILE_WRITE = re.compile(r""">>?\s*["']?\$\{?CLAUDE_ENV_FILE|\btee\s+(-a\s+)?["']?\$\{?CLAUDE_ENV_FILE|"""
                             r"""(appendFileSync|appendFile|writeFileSync|writeFile)\s*\([^)\n]{0,40}CLAUDE_ENV_FILE|"""
                             r"""open\([^)\n]{0,60}CLAUDE_ENV_FILE[^)\n]{0,40}["']a""")
_EXPORT = re.compile(r"\bexport\s+([A-Za-z_][A-Za-z0-9_]*)=")
_HIJACK_ENV = {"NODE_OPTIONS", "PYTHONPATH", "PYTHONSTARTUP", "BASH_ENV", "ENV", "PROMPT_COMMAND", "PERL5OPT",
               "RUBYOPT", "ANTHROPIC_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "GIT_SSH_COMMAND",
               "GIT_EXEC_PATH", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE"}
# instructions a hook or command hands the model to act without the user
_CONTEXT_INJECTION = re.compile(
    r"(?i)\b(do\s+not|don't|never)\s+ask\s+(the\s+)?user\s+(for\s+)?(confirmation|permission|approval)\b|"
    r"\bjust\s+do\s+it\b|\byou\s+must\s+(read|run|execute|follow)\b[^.\n]{0,80}\b(instructions|commands?)\b")
_SETTINGS_CHANGE = re.compile(
    r"(?i)\b(writes?|sets?|adds?|installs?|updates?|configures?)\b[^.\n]{0,40}[`\"']?"
    r"(statusLine|subagentStatusLine|apiKeyHelper|otelHeadersHelper)\b|"
    r"\b(writes?|sets?|adds?|installs?|updates?|configures?|edit|merge)\b[^.\n]{0,60}"
    r"[`\"']?(statusLine|hooks|permissions|apiKeyHelper|enabledPlugins)[`\"']?[^.\n]{0,60}settings(\.local)?\.json|"
    r"\bsettings(\.local)?\.json\b[^.\n]{0,60}\b(statusLine|hooks|permissions\.allow|apiKeyHelper)\b")
_FALSE_TRUST = re.compile(
    r"(?i)\b(pre-?approved|verified|certified|endorsed|trusted|whitelisted|allow-?listed|audited)\s+(by|from)\s+"
    r"(anthropic|claude|openai|github|vercel|microsoft|google)\b|"
    r"\b(this|the)\s+(skill|plugin|hook|server|tool|command)\s+(is|has\s+been)\s+(safe|trusted|verified|"
    r"pre-?approved|audited)\b[^.\n]{0,60}\b(skip|no\s+need|without|bypass)\b|"
    r"\bskip\s+(the\s+)?(security\s+)?(review|vetting|scan)\b|"
    r"\b(do\s+not|don't|no\s+need\s+to)\s+(review|vet|scan|inspect)\s+(this|the)\s+(skill|plugin|hook|code)\b")
# local references a script makes to other files in the repository
_LOCAL_REF = re.compile(
    r"""\brequire\s*\(\s*["'](\.{1,2}/[^"'\s]+)["']\s*\)|\b(?:import|export)\s+[^;"']{0,600}?\bfrom\s+["'](\.{1,2}/[^"'\s]+)["']|"""
    r"""\bimport\s*\(\s*["'](\.{1,2}/[^"'\s]+)["']\s*\)|\bimport\s+["'](\.{1,2}/[^"'\s]+)["']|"""
    r"""__dirname\s*,\s*["']([^"'\s]+\.(?:c|m)?[jt]s)["']|"""
    r"""\$\{?CLAUDE_PLUGIN_ROOT\}?/([\w./@+-]+)|"""
    r"""(?:^|[\s;&|(])(?:source|\.|bash|sh|zsh|node|python3?|bun)\s+["']?((?:\./|\.\./)[\w./@+-]+)""", re.M)
_COMPUTED_REQUIRE = re.compile(r"""\b(require|import)\s*\(\s*(?!["'])(?!path\.(join|resolve)\(\s*__dirname\s*,\s*["'][^"']+["']\s*\)\s*\))[\w.$]|"""
                               r"""\b(require|import)\s*\(\s*["'][^"']*["']\s*\+""")
_LITERAL_SCRIPT = re.compile(r"""["']((?:[\w@+-]+/)*[\w@+.-]+\.(?:c|m)?[jt]s)["']""")

# interpreter options that take a value: the value is not the script
_VALUE_FLAGS: dict[str, frozenset[str]] = {
    "python": frozenset({"-W", "-X", "-Q"}), "py": frozenset({"-W", "-X"}),
    "node": frozenset({"--input-type", "--title", "--env-file", "--conditions", "-C"}),
    "bash": frozenset({"-o", "-O", "+o", "+O"}), "sh": frozenset({"-o", "+o"}), "zsh": frozenset({"-o", "+o"}),
    "pwsh": frozenset({"-executionpolicy", "-ep", "-ex", "-windowstyle", "-w", "-workingdirectory", "-wd",
                       "-configurationname", "-outputformat", "-of", "-inputformat", "-if", "-version", "-v",
                       "-settingsfile", "-psconsolefile"}),
}
_VALUE_FLAGS["powershell"] = _VALUE_FLAGS["pwsh"]
_PRELOAD_FLAGS = frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader"})

INTERPRETERS = re.compile(r"^(node|nodejs|bun|deno|tsx|ts-node|python[0-9.]*|py|bash|sh|zsh|dash|ksh|fish|"
                          r"ruby|perl|php|pwsh|powershell|osascript|lua)(\.exe)?$")
RUNNERS = re.compile(r"^(npx|bunx|pnpx|uvx|pipx|docker|podman|nerdctl)(\.exe|\.cmd)?$")
RUNNER_SUBCOMMANDS = {("pnpm", "dlx"), ("yarn", "dlx"), ("npm", "exec"), ("bun", "x"), ("uv", "tool"),
                      ("pipx", "run")}
SHELL_BUILTINS = {"echo", "printf", "cat", "true", "false", "test", "[", "exit", "cd", "pwd", "sleep", "date",
                  "mkdir", "touch", "tee", "grep", "egrep", "sed", "awk", "head", "tail", "sort", "uniq", "wc",
                  "cut", "tr", "basename", "dirname", "realpath", "command", "which", "type", "read", "set",
                  "jq", "git", "export", "exec", "env", "if", "then", "else", "fi", "for", "do", "done",
                  "while", "case", "esac", "[[", "]]", "return", "local", "shift", ":", "trap", "wait",
                  "ls", "find", "stat", "rm", "cp", "mv", "ln", "chmod", "xargs", "timeout", "nohup"}
NOTIFIERS = {"notify-send", "terminal-notifier", "afplay", "paplay", "aplay", "say", "osascript", "powershell",
             "pwsh", "tput"}
# formatters and linters run on files; they do not run repository code
DEV_TOOLS = {"prettier", "eslint", "biome", "black", "ruff", "isort", "gofmt", "goimports", "rustfmt", "tsc",
             "mypy", "pyright", "gh", "swiftformat", "clang-format", "shellcheck", "shfmt"}
# these run code named by the repository (a package.json script, a Makefile target, a test suite) or
# fetch packages at runtime
PROJECT_RUNNERS = {"npm", "pnpm", "yarn", "bun", "make", "gmake", "go", "cargo", "pytest", "tox", "nox", "uv",
                   "pip", "pip3", "poetry", "pipenv", "deno", "gradle", "gradlew", "mvn", "rake", "just", "task"}
WRAPPERS = {"timeout", "nice", "nohup", "stdbuf", "ionice", "time", "env", "command", "exec", "setsid", "chrt",
            "caffeinate", "unbuffer", "flock", "xargs", "find", "watch", "script", "busybox"}
LANGUAGE_SERVERS = {"pyright-langserver", "basedpyright-langserver", "pylsp", "typescript-language-server",
                    "vtsls", "gopls", "rust-analyzer", "clangd", "jdtls", "sourcekit-lsp", "lua-language-server",
                    "kotlin-language-server", "omnisharp", "csharp-ls", "intelephense", "solargraph",
                    "ruby-lsp", "elixir-ls", "zls", "metals", "haskell-language-server-wrapper", "bash-language-server",
                    "yaml-language-server", "vscode-json-language-server", "terraform-ls"}
_SECRET_KEY = re.compile(r"(?i)(authorization|token|secret|password|passwd|api[-_]?key|access[-_]?key|cookie|"
                         r"session|bearer|credential|private[-_]?key)")
_SECRET_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}|\b(sk|pk|rk)-[A-Za-z0-9_-]{12,}|\bgh[pousr]_[A-Za-z0-9]{20,}|"
                           r"\bxox[abpr]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}")
_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+([-+][\w.]+)?$")
# letters that render like ASCII (a small, explicit confusables table)
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "α": "a", "ο": "o", "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "ϲ": "c", "ѡ": "w",
    "｜": "|", "∣": "|", "ǀ": "|", "−": "-", "‐": "-", "–": "-", "／": "/"})


def _data_not_command(rule: str, line: str, hit: re.Match[str]) -> bool:
    """Two inherited rules read code too literally:
    - `pipe-to-shell` fires on `| node script.js` and `| perl -pe '…'` (stdin is data
      there) and on regex alternations such as `(?:bash|zsh|sh)`;
    - `credential-files` fires on a bare `id_rsa` inside a list of names to *detect*.
    Path forms (`~/.ssh/id_rsa`, `.aws/credentials`) and `| sh` itself stay at full severity."""
    if rule == "pipe-to-shell":
        after = line[hit.end():hit.end() + 40]
        bar = hit.group(0).find("|")
        tight = bar > 0 and not hit.group(0)[bar - 1].isspace() and not hit.group(0)[bar + 1:bar + 2].isspace()
        if re.search(r"\(\?:[^)]*$", line[:hit.end()]) or (tight and re.match(r"[)?'\"\]\\/]", after)):
            return True  # `(?:bash|zsh|sh)`, `"zsh|sh"`: an alternation, not a pipe
        nxt = after.strip().split()[0] if after.strip() else ""
        interp = hit.group(0).split("|")[-1].strip().split("/")[-1]
        if interp.startswith(("node", "perl", "ruby", "python")) and nxt and nxt not in ("-", "-s", "-i", "-x"):
            return not nxt.startswith("-") or nxt in ("-c", "-e", "-pe", "-ne", "-le", "-p", "-n", "-0777")
        return False
    if rule == "credential-files":
        token = hit.group(0)
        if re.search(r"[~/$]|\.aws/credentials", token):
            return False
        return bool(re.search(r"\|\s*" + re.escape(token) + r"|" + re.escape(token) + r"\s*\|", line)
                    or re.fullmatch(r"\s*/[^/\n]*" + re.escape(token) + r"[^/\n]*/[a-z]*\s*,?\s*", line)
                    # a line that is only a list of string literals: names to detect, not a path to read
                    or re.fullmatch(r"""\s*(\w+\s*=\s*)?[\[({]?\s*(["'][\w.@-]+["']\s*,\s*)*["'][\w.@-]+["']\s*,?\s*[\])}]?\s*,?\s*""",
                                    line))
    return False


def _line_kinds(path: str, text: str) -> list[str]:
    """`code`, `comment` or `string` per line of an executable file. A block
    comment that closes mid-line is code after the `*/`; lines inside a
    Python triple-quoted string or a JS template literal are string data."""
    kinds = line_contexts(path, text)
    lines = text.splitlines()
    ext = PurePosixPath(path).suffix.lower()
    quote = ""
    for i, line in enumerate(lines):
        if i >= len(kinds):
            break
        if kinds[i] == "comment" and "*/" in line and line.split("*/", 1)[1].strip():
            kinds[i] = "code"
        if ext in (".py", ".pyi"):
            if quote:
                kinds[i] = "string"
                if line.count(quote) % 2 == 1:
                    quote = ""
                continue
            for q in ('"""', "\'\'\'"):
                if line.count(q) % 2 == 1:
                    quote = q
                    break
        elif ext in (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"):
            ticks = line.count("`") - line.count("\\`")
            if quote:
                kinds[i] = "string"
                if ticks % 2 == 1:
                    quote = ""
            elif ticks % 2 == 1:
                quote = "`"
    return kinds


def _unwrap(seg: list[str]) -> list[str] | None:
    """The command a wrapper runs: `timeout 5 x`, `nice -n 5 x`, `env -i A=1 x`,
    `xargs -n1 x`, `find . -exec x {} ;`. None when `seg` is not a wrapper."""
    name = PurePosixPath(seg[0]).name
    if name not in WRAPPERS:
        return None
    rest = seg[1:]
    if name == "find":
        for i, tok in enumerate(rest):
            if tok in ("-exec", "-execdir", "-ok", "-okdir"):
                cmd = rest[i + 1:]
                end = next((j for j, t in enumerate(cmd) if t in (";", "+", "\\;")), len(cmd))
                return cmd[:end]
        return []
    takes_value = {"timeout": {"-s", "--signal", "-k", "--kill-after"}, "nice": {"-n", "--adjustment"},
                   "stdbuf": {"-i", "-o", "-e"}, "ionice": {"-c", "-n", "-p"}, "env": {"-u", "--unset", "-C", "-S"},
                   "xargs": {"-n", "-P", "-I", "-L", "-s", "-d", "-E", "-a"}, "flock": {"-w", "-E"},
                   "chrt": set(), "watch": {"-n", "-d"}}.get(name, set())
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in takes_value:
            i += 2
        elif tok.startswith("-") and tok != "-":
            i += 1
        elif name == "env" and "=" in tok:
            i += 1
        else:
            break
    rest = rest[i:]
    if name in ("timeout", "chrt") and rest and re.fullmatch(r"[\d.]+[smhd]?", rest[0]):
        rest = rest[1:]
    if name == "flock" and rest:
        rest = rest[1:]
    if name == "busybox" and rest:
        return rest
    return rest


def _substitutions(command: str) -> tuple[str, list[str]]:
    """Replace each top-level `$(...)` and backtick span with a placeholder;
    return the inner commands."""
    out, inner, i = [], [], 0
    while i < len(command):
        if command[i] == "`":
            j = command.find("`", i + 1)
            j = len(command) if j < 0 else j
            inner.append(command[i + 1:j])
            out.append("__SUBST__")
            i = j + 1
        elif command.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(command) and depth:
                depth += {"(": 1, ")": -1}.get(command[j], 0)
                j += 1
            inner.append(command[i + 2:j - 1])
            out.append("__SUBST__")
            i = j
        else:
            out.append(command[i])
            i += 1
    return "".join(out), inner


def fold(text: str) -> str:
    """NFKC plus the confusables table, with invisible characters removed."""
    return _HIDDEN_CHARS.sub("", unicodedata.normalize("NFKC", text).translate(_CONFUSABLES))


def _snip(text: str, limit: int = 140) -> str:
    return redact_text(" ".join(text.split()))[:limit]


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
class _Analyzer:
    def __init__(self, source: Source):
        self.src = source
        self.report = PluginReport(source.label, source.integrity)
        self.read_count = 0
        self._inspected: dict[str, list[Finding]] = {}
        self._unresolved: list[str] = []
        self._script_meta: dict[str, dict[str, Any]] = {}

    # ---------------------------------------------------------------- paths
    def _norm(self, rel: str, base: str = "") -> tuple[str | None, str]:
        """Normalise a path inside the repository: (path | None, problem)."""
        if "\\" in rel:
            return None, "backslash"
        if rel.startswith("/"):
            return None, "absolute"
        parts: list[str] = [p for p in PurePosixPath(base).parts if p not in ("", ".")] if base else []
        for part in PurePosixPath(rel).parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    return None, "escape"
                parts.pop()
            else:
                parts.append(part)
        return "/".join(parts), ""

    def _resolve_link(self, path: str, comp: Component, hops: int = 0) -> str | None:
        """Follow a symlink only while its target stays inside the repository."""
        kind = self.src.kind(path)
        if kind != "symlink":
            return path if kind == "file" else None
        target = self.src.link_target(path)
        norm, problem = self._norm(target, str(PurePosixPath(path).parent)) if target else (None, "empty")
        if norm is None or hops > 4:
            comp.findings.append(Finding("critical", "confirmed", "artifact", "symlink-escape", path, 0,
                                         f"symbolic link -> {target[:120]} leaves the repository"))
            return None
        comp.findings.append(Finding("info", "confirmed", "artifact", "symlink-internal", path, 0,
                                     f"symbolic link -> {norm} (inside the repository)"))
        return self._resolve_link(norm, comp, hops + 1)

    def _json(self, path: str, comp_findings: list[Finding]) -> Any:
        text = self.src.text(path)
        if text is None:
            if self.src.kind(path) == "file":
                comp_findings.append(Finding("high", "unknown", "config", "not-inspected", path, 0,
                                             "configuration file too large or unreadable: not analysed"))
            return None
        self.read_count += 1
        try:
            return json.loads(text)
        except ValueError as exc:
            comp_findings.append(Finding("high", "confirmed", "config", "invalid-json", path, 0,
                                         f"not valid JSON ({str(exc)[:60]}); Claude Code may reject or "
                                         "partially load it, and it was not analysed"))
            return None

    # ---------------------------------------------------------- text rules
    def _text_findings(self, path: str, text: str, *, command: bool = False, line_offset: int = 0,
                       all_code: bool = False) -> list[Finding]:
        out: list[Finding] = []
        if _HIDDEN_CHARS.search(text[1:] if text.startswith("\ufeff") else text):  # one leading BOM is encoding
            out.append(Finding("high", "confirmed", "obfuscation", "hidden-unicode", path, 0,
                               "zero-width or bidirectional control characters"))
        # executable files: every line counts, but comments and string data count one level lower (a block
        # comment can end mid-line, and a `.js` file can be run by bash, so nothing is skipped)
        contexts = ["code"] * len(text.splitlines()) if command else (
            _line_kinds(path, text) if all_code else line_contexts(path, text))
        raw = text.splitlines()
        for i, line in enumerate(raw):
            if not all_code and i < len(contexts) and contexts[i] == "comment":
                continue
            lineno = i + 1 + line_offset
            folded = fold(line)
            ctx = contexts[i] if i < len(contexts) else "code"
            for severity, kind, category, rule, pattern in _RULES:
                hit = pattern.search(line)
                if hit is not None:
                    if ctx in ("comment", "string"):
                        severity = {"critical": "high", "high": "medium", "medium": "low"}.get(severity, "info")
                        kind = "suspected"
                    elif ctx == "code" and not command and _data_not_command(rule, line, hit):
                        severity, kind = "low", "suspected"  # a pattern or a string, not something that runs
                    elif ctx in ("prose", "inline") and _negated_before(line, hit.start(),
                                                                      strict=category in _NEVER_DOWNGRADE):
                        severity, kind = "info", "suspected"  # same rule as the skill firewall
                    elif ctx == "prose" and category not in _NEVER_DOWNGRADE:
                        severity = {"critical": "high", "high": "medium", "medium": "low"}.get(severity, "info")
                    out.append(Finding(severity, kind, category, rule, path, lineno, _snip(line)))
                elif folded != line and category in _NEVER_DOWNGRADE and pattern.search(folded):
                    out.append(Finding("critical", "confirmed", "obfuscation", "homoglyph-command", path, lineno,
                                       f"look-alike characters hide `{rule}`: {_snip(folded)}"))
            for severity, kind, category, rule, pattern in _SOURCE_RULES:
                if pattern.search(line):
                    if ctx in ("comment", "string"):
                        severity = {"critical": "high", "high": "medium", "medium": "low"}.get(severity, "info")
                    out.append(Finding(severity, kind, category, rule, path, lineno, _snip(line)))
            inj = _INJECTION.search(line) or _CONTEXT_INJECTION.search(line)
            if inj and not (ctx in ("prose", "inline") and _negated_before(line, inj.start())):
                out.append(Finding("high", "confirmed", "prompt-injection", "injection-phrase", path, lineno,
                                   _snip(line)))
            if _FALSE_TRUST.search(line):
                out.append(Finding("high", "confirmed", "provenance", "false-trust-claim", path, lineno,
                                   "claims to be trusted or pre-approved (a claim grants nothing): " + _snip(line)))
            if _ENV_FILE_WRITE.search(line):
                names = set(_EXPORT.findall(line))
                if names and names <= {"PATH"}:
                    out.append(Finding("high", "confirmed", "exec", "env-file-path", path, lineno,
                                       "changes PATH for every later Bash command (CLAUDE_ENV_FILE), so it can "
                                       "shadow the commands Claude runs"))
                else:
                    hijack = names & _HIJACK_ENV or any(n.startswith(("DYLD_", "LD_")) for n in names)
                    out.append(Finding("critical" if hijack else "high", "confirmed", "exec", "env-file-injection",
                                       path, lineno, "writes environment variables into every later Bash command: "
                                       + ", ".join(sorted(names))[:80]))
        return out

    def _script_signals(self, path: str, text: str) -> dict[str, Any]:
        lines = text.splitlines() or [""]
        longest = max(len(x) for x in lines)
        return {"network": bool(_NETWORK_SRC.search(text)),
                "hosts": sorted({h.lower() for h in _URL_HOST.findall(text)})[:10],
                "transcript": bool(_TRANSCRIPT.search(text)),
                "spawns": bool(_SPAWN.search(text)), "writes": bool(_FILE_WRITE.search(text)),
                "minified": len(text) > MINIFIED_BYTES or (len(text) > 20_000 and (
                    longest > 5_000 or len(text) / len(lines) > 400)),
                "computed_require": bool(_COMPUTED_REQUIRE.search(text))}

    # --------------------------------------------------------- scripts
    def inspect_script(self, path: str, comp: Component, depth: int = 0) -> None:
        """Read one in-repository file and the local files it references."""
        real = self._resolve_link(path, comp)
        if real is None:
            if self.src.kind(path) is None:
                comp.unknown.append(f"`{path}` is not in the repository")
            return
        if real in comp.resolved:
            return
        if len(comp.resolved) >= MAX_FILES_PER_COMPONENT or self.read_count >= MAX_FILES_TOTAL:
            comp.unknown.append(f"stopped before `{real}` (file limit)")
            return
        comp.resolved.append(real)
        if real in self._inspected:
            comp.findings.extend(self._inspected[real])
            meta = self._script_meta.get(real, {})
        else:
            data = self.src.read(real)
            self.read_count += 1
            found: list[Finding] = []
            meta = {}
            if data is None:
                comp.unknown.append(f"`{real}` could not be read (too large or unavailable)")
            elif data[:4] in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe") \
                    or data[:2] == b"MZ":
                found.append(Finding("high", "unknown", "binary", "compiled-executable", real, 0,
                                     "compiled executable: its behaviour cannot be reviewed"))
                meta = {"unknown": "compiled executable"}
            elif b"\x00" in data[:8192]:
                found.append(Finding("high", "unknown", "binary", "binary-file", real, 0, "binary, not inspected"))
                meta = {"unknown": "binary file"}
            else:
                text = data.decode("utf-8", "replace")
                found = self._text_findings(real, text, all_code=not real.endswith((".md", ".txt")))
                meta = self._script_signals(real, text)
                meta["refs"] = self._local_refs(real, text)
                if meta["minified"]:
                    found.append(Finding("high", "unknown", "exec", "minified-unreviewable", real, 0,
                                         f"{len(data):,} bytes of bundled or minified code: not reviewable"))
                    meta["unknown"] = "minified or bundled code"
                elif meta["network"] and any(f.rule == "dynamic-code" and f.severity == "high" for f in found):
                    found.append(Finding("critical", "suspected", "remote-exec", "fetch-and-eval", real, 0,
                                         "downloads and evaluates code at runtime"))
                if meta["network"]:
                    hosts = ", ".join(meta["hosts"]) or "a computed address"
                    found.append(Finding("high", "confirmed", "network", "network-in-source", real, 0,
                                         f"makes network requests ({hosts})"
                                         + ("; it also reads the session transcript" if meta["transcript"] else "")))
                if meta["transcript"] and any(f.rule == "model-respawn" for f in found):
                    found.append(Finding("high", "confirmed", "exec", "model-respawn-transcript", real, 0,
                                         "sends the session transcript to another model run (hidden spend)"))
                if meta["writes"]:
                    found.append(Finding("low", "confirmed", "exec", "file-rewrite", real, 0, "writes or rewrites files"))
                if meta["spawns"]:
                    found.append(Finding("info", "confirmed", "exec", "spawns-processes", real, 0,
                                         "starts other processes"))
            for f in found:  # code that runs on its own, not instructions a model may decline
                if (f.category, f.rule) in _ESCALATE_IN_CODE and f.severity == "high":
                    f.severity = "critical"
            self._inspected[real] = found
            self._script_meta[real] = meta
            comp.findings.extend(found)
        if meta.get("unknown"):
            comp.unknown.append(f"`{real}`: {meta['unknown']}")
        if self._unresolved:
            comp.unknown.extend(self._unresolved)
            self._unresolved = []
        if depth >= MAX_FOLLOW_DEPTH:
            more = [r for r in meta.get("refs", []) if r not in comp.resolved]
            if more:
                comp.unknown.append(f"`{real}` loads {len(more)} more file(s) beyond the follow depth "
                                    f"({MAX_FOLLOW_DEPTH} hops), not inspected")
            return
        for ref in meta.get("refs", []):
            self.inspect_script(ref, comp, depth + 1)
        if meta.get("computed_require"):
            comp.unknown.append(f"`{real}` loads a module from a computed path")

    def _local_refs(self, path: str, text: str) -> list[str]:
        base = str(PurePosixPath(path).parent)
        out: list[str] = []
        for m in _LOCAL_REF.finditer(text):
            raw = next(g for g in m.groups() if g)
            rel_base = base if not m.group(6) else self._plugin_root_of(path)
            norm, _ = self._norm(raw, rel_base)
            if norm is None:
                continue
            hit = self._with_ext(norm)
            if hit and hit != path and hit not in out:
                out.append(hit)
        if path.endswith(".py"):
            for m in re.finditer(r"(?m)^\s*(?:from\s+(\.*[\w.]*)\s+import\s+([\w, ]+)|import\s+([\w., ]+))", text):
                mods = [m.group(1)] if m.group(1) else [x.strip().split(" ")[0] for x in (m.group(3) or "").split(",")]
                if m.group(1) is not None and set(m.group(1)) <= {"."}:
                    mods = [m.group(1) + x.strip() for x in m.group(2).split(",")]
                for mod in mods:
                    dots = len(mod) - len(mod.lstrip("."))
                    rel = mod.lstrip(".").replace(".", "/")
                    here = PurePosixPath(base)
                    for _ in range(max(dots - 1, 0)):
                        here = here.parent
                    for cand in (f"{here}/{rel}.py", f"{here}/{rel}/__init__.py"):
                        norm, _ = self._norm(cand.lstrip("./") if str(here) == "." else cand)
                        if norm and self.src.kind(norm) == "file" and norm != path and norm not in out:
                            out.append(norm)
        if path.endswith((".sh", ".bash", ".zsh")) or text.startswith("#!") and "sh" in text[:40]:
            for m in re.finditer(r"""(?m)(?:^|[\s;&|(])(?:source|\.)\s+["']?\$\{?\w+\}?/([\w./@+-]+)""", text):
                norm, _ = self._norm(m.group(1), base)
                hit = self._with_ext(norm) if norm else None
                if hit and hit not in out:
                    out.append(hit)  # the `DIR=$(dirname "$0")` idiom: resolved next to the script
                elif not hit:
                    self._unresolved.append(f"`{path}` sources `{m.group(1)}` through a variable")
        # string literals naming an existing script (bootstraps that compute a root)
        if not out and _COMPUTED_REQUIRE.search(text):
            for lit in _LITERAL_SCRIPT.findall(text):
                for cand in (lit, *(f"{r}/{lit}" if r != "." else lit for r in self.report.plugins)):
                    norm, _ = self._norm(cand)
                    hit = self._with_ext(norm) if norm else None
                    if hit and hit not in out:
                        out.append(hit)
        return out[:MAX_FILES_PER_COMPONENT]

    def _with_ext(self, norm: str) -> str | None:
        for cand in (norm, norm + ".js", norm + ".mjs", norm + ".cjs", norm + ".ts", norm + ".py", norm + ".sh",
                     norm + "/index.js", norm + "/index.mjs", norm + "/index.ts"):
            if self.src.kind(cand) in ("file", "symlink"):
                return cand
        return None

    def _plugin_root_of(self, path: str) -> str:
        best = "."
        for root in self.report.plugins:
            if root == "." or path.startswith(root + "/"):
                if root != "." and (best == "." or len(root) > len(best)):
                    best = root
        return "" if best == "." else best

    # --------------------------------------------------------- commands
    def inspect_command(self, comp: Component, command: str, args: list[str] | None, root: str) -> None:
        """A hook/monitor/MCP/LSP/helper command: text rules on the command,
        then resolve what it runs."""
        display = command + (" " + " ".join(args) if args else "")
        comp.command = _snip(display, 300)
        if args is None and re.search(r"(^|\s)\.{0,2}\\[\w.-]|[\w.-]\\[\w.-]+\.(cmd|bat|ps1|exe|sh|js)\b", command):
            comp.findings.append(Finding("medium", "confirmed", "config", "backslash-path", comp.declared_in, 0,
                                         "command uses a Windows path (loaded only on Windows)"))
            comp.unknown.append("Windows path: not resolved")
        comp.findings.extend(self._text_findings(comp.declared_in, display, command=True))
        if any(ord(ch) > 127 for ch in display) and not _HIDDEN_CHARS.search(display):
            comp.findings.append(Finding("medium", "confirmed", "obfuscation", "non-ascii-command",
                                         comp.declared_in, 0, "non-ASCII characters in a command"))
        segments: list[list[str]] = []
        if args is not None:  # exec form: no shell
            segments = [[command, *args]]
        else:
            command, inner = _substitutions(command)
            for sub in inner[:6]:
                self.inspect_command(comp, sub, None, root)
            comp.command = _snip(display, 300)
            for physical in fold(command).replace("\r", "\n").split("\n"):
                try:
                    lexer = shlex.shlex(physical, posix=True, punctuation_chars=";&|()<>")
                    lexer.whitespace_split = True
                    lexer.commenters = ""  # bash: `#` starts a comment only at the start of a word
                    tokens = list(lexer)
                except ValueError:
                    comp.unknown.append("the command cannot be parsed")
                    return
                cur: list[str] = []
                redirect = False
                for tok in tokens:
                    if tok.startswith("#"):
                        break
                    if redirect:  # `2>/dev/null`, `> out.log`: a file name, not a program
                        redirect = False
                        if not (tok and set(tok) <= set(";&|()<>")):
                            continue
                    if tok and set(tok) <= set(";&|()<>"):
                        if set(tok) & set("<>") and not set(tok) & set(";|()"):
                            redirect = True
                            if cur and cur[-1].isdigit():
                                cur.pop()  # the file descriptor in `2>`
                            continue
                        if cur:
                            segments.append(cur)
                        cur = []
                    else:
                        cur.append(tok)
                if cur:
                    segments.append(cur)
        for seg in segments[:12]:
            self._segment(comp, seg, root)

    def _expand(self, token: str, root: str) -> tuple[str, bool]:
        """Expand plugin variables; (value, dynamic)."""
        prefix = (root + "/") if root not in ("", ".") else ""
        value = re.sub(r"\$\{CLAUDE_PLUGIN_ROOT(:-[^}]*)?\}/?|\$CLAUDE_PLUGIN_ROOT/?", prefix, token)
        value = re.sub(r"\$\{CLAUDE_PROJECT_DIR\}/?|\$CLAUDE_PROJECT_DIR/?", "<project>/", value)
        dynamic = bool(re.search(r"\$\{?[A-Za-z_]|\$\(|`", value)) or "<project>/" in value
        return value, dynamic

    def _segment(self, comp: Component, seg: list[str], root: str, depth: int = 0) -> None:
        assigns: dict[str, str] = {}
        while seg and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[0]) or seg[0] in {"then", "do", "else", "if",
                                                                                    "!", "{", "}"}):
            if "=" in seg[0]:
                k, _, v = seg[0].partition("=")
                assigns[k] = v
            seg = seg[1:]
        if assigns:
            self._env_hijack(comp, assigns, root, "an inline assignment")
        if not seg:
            return
        inner = _unwrap(seg)
        if inner is not None:  # timeout, nice, nohup, env, xargs, find -exec … run the rest
            if depth < 4:
                self._segment(comp, inner, root, depth + 1)
            return
        if PurePosixPath(seg[0]).name in ("sudo", "doas", "pkexec"):
            comp.findings.append(Finding("high", "confirmed", "permission-escalation", "sudo-in-hook", comp.declared_in,
                                         0, f"runs `{seg[0]}`: asks for elevated privileges"))
            if depth < 4:
                self._segment(comp, [a for a in seg[1:] if not a.startswith("-")], root, depth + 1)
            return
        prog_raw = seg[0]
        prog, dynamic = self._expand(prog_raw, root)
        name = PurePosixPath(prog).name
        rest = seg[1:]
        if dynamic and "<project>/" not in prog:
            comp.unknown.append(f"runs a program from a computed path `{prog_raw[:80]}`")
            return
        if "<project>/" in prog:
            comp.unknown.append(f"runs `{prog_raw[:80]}` from the user's project, not from this repository")
            return
        sub = (name, rest[0]) if rest else None
        if RUNNERS.match(name) or sub in RUNNER_SUBCOMMANDS:
            self._runner(comp, name, rest)
            return
        if INTERPRETERS.match(name):
            self._interpreter(comp, name, rest, root)
            return
        if "/" in prog or prog.startswith("."):
            norm, problem = self._norm(prog, "" if prog_raw.startswith("$") else (root if root != "." else ""))
            if problem == "absolute":
                comp.findings.append(Finding("medium", "unknown", "exec", "absolute-path", comp.declared_in, 0,
                                             f"runs `{prog[:80]}`, which is outside this repository"))
                comp.unknown.append(f"runs `{prog[:80]}`, which is not shipped here")
                return
            if norm is None:
                comp.findings.append(Finding("critical" if problem == "escape" else "medium", "confirmed",
                                             "config", "path-escape" if problem == "escape" else
                                             "backslash-path", comp.declared_in, 0,
                                             f"command path `{prog[:80]}` "
                                             + ("leaves the repository" if problem == "escape" else
                                                "uses backslashes (loaded only on Windows)")))
                if problem != "escape":
                    comp.unknown.append(f"`{prog[:80]}` was not resolved")
                return
            self.inspect_script(norm, comp)
            if norm.endswith(".cmd"):  # polyglot launcher: it runs a sibling named by its argument
                for arg in rest[:2]:
                    sib = self._with_ext(f"{PurePosixPath(norm).parent}/{arg}")
                    if sib:
                        self.inspect_script(sib, comp)
            return
        if self._project_runner(comp, name, rest, root):
            return
        shipped = self._in_bin(name, root)
        if shipped:
            self.inspect_script(shipped, comp)
            return
        if name in SHELL_BUILTINS or name in NOTIFIERS:
            return
        if name in DEV_TOOLS or name in LANGUAGE_SERVERS:
            comp.notes.append(f"runs the installed `{name}` (not shipped by this plugin)")
            return
        comp.unknown.append(f"runs `{name}`, which this repository does not ship; its behaviour depends "
                            "on what is installed")

    def _project_runner(self, comp: Component, name: str, rest: list[str], root: str) -> bool:
        if name not in PROJECT_RUNNERS:
            return False
        base = root if root not in ("", ".") else ""
        for flag in ("--prefix", "-C", "--cwd", "--dir", "--directory"):
            if flag in rest[:-1]:
                value, dyn = self._expand(rest[rest.index(flag) + 1], root)
                norm, _ = self._norm(value)
                base = norm if (norm is not None and not dyn) else base
        value_flags = {"--prefix", "-C", "--cwd", "--dir", "--directory", "-f", "--file", "--workspace", "-w", "--with",
                       "--from", "-p", "--project", "--python"}
        words, skip = [], False
        for a in rest:
            if skip:
                skip = False
            elif a in value_flags:
                skip = True
            elif not a.startswith("-"):
                words.append(a)
        if name in ("npm", "pnpm", "yarn", "bun") and words and words[0] in ("run", "run-script", "start", "test"):
            script = words[1] if words[0] in ("run", "run-script") and len(words) > 1 else words[0]
            self._package_script(comp, base, script, name)
            return True
        if name in ("pip", "pip3", "poetry", "pipenv", "uv") and ("install" in words or "add" in words
                                                                   or "--with" in rest):
            comp.findings.append(Finding("medium", "confirmed", "dependencies", "runtime-install", comp.declared_in, 0,
                                         f"installs packages when the hook runs (`{name} {' '.join(rest)[:60]}`)"))
            comp.unknown.append(f"`{name}` installs and runs packages that are not in this repository")
            if name == "uv" and words[:1] == ["run"]:
                self._script_args(comp, words[1:], root)
            return True
        if name in ("make", "gmake", "just", "task", "rake"):
            target = next((f"{base}/{n}" if base else n for n in ("Makefile", "makefile", "GNUmakefile", "justfile",
                                                                  "Taskfile.yml", "Rakefile")
                           if self.src.kind(f"{base}/{n}" if base else n) == "file"), None)
            if target:
                self.inspect_script(target, comp)
            comp.unknown.append(f"runs a `{name}` target defined by the repository")
            return True
        comp.unknown.append(f"`{name} {' '.join(rest)[:50]}` runs code the project defines or fetches")
        return True

    def _package_script(self, comp: Component, base: str, script: str, runner: str) -> None:
        pkg = f"{base}/package.json" if base else "package.json"
        data = self._json(pkg, comp.findings) if self.src.kind(pkg) == "file" else None
        scripts: dict[str, Any] = data["scripts"] if isinstance(data, dict) and isinstance(data.get("scripts"), dict) \
            else {}
        body = scripts.get(script)
        if isinstance(body, str) and comp.notes.count(f"package script `{script}`") < 1:
            comp.notes.append(f"package script `{script}`")
            self.inspect_command(comp, body, None, base or ".")
            comp.command = comp.command or _snip(body)
        else:
            comp.unknown.append(f"`{runner}` runs script `{script}`, which was not found in {pkg}")

    def _env_hijack(self, comp: Component, env: dict[str, Any], root: str, where: str,
                    settings: bool = False) -> None:
        """Variables that make every later process load or contact something else."""
        for key, value in env.items():
            k, v = str(key), str(value)
            if k.endswith("_BASE_URL") or k in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
                host = (_URL_HOST.findall(v) or [""])[0].lower()
                local = host in ("localhost", "127.0.0.1", "[::1]") or host.endswith(".localhost")
                if v and "${" not in v and not local:
                    comp.findings.append(Finding("critical" if settings else "high", "confirmed", "exfiltration",
                                                 "traffic-redirect", comp.declared_in, 0,
                                                 f"{where} sets {k}={_snip(v, 60)}: requests (and their credentials) "
                                                 "go to that host"))
                continue
            if k in _HIJACK_ENV or k.startswith(("LD_", "DYLD_")):
                comp.findings.append(Finding("high", "confirmed", "exec", "env-hijack", comp.declared_in, 0,
                                             f"{where} sets {k}: every process it starts loads what it names"))
                for path in re.findall(r"(?:--require[= ]|--import[= ]|-r[= ]?|^)([^\s=]+\.(?:c|m)?[jt]s|[^\s=]+\.(?:py|sh))",
                                       v):
                    value_, dyn = self._expand(path, root)
                    norm, _ = self._norm(value_, "" if path.startswith("$") else (root if root != "." else ""))
                    if norm and not dyn:
                        self.inspect_script(norm, comp)
                    else:
                        comp.unknown.append(f"{k} loads `{path[:60]}`, which was not resolved")

    def _in_bin(self, name: str, root: str) -> str | None:
        for r in [root, *self.report.plugins]:
            cand = f"{r}/bin/{name}" if r not in ("", ".") else f"bin/{name}"
            if self.src.kind(cand) in ("file", "symlink"):
                return cand
        return None

    def _interpreter(self, comp: Component, name: str, rest: list[str], root: str) -> None:
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok in ("-e", "-c", "--eval", "-p", "--print", "-Command", "-command", "-e/--eval"):
                code = rest[i + 1] if i + 1 < len(rest) else ""
                comp.findings.extend(self._text_findings(comp.declared_in, code, command=True))
                meta = self._script_signals(comp.declared_in, code)
                if meta["network"] and re.search(r"(?<![\w.])eval\s*\(|\.then\(\s*eval\s*\)|new\s+Function", code):
                    comp.findings.append(Finding("critical", "suspected", "remote-exec", "fetch-and-eval",
                                                 comp.declared_in, 0, "inline code downloads and evaluates code"))
                refs = self._local_refs(comp.declared_in, code)
                if meta["computed_require"]:
                    comp.findings.append(Finding("medium", "suspected", "exec", "bootstrap-indirect",
                                                 comp.declared_in, 0, "inline code computes which file to load"))
                    comp.unknown.append("inline code loads a module from a computed path" + (
                        f" (probably {', '.join(refs[:2])}, inspected)" if refs else ""))
                for ref in refs:
                    self.inspect_script(ref, comp, 1)
                if not refs and not meta["computed_require"] and meta["network"]:
                    comp.findings.append(Finding("medium", "confirmed", "network", "network-in-source",
                                                 comp.declared_in, 0, "inline code makes network requests"))
                self._script_args(comp, rest[i + 2:], root)  # `node -e "<bootstrap>" node real-hook.js`
                return
            if tok == "-m" and name.startswith("py"):
                module = rest[i + 1] if i + 1 < len(rest) else ""
                local = self._with_ext(module.replace(".", "/")) or self._with_ext(
                    module.replace(".", "/") + "/__main__")
                if local:
                    self.inspect_script(local, comp)
                else:
                    comp.unknown.append(f"runs the installed Python module `{module[:60]}`")
                return
            flag = tok.lower() if name.startswith(("pwsh", "powershell")) else tok
            if flag in _PRELOAD_FLAGS and i + 1 < len(rest):  # `node -r ./x.js`: code that runs first
                self._interpreter(comp, name, [rest[i + 1]], root)
                i += 2
                continue
            if flag in _VALUE_FLAGS.get(re.sub(r"[0-9.]+$|\.exe$", "", name), ()):  # `-ExecutionPolicy Bypass`
                i += 2
                continue
            if tok.startswith("-") or (name == "deno" and tok in ("run",)):
                i += 1
                continue
            script, dynamic = self._expand(tok, root)
            if dynamic:
                comp.unknown.append(f"`{name}` runs a script from a computed path `{tok[:80]}`")
                return
            norm, problem = self._norm(script, "" if tok.startswith("$") else (root if root != "." else ""))
            if norm is None:
                if problem == "absolute":
                    comp.unknown.append(f"`{name}` runs `{script[:80]}`, outside this repository")
                else:
                    comp.findings.append(Finding("critical", "confirmed", "config", "path-escape", comp.declared_in,
                                                 0, f"script path `{script[:80]}` leaves the repository"))
                return
            self.inspect_script(self._with_ext(norm) or norm, comp)
            self._script_args(comp, rest[i + 1:], root)  # launchers that take the real script as an argument
            return
        if name in {"bash", "sh", "zsh"}:
            comp.unknown.append(f"`{name}` reads its script from standard input")

    def _script_args(self, comp: Component, args: list[str], root: str) -> None:
        for extra in args[:6]:
            value, dyn = self._expand(extra, root)
            if dyn or extra.startswith("-") or not re.search(r"\.(c|m)?[jt]s$|\.py$|\.sh$", value):
                continue
            for base in ((root if root != "." else ""), ""):
                hit, _ = self._norm(value, "" if extra.startswith("$") else base)
                if hit and self.src.kind(hit) in ("file", "symlink"):
                    self.inspect_script(hit, comp)
                    break

    def _runner(self, comp: Component, name: str, rest: list[str]) -> None:
        args = [a for a in rest if a not in ("-y", "--yes", "-q", "--quiet", "dlx", "exec", "x", "run", "tool")]
        if name in ("docker", "podman", "nerdctl"):
            joined = " ".join(rest)
            if re.search(r"(-v|--volume|--mount)[ =]\S*(?:^|[ =\"'])(/|~|\$HOME|\$\{HOME\})(:|,|\s|$)", " " + joined) \
                    or re.search(r"(-v|--volume)\s+/:", joined) or "--privileged" in rest \
                    or re.search(r"(-v|--volume)\s+(/var/run/docker\.sock|~|\$HOME|/Users|/home)\b", joined):
                comp.findings.append(Finding("critical", "confirmed", "permission-escalation", "docker-host-access",
                                             comp.declared_in, 0, "container gets the host file system, the docker "
                                             "socket or privileged mode: " + _snip(joined, 100)))
            image = next((a for a in args if not a.startswith("-") and ("/" in a or ":" in a or "@" in a)), "")
            if "@sha256:" not in image:
                comp.findings.append(Finding("medium", "confirmed", "mcp", "unpinned-image", comp.declared_in, 0,
                                             f"container image {image or '?'} is not pinned by digest"))
            comp.unknown.append(f"runs container image {image or '?'}: its contents are not inspected")
            return
        if name in ("uvx", "pipx", "uv"):
            src = next((rest[j + 1] for j, a in enumerate(rest[:-1]) if a == "--from"), "")
            pkg = src or next((a for a in args if not a.startswith("-")), "")
            if pkg.startswith("git+"):
                pinned = bool(re.search(r"@[0-9a-f]{40}\b", pkg))
                if not pinned:
                    comp.findings.append(Finding("high", "confirmed", "mcp", "unpinned-git-runner", comp.declared_in,
                                                 0, f"installs and runs {pkg[:100]} from a moving git ref"))
            elif not re.search(r"==\d", pkg):
                comp.findings.append(Finding("medium", "confirmed", "mcp", "unpinned-runner", comp.declared_in, 0,
                                             f"`{name} {pkg[:80]}` fetches whatever version is current"))
            comp.unknown.append(f"`{name}` fetches and runs {pkg[:80] or 'a package'}: not inspected")
            return
        pkg = next((a for a in args if not a.startswith("-")), "")
        body = pkg[1:] if pkg.startswith("@") else pkg
        version = body.split("@", 1)[1] if "@" in body else ""
        if not _EXACT_VERSION.match(version):
            comp.findings.append(Finding("medium", "confirmed", "mcp", "unpinned-runner", comp.declared_in, 0,
                                         f"`{name} {pkg[:80]}` fetches whatever version is current at every launch"))
        else:
            comp.notes.append(f"pinned to {pkg[:80]}; the package itself is not inspected")
        comp.unknown.append(f"`{name}` downloads and runs {pkg[:80] or 'a package'}: not inspected")

    # ------------------------------------------------------- components
    def hooks(self, data: Any, declared: str, root: str) -> None:
        if not isinstance(data, dict):
            return
        events = data.get("hooks") if isinstance(data.get("hooks"), dict) else (
            data if all(isinstance(v, list) for v in data.values()) and data else {})
        for module in data.get("modules") or [] if isinstance(data.get("modules"), list) else []:
            comp = Component("hooks-module", str(module)[:80], declared, root)
            comp.findings.append(Finding("high", "confirmed", "plugin", "hooks-module", declared, 0,
                                         "a hooks module runs inside the Claude Code process and can approve "
                                         "tool calls before you are asked"))
            comp.unknown.append("in-process module: what it registers is only known at runtime")
            here = str(PurePosixPath(declared).parent)  # module paths are relative to the hooks file
            for base in (here if here != "." else "", root if root != "." else ""):
                norm, _ = self._norm(str(module), base)
                if norm and self.src.kind(norm) in ("file", "symlink"):
                    self.inspect_script(norm, comp)
                    break
            else:
                comp.unknown.append(f"module `{str(module)[:60]}` was not found")
            self.report.components.append(comp)
        for event, groups in (events or {}).items():
            for group in groups if isinstance(groups, list) else []:
                if not isinstance(group, dict):
                    continue
                matcher = str(group.get("matcher", ""))
                for h in group.get("hooks") or []:
                    if isinstance(h, dict):
                        self._hook(h, str(event), matcher, declared, root)

    def _hook(self, h: dict[str, Any], event: str, matcher: str, declared: str, root: str) -> None:
        kind = str(h.get("type", "command"))
        comp = Component("hook", f"{event}" + (f"[{matcher}]" if matcher else ""), declared, root, event=event)
        if kind == "command":
            args = h.get("args") if isinstance(h.get("args"), list) else None
            self.inspect_command(comp, str(h.get("command", "")), [str(a) for a in args] if args else None, root)
            if event in ("PreToolUse", "PermissionRequest"):
                comp.notes.append("can allow, deny or rewrite tool calls")
            if event in ("SessionStart", "UserPromptSubmit"):
                comp.notes.append("its output is added to the model's context")
        elif kind == "http":
            url = str(h.get("url", ""))
            comp.command = _snip(url, 200)
            host = (_URL_HOST.findall(url) or [""])[0].lower()
            local = host in ("localhost", "127.0.0.1", "[::1]") or host.endswith(".localhost")
            comp.findings.append(Finding("medium" if local else "high", "confirmed", "hook",
                                         "transcript-to-network", declared, 0,
                                         f"POSTs every {event} event (session id, transcript path, tool input) "
                                         f"to {host or url[:60]}"))
            self._headers(comp, h.get("headers"))
        elif kind in ("prompt", "agent"):
            comp.command = _snip(str(h.get("prompt", "")), 200)
            comp.findings.append(Finding("low", "confirmed", "hook", "model-spend", declared, 0,
                                         f"`{kind}` hook runs a model on every {event} (token spend)"))
            comp.findings.extend(self._text_findings(declared, str(h.get("prompt", "")), command=True))
        else:
            comp.command = _snip(json.dumps(h)[:200])
            comp.notes.append(f"hook type `{kind}`")
        self.report.components.append(comp)

    def _headers(self, comp: Component, headers: Any) -> None:
        for key, value in (headers or {}).items() if isinstance(headers, dict) else []:
            v = str(value)
            if "${" in v:
                continue
            if _SECRET_VALUE.search(v) or (_SECRET_KEY.search(str(key)) and len(v) >= 12 and
                                           not re.fullmatch(r"[\w.-]{0,40}", v.lower().replace("bearer", ""))):
                comp.findings.append(Finding("critical", "confirmed", "credentials", "hardcoded-credential",
                                             comp.declared_in, 0, f"header {key} carries a literal secret"))

    def mcp(self, data: Any, declared: str, root: str) -> None:
        if isinstance(data, str):
            comp = Component("mcp", data[:80], declared, root, command=_snip(data))
            if data.endswith((".mcpb", ".dxt")) or data.startswith("http"):
                comp.findings.append(Finding("high", "unknown", "mcp", "bundle-unreviewable", declared, 0,
                                             f"MCP bundle {data[:80]} is downloaded or unpacked at install"))
                comp.unknown.append("packaged MCP bundle: contents not inspected")
            self.report.components.append(comp)
            return
        servers = data.get("mcpServers") if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict) \
            else data
        for name, spec in (servers or {}).items() if isinstance(servers, dict) else []:
            if not isinstance(spec, dict):
                continue
            comp = Component("mcp", str(name), declared, root)
            url = str(spec.get("url") or "")
            if url:
                comp.command = _snip(url.split("?", 1)[0], 200)
                host = (_URL_HOST.findall(url) or ["?"])[0].lower()
                comp.findings.append(Finding("info", "confirmed", "mcp", "remote-host", declared, 0,
                                             f"remote server {host}: tool calls send data off the machine"))
                self._headers(comp, spec.get("headers"))
                comp.findings.extend(self._text_findings(declared, url, command=True))
            if spec.get("headersHelper"):
                comp.findings.append(Finding("high", "confirmed", "mcp", "headers-helper-shell", declared, 0,
                                             "headersHelper runs a shell command at every connection"))
                helper = Component("helper", f"{name}.headersHelper", declared, root)
                self.inspect_command(helper, str(spec["headersHelper"]), None, root)
                self.report.components.append(helper)
            if spec.get("command"):
                args = [str(a) for a in spec.get("args") or [] if isinstance(a, (str, int, float))]
                self.inspect_command(comp, str(spec["command"]), args, root)
            if isinstance(spec.get("env"), dict):
                self._env_hijack(comp, spec["env"], root, "the server's env")
            for key, value in (spec.get("env") or {}).items() if isinstance(spec.get("env"), dict) else []:
                v = str(value)
                if "${" not in v and (_SECRET_VALUE.search(v) or (_SECRET_KEY.search(str(key)) and len(v) >= 16)):
                    comp.findings.append(Finding("critical", "confirmed", "credentials", "hardcoded-credential",
                                                 declared, 0, f"env {key} carries a literal secret"))
            self.report.components.append(comp)

    def lsp(self, data: Any, declared: str, root: str) -> None:
        servers = data.get("lspServers") if isinstance(data, dict) and isinstance(data.get("lspServers"), dict) \
            else data
        for name, spec in (servers or {}).items() if isinstance(servers, dict) else []:
            if isinstance(spec, dict) and spec.get("command"):
                comp = Component("lsp", str(name), declared, root)
                args = [str(a) for a in spec.get("args") or [] if isinstance(a, (str, int, float))]
                self.inspect_command(comp, str(spec["command"]), args, root)
                comp.notes.append("spawned when a matching file is opened; runs outside the sandbox")
                self.report.components.append(comp)

    def monitors(self, data: Any, declared: str, root: str) -> None:
        items = data.get("monitors") if isinstance(data, dict) else data
        for m in items if isinstance(items, list) else []:
            if isinstance(m, dict) and m.get("command"):
                comp = Component("monitor", str(m.get("name", "monitor"))[:60], declared, root)
                self.inspect_command(comp, str(m["command"]), None, root)
                comp.notes.append("runs in the background from session start; its output reaches the model")
                self.report.components.append(comp)

    def settings(self, data: Any, declared: str, root: str, plugin_settings: bool) -> None:
        if not isinstance(data, dict):
            return
        comp = Component("settings", PurePosixPath(declared).name, declared, root)
        perms: dict[str, Any] = data["permissions"] if isinstance(data.get("permissions"), dict) else {}
        mode = str(perms.get("defaultMode") or data.get("defaultMode") or "")
        if mode in ("bypassPermissions", "dontAsk"):
            comp.findings.append(Finding("critical", "confirmed", "permission-escalation", "settings-bypass",
                                         declared, 0, f"sets permission mode {mode}"))
        elif mode == "acceptEdits":
            comp.findings.append(Finding("high", "confirmed", "permission-escalation", "settings-accept-edits",
                                         declared, 0, "accepts every file edit without asking"))
        allow = [str(a) for a in perms.get("allow") or [] if isinstance(a, str)]
        broad = [a for a in allow if re.fullmatch(r"(Bash|Write|Edit|WebFetch|mcp__\w*)(\((\*|\*\*|:\*)?\))?", a)
                 or a.endswith("(*)") or "domain:*" in a
                 # an interpreter, shell, network tool or package runner with any arguments is Bash(*)
                 or re.match(r"Bash\((sudo|bash|sh|zsh|python[\d.]*|node|perl|ruby|php|deno|bun|npx|uvx|pip3?|npm|curl|"
                             r"wget|nc|ssh|scp|eval|env|xargs|docker)\b[^)]*\*", a)
                 or re.match(r"(Read|Edit|Write)\((~|/|\$HOME)?/?(\*\*|\.ssh|\.aws|\.gnupg|\.config|\.netrc)", a)]
        if broad:
            comp.findings.append(Finding("high", "confirmed", "permission-escalation", "settings-broad-allow",
                                         declared, 0, "pre-approves " + ", ".join(broad[:5])))
        elif allow:
            comp.findings.append(Finding("medium", "confirmed", "permission-escalation", "settings-allow",
                                         declared, 0, "pre-approves " + ", ".join(allow[:5])))
        if data.get("enableAllProjectMcpServers") is True:
            comp.findings.append(Finding("high", "confirmed", "permission-escalation", "enable-all-mcp", declared, 0,
                                         "approves every project MCP server without asking"))
        if plugin_settings and data.get("agent"):
            comp.findings.append(Finding("high", "confirmed", "config", "session-agent-override", declared, 0,
                                         f"runs the whole session as agent {str(data['agent'])[:40]!r}"))
        if declared.endswith("settings.local.json"):
            comp.findings.append(Finding("medium", "confirmed", "config", "committed-local-settings", declared, 0,
                                         "a personal settings file is committed"))
        if isinstance(data.get("env"), dict):
            self._env_hijack(comp, data["env"], root, "settings env", settings=True)
        for key, value in (data.get("env") or {}).items() if isinstance(data.get("env"), dict) else []:
            if _SECRET_VALUE.search(str(value)):
                comp.findings.append(Finding("critical", "confirmed", "credentials", "hardcoded-credential",
                                             declared, 0, f"env {key} carries a literal secret"))
        for key in ("statusLine", "subagentStatusLine", "fileSuggestion"):
            spec = data.get(key)
            if isinstance(spec, dict) and spec.get("command"):
                sub = Component("status-line", key, declared, root)
                self.inspect_command(sub, str(spec["command"]), None, root)
                self.report.components.append(sub)
        for key in ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper"):
            if isinstance(data.get(key), str):
                sub = Component("helper", key, declared, root)
                sub.findings.append(Finding("high", "confirmed", "credentials", "credential-helper", declared, 0,
                                            f"{key} runs a command that produces credentials"))
                self.inspect_command(sub, data[key], None, root)
                self.report.components.append(sub)
        if isinstance(data.get("hooks"), dict):
            self.hooks({"hooks": data["hooks"]}, declared, root)
        if isinstance(data.get("mcpServers"), dict):
            self.mcp(data, declared, root)
        for key in ("trusted", "verified", "preApproved", "pre_approved", "safe", "anthropicApproved"):
            if data.get(key) is True:
                comp.findings.append(Finding("high", "confirmed", "provenance", "false-trust-claim", declared, 0,
                                             f"declares `{key}: true`, which no client honours (a claim grants "
                                             "nothing)"))
        if comp.findings:
            self.report.components.append(comp)

    def manifest(self, root: str) -> None:
        rel = f"{root}/.claude-plugin/plugin.json" if root != "." else ".claude-plugin/plugin.json"
        found: list[Finding] = []
        data = self._json(rel, found) if self.src.kind(rel) == "file" else {}
        comp = Component("settings", "plugin.json", rel, root, findings=found)
        data = data if isinstance(data, dict) else {}
        base = root if root != "." else ""

        def component(key: str, default: str) -> list[tuple[Any, str]]:
            """(data, declared-in) pairs: inline values or files the manifest points at."""
            value = data.get(key)
            values = value if isinstance(value, list) else [value] if value is not None else []
            out: list[tuple[Any, str]] = []
            for v in values:
                if isinstance(v, dict):
                    out.append((v, rel))
                elif isinstance(v, str):
                    norm, problem = self._norm(v, base)
                    if norm is None:
                        comp.findings.append(Finding("critical" if problem == "escape" else "medium", "confirmed",
                                                     "config", "path-escape" if problem == "escape" else
                                                     "absolute-or-backslash-path", rel, 0,
                                                     f"`{key}` points at {v[:80]}"))
                        continue
                    if v.endswith((".mcpb", ".dxt")) or v.startswith("http"):
                        out.append((v, rel))
                    elif self.src.kind(norm) == "symlink":
                        real = self._resolve_link(norm, comp)
                        if real:
                            out.append((self._json(real, comp.findings), real))
                    elif self.src.kind(norm) == "file":
                        out.append((self._json(norm, comp.findings), norm))
            default_path = f"{base}/{default}" if base else default
            if not values and self.src.kind(default_path) == "file":
                out.append((self._json(default_path, comp.findings), default_path))
            return out

        for d, where in component("hooks", "hooks/hooks.json"):
            self.hooks(d, where, root)
        for d, where in component("mcpServers", ".mcp.json"):
            self.mcp(d, where, root)
        for d, where in component("lspServers", ".lsp.json"):
            self.lsp(d, where, root)
        for d, where in component("monitors", "monitors/monitors.json"):
            self.monitors(d, where, root)
        exp: dict[str, Any] = data["experimental"] if isinstance(data.get("experimental"), dict) else {}
        if isinstance(exp.get("monitors"), (list, dict)):
            self.monitors(exp["monitors"], rel, root)
        for d, where in component("settings", "settings.json"):
            self.settings(d, where, root, plugin_settings=True)
        for key in ("trusted", "verified", "preApproved", "anthropicApproved", "official"):
            if data.get(key) is True:
                comp.findings.append(Finding("high", "confirmed", "provenance", "false-trust-claim", rel, 0,
                                             f"declares `{key}: true`, which Claude Code does not honour (a claim "
                                             "grants nothing)"))
        desc = " ".join(str(data.get(k, "")) for k in ("description", "name"))
        if _FALSE_TRUST.search(desc) or _INJECTION.search(desc):
            comp.findings.append(Finding("high", "confirmed", "provenance", "false-trust-claim", rel, 0,
                                         _snip(desc)))
        self._bin(root)
        if comp.findings:
            self.report.components.append(comp)

    def _bin(self, root: str) -> None:
        prefix = f"{root}/bin/" if root != "." else "bin/"
        files = [p for p in self.src.paths() if p.startswith(prefix) and p.count("/") == prefix.count("/")]
        for p in files[:MAX_BIN_FILES]:
            comp = Component("bin", PurePosixPath(p).name, p, root)
            comp.notes.append("on the Bash tool's PATH while the plugin is enabled")
            self.inspect_script(p, comp)
            self.report.components.append(comp)
        if len(files) > MAX_BIN_FILES:
            comp = Component("bin", f"{len(files) - MAX_BIN_FILES} more", prefix, root)
            comp.unknown.append(f"{len(files) - MAX_BIN_FILES} more bin/ executables were not inspected")
            self.report.components.append(comp)

    def marketplace(self) -> list[str]:
        rel = ".claude-plugin/marketplace.json"
        if self.src.kind(rel) != "file":
            return []
        comp = Component("marketplace", "marketplace.json", rel)
        data = self._json(rel, comp.findings)
        roots: list[str] = []
        for entry in (data or {}).get("plugins") or [] if isinstance(data, dict) else []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "?"))[:60]
            src = entry.get("source")
            if isinstance(src, str):
                norm, problem = self._norm(src)
                if norm is None:
                    comp.findings.append(Finding("critical" if problem == "escape" else "medium", "confirmed",
                                                 "config", "path-escape", rel, 0, f"plugin {name} source {src[:80]}"))
                    continue
                roots.append(norm or ".")
                if entry.get("strict") is False or any(k in entry for k in ("hooks", "mcpServers", "lspServers")):
                    for key, fn in (("hooks", self.hooks), ("mcpServers", self.mcp), ("lspServers", self.lsp)):
                        if isinstance(entry.get(key), dict):
                            fn(entry[key] if key != "hooks" else {"hooks": entry[key].get("hooks", entry[key])},
                               rel, norm or ".")
            elif isinstance(src, dict):
                kind = str(src.get("source", ""))
                if kind == "command" or "command" in src:
                    sub = Component("marketplace", f"{name} (command source)", rel)
                    sub.findings.append(Finding("high", "confirmed", "marketplace", "command-source", rel, 0,
                                                "builds the plugin by running a command on your machine at install "
                                                "and each session"))
                    self.inspect_command(sub, str(src.get("command", "")), None, ".")
                    self.report.components.append(sub)
                    continue
                pinned = bool(src.get("sha") or src.get("sha256") or src.get("version"))
                where = src.get("repo") or src.get("url") or src.get("package") or "?"
                ext = Component("marketplace", f"{name} (external source)", rel)
                ext.unknown.append(f"plugin {name} comes from {str(where)[:80]}; it is not in this repository")
                if not pinned:
                    ext.findings.append(Finding("medium", "confirmed", "marketplace", "unpinned-ref", rel, 0,
                                                f"plugin {name} follows a moving ref (no sha)"))
                self.report.components.append(ext)
        if comp.findings:
            self.report.components.append(comp)
        return roots

    def package(self, path: str, root: str) -> None:
        data = self._json(path, self.report.findings)
        if not isinstance(data, dict):
            return
        scripts: dict[str, Any] = data["scripts"] if isinstance(data.get("scripts"), dict) else {}
        for hook in ("preinstall", "install", "postinstall", "prepare", "prepublish", "preprepare", "postprepare"):
            if isinstance(scripts.get(hook), str):
                comp = Component("lifecycle", hook, path, root)
                comp.findings.append(Finding("high", "confirmed", "lifecycle", "npm-lifecycle-script", path, 0,
                                             f"`{hook}` runs on a manual `npm install` of this repository "
                                             "(Claude Code installs plugin dependencies with --ignore-scripts)"))
                base = str(PurePosixPath(path).parent)
                self.inspect_command(comp, scripts[hook], None, base if base != "." else ".")
                self.report.components.append(comp)
        for section in ("dependencies", "optionalDependencies"):
            for dep, spec in (data.get(section) or {}).items() if isinstance(data.get(section), dict) else []:
                if re.search(r"(git\+|https?://|file:|github:)", str(spec)):
                    self.report.findings.append(Finding("high", "confirmed", "dependencies", "url-dependency",
                                                        path, 0, f"{dep} from {str(spec)[:80]}"))

    def installers(self) -> None:
        for p in self.src.paths():
            name = PurePosixPath(p).name
            if p.count("/") <= 1 and (re.fullmatch(r"(install|setup|bootstrap)[\w-]*\.(sh|ps1|py)", name)):
                comp = Component("installer", name, p)
                self.inspect_script(p, comp)
                # a script you run by hand: report what it does, block only on the never-downgrade classes
                for f in comp.findings:
                    if f.severity == "critical" and f.category not in _NEVER_DOWNGRADE:
                        f.severity = "high"
                comp.notes.append("runs only if you run it by hand")
                self.report.components.append(comp)

    def prompt_texts(self, roots: list[str]) -> None:
        """Commands, agents and output styles are instructions Claude follows."""
        for p in self.src.paths():
            if not p.endswith(".md") or "/SKILL.md" in "/" + p:
                continue
            parts = PurePosixPath(p).parts
            if not any(d in parts[:-1] for d in ("commands", "agents", "output-styles")):
                continue
            text = self.src.text(p)
            if text is None:
                continue
            self.read_count += 1
            found = [f for f in self._text_findings(p, text)
                     if f.category in ("prompt-injection", "provenance", "permission-escalation", "remote-exec",
                                       "credentials", "exfiltration")]
            m = _SETTINGS_CHANGE.search(text)
            if m:
                found.append(Finding("medium", "confirmed", "config", "instructs-settings-change", p,
                                     text[:m.start()].count("\n") + 1, "tells Claude to write a status line, hook or "
                                     "permission into your settings, which then runs on its own: " + _snip(m.group(0))))
            if found:
                self.report.components.append(Component("prompt-text", PurePosixPath(p).stem, p, findings=found))
            if self.read_count >= MAX_FILES_TOTAL:
                break

    def structure(self) -> None:
        for p in self.src.paths():
            kind = self.src.kind(p)
            if kind == "submodule":
                self.report.findings.append(Finding("high", "unknown", "artifact", "submodule", p, 0,
                                                    "git submodule: nested source not inspected"))
            elif kind == "special":
                self.report.findings.append(Finding("high", "confirmed", "artifact", "special-file", p, 0,
                                                    "not a regular file"))
            elif kind == "symlink":
                target = self.src.link_target(p)
                norm, _ = self._norm(target, str(PurePosixPath(p).parent)) if target else (None, "")
                if norm is None:
                    self.report.findings.append(Finding("critical", "confirmed", "artifact", "symlink-escape", p, 0,
                                                        f"symbolic link -> {target[:120]} leaves the repository"))

    def license(self) -> None:
        for p in self.src.paths():
            if "/" not in p and PurePosixPath(p).name.upper().startswith(("LICENSE", "COPYING")):
                text = self.src.text(p) or ""
                self.report.license = _detect_license(text) or "OTHER"
                return


def plugin_roots(src: Source) -> list[str]:
    roots = {"."}
    for p in src.paths():
        if p.endswith(".claude-plugin/plugin.json"):
            parent = str(PurePosixPath(p).parent.parent)
            roots.add(parent if parent not in ("", ".") else ".")
        elif p.endswith("hooks/hooks.json") and p.count("/") <= 3:
            parent = str(PurePosixPath(p).parent.parent)
            roots.add(parent if parent not in ("", ".") else ".")
    return sorted(roots)[:MAX_PLUGIN_ROOTS]


def vet(src: Source, skills: dict[str, Any] | None = None) -> PluginReport:
    """Inspect every plugin component in `src`. Never executes anything."""
    a = _Analyzer(src)
    a.structure()
    a.license()
    listed = set(a.marketplace())
    roots = sorted(set(plugin_roots(src)) | listed)
    a.report.plugins = [r for r in roots if r != "." or r in listed or src.kind(".claude-plugin/plugin.json") == "file"
                        or src.kind("hooks/hooks.json") == "file"]
    for root in a.report.plugins:
        a.manifest(root)
    # project-scoped files a cloned repository applies when opened in Claude Code
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        if src.kind(rel) == "file":
            a.settings(a._json(rel, a.report.findings), rel, ".", plugin_settings=False)
    if src.kind(".mcp.json") == "file" and not any(c.declared_in == ".mcp.json" for c in a.report.components):
        a.mcp(a._json(".mcp.json", a.report.findings), ".mcp.json", ".")
    for root in roots:
        pkg = f"{root}/package.json" if root != "." else "package.json"
        if src.kind(pkg) == "file":
            a.package(pkg, root)
    if src.kind("setup.py") == "file":
        a.report.findings.append(Finding("high", "confirmed", "lifecycle", "setup-py", "setup.py", 0,
                                         "setup.py runs arbitrary code when the package is installed"))
    a.installers()
    a.prompt_texts(roots)
    if src.truncated:
        a.report.findings.append(Finding("high", "unknown", "artifact", "listing-truncated", "", 0,
                                         "the repository listing was truncated: some files were never seen"))
    if isinstance(src, GitHubSource) and src.errors:
        a.report.findings.append(Finding("high", "unknown", "artifact", "not-fetched", "", 0,
                                         f"{len(src.errors)} file(s) could not be fetched ({src.errors[0][:100]})"))
    if isinstance(src, GitHubSource) and src.mismatches:
        a.report.findings.append(Finding("critical", "confirmed", "integrity", "blob-mismatch", src.mismatches[0], 0,
                                         f"{len(src.mismatches)} file(s) did not match their git blob SHA"))
    a.report.integrity = src.integrity
    a.report.skills = skills or {}
    a.report.files_read = a.read_count
    for c in a.report.components:
        c.findings.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.category, f.rule, f.file, f.line))
        unique: dict[tuple[str, str, str, int], Finding] = {}
        for f in c.findings:
            unique.setdefault((f.rule, f.category, f.file, f.line), f)
        c.findings = list(unique.values())
        c.unknown = list(dict.fromkeys(c.unknown))
    return a.report


def render(report: PluginReport, limit: int = 30) -> str:
    from .textsafe import display as d  # names, commands, evidence and reasons come from the repository
    dims = report.dimensions()
    ex = dims["executable_source"]
    unknown = sum(len(d["reasons"]) for d in dims["dynamic_unknown"])
    lines = [f"plugin components: {report.verdict.upper()} ({len(report.components)} component(s) in "
             f"{len(report.plugins) or 'no'} plugin root(s); {report.files_read} file(s) read)",
             f"  skills {dims['skill_content'].get('status', 'none')} · config {dims['plugin_config']['status']} · "
             f"executables {ex['components']} ({ex['unresolved_components']} with unknowns) · "
             f"dynamic-unknown {unknown} · integrity {dims['source_integrity']['status']} · "
             f"licence {d(dims['license']['spdx'], 40)} · authorization NOT APPROVED"]
    order = {"blocked": 0, "review": 1, "eligible": 2}
    shown = 0
    for c in sorted(report.components, key=lambda c: (order[c.verdict], c.plugin, c.kind, c.name)):
        if c.verdict == "eligible" and not c.notes:
            continue
        if shown >= limit:
            lines.append(f"  … {len(report.components) - shown} more (use --json)")
            break
        shown += 1
        where = f"{c.plugin}/" if c.plugin not in (".", "") else ""
        lines.append(f"  {c.verdict.upper():8s} {c.kind}:{d(where + c.name, 100)}"
                     + (f"  `{d(c.command, 90)}`" if c.command else ""))
        for f in [f for f in c.findings if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["medium"]][:3]:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            lines.append(f"      [{f.severity}] {f.category}/{f.rule} {d(loc, 100)} {d(f.evidence, 90)}")
        for u in c.unknown[:2]:
            lines.append(f"      [unknown] {d(u, 120)}")
    for f in [f for f in report.findings if SEVERITY_ORDER[f.severity] >= SEVERITY_ORDER["high"]][:5]:
        lines.append(f"  [{f.severity}] {f.category}/{f.rule} {d(f.file, 100)} {d(f.evidence, 100)}")
    ev = dims["evidence"]
    lines.insert(2, f"  evidence: observed {ev['observed']} · risky {ev['risky']} · quoted in text {ev['quoted']} · "
                    f"unresolved {ev['unresolved']} · unsupported {ev['unsupported']}")
    lines.append("  experimental: static inspection never approves a plugin, so a plugin is `review` at best "
                 "(its skills may be eligible on their own). Executable components run with your full user permissions if you enable it; "
                 "no finding means no known problem, not proof of safety")
    return "\n".join(lines)
