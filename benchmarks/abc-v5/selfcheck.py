"""Free, offline self-check for abc-v5: manifest seal + grader controls. Exit 0 only if every check holds.

  python selfcheck.py [--quick]      --quick grades with one repeat instead of two

Checks (PREREGISTRATION.md section 10):
  * manifest.w.json and manifest.json verify (schema, self-hash, every file hash, W -> FULL link);
  * a tampered file digest and a tampered manifest body are both detected;
  * the reference yields exactly the frozen visible and hidden test IDs, all passing;
  * every candidate grades to its frozen expected grade (untouched FAIL, reference CORRECT, decoys FALSE_GREEN, ...);
  * unsafe candidates (path traversal, absolute path, reserved path, symlink, NUL byte) grade INVALID;
  * hidden test content never appears in the A-view tree;
  * grading is deterministic (two grades of the reference are identical);
  * the primary draw in manifest.json names a semantic decoy of each task.
This file does not run arm B (that is run_offline.py) and never invokes a model or provider.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import grade as G  # noqa: E402
import make_manifest as MM  # noqa: E402

FAILURES: list[str] = []


def ok(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILURES.append(what)


def check_seal() -> None:
    ok(not MM.check(MM.W_PATH), "manifest.w.json verifies")
    ok(not MM.check(MM.FULL_PATH), "manifest.json verifies")
    m = json.loads(MM.FULL_PATH.read_text())
    with tempfile.TemporaryDirectory() as d:
        bad = copy.deepcopy(m)
        key = sorted(bad["sha256"])[0]
        bad["sha256"][key] = "0" * 64
        body = {k: v for k, v in bad.items() if k != "content_sha256"}
        bad["content_sha256"] = hashlib.sha256(MM.canonical(body)).hexdigest()   # re-sealed body, wrong file hash
        p = Path(d) / "m.json"
        p.write_text(json.dumps(bad))
        ok(any("file hash mismatch" in x for x in MM.check(p)), "a tampered file digest is detected")
        edited = copy.deepcopy(m)
        edited["seed"] = edited["seed"] + 1                                       # body edited, not re-sealed
        p.write_text(json.dumps(edited))
        ok(any("content_sha256" in x for x in MM.check(p)), "an edited manifest body is detected")
    for t in MM.task_ids():
        draw = m["primary_candidate_draw"].get(t)
        ok(draw is not None and G.load_candidates(t)[draw]["stratum"] == "semantic",
           f"{t}: primary draw {draw} is a semantic decoy")


def check_task(t: str, repeats: int) -> None:
    oracle = G.load_oracle(t)
    task = G.load_task(t)
    ref = G.candidate_files(t, "reference")
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "f"
        G.materialize_w(t, f)
        G.overlay(f, ref)
        vis = G.run_suite(task, f, G.test_files(task, f))
        ok(sorted(vis["tests"]) == sorted(oracle["visible_tests"]) and set(vis["tests"].values()) == {"pass"},
           f"{t}: reference yields exactly the frozen visible test IDs, all pass")
    g1 = G.grade(t, ref, repeats=repeats)
    ok(sorted(g1["hidden"]["not_passing"]) == [] and g1["label"] == "CORRECT", f"{t}: reference hidden oracle passes")
    g2 = G.grade(t, ref, repeats=repeats)
    ok(g1 == g2, f"{t}: grading the reference twice gives identical results")
    for name, meta in sorted(G.load_candidates(t).items()):
        g = G.grade(t, G.candidate_files(t, name), repeats=repeats)
        ok(g["label"] == meta["expected_grade"], f"{t}: {name} grades {g['label']} (expected {meta['expected_grade']})")
        ok(g.get("hidden_leak_into_a_view") is False, f"{t}: {name}: no hidden content in the A-view tree")
    wp = task["write_paths"][0]
    for bad, why in (({"../evil.py": "x"}, "path traversal"), ({"/etc/x.py": "x"}, "absolute path"),
                     ({".git/hooks/pre-commit": "x"}, "reserved path"), ({wp: "a\0b"}, "NUL byte")):
        ok(G.grade(t, bad, repeats=1)["label"] == "INVALID", f"{t}: {why} candidate grades INVALID")
    with tempfile.TemporaryDirectory() as d:
        cdir = Path(d) / "c"
        cdir.mkdir()
        os.symlink(str(G.TASKS / t / "reference" / wp), cdir / wp)
        ok(G.grade(t, cdir, repeats=1)["label"] == "INVALID", f"{t}: symlinked candidate file grades INVALID")


def main() -> int:
    repeats = 1 if "--quick" in sys.argv else G.REPEATS
    check_seal()
    for t in MM.task_ids():
        check_task(t, repeats)
    print(f"\n{'OK' if not FAILURES else 'FAILED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
