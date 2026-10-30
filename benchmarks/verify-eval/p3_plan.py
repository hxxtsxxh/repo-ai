#!/usr/bin/env python3
"""P3 (docs/research/VERIFY-INTERFACE-PROPOSALS-2026-10.md, Session B):
is a per-edit, read-only plan cheap enough to run after every edit, and is
it consistent with the plan for the whole change?

    VEV_WORK=... python p3_plan.py [--sessions N] <project> [...] > results/p3-plan-<commit>.json

Per project, in a fresh clone set up as `wallclock.py` does, with no test
executed (planning only):
- **edit sessions:** the corpus's single-file changes, taken in order and
  grouped three at a time over distinct files (a multi-file change). With
  each session applied:
  - `full`: `build_plan` for the whole change, five times (the first is cold);
  - `per_path`: `build_plan(paths=[f])` for each changed file, five times each.
- **Reported:**
  - median and p95 latency of both;
  - whether the union of the per-path selections equals the full plan's
    selection;
  - whether "full suite required" agrees (any per-path requires it versus the
    full plan does);
  - the size of a per-path plan's JSON and text (context cost for an agent
    hook).

Latency is measured in-process (the engine's own call), excluding
interpreter start-up. The CLI start-up is measured separately once per
project (`verify --json --paths`).
"""

from __future__ import annotations

import json
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

REPEATS = 5


def _sessions(name: str, n: int) -> list[list[dict]]:
    every = H.load(name, "changes")
    out: list[list[dict]] = []
    cur: list[dict] = []
    for c in every:
        files = set(c.get("files") or {})
        if not files or any(files & set(x.get("files") or {}) for x in cur):
            continue
        cur.append(c)
        if len(cur) == 3:
            out.append(cur)
            cur = []
            if len(out) == n:
                break
    return out


def _p(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 4)


def measure(name: str, sessions: int) -> dict:
    from repo_ai.config import load_config
    from repo_ai.paths import detect_kind, resolve_layout
    from repo_ai.verify import engine, report

    src = H.WORK / "repos" / name
    repo = H.WORK / "p3" / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)
    W.ra("new", repo, "init", "--agent", "none", "-q")
    H.git(repo, "add", "-A")
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "repo-ai init", check=False)
    cmd = H.CORPUS[name]["test_command"]
    layout = resolve_layout(repo, load_config(repo), prefer=detect_kind(repo) or "standard")
    rows = []
    for group in _sessions(name, sessions):
        for c in group:
            H._apply(repo, c)
        try:
            full_s, plans = [], None
            for _ in range(REPEATS):
                t = time.perf_counter()
                p, change = engine.build_plan(repo, layout, command=cmd)
                full_s.append(time.perf_counter() - t)
                plans = (p, change)
            p_full, change = plans
            paths = sorted(f.path for f in change.files)
            per_s: list[float] = []
            union: set[str] = set()
            any_required = False
            sizes = []
            for path in paths:
                for _ in range(REPEATS):
                    t = time.perf_counter()
                    pp, _ = engine.build_plan(repo, layout, command=cmd, paths=[path])
                    per_s.append(time.perf_counter() - t)
                union |= {s.test for s in pp.selected}
                any_required |= pp.full_suite_required
                sizes.append({"json_bytes": len(json.dumps({**pp.to_json(), "scope": {"paths": [path]}})),
                              "text_bytes": len(report.render_plan(pp))})
            full_sel = {s.test for s in p_full.selected}
            rows.append({"changes": [c["id"] for c in group], "files": paths,
                         "full_cold_s": round(full_s[0], 4), "full_s": [round(x, 4) for x in full_s],
                         "per_path_s": [round(x, 4) for x in per_s],
                         "union_equals_full": union == full_sel,
                         "only_in_union": sorted(union - full_sel)[:10], "only_in_full": sorted(full_sel - union)[:10],
                         "required_agrees": any_required == p_full.full_suite_required,
                         "full_required": p_full.full_suite_required, "sizes": sizes})
        finally:
            W._revert(repo)
    t = time.monotonic()
    cli = subprocess.run([H.RA, "verify", "--json", "--test-command", cmd, "--paths", "README.md"], cwd=repo,
                         env=H.env(), capture_output=True, text=True)
    cli_s = time.monotonic() - t
    per = [x for r in rows for x in r["per_path_s"]]
    full = [x for r in rows for x in r["full_s"][1:]]
    return {"project": name, "sessions": rows,
            "summary": {"sessions": len(rows),
                        "full_warm_median_s": _p(full, 0.5) if full else None,
                        "full_warm_p95_s": _p(full, 0.95) if full else None,
                        "per_path_median_s": _p(per, 0.5) if per else None,
                        "per_path_p95_s": _p(per, 0.95) if per else None,
                        "union_equals_full": sum(r["union_equals_full"] for r in rows),
                        "required_agrees": sum(r["required_agrees"] for r in rows),
                        "per_path_json_bytes_median": statistics.median(
                            [s["json_bytes"] for r in rows for s in r["sizes"]]) if rows else None,
                        "per_path_text_bytes_median": statistics.median(
                            [s["text_bytes"] for r in rows for s in r["sizes"]]) if rows else None,
                        "cli_wall_s": round(cli_s, 3), "cli_exit": cli.returncode}}


def main() -> int:
    args = sys.argv[1:]
    n = int(args[args.index("--sessions") + 1]) if "--sessions" in args else 4
    names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--sessions")]
    out = {}
    for name in names:
        try:
            out[name] = measure(name, n)
        except Exception as exc:  # noqa: BLE001 - recorded, not hidden
            out[name] = {"project": name, "error": repr(exc)[:500]}
        print(json.dumps(out[name].get("summary") or out[name].get("error")), file=sys.stderr, flush=True)
    json.dump(out, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
