#!/usr/bin/env python3
"""Held-out-6 scorer (PROTOCOL.md Amendment 5). Frozen with the protocol:
it reads what `scenarios.py`, `wallclock.py`, `cancelprobe.py` and
`perf6.py` recorded and applies the rules below. It never re-runs anything.

    VEV_WORK=... python score6.py <project> [...] > heldout6-score.json

Definitions (Amendment 5, "Labels and rules"):
- pass-like: a verdict starting with one of `wallclock.PASSING`, or exit 0.
- failing state: the scenario's label has `new_failure` or `hang`, or a
  wallclock change has a non-empty affected set.
- false assurance (G1), any of, on a valid failing state:
  - a run with a pass-like verdict;
  - a run that reports a labelled failing file `pass` or `no-tests`;
  - `repo-ai evidence` reporting `current` or `same_behaviour` with a
    pass-like verdict;
  - the gate silent (with no earlier gate state) on a state with a code change.
- new failure reported as pre-existing (G2): on a valid state with a new
  failure, a verdict starting `failing (all failures pre-existing`, or a
  labelled file classified `already failing at the base (the same tests fail)`.
- miss: a failing state whose verdict is not `regression` (G3 counts only
  wallclock failing changes; scenarios report it per scenario).
- false alarm (G4): a `regression` verdict on a state without a new failure
  (wallclock passing changes, by its own rule; S1). S4 (flaky) is reported,
  not gated.
- tree integrity (G6): every run's `tree_unchanged`, except the C5 run the
  scenario edits on purpose.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import wallclock as W  # noqa: E402

PRE_SAME = "already failing at the base (the same tests fail)"
PRE_VERDICT = "failing (all failures pre-existing"
UNGATED = {"S4-flaky-unrelated"}
NO_GATE_CHECK = {"C8-committed-change"}
# without its dependencies the base fails the same way, so "pre-existing" is true there: G1 only
G1_ONLY = {"A2-no-deps-failing"}


def pass_like(run: dict) -> bool:
    v = str(run.get("verdict") or "")
    return v.startswith(W.PASSING) or (run.get("exit") == 0 and not run.get("error"))


def score_row(row: dict) -> dict:
    lab = row.get("label") or {}
    out: dict = {"id": row["id"], "valid": bool(lab.get("valid")), "why_invalid": lab.get("why_invalid")}
    runs = row.get("runs") or []
    if not lab.get("valid") or not (runs or row.get("evidence") or row.get("gate")):
        return out
    failing = bool(lab.get("new_failure") or lab.get("hang"))
    files = set(lab.get("files") or [])
    fa: list[str] = []
    g2: list[str] = []
    for i, r in enumerate(runs):
        if failing and pass_like(r):
            fa.append(f"run {i}: pass-like verdict {r.get('verdict')!r}")
        for res in r.get("results") or []:
            if failing and res.get("test") in files and res.get("status") in {"pass", "no-tests"}:
                fa.append(f"run {i}: {res['test']} reported {res['status']}")
            if lab.get("new_failure") and row["id"] not in G1_ONLY and res.get("test") in files and \
                    str(res.get("classification") or "").startswith(PRE_SAME):
                g2.append(f"run {i}: {res['test']} classified {res['classification']!r}")
        if lab.get("new_failure") and row["id"] not in G1_ONLY and str(r.get("verdict") or "").startswith(PRE_VERDICT):
            g2.append(f"run {i}: verdict {r.get('verdict')!r}")
    ev = row.get("evidence")
    if failing and ev and (ev.get("current") or ev.get("same_behaviour")) and \
            str(ev.get("verdict") or "").startswith(W.PASSING):
        fa.append(f"evidence: current={ev.get('current')} same_behaviour={ev.get('same_behaviour')} "
                  f"verdict {ev.get('verdict')!r}")
    gt = row.get("gate")
    if failing and gt and row["id"] not in NO_GATE_CHECK and gt.get("silent"):
        fa.append("gate: silent")
    verdicts = [r.get("verdict") for r in runs]
    out.update({
        "failing_state": failing, "verdicts": verdicts,
        "false_assurance": fa, "new_as_preexisting": g2,
        "missed": failing and lab.get("new_failure") and any(v != "regression" for v in verdicts),
        "false_alarm": (not failing) and row["id"] not in UNGATED and any(v == "regression" for v in verdicts),
        "flaky_false_alarms": sum(v == "regression" for v in verdicts) if row["id"] in UNGATED else None,
        "errors": [r.get("error") for r in runs if r.get("error")],
        "tree_changed": [i for i, r in enumerate(runs) if r.get("tree_unchanged") is False],
        "wall_s": [r.get("wall_s") for r in runs],
    })
    return out


def score_wallclock(proj: dict) -> dict:
    s = proj.get("session") or []
    fa = [x["id"] for x in s if x["truth_affected"] and str(x["verdict"]).startswith(W.PASSING)]
    rep = proj.get("repeat") or []
    cold = proj.get("cold") or []
    fa += [f"{r['id']} (repeat)" for r in rep for v in (r["again"], r["rerun"])
           if (next((x for x in s if x["id"] == r["id"]), {}).get("truth_affected")) and str(v).startswith(W.PASSING)]
    fa += [f"{r['id']} (cold)" for r in cold if (next((x for x in s if x["id"] == r["id"]), {}).get("truth_affected"))
           and str(r["cold"]).startswith(W.PASSING)]
    return {"summary": proj.get("summary"), "false_assurance": fa,
            "new_as_preexisting": sum(len(x["new_as_preexisting"]) for x in s),
            "failing": sum(1 for x in s if x["truth_affected"]),
            "detected": sum(1 for x in s if x["detected"]),
            "passing": sum(1 for x in s if not x["truth_affected"]),
            "false_alarms": [x["id"] for x in s if x["false_alarm"]],
            "tree_changed": [x["id"] for x in s if not x["tree_unchanged"]] +
            [r["id"] for r in rep if not r["tree_unchanged"]] + [r["id"] for r in cold if not r["tree_unchanged"]]}


def upper95(k: int, n: int) -> float | None:
    """One-sided 95% upper bound for a rate with k events in n trials (exact for k = 0)."""
    if n == 0:
        return None
    if k == 0:
        return round(1 - 0.05 ** (1 / n), 4)
    lo, hi = k / n, 1.0
    for _ in range(60):  # Clopper-Pearson by bisection
        mid = (lo + hi) / 2
        cdf = sum(math.comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(k + 1))
        lo, hi = (mid, hi) if cdf > 0.05 else (lo, mid)
    return round(hi, 4)


def unconfirmed(name: str) -> set[str]:
    """POST-HOC (`--recheck`): changes whose label `recheck6.py` did not
    reproduce (fewer than 2 of 3 quiet runs)."""
    p = H.WORK / f"recheck6-{name}.json"
    if not p.exists():
        return set()
    return {cid for cid, r in json.loads(p.read_text("utf-8"))["changes"].items() if not r["confirmed"]}


DEPENDS_ON_M = {"S3-mutation-in-failing-file"}  # labelled by composition with M, without re-running M there


def main() -> int:
    recheck = "--recheck" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    wall = {}
    p = H.WORK / "wallclock-heldout6-new.json"
    if p.exists():
        wall = json.loads(p.read_text("utf-8"))
    cancel = {}
    p = H.WORK / "cancelprobe-heldout6.json"
    if p.exists():
        cancel = json.loads(p.read_text("utf-8"))
    out: dict = {"projects": {}, "mode": "POST-HOC recheck (unconfirmed labels set aside)" if recheck else "frozen"}
    tot = {"failing_checks": 0, "false_assurance": [], "new_as_preexisting": [], "false_alarms": [],
           "tree_changed": [], "invalid": [], "wall_failing": 0, "wall_detected": 0, "cancel_unclean": []}
    for n in names:
        proj: dict = {}
        sp = H.WORK / f"scenarios-{n}.json"
        bad = unconfirmed(n) if recheck else set()
        if sp.exists():
            sc = json.loads(sp.read_text("utf-8"))
            m = (sc.get("picks") or {}).get("M")
            rows = [score_row(r) for r in sc.get("rows") or [] if not r["id"].startswith("setup-")
                    and not (recheck and m in bad and r["id"] in DEPENDS_ON_M)]
            proj["scenarios"] = rows
            proj["scenario_error"] = sc.get("error")
            for r in rows:
                if not r["valid"]:
                    tot["invalid"].append(f"{n}:{r['id']}: {r.get('why_invalid')}")
                    continue
                if r.get("failing_state"):
                    tot["failing_checks"] += 1
                tot["false_assurance"] += [f"{n}:{r['id']}: {x}" for x in r.get("false_assurance") or []]
                tot["new_as_preexisting"] += [f"{n}:{r['id']}: {x}" for x in r.get("new_as_preexisting") or []]
                if r.get("false_alarm"):
                    tot["false_alarms"].append(f"{n}:{r['id']}")
                tot["tree_changed"] += [f"{n}:{r['id']} run {i}" for i in r.get("tree_changed") or []]
        if n in wall and "session" in wall[n]:
            proj_wall = wall[n]
            if recheck and bad:  # POST-HOC: unconfirmed labels set aside
                proj_wall = {**proj_wall, "session": [x for x in proj_wall["session"] if x["id"] not in bad],
                             "repeat": [x for x in proj_wall.get("repeat") or [] if x["id"] not in bad],
                             "cold": [x for x in proj_wall.get("cold") or [] if x["id"] not in bad]}
                proj["recheck_set_aside"] = sorted(bad)
            w = score_wallclock(proj_wall)
            proj["wallclock"] = w
            tot["false_assurance"] += [f"{n}:wallclock {x}" for x in w["false_assurance"]]
            if w["new_as_preexisting"]:
                tot["new_as_preexisting"].append(f"{n}:wallclock {w['new_as_preexisting']} file(s)")
            tot["false_alarms"] += [f"{n}:wallclock {x}" for x in w["false_alarms"]]
            tot["tree_changed"] += [f"{n}:wallclock {x}" for x in w["tree_changed"]]
            tot["wall_failing"] += w["failing"]
            tot["wall_detected"] += w["detected"]
        elif n in wall:
            proj["wallclock_error"] = wall[n].get("error")
        if n in cancel:
            runs = cancel[n].get("runs") or []
            bad = [i for i, r in enumerate(runs) if not r.get("clean")]
            proj["cancel"] = {"runs": len(runs), "unclean": bad}
            tot["cancel_unclean"] += [f"{n} run {i}" for i in bad]
        out["projects"][n] = proj
    k = len(tot["false_assurance"])
    out["gates"] = {
        "G1_false_assurance": {"count": k, "met": k == 0, "items": tot["false_assurance"],
                               "scenario_failing_states": tot["failing_checks"],
                               "upper95_per_failing_state": upper95(0, tot["failing_checks"] + tot["wall_failing"])
                               if k == 0 else None},
        "G2_new_as_preexisting": {"count": len(tot["new_as_preexisting"]), "met": not tot["new_as_preexisting"],
                                  "items": tot["new_as_preexisting"]},
        "G3_runtime_no_miss": {"detected": tot["wall_detected"], "failing": tot["wall_failing"],
                               "rate": round(tot["wall_detected"] / tot["wall_failing"], 4) if tot["wall_failing"]
                               else None,
                               "met": bool(tot["wall_failing"]) and tot["wall_detected"] / tot["wall_failing"] >= 0.95},
        "G4_false_alarms": {"count": len(tot["false_alarms"]), "met": not tot["false_alarms"],
                            "items": tot["false_alarms"]},
        "G6_tree_unchanged": {"count": len(tot["tree_changed"]), "met": not tot["tree_changed"],
                              "items": tot["tree_changed"]},
        "G7_cancellation": {"unclean": tot["cancel_unclean"], "met": not tot["cancel_unclean"]},
        "invalid_scenarios": tot["invalid"],
    }
    json.dump(out, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
