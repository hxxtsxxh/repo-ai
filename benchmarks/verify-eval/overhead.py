#!/usr/bin/env python3
"""Fixed per-run overhead of two engines, interleaved run by run
(docs/VERIFY-NEXT-OVERHEAD.md, acceptance criterion C2). Development corpus
only: this is engineering measurement, not held-out validation.

    VEV_WORK=... VEV_A=<repo-ai> VEV_B=<repo-ai> python overhead.py [--rounds N] <project> [...] > out.json

Per project, in a fresh clone set up as `wallclock.py` does, with its first
failing change applied, `rounds` times, alternating which engine goes first:
- `verify --json` (the plan: no test runs);
- `verify --run --json --rerun` (the same selection every round).

Both engines run on the same tree, with the same test command and sandbox.
Reported per engine:
- the median, with a bootstrap 95% interval (2000 resamples, fixed seed);
- the median difference B − A, with its interval;
- the p95 of the plan;
- whether every pair of runs agreed on the verdict.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import wallclock as W  # noqa: E402

A, B = os.environ.get("VEV_A", ""), os.environ.get("VEV_B", "")


def _run(exe: str, repo: Path, *args: str) -> tuple[float, dict]:
    t = time.monotonic()
    p = subprocess.run([exe, *args], cwd=repo, env=H.env(), capture_output=True, text=True)
    wall = time.monotonic() - t
    try:
        return wall, json.loads(p.stdout)
    except ValueError:
        return wall, {"error": (p.stderr or p.stdout)[-300:]}


def _ci(xs: list[float], ys: list[float] | None = None) -> list[float]:
    rnd = random.Random(1)
    stats = []
    for _ in range(2000):
        a = [rnd.choice(xs) for _ in xs]
        if ys is None:
            stats.append(statistics.median(a))
        else:
            b = [rnd.choice(ys) for _ in ys]
            stats.append(statistics.median(b) - statistics.median(a))
    stats.sort()
    return [round(stats[50], 3), round(stats[1949], 3)]


def measure(name: str, rounds: int) -> dict:
    src = H.WORK / "repos" / name
    repo = H.WORK / "overhead" / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)
    proj = H.CORPUS[name]
    W.ra("new", repo, "init", "--agent", "none", "-q")
    H.git(repo, "add", "-A")
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "repo-ai init", check=False)
    truth = H.load(name, "truth")
    change = next(c for c in H.load(name, "changes") if (truth.get(c["id"]) or {}).get("affected"))
    H._apply(repo, change)
    # a project with an image runs in its network-less container, as in wallclock.py
    sandbox = ["--sandbox", "podman", "--image", proj["image"]] if proj.get("image") else []
    tc = ["--test-command", proj["test_command"], *sandbox]
    plan: dict[str, list[float]] = {"A": [], "B": []}
    run: dict[str, list[float]] = {"A": [], "B": []}
    verdicts: list[tuple[str, str]] = []
    for i in range(rounds):
        order = [("A", A), ("B", B)] if i % 2 == 0 else [("B", B), ("A", A)]
        got = {}
        for key, exe in order:
            plan[key].append(_run(exe, repo, "verify", "--json", *tc)[0])
            wall, data = _run(exe, repo, "verify", "--run", "--json", "--rerun", *tc)
            run[key].append(wall)
            got[key] = str((data.get("evidence") or {}).get("verdict") or data.get("error"))
        verdicts.append((got["A"], got["B"]))
    W._revert(repo)
    out: dict = {"project": name, "change": change["id"], "rounds": rounds, "sandbox": "podman" if sandbox else "host",
                 "verdicts_agree": all(a == b for a, b in verdicts), "verdicts": sorted(set(verdicts))}
    for label, series in (("plan", plan), ("run", run)):
        out[label] = {k: {"median_s": round(statistics.median(v), 3), "ci95": _ci(v),
                          "p95_s": round(sorted(v)[max(0, int(round(0.95 * (len(v) - 1))))], 3)}
                      for k, v in series.items()}
        out[label]["B_minus_A_median_s"] = round(statistics.median(series["B"]) - statistics.median(series["A"]), 3)
        out[label]["B_minus_A_ci95"] = _ci(series["A"], series["B"])
    return out


def main() -> int:
    args = sys.argv[1:]
    rounds = int(args[args.index("--rounds") + 1]) if "--rounds" in args else 10
    names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--rounds")]
    if not (A and B):
        raise SystemExit("set VEV_A (baseline) and VEV_B (candidate) to repo-ai executables")
    out = {"A": A, "B": B, "projects": {}}
    for n in names:
        out["projects"][n] = measure(n, rounds)
        print(json.dumps({k: out["projects"][n][k] for k in ("project", "plan", "run", "verdicts_agree")}),
              file=sys.stderr, flush=True)
    json.dump(out, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
