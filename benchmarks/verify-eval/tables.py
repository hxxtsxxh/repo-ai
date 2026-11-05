#!/usr/bin/env python3
"""Render verify-eval scores as Markdown tables (no hand-copied numbers).

    VEV_WORK=... python tables.py heldout > results/heldout-tables.md
"""

from __future__ import annotations

import sys

import harness

ORDER = ["all", "grep", "impact-0.7.7", "verify-static", "policy-static", "verify-runtime", "policy-runtime"]
LABEL = {"all": "run every test file", "grep": "grep (imports or mentions)",
         "impact-0.7.7": "repo-ai 0.7.7 `impact`", "verify-static": "`verify`, static evidence",
         "policy-static": "`verify` static + full suite when confidence is low",
         "verify-runtime": "`verify` with runtime evidence",
         "policy-runtime": "`verify` runtime + full suite when confidence is low"}


def table(score: dict) -> str:
    rows = ["| Method | Detected changes | No-miss | Mean recall | Test files selected | Suite time | Misses by reported confidence |",
            "|---|---|---|---|---|---|---|"]
    for meth in ORDER:
        m = score["methods"].get(meth)
        if not m:
            continue
        conf = "; ".join(f"{k}: {v}" for k, v in m["misses_by_confidence"].items()) if meth != "all" else "-"
        rows.append(f"| {LABEL[meth]} | {m['detected']} of {m['changes']} | **{m['no_miss_rate']:.1%}** | "
                    f"{m['mean_recall']:.1%} | {m['selected_file_share']:.0%} | **{m['suite_time_share']:.0%}** | {conf} |")
    return "\n".join(rows)


def per_project(which: str) -> str:
    rows = ["| Project | Lang | Detected | verify-runtime no-miss / time | verify-static no-miss / time | "
            "policy-static time | 0.7.7 impact no-miss | grep no-miss |", "|---|---|---|---|---|---|---|---|"]
    saved = harness.CORPUS
    for name, proj in saved.items():
        if proj["set"] != which:
            continue
        harness.CORPUS = {name: {**proj, "set": "_one"}}
        try:
            d = harness.score("_one")["methods"]
        except Exception:  # noqa: BLE001 - a project without results
            d = {}
        finally:
            harness.CORPUS = saved
        if not d:
            rows.append(f"| {name} | {proj['lang']} | (no results) | | | | | |")
            continue
        r, s, ps = d["verify-runtime"], d["verify-static"], d["policy-static"]
        rows.append(f"| {name} | {proj['lang']} | {d['all']['detected']} of {d['all']['changes']} | "
                    f"{r['no_miss_rate']:.0%} / {r['suite_time_share']:.0%} | {s['no_miss_rate']:.0%} / "
                    f"{s['suite_time_share']:.0%} | {ps['suite_time_share']:.0%} | "
                    f"{d['impact-0.7.7']['no_miss_rate']:.0%} | {d['grep']['no_miss_rate']:.0%} |")
    return "\n".join(rows)


def misses(score: dict) -> str:
    rows = ["| Project | Change | Kind | Method | Confidence | Missed test files |", "|---|---|---|---|---|---|"]
    for m in score["verify_misses"]:
        rows.append(f"| {m['project']} | {m['change']} | {m['kind']} | {m['method']} | {m['confidence']} | "
                    f"{', '.join(m['missed'])} |")
    return "\n".join(rows) if len(rows) > 2 else "(none)"


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "heldout"
    s = harness.score(which)
    print(f"### {which}: all projects\n\n{table(s)}\n\n### {which}: per project\n\n{per_project(which)}\n\n"
          f"### {which}: every `verify` miss\n\n{misses(s)}\n")
