#!/usr/bin/env python3
"""Markdown tables from wallclock.py results (no hand-copied numbers).

    python wallclock_tables.py results/wallclock-summary.json:<set>-new-<commit> results/wallclock-summary.json:<set>-old-cf56523
"""

from __future__ import annotations

import json
import statistics
import sys


def f(x, unit="s"):
    if x is None:
        return "-"
    return f"{x:.2f}{unit}" if isinstance(x, float) else f"{x}{unit}"


def ratio(a, b):
    return "-" if not a or not b else f"{a / b:.2f}x"


def _load(arg: str) -> dict:
    """A result file, or `results/wallclock-summary.json:<set-engine-commit>`."""
    if arg == "/dev/null":
        return {}
    path, _, key = arg.partition(".json:")
    data = json.load(open(path + ".json" if key else arg))
    data = data[key] if key else data
    return {k: v for k, v in data.items() if not k.startswith("_")}  # `_superseded`: earlier attempts


def main() -> int:
    new = _load(sys.argv[1])
    old = _load(sys.argv[2]) if len(sys.argv) > 2 else {}
    out = ["| project | sandbox | native full suite | new: median (failing / passing) | old: median (failing / passing) "
           "| new / native | old / native | processes per run, new / old (median) | files run twice, new / old |",
           "|---|---|---|---|---|---|---|---|---|"]
    corr = ["| project | failing changes | detected, new / old | missed, new / old (confidence) | false alarms, new / old "
            "| regressions outside the ground truth, new / old | new reported as pre-existing, new / old "
            "| repeat runs agree (new) | tree unchanged, every run (new / old) |",
            "|---|---|---|---|---|---|---|---|---|"]
    totals = {"new": [], "old": [], "native": []}
    for name in new:
        n, o = new[name], old.get(name, {})
        sn, so = n.get("summary") or {}, o.get("summary") or {}
        if n.get("error"):
            out.append(f"| {name} | error: {n['error'][:80]} |  |  |  |  |  |  |  |")
            continue
        nat = sn.get("native_median_s")
        out.append(f"| {name} | {n.get('sandbox')} | {f(nat)} | {f(sn.get('median_s'))} ({f(sn.get('median_failing_s'))} / "
                   f"{f(sn.get('median_passing_s'))}) | {f(so.get('median_s'))} ({f(so.get('median_failing_s'))} / "
                   f"{f(so.get('median_passing_s'))}) | {ratio(sn.get('median_s'), nat)} | {ratio(so.get('median_s'), nat)} | "
                   f"{f(sn.get('processes_median'), '')} / {f(so.get('processes_median'), '')} | "
                   f"{sn.get('repeated_file_runs', '-')} / {so.get('repeated_file_runs', '-')} |")
        corr.append(f"| {name} | {sn.get('failing_changes')} | {sn.get('detected')} / {so.get('detected', '-')} | "
                    f"{_miss(sn)} / {_miss(so)} | {len(sn.get('false_alarms') or [])} / {len(so.get('false_alarms') or [])} | "
                    f"{len(sn.get('regressions_outside_ground_truth') or [])} / "
                    f"{len(so.get('regressions_outside_ground_truth') or [])} | "
                    f"{sn.get('new_as_preexisting')} / {so.get('new_as_preexisting', '-')} | "
                    f"{'yes' if sn.get('repeat_agree') else 'NO'} | "
                    f"{'yes' if sn.get('tree_unchanged_every_run') else 'NO'} / "
                    f"{'yes' if so.get('tree_unchanged_every_run') else ('-' if not so else 'NO')} |")
        if nat and sn.get("median_s") and so.get("median_s"):
            totals["native"].append(nat)
            totals["new"].append(sn["median_s"])
            totals["old"].append(so["median_s"])
    lines = out + [""] + corr
    if totals["native"]:
        gm = (lambda xs, ys: statistics.geometric_mean([x / y for x, y in zip(xs, ys, strict=True)]))
        lines += ["", f"Geometric mean of median wall time over the native full suite, {len(totals['native'])} projects: "
                      f"new {gm(totals['new'], totals['native']):.2f}x, old {gm(totals['old'], totals['native']):.2f}x; "
                      f"new over old {gm(totals['new'], totals['old']):.2f}x.",
                  f"Projects where the new engine's median is at or below the native suite: "
                  f"{sum(1 for a, b in zip(totals['new'], totals['native'], strict=True) if a <= b)} of {len(totals['native'])} "
                  f"(old engine: {sum(1 for a, b in zip(totals['old'], totals['native'], strict=True) if a <= b)})."]
    rec = ["", "| project | `--record`, new (includes one native full-suite run) | `--record`, old |", "|---|---|---|"]
    for name in new:
        rec.append(f"| {name} | {f((new[name].get('summary') or {}).get('record_s'))} | "
                   f"{f((old.get(name, {}).get('summary') or {}).get('record_s'))} |")
    print("\n".join(lines + rec + (_extended(new, old) if "--extended" in sys.argv else [])))
    return 0


def _extended(new: dict, old: dict) -> list[str]:
    """PROTOCOL.md Amendment 4a: what the held-out-4 tables left out."""
    out = ["", "| project | native exit codes | max run / native | passing changes not reported as passing (new) "
               "| `--workers 1` median (new) / detected | cold run agrees, verdict and files (new) |",
           "|---|---|---|---|---|---|"]
    for name, n in new.items():
        sn = n.get("summary") or {}
        out.append(f"| {name} | {sn.get('native_exits', '-')} | {f(sn.get('max_ratio'), 'x')} | "
                   f"{len(sn['not_reported_passing']) if 'not_reported_passing' in sn else '-'} | "
                   f"{f(sn.get('median_workers1_s'))} / "
                   f"{sn.get('workers1_detected', '-')} | {sn.get('cold_agree', '-')} |")
    ratios = {"new": [], "old": [], "new_f": [], "old_f": [], "new_p": [], "old_p": [], "new_1": []}
    for name, n in new.items():
        sn, so = n.get("summary") or {}, (old.get(name) or {}).get("summary") or {}
        nat = sn.get("native_median_s")
        if not nat:
            continue
        for key, src, field in (("new", sn, "median_s"), ("old", so, "median_s"), ("new_f", sn, "median_failing_s"),
                                ("old_f", so, "median_failing_s"), ("new_p", sn, "median_passing_s"),
                                ("old_p", so, "median_passing_s"), ("new_1", sn, "median_workers1_s")):
            if src.get(field):
                ratios[key].append(src[field] / nat)
    out.append("")
    for label, key in (("all changes, new", "new"), ("all changes, old", "old"), ("failing changes, new", "new_f"),
                       ("failing changes, old", "old_f"), ("passing changes, new", "new_p"),
                       ("passing changes, old", "old_p"), ("`--workers 1`, new", "new_1")):
        xs = ratios[key]
        if xs:
            out.append(f"- {label} ({len(xs)} projects): geometric mean {statistics.geometric_mean(xs):.2f}x, "
                       f"arithmetic mean {statistics.mean(xs):.2f}x, max {max(xs):.2f}x")
    return out


def _miss(s):
    m = s.get("missed")
    if m is None:
        return "-"
    return str(len(m)) + (" (" + ", ".join(f"{i} {c}" for i, c in m) + ")" if m else "")


if __name__ == "__main__":
    raise SystemExit(main())
