"""Episodic outcomes: what happened in each Claude session, minimally.

Recorded only with `learning_signals = "outcomes"` (which `--smart` turns
on). Everything stays in the machine-local state directory
(`state/episodes/<session-hash>.json`). Per session:

* for each prompt, its task classes, the ranked candidate files and which of
  them were injected, but **never the prompt text**;
* repository-relative paths Claude edited (from the existing edit hook);
* which of the repository's *known* commands ran, their kind
  (test/lint/build) and whether Claude Code reported failure, but **never
  the command output, and never unknown commands**;
* a status computed at `Stop`:

  ========== ==========================================================
  verified   a known test command passed *after* the last edit
  failed     the last known test command after the last edit failed
  unverified files were edited but no test ran after the last edit
  no-change  nothing was edited
  ========== ==========================================================

  "verified" means tests passed, not that the task was done: a session can
  pass tests and still be wrong. repo-ai never infers task success.

From those records, repo-ai can propose an **outcome prior**: a small,
bounded per-file ranking adjustment. It is evaluated in shadow
(leave-one-session-out, on recorded candidate lists only) and used by
retrieval only after promotion. The **friction radar** turns repeated waste
into a short digest.

Retention: 30 days and 400 sessions by default. `repo-ai learn forget`
deletes the records.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .locks import file_lock

VERSION = 1
MAX_PROMPTS, MAX_EDITS, MAX_COMMANDS = 20, 200, 100
RETENTION_DAYS, MAX_SESSIONS = 30, 400
# Fields an episode may contain. `privacy audit` flags anything else.
ALLOWED_KEYS = frozenset({"v", "session", "started", "updated", "prompts", "edits", "commands",
                          "skills", "status", "tool_version"})
ALLOWED_PROMPT_KEYS = frozenset({"t", "intents", "cands", "injected", "confidence", "stale"})


def enabled(cfg) -> bool:
    return getattr(cfg, "learning_signals", "off") == "outcomes"


def session_hash(session_id: str) -> str:
    return hashlib.sha256(("repo-ai:" + (session_id or "")).encode()).hexdigest()[:10]


def _dir(layout) -> Path:
    return layout.state_dir / "episodes"


def _path(layout, session: str) -> Path:
    return _dir(layout) / f"{session_hash(session)}.json"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except OSError:
        return None
    except ValueError:
        _quarantine(path)
        return None
    if not isinstance(data, dict):
        _quarantine(path)
        return None
    return data


def _quarantine(path: Path) -> None:
    """Move a corrupt state file aside so it cannot disable a feature forever."""
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
    except OSError:
        pass


def _well_formed(data: dict[str, Any]) -> bool:
    try:
        for key in ("prompts", "edits", "commands", "skills"):
            if not isinstance(data.get(key, []), list):
                return False
        for t, p in data.get("edits", []):
            int(t), str(p)
        for t, _k, _c, _ok in data.get("commands", []):
            int(t)
        for prompt in data.get("prompts", []):
            if not isinstance(prompt, dict):
                return False
        return True
    except (TypeError, ValueError):
        return False


def _update(layout, session: str, mutate) -> None:
    """Read-modify-write one session record under a short lock. Best effort:
    an episode is diagnostics, so contention or IO errors drop the event."""
    directory = _dir(layout)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with file_lock(directory / ".lock", timeout=1.5) as held:
            if not held:
                return
            path = _path(layout, session)
            now = int(time.time())
            loaded = _load(path)
            if loaded is not None and not _well_formed(loaded):
                _quarantine(path)
                loaded = None
            data = loaded or {"v": VERSION, "session": session_hash(session),
                                   "started": now, "prompts": [], "edits": [], "commands": [],
                                   "status": "no-change"}
            mutate(data)
            data["updated"] = now
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, path)
    except (OSError, TypeError, ValueError, KeyError, AttributeError):
        pass


# --------------------------------------------------------------------------
# recording (called from hooks)
# --------------------------------------------------------------------------
def note_prompt(layout, cfg, session: str, intents: list[str], candidates: list[tuple[str, float]],
                injected: list[str], confidence: str, stale: bool) -> None:
    if not enabled(cfg):
        return

    def mutate(data: dict[str, Any]) -> None:
        prompts = data.setdefault("prompts", [])
        prompts.append({"t": int(time.time()), "intents": list(intents)[:4],
                        "cands": [[p, round(float(s), 2)] for p, s in candidates[:10]],
                        "injected": list(injected)[:10], "confidence": confidence,
                        "stale": bool(stale)})
        del prompts[:-MAX_PROMPTS]
    _update(layout, session, mutate)


def note_edit(layout, cfg, session: str, rel: str) -> None:
    if not enabled(cfg) or not rel:
        return

    def mutate(data: dict[str, Any]) -> None:
        edits = data.setdefault("edits", [])
        edits.append([int(time.time()), rel])
        del edits[:-MAX_EDITS]
    _update(layout, session, mutate)


def note_command(layout, cfg, session: str, kind: str, command: str, ok: bool) -> None:
    if not enabled(cfg):
        return

    def mutate(data: dict[str, Any]) -> None:
        cmds = data.setdefault("commands", [])
        cmds.append([int(time.time()), kind, command, bool(ok)])
        del cmds[:-MAX_COMMANDS]
    _update(layout, session, mutate)


def note_skill(layout, cfg, session: str, name: str, version: int) -> None:
    if not enabled(cfg):
        return

    def mutate(data: dict[str, Any]) -> None:
        used = data.setdefault("skills", [])
        used.append([int(time.time()), name, int(version)])
        del used[:-50]
    _update(layout, session, mutate)


def skill_outcomes(episodes: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, int]]:
    """(skill, version) -> session counts by status."""
    out: dict[tuple[str, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ep in episodes:
        for name, version in {(n, int(v)) for _, n, v in ep.get("skills") or []}:
            out[(name, version)][ep.get("status", "no-change")] += 1
    return {k: dict(v) for k, v in out.items()}


def classify(data: dict[str, Any]) -> str:
    edits = data.get("edits") or []
    if not edits:
        return "no-change"
    last_edit = max(int(t) for t, _ in edits)
    tests = [c for c in data.get("commands") or [] if c[1] == "test" and int(c[0]) >= last_edit]
    if not tests:
        return "unverified"
    return "verified" if tests[-1][3] else "failed"


def close(layout, cfg, session: str) -> None:
    """At Stop: compute the status, then apply retention."""
    if not enabled(cfg):
        return
    from . import __version__

    def mutate(data: dict[str, Any]) -> None:
        data["status"] = classify(data)
        data["tool_version"] = __version__
    _update(layout, session, mutate)
    prune(layout)


# --------------------------------------------------------------------------
# reading, retention, forgetting
# --------------------------------------------------------------------------
def load_all(layout, max_age_days: int = RETENTION_DAYS) -> list[dict[str, Any]]:
    cutoff = time.time() - max_age_days * 86400
    out = []
    for path in sorted(_dir(layout).glob("*.json")):
        data = _load(path)
        if data is None:
            continue
        if not _well_formed(data):
            _quarantine(path)
            continue
        try:
            fresh = float(data.get("updated", 0)) >= cutoff
        except (TypeError, ValueError):
            fresh = False
        if fresh:
            out.append(data)
    return sorted(out, key=lambda d: (d.get("started", 0), d.get("session", "")))


def prune(layout, max_age_days: int = RETENTION_DAYS, max_sessions: int = MAX_SESSIONS) -> int:
    cutoff = time.time() - max_age_days * 86400
    files = []
    for path in _dir(layout).glob("*.json"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort()
    removed = 0
    for i, (mtime, path) in enumerate(files):
        if mtime < cutoff or i < len(files) - max_sessions:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def forget(layout, older_than_days: int | None = None) -> int:
    if older_than_days is not None:
        return prune(layout, max_age_days=older_than_days, max_sessions=10**9)
    removed = 0
    for path in _dir(layout).glob("*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    try:
        _dir(layout).rmdir()
    except OSError:
        pass
    return removed


# --------------------------------------------------------------------------
# outcome prior: proposal, shadow evaluation, promotion
# --------------------------------------------------------------------------
PRIOR_STRENGTH = 0.3     # score x (1 + strength x delta), delta in [-1, 1]: at most ±30 %
MIN_PROMPTS, MIN_SESSIONS, MIN_GAIN = 8, 3, 0.02


def _useful_prompts(episodes: list[dict[str, Any]]):
    for ep in episodes:
        if ep.get("status") not in {"verified", "unverified"}:
            continue  # failed sessions are not evidence of where the fix belongs
        edited = {p for _, p in ep.get("edits") or []}
        if not edited:
            continue
        for prompt in ep.get("prompts") or []:
            if prompt.get("cands"):
                yield ep.get("session", ""), prompt, edited


def compute_prior(episodes: list[dict[str, Any]], exclude: str | None = None) -> dict[str, float]:
    useful: dict[str, float] = defaultdict(float)
    unused: dict[str, float] = defaultdict(float)
    seen: dict[str, int] = defaultdict(int)
    for session, prompt, edited in _useful_prompts(episodes):
        if session == exclude:
            continue
        for path, _ in prompt["cands"]:
            seen[path] += 1
            if path in edited:
                useful[path] += 1.0
            else:
                unused[path] += 1.0
    prior = {}
    for path, n in seen.items():
        value = (useful[path] - 0.35 * unused[path]) / (n + 2.0)
        if abs(value) >= 0.05:
            prior[path] = round(max(-1.0, min(1.0, value)), 3)
    return prior


def apply_prior(score: float, delta: float) -> float:
    """The one place the outcome prior's effect is defined (retrieval uses it too)."""
    return score * (1.0 + PRIOR_STRENGTH * max(-1.0, min(1.0, delta)))


def _rank_of_first(cands: list[list[Any]], edited: set[str], prior: dict[str, float]) -> int | None:
    ordered = sorted(cands, key=lambda c: (-apply_prior(float(c[1]), prior.get(c[0], 0.0)), c[0]))
    for i, (path, _) in enumerate(ordered, 1):
        if path in edited:
            return i
    return None


def shadow_evaluate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Leave-one-session-out: each prompt is re-ranked with a prior learned
    from *other* sessions only, and compared with its recorded ranking."""
    rows = list(_useful_prompts(episodes))
    sessions = {s for s, _, _ in rows}
    base_rr, prior_rr, wins, losses = [], [], 0, 0
    priors: dict[str, dict[str, float]] = {}
    for session, prompt, edited in rows:
        if session not in priors:
            priors[session] = compute_prior(episodes, exclude=session)
        base = _rank_of_first(prompt["cands"], edited, {})
        new = _rank_of_first(prompt["cands"], edited, priors[session])
        if base is None:
            continue  # the edited file was never a candidate: a prior cannot help
        base_rr.append(1.0 / base)
        prior_rr.append(1.0 / new if new else 0.0)
        wins += int(bool(new and new < base))
        losses += int(not new or new > base)
    n = len(base_rr)
    mrr_base = round(sum(base_rr) / n, 3) if n else 0.0
    mrr_prior = round(sum(prior_rr) / n, 3) if n else 0.0
    enough = n >= MIN_PROMPTS and len(sessions) >= MIN_SESSIONS
    return {"prompts": n, "sessions": len(sessions), "mrr_recorded": mrr_base,
            "mrr_with_prior": mrr_prior, "gain": round(mrr_prior - mrr_base, 3),
            "wins": wins, "losses": losses, "enough_evidence": enough,
            "promotable": enough and mrr_prior >= mrr_base + MIN_GAIN and wins > losses,
            "criteria": f">= {MIN_PROMPTS} prompts over >= {MIN_SESSIONS} sessions, MRR gain "
                        f">= {MIN_GAIN}, more wins than losses (leave-one-session-out)"}


def ranking_path(layout) -> Path:
    return layout.state_dir / "ranking.json"


def load_prior(layout) -> dict[str, float]:
    data = _load(ranking_path(layout))
    if not data or data.get("status") != "active":
        return {}
    weights = data.get("weights")
    if not isinstance(weights, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in weights.items():
        try:
            out[str(k)] = max(-1.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            _quarantine(ranking_path(layout))
            return {}
    return out


def promote(layout, episodes: list[dict[str, Any]], force: bool = False) -> dict[str, Any]:
    evaluation = shadow_evaluate(episodes)
    if not evaluation["promotable"] and not force:
        return {"promoted": False, "evaluation": evaluation}
    weights = compute_prior(episodes)
    record = {"status": "active", "weights": weights, "evaluation": evaluation,
              "promoted_at": int(time.time()), "forced": force}
    path = ranking_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"promoted": True, "evaluation": evaluation, "files": len(weights)}


def demote(layout) -> bool:
    try:
        ranking_path(layout).unlink()
        return True
    except FileNotFoundError:
        return False


# --------------------------------------------------------------------------
# friction radar
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Friction:
    kind: str
    summary: str
    evidence: str
    suggestion: str
    weight: float = 0.0
    paths: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "summary": self.summary, "evidence": self.evidence,
                "suggestion": self.suggestion, "paths": self.paths}


def friction(episodes: list[dict[str, Any]], limit: int = 5) -> list[Friction]:
    out: list[Friction] = []
    missed: dict[str, set[str]] = defaultdict(set)
    for ep in episodes:
        injected = {p for pr in ep.get("prompts") or [] for p in pr.get("injected") or []}
        if not injected:
            continue
        for _, path in ep.get("edits") or []:
            if path not in injected:
                missed[path].add(ep.get("session", ""))
    for path, sessions in sorted(missed.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(sessions) >= 2:
            out.append(Friction(
                "missed-file", f"{path} was edited in {len(sessions)} sessions but never "
                "in repo-ai's injected shortlist",
                f"{len(sessions)} sessions", "check `repo-ai explain \"<a typical task>\"`; a "
                "docstring naming what the file does helps ranking", len(sessions), [path]))
    fails: dict[str, int] = defaultdict(int)
    oks: dict[str, int] = defaultdict(int)
    for ep in episodes:
        for _, _kind, cmd, ok in ep.get("commands") or []:
            (oks if ok else fails)[cmd] += 1
    for cmd, n in sorted(fails.items(), key=lambda kv: -kv[1]):
        if n >= 2 and oks.get(cmd, 0) == 0:
            out.append(Friction("failing-command", f"`{cmd}` failed {n} times and never passed",
                                f"{n} failures, 0 passes", "is it still the right command? "
                                "fix it in the manifest/Makefile, or `repo-ai learn reject` the "
                                "rule that recommends it", n))
    edited = [ep for ep in episodes if ep.get("edits")]
    unverified = [ep for ep in edited if ep.get("status") == "unverified"]
    if len(edited) >= 3 and len(unverified) / len(edited) >= 0.5:
        out.append(Friction("unverified", f"{len(unverified)} of {len(edited)} sessions with "
                            "edits ended without a test run after the last edit",
                            "session statuses", "use /repo-verify before finishing, or the "
                            "focused command repo-ai prints in each shortlist",
                            len(unverified)))
    stale = sum(1 for ep in episodes for pr in ep.get("prompts") or [] if pr.get("stale"))
    if stale >= 3:
        out.append(Friction("stale-context", f"{stale} prompts were answered from a stale index",
                            f"{stale} prompts", "check `repo-ai doctor --agent claude` (Stop "
                            "hook refresh) or lower refresh_debounce_seconds", stale))
    return sorted(out, key=lambda f: -f.weight)[:limit]


def stats(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    by_intent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ep in episodes:
        status = ep.get("status", "no-change")
        by_status[status] += 1
        intents = {i for pr in ep.get("prompts") or [] for i in pr.get("intents") or []}
        for intent in intents:
            by_intent[intent][status] += 1
    return {"sessions": len(episodes), "by_status": dict(sorted(by_status.items())),
            "by_intent": {k: dict(v) for k, v in sorted(by_intent.items())}}
