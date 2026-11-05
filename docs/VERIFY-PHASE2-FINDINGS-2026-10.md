# Phase 2 adversarial findings on main `083b6f1` (Session A, 2026-10-24)

## How the defects were found

Two independent adversarial reviews of the integrated main ran in parallel, and a dry run of the
held-out-6 scenario harness ran alongside them:
- **Review A:** execution-result integrity. Node event order, time-outs, the watchdog, incomplete
  reports, and how failures are compared with the base.
- **Review B:** state and evidence. Fingerprints, caches, reuse, freshness, concurrency, and Windows
  fallbacks.
- **Dry run:** on previously used projects (h11, geojson-vt). These are development data, never
  reported as fresh.

**What counts:**
- A finding counts only if a pytest test fails on `083b6f1` *because of the defect*.
- Every sandboxed test first shows that the state really fails, either with `--rerun` or with a
  failing test the change introduced. It then checks what verify, `repo-ai evidence` or the gate
  claims about that state.

**Status:** these findings were known before held-out-6 was frozen (`PROTOCOL.md` Amendment 5).
None of them led to adding or removing a scenario. Fixes are post-hoc with respect to held-out-6.

## Defects

"Ordinary" means a plausible developer or agent action; no test author is trying to deceive. Every
defect below is ordinary, except the two variants of D1 noted there.

| # | Class | Trigger | What verify says | Root cause |
|---|---|---|---|---|
| D1 | **false pass** | The change breaks a test, and code later in the same process exits with status 0 (`os._exit(0)` in a helper; `SystemExit(0)` from `setUpClass`/`setUpModule`). The `pytest.exit(returncode=0)` and conftest `exitstatus` variants look malicious. | `selected-and-full-suite-passed`, both files `pass`, HIGH | An exit status of 0 is accepted as a pass without reading the per-test report, which shows the failure and has no `done` event (`engine._run_full`, `_run_batch`, `_run_file`) |
| D2 | **false pass** | node: the change leaves a file with no test that runs. Three forms: a condition skips registration; `process.exit(0)` comes before the broken test; a `describe.skip` wraps the suite | `selected-passed` | The per-file wrapper and suite events count as tests that ran (`results.py`), so the file is not `no-tests` and the skip check never runs |
| D3 | **false pass** | The change marks its now-broken tests as expected failures (`@unittest.expectedFailure`, `pytest.mark.xfail`), something an agent might do | `selected-passed (full suite not run)` | The reporters record an expected failure as `pass` (`rai_result.py`), so T20's skip check never sees it. `@skip` is handled correctly |
| D4 | **wrong attribution** | A base run is cut by the time limit, for example `--timeout` below the base's time | `failing (all failures pre-existing at the base)` | `_file_outcome` turns any untrusted base process, a time-out included, into "fails at the base" |
| D5 | **stale evidence presented as current** | A second edit inside a git submodule | `--run` reuses the pass; `evidence` reports `current: true` | The fingerprint sees only the gitlink entry, not the submodule files the workspace copies |
| D6 | **stale evidence presented as current** | An edit to a tracked file flagged `--skip-worktree` or `--assume-unchanged` (common for local settings) | the same | `git diff` honours the flags, so the fingerprint omits the file, but the workspace copies it |
| D7 | **stale evidence presented as current** | A changed file re-saved with CRLF line endings (a golden file read by a test) | the same | `content_id` normalises CRLF to LF, although its docstring says states that differ anywhere never share it |
| D8 | **stale evidence presented as current** | `pip install -U dep` in the project's virtualenv | `--run` reuses the pass (`reused: true`) | `isolate.site_dirs` runs the interpreter with `-S`, so it lists the base interpreter's site-packages instead of the venv's, and the environment key never covers the venv's packages |
| D9 | **false pass** | A staged `git mv` of a source module (Python and JS) | `nothing-selected`; the gate is silent | A rename whose content is unchanged is judged non-behavioural (Python: equal syntax trees), so the deleted import path selects nothing |
| D10 | **no tests seen** (found by held-out-6 setup, after the freeze) | A TypeScript project tested with plain `node --test` (node ≥ 23.6 strips types by default and runs `*.test.ts/.mts/.cts`) | 0 test files; every change, a failing one included, selects nothing | `runner.NODE_DEFAULT_GLOBS` has only the JavaScript forms of node's default patterns |

**Low priority**, each probed but without a test:
- **The JS semantic tokenizer** ends a `//` comment only at `\n`. A `\r`, U+2028 or U+2029 also ends
  one, so two different programs can share a semantic fingerprint. Contrived.
- **A node command that already passes `--test-reporter`** is judged by its exit code alone, because
  verify cannot add its own reporter.

## Attacks that held (summary)

- **pytest:**
  - a module-level `pytest.skip`;
  - a conftest added by the change that deselects tests;
  - `sys.exit(0)` and `os._exit(1)` inside a test.
- **unittest:** `@skip`.
- **node:**
  - late throws and unhandled rejections;
  - top-level throws;
  - `it.skip`;
  - the #37 ordering (hung, done and pending sets).
- **The watchdog:** it turns a stall into a time-out, never a pass. Base and confirmation runs keep
  the hard limit.
- **The environment allowlist.**
- **`--timeout` in the reuse key.**
- **A moved base:** a new commit, an amend or a `--base`.
- **Untracked, deleted and renamed paths** in the fingerprint.
- **Atomic evidence writes and corrupt-record skipping.**
- **The gate's fallbacks** to another session's `latest.json` and to the semantic fingerprint.
- **The integrity check** during a run.
- **No unsandboxed fallback** (Windows reasoned from the code, not run).

## Regression tests and fixes

| Defect | Test file (in its fix PR) | Fails on `083b6f1` | Fix |
|---|---|---|---|
| D1 | `tests/test_verify_exit_status_vs_report.py` | 2 of 2 | #42 |
| D2 | `tests/test_verify_node_no_tests.py` | 3 of 3 | #42 |
| D3 | `tests/test_verify_expected_failure.py` | 1 of 2 (the other is a control) | #42 |
| D4 | `tests/test_verify_base_timeout.py` | 1 of 1 | #42 |
| D5 | `tests/test_verify_fingerprint_submodule.py` | 2 of 2 | #43 |
| D6 | `tests/test_verify_fingerprint_index_flags.py`, `tests/test_verify_fingerprint_coverage.py` | 2 of 2; 1 | #43 |
| D7 | `tests/test_verify_fingerprint_crlf.py`, `tests/test_verify_fingerprint_coverage.py` | 2 of 2; 1 | #43 |
| D8 | `tests/test_verify_environment_key_venv.py` | 2 of 2 | #43 |
| D9 | `tests/test_verify_rename.py` | 3 of 3 | #41 |
| D10 | `tests/test_verify_node_typescript_discovery.py` | 2 of 2 | #45 |

Held-out-6 measurements and the release assessment are in `docs/VERIFY-PHASE2-RESULTS-2026-10.md`.
