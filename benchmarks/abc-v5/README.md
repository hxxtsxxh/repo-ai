# abc-v5: false-green detection (preregistered; calibration only so far)

abc-v5 asks whether repo-ai's evidence (frozen verification plus `repo-ai coverage` over a requirement map declared
before any candidate existed) catches **false greens**: candidates that pass the visible tests but violate a stated
requirement. It also asks what that costs on correct candidates. The protocol is in
[PREREGISTRATION.md](PREREGISTRATION.md). This directory holds only the **calibration** split: 4 synthetic tasks, a
sealed grader and a free offline harness. **No live model or provider was invoked. Spend: $0.**

| file | role |
|---|---|
| `PREREGISTRATION.md`, `power.py` | protocol and exact planning arithmetic (`python power.py`) |
| `manifest.schema.json`, `make_manifest.py` | write-once manifests: `manifest.w.json` (stage W, before candidates), `manifest.json` (FULL, before any arm) |
| `grade.py` | sealed hidden-oracle grader: CORRECT / FALSE_GREEN / FAIL / INVALID |
| `run_offline.py` | arms A, A0, A_clean, B (`repo-ai do --agent replay --run` + `repo-ai coverage`), B+, A+, A++ |
| `selfcheck.py` | manifest seal plus grader controls (the free protocol check) |
| `results/calibration.json` | observed calibration run (not hashed; produced after the FULL freeze) |

## Reproduce

Use an interpreter with `pytest` and `pathspec`, plus Node 24. repo-ai is taken from `../../src` through
`PYTHONPATH`.

```sh
python make_manifest.py verify     # OK
python selfcheck.py                # 0 failing checks
python run_offline.py              # writes results/calibration.json (~4 min)
```

## Freeze evidence

* Commit `13f5b67` (stage W) holds the statements, `repo/`, the acceptance tests, the requirement maps and the
  follow-up pools.
* Commit `598ed2d` (FULL) adds the hidden oracle, the candidates, the grader and the harness.
* Arm B was first run after `598ed2d`, and the run records that HEAD. `run_offline.py` was debugged beforehand on two
  throw-away dev tasks outside this tree, so no calibration B result was seen before the freeze.
* The grader's A-view is arm A's decision, and it was seen while the controls were being developed. That is
  unavoidable: decoys are A-green by construction.

## Calibration result (n = 4 tasks, 29 candidates; NOT confirmatory, one author for every role)

Rows are the grader's label and columns the decision. "abst." is ABSTAIN.

| label (n) | A naive | A_clean | **B repo-ai** | B+ directed follow-up | A++ test every requirement |
|---|---|---|---|---|---|
| CORRECT (4) | 4 accept | 4 accept | 2 accept, 2 abst. | 4 accept | 4 accept |
| FALSE_GREEN (19) | 19 accept | 11 accept, 8 reject | **5 accept**, 4 abst., 10 reject | 7 accept, 12 reject | 2 accept, 17 reject |
| FAIL (6) | 6 reject | 6 reject | 6 reject | 6 reject | 6 reject |

How many false greens each rule accepted, by stratum:

| stratum | A | A_clean | B | B+ | A+ | A++ |
|---|---|---|---|---|---|---|
| semantic decoys | 9/9 | 9/9 | **5/9** | 7/9 | 8/9 | 0/9 |
| process controls | 10/10 | 2/10 | **0/10** | 0/10 | 10/10 | 2/10 |

## What the calibration shows

* **The lemma held (PREREGISTRATION section 3).** B's task-level discrimination J was 0 on all 4 tasks. In
  `cal-py-backoff` and `cal-node-roman`, every semantic "catch" by B was an ABSTAIN that B also gave the correct
  reference (an `UNMAPPED` R5 and a `NOT_DISCRIMINATING` R3). In `cal-py-sizes` and `cal-node-chunk` the maps were
  complete but weak, and B accepted all 5 decoys together with the reference. On the primary pairs, b = x = 2.
* **Only 2 of B's 4 semantic catches were actionable.** For `decoy-r5-bool` and `decoy-r3-lowercase`, B named the
  requirement the decoy actually breaks. For the other two, the named gap was a different requirement.
* **B+ shows both sides.** Directed follow-up removed every abstention on correct candidates (4/4 accepted). It also
  turned two accidental abstentions into acceptances, `decoy-r3-partial` and `decoy-r2-repeats`, so semantic false
  greens accepted rose from 5/9 to 7/9. B+ caught the primary decoy while accepting the reference on 1 task (J = 1,
  `cal-node-roman`), the only candidate-dependent semantic catch observed. A++ caught everything except 2 process
  controls, but it used every requirement's test (4-5 per task) where B+ used 1 per gapped task. The follow-up pool
  was written by the same author as the decoys, so this comparison is circular in calibration.
* **Process gaming is where B differs from A on the candidate itself.**
  * B refused all 8 test-edit controls. With `--allow-write` widened to the test files (`B_perm`), it still refused
    them all: "frozen acceptance inputs/config cannot change". A_clean also catches these.
  * The Node source-level `process.exit(0)` control (`ctl-srcskip`) fooled both A and the careful A_clean. B rejected
    it (verdict INCONCLUSIVE) in both Node tasks. This is the only false green where B beat a careful developer.
  * The Python equivalent (`pytest.skip` at import time) was already caught by pytest's exit code 5 (no tests
    collected).
* **The claims heuristic** gave `ASSURANCE_PARTIAL` on all 13 A-green semantic and reference candidates, so it does
  not discriminate (consistent with CHANGELOG 0.9.0.dev3).
* **Arm B ran end-to-end with existing commands.** No step was missing. Two coverage-semantics findings for the
  maintainers:
  1. `NOT_DISCRIMINATING` is decided per requirement. One mapped test that already passes at baseline makes a
     requirement unverified even when another mapped test is fail-to-pass (`cal-node-roman` R3).
  2. A "reject X" requirement whose baseline already rejects X, for the wrong reason, can never be verified
     fail-to-pass (for example `cal-py-sizes` follow-up R3-R5 pass at baseline).

Pilot statistics (`repo_ai.stats.compare_clustered`, 4 < MIN_PAIRS): H1 McNemar p = 0.5, H2 p = 1.0, both
`inconclusive (pilot)`. These numbers inform nothing confirmatory, and the confirmatory split must not reuse any task,
cluster or test from here. Proposed protocol changes are in [AMENDMENTS.md](AMENDMENTS.md).
