#!/usr/bin/env python3
"""Held-out-6 POST-HOC label recheck (not part of the frozen protocol; reported
separately from `score6.py`'s frozen result).

Why: a ground-truth label comes from one run of each test file alone, three
files in parallel, on a host that was also running other work. On jsonic every
"affected" change is attributed to one file whose tests have a 5 s timeout
and that passes 7 of 7 times when run alone. Such a label can be load noise.

What: for each failing change a score uses (the wallclock session's failing
changes, and M/M2 of the scenarios), its affected files are run again in the
project's image, alone and sequentially, three times. The label is
**confirmed** when the set fails in at least 2 of the 3 runs, otherwise
**unconfirmed**. Nothing frozen is edited: this writes
`$VEV_WORK/recheck6-<project>.json`, and `score6.py --recheck` reports the
gates with unconfirmed labels set aside, next to the frozen numbers.

    VEV_WORK=... python recheck6.py <project> [...]
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import scenarios as SC  # noqa: E402
import wallclock as W  # noqa: E402

RUNS = 3


def recheck(name: str) -> dict:
    W.N_FAIL = W.N_PASS = 6
    truth = H.load(name, "truth")
    ids = [c["id"] for c in W._changes(name) if (truth.get(c["id"]) or {}).get("affected")]
    scen = H.WORK / f"scenarios-{name}.json"
    if scen.exists():
        picks = json.loads(scen.read_text("utf-8")).get("picks") or {}
        ids += [picks[k] for k in ("M", "M2") if picks.get(k) and picks[k] not in ids]
    out: dict = {"project": name, "runs": RUNS, "changes": {}}
    native = (truth.get(ids[0]) or {}).get("affected") == ["<native suite>"] if ids else False
    for cid in ids:
        affected = truth[cid]["affected"]
        touched = list(SC.change(name, cid)["files"])
        if any(p.startswith("node_modules/") or "/node_modules/" in p for p in touched):
            # the harness copies a repository without node_modules/ and then writes the one mutated file
            # into it: a committed dependency becomes a one-file stub that no test can import. The label
            # says nothing about the change itself (hb-actions commits its node_modules/)
            out["changes"][cid] = {"affected": affected, "failing_runs": None, "confirmed": False,
                                   "detail": ["harness artifact: a change under a committed node_modules/"]}
            print(f"  {name} {cid}: UNCONFIRMED (harness artifact: node_modules)", flush=True)
            continue
        work = H._copy(name, "recheck-" + cid)
        H._apply(work, SC.change(name, cid))
        fails = 0
        detail = []
        try:
            for _ in range(RUNS):
                if native:
                    detail.append("native suite: not rechecked (Amendment 5a labels are suite-level)")
                    fails = RUNS
                    break
                res = SC.files_truth(name, work, affected, timeout=300)
                bad = sorted(t for t in affected if SC._fails(res, t))
                detail.append(bad)
                fails += bool(bad)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        out["changes"][cid] = {"affected": affected, "failing_runs": fails, "detail": detail,
                               "confirmed": fails >= 2}
        print(f"  {name} {cid}: {fails}/{RUNS} {'confirmed' if fails >= 2 else 'UNCONFIRMED'}", flush=True)
    return out


def main() -> int:
    for name in [a for a in sys.argv[1:] if not a.startswith("--")]:
        t = time.time()
        res = recheck(name)
        res["seconds"] = round(time.time() - t, 1)
        (H.WORK / f"recheck6-{name}.json").write_text(json.dumps(res, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
