# Phase 2: independent evidence for `repo-ai verify` (Session A, 2026-10-24)

## Summary

**The engine under test is main `083b6f1`, unmodified:** the integrated tree with #29, #33, #35,
#37 and #38, installed from a pinned wheel. It was evaluated on **held-out-6**, a fresh set frozen
before selection. It was also attacked by three independent adversarial reviews.

- **The false-assurance invariant does not hold on `083b6f1`.**
  - Ten reproducible defects can show a failing (or stale) state as passing, current or verified
    (D1–D10).
  - One of them (D9, a staged rename gives `nothing-selected`) reproduced on **every** fresh
    project where the scenario could be built: 5 of 5.
  - Another (D10) leaves a TypeScript project tested by plain `node --test` with **no test file**.
  - Every defect has a fix PR with tests that fail before the fix: #41, #42, #43 and #45. None is
    merged.
- **Apart from those defects, verify's verdicts held on fresh data:**
  - 0 new failures reported as pre-existing;
  - 0 false alarms;
  - the working tree unchanged around every run;
  - 24 of 24 cancellation probes clean;
  - stale-evidence, reuse, concurrency, corrupted-state, hang, pre-existing-failure and
    flaky-base scenarios all correct on every project where they were valid.
- **Ground truth is the weakest part of the evaluation.** Several labels did not reproduce when
  re-run quietly:
  - a jsonic file with 5 s per-test timeouts;
  - a websockets asyncio test;
  - mutations in hb-actions's committed `node_modules/`.

  The frozen result counts those as false assurances, as the frozen scorer requires. A separately
  labelled post-hoc recheck sets them aside. Both are reported.
- **Recommendation:** no release of verify's run verdicts as "verified" until #41–#45 are merged
  and re-measured on data not used to make them. See [Release qualification](#release-qualification).

## 1. Frozen protocol and corpus provenance

| Step | Commit (branch `eval/heldout6`) | What |
|---|---|---|
| Freeze | `06b5dfc` | Amendment 5: quotas, candidate lists and queries, constructed scenarios and labels, scorer `score6.py`, gates and thresholds, decision rule |
| Selection | `d8ef027` | 68 reads in order (`results/heldout6/reads.json`), 8 projects pinned in `corpus.json` |
| 5a | `3b17e4b` | native-suite ground truth where the engine lists no test file, and for the control. Written before any verify run on those projects |
| 5b, replacement | `611a58c` | hb-actions universe from node's own discovery; wcd replaced by ha-map-card under the frozen rule; harness fixes before measurement |

**Engine:**
- `083b6f1`, wheel sha256 `cf2c6b3c…5061`;
- images `python:3.12-slim` (`sha256:18d23907…`) and `node:24-slim` (`sha256:156e9bc7…`);
- podman 6.0.2, on a 7-CPU, 2 GiB VM on macOS arm64.

| Quota | Project (pinned) | Runner | Test files | Reference command |
|---|---|---|---|---|
| Python, pytest, deps | pyjwt `16231ab` | pytest | 10 | `python -m pytest tests` |
| | parsel `599897f` | pytest (doctests; pytest 9 `[tool.pytest]`) | 9 | `python -m pytest docs parsel tests` |
| Python, unittest | mkdocs `2862536` | unittest | 20 | `python -m unittest discover -s mkdocs -p "*tests.py"` |
| | websockets `60bc200` | unittest | 43 | `PYTHONPATH=src python -m unittest` |
| Python, large suite | **not met** | — | — | pygments 33, babel 42, werkzeug 27, alembic 39 test files (< 60); networkx and sphinx failed check 1 |
| JavaScript, `node --test` | hubot `9aab11a` | node | 26 (node's discovery) | `node --test --test-timeout=40000` |
| | jsonic `46b8655` | node | 28 | `node --enable-source-maps --test test/**/*.test.js` |
| TypeScript, type stripping | Homebrew/actions `d482da0` | node, `.mts`, its own reporter | 20 by node; **0 by verify** (D10) | `node --test --experimental-test-module-mocks --import ./spec-helper.mts --test-reporter ./test-reporter.mts …` |
| Unsupported runner (control) | ha-map-card `0f2c9f9` (replaced wcd) | Jest (opaque) | 23 | `jest` |

**Windows: not measured.** The measuring host has none, and no Actions spending is authorized.

## 2. Results (frozen scorer)

### Gates

Measured on 114 scenario failing states and 47 wallclock failing changes across 8 projects.
Frozen data and scorer: `results/heldout6/heldout6-score-frozen.json`. Post-hoc data:
`heldout6-score-posthoc-recheck.json`.

| Gate | Threshold | **Frozen result** | Post-hoc: unconfirmed labels set aside (`recheck6.py`) |
|---|---|---|---|
| G1 false assurance | 0 | **missed: 15 failing states**, 28 checks. These are D9 on 5/5 projects; jsonic S3 and 6 jsonic wallclock changes; websockets `mut-03` | **missed: 5 failing states, all D9** (a staged rename) |
| G2 new as pre-existing | 0 | **met** (0) | met (0) |
| G3 runtime no-miss | ≥ 95% | **missed: 28/47 (59.6%)** | 28/34 (82.4%). The 6 remaining misses are the Jest control, whose `full-suite-failed` is never `regression` by design. Excluding it: 28/28 |
| G4 false alarms | 0 | **met** (0) | met |
| G6 tree unchanged | 100% | **met**: every run | met |
| G7 cancellation | all clean | **met**: 24/24 clean (exit 130, signalled while tests ran; no process, container or workspace left) | — |

**What the post-hoc recheck is.** It is not part of the frozen protocol. Each label a score uses was
re-run three times, quietly and alone. A label confirmed in at least 2 of the 3 runs stands.
- **Confirmed:** every label of pyjwt, parsel, mkdocs and hubot, and all websockets labels but one.
- **Not confirmed:**
  - websockets `mut-03`: 0/3 (an asyncio test that failed once under load);
  - all 6 of jsonic's: 0/3. Its only "affected" file has 5 s per-test timeouts and failed under the
    3-way-parallel truth run; the mutations themselves are in `src/*.ts`, which its tests never
    load;
  - hb-actions: a harness artifact. Mutations hit its committed `node_modules/`, and the harness
    copies a tree without `node_modules/`, so the label measured a one-file stub.
- **jsonic S3** is labelled by composition with an unconfirmed change, so it falls with them.

The frozen numbers stand as recorded. The recheck explains them.

### Scenario verdicts (frozen data)

`reg` = `regression`; `pass` = a passing verdict; `pre` = `failing (all failures pre-existing …)`;
`diff` = `failing (tests that fail at the base now fail differently)`; `fsf` = `full-suite-failed`;
**bold** = a pass-like verdict on a failing state. "invalid" means the construction did not
validate before verify ran, so it was excluded.

| scenario | pyjwt | parsel | mkdocs | websockets | hubot | jsonic | hb-actions | ha-map-card |
|---|---|---|---|---|---|---|---|---|
| U1-staged | reg | reg | reg | reg | reg | invalid | invalid | — |
| U2-untracked-test | reg | reg | reg | reg | reg | reg | invalid | — |
| U3-deleted | reg | reg | reg | reg | reg | invalid | invalid | — |
| U4-deleted-staged | reg | reg | reg | reg | reg | invalid | invalid | — |
| U5-renamed-staged | **nothing-sel** | **nothing-sel** | **nothing-sel** | **nothing-sel** | **nothing-sel** | invalid | invalid | — |
| U6-index-differs | reg | reg | reg | reg | reg | invalid | invalid | — |
| C1-stale-evidence | evidence regression, gate blocks | evidence regression, gate blocks | evidence regression, gate blocks | evidence regression, gate blocks | evidence regression, gate blocks | invalid | invalid | — |
| C2-reuse-after-revert | reg | reg | reg | reg | reg | invalid | invalid | — |
| C3-concurrent-same-state | reg | reg | reg | invalid | reg | invalid | invalid | — |
| C4-two-worktrees | reg | reg | reg | reg | reg | invalid | invalid | — |
| C5-edit-during-run | reg | reg | reg | reg | reg | invalid | invalid | — |
| C6-corrupted-state | reg | reg | reg | reg | reg | invalid | invalid | — |
| C8-committed-change | reg | reg | reg | reg | reg | invalid | invalid | — |
| H1-hang | reg (6.6 s) | reg (7.42 s) | reg (6.75 s) | reg (6.79 s) | reg (36.12 s) | reg (36.26 s) | fsf (1807.19 s) | — |
| H2-hang-then-failure | reg (6.6 s) | reg (44.26 s) | reg (6.86 s) | reg (11.45 s) | reg (36.65 s) | reg (36.74 s) | fsf (1807.13 s) | — |
| H3-base-hang-then-failure | reg (1.32 s) | reg (1.56 s) | reg (1.5 s) | reg (1.4 s) | reg (1.2 s) | reg (1.26 s) | fsf (67.09 s) | — |
| S1-preexisting-unrelated | pass | pre | diff | nothing-sel | pass | pass | fsf | — |
| S2-new-failure-in-failing-file | reg | reg | reg | reg | reg | reg | fsf | — |
| S3-mutation-in-failing-file | reg | reg | reg | reg | reg | **nothing-sel** | fsf | — |
| S4-flaky-unrelated | pass | pass | diff/pre | nothing-sel | pass | pass | fsf | — |
| S5-flaky-and-failing | reg | reg | reg | reg | reg | invalid | invalid | — |
| A2-no-deps-failing | pre | pre | pre | reg | reg | invalid | invalid | — |
| A2-no-deps-passing | pre | pre | pre | nothing-sel | pre | pass | fsf | — |
| A1 (control) | — | — | — | — | — | — | — | failing 4/4 fsf, passing 2/2 pass |

**Reading the matrix:**
- **U5 (D9) is the only false assurance on valid states.** The verdict was pass-like, `evidence`
  said current, and the gate was silent, on all 5 projects where the rename could be built.
- **Correct on every project where valid:**
  - staged, untracked, deleted and index-differs changes;
  - stale evidence (C1: evidence not passing, gate blocks), reuse after a revert, two concurrent
    runs, two worktrees, an edit during a run, every state file cut in half;
  - a committed change against `--base`;
  - hangs (H1–H3, including #37's case of a hang at the base before a new failure);
  - a new failure in an already-failing file (S2, S3);
  - a flaky base with a real failure (S5, 3 runs each).
- **hb-actions:** verify lists no test file there (D10), so every run is the full suite. That suite
  already fails at the base (one vendoring test), so every state reads `full-suite-failed`: never
  a pass, never informative. A hang costs the full-suite cap, **1807 s**.
- **The Jest control (A1)** abstains correctly: its 4 failing changes give `full-suite-failed` and its
  2 passing changes give `selected-and-full-suite-passed`.
- **Without the dependency image (A2),** a failing change is never pass-like. A passing change reads
  `failing (all failures pre-existing …)`, or `nothing-selected` where nothing is selected.

### Execution (`wallclock.py`, 6 failing and 6 passing changes per project, container)

| project | native (s) | verify --run median (s) | failing | passing | ratio | detected | missed | pass-like on failing | false alarms | not reported passing | reuse/rerun/cold agree | tree |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pyjwt | 5.97 | 1.96 | 1.96 | 3.88 | 0.33 | 6/6 | 0 | 0  | 0 | 0 | True/True | True |
| parsel | 8.79 | 11.01 | 11.19 | 10.25 | 1.25 | 6/6 | 0 | 0  | 0 | 0 | True/True | True |
| mkdocs | 10.21 | 2.74 | 3.17 | 2.73 | 0.27 | 5/5 | 0 | 0  | 0 | 6 | True/False | True |
| websockets | 11.15 | 4.97 | 6.42 | 2.53 | 0.45 | 5/6 | 1 | 1 ['mut-03'] | 0 | 0 | True/True | True |
| hubot | 33.81 | 1.76 | 19.46 | 1.75 | 0.05 | 6/6 | 0 | 0  | 0 | 0 | True/True | True |
| jsonic | 6.28 | 1.25 | 1.26 | 1.25 | 0.2 | 0/6 | 6 | 6 ['mut-00', 'mut-04', 'mut-07', 'mut-12', 'mut-16', 'mut-19'] | 0 | 0 | True/True | True |
| hb-actions | 4.36 | 6.17 | 6.21 | 6.14 | 1.42 | 0/6 | 6 | 0  | 0 | 6 | True/True | True |
| ha-map-card | 0.19 | 2.8 | 2.81 | 2.79 | 14.74 | 0/6 | 6 | 0  | 0 | 0 | True/True | True |

Notes:
- The native time for ha-map-card is invalid. The wallclock tool times an opaque runner with its
  empty `full` argv (0.19 s), so nothing ran. The 5a native run measured 2.08 s.
- In mkdocs, `build_tests.py` already fails at the base, so every passing change reads `failing
  (…)`.
- The cold run of mkdocs disagreed with its first run on which files were new or pre-existing. It
  was not a pass either time.


## 3. Defects found, and fixes

| # | Class | Trigger (ordinary unless noted) | Fix PR |
|---|---|---|---|
| D1 | false pass | exit status 0 overrides a per-test report that shows a failure (`os._exit(0)`, `SystemExit(0)` in a fixture) | #42 |
| D2 | false pass | node file where no test ran counted as passed (`describe.skip`, `process.exit(0)`, skipped registration) | #42 |
| D3 | false pass | `xfail` / `@expectedFailure` recorded as `pass` | #42 |
| D4 | wrong attribution | a base run cut by the time limit becomes "fails at the base" | #42 |
| D5 | stale shown current | edits inside a submodule are not fingerprinted | #43 |
| D6 | stale shown current | `--skip-worktree` / `--assume-unchanged` files are not fingerprinted | #43 |
| D7 | stale shown current | CRLF normalisation in `content_id`; with `text=auto`, git hides the conversion | #43 |
| D8 | stale shown current | the environment key misses a virtualenv's own site-packages (`-S`) | #43 |
| D9 | **false pass, held-out-6: 5/5** | a staged `git mv` of a module: `nothing-selected`, the gate silent | #41 |
| D10 | **no tests seen** | TypeScript test files under node's default discovery are not listed | #45 |

**Reviews:**
- Each fix had an independent adversarial review.
- #42's first draft caused false alarms (node `todo`, unittest runs inside a test, very large
  reports, script-style node files). Those are fixed, each with a regression test.
- #43's first draft missed CRLF under `text=auto` and deleted flagged files, and nearly tripled the
  fingerprint cost. Both are fixed, and the cost is now about +95 ms on 300–1200-file repositories.

**Validation:**
- The merged tree of #41, #42 and #43 passes the full suite: 1255 passed, 2 xfailed.
- #45 passes alone: 1228 passed.
- **CI was not run:** no Actions spending is authorized.

## 4. Performance

**Every timing has a caveat.** The host was shared, and its load average ranged from 3 to 20,
which is recorded per project in `log-perf.log`. Some runs were inflated, by host sleep or by
contention: hubot's `--full` outliers took 226 and 296 s against 35 s typical. Medians are
reported, and no figure is a release benchmark.

| project | plan (s, median) | --full (s, median) | 1-file change: verify / file alone (s) | non-code change (s) | interpreter start in sandbox (s) |
|---|---|---|---|---|---|
| pyjwt | 0.31 | 6.95 | 0.76 / 0.34 | 6.83 | 0.18 |
| parsel | 0.34 | 14.82 | 0.77 / 0.65 | 8.98 | 0.18 |
| mkdocs | 0.35 | 11.59 | 0.88 / 0.35 | 11.54 | 0.18 |
| websockets | 0.34 | 25.8 | 0.88 / 0.29 | 26.02 | 0.18 |
| hubot | 0.32 | 34.73 | 1.09 / 0.24 | 34.74 | 0.18 |
| jsonic | 0.36 | 7.41 | 1.31 / 0.28 | 7.54 | 0.23 |
| hb-actions | 0.67 | 6.31 | 6.58 / 0.46 | 6.32 | 0.19 |
| ha-map-card | 0.33 | 2.83 | None / None | 2.9 | 0.18 |

**Host sandbox (macOS seatbelt) and container, on the same changes:**

| project | host native (s) | host verify median (s) | container verify median (s) | host detected | host pass-like on failing |
|---|---|---|---|---|---|
| pyjwt | 5.26 | 5.46 | 1.96 | 8/8 | 0 |
| parsel | 8.92 | 10.91 | 11.01 | 8/8 | 0 |
| mkdocs | 9.68 | 2.24 | 2.74 | 5/5 | 0 |
| websockets | 4.52 | 2.9 | 4.97 | 4/8 | 1 |
| jsonic | 3.75 | 1.06 | 1.25 | 0/8 | 8 |
| ha-map-card | 0.08 | None | 2.8 | 0/8 | 0 |

The host comparison is incomplete:
- **hubot:** its native suite did not finish in 41 min under the host sandbox (0% CPU); I stopped
  the measurement, so hubot has no host data.
- **ha-map-card:** `jest` is not on the host sandbox's PATH, so verify ran nothing and reported an
  error (a correct abstention).
- **hb-actions:** not measured on the host. `npm ci` would rewrite its committed `node_modules/`.
- **Changes measured:** perf6 ran stand-alone, so it measured 8+8 changes per project, not 6+6.

**Conclusions:**
- **Planning is cheap:** 0.3–0.7 s per change, with no test run.
- **The fixed cost of `--run` is about 0.4–1.0 s** over running the one affected file alone (0.8–1.3 s
  against 0.24–0.65 s). Interpreter start in the sandbox is 0.18 s; the rest is the copy, the
  integrity check and the base comparison.
- **Selective runs pay off on these suites.** The median `verify --run` against the native suite has a
  geometric mean of **0.36×** over the 7 per-file projects, and is slower on 2 of 7:
  - parsel 1.25×;
  - hb-actions 1.42×, where every run is the full suite.

  Largest single-run ratios: hubot 3.32×, mkdocs 2.18×.
- **Reuse is the big win.** Re-verifying an unchanged state takes 0.6 s on every project. A warm
  `--rerun` and a cold run (caches removed) are close to the first run.
- **A safe fallback costs as much as the native suite:**
  - `--full` is the native suite plus about 1 s;
  - a change to one untracked non-code file (a note) runs the full suite every time;
  - an unsplittable or zero-universe project (hb-actions) runs the full suite on every change.
- **Hang cost:**

  | Case | Settled in | Target | Met |
  |---|---|---|---|
  | unittest/pytest, H1 | 6.6–7.4 s on 4 projects | ≤ 10 s | yes |
  | unittest/pytest, H2 (hang plus failure) | up to 44 s (parsel) | — | — |
  | node | about 36 s on hubot and jsonic | ≤ 15 s | no |
  | a project verify cannot split | 1807 s | — | — |

- **`--workers 1`** is slower than the default (pyjwt 3.4 s against 2.0 s; websockets 11.3 s against
  5.0 s). Parallelism is part of the gain.
- **What to change:**
  - **Correctness first:** merge #41–#45.
  - **Then latency:** a node watchdog with budgets proven against node's event order, and a lower
    full-suite cap when no test file is known.
  - **Not worth tuning further:** the 0.4–1 s fixed overhead. It is small next to reuse (0.6 s) and
    the hang costs.


## 5. Evidence contract for ProofLab

`docs/PROOF-EVIDENCE-CONTRACT.md` and `docs/schemas/proof-evidence-1.schema.json` define schema
`repo-ai.proof-evidence/1`, contract 1.0 (PR #39). They were posted to PR #24 as
`PHASE2_EVIDENCE_CONTRACT`.
- **Five claim levels:** from `not_established` to `supported_by_controlled_comparison`.
- **Observation states and rules:** they close D1–D10.
- **A cap on claims:** claims are capped at `test_passed` while D5–D9 remain unfixed in the
  producing engine.

## Release qualification

**Decision rule** (frozen in Amendment 5). Any G1 or G2 violation excludes the runner, environment or
scenario class involved from a release claim until a fix is validated on data not used to make it.
G1 is violated, both frozen and post-hoc.

| Item (release blockers from `RELEASE-READINESS-2026-10.md` and this phase) | Status after Phase 2 |
|---|---|
| Cancellation leaves nothing running | **resolved** for the tested windows: 24/24 clean on fresh projects |
| Working tree unchanged; sandboxed only | **resolved**: every run on held-out-6 |
| Concurrent sessions, stale or corrupted evidence, reuse across states (#33) | **resolved for the tested scenarios**: C1–C8 correct on every valid project. D5–D8 are other routes to stale-as-current; fixed in #43, unmerged |
| #37: node time-out attribution | **validated on fresh data**: H2/H3 correct on hubot and jsonic (a hang before a failure, a hang already at the base) |
| Hang cost, unittest/pytest | **target met for H1** (6.6–7.4 s ≤ 10 s); H2 up to 44 s |
| Hang cost, node | **supported limitation**: about 36 s (target 15 s missed); node keeps the hard limit |
| Hang cost when verify cannot split, or lists no test | **actual usability blocker**: 1807 s per hang (the full-suite cap) |
| Pre-existing failures, flaky bases | **resolved**: G2 0; S2, S3 and S5 correct. Passing changes in a project with a base failure read `failing (…)`, never pass (a usability limit) |
| Speed on short suites | **mostly resolved by reuse and selection**: geometric mean 0.36× native; slower on 2/7. Fixed overhead 0.4–1.0 s: a supported limitation |
| **D9: staged rename gives `nothing-selected`** (5/5 fresh projects) | **actual correctness blocker.** Fix #41, unmerged; needs validation on new data |
| **D1–D3: exit 0 / node no-test / xfail passes** | **actual correctness blockers** (reproduced, not prevalence-measured). Fix #42, unmerged |
| **D5–D8: stale evidence shown as current** | **actual correctness blockers** for evidence consumers (gate, ProofLab). Fix #43, unmerged |
| **D10: TypeScript under node's default discovery has no tests** | **actual correctness blocker** for TypeScript (with D9-like `nothing-selected` outcomes on per-file runners). Fix #45, unmerged |
| D4: a base time-out counted as a base failure | wrong attribution, not a false pass. Fix #42 |
| Detached test processes outlive a run on macOS (T7; found by Session B's ProofLab review) | **open defect, not a false pass**: survivors stay inside the seatbelt profile. `ps -E` cannot see the run marker of sandboxed processes. Not fixed |
| A committed virtualenv interpreter executed on the host (T24; Session B) | **security blocker, fixed in #40** (unmerged; independently reviewed by Session A: no blocking issue) |
| TypeScript validation | **needs further validation**: the only fresh TypeScript project had 0 test files under verify (D10) |
| Large suites (≥ 60 files) | **needs further validation**: quota not met |
| Windows | **needs further validation**: never measured; no host sandbox there |
| Opaque runners (Jest/Vitest) | **supported limitation**: correct abstention (never pass on a failing change). The full suite every time; not splittable |
| Evaluation ground truth under load | **needs further validation**: 13 of 47 wallclock labels did not reproduce quietly. The next held-out set must run truth serially or confirm each label twice |

### Recommended scope

**No release of `verify --run` verdicts as "verified" from `083b6f1`.**

**After #41, #42, #43 and #45 are merged,** a fresh held-out-7 (truth confirmed by repeat) with G1 = 0
and G2 = 0 would support a **narrow initial release**:
- `verify` (plan) and `verify --run`, for Python `unittest`/`pytest` and JavaScript `node --test`;
- on macOS (seatbelt) and Linux (container or bubblewrap);
- verdicts worded as what they are: "the selected tests passed against the base, in this
  environment";
- evidence consumed through `repo-ai.proof-evidence/1`, levels capped as the contract says.

**Keep experimental:**
- TypeScript, until fresh validation with #45;
- opaque runners (full-suite only);
- Windows;
- very large suites;
- hang-heavy projects on node.

**The read-only plan's "stable" label** (`STATUS.md`) **should be "stable candidate" until then:** D9 and
D10 are plan-level selection defects seen on fresh data.

### The three highest-impact unresolved risks

1. **An empty selection counts as a pass.** `nothing-selected` is a passing verdict, so any blind
   spot in the test universe or the selection becomes a false pass silently. D9 (renames) and D10
   (TypeScript) are two instances, found within a day. Fixing each instance leaves the class. A
   behavioural code change that selects nothing should read "not verified", not passed, and the
   contract would have to say so: a schema-visible change, for Session B and the owner to decide.
2. **Verdicts depend on the runner reporting honestly.** D1–D3 show a test process can make a
   failure look like a pass: exit status 0, node file-level events, expected failures. #42 closes
   the reproduced routes. Others remain:
   - node `process.exit(0)` after results were flushed;
   - a partial `xfail` or `skip` of only the broken test, judged per file;
   - a project's own `--test-reporter` (hb-actions), where verify sees only the exit status.
3. **Unvalidated coverage, measured by noisy ground truth.** Windows, large suites and TypeScript have
   no fresh validation. The held-out ground truth itself proved load-sensitive (jsonic, websockets) and
   blind to committed `node_modules/`. A future pass rate is only as good as its labels.

