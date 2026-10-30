"""Skill recommendations, coverage map and portfolio optimisation.

Two separate questions are answered for each candidate:

1. **Is it allowed?** The firewall verdict and licence. This is a gate:
   relevance or popularity can never override a block.
2. **Is it worth it?** A transparent relevance score from:
   - the evidence-backed gaps it addresses, weighted by the gap's
     strength;
   - redundancy with existing skills and native Claude Code commands;
   - documentation quality;
   - provenance;
   - context-token overhead;
   - empirical trial evidence, when any exists.

Popularity (stars) counts only as a weak provenance signal. "No additional
skills are necessary" is a first-class, successful outcome.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from . import firewall

THRESHOLD = 0.35


@dataclass(slots=True)
class Recommendation:
    candidate_id: str
    name: str
    score: float
    eligible: bool
    verdict: str
    install_recommended: bool
    reasons: list[str]
    gaps: list[str]
    overlaps: list[str]
    context_tokens_est: int
    evidence_status: str
    permissions: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def score(candidate: dict[str, Any], report: dict[str, Any] | None, profile: dict[str, Any],
          existing: dict[str, str], trial: dict[str, Any] | None = None) -> Recommendation:
    from .skills_lab import overlap
    gaps = {g["id"]: g for g in profile.get("gaps", [])}
    matched = [g for g in candidate.get("matched_gaps", []) if g in gaps]
    reasons = []
    relevance = 0.0
    for gid in matched:
        g = gaps[gid]
        relevance = max(relevance, float(g["strength"]))
        reasons.append(f"addresses gap '{g['title']}' ({'; '.join(g['evidence'][:2])})")
    if not matched:
        reasons.append("matches no evidence-backed capability gap of this repository")
    desc = str(candidate.get("description", ""))
    doc_quality = min(1.0, len(desc) / 200) * (1.0 if " when " in desc.lower() or "use " in desc.lower()
                                               else 0.7)
    overlaps = sorted(name for name, text in existing.items() if overlap(desc, text) >= 0.35)
    redundancy = 0.5 if overlaps else 0.0
    if overlaps:
        reasons.append(f"overlaps existing skills: {', '.join('/' + o for o in overlaps)}")
    owner = str(candidate.get("owner", "")).lower()
    from .radar import KNOWN_PUBLISHERS
    provenance = 0.15 if owner in KNOWN_PUBLISHERS else min(0.1, math.log10(1 + int(candidate.get("stars") or 0)) / 50)
    size = sum(int(f.get("size", 0)) for f in (report or {}).get("files", []) if f.get("path") == "SKILL.md")
    tokens = math.ceil(len(desc) / 4) + 4
    cost_penalty = min(0.2, size / 4 / 10000)
    empirical = 0.0
    evidence_status = "not evaluated"
    if trial:
        evidence_status = trial.get("status", "not evaluated")
        if trial.get("verdict", "").startswith("with") and "better" in trial.get("verdict", ""):
            empirical = 0.3
        elif "worse" in trial.get("verdict", ""):
            empirical = -0.5
            reasons.append("controlled trial: outcomes were worse with this skill")
    total = round(relevance * (1 - redundancy) * 0.7 + doc_quality * 0.1 + provenance
                  - cost_penalty + empirical, 3)
    verdict = (report or {}).get("verdict", "not audited")
    no_license = any(f.get("rule") in firewall.LICENSE_GATE_RULES for f in (report or {}).get("findings", []))
    eligible = verdict in {"eligible", "review"} and not no_license
    if verdict == "blocked":
        reasons.append("BLOCKED by the firewall: " + ", ".join(sorted({
            f"{f['category']}/{f['rule']}" for f in (report or {}).get("findings", [])
            if f["severity"] == "critical"}))[:200])
    elif no_license:
        reasons.append("no usable licence: not installable")
    perms = []
    for f in (report or {}).get("findings", []):
        if f["rule"] in {"allowed-tools", "external-host", "external-requirements"}:
            perms.append(f"{f['rule']}: {f['evidence'][:80]}")
    recommended = eligible and total >= THRESHOLD and bool(matched)
    return Recommendation(candidate.get("id", ""), candidate.get("name", ""), total, eligible, verdict,
                          recommended, reasons, matched, overlaps, tokens, evidence_status, perms[:6])


def recommend(candidates: list[dict[str, Any]], reports: dict[str, dict[str, Any]],
              profile: dict[str, Any], existing: dict[str, str],
              trials: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    # trials are recorded by skill name (`skills benchmark <name>`), candidates carry an id
    recs = [score(c, reports.get(c["id"]), profile, existing,
                  (trials or {}).get(c["id"]) or (trials or {}).get(c.get("name", "")))
            for c in candidates]
    recs.sort(key=lambda r: (not r.install_recommended, -r.score, r.name))
    # portfolio optimisation: one recommendation per gap (smallest high-performing set)
    chosen: dict[str, Recommendation] = {}
    for r in recs:
        if r.install_recommended:
            for gap in r.gaps:
                if gap not in chosen:
                    chosen[gap] = r
    picked = {r.candidate_id for r in chosen.values()}
    for r in recs:
        if r.install_recommended and r.candidate_id not in picked:
            r.install_recommended = False
            r.reasons.append("a stronger candidate already covers the same gap")
    summary = ("No additional skills are necessary: " + (
        "no evidence-backed capability gap was found" if not profile.get("gaps") else
        "no eligible candidate addresses a gap strongly enough")) if not picked else \
        f"{len(picked)} skill(s) recommended for {len(chosen)} gap(s)"
    return {"summary": summary, "recommendations": [r.to_json() for r in recs],
            "gaps_without_candidates": sorted(set(g["id"] for g in profile.get("gaps", [])) -
                                              {g for r in recs for g in r.gaps})}


def coverage_map(profile: dict[str, Any], existing: dict[str, str], lock: dict[str, Any],
                 episodes_skill_stats: dict[tuple[str, int], dict[str, int]]) -> dict[str, Any]:
    """Requirements → tasks → tools/skills → verified outcomes."""
    from .radar import GAP_KEYWORDS
    rows = []
    for gap in profile.get("gaps", []):
        from .adapters.claude_content import NATIVE_MANAGEMENT_SKILLS
        native = {c.lstrip("/").split()[0] for c in gap.get("covered_by", [])} | set(NATIVE_MANAGEMENT_SKILLS)
        skills = sorted(name for name, text in existing.items() if name not in native
                        and any(k in text for k in GAP_KEYWORDS.get(gap["id"], ())))
        outcomes = {s: sum(v.values()) for (s, _), v in episodes_skill_stats.items() if s in skills}
        rows.append({"gap": gap["id"], "title": gap["title"], "evidence": gap["evidence"],
                     "strength": gap["strength"], "skills": skills,
                     "covered_by_native": gap.get("covered_by", []),
                     "sessions_with_outcomes": outcomes,
                     "status": "covered" if skills or gap.get("covered_by") else "gap"})
    third_party = {n: e.get("evidence", {}).get("status", "not evaluated")
                   for n, e in (lock.get("skills") or {}).items()}
    weak = sorted(n for n, s in third_party.items() if s == "not evaluated")
    redundant = []
    names = sorted(existing)
    from .skills_lab import overlap
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if overlap(existing[a], existing[b]) >= 0.5:
                redundant.append([a, b])
    return {"capabilities": rows, "third_party_evidence": third_party,
            "weak_evidence": weak, "redundant_pairs": redundant}
