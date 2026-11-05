#!/usr/bin/env python3
"""Markdown tables from e2e.py results (no hand-copied numbers).

    python e2e_tables.py results/e2e-<engine>.json > results/e2e-<engine>.md
"""

from __future__ import annotations

import json
import statistics
import sys


def f(x, unit="s"):
    return "-" if x is None else f"{x:.2f}{unit}" if isinstance(x, float) else f"{x}{unit}"


def main() -> int:
    data = json.load(open(sys.argv[1]))
    out = ["| project | full suite (sandboxed, one process) | init | `--record` | plan (median) | `verify --run` median (10 changes) | min / max | saved per change | break-even changes | tree unchanged, every run |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    detail = []
    for name, r in data.items():
        s = r.get("summary") or {}
        sess = r.get("session") or []
        plans = [x["plan_s"] for x in sess]
        runs = [x["run_s"] for x in sess]
        out.append(f"| {name} | {f(s.get('full_suite_s'))} | {f(s.get('init_s'))} | {f(s.get('record_s'))} | "
                   f"{f(statistics.median(plans) if plans else None)} | {f(s.get('verify_run_median_s'))} | "
                   f"{f(min(runs) if runs else None)} / {f(max(runs) if runs else None)} | "
                   f"{f(s.get('saved_per_change_s'))} | "
                   f"{s.get('break_even_changes') if s.get('break_even_changes') is not None else 'never'} | "
                   f"{'yes' if s.get('tree_unchanged_every_run') else 'NO'} |")
        rows = [f"\n**{name}** (`{r.get('test_command')}`)\n",
                "| scenario | selected / universe | confidence | wall time | verdict |", "|---|---|---|---|---|"]

        def row(label, x, rows=rows):
            if not x:
                return
            run = x.get("run", x)
            rows.append(f"| {label} | {run.get('selected')} / {run.get('universe')} | {run.get('confidence')} | "
                        f"{f(run.get('wall_s'))} | {run.get('verdict') or run.get('error', '')[:60]} |")
        row("one change", r.get("single"))
        for i, x in enumerate(r.get("same_file") or []):
            row(f"same file, edit {i + 1}", x)
        row(f"broad ({(r.get('broad') or {}).get('files')} files)", r.get("broad"))
        row(f"config edit ({(r.get('config') or {}).get('file')})", r.get("config"))
        row("stale evidence (change committed, new change)", r.get("stale"))
        if r.get("stale"):
            rows.append(f"| re-record after the commit | - | - | {f(r['stale']['re_record'].get('wall_s'))} | - |")
        row("`--run --full`", r.get("full"))
        detail += rows
    print("\n".join(out + detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
