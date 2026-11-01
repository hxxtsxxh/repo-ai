# speed-v1: results

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md) (committed with the harness and workflow at 8b8d7e5, before any
measurement), with Amendment 1 (a harness defect: run 1 invalid). Measurement: **run 2**, GitHub Actions run
[41240668799](https://github.com/hxxtsxxh/repo-ai/actions/runs/41240668799), commit 47d950c, 2026-10-31T20:55Z,
`ubuntu-latest` (4 vCPU, AMD EPYC 9V45), Python 3.12, bwrap sandbox. Raw: [results/run-2.json](results/run-2.json);
run 1 is kept as [results/run-1-invalid.json](results/run-1-invalid.json). Spend: $0.

## Speed (the preregistered question)

30 valid changes (5 projects × 6 real upstream commits, replayed on their parents).

| project | native suite, median | verify --run (cold), median | ratio, median | overhead, median |
|---|---|---|---|---|
| jpadilla/pyjwt | 4.95 s | 5.38 s | 1.09× | +0.42 s |
| python-humanize/humanize | 0.16 s | 1.55 s | 8.96× | +1.10 s |
| more-itertools/more-itertools | 1.71 s | 0.72 s | 0.43× (see below) | −0.97 s |
| pallets/itsdangerous | 0.71 s | 1.28 s | 1.84× | +0.58 s |
| marshmallow-code/marshmallow | 0.76 s | 2.53 s | 3.39× | +1.79 s |

- **Geometric mean of the cold ratio: 1.84×. verify was slower on 24 of 30 changes.** By the preregistered reading
  rule, verify is **not** faster than the native suite on these projects.
- **The 6 "faster" changes are not a speed win.** They are all more-itertools, where verify's full-suite run ended
  `full-suite-failed` in about a second while the native suite passed (652–664 tests per change). verify finished early because its
  run failed (cause not yet known, below), not because it was quicker. Without them, verify was slower on all 24.
- **Native "suites" that crashed are not durations either.** In 4 of the 6 humanize changes the native run stopped
  within 0.2 s (a pytest configuration error, or a collection error), which inflates those ratios (4.8–15.8×).
  On the 19 changes where the native suite passed and verify's run did not fail early, verify took 1.99×
  (geometric mean) and was slower on all 19.
- **Two measurements are contaminated** (disclosed after an independent review): the harness reset tracked files
  between changes but did not remove untracked ones, so files added by humanize d7f5dc5d (`lists.py`,
  `tests/test_lists.py`) stayed in the tree for the next two, older changes (f8c144eb, 1bf3f4c7). Their native
  failures and verify's `regression` on `tests/test_lists.py` come from those files, not from the commits. Without
  them: 1.78×, slower on 22 of 28. Amendment 2 fixes the harness for future runs; run 2 stands as recorded.
- **Overhead:** median +0.63 s per change (range −1.26 to +5.88 s). On suites of 0.2–5 s this fixed cost dominates;
  the selection cannot pay for itself when the whole suite takes a second.
- **Re-verifying an unchanged state** (evidence reused): median 0.20 s, at most 0.88 s. A forced `--rerun` with warm
  caches costs about the same as the cold run (geometric mean 1.80× native).

This agrees with the earlier held-out-7 result (slower on 3 of 5 projects, 1.44–2.31×) and extends it to real
upstream changes: on small, fast pure-Python suites, verify's value is its classification and evidence, not time.

## Agreement with the native suite (reported, not preregistered as a gate)

The exit codes agreed on 16 of 30 changes; in all 14 disagreements the native suite passed and verify exited 1.
Every disagreement was examined:

- **No false assurance**, with little power: verify never exited 0 where the native suite failed (cold, reuse
  or rerun), but only 5 of the 30 native suites failed, all humanize, 2 of them contaminated. (In the invalid run
  1 it seemed to: that was the harness testing an installed release instead of the working tree.)
- **pyjwt, 6 of 6:** native passes; verify reports `failing (all failures pre-existing at the base)`. The failing
  file is `tests/test_jwks_client.py` at base and change alike, consistent with tests that fetch over the network,
  which the sandbox denies. The label is honest, but a suite that passes natively exits 1 under verify, and the
  output does not say the cause is the sandbox's network rule.
- **more-itertools, 6 of 6:** native passes; verify reports `full-suite-failed` with no failing file, no counts and
  no failure detail. **Unexplained**, and a defect in either verify or its sandbox until shown otherwise: it fails
  a passing suite and cannot say why.
- **marshmallow 2fc8207d:** verify ran `tests/mypy_test_cases/test_*.py`, which marshmallow's `norecursedirs`
  excludes, and reported them as pre-existing failures (exit 1). This matches the documented limit: without
  `verify --record`, test files are matched by name. The same tree under `--rerun` gave
  `selected-and-full-suite-passed` (exit 0, full strategy, those files listed as `no_tests`): the verdict changed
  between two runs of one state, which is unexplained and queued with item 1.
- **humanize f772e59b:** native passes (605 tests); verify reports all 5 selected test files failing at base and
  change alike (`pre-existing`). **Unexplained**, like more-itertools. On 9528daf5, fb61d5aa and d7f5dc5d both sides
  fail (an old pytest configuration names the `coverage` module, which is not installed); f8c144eb and 1bf3f4c7 are
  the contaminated measurements above.

## Follow-ups (queued)

1. verify fails tests that pass natively, without saying why: more-itertools (`full-suite-failed`, 6 of 6) and
   humanize f772e59b (5 files). Reproduce in CI with verify's full output and fix, or report the cause. A failed
   run must always say why.
2. Sandbox-denied network: tell the user when failures at base and change are consistent with the sandbox (for
   example a network-denied test), instead of only "pre-existing".
3. Fixed overhead (~0.4–1.8 s): profile the cold path on small suites (copy, base comparison, interpreter start)
   without reducing isolation.

## Run 3: replication after 0.11.5 and #60 (Amendment 3)

Stated before the run in [Amendment 3](PREREGISTRATION.md). GitHub Actions run
[41306386452](https://github.com/hxxtsxxh/repo-ai/actions/runs/41306386452), commit 8cd3afd (main at c462f0e plus the
amendment), 2026-11-01T12:33Z, `ubuntu-latest` (4 vCPU, AMD EPYC 9V74: a different CPU from run 2's 9V45),
Python 3.12, bwrap sandbox, Amendment 2 harness. Raw: [results/run-3.json](results/run-3.json). Spend: $0. Run 2
remains the speed-v1 result; the runs are not pooled.

| | run 2 (47d950c) | run 3 (8cd3afd) |
|---|---|---|
| valid changes | 30 | 30 |
| verify --run (cold) / native, geometric mean | 1.84× | **2.23×** |
| slower than the native suite | 24 of 30 | **30 of 30** |
| overhead, median (range) | +0.63 s (−1.26 to +5.88) | +0.82 s (+0.07 to +6.38) |
| same, more-itertools excluded (24 changes) | 2.64× | 2.61× |
| re-verifying an unchanged state, median (max) | 0.20 s (0.88) | 0.21 s (1.01) |
| exit code agrees with the native suite | 16 of 30 | **23 of 30** |
| verify passed where the native suite failed | 0 (of 5 failing) | 0 (of 4 failing) |

**Question 1 (overhead): no measurable change.** By the reading rule, verify is again **not** faster than the
native suite. The geometric mean rose because more-itertools' six changes now run their tests (1.18×) instead of
ending early with `full-suite-failed` (0.43× in run 2, not a speed win then either). Without more-itertools the two
runs agree (2.64× and 2.61×). Per-project ratios are unchanged (pyjwt 1.09× and 1.10×, itsdangerous 1.84× both,
marshmallow 3.39× and 3.32×, humanize 8.96× and 9.27×). Absolute times are 20–30% higher on both sides, native
included (marshmallow's suite: 0.76 s and 0.97 s median), consistent with the different runner CPU, so absolute
overheads are not compared across the runs. #60's saving (about 80 ms of imports per command; its git change is
macOS-only) is smaller than that run-to-run difference and is not visible here.

**Question 2 (agreement): the attributed causes are confirmed for more-itertools and humanize.**
- more-itertools, 6 of 6: `selected-passed (full suite not run)`, exit 0, where run 2 reported a passing suite
  `full-suite-failed`. The fixes from 0.11.4/0.11.5 (a lint-only `make check` taken for the suite, the unittest
  marker) account for it.
- humanize f772e59b: `selected-passed`, where run 2 had 5 files failing at base and change alike (the missing
  build-time version file, fixed in 0.11.4). f8c144eb (contaminated in run 2) also agrees now. The four humanize
  changes whose native suite fails (an old pytest configuration naming `coverage`, and exit 5, no tests collected,
  on 1bf3f4c7) fail under verify too.
- Still disagreeing, as expected: pyjwt 6 of 6 (`failing (all failures pre-existing at the base)`:
  `tests/test_jwks_client.py`, consistent with the sandbox denying the network) and marshmallow 2fc8207d (files
  matched by name that pytest's `norecursedirs` excludes; the documented limit without `verify --record`). Whether
  verify named pyjwt's failures as sandbox-network suspects is **not recorded**: the harness does not capture
  `summary.sandbox_network_suspected`.

Follow-ups 1 is resolved for more-itertools and humanize f772e59b; follow-up 2 shipped in 0.11.4 (not measured
here, see above); follow-up 3 stays open: the fixed overhead on Linux is unchanged.
