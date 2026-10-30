"""Documentation analysis.

Docs are the highest-value-per-token content in most repositories, and also
the most likely to be stale. This module ranks documents, extracts headings
(cheap structural summary), and pulls the setup/run commands that READMEs
almost always contain but that no manifest records.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .models import FileRecord

DOC_PRIORITY: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"^readme\.(md|rst|txt|adoc)$", re.I), 100, "readme"),
    (re.compile(r"^(architecture|design)\.(md|rst|adoc)$", re.I), 95, "architecture"),
    (re.compile(r"^contributing\.(md|rst|adoc)$", re.I), 85, "contributing"),
    (re.compile(r"^(development|dev|developing|hacking|onboarding)\.(md|rst)$", re.I), 85, "development"),
    (re.compile(r"^(api|api-reference)\.(md|rst|adoc)$", re.I), 80, "api"),
    (re.compile(r"^(deploy|deployment|operations|runbook|ops)\.(md|rst)$", re.I), 80, "deployment"),
    (re.compile(r"^(testing|tests)\.(md|rst)$", re.I), 75, "testing"),
    (re.compile(r"^security\.(md|rst)$", re.I), 70, "security"),
    (re.compile(r"^(agents|claude|cursor|copilot-instructions)\.md$", re.I), 70, "agent-instructions"),
    (re.compile(r"^adr-?\d+.*\.(md|rst)$", re.I), 65, "adr"),
    (re.compile(r"^\d{4}-.*\.(md|rst)$", re.I), 60, "adr"),
    (re.compile(r"^changelog\.(md|rst)$", re.I), 30, "changelog"),
    (re.compile(r"^(license|licence|copying|notice)", re.I), 5, "license"),
    (re.compile(r"^code_of_conduct\.md$", re.I), 5, "conduct"),
]

DIR_BOOST = {
    "docs": 15, "doc": 15, "documentation": 15, "adr": 20, "adrs": 20,
    "rfc": 15, "rfcs": 15, "architecture": 20, "design": 15,
    "node_modules": -100, "examples": -10, "example": -10, "vendor": -100,
    "third_party": -100, "i18n": -20, "locales": -20, "translations": -20,
    "changelog.d": -30,
}

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*$", re.M)
RST_HEADING_RE = re.compile(r"^(.+)\n[=\-~^]{3,}\s*$", re.M)

# Fenced code blocks in docs are the best source of real run instructions.
FENCE_RE = re.compile(r"```(?:bash|sh|shell|console|zsh|terminal)?\n(.*?)```", re.S)
COMMAND_HINT_RE = re.compile(
    r"^\s*\$?\s*((?:npm|pnpm|yarn|bun|npx|pip|pip3|python|python3|poetry|uv|"
    r"make|mvn|gradle|\./gradlew|\./mvnw|go|cargo|bundle|rails|composer|php|"
    r"docker|docker-compose|kubectl|helm|terraform|pytest|jest|vitest|dotnet|"
    r"just|task|rake|sbt|node|deno)\s+[^\n|&;<>]{1,120})$",
    re.M,
)


def score_doc(path: str) -> tuple[int, str]:
    p = PurePosixPath(path)
    name = p.name
    score, category = 20, "other"
    for pattern, base, cat in DOC_PRIORITY:
        if pattern.match(name):
            score, category = base, cat
            break
    for part in p.parts[:-1]:
        score += DIR_BOOST.get(part.lower(), 0)
    depth = len(p.parts) - 1
    score -= depth * 3  # top-level docs matter more
    return score, category


def extract_headings(text: str, limit: int = 25) -> list[str]:
    headings = [f"{'#' * len(m.group(1))} {m.group(2)}" for m in HEADING_RE.finditer(text)]
    if not headings:
        headings = [m.group(1).strip() for m in RST_HEADING_RE.finditer(text)]
    cleaned: list[str] = []
    for heading in headings:
        h = re.sub(r"[`*_\[\]]", "", heading).strip()
        if h and len(h) < 120:
            cleaned.append(h)
        if len(cleaned) >= limit:
            break
    return cleaned


def extract_intro(text: str, max_chars: int = 700) -> str:
    """The first real paragraph, skipping badges, titles, and TOCs."""
    lines = text.splitlines()
    buffer: list[str] = []
    for raw in lines[:120]:
        line = raw.strip()
        if not line:
            if buffer:
                break
            continue
        if line.startswith("#") or line.startswith("=") or line.startswith("---"):
            continue
        if line.startswith(("[!", "![", "<img", "<p", "<div", "<h1", "<a", "|", "<!--")):
            continue
        if re.match(r"^\[!\[", line) or "shields.io" in line or "badge" in line.lower():
            continue
        buffer.append(line)
        if sum(len(b) for b in buffer) > max_chars:
            break
    intro = " ".join(buffer).strip()
    intro = re.sub(r"\s+", " ", intro)
    return intro[:max_chars]


def extract_commands(text: str) -> list[str]:
    commands: list[str] = []
    for block in FENCE_RE.finditer(text):
        for match in COMMAND_HINT_RE.finditer(block.group(1)):
            cmd = match.group(1).strip()
            if cmd not in commands and not cmd.startswith(("docker pull", "git clone")):
                commands.append(cmd)
        if len(commands) >= 30:
            break
    return commands[:30]


def analyze_docs(
    files: list[FileRecord], file_texts: dict[str, str], limit: int = 40
) -> tuple[list[dict[str, str]], list[str]]:
    """Return (ranked doc records, commands harvested from docs)."""
    candidates = [f for f in files if f.role == "doc"]
    scored: list[tuple[int, str, FileRecord]] = []
    for record in candidates:
        score, category = score_doc(record.path)
        if score <= 0:
            continue
        scored.append((score, category, record))
    scored.sort(key=lambda item: (-item[0], item[2].path))

    docs: list[dict[str, str]] = []
    harvested: list[str] = []
    for score, category, record in scored[:limit]:
        text = file_texts.get(record.path, "")
        entry = {
            "path": record.path,
            "category": category,
            "score": str(score),
            "lines": str(record.lines),
            "title": "",
            "intro": "",
            "headings": "",
        }
        if text:
            headings = extract_headings(text)
            entry["title"] = headings[0].lstrip("# ").strip() if headings else PurePosixPath(record.path).stem
            entry["intro"] = extract_intro(text)
            entry["headings"] = " | ".join(h.lstrip("# ").strip() for h in headings[:12])
            if category in {"readme", "development", "contributing", "deployment", "testing"}:
                for cmd in extract_commands(text):
                    if cmd not in harvested:
                        harvested.append(cmd)
        docs.append(entry)
    return docs, harvested[:25]
