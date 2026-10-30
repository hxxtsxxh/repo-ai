# `repo-ai verify` pre-release audit (2026-10-23)

## Scope and method

**What was audited:** PR #25 (`verify/adaptive`) at `1a86667`, before the
held-out-5 freeze.

**How:** four read-only reviews ran in parallel. Each could write only to its
own scratch directory and none edited the repository:
- a benchmark skeptic;
- process isolation and cancellation;
- correctness and caching;
- performance.

The lead then:
1. reproduced each claimed defect;
2. turned it into a regression test that fails on `1a86667`;
3. fixed it before the freeze.

Findings not fixed are listed below with the reason.

**Severities** are the reviewers'. "Wrong attribution" means a real regression
reported as pre-existing or as a pass: the outcome this tool exists to
prevent. Every such finding was treated as a release blocker.

## Correctness and caching

Each test below is in `tests/test_verify_audit.py` unless noted, and each one
fails on `1a86667`.

| # | Finding (reproduced) | Severity | Decision | Regression test |
|---|---|---|---|---|
| 1 | A doctest or `load_tests` test re-run "by id" at the base. unittest *called* the named function, so the base always failed and a regression read as pre-existing. | blocker | **fixed**: an id is re-run alone only when it is `<this file's module>.<Class>.<method>`; anything else is compared by file | `test_a_doctest_regression_is_new_not_pre_existing` |
| 2 | "Fails differently" was hidden behind the verdict "all failures pre-existing". | high | **fixed**: its own non-passing verdict, `failing (tests that fail at the base now fail differently)`, plus a `DIFF` line in the report | `test_a_test_that_now_fails_differently_is_not_called_pre_existing` |
| 3 | A new hang (or a load failure) in a file that already had a failing test was called pre-existing. | high | **fixed**: a file that no longer completes, when it completed at the base with specific failures, is a new failure | `test_a_new_hang_in_a_file_with_a_known_failure_is_new` |
| 4 | After a timeout, a file whose tests interleaved with the hung file's (reordered items) was counted as finished, so its unrun failing test was lost. | high | **fixed**: both reporters list every test id per file before running (`collected`); a file counts as finished only when all of its tests ended, and otherwise runs again | `test_interleaved_tests_do_not_make_an_unfinished_file_count_as_passed` |
| 5 | Skipped tests counted as passing: a change that made a whole file skip read as verified. | high | **fixed**: a file that skips every test, or defines none, is run at the base. If its tests ran there, the verdict is `not verified: …`. If they skip there too (a platform skip), it is noted and nothing changes | `test_a_file_whose_tests_all_skip_…`, `test_a_test_that_skips_at_the_base_too_…` |
| 6 | After a dependency upgrade, the base ran with the upgraded dependencies, so a regression read as pre-existing. | high | **fixed**: when a dependency-declaring file changed, a failure that also fails at the base is "not comparable" (verdict `failing (not compared with the base)`) | `test_a_failure_after_a_dependency_change_is_not_called_pre_existing` |
| 7 | An "aggregator" test file that configures what it imports (`conf.STRICT = True`) was skipped as a duplicate. | high | **fixed**: a file is skipped as an aggregator only if its top level is imports, a docstring, `__all__` and a `__main__` guard | `test_an_aggregator_that_configures_its_tests_is_not_skipped` |
| 8 | A test class imported into another file was confirmed and base-checked in its defining module's context. | medium-high | **fixed** by #1's rule (the id must name the file's own module) | `test_a_failure_of_an_imported_test_class_is_compared_in_its_own_file` |
| 9 | A passing batch can hide a failure that only shows when a file runs alone (test-order dependence). | medium | **documented, not changed**: the project's own full suite passes too, and per-file isolation for every passing file would undo batching. Listed under the limitations in `docs/VERIFY.md` | none |
| 10 | Retargeting a symbolic link reused the previous evidence. | medium | **fixed**: a link is identified by its target | `test_retargeting_a_symlink_is_a_different_change` |
| 11 | An edit beyond the first 4 MB of a file reused the previous evidence. | low-medium | **fixed**: identity hashes the whole file, streamed (`changes.content_id`) | `test_an_edit_past_the_first_megabytes_is_a_different_change` |
| 12 | An explicit `--timeout` was not part of the reuse key. | low | **fixed** | (reuse key) |
| 13 | The gate's semantic fingerprint decoded with replacement characters, so two different non-UTF-8 sources could look the same. | low (gate only) | **fixed**: Python parses the bytes (its own decoding rules); JS/TS must decode strictly, or the exact bytes count | `tests/test_verify_gate.py` |
| 14 | `environment_key` lists site-packages by name, so an editable install pointing outside the repository can change unseen. | low | **residual**, documented | none |
| 15 | A hang in session-fixture teardown is charged to the last file. | low | **residual**: the verdict still fails | none |

**Also found by the performance review and reproduced:** a run under the
legacy layout (`repo-ai init` without `--agent`, state in `.bob/context`)
always reported "source tree changed", because the integrity check skipped
only `.repo-ai/state/`.
- **Fixed:** the check skips the layout's own state directory, and the managed
  `.gitignore` block now lists verify's files.
- **Test:** `tests/test_verify_adaptive.py::test_a_legacy_layout_run_keeps_its_own_state_out_of_the_integrity_check`,
  which fails on `1a86667`.

## Process isolation and cancellation (Part 4)

**The earlier incident:** a hang process survived once under heavy load, and
"stopped 0" was printed.
- **Most likely cause:** the test itself, before `918a4d2`.
  - Two parametrizations, and any other suite on the machine, used the same
    `tests/test_hang.py`.
  - The test found "its" process with a system-wide `pgrep`. It could see
    another run's process, signal before its own test started, and then
    count that other process as a survivor.
- **Corroboration:** the one ps sample, a pgid that differed from the pid and
  later equalled it, cannot be a process `_run_host` started, because
  `setsid()` runs before exec. That points to a different process.
- **Fix status:** `918a4d2` gives each run a unique token.
- **No guarantee is claimed from this:** that is an explanation, and the
  review went on to look for real leaks.

**Real leaks found and reproduced deterministically, all fixed.** Tests are in
`tests/test_sandbox_cancellation.py`; each fails on `1a86667`.

| # | Defect | Fix | Test |
|---|---|---|---|
| F1 | A signal delivered while `Popen` waited for the child's exec. The child was not registered yet and had no marker (it had not exec'd), so `terminate_all()` missed it. This affects main-thread runs: the full suite and its base run. | SIGINT, SIGTERM and SIGHUP are blocked in the main thread from before the fork until the pid is registered; the child unblocks them before exec | `test_a_signal_while_the_process_is_starting_never_leaves_it_running` (3 runs; the slow exec is injected) |
| F2 | A process that kept the test process's stdout open stalled the run: until the limit when it was in the group, and forever when it was detached. Cancellation then hung too. | The wait polls the test process. When it has ended, its group and markers are killed and the output is drained for at most `DRAIN_S` (5 s). Every kill path drains with that bound | `test_a_background_process_holding_the_output_…`, `test_a_detached_process_holding_the_output_…` |
| F3 | The host read reports the sandbox could replace with something else. A FIFO blocked the read (reproduced); a link to `/dev/zero` or to a host file was followed. | `isolate.read_inside`: no link under the workspace is followed (`openat` walk with `O_NOFOLLOW`); only a regular file is read; `O_NONBLOCK`; the size is bounded. Used for per-test reports, Python traces and V8 coverage | `test_a_report_replaced_by_something_other_than_a_file_is_not_read` (FIFO, `/dev/zero`, host file, linked directory) |
| F4 | A cancelled container run killed the client, then dropped the container's name, so the container kept running. | `rm -f` before forgetting the name; if removal is interrupted again, the name stays for `terminate_all()` | `test_a_cancelled_container_run_removes_its_container` (stubbed CLI) |
| F5 | A pid could be signalled after reuse: unregistered only after the marker scan. | Unregistered under the lock before the scan | (reasoning; no deterministic test) |
| F7 (lead, Part 4) | **Parent termination:** `kill -9` of the `repo-ai` process. Nothing in it can clean up. A seatbelt test process leads its own session, was reparented to pid 1 and ran on without a limit (the parent enforced the limit). A container outlives its killed client. The marker scan could not help: macOS hides the environment of Apple's own binaries (`/bin/sleep`, `/bin/sh`) from `ps`. | A **guardian** per `repo-ai` process: repo-ai's own code (`python -I`, cwd `/`, never repository code), started at the first sandboxed run. It holds the read end of a pipe only the parent can write. The parent tells it each test process group and container it starts and ends. When the pipe closes, it kills the registered groups whose leader is now an orphan of this user (never a process that reused the pid), and what carries this process's markers, and removes the registered containers. bwrap already had `--die-with-parent` | `test_killing_the_parent_outright_leaves_no_test_process` (3 runs), `test_killing_the_parent_outright_removes_its_containers` (fake CLI) |
| F6 | `allow_runs()` resets cancellation for every caller. | **Not changed**: nothing nests runs today. Recorded as a constraint for any future nested use | none |

**Residual risk, documented:** on macOS, a process that leaves its group
(`setsid`) and is not found by the marker scan survives the run. That is the
case when it clears its environment, or when it is one of Apple's own
binaries, whose environment `ps` does not show.
- It remains confined by the seatbelt profile.
- The run no longer waits for it.
- bwrap (a PID namespace) and containers do not have this gap.

**No absolute cleanup guarantee is claimed.** The tests cover the windows
listed above. A stress run passing is not proof that no other window exists.

## Benchmark methodology (skeptic)

**Verdict:** no blocker. No leakage, ordering problem or post-hoc tuning was
found; the detections and integrity checks are real. The weaknesses are in
how speed is measured and summarised.

| # | Finding | Decision |
|---|---|---|
| 1 | The headline speedup mixes test selection with 4-way parallelism against a serial native baseline. | Held-out-5 adds a `--workers 1` pass (selection effect alone). Held-out-4 text now names the baseline as one process |
| 2 | The geometric mean hides the slow projects, and the target "no execution-time regression" was missed on 3 of 8 without saying "missed". | Held-out-4 now states "missed on tomlkit, jmespath.py and colorama". Held-out-5 reports the arithmetic mean, the failing-only and passing-only geometric means and the maximum ratio |
| 3 | The native time was not checked for whether the suite actually ran (tomlkit's 0.5 s stops at a collection error). | Held-out-5 records the native exit code and output tail |
| 4 | "False alarm" counted only the verdict `regression`, so a passing change reported `full-suite-failed` went uncounted. | Held-out-5 adds "passing change not reported as passing" |
| 5 | `repeat_agree` did not test cache correctness: it reused evidence, with warm caches. | Held-out-5 adds a cold run (verify's state cleared) and compares per-file outcomes, not just verdicts |
| 6 | The TypeScript selection trail was incomplete. | Held-out-5 records every candidate read, in order |
| 7–8 | The sampling favours mutations; re-runs overwrite earlier attempts; the engines were not interleaved. | Held-out-5 keeps superseded attempts, timestamps every run and alternates engine order per project |

The protocol changes are written in PROTOCOL.md Amendment 4a, before any
held-out-5 candidate was searched.

## Performance (not changed before the freeze)

**Reproduced and fixed:** the legacy-layout integrity failure (above).

**Measured, ranked and left for after the freeze.** None is a correctness
issue:
- duplicate git and interpreter spawns: about −0.35 s per run on a small
  suite;
- the fingerprint re-check: −170 ms;
- in-process reaping instead of `ps`: about 30–65 ms per process;
- a node cost model that sums per-file times although node runs files in
  parallel: the slower shape was chosen, about 3× in the demonstrated case;
- per-shape calibration, and `full_unusable` never expiring;
- a per-test progress watchdog (hang cost from at least 30 s to 2–5 s);
- de-duplicating `--record`;
- `clonefile()` of whole directories;
- compiling bytecode once.

The node cost model and the watchdog are the Part 7 candidates.
