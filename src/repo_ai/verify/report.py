"""Terminal rendering of plans and evidence: short, evidence first, and never
stronger than the evidence."""

from __future__ import annotations

from typing import Any

from .select import Plan

CONF_TEXT = {
    "high": "HIGH: every changed code unit has fresh runtime evidence",
    "medium": "MEDIUM: some of the change rests on static evidence only (imports or file names), "
              "not on runtime evidence",
    "low": "LOW: the selection may miss tests; run the full suite",
    "none": "nothing to verify",
}


# `processes` also holds counts of test-file runs, which are not processes
_NOT_PROCESSES = {"total", "test_file_runs_at_change", "repeated_file_runs"}
_PHASE = {"full": "full suite", "base": "base comparison", "file": "per file", "batch": "batched",
          "rerun": "re-run", "confirm": "confirmation"}


def render_plan(p: Plan, limit: int = 15, evidence_status: dict[str, Any] | None = None) -> str:
    """What changed, what can show a regression and how sure that is, how to
    run it, and whether the last run still covers the working tree."""
    out: list[str] = []
    n = len(p.files)
    out.append(f"repo-ai verify: {n} changed file{'s' if n != 1 else ''} against {p.base}")
    if p.files:
        out.append("\nchanged")
        for f in p.files[:20]:
            units = f", units: {', '.join(f.changed_units[:5])}" if f.changed_units else ""
            out.append(f"  {f.path}  [{f.kind}, {f.status}{units}]")
            if not f.behavioral:
                out.append("      " + next((n for n in f.notes if "behavioural" in n or "repo-ai's own" in n),
                                           "no behavioural change (comments/formatting)"))
            for e in f.exposure[:2]:
                out.append(f"      ! {e['detail']}")
            if f.never_executed:
                out.append(f"      ! never executed by any recorded test: {', '.join(f.never_executed[:5])}")
            if f.kind == "source" and f.behavioral:
                out.append(f"      evidence: {f.consumers} linked test file(s); runtime evidence {f.runtime}")
        if len(p.files) > 20:
            out.append(f"  … and {len(p.files) - 20} more")
    est = p.estimate
    timing = ""
    if est.get("full_suite_seconds"):
        # recorded per-file times include each file's interpreter start-up: the suite run as
        # one process is usually faster than their sum (see docs/VERIFY.md, "Cost")
        timing = (f"   (est. {est['selected_seconds']:.1f}s of {est['full_suite_seconds']:.1f}s run file by file, "
                  f"{est['share_of_suite_time']:.0%})")
    out.append(f"\nselected {len(p.selected)} of {p.universe} test files{timing}")
    for s in p.selected[:limit]:
        r = s.reasons[0]
        more = f" (+{len(s.reasons) - 1} more)" if len(s.reasons) > 1 else ""
        out.append(f"  {s.test}  [{r.kind}] {r.detail[:110]}{more}")
    if len(p.selected) > limit:
        out.append(f"  … and {len(p.selected) - limit} more (--json lists all, with evidence)")
    out.append(f"\nconfidence: {CONF_TEXT.get(p.confidence, p.confidence)}")
    for t in p.triggers[:6]:
        out.append(f"  - {t}")
    if p.uncertainty:
        out.append("uncertainty")
        out += [f"  - {u}" for u in p.uncertainty[:6]]
    runner = p.runner
    if runner.command:
        out.append(f"\ntest command: {runner.command}" + (f"   ({runner.source})" if runner.source else ""))
        for note in runner.notes[:4]:
            out.append(f"  - {note}")
        if runner.env:
            out.append("  - environment: " + " ".join(f"{k}={v}" for k, v in sorted(runner.env.items())))
    out.append("\nrun")
    for c in p.targeted_commands[:3]:
        out.append(f"  targeted:   {c}")
    if p.full_command:
        out.append(f"  full suite: {p.full_command}" + ("   <- required" if p.full_suite_required else
                                                          "   (before merging)"))
    if runner.per_file or runner.full:
        out.append("  sandboxed:  repo-ai verify --run" + ("" if p.full_suite_required else
                                                           "   (--full runs the full suite instead)"))
        out.append("              tests run in a disposable copy of the working tree, never in it; "
                   "failures are re-checked against the base")
    if p.files and runner.per_file and p.confidence != "high" and not p.estimate.get("full_suite_seconds"):
        out.append("  sharper:    repo-ai verify --record   (once: records which code each test runs)")
    if evidence_status is not None:
        state = evidence_status.get("state")
        if state == "current":
            out.append(f"\nevidence: CURRENT. The last run ({evidence_status.get('created')}) covers exactly this "
                       f"change: {evidence_status.get('verdict')}")
        elif state == "stale" and evidence_status.get("stale_reason") == "environment":
            out.append(f"\nevidence: STALE. The last run ({evidence_status.get('created')}) was of this change, in a "
                       "test environment that has changed since (installed packages or the interpreter)")
        elif state == "stale":
            out.append(f"\nevidence: STALE. The last run ({evidence_status.get('created')}) was for a different "
                       "working tree; it does not cover this change")
        else:
            out.append("\nevidence: none yet for this repository")
    return "\n".join(out) + "\n"


def render_evidence(rec: dict[str, Any], current: bool | None = None,
                    environment: tuple[str, str] = ("not checked", "")) -> str:
    """`repo-ai evidence`: the last run, whether it still applies, and its
    conclusion in the same form as `verify --run`. `environment`:
    `evidence.environment_check` of the record."""
    out = [f"verification evidence {rec.get('created', '')}  ({rec.get('backend', '?')} sandbox)"]
    env, detail = environment
    if current is not None:
        out.append("applies to the current working tree" if current else
                   f"STALE: the test environment changed after this run ({detail}); it no longer vouches for the "
                   "change (`repo-ai verify --run` runs it again)" if env == "changed" else
                   "STALE: the working tree changed after this run; it does not cover the current change")
    if env == "not recorded":
        out.append(f"note: {detail}, so a later change to installed packages is not detected")
    out.append("")
    out += _outcome(rec, summarize(rec), list((rec.get("plan") or {}).get("uncertainty") or []), after_run=False)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# the result of a run, short first
# --------------------------------------------------------------------------
_HEADLINE = {
    "regression": "REGRESSION: this change breaks tests that pass at the base",
    "failing (all failures pre-existing at the base)": "NO NEW FAILURES: every failure also happens at the base",
    "failing (only next to other test files: order-dependent or flaky)":
        "UNCONFIRMED FAILURES: they happen only next to other test files (order-dependent or flaky)",
    "failing (not compared with the base)": "FAILING: the failures could not be compared with the base",
    "full-suite-failed": "FULL SUITE FAILED: its failures could not be attributed to test files",
    "selected-and-full-suite-passed": "PASSED: the full suite passed",
    "selected-passed (full suite not run)": "PASSED: every selected test passed (the full suite was not run)",
    "selected-passed; full suite REQUIRED but not run":
        "PASSED, BUT INCOMPLETE: the selected tests passed; this change requires the full suite",
    "nothing-selected": "NOTHING TO RUN: the change alters no code behaviour (documentation, comments or formatting)",
    "not verified: no test is linked to the behavioural change (nothing was selected)":
        "NOT VERIFIED: no test is linked to this behavioural change, so nothing ran",
    "not verified: the full suite is required for this change and could not be run":
        "NOT VERIFIED: this change requires the full suite, which could not be run here",
    "failing (tests that fail at the base now fail differently)":
        "FAILING DIFFERENTLY: tests that fail at the base fail another way with this change (it may affect them)",
    "selected-passed; full suite failed (not required; its failures cannot be attributed)":
        "SELECTED TESTS PASSED, FULL SUITE FAILED: the full suite (run only because it was expected to be faster) "
        "failed in a way that cannot be attributed to files; it will not be chosen for speed again here",
}


def summarize(rec: dict[str, Any]) -> dict[str, Any]:
    """The run in a few fields, for people and agents alike."""
    rows = rec.get("results") or []
    new = [r for r in rows if r["status"] not in {"pass", "no-tests"} and r.get("confirmed", True)
           and (r.get("baseline") in {"pass", "absent"} or r.get("new_failing_tests"))]
    unconfirmed = [r for r in rows if r["status"] not in {"pass", "no-tests"} and r.get("confirmed") is False]
    pre_all = [r for r in rows if r["status"] not in {"pass", "no-tests"} and r not in new and r not in unconfirmed
               and r.get("baseline") == "fail"]
    changed = [r for r in pre_all if r.get("changed_failures")]
    pre = [r for r in pre_all if not r.get("changed_failures")]
    other = [r for r in rows if r["status"] not in {"pass", "no-tests"} and r not in new + unconfirmed + pre_all]
    return {
        "verdict": rec.get("verdict"),
        "new_failures": [{"test_file": r["test"], "tests": (r.get("new_failing_tests") or
                                                           [t for t in r.get("failing_tests", []) if t != "<file>"])[:20],
                          "status": r["status"]} for r in new],
        "pre_existing": [r["test"] for r in pre],
        "failing_differently": [r["test"] for r in changed],
        "unverified": [r["test"] for r in rows if r.get("unverified")],
        "unconfirmed": [r["test"] for r in unconfirmed],
        "not_compared": [r["test"] for r in other],
        "passed": sum(1 for r in rows if r["status"] == "pass"),  # selected test FILES that passed
        "full_suite_counts": (rec.get("full_suite") or {}).get("counts"),
        "no_tests": [r["test"] for r in rows if r["status"] == "no-tests"],
        "not_run": [x["test"] for x in rec.get("not_run") or []],
        "strategy": (rec.get("strategy") or {}).get("kind"),
        "seconds": (rec.get("timing") or {}).get("total_s"),
        "processes": (rec.get("processes") or {}).get("total"),
        "reused": bool(rec.get("reused")),
        "source_tree_unchanged": (rec.get("source_tree") or {}).get("unchanged"),
    }


def _why(r: dict[str, Any]) -> str:
    links = r.get("linked_by") or []
    if not links:
        return "not in the selection: found by the full suite" if r.get("selected") is False else ""
    first = links[0]
    return f"selected because it {first['detail'][:110]} ({first['kind']} evidence)"


def _failure_lines(r: dict[str, Any], limit: int = 3) -> list[str]:
    fails = r.get("failures") or {}
    names = r.get("new_failing_tests") or [t for t in (r.get("failing_tests") or [])]
    out = []
    for name in names[:limit]:
        msg = fails.get(name, "")
        label = "the file itself" if name == "<file>" else name
        out.append(f"{label}: {msg}" if msg else label)
    if len(names) > limit:
        out.append(f"(+{len(names) - limit} more)")
    if not out:
        out = [ln for ln in (r.get("output_tail") or "").strip().splitlines()[-2:]]
    return out


def render_run(p: Plan, rec: dict[str, Any]) -> str:
    """What `verify --run` found, the conclusion first."""
    s = summarize(rec)
    out: list[str] = []
    names = ", ".join(f.path for f in p.files[:3]) + (f" (+{len(p.files) - 3} more)" if len(p.files) > 3 else "")
    out.append(f"repo-ai verify: {len(p.files)} changed file{'s' if len(p.files) != 1 else ''} against {p.base}"
               + (f": {names}" if names else ""))
    out.append(f"selected {len(p.selected)} of {p.universe} test files; confidence "
               f"{CONF_TEXT.get(p.confidence, p.confidence)}")
    strat = rec.get("strategy") or {}
    how = {"full": "the full suite as one process", "targeted": "the selected files",
           "none": "nothing"}.get(strat.get("kind", ""), strat.get("kind", ""))
    if rec.get("reused"):
        out.append(f"reused the evidence from {rec['reused'].get('created')}: same change, environment and "
                   "selection (`--rerun` runs it again)")
    else:
        procs = rec.get("processes") or {}
        parts = ", ".join(f"{_PHASE.get(k, k)} {v}" for k, v in procs.items()
                          if k not in _NOT_PROCESSES and isinstance(v, int) and v)
        out.append(f"ran {how}: {s['processes'] or 0} sandboxed process(es) in all"
                   + (f" ({parts})" if parts else "") + f", {s['seconds'] or 0:.1f}s"
                   + (f": {strat.get('reason')}" if strat.get("reason") else ""))
    out.append("")
    out += _outcome(rec, s, p.uncertainty)
    return "\n".join(out) + "\n"


def _outcome(rec: dict[str, Any], s: dict[str, Any], uncertainty: list[str], after_run: bool = True) -> list[str]:
    """The conclusion of a run and what supports it: shared by `verify --run`
    and `repo-ai evidence`."""
    verdict = str(rec.get("verdict", "?"))
    out: list[str] = [_HEADLINE.get(verdict, "NOT VERIFIED: " + verdict.split(": ", 1)[1]
                                    if verdict.startswith("not verified: ") else verdict.upper())]
    rows = {r["test"]: r for r in rec.get("results") or []}
    new = [rows[x["test_file"]] for x in s["new_failures"]]
    # one cause, many files (an import that now fails): say it once
    by_msg: dict[str, list[dict[str, Any]]] = {}
    for r in new:
        msgs = {m for m in (r.get("failures") or {}).values() if m}
        key = msgs.pop() if len(msgs) == 1 else ""
        by_msg.setdefault(key, []).append(r)
    for msg, group in by_msg.items():
        if msg and len(group) >= 3:
            out.append(f"  NEW  {len(group)} test files fail with the same error: {msg[:160]}")
            out.append("       " + ", ".join(r["test"] for r in group[:6]) + (" …" if len(group) > 6 else ""))
            why = _why(group[0])
            if why:
                out.append(f"       {why}")
            continue
        for r in group:
            label = "TIMEOUT" if r["status"] == "timeout" else "NEW"
            out.append(f"  {label:4s} {r['test']}: {r.get('classification', '')}")
            out += [f"         {line[:150]}" for line in _failure_lines(r)]
            why = _why(r)
            if why:
                out.append(f"         {why}")
    for r in (rows[t] for t in s["unconfirmed"]):
        out.append(f"  ?    {r['test']}: {r.get('classification', '')}")
        out += [f"         {line[:150]}" for line in _failure_lines(r, 2)]
    for r in (rows[t] for t in s["not_compared"]):
        out.append(f"  FAIL {r['test']}: {r.get('classification', '')}")
        out += [f"         {line[:150]}" for line in _failure_lines(r, 2)]
    for r in (rows[t] for t in s.get("failing_differently") or []):
        out.append(f"  DIFF {r['test']}: {r.get('classification', '')}")
        for tid, m in list((r.get("changed_failures") or {}).items())[:2]:
            out.append(f"         {tid}: at the base {str(m.get('base'))[:70]!r}, now {str(m.get('now'))[:70]!r}")
    for r in (rows[t] for t in s.get("unverified") or []):
        out.append(f"  SKIP {r['test']}: {r['unverified']}")
    if s["pre_existing"]:
        out.append("  already failing at the base, so not caused by this change: "
                   + ", ".join(s["pre_existing"][:6]) + (" …" if len(s["pre_existing"]) > 6 else ""))
    full = rec.get("full_suite")
    if full and full.get("status") not in {None, "not-run"} and str(rec.get("verdict")) == "full-suite-failed":
        out += [f"  | {line[:150]}" for line in (full.get("output_tail") or "").strip().splitlines()[-6:]]
    elif full and full.get("status") == "not-run":
        out.append(f"  full suite not run: {full.get('reason')}")
    counts = [f"{s['passed']} selected test file(s) passed"]
    if s.get("full_suite_counts"):
        c = s["full_suite_counts"]
        counts.append(f"full suite: {c['passed']} test(s) passed, {c['failed']} failed, {c['skipped']} skipped")
    if s["no_tests"]:
        counts.append(f"{len(s['no_tests'])} define no tests")
    if s["not_run"]:
        counts.append(f"{len(s['not_run'])} skipped as duplicates ({', '.join(s['not_run'][:2])})")
    out.append("  " + "; ".join(counts))
    tree = rec.get("source_tree") or {}
    if tree:
        out.append("  source tree unchanged" if tree.get("unchanged") else "  SOURCE TREE CHANGED: evidence invalid")
    for u in uncertainty[:3]:
        out.append(f"  ! {u}")
    if after_run:
        out.append(("evidence reused" if rec.get("reused") else "evidence saved")
                   + "; `repo-ai evidence` shows whether it still covers the working tree.")
    if verdict.startswith(("nothing-selected", "not verified")):
        out.append("No test ran: this is not evidence that the change is correct.")
    elif verdict.startswith("selected-") or verdict == "failing (all failures pre-existing at the base)":
        out.append("This covers only the tests that ran; it is not proof the change is correct.")
    return out
