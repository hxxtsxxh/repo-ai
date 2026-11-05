"""Continuous optimisation: zero-value detection, a context-budget governor,
research proposals and the Self-Improvement Governor.

Everything here is computed from records repo-ai already keeps on this
machine (episodes, flight recorder, lab experiments, the skill portfolio).
Nothing is sent anywhere and nothing changes unless `repo-ai optimize
--apply` is run, and even then only within the governor's rules:

* only **tunable, repo-ai-owned retrieval knobs** (`TUNABLE`), never
  permissions, hooks, installs, network access, or user-authored files;
* never a key the user (or the repository) set explicitly: explicit
  settings always win over tuning;
* only with enough evidence (`MIN_PROMPTS`), in bounded steps (at most
  halving or doubling), at most one change per `RATE_LIMIT_S`;
* every change is journaled and revertible (`optimize --revert`), and a
  change is proposed for revert when later evidence shows it hurt.

Tuned values live outside the repository (`registry.machine_dir`, keyed by
the checkout's identity), so they never leak into a committed file or to
teammates, and a cloned repository cannot plant them.

Episode evidence is observational: an edit after a prompt is a proxy for
"this file mattered", not proof. Proposals say which metric would confirm
them and how to run the controlled experiment.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TUNABLE: dict[str, tuple[int, int]] = {"hook_max_files": (2, 8), "hook_budget_tokens": (400, 1600)}
MIN_PROMPTS = 12
MIN_SESSIONS = 10
RATE_LIMIT_S = 7 * 86400
COVERAGE = 0.9  # keep the edited file in the shortlist for this share of prompts
ENTRY_TOKENS = 32  # rough size of one shortlist line (estimate)


# --------------------------------------------------------------------------
# tuning layer (machine-local, below every explicit setting)
# --------------------------------------------------------------------------
def tuning_path(layout) -> Path:
    from .registry import machine_dir
    return machine_dir(layout.root) / "tuning.json"


def journal_path(layout) -> Path:
    from .registry import machine_dir
    return machine_dir(layout.root) / "optimize-journal.json"


def load_tuning(layout) -> dict[str, int]:
    try:
        data = json.loads(tuning_path(layout).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for key, value in (data.items() if isinstance(data, dict) else []):
        bounds = TUNABLE.get(key)
        if bounds and isinstance(value, int) and bounds[0] <= value <= bounds[1]:
            out[key] = value
    return out


def apply_tuning(cfg, layout):
    """Overlay governor-applied values on keys nobody set explicitly."""
    explicit = set(cfg.extra.get("_explicit_keys", ()))
    applied = {}
    for key, value in load_tuning(layout).items():
        if key not in explicit:
            setattr(cfg, key, value)
            applied[key] = value
    if applied:
        cfg.extra["_tuned"] = applied
    return cfg


def load_journal(layout) -> list[dict[str, Any]]:
    try:
        data = json.loads(journal_path(layout).read_text("utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(path: Path, data: Any) -> None:
    from .fsutil import atomic_write
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# evidence from episodes
# --------------------------------------------------------------------------
def _prompt_edits(ep: dict[str, Any]) -> list[tuple[dict[str, Any], set[str]]]:
    """Each prompt with the files edited after it and before the next one."""
    prompts = sorted(ep.get("prompts") or [], key=lambda p: p.get("t", 0))
    edits = [(int(t), str(p)) for t, p in ep.get("edits") or []]
    out = []
    for i, pr in enumerate(prompts):
        start = pr.get("t", 0)
        end = prompts[i + 1].get("t", math.inf) if i + 1 < len(prompts) else math.inf
        out.append((pr, {p for t, p in edits if start <= t < end}))
    return out


def injection_stats(episodes: list[dict[str, Any]], since: float = 0, until: float = math.inf
                    ) -> dict[str, Any]:
    """How well the prompt hook's shortlist predicted the files then edited."""
    rows: list[dict[str, Any]] = []
    for ep in episodes:
        for pr, edited in _prompt_edits(ep):
            if not (since <= pr.get("t", 0) < until) or not edited:
                continue
            injected = list(pr.get("injected") or [])
            cands = [str(c[0]) for c in pr.get("cands") or [] if c]
            ranks = [cands.index(p) + 1 for p in edited if p in cands]
            rows.append({"injected": len(injected),
                         "hit": bool(set(injected) & edited),
                         "precision": len(set(injected) & edited) / len(injected) if injected else None,
                         "first_rank": min(ranks) if ranks else None})
    injected_rows = [r for r in rows if r["injected"]]
    precisions = [r["precision"] for r in injected_rows if r["precision"] is not None]
    return {
        "prompts_with_edits": len(rows),
        "prompts_injected": len(injected_rows),
        "hit_rate": round(sum(r["hit"] for r in injected_rows) / len(injected_rows), 3)
        if injected_rows else None,
        "precision": round(sum(precisions) / len(precisions), 3) if precisions else None,
        "mean_injected": round(sum(r["injected"] for r in injected_rows) / len(injected_rows), 2)
        if injected_rows else None,
        "first_ranks": sorted(r["first_rank"] for r in rows if r["first_rank"] is not None),
    }


def _quantile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


# --------------------------------------------------------------------------
# proposals
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Proposal:
    id: str
    kind: str  # tune | revert | disable | experiment | retrieval | skill
    title: str
    hypothesis: str
    evidence: list[str]
    experiment: str  # how to confirm it (command)
    metric: str
    risk: str
    change: dict[str, Any] | None = None  # {"key", "from", "to"} for tune/revert
    governor: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def budget_governor(episodes: list[dict[str, Any]], cfg) -> tuple[dict[str, Any], Proposal | None]:
    """Context-budget governor: size the shortlist to what sessions use."""
    stats = injection_stats(episodes)
    current = int(cfg.hook_max_files)
    stats["current_max_files"] = current
    ranks = stats["first_ranks"]
    if stats["prompts_injected"] < MIN_PROMPTS or len(ranks) < MIN_PROMPTS // 2:
        stats["status"] = (f"insufficient evidence ({stats['prompts_injected']} injected prompts "
                           f"followed by edits; {MIN_PROMPTS} needed)")
        return stats, None
    k = max(TUNABLE["hook_max_files"][0], _quantile(ranks, COVERAGE))
    stats["coverage_rank"] = k
    lo, hi = max(TUNABLE["hook_max_files"][0], math.ceil(current / 2)), min(TUNABLE["hook_max_files"][1],
                                                                             current * 2)
    target = min(max(k, lo), hi)
    stats["status"] = "measured"
    if target == current:
        return stats, None
    beyond = sum(1 for r in ranks if r > target)
    if target < current:
        title = f"shrink the prompt shortlist from {current} to {target} files"
        hypothesis = (f"in {COVERAGE:.0%} of prompts the first edited file ranked within the top "
                      f"{k}; files below that cost ~{(current - target) * ENTRY_TOKENS} tokens per "
                      "injection without being used")
        risk = f"{beyond} of {len(ranks)} observed prompts had their first edited file below rank {target}"
    else:
        title = f"widen the prompt shortlist from {current} to {target} files"
        hypothesis = (f"the first edited file ranked below {current} in "
                      f"{sum(1 for r in ranks if r > current)} of {len(ranks)} prompts")
        risk = f"~{(target - current) * ENTRY_TOKENS} more tokens per injection"
    step_note = " (step-limited)" if target != k else ""
    return stats, Proposal(
        f"tune-hook_max_files-{target}", "tune", title + step_note, hypothesis,
        [f"{stats['prompts_injected']} injected prompts followed by edits",
         f"hit rate {stats['hit_rate']}, precision {stats['precision']}",
         f"first-edited-file rank p90 = {k}"],
        "repo-ai eval coding --compare core,full  (controlled; billable) or keep observing",
        "hit rate (an injected file was edited) must not drop; injected tokens fall",
        risk, {"key": "hook_max_files", "from": current, "to": target})


def _front_matter(text: str) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip().strip('"')
    return out


def installed_skills(root: Path) -> list[dict[str, Any]]:
    from .adapters.claude_content import CURATED_SKILL_NAMES, NATIVE_MANAGEMENT_SKILLS
    from .portfolio import load_lock
    third = set(load_lock(root)["skills"])
    out = []
    base = root / ".claude" / "skills"
    for skill_md in sorted(base.glob("*/SKILL.md")) if base.is_dir() else []:
        name = skill_md.parent.name
        try:
            front = _front_matter(skill_md.read_text("utf-8", errors="replace"))
        except OSError:
            continue
        manual = front.get("disable-model-invocation", "").lower() == "true"
        origin = ("native" if name in CURATED_SKILL_NAMES or name in NATIVE_MANAGEMENT_SKILLS else
                  "third-party" if name in third else "generated" if name.startswith("repo-") else "user")
        standing = 0 if manual else math.ceil(len(front.get("description", "")) / 4) + 4
        out.append({"name": name, "origin": origin, "manual_only": manual, "standing_tokens": standing})
    return out


def zero_value(root: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Assets that cost context every session but show no use."""
    sessions = [ep for ep in episodes if ep.get("prompts")]
    used: dict[str, int] = {}
    for ep in sessions:
        for name in {str(s[1]) for s in ep.get("skills") or [] if len(s) >= 2}:
            used[name] = used.get(name, 0) + 1
    rows = []
    for s in installed_skills(root):
        uses = used.get(s["name"], 0)
        if len(sessions) < MIN_SESSIONS:
            status = "insufficient evidence"
        elif s["manual_only"]:
            status = "no standing cost (manual-only)"
        elif uses == 0:
            status = "zero-value"
        else:
            status = "used"
        rows.append({**s, "sessions_used": uses, "status": status,
                     "context_tokens_spent_est": s["standing_tokens"] * len(sessions)})
    inj = injection_stats(episodes)
    hook = {"prompts_injected": inj["prompts_injected"], "hit_rate": inj["hit_rate"],
            "status": "insufficient evidence" if inj["prompts_injected"] < MIN_PROMPTS else
            ("zero-value" if (inj["hit_rate"] or 0) < 0.2 else "useful")}
    return {"sessions": len(sessions), "skills": rows, "prompt_hook": hook,
            "not_observable": ["subagent use (Claude Code does not report it to hooks repo-ai uses)",
                               "learned rules (they are read, not invoked)"]}


def skill_evolution(layout, episodes: list[dict[str, Any]]) -> list[Proposal]:
    """Evolution proposals for repo-ai-generated skills (never user skills):
    revise a skill whose sessions verify less often than comparable sessions
    without it, and settle a canary when two versions both have outcomes."""
    from .skills import SkillState
    from .skills_lab import fisher_two_sided
    state = SkillState.load(layout)
    edited = [ep for ep in episodes if ep.get("edits")]
    out = []
    for name, entry in sorted(state.entries.items()):
        if entry.get("status") not in (None, "active"):
            continue
        uses = [ep for ep in edited if any(len(s) >= 2 and s[1] == name for s in ep.get("skills") or [])]
        rest = [ep for ep in edited if ep not in uses]
        a, b = (sum(1 for ep in uses if ep.get("status") == "verified"),
                sum(1 for ep in rest if ep.get("status") == "verified"))
        if len(uses) >= 5 and len(rest) >= 5:
            p = fisher_two_sided(a, len(uses) - a, b, len(rest) - b)
            if a / len(uses) < b / len(rest) and p < 0.1:
                out.append(Proposal(
                    f"evolve-{name}", "skill", f"revise /{name}: its sessions verify less often",
                    "the skill's procedure may steer sessions wrong (association, not proof)",
                    [f"verified {a}/{len(uses)} with it vs {b}/{len(rest)} without (Fisher p={p:.3f})"],
                    f"repo-ai skills diff {name}; repo-ai skills draft {name} --dry-run; then "
                    f"repo-ai skills canary {name}", "verified-session rate of the new version",
                    "confounded by task difficulty: harder tasks may pick the skill"))
        versions = {int(h["version"]) for h in entry.get("history", []) if h.get("version")}
        versions.add(int(entry.get("version", 1) or 1))
        if len(versions) >= 2:
            last_two = sorted(versions)[-2:]
            counts = {v: sum(1 for ep in edited for s in ep.get("skills") or []
                             if len(s) >= 3 and s[1] == name and int(s[2]) == v) for v in last_two}
            if all(n >= 5 for n in counts.values()):
                out.append(Proposal(
                    f"canary-{name}", "skill", f"settle the canary for /{name}",
                    "both versions have enough sessions to compare",
                    [f"v{v}: {n} uses" for v, n in counts.items()],
                    f"repo-ai skills canary {name}  (then --apply to retire the worse version)",
                    "verified-session rate (Fisher exact)", "low; retired versions stay in history"))
    return out


def _experiments() -> list[dict[str, Any]]:
    from . import coding_lab as lab
    try:
        return lab.list_experiments()
    except (OSError, ValueError):
        return []


def mission_stats(root: Path) -> dict[str, Any]:
    """Read-only summary of local Reality Engine missions without creating directories."""
    from .mission.ledger import Store
    store = Store(root)
    if not store.folder.is_dir():
        return {
            "missions_total": 0,
            "verified_pass": 0,
            "failed_or_inconclusive": 0,
            "tournaments": 0,
            "mean_seconds_used": None,
            "by_provider": {},
        }
    total = 0
    passed = 0
    failed = 0
    tournaments = 0
    durations: list[float] = []
    by_provider: dict[str, dict[str, int]] = {}
    for path in sorted(store.folder.glob("*.json")):
        try:
            data = store.load(path.stem)
        except (OSError, ValueError):
            continue
        total += 1
        if data.get("kind") == "comparison":
            tournaments += 1
        verdict = (data.get("passport") or {}).get("verdict", "BLOCKED")
        if data.get("state") == "COMPLETE" and verdict == "PASS":
            passed += 1
        else:
            failed += 1
        sec = data.get("seconds_used")
        if isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec >= 0:
            durations.append(float(sec))
        prov = str((data.get("provider") or {}).get("name") or ("comparison" if data.get("kind") == "comparison" else "unknown"))
        slot = by_provider.setdefault(prov, {"runs": 0, "verified": 0})
        slot["runs"] += 1
        if data.get("state") == "COMPLETE" and verdict == "PASS":
            slot["verified"] += 1
    return {
        "missions_total": total,
        "verified_pass": passed,
        "failed_or_inconclusive": failed,
        "tournaments": tournaments,
        "mean_seconds_used": round(sum(durations) / len(durations), 3) if durations else None,
        "by_provider": by_provider,
    }


def proposals(root: Path, cfg, layout, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Research proposals: hypotheses with the evidence and the experiment
    that would confirm them. Only `tune`/`revert` can be applied automatically."""
    from . import episodes as ep_mod
    from .portfolio import load_lock
    out: list[Proposal] = []
    gov_stats, tune = budget_governor(episodes, cfg)
    journal = load_journal(layout)
    active = [j for j in journal if j.get("active")]
    for j in active:
        before = injection_stats(episodes, until=j["ts"])
        after = injection_stats(episodes, since=j["ts"])
        j["observed"] = {"before": before["hit_rate"], "after": after["hit_rate"],
                         "after_n": after["prompts_injected"]}
        if (after["prompts_injected"] >= MIN_PROMPTS and before["hit_rate"] is not None
                and after["hit_rate"] is not None and after["hit_rate"] < before["hit_rate"] - 0.1):
            out.append(Proposal(
                f"revert-{j['id']}", "revert", f"revert {j['key']} {j['from']} → {j['to']}",
                "the hit rate fell after this change", [
                    f"hit rate before {before['hit_rate']} (n={before['prompts_injected']}), after "
                    f"{after['hit_rate']} (n={after['prompts_injected']})"],
                f"repo-ai optimize --revert {j['id']}", "hit rate recovers", "none: restores the "
                "previous value", {"key": j["key"], "from": j["to"], "to": j["from"], "journal": j["id"]}))
    if tune and tune.change and not any(j["key"] == tune.change["key"] and j["to"] == tune.change["to"]
                                        for j in active):
        out.append(tune)
    zv = zero_value(root, episodes)
    for s in zv["skills"]:
        if s["status"] == "zero-value":
            cmd = (f"repo-ai skills disable {s['name']}" if s["origin"] in {"third-party", "generated"}
                   else "(your own skill: review it yourself)" if s["origin"] == "user"
                   else "set skills_mode or write_claude_skills in .repo-ai/config.toml")
            out.append(Proposal(
                f"zero-value-{s['name']}", "disable", f"/{s['name']} was never used",
                f"it costs ~{s['standing_tokens']} tokens of skill listing in every session",
                [f"0 uses in {zv['sessions']} recorded sessions",
                 f"~{s['context_tokens_spent_est']} tokens spent (estimate)"],
                cmd, "no change in session outcomes after removal", "the skill may matter for rare "
                "tasks the sample did not include"))
    out.extend(skill_evolution(layout, episodes))
    if zv["prompt_hook"]["status"] == "zero-value":
        out.append(Proposal(
            "experiment-ablate-hooks", "experiment", "the prompt shortlist rarely names the edited files",
            "prompt injection is not helping in this repository",
            [f"hit rate {zv['prompt_hook']['hit_rate']} over {zv['prompt_hook']['prompts_injected']} prompts"],
            "repo-ai eval ablate --feature hooks --max-cost-usd <budget>", "task success without "
            "hooks is not lower", "removing hooks also removes freshness refreshes"))
    for f in ep_mod.friction(episodes):
        out.append(Proposal(
            f"friction-{f.kind}", "retrieval", f.summary, "repeated waste with a known cause",
            [f.evidence], f.suggestion, "the pattern stops recurring", "low"))
    shadow = ep_mod.shadow_evaluate(episodes)
    if shadow.get("promotable") and not ep_mod.load_prior(layout):
        out.append(Proposal(
            "promote-outcome-prior", "retrieval", "promote the outcome prior",
            f"recorded sessions rank edited files higher with the prior ({shadow.get('criteria')})",
            [f"MRR {shadow.get('mrr_recorded')} → {shadow.get('mrr_with_prior')}"],
            "repo-ai learn approve ranking", "first-edited-file rank improves", "bounded adjustment"))
    lock = load_lock(root)
    for name, entry in sorted(lock["skills"].items()):
        evidence = (entry.get("evidence") or {}).get("status", "not evaluated")
        if entry.get("status") == "active" and evidence in {"not evaluated", "fake"}:
            out.append(Proposal(
                f"trial-{name}", "experiment", f"third-party /{name} has no measured benefit",
                "it may not improve outcomes", [f"evidence: {evidence}"],
                f"repo-ai skills benchmark {name} --max-cost-usd <budget>  (billable)",
                "paired task success with vs without the skill", "a pilot is directional only"))
    live = [e for e in _experiments() if not e.get("fake") and not e.get("dry_run")]
    if not live:
        out.append(Proposal(
            "experiment-pilot", "experiment", "no live coding-performance experiment exists",
            "repo-ai's effect on task success is UNVERIFIED until measured",
            ["0 live experiments recorded"],
            "repo-ai eval coding --pilot --compare baseline,core,full --max-cost-usd <budget>",
            "paired task success (McNemar), cost, turns", "billable; small samples are directional"))
    mstats = mission_stats(root)
    if mstats["missions_total"] >= 3 and mstats["verified_pass"] == 0:
        out.append(Proposal(
            "mission-acceptance-review", "experiment",
            "recorded missions have 0 verified passes",
            "task scope or --allow-write paths may be under-specified for the failing suite",
            [f"0/{mstats['missions_total']} recorded missions reached PASS"],
            "repo-ai why-test-failed <mission_id> --json",
            "verified mission pass rate", "low; local read-only diagnosis"))
    elif mstats["verified_pass"] >= 1:
        out.append(Proposal(
            "mission-verified-playbook", "skill",
            "distill verified mission traces into a reusable local repair playbook",
            "completed missions passed baseline-to-candidate and full regression verification",
            [f"{mstats['verified_pass']}/{mstats['missions_total']} missions verified PASS"],
            "repo-ai skills list",
            "reuse verified write-path and acceptance contracts on future tasks",
            "quarantined until human review; never overwrites user-owned skills"))
    return {"governor": gov_stats, "journal": journal, "zero_value": zv,
            "missions": mstats,
            "proposals": [govern(p, cfg, layout, journal) for p in out]}


# --------------------------------------------------------------------------
# Self-Improvement Governor
# --------------------------------------------------------------------------
def govern(p: Proposal, cfg, layout, journal: list[dict[str, Any]], now: float | None = None) -> Proposal:
    now = time.time() if now is None else now
    reasons: list[str] = []
    if p.kind not in {"tune", "revert"} or not p.change:
        reasons.append(f"{p.kind} proposals need a human: the governor only tunes repo-ai's own "
                       "retrieval knobs")
    else:
        key, to = p.change["key"], p.change["to"]
        bounds = TUNABLE.get(key)
        if not bounds:
            reasons.append(f"{key} is not tunable")
        elif not (bounds[0] <= int(to) <= bounds[1]):
            reasons.append(f"{key}={to} is outside {bounds}")
        if key in set(cfg.extra.get("_explicit_keys", ())):
            reasons.append(f"{key} is set explicitly in your configuration; explicit settings win")
        if p.kind == "tune":
            current = int(p.change["from"])
            if current and not (current / 2 <= int(to) <= current * 2):
                reasons.append("change is larger than one bounded step")
            last = max((j["ts"] for j in journal if j.get("kind") == "tune"), default=0)
            if now - last < RATE_LIMIT_S:
                reasons.append(f"rate limit: one change per {RATE_LIMIT_S // 86400} days "
                               f"(last {int((now - last) // 3600)} h ago)")
    p.governor = {"auto_apply": not reasons, "reasons": reasons or ["within the governor's rules"]}
    return p


def apply(layout, cfg, plan: dict[str, Any], ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Apply governor-approved tune/revert proposals (all, or the named ones)."""
    applied = []
    journal = load_journal(layout)
    tuning = load_tuning(layout)
    for p in plan["proposals"]:
        if ids and p["id"] not in ids:
            continue
        if not p["governor"]["auto_apply"]:
            if ids:
                raise ValueError(f"{p['id']}: not allowed by the governor: {'; '.join(p['governor']['reasons'])}")
            continue
        ch = p["change"]
        if p["kind"] == "revert":
            _revert_entry(journal, tuning, ch["journal"])
            applied.append({"id": p["id"], "reverted": ch["journal"]})
            continue
        entry = {"id": f"opt-{int(time.time())}-{len(journal)}", "ts": int(time.time()), "kind": "tune",
                 "key": ch["key"], "from": ch["from"], "to": ch["to"], "proposal": p["id"],
                 "evidence": p["evidence"], "active": True}
        tuning[ch["key"]] = int(ch["to"])
        journal.append(entry)
        applied.append(entry)
    if applied:
        _save(tuning_path(layout), tuning)
        _save(journal_path(layout), journal)
    return applied


def _revert_entry(journal: list[dict[str, Any]], tuning: dict[str, int], entry_id: str) -> dict[str, Any]:
    entry = next((j for j in journal if j.get("id") == entry_id and j.get("active")), None)
    if entry is None:
        raise ValueError(f"no active optimisation {entry_id!r}")
    entry["active"] = False
    entry["reverted_at"] = int(time.time())
    earlier = [j for j in journal if j.get("active") and j["key"] == entry["key"]]
    if earlier:
        tuning[entry["key"]] = int(earlier[-1]["to"])
    else:
        tuning.pop(entry["key"], None)
    return entry


def revert(layout, entry_id: str | None = None) -> list[dict[str, Any]]:
    """Revert one journaled change, or every active one."""
    journal = load_journal(layout)
    tuning = load_tuning(layout)
    targets = [entry_id] if entry_id else [j["id"] for j in reversed(journal) if j.get("active")]
    out = [_revert_entry(journal, tuning, t) for t in targets]
    _save(tuning_path(layout), tuning)
    _save(journal_path(layout), journal)
    return out


# --------------------------------------------------------------------------
# performance view
# --------------------------------------------------------------------------
def performance(root: Path, cfg, layout, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    from . import coding_lab as lab
    from . import episodes as ep_mod
    from . import flight
    entries = [e for e in flight.entries(layout, limit=500) if e.get("event") == "prompt"]
    elapsed = sorted(int(e["elapsed_ms"]) for e in entries if isinstance(e.get("elapsed_ms"), (int, float)))
    hook: dict[str, Any] = {"status": "not recorded (flight_recorder is off)" if not entries else "measured",
                            "prompts": len(entries)}
    if entries:
        injected = [e for e in entries if e.get("decision") == "injected"]
        hook.update(injection_rate=round(len(injected) / len(entries), 3),
                    tokens_mean=round(sum(int(e.get("tokens_est") or 0) for e in injected)
                                      / len(injected), 1) if injected else 0,
                    latency_ms_p50=_quantile(elapsed, 0.5) if elapsed else None,
                    latency_ms_p95=_quantile(elapsed, 0.95) if elapsed else None)
    experiments = []
    for meta in _experiments()[-5:]:
        try:
            _, runs = lab.load_runs(meta["id"])
        except SystemExit:
            continue
        summary = lab.summarize(runs) if runs else {}
        experiments.append({"id": meta["id"], "kind": "fake" if meta.get("fake") else
                            ("dry-run" if meta.get("dry_run") else "live"),
                            "runs": len(runs), "arms": {a: {k: v.get(k) for k in ("n", "success_rate",
                                                                                   "mean_cost_usd")}
                                                        for a, v in (summary.get("arms") or {}).items()}})
    stats = ep_mod.stats(episodes)
    return {"sessions": {"status": "measured" if stats["sessions"] else
                         "not recorded (learning_signals = \"outcomes\" enables it)", **stats},
            "prompt_hook": hook, "shortlist": injection_stats(episodes) | {"first_ranks": None},
            "outcome_prior": ep_mod.shadow_evaluate(episodes),
            "missions": mission_stats(root),
            "experiments": experiments or "none recorded",
            "task_success": "UNVERIFIED: no live experiment" if not any(
                e["kind"] == "live" for e in experiments) else "see experiments (live)",
            "tuning": load_tuning(layout)}
