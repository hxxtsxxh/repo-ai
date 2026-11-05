"""Stack Packs: evidence-backed bundles learned across repositories of one zone.

A pack is built from the sanitized per-repository patterns that `repo-ai
registry contribute` stores in a zone (no paths, code, prompts or names:
only the stack, rule kinds, repo-ai skill names, outcome counts, and
pinned public third-party skills). An item enters a pack only when at least
`MIN_SUPPORT` repositories of the same stack share it, or (for a
third-party skill) when one of them measured a non-negative benefit in a
live trial.

Packs never cross zones, and applying one changes nothing by itself: the
plan lists what this repository already has, what its own learning must
confirm locally (`repo-ai learn review`), and which pinned third-party
skills it may vet and approve through the normal firewall path. A pack is a
starting hypothesis for a new repository, not a rule.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

MIN_SUPPORT = 2


def _slug(stack: dict[str, Any]) -> str:
    parts = [*stack["languages"][:2], *stack["frameworks"][:2], *stack["tests"][:1]]
    return re.sub(r"[^a-z0-9]+", "-", "-".join(parts).lower()).strip("-") or "generic"


def build(zone: str) -> list[dict[str, Any]]:
    from .registry import patterns
    packs = []
    for key, entry in sorted(patterns(zone).items()):
        repos = list((entry.get("by_repo") or {}).values())
        if len(repos) < MIN_SUPPORT:
            continue
        rules = Counter(r for p in repos for r in set(p.get("rules") or []))
        skills = Counter(s for p in repos for s in set(p.get("skills") or []))
        third: dict[str, dict[str, Any]] = {}
        for p in repos:
            for s in p.get("thirdparty") or []:
                item = third.setdefault(s["content_hash"], {**s, "support": 0, "measured": []})
                item["support"] += 1
                if s.get("evidence") in {"pilot", "evaluated"} and s.get("diff") is not None:
                    item["measured"].append({"status": s["evidence"], "diff": s["diff"]})
        outcomes: Counter[str] = Counter()
        for p in repos:
            outcomes.update({k: int(v) for k, v in (p.get("outcomes") or {}).items()})
        third_items = []
        for item in third.values():
            measured_ok = any(m["diff"] >= 0 for m in item["measured"]) and \
                not any(m["diff"] < 0 and m["status"] == "evaluated" for m in item["measured"])
            if item["support"] >= MIN_SUPPORT or measured_ok:
                third_items.append({k: item[k] for k in ("name", "owner", "repo", "commit",
                                                          "content_hash", "support", "measured")})
        packs.append({
            "id": _slug(entry["stack"]), "key": key, "stack": entry["stack"], "repos": len(repos),
            "rules": sorted((r, n) for r, n in rules.items() if n >= MIN_SUPPORT),
            "skills": sorted((s, n) for s, n in skills.items() if n >= MIN_SUPPORT),
            "thirdparty": sorted(third_items, key=lambda x: (-x["support"], x["name"])),
            "outcomes": dict(sorted(outcomes.items())),
        })
    seen: Counter[str] = Counter()
    for pack in packs:  # stable unique ids
        seen[pack["id"]] += 1
        if seen[pack["id"]] > 1:
            pack["id"] += f"-{seen[pack['id']]}"
    return packs


def match(packs: list[dict[str, Any]], facts: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    from .registry import sanitize_pattern
    mine = sanitize_pattern(facts, [], [], {})["stack"]
    scored = []
    for pack in packs:
        score = 2 * len(set(pack["stack"]["frameworks"]) & set(mine["frameworks"])) + \
            len(set(pack["stack"]["languages"]) & set(mine["languages"])) + \
            len(set(pack["stack"]["tests"]) & set(mine["tests"]))
        if score:
            scored.append((score, pack))
    return sorted(scored, key=lambda sp: (-sp[0], sp[1]["id"]))


def plan(root: Path, pack: dict[str, Any], active_rules: list[dict[str, Any]],
         installed_skills: set[str], lock: dict[str, Any]) -> dict[str, Any]:
    have_rules = {f"{r.get('kind')}:{r.get('topic') or '-'}" for r in active_rules}
    have_hashes = {e.get("content_hash") for e in (lock.get("skills") or {}).values()}
    items = []
    for rule, support in pack["rules"]:
        items.append({"type": "rule", "item": rule, "support": support,
                      "status": "present" if rule in have_rules else "confirm locally",
                      "next": "" if rule in have_rules else
                      "repo-ai learn review  (adopted only if this repository's own evidence agrees)"})
    for skill, support in pack["skills"]:
        items.append({"type": "skill", "item": skill, "support": support,
                      "status": "present" if skill in installed_skills else "candidate",
                      "next": "" if skill in installed_skills else "repo-ai skills discover  "
                      "(generated from this repository's own evidence)"})
    for s in pack["thirdparty"]:
        present = s["content_hash"] in have_hashes
        items.append({"type": "third-party skill", "item": f"{s['owner']}/{s['repo']}:{s['name']}",
                      "support": s["support"], "measured": s["measured"],
                      "status": "present" if present else "vet and approve",
                      "next": "" if present else
                      f"repo-ai skills discover --online, then audit; install only with "
                      f"--approve {s['content_hash'][:16]} (the pinned content)"})
    return {"pack": pack["id"], "repos": pack["repos"], "items": items,
            "note": "nothing was changed; every item goes through this repository's own gates"}
