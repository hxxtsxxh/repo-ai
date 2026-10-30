# abc-v1 results (Bob only, n = 4 tasks, 1 run per cell)

**Verdict: `NOT_YET_DEMONSTRATED`.** Four synthetic tasks, one provider, one run per cell, no repeats.
No significance, superiority or "lift" claim is made or possible from this sample.

* Manifest: `manifest.json` (task, hidden-test and grader sha256 frozen before the live runs; verify with
  `python make_manifest.py verify`). Order was seeded and counterbalanced per task.
* Provider: IBM Bob 2.0.9, `--max-turns 8`, cap $0.50 per call, 400 s. Arm A = bare `bob run` with the task prompt.
  Arm B = `repo-ai do ... --agent bob --allow-live-provider --run` (adds write-path constraints, isolation,
  frozen visible-test verification). Arm C (multi-agent/tournament) is **NOT_RUN**: the tournament is replay-only.
* Grader: `grade.py`, run in a separate temp copy. The hidden tests were never in the agent workspace or prompt.
  Only `task.write_paths` of the produced candidate are honoured (edits to tests are ignored and reported).
  Arm B is graded from the diff stored in the mission, applied to a fresh copy; Arm A from the resulting file.
* Author of the tasks, hidden tests and harness is the same agent family as the provider: this is not an
  independent evaluation. Tasks are synthetic, small, and not repository-disjoint from each other's style.

| task | cluster | A (bare Bob) | B (repo-ai + Bob) | repo-ai said |
|---|---|---|---|---|
| py-ledger | python_stateful_finance | CORRECT | CORRECT | PASS |
| py-ttlcache | python_cache_expiry | CORRECT | CORRECT | PASS |
| node-slug | node_cjs_text_utils | FALSE_GREEN | FALSE_GREEN | PASS |
| node-versions | node_cjs_protocol_parsers | FAIL | CORRECT | PASS |

Counts: A 2/4 CORRECT, 1 FALSE_GREEN, 1 FAIL. B 3/4 CORRECT, 1 FALSE_GREEN. Differences are 1 task out of 4
(node-versions) and are consistent with noise.

**Important negative finding.** On `node-slug`, repo-ai reported `PASS` / `LIVE_CANDIDATE_VERIFIED` for a candidate
that fails the hidden requirement (unique suffixes across the whole list). repo-ai's frozen oracle is the *visible*
test suite; it cannot catch a requirement the visible tests do not state. A PASS means "the enumerated visible
checks passed", not "correct". This is the documented meaning of the label, and this run is the counterexample.

Observed provider cost of the 8 graded runs: $0.846926 (provider-reported, not billing truth). Failed/discarded
harness attempts (arm A env bug, stdin consumption, diff trailing-newline bug found by this study and fixed in
`3ea193f`) are kept under `dist/reality-engine/bob-live/abc-v1-runs/final-attempt*` and counted in the spend ledger.

Not done / blocked: other providers (Claude BLOCKED_AUTH in scratch HOME, Gemini rejected, Codex see handoff docs),
repeated runs, repository-disjoint real projects, human-intervention measurement, arm C.

## Manifest amendment (disclosed)

After the live runs, the full-suite qualification of `2eba626` failed 6 `test_abc_protocol` cases: stale
`__pycache__` files (created by `compileall`) were copied into the grading directory and broke the Python hidden
runs (`INCONCLUSIVE`). `grade.py` now ignores bytecode; only its sha256 in `manifest.json` changed. Task, hidden-test
and decoy/reference hashes are unchanged, so the live-run candidates would grade identically (the live runs happened
on a tree without bytecode). The failure was in the harness tests, not the product, and was a real
false-INCONCLUSIVE hazard that `test_stray_bytecode_cannot_change_a_grade` now pins.
