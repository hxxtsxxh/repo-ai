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

**Question 1 (overhead): not answerable in absolute terms; the ratios are flat.** By the reading rule, verify
is again **not** faster than the native suite. Three things changed between the runs (repo-ai, the Amendment 2
harness and the runner CPU), and there is one run per CPU, so no run-to-run variance estimate. Absolute times rose
on both sides for four projects (native ×1.25–1.30: humanize, more-itertools, itsdangerous, marshmallow) and
barely for pyjwt (native ×1.06, verify ×1.07); the absolute overhead (+0.63 → +0.82 s; +0.69 → +0.86 s without
more-itertools) is therefore confounded by the CPU and is not compared. The ratios are comparable and did not
move: without more-itertools 2.64× and 2.61×; per project pyjwt 1.09× both, itsdangerous 1.84× both, marshmallow
3.39× and 3.31×, humanize 8.96× and 9.27×. The geometric mean over all 30 rose because more-itertools went from
0.43× (run 2: `full` strategy runs that ended early with `full-suite-failed`, not a speed win) to 1.18× (run 3:
`targeted` runs of 2 selected test files, below), a different measurement rather than a slowdown. #60's saving
(about 80 ms of imports per command; its git change is macOS-only) cannot be seen in these data.

**Question 2 (agreement): the symptoms are gone for more-itertools and humanize f772e59b; the runs do not isolate
why.** The observations are consistent with the fixes from 0.11.4/0.11.5, but the repo-ai version, the harness and
the CPU all changed, so this is not a controlled test of those fixes.
- more-itertools, 6 of 6: exit 0, `selected-passed (full suite not run)`, where run 2 reported `full-suite-failed`
  on a natively passing suite. Run 3 chose the `targeted` strategy (2 selected test files) on all 6 cold runs,
  where run 2 chose `full`. So exit codes agree on 6 of 6, but verify's full suite on more-itertools ran in only
  1 of the 18 run 3 measurements (the e7331924 `--rerun`: `selected-and-full-suite-passed`, no counts recorded).
  That the full-suite failure is gone is shown once, not 6 times.
- humanize f772e59b: `selected-passed` cold; its `--rerun` ran the full suite, 605 passed and 24 skipped, the same
  as the native suite. Run 2 had 5 files failing at base and change alike. This is the strongest evidence that
  the missing build-time version file (fixed in 0.11.4) was the cause. f8c144eb (contaminated in run 2) also
  agrees now.
- The four humanize changes whose native suite fails (an old pytest configuration naming `coverage`; exit 5, no
  tests collected, on 1bf3f4c7) fail under verify too. "No false assurance" (0 of 4) again has **little power**:
  all four are configuration or collection crashes of 0.15–0.19 s, not tests failing on a defect.
- Still disagreeing: pyjwt 6 of 6 (`failing (all failures pre-existing at the base)`: `tests/test_jwks_client.py`,
  consistent with the sandbox denying the network), and marshmallow 2fc8207d (files matched by name that pytest's
  `norecursedirs` excludes; the documented limit without `verify --record`). Whether verify named pyjwt's failures
  as sandbox-network suspects is **not recorded**: the harness does not capture `summary.sandbox_network_suspected`.
- **Still unexplained, carried forward from run 2:** marshmallow 2fc8207d again gives two verdicts for one state:
  exit 1 cold, exit 0 under `--rerun` (`selected-and-full-suite-passed`).
- Also different from run 2: itsdangerous c2300185 ran `targeted` in run 3 (`full` in run 2): 1.52× against 1.84×.
- In both runs pyjwt's native suite skips 4 tests ("cryptography library not installed") despite the `.[crypto]`
  install; verify and native ran the same environment, so the comparison stands, but the install is incomplete.

Follow-up 1: its symptoms are gone for more-itertools (exit codes; the full suite seen passing once) and humanize
f772e59b; marshmallow 2fc8207d's verdict difference is explained in the addendum below (why the strategy differed is not recorded). Follow-up 2 shipped in 0.11.4 (not measured here).
Follow-up 3 stays open: the Linux overhead could not be compared across these runs.

## Addendum (2026-11-01): marshmallow 2fc8207d's two verdicts

**Recorded, identical in run 2 and run 3:**
- Run order: 5c136b11 first (cold `full`, exit 0, full suite passed), then 2fc8207d cold, reuse and `--rerun`.
- 2fc8207d cold: strategy `targeted`, exit 1, `failing (all failures pre-existing at the base)`. Pre-existing
  failures are `tests/mypy_test_cases/test_class_registry.py` and `test_validation_error.py`, and
  `tests/mypy_test_cases/test_schema.py` is `no_tests`.
- 2fc8207d `--rerun`: strategy `full`, exit 0, `selected-and-full-suite-passed`, all three files `no_tests`, 1,117
  passed.
- marshmallow 4.0.0's `[tool.pytest.ini_options]` has
  `norecursedirs = ".git .ropeproject .tox docs env venv tests/mypy_test_cases"`.

**Inferred** (the harness records neither the argv nor the strategy chooser's reason):
- A targeted run passes the selected files to pytest by path. pytest's `norecursedirs` applies when it recurses into
  directories, so it collects explicitly named files inside one; its code matches a pattern containing a separator
  against the path, which is why the full run skipped `tests/mypy_test_cases`.
- So the verdict depended on which strategy ran: the targeted run reached files the project's own collection
  excludes, and the full run did not. Why the strategy differed between the cold run and `--rerun` is not recorded.
  Both choices are timing-driven (`verify/strategy.py` `decide` compares estimated targeted and full-suite times),
  and the cold run updated verify's timing records before the `--rerun`, but the exact inputs are unknown. One
  thing is clear from the code: the two failing files cannot have gained durations from the cold run, because
  failing runs record none.

This is the documented limit that files are matched by name until `repo-ai verify --record` has captured pytest's
own collection; verify deliberately never removes a test file on a static reading of pytest's configuration. It is
not a new defect. Queued: a note that names such files (QUEUE row 16), and recording `strategy.reason` and the argv
in the harness.

## Run 4: replication after the snapshot fix (Amendment 4)

Stated before the run in [Amendment 4](PREREGISTRATION.md). GitHub Actions run
[41360280119](https://github.com/hxxtsxxh/repo-ai/actions/runs/41360280119), commit 0f5bda4 (0.11.7 at 34cb2e9 plus
the amendment), `ubuntu-latest` on an **AMD EPYC 9V45, the same CPU model as run 2** (run 3 used a 9V74), Python 3.12,
bwrap, Amendment 2 harness. Raw: [results/run-4.json](results/run-4.json). Spend: $0. Run 2 remains the speed-v1
result; the runs are not pooled.

| | run 2 (47d950c, 9V45) | run 3 (8cd3afd, 9V74) | run 4 (0f5bda4, 9V45) |
|---|---|---|---|
| verify --run (cold) / native, geometric mean | 1.84× | 2.23× | **2.00×** |
| slower than the native suite | 24 of 30 | 30 of 30 | **30 of 30** |
| same, more-itertools excluded (24 changes) | 2.64× | 2.61× | **2.26×** |
| overhead, median | +0.63 s | +0.82 s | **+0.38 s** |
| re-verifying an unchanged state, median (max) | 0.20 s (0.88) | 0.21 s (1.01) | 0.16 s (0.69) |
| exit code agrees with the native suite | 16 of 30 | 23 of 30 | **24 of 30** |
| verify passed where the native suite failed | 0 of 5 | 0 of 4 | 0 of 4 |

**Question 1 (overhead): the cold ratio fell below run 3's (2.00× against 2.23×; 2.26× against 2.61× without
more-itertools). By the reading rule verify is still not faster than the native suite** (slower on 30 of 30).

**Decided after the run, not preregistered** (Amendment 4 says only ratios are compared, because runner CPUs may
differ): because run 4 ran on the same CPU model as run 2 and the native suites took about the same time (median pyjwt 4.95 s in both,
itsdangerous 0.71 → 0.68 s, marshmallow 0.76 → 0.67 s, humanize 0.16 → 0.14 s), absolute overheads can be set side by
side with run 2 here, though not with run 3: per-project median overhead pyjwt 0.42 → 0.18 s, itsdangerous 0.58 →
0.30 s, humanize 1.10 → 0.83 s, marshmallow 1.79 → 1.43 s; overall median +0.63 → +0.38 s. That is consistent with
the snapshot fix (PR #69), whose cost the profiler put at most of a comment-only run's own time on a generated
project (cProfile inflates such code; without the profiler that project's comment-only run fell about 0.11 s,
0.34 → 0.23 s, measured on a slower runner, so the saving there may be larger). Confounders: one run per
configuration; repo-ai changed in other ways between runs 2 and 4; run 2 used the harness before Amendment 2 (no
`git clean`), run 4 the Amendment 2 harness; the same CPU model is not the same host, and run 4's native suites were
up to 12% faster (marshmallow ×0.88, humanize ×0.90, itsdangerous ×0.96, more-itertools ×0.97; pyjwt unchanged), so part of the drop may be the host.
Strategies also moved: more-itertools ran `targeted` on 2 and `full` on 4 of its 6 changes (run 3: all `targeted`),
so its ratio is not comparable across runs; within the other 24 changes, marshmallow 2fc8207d, itsdangerous's sixth
change and humanize's second ran `full` where an earlier run had `targeted`, so the 24-change subset is not
like-for-like either. In run 4 the more-itertools full suite passed in all 4 `full` cold runs and in all 6 reruns,
which closes run 3's "seen passing once".

**Question 2 (agreement): 24 of 30, not fewer than run 3's 23.** The only disagreements are pyjwt's 6
(`failing (all failures pre-existing at the base)`, consistent with the sandbox denying the network). The one change
from run 3 is marshmallow 2fc8207d, and it is not a fix: its cold run chose `full` this time (exit 0, 1,117 passed)
where runs 2 and 3 chose `targeted` (exit 1), the strategy mechanism the addendum above describes. So a verdict did
change between runs, through the strategy choice; the C16 limit about 2fc8207d stands, though it did not reproduce
in run 4. No false
assurance (0 of 4 failing native suites, all humanize configuration or collection crashes: little power).

## Run 5: replication with strategy reasons and commands recorded (Amendment 5)

Stated before the run in [Amendment 5](PREREGISTRATION.md). GitHub Actions run
[41374239895](https://github.com/hxxtsxxh/repo-ai/actions/runs/41374239895), commit cc140c1 (main after #78 and #79,
plus the harness change and the amendment), `ubuntu-latest` on an AMD EPYC 9V45 (the CPU model of runs 2 and 4), Python
3.12, bwrap. Raw: [results/run-5.json](results/run-5.json). Spend: $0. Run 2 remains the speed-v1 result; the runs are
not pooled.

| | run 2 (9V45) | run 3 (9V74) | run 4 (9V45) | run 5 (9V45) |
|---|---|---|---|---|
| verify --run (cold) / native, geometric mean | 1.84× | 2.23× | 2.00× | **1.96×** |
| slower than the native suite | 24 of 30 | 30 of 30 | 30 of 30 | **28 of 30** |
| same, more-itertools excluded (24 changes) | 2.64× | 2.61× | 2.26× | **2.27×** |
| overhead, median | +0.63 s | +0.82 s | +0.38 s | **+0.32 s** |
| re-verifying an unchanged state, median (max) | 0.20 s (0.88) | 0.21 s (1.01) | 0.16 s (0.69) | 0.15 s (0.70) |
| exit code agrees with the native suite | 16 of 30 | 23 of 30 | 24 of 30 | **24 of 30** |
| verify passed where the native suite failed | 0 of 5 | 0 of 4 | 0 of 4 | 0 of 4 |

**Question 3 (speed and agreement): by the reading rule verify is not faster than the native suite** (1.96×, slower on
28 of 30; the two faster changes are more-itertools dab9518f and fc5773f4, by 0.06–0.16 s). Agreement 24 of 30, the
same 6 pyjwt disagreements as run 4: `failing (all failures pre-existing at the base)`, now recorded as
`sandbox_network_suspected: tests/test_jwks_client.py` on every one.

**Question 1 (why strategies shifted).** Nine changes ran a different cold strategy across runs 2–4 (more-itertools 6,
marshmallow 2fc8207d, itsdangerous c2300185, humanize 9528daf5). Every run-5 reason names the input that decided it:
- of the nine, more-itertools e7331924 (its project's first change) had no per-file durations and ran `targeted`.
  When the full suite is not required, a missing measurement means `targeted`; in run 5 that reason appears on 9 cold
  calls, 4 of them a project's first change (pyjwt's later changes and itsdangerous's second also lacked durations);
  a change that requires the full suite runs `full` regardless (marshmallow 5c136b11);
- the other eight compared two estimates, and those were close: more-itertools selection ~1.3 s against a measured
  full suite of 1.8 s (`targeted`); marshmallow full 1.33 s against selection ~1.18 s, itsdangerous c2300185 0.73 s
  against ~0.56 s and humanize 9528daf5 0.85 s against ~0.79 s (`full`: with `strategy.py`'s 0.25 s tie margin,
  for example 1.33 ≤ 1.18 + 0.25).

**Recorded within run 5:** the cold and `--rerun` calls on one state chose different strategies on 4 of 30 changes,
each after the cold call had added timings or a full-suite record: humanize f772e59b (targeted → full, full suite estimated at 0.8 s),
humanize 9528daf5 (full → targeted: the full suite's result could not be attributed to files), more-itertools
e7331924 (targeted → full, 1.4 s against 1.3 s) and itsdangerous 4712ab6f (targeted → full, 0.7 s against 0.6 s). So
the same runner chooses differently between two calls on the same state once the recorded inputs change, the pattern of 2fc8207d
in runs 2 and 3. That the earlier cross-run flips happened this way remains inferred: runs 2–4 did not record their
estimates. One reason's wording was wrong ("no a full-suite time yet"); fixed in #83.

**Question 2 (marshmallow 2fc8207d).** The cold and `--rerun` calls each chose `full` and ran the same command,
`PYTHONPATH=src python -m pytest` (exit 0, `selected-and-full-suite-passed`; the three `tests/mypy_test_cases/` files
listed as `no_tests`); the reuse call reported the cold call's record (`reused: true`). The `targeted` path that gave
exit 1 in runs 2 and 3 did not occur, so the addendum's inference about its command is still not checked by a
recorded argv. Why it went `full`: the measured full suite (1.33 s) was within the 0.25 s tie margin of the
selection (~1.18 s).

**Limits.** One run. Not pooled. Estimates come from the same run's timings, so the same runner can choose
differently between calls (above). For reuse calls the new fields describe the earlier run whose record was reused.
`commands` holds the per-file result rows' display commands; a full suite run's command is in `full_suite.command`
(so a `full`-only call can list no `commands`), and the base-comparison runs are not recorded.
