# Release-readiness review: PR #25 (`repo-ai verify`, adaptive engine)

## Scope

**What is reviewed:** the PR head at the time of this review.
- **The engine reviewed:** `src/` tree `d0060a3`, unchanged since commit
  `2f6ea31`, the held-out-5 freeze. Later commits change only docs and
  benchmark files.
- **Rule:** a requirement is PASS only when it was shown on this engine.
  Evidence from an earlier commit is listed as NOT MEASURED.

**Classes:**
- **PASS**: shown on this engine.
- **FAIL**: measured on this engine, and the target is missed.
- **BLOCKED**: could not be measured here.
- **NOT MEASURED**: no evidence on this engine.

## Requirements

| # | Requirement | Class | Evidence (this engine) |
|---|---|---|---|
| 1 | No high-confidence miss on a fresh held-out set | **PASS** | held-out-5: 0 misses at any confidence with runtime evidence (135/135); static evidence missed 1 at *medium* |
| 2 | ≥ 95% runtime no-miss | **PASS** | 100% (selection); 55/55 failing changes reported `regression` when run |
| 3 | No false alarm | **PASS** | 0 on held-out-5. One regression the file-level ground truth cannot judge (MusicBot `mut-08`), explained in RESULTS.md |
| 4 | New failures never reported as pre-existing | **PASS** | 0 on held-out-5; the 8 audit counterexamples are regression tests (`tests/test_verify_audit.py`) |
| 5 | Evidence reuse and caches never vouch for a different state | **PASS** | cold and warm runs agree on verdict and files on 7/7 projects; tests for symlinks, edits past the first 4 MB, `--timeout`, and an edit or commit during the copy |
| 6 | Working tree unchanged by every run | **PASS** | every held-out-5 run (both engines); integrity snapshot under the legacy layout (test) |
| 7 | Tests never run unsandboxed | **PASS** | sandbox, sandbox-bwrap and test-macos CI jobs; no unsandboxed path in `verify --run` (threat model T1–T23) |
| 8 | Cancellation leaves nothing running | **PASS for the tested windows**; no absolute guarantee | 21 protocol probes and 12 post-hoc probes clean; signal-during-start, output-holding, detached and parent-SIGKILL tests (`tests/test_sandbox_cancellation.py`). 12 of the 21 protocol probes finished before the signal (not exercised) |
| 9 | Host never follows links or blocks on files the sandbox writes | **PASS** | FIFO, `/dev/zero`, host-file and linked-directory tests |
| 10 | Not slower than the native suite | **FAIL** | slower on 4 of 7 held-out-5 projects (all suites of about a second or less): 1.22–2.52× |
| 11 | Faster than the previous adaptive engine | **FAIL** | 1.06× slower (geometric mean), slower on 7/7 |
| 12 | Hang cost bounded | **FAIL** (known limitation) | two hang mutations cost 91 s and 111 s with both engines |
| 13 | Zero-config test command | **PASS with one partial** | 6 of 7 correct; attrs partial (one extra, failing file) |
| 14 | The runner honours the project's own test-collection config | **FAIL** (found here) | marshmallow: `norecursedirs` excluded files are run, so every passing change reads `failing (all failures pre-existing)` |
| 15 | TypeScript through type stripping | **NOT MEASURED** | the held-out-5 TypeScript quota was not met; last measured on held-out-4 (`ccb0622`) |
| 16 | Windows | **PASS for tests; NOT MEASURED for held-out** | CI `test (windows-latest, py3.10/3.13)`; no Windows held-out run (a container is required there) |
| 17 | Completion gate P1 and P2 | **PASS** | `tests/test_verify_gate.py` |
| 18 | Gate's effect on agent outcomes | **NOT MEASURED** | requires a pre-registered agent experiment (paid; not authorized) |
| 19 | Reproducible packages | **PASS** | wheel and sdist built twice from the PR head with `SOURCE_DATE_EPOCH`: byte-identical (wheel `49712f05…`, sdist `693e248a…`); clean install runs plan, `--run` and `--gate` |
| 20 | Full CI matrix on the engine | **PASS** | `workflow_dispatch` run `39885975985` on `2f6ea31`: 13/13 jobs. PR runs on later, docs-only commits listed in the PR |
| 22 | The whole suite is deterministic in CI | **FAIL** (outside verify) | `tests/test_graph_packet.py::test_killed_update_leaves_a_recoverable_index` failed on Windows py3.10 (run `39883135091`) and on Ubuntu py3.10 (run `39898697152`), and passed on re-runs and locally 10/10. It tests the index's recovery after `repo-ai update` is killed 0.8 s in, code this PR does not change. Either the test is timing-dependent or recovery misses changes. Open before a release |
| 21 | Documentation matches observed behaviour | **PASS** | README, VERIFY.md, the threat model, the audit, the agent contract and RESULTS.md updated with the held-out-5 numbers, including the missed targets |

## Verdict

**READY TO MERGE AS EXPERIMENTAL, NOT READY TO RELEASE.**

**Why merge:** correctness, attribution, isolation, cache safety and
cancellation hold on a fresh, frozen held-out set (rows 1–9). Every defect the
pre-release audit reproduced is fixed with a regression test. The feature is
already labelled experimental in `docs/VERIFY.md`.

**Why not release:**
- The speed targets fail on small suites (rows 10–11). Speed is the main
  reason to use `verify --run` over running the suite.
- A hanging change costs the whole time limit (row 12).
- The runner ignores project-level collection config (row 14), which makes
  passing changes read as failing on such projects.
- TypeScript was not re-validated (row 15).

**Before a release:**
1. Lower the fixed per-run overhead (the Part 7 branch). Then measure on a
   new frozen set.
2. Add a per-test watchdog.
3. Honour pytest `norecursedirs`, `testpaths` and similar settings when
   listing test files.
4. Re-validate TypeScript.

Not merged, no version change, no tag, no publication: each needs the
owner's approval.
