#!/usr/bin/env python3
"""Zero-configuration test commands: does `repo-ai verify` establish a
correct per-file runner with no `--test-command`?

For each corpus project, at its pinned commit:
1. the runner `repo-ai verify --json` establishes on its own (`inferred`);
2. the corpus reference runner (`test_command` in corpus.json, validated at
   baseline in the network-less container);
3. **universe:** inferred test files compared with the reference test files;
4. **execution:** every reference test file, plus every extra file the
   inferred runner adds, run *with the inferred per-file command* in the same
   network-less container as the reference baseline. Outcomes are compared
   with `baseline.json`.

**Classification:**
- `correct`: per-file runner; no reference file missing; every reference file
  has the same outcome as with the reference command; extra files, if any,
  pass.
- `partial`: a per-file runner that misses reference files or disagrees on
  outcomes.
- `opaque`: no per-file runner (verify would require the full suite).
- `none`: no command established.

    VEV_WORK=... python zeroconfig.py [--set dev|heldout|heldout2|heldout3] [--label NAME] [--no-exec]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

from repo_ai.verify.runner import TestRunner  # noqa: E402


def inferred_runner(name: str) -> tuple[TestRunner | None, dict]:
    repo = H.WORK / "repos" / name
    p = subprocess.run([H.RA, "verify", "--json"], cwd=repo, env=H.env(), capture_output=True, text=True)
    try:
        plan = json.loads(p.stdout)
    except ValueError:
        return None, {"error": (p.stderr or p.stdout)[-300:]}
    data = plan["runner"]
    if "full" not in data and data.get("command"):
        # an engine whose plan names only the command: resolve it with that engine's own code
        code = ("import json,sys;from pathlib import Path;from repo_ai.verify.runner import resolve;"
                "print(json.dumps(resolve(Path(sys.argv[1]),sys.argv[2]).to_json()))")
        out = subprocess.run([sys.executable, "-c", code, str(repo), data["command"]], capture_output=True, text=True,
                             env={**os.environ, "PYTHONPATH": os.environ.get("VEV_ENGINE_SRC", "")})
        data = json.loads(out.stdout)
    r = TestRunner.from_json(data)
    return r, {"command": r.command, "kind": r.kind, "env": r.env, "source": data.get("source", ""),
               "notes": data.get("notes", [])}


def run_with(name: str, runner: TestRunner, tests: list[str]) -> dict:
    """`harness.run_tests`, but with the given runner's per-file commands."""
    original = H.runner_for
    H.runner_for = lambda _n: runner  # type: ignore[assignment]
    try:
        work = H._copy(name, "zeroconfig")
        try:
            return H.run_tests(name, work, tests)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    finally:
        H.runner_for = original  # type: ignore[assignment]


def measure(name: str, execute: bool) -> dict:
    repo = H.WORK / "repos" / name
    files = [f for f in H.git(repo, "ls-files").split("\n") if f]
    ref = H.runner_for(name)
    ref_tests = set(ref.test_files(files))
    base = H.load(name, "baseline")
    inferred, info = inferred_runner(name)
    row = {"project": name, "set": H.CORPUS[name]["set"], "reference": H.CORPUS[name]["test_command"], **info,
           "reference_files": len(ref_tests)}
    if inferred is None or not inferred.command:
        row["class"] = "none"
        return row
    if not inferred.per_file:
        row["class"] = "opaque"
        return row
    inf_tests = set(inferred.test_files(files))
    # files the corpus excludes from scoring (nondeterministic or environment-bound) are real test
    # files: including them is not an error, and they are not run here
    corpus_excluded = set(H.CORPUS[name].get("excluded_tests", []))
    missing, extra = sorted(ref_tests - inf_tests), sorted(inf_tests - ref_tests - corpus_excluded)
    row.update({"inferred_files": len(inf_tests), "missing": missing[:20], "missing_count": len(missing),
                "extra": extra[:20], "extra_count": len(extra)})
    if execute:
        res = run_with(name, inferred, sorted((ref_tests & inf_tests) | set(extra)))
        disagree = sorted(t for t in ref_tests & inf_tests
                          if (res.get(t, {}).get("exit") == 0) != (base.get(t, {}).get("exit") == 0))
        extra_fail = sorted(t for t in extra if res.get(t, {}).get("exit") != 0)
        row.update({"disagreements": disagree[:20], "disagreement_count": len(disagree),
                    "extra_failing": extra_fail[:20], "extra_failing_count": len(extra_fail)})
        ok = not missing and not disagree and not extra_fail
        runner_missing = inferred.kind == "pytest" and disagree and all(
            "No module named pytest" in (res.get(t, {}).get("tail") or "") for t in disagree)
        if runner_missing:
            row["class"] = "runner-not-installed"  # the evaluation image has no pytest
            return row
    else:
        ok = not missing
    row["class"] = "correct" if ok else "partial"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append")
    ap.add_argument("--label", default="")
    ap.add_argument("--no-exec", action="store_true")
    ap.add_argument("projects", nargs="*")
    a = ap.parse_args()
    names = a.projects or [n for n, p in H.CORPUS.items() if not a.set or p["set"] in a.set]
    rows = []
    for n in names:
        if not (H.WORK / "out" / n / "baseline.json").exists():
            print(f"{n}: no baseline; skipped", file=sys.stderr)
            continue
        row = measure(n, not a.no_exec)
        rows.append(row)
        print(f"{n:20s} {row['class']:8s} {row.get('command', '')[:70]}"
              + (f"  missing {row.get('missing_count')}, disagree {row.get('disagreement_count')}, "
                 f"extra {row.get('extra_count')} ({row.get('extra_failing_count')} failing)"
                 if row["class"] in {"correct", "partial"} else ""), flush=True)
    summary = {c: sum(1 for r in rows if r["class"] == c)
               for c in ("correct", "partial", "runner-not-installed", "opaque", "none")}
    out = {"label": a.label, "engine": os.environ.get("VEV_ENGINE", ""), "summary": summary,
           "projects": len(rows), "rows": rows}
    if a.label:
        (H.WORK / f"zeroconfig-{a.label}.json").write_text(json.dumps(out, indent=1), "utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
