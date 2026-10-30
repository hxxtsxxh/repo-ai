"""`repo-ai packet "<task>"`: a small, source-linked task briefing.

A packet answers, for one task and within a hard token cap:

* **goal**: task class (bug/feature/test/...) and how confident repo-ai is;
* **plan**: which lookup channels the query planner used, cheapest first
  (exact path → stack frame → symbol → route → changed files → ranked
  lexical/graph retrieval), and which it skipped;
* **locations**: `path:line` ranges with the reasons they rank;
* **verify**: linked tests and focused test commands;
* **constraints**: learned rules whose scope covers these files, generated
  and quarantined paths to leave alone;
* **blast radius**: importers, routes, CI files and co-change partners;
* **uncertainty**: what is heuristic, unresolved or low-confidence;
* **freshness**: index age, HEAD match, pending edits.

Everything is read from the local index; nothing is executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .retrieval import Retrieval, cached_search, classify, estimate_tokens

DIFF_WORDS = re.compile(r"\b(my|this|current|these|staged|uncommitted|working)\s+"
                        r"(change|changes|diff|patch|branch|edits?)\b", re.I)


@dataclass(slots=True)
class Packet:
    task: str
    intents: list[str]
    confidence: str
    plan: list[dict[str, Any]] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    blast: dict[str, Any] = field(default_factory=dict)
    uncertainty: list[str] = field(default_factory=list)
    freshness: dict[str, Any] = field(default_factory=dict)
    tokens_est: int = 0

    def to_json(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _glob_match(path: str, pattern: str) -> bool:
    """`**`-aware glob match by segments (no regex backtracking: a pattern of
    many `**/` cannot blow up, since rule paths come from a committed ledger)."""
    from fnmatch import fnmatchcase
    segs = [s for s in pattern.split("/") if s]
    collapsed: list[str] = []
    for seg in segs:
        if seg == "**" and collapsed and collapsed[-1] == "**":
            continue
        collapsed.append(seg)
    parts = path.split("/")
    # dp[i][j]: pattern[:i] matches parts[:j]
    prev = [True] + [False] * len(parts)
    for seg in collapsed:
        cur = [False] * (len(parts) + 1)
        if seg == "**":
            seen = False
            for j in range(len(parts) + 1):
                seen = seen or prev[j]
                cur[j] = seen
        else:
            for j in range(1, len(parts) + 1):
                cur[j] = prev[j - 1] and fnmatchcase(parts[j - 1], seg)
        prev = cur
    return prev[len(parts)]


def plan_query(index, task: str, changed: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Cheapest sufficient lookups first. Returns (steps, pinned paths)."""
    query = classify(task)
    files = {row["path"] for row in index.all_files()}
    steps: list[dict[str, Any]] = []
    pinned: list[str] = []

    def step(name: str, used: bool, found: int = 0, note: str = "") -> None:
        steps.append({"channel": name, "used": used, "found": found, "note": note})

    exact = [p.lstrip("./") for p in query.paths if p.lstrip("./") in files]
    step("exact path", bool(query.paths), len(exact),
         "named in the task" if exact else ("named but not indexed" if query.paths else ""))
    pinned += exact
    frames = [p for p, _ in query.frames if p.lstrip("./") in files]
    step("stack frames", bool(query.frames), len(frames))
    pinned += [f.lstrip("./") for f in frames if f.lstrip("./") not in pinned]
    defs: list[str] = []
    for ident in query.identifiers[:6]:
        defs += [r["path"] for r in index.find_symbol(ident, limit=5)]
    step("symbol lookup", bool(query.identifiers), len(set(defs)))
    routes = []
    if query.url_paths:
        from .graph import route_matches
        routes = [r for r in index.routes(5000)
                  if any(route_matches(u, r["path_pattern"]) for u in query.url_paths)]
    step("route match", bool(query.url_paths), len(routes))
    for r in routes:
        if r["file"] not in pinned:
            pinned.append(r["file"])
    wants_diff = bool(DIFF_WORDS.search(task))
    step("changed files", wants_diff, len(changed) if wants_diff else 0,
         "task refers to the working-tree change" if wants_diff else "")
    if wants_diff:
        pinned += [p for p in changed if p in files and p not in pinned]
    step("ranked retrieval", True, 0, "lexical (BM25 × IDF coverage) + graph + git signals")
    return steps, pinned


def build_packet(root: Path, index, facts: dict[str, Any] | None, task: str, *,
                 facts_obj: Any = None, rules: list[Any] | None = None,
                 changed: list[str] | None = None, max_files: int = 6,
                 budget_tokens: int = 900, prior: dict[str, float] | None = None) -> Packet:
    from .impact import analyze_impact

    changed = changed or []
    steps, pinned = plan_query(index, task, changed)
    result: Retrieval = cached_search(index, task[:4000], max_files=max_files * 2,
                                      include_tests=True, prior=prior)
    for s in steps:
        if s["channel"] == "ranked retrieval":
            s["found"] = len(result.hits)
    packet = Packet(task=task, intents=result.query.intents, confidence=result.confidence,
                    plan=steps)
    hits = {h.path: h for h in result.hits}
    order = list(dict.fromkeys([*pinned, *[h.path for h in result.hits if h.role != "test"]]))
    for path in order[:max_files]:
        hit = hits.get(path)
        ranges = [f"{s}-{e}" for s, e, _ in (hit.lines if hit else [])][:2]
        packet.locations.append({
            "path": path, "lines": ranges,
            "why": (hit.reasons[:3] if hit else ["pinned by the query planner"]),
            "score": round(hit.score, 2) if hit else None})
    targets = [loc["path"] for loc in packet.locations[:3]]

    impact = analyze_impact(index, facts_obj, targets, max_depth=2, root=root) if targets else None
    # Tests linked to the top locations by the import graph come first;
    # tests that only matched the task's words follow.
    tests = sorted(impact.tests, key=lambda t: (impact.tests[t] != "import", t)) if impact else []
    tests += [h.path for h in result.hits if h.role == "test" and h.path not in tests]
    if impact:
        packet.commands = impact.commands[:3]
        direct = [p for p, d in impact.importers.items() if d == 1]
        packet.blast = {
            "direct_importers": len(direct), "transitive_importers": len(impact.importers),
            "importers_sample": sorted(direct)[:5],
            "routes": [f"{r['method']} {r['path']}" for r in impact.routes][:5],
            "ci": impact.ci[:4], "co_change": impact.cochange[:4],
            "components": impact.components}
        packet.uncertainty += impact.uncertainty
    if not packet.commands and facts:
        cmds = (facts.get("commands") or {}).get("test") or []
        packet.commands = cmds[:1]
    packet.tests = tests[:5]

    # constraints: learned rules scoped to these files, plus no-go paths
    for rule in rules or []:
        paths = list(getattr(rule, "paths", []) or [])
        if not paths or any(_glob_match(t, p) for t in targets for p in paths):
            text = getattr(rule, "text", "")
            if text and text not in packet.constraints:
                packet.constraints.append(text)
    generated = [loc["path"] for loc in packet.locations
                 if (row := index.get_file(loc["path"])) is not None and row["role"] == "generated"]
    if generated:
        packet.constraints.append("generated, do not hand-edit: " + ", ".join(generated))
    if facts:
        if facts.get("quarantined"):
            packet.constraints.append(f"{len(facts['quarantined'])} secret-bearing path(s) are "
                                      "quarantined and never shown")
    packet.constraints = packet.constraints[:6]

    # uncertainty
    if result.confidence in {"low", "none"}:
        packet.uncertainty.append(f"retrieval confidence is {result.confidence}: treat locations "
                                  "as guesses and search before editing")
    heuristic_only = [h.path for h in result.hits[:3]
                      if h.reasons and all("co-change" in r or "name" in r for r in h.reasons)]
    if heuristic_only:
        packet.uncertainty.append("ranked only by naming/co-change: " + ", ".join(heuristic_only))
    if not packet.tests:
        packet.uncertainty.append("no linked test found for the top locations")

    packet.freshness = freshness(root, index)
    if packet.freshness.get("stale"):
        packet.uncertainty.append("index is stale: " + packet.freshness["stale"])
    _fit(packet, budget_tokens)
    return packet


def freshness(root: Path, index) -> dict[str, Any]:
    from .gitinfo import current_head, is_git_repo
    out: dict[str, Any] = {"indexed_at": index.get_meta("generated_at"),
                           "indexed_head": index.get_meta("git_head")}
    if is_git_repo(root):
        head = current_head(root)
        out["head"] = head
        if head and out["indexed_head"] and head != out["indexed_head"]:
            out["stale"] = f"HEAD moved ({out['indexed_head']} → {head}); run `repo-ai update`"
    return out


def _fit(packet: Packet, budget: int) -> None:
    """Trim the least important sections until the estimate fits."""
    packet.tokens_est = estimate_tokens(render_markdown(packet))
    trims = [("blast", "co_change"), ("blast", "ci"), ("constraints", None), ("tests", None),
             ("locations", None)]
    for section, key in trims:
        while packet.tokens_est > budget:
            target = getattr(packet, section)
            if key is not None:
                if not target.get(key):
                    break
                target[key] = target[key][:-1]
            else:
                if len(target) <= 1:
                    break
                target.pop()
            packet.tokens_est = estimate_tokens(render_markdown(packet))
        if packet.tokens_est <= budget:
            break


def render_markdown(packet: Packet) -> str:
    out = [f"## Task packet: {packet.task[:120]}",
           f"goal: {', '.join(packet.intents) or 'general'} · confidence: {packet.confidence}"]
    used = [s for s in packet.plan if s["used"]]
    if used:
        out.append("plan: " + " → ".join(f"{s['channel']} ({s['found']})" for s in used))
    if packet.locations:
        out.append("\nlocations (read these first; verify before relying on them):")
        for i, loc in enumerate(packet.locations, 1):
            span = f":{loc['lines'][0]}" if loc["lines"] else ""
            why = "; ".join(loc["why"])
            out.append(f"{i}. {loc['path']}{span} — {why}")
    if packet.tests or packet.commands:
        out.append("\nverify:")
        out += [f"- test: {t}" for t in packet.tests]
        out += [f"- run: `{c}`" for c in packet.commands]
    if packet.constraints:
        out.append("\nconstraints:")
        out += [f"- {c}" for c in packet.constraints]
    b = packet.blast
    if b:
        parts = [f"{b.get('direct_importers', 0)} direct / {b.get('transitive_importers', 0)} "
                 "transitive importers"]
        if b.get("routes"):
            parts.append("routes " + ", ".join(b["routes"]))
        if b.get("ci"):
            parts.append("CI " + ", ".join(b["ci"]))
        if b.get("co_change"):
            parts.append("usually changes with " + ", ".join(b["co_change"]))
        out.append("\nblast radius: " + "; ".join(parts))
    if packet.uncertainty:
        out.append("\nuncertainty:")
        out += [f"- {u}" for u in dict.fromkeys(packet.uncertainty)]
    f = packet.freshness
    if f:
        out.append(f"\nfreshness: indexed {f.get('indexed_at') or '?'} at {f.get('indexed_head') or '?'}"
                   + (f" — STALE: {f['stale']}" if f.get("stale") else ""))
    return "\n".join(out) + "\n"


def render_claude(packet: Packet) -> str:
    body = render_markdown(packet).replace("## Task packet: ", "task: ", 1)
    return f'<repo-ai-packet confidence="{packet.confidence}">\n{body}</repo-ai-packet>\n'


