"""Validation for SKILL.md files (Claude Code project skills).

Deliberately dependency-free: the front matter repo-ai writes is a strict
subset of YAML (`key: value` scalars, double-quoted strings, booleans), and
this parser accepts exactly that subset — anything fancier in a generated
skill is itself a validation failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024  # Claude Code allows 1,536 incl. when_to_use; stay well under

KNOWN_KEYS = frozenset({
    "name", "description", "argument-hint", "disable-model-invocation", "user-invocable",
    "allowed-tools", "disallowed-tools", "model", "context", "agent", "paths", "effort",
    "when_to_use", "arguments", "background",
})

# Workflows that can change the world outside the working tree. A skill that
# runs any of these must be manual-only (`disable-model-invocation: true`).
RISKY_RE = re.compile(
    r"(?i)\b(deploy|publish|release|push|migrat\w*|drop\s+table|truncate|delete\s+from|"
    r"rm\s+-[a-z]*[rf][a-z]*|kubectl\s+(apply|delete)|terraform\s+(apply|destroy)|"
    r"helm\s+(install|upgrade)|npm\s+publish|twine\s+upload|docker\s+push|credential|secret|"
    r"password|payment|charge|prod(uction)?|reset\s+--hard|clean\s+-[a-z]*f[a-z]*|sudo|chmod|chown|"
    r"eval|exec|ssh|scp|rsync|mkfs|dd\s+if=|shutdown|reboot)\b"
    r"|\b(curl|wget|fetch|nc|ncat)\b[^\n|]*\|\s*(ba|z|da|k)?sh\b"   # pipe a download into a shell
    r"|>\s*/dev/|~/\.ssh|\.aws/credentials")


# Lookalike backticks a model (or a hostile README) could use to hide code.
_BACKTICKS = str.maketrans({"\u02cb": "`", "\uff40": "`", "\u2035": "`", "\u0060": "`"})
# High-precision destructive patterns, checked over the *whole* body (prose
# included): no legitimate skill pipes a download into a shell.
DANGEROUS_ANYWHERE_RE = re.compile(
    r"(?i)\b(curl|wget|fetch|iwr|invoke-webrequest)\b[^\n]*\|\s*(sudo\s+)?(ba|z|da|k|fi)?sh\b"
    r"|\brm\s+-[a-z]*r[a-z]*f[a-z]*\b|\brm\s+-[a-z]*f[a-z]*r[a-z]*\b"
    r"|\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+(-f|--force))"
    r"|\bmkfs\b|\bdd\s+if=|>\s*/dev/(sd|disk|nvme)|chmod\s+-R\s+777"
    r"|~/\.ssh\b|\.aws/credentials|/etc/(passwd|shadow)")


def command_text(body: str) -> str:
    """Every command-bearing span: inline code, ``` and ~~~ fences, indented
    code blocks and <code>/<pre> elements (lookalike backticks normalised)."""
    body = body.translate(_BACKTICKS)
    spans: list[str] = []
    for fence in ("```", "~~~"):
        for block in re.findall(rf"{fence}[^\n]*\n(.*?){fence}", body, flags=re.S):
            spans.extend(line for line in block.splitlines() if line.strip())
        body = re.sub(rf"{fence}.*?{fence}", " ", body, flags=re.S)
    for block in re.findall(r"<(?:code|pre)[^>]*>(.*?)</(?:code|pre)>", body, flags=re.S | re.I):
        spans.extend(line for line in block.splitlines() if line.strip())
    spans += re.findall(r"`+([^`\n]+?)`+", body)
    previous_blank = True
    for line in body.splitlines():
        if previous_blank and re.match(r"^(\t| {4,})\S", line):
            spans.append(line.strip())
        elif re.match(r"^(\t| {4,})\S", line) and spans and spans[-1]:
            spans.append(line.strip())
        previous_blank = not line.strip()
    return "\n".join(spans)

# Built-in Claude Code slash commands a project skill must not shadow.
RESERVED_NAMES = frozenset({
    "add-dir", "agents", "bug", "clear", "compact", "config", "context", "cost", "doctor",
    "exit", "export", "help", "hooks", "ide", "init", "install-github-app", "login", "logout",
    "mcp", "memory", "model", "permissions", "plugin", "pr-comments", "release-notes", "resume",
    "review", "security-review", "skills", "status", "statusline", "terminal-setup", "upgrade",
    "vim", "rewind", "usage", "todos", "output-style", "fast", "plan", "artifacts",
})


@dataclass(slots=True)
class SkillReport:
    path: str
    name: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_only: bool = False
    description_chars: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_front_matter(text: str) -> tuple[dict[str, object] | None, str, str]:
    """Return (front matter or None, body, error)."""
    if not text.startswith("---\n"):
        return None, text, "missing YAML front matter"
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text, "unterminated YAML front matter"
    data: dict[str, object] = {}
    for lineno, raw in enumerate(text[4:end].splitlines(), start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if not match:
            return None, text, f"line {lineno}: unsupported YAML ({raw.strip()[:40]!r})"
        key, value = match.group(1), match.group(2).strip()
        if value.startswith('"'):
            if not value.endswith('"') or len(value) < 2:
                return None, text, f"line {lineno}: unterminated string"
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif value in {"true", "false"}:
            value = value == "true"  # type: ignore[assignment]
        elif value.startswith(("'", "[", "{", ">", "|")):
            if value.startswith("'") and value.endswith("'") and len(value) >= 2:
                value = value[1:-1]
            elif value.startswith((">", "|")):
                return None, text, f"line {lineno}: block scalars are not allowed in generated skills"
        if key in data:
            return None, text, f"duplicate key {key!r}"
        data[key] = value
    return data, text[end + 5:], ""


def validate_skill_text(text: str, path: str = "SKILL.md", dir_name: str = "",
                        root: Path | None = None) -> SkillReport:
    report = SkillReport(path=path)
    front, body, error = parse_front_matter(text)
    if error:
        report.errors.append(error)
        return report
    assert front is not None
    unknown = sorted(set(front) - KNOWN_KEYS)
    if unknown:
        report.warnings.append(f"unknown front-matter keys: {', '.join(unknown)}")
    name = str(front.get("name") or dir_name)
    report.name = name
    if not NAME_RE.match(name) or len(name) > MAX_NAME:
        report.errors.append(f"invalid skill name {name!r} (lowercase letters, digits, hyphens)")
    if dir_name and name != dir_name:
        report.errors.append(f"name {name!r} does not match directory {dir_name!r}")
    if name in RESERVED_NAMES:
        report.errors.append(f"name {name!r} collides with a built-in command")
    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        report.errors.append("missing description")
    else:
        report.description_chars = len(description)
        if len(description) > MAX_DESCRIPTION:
            report.errors.append(f"description too long ({len(description)} > {MAX_DESCRIPTION})")
    dmi = front.get("disable-model-invocation", False)
    if not isinstance(dmi, bool):
        report.errors.append("disable-model-invocation must be true or false")
    report.manual_only = bool(dmi)
    if "allowed-tools" in front:
        report.warnings.append("declares allowed-tools (pre-approves tools while active)")
    if not body.strip():
        report.errors.append("empty body")
    commands = command_text(body)
    if DANGEROUS_ANYWHERE_RE.search(body.translate(_BACKTICKS)):
        report.errors.append("contains a destructive or exfiltrating command (download piped to "
                             "a shell, rm -rf, force push, credentials paths); never acceptable")
    if RISKY_RE.search(commands) and not report.manual_only:
        report.errors.append("runs risky commands but is model-invocable; "
                             "set disable-model-invocation: true")
    if root is not None:
        for ref in re.findall(r"`((?:[\w.-]+/)+[\w.-]+\.\w{1,6})`", body):
            if "<" in ref or ref.startswith(("http", "$")):
                continue
            if ref.startswith("/") or ".." in ref.split("/"):
                report.errors.append(f"references a path outside the repository: {ref}")
                continue
            if not (root / ref).exists():
                report.errors.append(f"references missing path {ref}")
    return report


def validate_skill_file(path: Path, root: Path | None = None) -> SkillReport:
    try:
        text = path.read_text("utf-8")
    except OSError as exc:
        return SkillReport(path=str(path), errors=[f"unreadable: {exc}"])
    return validate_skill_text(text, str(path), path.parent.name, root)
