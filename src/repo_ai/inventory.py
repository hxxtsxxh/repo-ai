"""Installed-capability inventory: what Claude Code can load in this repository.

Skills, plugins, hooks and MCP servers now arrive from many places:
- `npx skills add <url>` (copied into ~/.agents/skills and symlinked into
  ~/.claude/skills);
- `/plugin install` (cached under ~/.claude/plugins/cache);
- skills synced from claude.ai;
- skills committed to the project;
- an agent told to "install this skill from this repo".

repo-ai's firewall vets what *repo-ai* installs. This module looks at
everything that is *already* installed, whoever installed it, and reports:
- what each item is and where it came from;
- whether Claude Code loads it and whether the model can invoke it on its own;
- what it costs in always-loaded context;
- what the firewall finds in a quarantined copy;
- what runs automatically: hooks on every prompt or tool call, and MCP
  servers launched from unpinned packages.

Read-only and offline:
- nothing found is executed, installed, enabled or changed;
- the firewall works on a private temporary copy that is deleted afterwards;
- MCP environment values and secrets in arguments are never printed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .security import redact_text
from .textsafe import display

SCHEMA = "repo-ai.skills-inventory/1"
MAX_SKILLS = 500          # per run; a home directory is not a corpus
MAX_SKILL_MD = 200_000
OVERLAP_THRESHOLD = 0.5   # same threshold as the firewall's trigger-overlap rule
# Claude Code lists skill descriptions within 1% of the context window (about
# 2,000 tokens at 200k); past that, the least-used skills lose their
# descriptions and the model may not find them.
DEFAULT_BUDGET_TOKENS = 2000

# Hook events that put text into the model's context or can veto a tool call.
CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit"}
GATING_EVENTS = {"PreToolUse", "PermissionRequest", "Stop", "SubagentStop"}
_NETWORK_RE = re.compile(r"(?i)\b(curl|wget|nc|ncat|invoke-webrequest|iwr)\b|https?://")
_RUNNER_RE = re.compile(r"^(npx|bunx|pnpm|uvx|pipx|deno)$")
# The exact commands repo-ai's own wiring writes (adapters/claude.py, plugin.py). A hook is only
# labelled repo-ai's when it runs the script at exactly the path repo-ai writes *and* that script
# is byte-for-byte repo-ai's (see `_is_repo_ai_hook`).
_REPO_AI_SCRIPT_HOOK_RE = re.compile(r'sh "(\$CLAUDE_PROJECT_DIR|\$\{CLAUDE_PLUGIN_ROOT\})/([^"]*)" [a-z-]+')
_REPO_AI_CLI_HOOK_RE = re.compile(r"repo-ai hook claude [a-z-]+")
PLUGIN_HOOK_SCRIPT_REL = "hooks/repo-ai.sh"


@dataclass(slots=True)
class Issue:
    severity: str      # high | medium | low | info
    rule: str
    subject: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SkillItem:
    name: str
    scope: str                 # personal | project | synced | plugin | agents-store
    path: str                  # where Claude Code would find it
    kind: str = "skill"        # skill | command | agent
    namespace: str = ""        # plugin or synced namespace ("" = bare /name)
    link: str = ""             # symlink target when the directory is a link
    origin: str = "unknown"    # repo-ai | repo-ai-third-party | npx-skills | plugin | synced | user
    loaded: bool = True        # does Claude Code load it in this repository?
    model_invocable: bool = True
    description_tokens: int = 0
    source: str = ""           # where an installer says it came from (`npx skills` locks)
    pinned: bool = False       # the recorded source names an immutable commit
    verdict: str = ""          # firewall verdict on a quarantined copy ("" = not inspected)
    findings: list[str] = field(default_factory=list)
    content_hash: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _label(item: SkillItem) -> str:
    return f"{item.namespace + ':' if item.namespace else ''}{item.name}"


@dataclass(slots=True)
class Inventory:
    root: str
    skills: list[SkillItem] = field(default_factory=list)
    plugins: list[dict[str, Any]] = field(default_factory=list)
    hooks: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        loaded = [s for s in self.skills if s.loaded]
        # skill and agent descriptions are both listed to the model every session
        auto = [s for s in loaded if s.model_invocable and s.kind in {"skill", "agent"}]
        sev: dict[str, int] = {}
        for i in self.issues:
            sev[i.severity] = sev.get(i.severity, 0) + 1
        return {"skills_loaded": len(loaded), "model_invocable": len(auto),
                "always_loaded_description_tokens": sum(s.description_tokens for s in auto),
                "plugins_enabled": sum(1 for p in self.plugins if p.get("enabled")),
                "hooks": len(self.hooks), "mcp_servers": len(self.mcp_servers), "issues": sev}

    def to_json(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "root": self.root, "summary": self.summary(),
                "skills": [s.to_json() for s in self.skills], "plugins": self.plugins,
                "hooks": self.hooks, "mcp_servers": self.mcp_servers,
                "issues": [i.to_json() for i in self.issues], "notes": self.notes}


# --------------------------------------------------------------------------
# reading third-party files (lenient, never executed)
# --------------------------------------------------------------------------
def _read(path: Path, limit: int = MAX_SKILL_MD) -> str:
    if not path.is_file():  # never open a FIFO or device a hostile repository planted
        return ""
    try:
        with open(path, "rb") as fh:
            return fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _json(path: Path) -> Any:
    try:
        return json.loads(_read(path, 5_000_000) or "null")
    except ValueError:
        return None


def front_matter(text: str) -> dict[str, str]:
    """A lenient reader for third-party front matter: plain, quoted and block
    (`>` / `|`) scalars. Only used to measure; never to decide trust (the
    firewall's strict parser does that)."""
    text = text.replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---(?:\n|$)", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    lines = m.group(1).split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        km = re.match(r"^([A-Za-z_][\w-]*):[ \t]*(.*)$", line)
        i += 1
        if not km:
            continue
        key, value = km.group(1).lower(), km.group(2).strip()
        if value[:1] in {">", "|"}:
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in {" ", "\t"}):
                block.append(lines[i].strip())
                i += 1
            value = (" " if value[0] == ">" else "\n").join(b for b in block if b)
        elif value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1]
        out[key] = value
    return out


def _tokens(text: str) -> int:
    return len(text) // 4  # the same estimate as `repo-ai budget`


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "on"}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
def claude_home(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude"


def _skill_dirs(base: Path, depth: int = 1) -> list[Path]:
    """`<base>/<name>/SKILL.md` (depth 1) or `<base>/<group>/<name>/SKILL.md`."""
    if not base.is_dir():
        return []
    pattern = "*/SKILL.md" if depth == 1 else "*/*/SKILL.md"
    return sorted(p.parent for p in base.glob(pattern))[:MAX_SKILLS]


def _skill_item(skill_dir: Path, scope: str, namespace: str = "", origin: str = "unknown",
                loaded: bool = True) -> SkillItem:
    text = _read(skill_dir / "SKILL.md")
    front = front_matter(text)
    name = front.get("name") or skill_dir.name
    desc = front.get("description", "") + " " + front.get("when_to_use", "")
    link = ""
    if skill_dir.is_symlink():
        try:
            link = os.readlink(skill_dir)
        except OSError:
            link = "?"
    return SkillItem(name=name, scope=scope, path=str(skill_dir), namespace=namespace, link=link,
                     origin=origin, loaded=loaded,
                     model_invocable=not _truthy(front.get("disable-model-invocation", "false")),
                     description_tokens=_tokens(desc.strip()))


def _md_items(base: Path, kind: str, scope: str, namespace: str, origin: str) -> list[SkillItem]:
    """Commands or agents: every `*.md` in a directory, or one `.md` file a plugin manifest names."""
    out = []
    if base.is_file() and base.suffix == ".md":
        found = [base]
    else:
        found = sorted(base.glob("*.md"))[:MAX_SKILLS] if base.is_dir() else []
    for md in found:
        front = front_matter(_read(md))
        out.append(SkillItem(name=front.get("name") or md.stem, scope=scope, path=str(md), kind=kind,
                             namespace=namespace, origin=origin,
                             model_invocable=kind == "agent" or not _truthy(
                                 front.get("disable-model-invocation", "false")),
                             description_tokens=_tokens(front.get("description", ""))))
    return out


def _project_origin(root: Path, skill_dir: Path) -> str:
    from .fsutil import MARKER_RE
    if MARKER_RE.search(_read(skill_dir / "SKILL.md")):
        return "repo-ai"
    try:
        from .portfolio import load_lock
        if skill_dir.name in load_lock(root)["skills"]:
            return "repo-ai-third-party"
    except Exception:  # noqa: BLE001 - a broken lockfile is reported by `skills portfolio`
        pass
    return "user"


def _settings(root: Path, home: Path | None) -> list[tuple[str, dict[str, Any]]]:
    """(label, settings) from lowest to highest precedence."""
    out = []
    for label, path in (("user", claude_home(home) / "settings.json"),
                        ("project", root / ".claude" / "settings.json"),
                        ("local", root / ".claude" / "settings.local.json")):
        data = _json(path)
        if isinstance(data, dict):
            out.append((label, data))
    return out


def _enabled_plugins(settings: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    """plugin id -> the settings scope that last enabled it (disabled ones dropped)."""
    state: dict[str, tuple[bool, str]] = {}
    for label, data in settings:
        for pid, on in (data.get("enabledPlugins") or {}).items() if isinstance(
                data.get("enabledPlugins"), dict) else []:
            state[str(pid)] = (bool(on), label)
    return {pid: label for pid, (on, label) in state.items() if on}


def _install_paths(root: Path, home: Path | None) -> dict[str, dict[str, Any]]:
    data = _json(claude_home(home) / "plugins" / "installed_plugins.json")
    out: dict[str, dict[str, Any]] = {}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    for pid, entries in (plugins or {}).items():
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not entry.get("installPath"):
                continue
            project = entry.get("projectPath")
            if project and Path(str(project)).resolve() != root.resolve():
                continue
            out[str(pid)] = entry
    return out


def _strip_query(url: str) -> str:
    """A URL without its query string or fragment, where tokens and keys usually travel."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _repo_ai_scripts() -> dict[str, tuple[str, bytes]]:
    """Path variable -> (the exact relative path repo-ai writes, the exact bytes it writes there)."""
    from .adapters import claude_content
    from .adapters.claude import HOOK_SCRIPT_REL
    from .fsutil import stamp_managed
    from .plugin import HOOK_SCRIPT as PLUGIN_HOOK_SCRIPT
    # adapters/claude.py writes plan_managed_file(..., content.HOOK_SCRIPT, "claude-hook", comment="hash")
    project = stamp_managed(claude_content.HOOK_SCRIPT, "claude-hook", "hash")
    return {"$CLAUDE_PROJECT_DIR": (HOOK_SCRIPT_REL, project.encode("utf-8")),
            "${CLAUDE_PLUGIN_ROOT}": (PLUGIN_HOOK_SCRIPT_REL, PLUGIN_HOOK_SCRIPT.encode("utf-8"))}


def _is_repo_ai_hook(cmd: str, project_root: Path | None, plugin_root: Path | None) -> bool:
    """repo-ai's own hook: `repo-ai hook claude <event>`, or `sh "<var>/<path>" <event>` where the
    path is exactly the one repo-ai writes and the script there is byte-for-byte repo-ai's."""
    cmd = cmd.strip()
    if _REPO_AI_CLI_HOOK_RE.fullmatch(cmd):
        return True
    m = _REPO_AI_SCRIPT_HOOK_RE.fullmatch(cmd)
    if not m:
        return False
    var, rel = m.group(1), m.group(2)
    expected_rel, expected = _repo_ai_scripts()[var]
    base = project_root if var == "$CLAUDE_PROJECT_DIR" else plugin_root
    if base is None or rel != expected_rel:  # `..`, another directory, another name: not ours
        return False
    script = base / rel
    if not script.is_file():  # absent, or a FIFO or device
        return False
    try:
        with open(script, "rb") as fh:
            data = fh.read(2 * len(expected) + 1)  # room for a CRLF copy; anything longer differs
    except OSError:
        return False
    return data.replace(b"\r\n", b"\n") == expected  # a CRLF checkout of the same script is still ours


def _hook_entries(source: str, data: Any, project_root: Path | None = None,
                  plugin_root: Path | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    for event, groups in (hooks or {}).items() if isinstance(hooks, dict) else []:
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            for h in group.get("hooks") or [] if isinstance(group.get("hooks"), list) else []:
                if not isinstance(h, dict):
                    continue
                cmd = str(h.get("command") or h.get("prompt") or "")
                if not cmd and h.get("url"):
                    cmd = _strip_query(str(h.get("url")))
                out.append({"source": source, "event": str(event), "matcher": str(group.get("matcher", "")),
                            "type": str(h.get("type", "command")), "command": redact_text(cmd)[:300],
                            "repo_ai": _is_repo_ai_hook(cmd, project_root, plugin_root)})
    return out


# --------------------------------------------------------------------------
# hooks declared in skill, agent and command front matter
# --------------------------------------------------------------------------
_FM_KEY_RE = re.compile(r"^([^\s:#\-\"'][^:]*|\"[^\"]*\"|'[^']*'):(?:[ \t]+(.*))?$")
_FM_HOOK_VALUE_RE = re.compile(r"""(?:^|[\s{,"'])(?:command|url|prompt)["']?\s*:\s*(.+)$""")


def _yaml_scalar(text: str) -> Any:
    text = text.strip()
    if text[:1] in {"[", "{"}:
        try:
            return json.loads(text)
        except ValueError:
            return text
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _raw_value(text: str) -> str:
    """A value as written on one line: a quoted string up to its closing quote, or the rest of the
    line without the flow-collection brackets that close after it."""
    text = text.strip()
    q = re.match(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'', text)
    if q:
        return q.group(1) if q.group(1) is not None else q.group(2)
    return text.rstrip(",}] \t")


def _yaml_tokens(lines: list[str]) -> list[tuple[int, str, bool, int]]:
    """(indent, text, is_dash, line index): `- key: v` becomes a dash and a key one column in."""
    toks: list[tuple[int, str, bool, int]] = []
    for idx, raw in enumerate(lines):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise ValueError("tab indentation")
        ind = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        while text == "-" or text.startswith("- "):
            toks.append((ind, "-", True, idx))
            rest = text[1:]
            ind += 1 + len(rest) - len(rest.lstrip(" "))
            text = rest.strip()
            if not text:
                break
        if text:
            toks.append((ind, text, False, idx))
    return toks


def _yaml_node(toks: list[tuple[int, str, bool, int]], i: int, lines: list[str]) -> tuple[Any, int]:
    """A small block-YAML reader (mappings, sequences, scalars, flow JSON), enough for a hooks block."""
    ind, _, is_dash, _ = toks[i]
    if is_dash:
        seq: list[Any] = []
        while i < len(toks) and toks[i][0] == ind and toks[i][2]:
            i += 1
            if i < len(toks) and toks[i][0] > ind:
                item, i = _yaml_node(toks, i, lines)
            else:
                item = None
            seq.append(item)
        return seq, i
    if not _FM_KEY_RE.match(toks[i][1]):
        return _yaml_scalar(toks[i][1]), i + 1
    mapping: dict[str, Any] = {}
    while i < len(toks) and toks[i][0] == ind and not toks[i][2]:
        km = _FM_KEY_RE.match(toks[i][1])
        if not km:
            raise ValueError(f"unexpected {toks[i][1][:40]!r}")
        key, value = str(_yaml_scalar(km.group(1))), (km.group(2) or "").strip()
        i += 1
        if value[:1] in {"|", ">"}:
            used: list[int] = []
            while i < len(toks) and toks[i][0] > ind:
                if toks[i][3] not in used:
                    used.append(toks[i][3])
                i += 1
            mapping[key] = (" " if value[0] == ">" else "\n").join(lines[n].strip() for n in used)
        elif value:
            mapping[key] = _yaml_scalar(value)
        elif i < len(toks) and (toks[i][0] > ind or (toks[i][0] == ind and toks[i][2])):
            mapping[key], i = _yaml_node(toks, i, lines)
        else:
            mapping[key] = None
    return mapping, i


def front_matter_hooks(text: str) -> tuple[Any, list[str]]:
    """The `hooks:` value of a front-matter block, and every command/url/prompt value written in it.

    The second list is a plain text scan, so a hook the small YAML reader cannot structure is still
    listed (as event "(unparsed)") rather than silently dropped."""
    text = text.replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---(?:\n|$)", text, re.S)
    if not m:
        return None, []
    lines = m.group(1).split("\n")
    start = next((n for n, line in enumerate(lines) if re.match(r"^[\"']?hooks[\"']?[ \t]*:", line, re.I)), -1)
    if start < 0:
        return None, []
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in {" ", "\t", "-", "#"}):
        end += 1
    block = lines[start:end]
    raw_values: list[str] = []
    for n, line in enumerate(block):
        v = _FM_HOOK_VALUE_RE.search(line.strip())
        if not v:
            continue
        value = _raw_value(v.group(1))
        if re.fullmatch(r"[|>][+-]?\d?", value):  # a block scalar: its text starts on the next line
            value = next((b.strip() for b in block[n + 1:] if b.strip()), "")
        raw_values.append(value)
    try:
        parsed, _ = _yaml_node(_yaml_tokens(block), 0, block)
    except (ValueError, IndexError, RecursionError):
        parsed = None
    hooks = parsed.get(next(iter(parsed), "")) if isinstance(parsed, dict) else None
    return hooks, [v for v in raw_values if v.strip()]


def _front_matter_hook_entries(source: str, text: str, project_root: Path) -> list[dict[str, Any]]:
    hooks, raw = front_matter_hooks(text)
    out = _hook_entries(source, {"hooks": hooks}, project_root) if isinstance(hooks, dict) else []
    seen = {h["command"] for h in out}
    for value in raw:
        shown = redact_text(_strip_query(value) if re.match(r"(?i)https?://", value) else value)[:300]
        if not any(shown in c for c in seen):  # written in the block but not understood: list it anyway
            seen.add(shown)
            out.append({"source": source, "event": "(unparsed)", "matcher": "", "type": "command",
                        "command": shown, "repo_ai": False})
    return out


def _mcp_entries(source: str, data: Any) -> list[dict[str, Any]]:
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    out = []
    for name, spec in (servers or {}).items() if isinstance(servers, dict) else []:
        if not isinstance(spec, dict):
            continue
        args = [str(a) for a in spec.get("args") or [] if isinstance(a, (str, int, float))]
        url = str(spec.get("url") or "")
        out.append({"source": source, "name": str(name),
                    "transport": str(spec.get("type") or ("http" if url else "stdio")),
                    "command": redact_text(str(spec.get("command") or ""))[:120],
                    "args": [redact_text(a)[:120] for a in args[:20]],
                    "url": redact_text(_strip_query(url))[:200],
                    "env_keys": sorted(str(k) for k in (spec.get("env") or {}))[:20],
                    "header_keys": sorted(str(k) for k in (spec.get("headers") or {}))[:20]})
    return out


def _manifest_values(manifest: dict[str, Any], key: str) -> list[Any]:
    value = manifest.get(key)
    if value is None:
        return []
    return list(value)[:50] if isinstance(value, list) else [value]


def _inside(base: Path, rel: str) -> Path | None:
    """`rel` resolved inside the plugin, or None: a manifest cannot make us read outside its plugin."""
    target = (base / rel).resolve()
    return target if target.is_relative_to(base.resolve()) else None


def _plugin_paths(base: Path, manifest: dict[str, Any], key: str, default: str,
                  refused: list[str]) -> list[Path]:
    """The default location plus every path plugin.json adds (Claude Code loads both)."""
    out = [base / default]
    seen = {out[0].resolve()}
    for value in _manifest_values(manifest, key):
        if not isinstance(value, str):
            continue
        target = _inside(base, value)
        if target is None:
            refused.append(f"{key}: {value}")
        elif target not in seen:
            seen.add(target)
            out.append(target)
    return out


def _plugin_configs(base: Path, manifest: dict[str, Any], key: str, default: str,
                    refused: list[str]) -> list[Any]:
    """Hooks or MCP servers: the default file always, plus every file or inline config plugin.json adds."""
    out: list[Any] = []
    wrap = "hooks" if key == "hooks" else "mcpServers"
    for value in _manifest_values(manifest, key):
        if isinstance(value, dict):  # inline, with or without the outer key
            out.append(value if isinstance(value.get(wrap), dict) else {wrap: value})
    strings = {key: [v for v in _manifest_values(manifest, key) if isinstance(v, str)]}
    out.extend(_json(path) for path in _plugin_paths(base, strings, key, default, refused))
    return out


def _plugin_skill_dirs(paths: list[Path]) -> list[Path]:
    """Each path is a skill directory itself or a directory of skill directories."""
    out: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        for d in [path] if (path / "SKILL.md").is_file() else _skill_dirs(path):
            if d.resolve() not in seen:
                seen.add(d.resolve())
                out.append(d)
    return out[:MAX_SKILLS]


def _plugin_md_items(paths: list[Path], kind: str, ns: str) -> list[SkillItem]:
    out: list[SkillItem] = []
    seen: set[Path] = set()
    for path in paths:
        for item in _md_items(path, kind, "plugin", ns, "plugin"):
            if Path(item.path).resolve() not in seen:
                seen.add(Path(item.path).resolve())
                out.append(item)
    return out[:MAX_SKILLS]


def _plugin_components(inv: Inventory, pid: str, base: Path, info: dict[str, Any]) -> None:
    """Resolve and read what an enabled plugin runs (hook scripts, servers,
    bin/, settings), not only its command lines."""
    from . import pluginvet
    report = pluginvet.vet(pluginvet.LocalSource(base, label=pid))
    summary = {"verdict": report.verdict, "components": len(report.components),
               "unknown": len(report.dimensions()["dynamic_unknown"])}
    inv.notes.append(f"plugin {pid}: components {report.verdict} ({summary['components']} inspected, "
                     f"{summary['unknown']} with dynamic-unknown behaviour)")
    info["components"] = summary
    for c in report.components:
        worst = [f for f in c.findings if f.severity in ("critical", "high")][:2]
        if c.verdict == "blocked":
            inv.issues.append(Issue("high", "plugin-component-blocked", f"{pid} {c.kind}:{c.name}",
                                    "; ".join(f"{f.rule}: {f.evidence[:80]}" for f in worst)))
        elif c.verdict == "review" and worst:
            inv.issues.append(Issue("medium", "plugin-component-review", f"{pid} {c.kind}:{c.name}",
                                    "; ".join(f"{f.rule}: {f.evidence[:80]}" for f in worst)))


def _npx_locks(root: Path, home: Path | None) -> dict[str, dict[str, Any]]:
    """`npx skills` records where a skill came from: ~/.agents/.skill-lock.json
    (global installs) and ./skills-lock.json (project). Neither records a
    resolved commit, only an optional ref."""
    out: dict[str, dict[str, Any]] = {}
    for path in (root / "skills-lock.json", (home or Path.home()) / ".agents" / ".skill-lock.json"):
        data = _json(path)
        entries = data.get("skills") if isinstance(data, dict) else None
        for name, e in (entries or {}).items() if isinstance(entries, dict) else []:
            if isinstance(e, dict) and str(name) not in out:
                ref = str(e.get("ref") or "")
                out[str(name)] = {"source": redact_text(str(e.get("sourceUrl") or e.get("source") or ""))[:200],
                                  "pinned": bool(re.fullmatch(r"[0-9a-f]{40}", ref)), "ref": ref}
    return out


def _tweakcc(home: Path | None) -> str:
    """tweakcc patches the Claude Code executable itself and records it here."""
    base = home or Path.home()
    for d in (base / ".tweakcc", base / ".claude" / "tweakcc"):
        if (d / "applied.json").is_file():
            return str(d / "applied.json")
    return ""


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
def _md_as_skill(md: Path, tmp: Path, n: int) -> Path:
    """An agent or command is one Markdown file: copy it (never opening a FIFO or device) into a
    private directory as SKILL.md so the firewall reads it like a skill."""
    from . import firewall
    if not md.is_file():
        raise firewall.QuarantineError("not a regular file (not read)")
    with open(md, "rb") as fh:
        data = fh.read(firewall.MAX_FILE + 1)  # past the limit, the firewall reports it as too large
    staged = tmp / "md" / f"{n}"
    staged.mkdir(parents=True, mode=0o700)
    (staged / "SKILL.md").write_bytes(data)
    return staged


def _firewall(items: list[SkillItem], tmp: Path) -> None:
    """The same firewall inspection for skills, agents and commands, each on a private copy."""
    from . import firewall
    for n, item in enumerate(items):
        if item.kind not in {"skill", "agent", "command"}:
            continue
        src = Path(item.path)
        try:
            staged = src if item.kind == "skill" else _md_as_skill(src, tmp, n)
            dest, files, prior = firewall.quarantine_local(staged, f"{item.kind}:{item.name}", store=tmp)
            dir_name = src.name if item.kind == "skill" else item.name
            report = firewall.inspect(dest, files, {"id": f"{item.scope}/{item.name}", "name": item.name,
                                                    "path": dir_name}, {}, prior)
        except (OSError, firewall.QuarantineError) as exc:
            item.verdict, item.findings = "unreadable", [str(exc)[:160]]
            continue
        # Licence decides whether repo-ai may *redistribute* a skill (the install
        # gate); it says nothing about whether one already installed is safe. The
        # Agent Skills format rules (name, description, SKILL.md layout) do not
        # apply to agents and commands; what their text says and runs still does.
        report.findings = [f for f in report.findings if f.category != "license"
                           and (item.kind == "skill" or f.category != "spec")]
        item.verdict, item.content_hash = firewall.verdict(report), report.content_hash
        order = firewall.SEVERITY_ORDER
        own_file = "SKILL.md" if item.kind == "skill" else src.name  # the staged copy is named SKILL.md
        item.findings = [f"{f.severity} {f.category}/{f.rule}"
                         + (f" {own_file if f.file == 'SKILL.md' else f.file}" if f.file else "")
                         + (f":{f.line}" if f.line else "")
                         for f in sorted(report.findings, key=lambda f: -order[f.severity])
                         if order[f.severity] >= order["high"]
                         or (not report.complete and f.kind == "unknown" and f.severity == "medium")][:8]


def _issues(inv: Inventory, budget_tokens: int) -> None:
    from .skills_lab import overlap
    add = inv.issues.append
    for s in inv.skills:
        if not s.loaded:
            continue
        label = _label(s) if s.kind == "skill" else f"{s.kind} {_label(s)}"
        if s.verdict == "blocked":
            add(Issue("high", "firewall-blocked", label, "; ".join(s.findings[:3]) or "critical finding"))
        elif s.verdict == "review":
            add(Issue("medium", "firewall-review", label, "; ".join(s.findings[:3]) or "incomplete evidence"))
    loaded = [s for s in inv.skills if s.loaded and s.kind == "skill"]
    for s in loaded:
        label = _label(s)
        if s.link and s.origin not in {"npx-skills"}:
            add(Issue("low", "symlinked-skill", label, f"directory is a link to {s.link}"))
        if s.origin == "npx-skills" and not s.pinned:
            add(Issue("low", "unpinned-source", label,
                      f"installed from {s.source or 'an unrecorded source'} with no commit recorded; "
                      "`repo-ai skills vet <url> --online` pins and inspects it"))
    bare: dict[str, list[SkillItem]] = {}
    for s in loaded:
        if not s.namespace:
            bare.setdefault(s.name, []).append(s)
    for name, same in sorted(bare.items()):
        if len({s.scope for s in same}) > 1:
            add(Issue("medium", "name-collision", name,
                      "defined in " + ", ".join(sorted({s.scope for s in same})) +
                      "; Claude Code uses one (personal wins over project), so the other is shadowed"))
    auto = [s for s in loaded if s.model_invocable]
    descs = {id(s): front_matter(_read(Path(s.path) / "SKILL.md")).get("description", "") for s in auto}
    for i, a in enumerate(auto):
        for b in auto[i + 1:]:
            if a.name != b.name and overlap(descs[id(a)], descs[id(b)]) >= OVERLAP_THRESHOLD:
                add(Issue("low", "trigger-overlap", f"{a.name} ~ {b.name}",
                          "descriptions overlap; the model may pick either"))
    total = sum(s.description_tokens for s in auto)
    if total > budget_tokens:
        add(Issue("medium", "always-loaded-budget", f"{len(auto)} model-invocable skills",
                  f"~{total} description tokens; Claude Code lists descriptions within ~{budget_tokens} "
                  "(1% of a 200k context) and drops the least-used ones past that, so some skills may never "
                  "be found. Make rarely used skills manual-only (disable-model-invocation: true) or remove them"))
    for h in inv.hooks:
        subject = f"{h['source']} {h['event']}" + (f" [{h['matcher']}]" if h["matcher"] else "")
        if _NETWORK_RE.search(h["command"]):
            add(Issue("high", "hook-network", subject, f"hook command uses the network: {h['command'][:120]}"))
        if h["repo_ai"]:
            continue
        if h["event"] in CONTEXT_EVENTS:
            add(Issue("info", "hook-context", subject, "runs on every session/prompt and can add context"))
        elif h["event"] in GATING_EVENTS:
            add(Issue("info", "hook-gating", subject, "can block or redirect the agent"))
    for p in inv.plugins:
        if p.get("enabled") and p.get("adds_to_path"):
            add(Issue("medium", "plugin-path", p["id"], "ships bin/: its executables are added to PATH, so "
                      "they can shadow commands the agent runs"))
        if p.get("enabled") and p.get("ships_settings"):
            add(Issue("medium", "plugin-settings", p["id"], "ships settings.json that Claude Code applies"))
    for m in inv.mcp_servers:
        subject = f"{m['source']} {m['name']}"
        cmd = Path(m["command"]).name
        if _RUNNER_RE.match(cmd):
            pkgs = [a for a in m["args"] if not a.startswith("-")]
            pkg = pkgs[0] if pkgs else ""
            body = pkg[1:] if pkg.startswith("@") else pkg
            if not pkg or "@" not in body or body.endswith("@latest"):
                add(Issue("medium", "mcp-unpinned", subject,
                          f"`{cmd} {pkg}` fetches whatever version is current at every launch"))
        if m["url"]:
            add(Issue("info", "mcp-remote", subject, f"remote server {m['url']}: data leaves the machine"))


def build(root: Path, home: Path | None = None, firewall: bool = True,
          budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> Inventory:
    root = root.resolve()
    inv = Inventory(root=str(root))
    ch = claude_home(home)
    agents_store = (home or Path.home()) / ".agents" / "skills"

    # personal skills (some are links into the `npx skills` store)
    for d in _skill_dirs(ch / "skills"):
        origin = "user"
        if d.is_symlink():
            target = d.resolve()
            origin = "npx-skills" if target.is_relative_to(agents_store.resolve()) else "user"
        inv.skills.append(_skill_item(d, "personal", origin=origin))
    # skills synced from claude.ai: ~/.claude/skills/synced/<bucket>/<name>
    for d in _skill_dirs(ch / "skills" / "synced", depth=2):
        inv.skills.append(_skill_item(d, "synced", namespace="synced", origin="synced"))
    inv.skills.extend(_md_items(ch / "commands", "command", "personal", "", "user"))
    inv.skills.extend(_md_items(ch / "agents", "agent", "personal", "", "user"))

    for base in (ch / "skills", root / ".claude" / "skills"):
        for loose in sorted(base.glob("*/.claude-plugin/plugin.json"))[:50] if base.is_dir() else []:
            inv.issues.append(Issue("high", "plugin-in-skills-dir", str(loose.parent.parent),
                                    "a whole plugin in a skills directory is loaded without the plugin "
                                    "trust prompt; its hooks and servers were not inventoried"))
    patched = _tweakcc(home)
    if patched:
        inv.issues.append(Issue("high", "claude-code-patched", patched,
                                "tweakcc has patched the Claude Code executable; its behaviour and safety "
                                "checks may differ from the release (`npx tweakcc --restore` reverts)"))

    # project
    for d in _skill_dirs(root / ".claude" / "skills"):
        inv.skills.append(_skill_item(d, "project", origin=_project_origin(root, d)))
    inv.skills.extend(_md_items(root / ".claude" / "commands", "command", "project", "", "user"))
    inv.skills.extend(_md_items(root / ".claude" / "agents", "agent", "project", "", "user"))

    # the cross-agent store: only what is linked into a Claude scope is loaded
    linked = {s.path and Path(s.path).resolve() for s in inv.skills if s.origin == "npx-skills"}
    for store, scope in ((agents_store, "agents-store"), (root / ".agents" / "skills", "agents-store")):
        for d in _skill_dirs(store):
            if d.resolve() not in linked:
                inv.skills.append(_skill_item(d, scope, origin="npx-skills", loaded=False))

    # plugins
    settings = _settings(root, home)
    enabled = _enabled_plugins(settings)
    installed = _install_paths(root, home)
    for pid in sorted(set(enabled) | set(installed)):
        entry = installed.get(pid, {})
        base = Path(str(entry.get("installPath", "")))
        ns = pid.split("@", 1)[0]
        info: dict[str, Any] = {"id": pid, "enabled": pid in enabled, "enabled_in": enabled.get(pid, ""),
                                "version": entry.get("version", ""), "commit": entry.get("gitCommitSha", ""),
                                "path": str(base) if entry else "", "skills": 0, "commands": 0, "agents": 0}
        if not entry or not base.is_dir():
            if pid in enabled:
                inv.notes.append(f"plugin {pid} is enabled but not installed on disk")
            inv.plugins.append(info)
            continue
        on = pid in enabled
        raw_manifest = _json(base / ".claude-plugin" / "plugin.json")
        manifest: dict[str, Any] = raw_manifest if isinstance(raw_manifest, dict) else {}
        refused: list[str] = []
        items = [_skill_item(d, "plugin", namespace=ns, origin="plugin", loaded=on) for d in
                 _plugin_skill_dirs(_plugin_paths(base, manifest, "skills", "skills", refused))]
        cmds = _plugin_md_items(_plugin_paths(base, manifest, "commands", "commands", refused), "command", ns)
        agents = _plugin_md_items(_plugin_paths(base, manifest, "agents", "agents", refused), "agent", ns)
        for it in cmds + agents:
            it.loaded = on
        inv.skills.extend(items + cmds + agents)
        info.update(skills=len(items), commands=len(cmds), agents=len(agents),
                    adds_to_path=(base / "bin").is_dir(), ships_settings=(base / "settings.json").is_file())
        if on and firewall:
            _plugin_components(inv, pid, base, info)
        if on:
            for config in _plugin_configs(base, manifest, "hooks", "hooks/hooks.json", refused):
                inv.hooks.extend(_hook_entries(f"plugin:{ns}", config, root, base))
            for config in _plugin_configs(base, manifest, "mcpServers", ".mcp.json", refused):
                inv.mcp_servers.extend(_mcp_entries(f"plugin:{ns}", config))
            for what in dict.fromkeys(refused):
                inv.issues.append(Issue("high", "plugin-path-escape", pid,
                                        f"plugin.json {what} resolves outside the plugin; it was not read"))
        inv.plugins.append(info)

    # hooks and MCP servers configured directly
    for label, data in settings:
        inv.hooks.extend(_hook_entries(f"settings:{label}", data, root))
    # hooks a skill, agent or command declares in its own front matter (active while it runs)
    for item in inv.skills:
        if item.loaded:
            text = _read(Path(item.path) / "SKILL.md" if item.kind == "skill" else Path(item.path))
            inv.hooks.extend(_front_matter_hook_entries(f"{item.kind}:{_label(item)}", text, root))
    inv.mcp_servers.extend(_mcp_entries("project:.mcp.json", _json(root / ".mcp.json")))
    user_cfg = _json((home or Path.home()) / ".claude.json")
    if isinstance(user_cfg, dict):
        inv.mcp_servers.extend(_mcp_entries("user:~/.claude.json", user_cfg))
        project_cfg = (user_cfg.get("projects") or {}).get(str(root)) if isinstance(
            user_cfg.get("projects"), dict) else None
        inv.mcp_servers.extend(_mcp_entries("local:~/.claude.json", project_cfg))

    locks = _npx_locks(root, home)
    for item in inv.skills:
        lock = locks.get(item.name) if item.origin == "npx-skills" else None
        if lock:
            item.source, item.pinned = lock["source"], lock["pinned"]
    if len(inv.skills) >= MAX_SKILLS:
        inv.notes.append(f"stopped at {MAX_SKILLS} items")
    if firewall:
        with tempfile.TemporaryDirectory(prefix="repo-ai-inventory-") as tmp:
            _firewall([s for s in inv.skills if s.loaded or s.scope == "agents-store"], Path(tmp))
    else:
        inv.notes.append("firewall inspection skipped (--no-firewall)")
    _issues(inv, budget_tokens)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    inv.issues.sort(key=lambda i: (order.get(i.severity, 9), i.rule, i.subject))
    return inv


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def render(inv: Inventory, verbose: bool = False) -> str:
    """Human-readable report. Every string a skill, plugin, repository or file name supplies goes
    through `display()`, so none can move the cursor, recolour, retitle the terminal or forge a line."""
    d = display
    s = inv.summary()
    lines = [f"installed capabilities for {d(inv.root, 300)}",
             f"  loaded: {s['skills_loaded']} skills/commands/agents; model-invocable skills/agents: "
             f"{s['model_invocable']} (~{s['always_loaded_description_tokens']} description tokens every session)",
             f"  plugins enabled: {s['plugins_enabled']}  hooks: {s['hooks']}  MCP servers: {s['mcp_servers']}"]
    by_scope: dict[str, list[SkillItem]] = {}
    for item in inv.skills:
        by_scope.setdefault(item.scope if item.loaded else f"{item.scope} (not loaded)", []).append(item)
    for scope, items in sorted(by_scope.items()):
        lines.append(f"\n  {d(scope, 60)}: {len(items)}")
        shown = items if verbose else [i for i in items if i.verdict in {"blocked", "review"}][:10]
        for i in shown:
            mode = "auto" if i.model_invocable else "manual"
            lines.append(f"    {d(i.kind, 7):7s} {d(_label(i), 60):36s} {mode:6s} ~{i.description_tokens:4d} tok "
                         f"{d(i.verdict or '-', 12):8s} {d(i.origin, 40)}")
        if not verbose and len(shown) < len(items):
            lines.append(f"    ({len(items) - len(shown)} more without firewall concerns; --all lists them)")
    if inv.hooks:
        lines.append("\n  hooks:")
        for h in inv.hooks:
            lines.append(f"    {d(h['source'], 60):22s} {d(h['event'], 40):18s} {d(h['matcher'], 20):20s} "
                         f"{'(repo-ai) ' if h['repo_ai'] else ''}{d(h['command'], 70)}")
    if inv.mcp_servers:
        lines.append("\n  MCP servers:")
        for m in inv.mcp_servers:
            target = m["url"] or " ".join([m["command"], *m["args"][:3]])
            env = f"  env: {d(', '.join(m['env_keys']), 120)}" if m["env_keys"] else ""
            lines.append(f"    {d(m['source'], 60):22s} {d(m['name'], 40):20s} {d(target, 60)}{env}")
    lines.append("\n  issues:" if inv.issues else "\n  issues: none")
    for issue in inv.issues:
        lines.append(f"    [{d(issue.severity, 10)}] {d(issue.rule, 40)}: {d(issue.subject, 120)} — "
                     f"{d(issue.detail, 600)}")
    for note in inv.notes:
        lines.append(f"  note: {d(note, 300)}")
    lines.append("\n  read-only: nothing was executed, enabled or changed. A clean firewall result means "
                 "no known problem, not proof of safety.")
    return "\n".join(lines)
