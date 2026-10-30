"""Adapter interface and the shared, ownership-aware write helpers.

An adapter turns the canonical `RepoFacts` (plus learned rules and skills)
into one agent's on-disk configuration. Adapters never write directly: they
record changes into a `Plan`, so install, update, dry-run, diff and uninstall
all share one code path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..fsutil import (Plan, detect_eol, managed_state, marker_attrs, remove_block, same_modulo_eol,
                      stamp_managed, to_eol, upsert_block)
from ..models import RepoFacts
from ..paths import Layout


@dataclass(slots=True)
class SetupContext:
    root: Path
    cfg: Config
    layout: Layout
    agents: tuple[str, ...]
    plan: Plan
    facts: RepoFacts | None = None
    quarantined: list[str] = field(default_factory=list)
    smart: bool = False
    rules: list[Any] = field(default_factory=list)       # active learned rules
    skills: list[Any] = field(default_factory=list)      # generated skill specs
    notes: list[str] = field(default_factory=list)       # user-facing remarks


@dataclass(slots=True)
class Check:
    label: str
    status: str  # ok | warn | fail | info
    detail: str = ""
    fix: str = ""

    def to_json(self) -> dict[str, str]:
        return {"label": self.label, "status": self.status, "detail": self.detail, "fix": self.fix}


class Adapter:
    name = "base"

    def plan_install(self, ctx: SetupContext) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def plan_uninstall(self, ctx: SetupContext) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def doctor(self, ctx: SetupContext) -> list[Check]:  # pragma: no cover - interface
        return []

    def local_only_ignores(self, ctx: SetupContext) -> list[str]:
        return []


# --------------------------------------------------------------------------
# managed whole files
# --------------------------------------------------------------------------
def plan_managed_file(
    plan: Plan,
    path: Path,
    body: str,
    kind: str,
    *,
    legacy_signature: str = "",
    executable: bool = False,
    comment: str = "html",
    attrs: dict[str, str] | None = None,
) -> str:
    """Write a stamped, repo-ai-owned file — unless a human owns it.

    Returns 'write' | 'unchanged' | 'adopted' | 'skip-foreign' | 'skip-modified'.
    `legacy_signature` lets a v0.4 file (written before ownership markers
    existed) be recognised and upgraded in place.
    """
    content = stamp_managed(body, kind, comment, **(attrs or {}))
    current = plan.current(path)
    state = managed_state(current)
    if state == "absent":
        plan.write(path, content, executable)
        return "write"
    if state == "pristine" and _third_party_bundle(current, kind):
        plan.skip(path, "a third-party skill repo-ai installed with your approval; left untouched")
        return "skip-foreign"
    if state == "pristine":
        if current == content or same_modulo_eol(current, content):
            return "unchanged"  # identical, or a CRLF checkout of identical text
        plan.write(path, content, executable)
        return "write"
    if state == "foreign":
        if legacy_signature and current is not None and legacy_signature in current:
            plan.write(path, content, executable, note="adopted v0.4 file")
            return "adopted"
        plan.skip(path, "exists and is not managed by repo-ai")
        return "skip-foreign"
    plan.skip(path, "edited by hand since repo-ai wrote it; left untouched")
    return "skip-modified"


def _third_party_bundle(current: str | None, kind: str = "") -> bool:
    """A file a capability bundle wrote is owned by the skill portfolio, not by the
    adapter that manages repo-ai's own files: its marker alone never lets them replace it."""
    from ..capbundle import MARKER_KIND
    return kind != MARKER_KIND and marker_attrs(current or "").get("kind") == MARKER_KIND


def plan_remove_managed_file(plan: Plan, path: Path, legacy_signature: str = "") -> str:
    current = plan.current(path)
    state = managed_state(current)
    if state == "absent":
        return "absent"
    if state == "pristine" and _third_party_bundle(current):
        plan.skip(path, "a third-party skill (capability bundle); removed only through the skill portfolio")
        return "kept"
    if state == "pristine" or (state == "foreign" and legacy_signature and current
                               and legacy_signature in current):
        plan.delete(path)
        plan.remove_dir_if_empty(path.parent)
        return "delete"
    plan.skip(path, "edited by hand or not created by repo-ai; kept"
              if state == "modified" else "not created by repo-ai; kept")
    return "kept"


# --------------------------------------------------------------------------
# managed blocks
# --------------------------------------------------------------------------
def plan_block(plan: Plan, path: Path, begin: str, end: str, block: str,
               create_with: str = "", position: str = "end") -> None:
    current = plan.current(path)
    if current is None:
        current = create_with or ""
    plan.write_shared(path, upsert_block(current, begin, end, block, position))


def plan_remove_block(plan: Plan, path: Path, begin: str, end: str,
                      delete_if: Callable[[str], bool] | None = None) -> None:
    current = plan.current(path)
    if current is None or begin not in current:
        return
    remaining = remove_block(current, begin, end)
    if delete_if is not None and delete_if(remaining):
        plan.delete(path, shared=True)
    else:
        plan.write_shared(path, remaining)


# --------------------------------------------------------------------------
# JSON settings with hook arrays (Claude Code and Bob share this shape)
# --------------------------------------------------------------------------
class SettingsError(ValueError):
    pass


def load_settings(text: str | None) -> dict:
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(f"invalid JSON ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(data, dict):
        raise SettingsError("top level is not a JSON object")
    return data


def merge_hook_entries(data: dict, ours: dict[str, list[dict]],
                       is_ours: Callable[[dict], bool]) -> dict:
    """Replace only repo-ai's own hook entries; every other key and hook is kept."""
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise SettingsError("`hooks` is not an object")
    hooks = dict(hooks or {})
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not (isinstance(e, dict) and is_ours(e))]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    for event, entries in ours.items():
        hooks[event] = list(hooks.get(event, [])) + entries
    out = dict(data)
    if hooks:
        out["hooks"] = hooks
    else:
        out.pop("hooks", None)
    return out


def remove_hook_entries(data: dict, is_ours: Callable[[dict], bool]) -> dict:
    return merge_hook_entries(data, {}, is_ours)


def json_style(text: str | None) -> dict:
    """Formatting of an existing JSON file, so rewriting it keeps its look."""
    style: dict[str, Any] = {"indent": 2, "separators": None, "eol": "\n",
                             "final_newline": True, "ensure_ascii": False}
    if not text or not text.strip():
        return style
    style["eol"] = detect_eol(text)
    style["final_newline"] = text.endswith("\n")
    body = text.strip()
    if "\n" not in body:
        style["indent"] = None
        style["separators"] = (", ", ": ") if '": ' in body else (",", ":")
    else:
        m = re.search(r"\n([ \t]+)\S", body)
        if m:
            ws = m.group(1)
            style["indent"] = "\t" if ws.startswith("\t") else len(ws)
    style["ensure_ascii"] = not re.search(r"[^\x00-\x7f]", text) and "\\u" in text
    return style


def dump_settings(data: dict, like: str | None = None) -> str:
    """Serialise settings in the style of `like` (the file being replaced)."""
    style = json_style(like)
    out = json.dumps(data, indent=style["indent"], separators=style["separators"],
                     ensure_ascii=style["ensure_ascii"])
    if style["final_newline"]:
        out += "\n"
    return to_eol(out, style["eol"])


# --------------------------------------------------------------------------
# .gitignore managed block (shared by every adapter; owned by core)
# --------------------------------------------------------------------------
GITIGNORE_BEGIN = "# >>> repo-ai managed >>>"
GITIGNORE_END = "# <<< repo-ai managed <<<"

# What v0.4 appended (without markers). Recognised so it can be migrated into
# the managed block and removed cleanly on uninstall.
LEGACY_GITIGNORE_ENTRIES = (
    ".bob/context/index.db", ".bob/context/index.db-wal",
    ".bob/context/index.db-shm", ".bob/context/.dirty", ".bob/context/",
)


def strip_legacy_gitignore(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "# repo-ai":
            j = i + 1
            while j < len(lines) and lines[j].strip() in LEGACY_GITIGNORE_ENTRIES:
                j += 1
            if j > i + 1:
                # drop the header, the entries, and one blank line before it
                if out and not out[-1].strip():  # "" or "\r" (CRLF file)
                    out.pop()
                i = j
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def gitignore_block(entries: list[str]) -> str:
    unique = list(dict.fromkeys(e for e in entries if e))
    return "\n".join([GITIGNORE_BEGIN,
                      "# Machine-local repo-ai state. Edit .repo-ai/config.toml, not this block.",
                      *unique, GITIGNORE_END])


def plan_gitignore(plan: Plan, root: Path, entries: list[str]) -> None:
    path = root / ".gitignore"
    current = plan.current(path) or ""
    cleaned = strip_legacy_gitignore(current)
    plan.write_shared(path, upsert_block(cleaned, GITIGNORE_BEGIN, GITIGNORE_END,
                                         gitignore_block(entries)))


def plan_remove_gitignore(plan: Plan, root: Path) -> None:
    path = root / ".gitignore"
    current = plan.current(path)
    if current is None:
        return
    cleaned = strip_legacy_gitignore(remove_block(current, GITIGNORE_BEGIN, GITIGNORE_END))
    if cleaned == current:
        return
    if not cleaned.strip():
        plan.delete(path, shared=True)
    else:
        eol = detect_eol(current)
        plan.write_shared(path, cleaned if cleaned.endswith("\n") else cleaned + eol)


_IMPORT_RE = re.compile(r"(?m)^\s*@(?:\./)?AGENTS\.md\s*$")


def imports_agents_md(claude_md_text: str | None) -> bool:
    """True when CLAUDE.md pulls AGENTS.md in with an `@AGENTS.md` import line."""
    return bool(claude_md_text and _IMPORT_RE.search(claude_md_text))
