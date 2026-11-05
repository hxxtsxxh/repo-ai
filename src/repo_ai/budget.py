"""Budget Governor (`repo-ai budget`): what repo-ai costs Claude every session.

It measures:
- always-loaded context (CLAUDE.md, rules without `paths:`, model-invocable
  skill descriptions, subagent descriptions, the SessionStart line);
- per-prompt context, from the flight recorder when it is on;
- duplicated lines between instruction files.

It checks these against the configured caps, and it shows when the hook
*chose to inject nothing*, because inactivity is a feature.

Token figures are **estimates** (characters / 4). Claude's tokenizer differs,
so treat them as relative sizes, not billing.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .fsutil import MARKER_RE, read_text

BEGIN, END = "<!-- BEGIN repo-ai:claude -->", "<!-- END repo-ai:claude -->"


def est(text: str) -> int:
    return math.ceil(len(text) / 4)


def _front(text: str) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                key, _, value = line.partition(":")
                out[key.strip()] = value.strip().strip('"')
    return out


def measure(root: Path, cfg, layout) -> dict[str, Any]:
    from . import flight
    items: list[dict[str, Any]] = []

    def add(kind: str, name: str, tokens: int, owner: str, always: bool, note: str = "") -> None:
        items.append({"kind": kind, "name": name, "tokens_est": tokens, "owner": owner,
                      "always_loaded": always, "note": note})

    for name in ("CLAUDE.md", "CLAUDE.local.md"):
        text = read_text(root / name)
        if text is None:
            continue
        start, stop = text.find(BEGIN), text.find(END)
        managed = text[start:stop + len(END)] if start != -1 and stop != -1 else ""
        add("instructions", f"{name} (repo-ai block)", est(managed), "repo-ai", True)
        add("instructions", f"{name} (your text)", est(text.replace(managed, "")), "you", True)
        if re.search(r"(?m)^\s*@(?:\./)?AGENTS\.md\s*$", text):
            agents = read_text(root / "AGENTS.md") or ""
            add("instructions", "AGENTS.md (imported)", est(agents), "you + repo-ai", True)
    rules_dir = root / ".claude" / "rules"
    for path in sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []:
        text = read_text(path) or ""
        scoped = "paths" in _front(text)
        owner = "repo-ai" if MARKER_RE.search(text.replace("\r\n", "\n")) else "you"
        add("rule", path.name, est(text), owner, not scoped,
            "loads only for matching paths" if scoped else "")
    skills_dir = root / ".claude" / "skills"
    for path in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []:
        front = _front(read_text(path) or "")
        manual = front.get("disable-model-invocation", "false") == "true"
        raw = (read_text(path) or "").replace("\r\n", "\n")
        owner = "repo-ai" if MARKER_RE.search(raw) else "you"
        if "origin=generated" in raw:
            owner = "repo-ai (generated)"
        add("skill", f"/{path.parent.name}", est(front.get("description", "")) + 4, owner,
            not manual, "manual-only: description not offered to the model" if manual else "")
    agents_dir = root / ".claude" / "agents"
    for path in sorted(agents_dir.glob("*.md")) if agents_dir.is_dir() else []:
        front = _front(read_text(path) or "")
        add("subagent", path.stem, est(front.get("description", "")) + 4,
            "repo-ai" if path.stem.startswith("repo-") else "you", True)
    add("hook", "SessionStart line", 60, "repo-ai", True, "about one sentence")

    always_repo_ai = sum(i["tokens_est"] for i in items if i["always_loaded"]
                         and i["owner"].startswith("repo-ai"))
    always_total = sum(i["tokens_est"] for i in items if i["always_loaded"])
    decisions = flight.entries(layout, 200)
    prompts = [d for d in decisions if d.get("event") == "prompt"]
    injected = [d for d in prompts if d.get("decision") == "injected"]
    per_prompt = {
        "recorded_prompts": len(prompts),
        "injected": len(injected),
        "omitted": len(prompts) - len(injected),
        "mean_tokens_est_when_injected": round(sum(d.get("tokens_est", 0) for d in injected)
                                               / len(injected)) if injected else None,
        "cap_tokens": cfg.hook_budget_tokens,
        "source": "flight recorder" if prompts else
                  "not measured (turn on flight_recorder for one session)",
    }
    duplicates = _duplicates(root)
    cap = getattr(cfg, "always_loaded_budget_tokens", 1500)
    problems = []
    if always_repo_ai > cap:
        problems.append(f"repo-ai's always-loaded context (~{always_repo_ai}) exceeds "
                        f"always_loaded_budget_tokens = {cap}")
    if duplicates:
        problems.append(f"{len(duplicates)} instruction line(s) appear in more than one file")
    generated = sum(1 for i in items if i["kind"] == "skill" and i["owner"] == "repo-ai (generated)")
    return {"items": items, "always_loaded_tokens_est": always_total,
            "always_loaded_repo_ai_tokens_est": always_repo_ai, "cap_tokens": cap,
            "per_prompt": per_prompt, "duplicates": duplicates[:10],
            "limits": {"hook_budget_tokens": cfg.hook_budget_tokens,
                       "hook_max_files": cfg.hook_max_files,
                       "refresh_debounce_seconds": cfg.refresh_debounce_seconds,
                       "max_generated_skills": getattr(cfg, "max_generated_skills", 8),
                       "generated_skills": generated,
                       "llm_drafting": getattr(cfg, "skills_llm", "off"),
                       "orchestration": getattr(cfg, "orchestration", "off")},
            "problems": problems,
            "note": "token figures are estimates (chars/4), not billing"}


def _duplicates(root: Path) -> list[str]:
    sources = {}
    for name in ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"):
        text = read_text(root / name)
        if text:
            sources[name] = text
    rules_dir = root / ".claude" / "rules"
    for path in sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []:
        sources[f".claude/rules/{path.name}"] = read_text(path) or ""
    seen: dict[str, str] = {}
    dupes = []
    for name, text in sources.items():
        for line in {ln.strip().lstrip("-* ").strip() for ln in text.splitlines()}:
            if len(line) < 30 or line.startswith(("<!--", "#", "---")):
                continue
            if line in seen and seen[line] != name:
                dupes.append(f"{line[:80]} ({seen[line]} and {name})")
            seen.setdefault(line, name)
    return sorted(set(dupes))


def render(data: dict[str, Any]) -> str:
    lines = ["repo-ai budget — what Claude loads (estimates: chars/4, not billing)"]
    for item in data["items"]:
        mark = "always" if item["always_loaded"] else "on demand"
        note = f" — {item['note']}" if item["note"] else ""
        lines.append(f"  {item['tokens_est']:6d}  {mark:9s} {item['kind']:12s} {item['name']} "
                     f"[{item['owner']}]{note}")
    lines.append(f"  always loaded: ~{data['always_loaded_tokens_est']} tokens, of which repo-ai "
                 f"~{data['always_loaded_repo_ai_tokens_est']} (cap {data['cap_tokens']})")
    pp = data["per_prompt"]
    if pp["recorded_prompts"]:
        lines.append(f"  per prompt: injected on {pp['injected']} of {pp['recorded_prompts']} "
                     f"recorded prompts (chose nothing on {pp['omitted']}); ~"
                     f"{pp['mean_tokens_est_when_injected']} tokens when injected (cap "
                     f"{pp['cap_tokens']})")
    else:
        lines.append(f"  per prompt: {pp['source']}; hard cap {pp['cap_tokens']} tokens")
    limits = data["limits"]
    lines.append(f"  limits: {limits['generated_skills']}/{limits['max_generated_skills']} generated "
                 f"skills, refresh debounce {limits['refresh_debounce_seconds']} s, LLM drafting "
                 f"{limits['llm_drafting']}, orchestration {limits['orchestration']}")
    for d in data["duplicates"]:
        lines.append(f"  duplicate: {d}")
    for p in data["problems"]:
        lines.append(f"  OVER BUDGET: {p}")
    if not data["problems"]:
        lines.append("  within budget")
    return "\n".join(lines)
