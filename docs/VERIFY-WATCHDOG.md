# Per-test watchdog: design, implementation and acceptance

## Why

In held-out-5, two hang mutations took **202 of 426 s (47.5%)** of the whole
session's wall time, with both engines:
- h11 `mut-04`: 111 s against a 0.44 s suite;
- koa `mut-07`: 91 s against a 4.6 s suite.

Neither hang paid "5× measured time". Each paid the 30 s floor, plus a fixed
15 s container grace and about 10 s of podman stop time, and then the same
again when the hung file was re-run.

## Phase 0: done in `fix/core-correctness`

None of these changes is a new timing policy:
- **Containers:** the run is polled and removed at the limit + 5 s with
  `rm -f -t 0`.
- **Full suite:** a time-out with a known hung test is attributed, and that
  file is not run again.
- **Speed choice:** a time-out never disables the full suite for speed.
- **Explicit limits:** `--timeout` now applies to full-suite runs too. It used
  to become 1800 s there.

**Estimated** (from the code path, not re-measured on the frozen set):
- h11 `mut-04`: 111 s → about 31 s;
- koa `mut-07`: 91 s → about 61 s, since its second hanging file still costs a
  limit.

Tests: `tests/test_verify_timeouts.py`.

## Phase 1: the progress watchdog (implemented for unittest and pytest)

`src/repo_ai/verify/watchdog.py` holds the reader. The sandbox polls it
through `Limits.watch` about every 0.5 s, in both the host loop and the
container loop. Nothing new is injected into the test process: the
reporters already write a line per test start and end.

**When it fires:** when the time since the last report event of any kind
exceeds the budget that applies at that moment.
- **With a test open:** the budget of the file that test belongs to.
  - The file is the one in pytest's node id, so an inherited test is
    charged to the file that collected it.
  - Otherwise it is the reported path inside the workspace.
  - The oldest open test decides.
- **Between tests:** the largest budget of the files the process runs, and
  only if every one of them is measured. This covers `setUpClass`,
  `setUpModule`, teardown, and the gap after the last test.
- **Before the first event (imports and collection):** the same formula
  applied to the *sum* of the measured times of every file the process
  runs, so a 300-file collection is not given a 3-file batch's start-up.
  - The clock starts only when the reporter has created the report, so a
    container that is still starting never counts.

**The budget:** for measured time t, max(5 s, 3·t + 2 s), capped at the
process's hard limit. The watchdog can only shorten a run.

**What t is:** the file's own-process peak in this environment
(`Timings.peaks`). It is the slowest recent whole-file wall time, start-up
included, from runs of the file in a process of its own, decaying by 0.8
per run.
- **Not batch shares:** a share of a batch never updates the peak, because
  costs paid once per batch (a session fixture, a heavy import) are charged
  to whichever file came first.
- **Fallback:** the file's `--record` time, but only when it was recorded in
  the same sandbox backend. It is traced, so it runs slower than an
  ordinary run.
- **Otherwise:** none, and the hard limit applies.
- This is more conservative than the design's "largest gap between events":
  a whole-file time is never smaller than any gap inside it.

**What happens when it fires:**
- The run takes the hard time-out's path: the process group is killed (and
  the container removed), and the result is `timed_out`.
- The open test is reported as not finished: "no test started or finished
  for Ns (budget Bs, in <file>)".
- A stall is always `timeout`, never a pass.

**It is off:**
- with `--timeout`, where the limit is the user's;
- for a file with no measurement, in the checks that need it;
- for node and opaque runners, and with the project's own reporter;
- for **base and confirmation runs**. Budgets are learned from the change's
  code; a base run cut by one would read as failing at the base and could
  make a new failure look pre-existing. Base runs keep the hard limit, so a
  hang that also happens at the base is still classified pre-existing, only
  more slowly.

**The report is untrusted** (the process under test writes it). It is:
- read incrementally, at most 1 MiB per poll and 32 MiB in all;
- opened relative to a run-directory descriptor with `O_NOFOLLOW` and
  `O_NONBLOCK` on POSIX, and only when it is a regular file.

The watch stops, and the hard limit then applies, when the report:
- is replaced by a link or a FIFO;
- passes the read cap;
- has more than 10,000 open tests;
- has a line over 64 KiB.

A test can therefore only make the watchdog wait for the hard limit (by
writing events) or end its own run as a time-out (by going silent).

**Node keeps the hard limit.** A node extension was built, measured and withdrawn (see the
recheck below).
- node writes a file's test events only when its turn comes, after every earlier file's.
- A leaf test's `start` arrives together with its end.
- A file's completion (`file_done`) arrives at once.

So no test is ever "open" in node, and a cut run's report can hold a completed file with none of
its results. That second point was a correctness bug on main, with the hard limit as well: a failing
later file was reported as passing. It is fixed separately (`fix/node-timeout-attribution`). Before
a node watchdog can be reconsidered, its budgets need instrumented evidence against this event
model.

**Changes from the adversarial review of 2026-10-23 (Session B):**
- **With a test open,** the budget is the largest of the open test's file and every file the
  process has already reported. It is none (the hard limit) if one of those files is unmeasured. A
  session or package fixture is torn down inside the last test that uses its scope, which can be
  a fast file's.
- **A passing run that skipped most of a file's tests** updates the blended time but never the peak.
  The peak would otherwise decay toward the skipped run, and the budget toward the floor.

## Acceptance criteria

All are defined before implementation. Each is a gate: a miss is reported as
a miss.

1. **Hang cost:** on the fixtures above, on the host and in podman, at most
   B + 3 s (at most 8 s when the history is ≤ 1 s).
2. **Attribution:**
   - the hung test id (or the file, for a node spin) is in `failing_tests`;
   - the hung file is re-run 0 times.
3. **No false time-outs:**
   - 0 across 10 runs of each legitimate fixture, and of development-corpus
     passing changes, at an emulated 2× contention;
   - silence over budget reported, and at most 0.5.
4. **Never a pass:**
   - a forged report with fake `end` events falls back to the hard limit;
   - a forged stall can only produce `timeout`.
5. **Base symmetry:** a hang that already happens at the base is
   pre-existing; a new hang is new.
6. **Cleanup:** no process or container is left, detached servers included.
7. **A held-out re-run, which needs the owner's approval:**
   - h11 `mut-04` ≤ 10 s and koa `mut-07` ≤ 15 s;
   - no verdict changes on any other change.

**Regression tests** (`tests/test_verify_watchdog.py`):
- the stall reader: budgets, the event clock, unmeasured files, the start-up
  budget and when it starts, the between-tests budget, a replaced report, a
  report past the read cap, forged event floods, giant lines, and inherited
  pytest tests;
- the budget source: batch shares never set a peak, and the start budget
  grows with collection;
- base and confirmation runs keep the hard limit;
- end to end (host, and docker in CI):
  - a hung test (unittest, and a pytest busy spin) is cut and reported,
    never passed;
  - a slow legitimate test is not cut;
  - a setUpClass hang is cut;
  - an explicit `--timeout` turns the watchdog off;
  - a hang already present at the base is pre-existing.

## Results (engineering measurement, 2026-10-23; not held-out)

**Builds:** main `7e77912` (A) against watchdog `35df606` (B), pinned
wheels. Host: macOS seatbelt, 14 cores. Scripts: `scratchpad/meas/wd_measure.py`
and `wd_corpus.py`.

| Criterion | Result | Status |
|---|---|---|
| 1. Hang cost (host) | unittest hung test: **30.5 → 6.2 s**; pytest busy spin: **30.5 → 6.1 s** (3/3 runs each; budget 5 s, so the cost is at most B + 1.2 s) | met on the host |
| 1. Hang cost (containers) | CI docker job: the unittest end-to-end cases pass inside containers. No podman timing (no podman machine on the measuring host) | **not measured** |
| 1. setUpClass hang | **60.6 → 11.8 s**. Both builds pay two cuts: a stall between tests cannot name a file, so the full suite's time-out is unattributed and the file is run once more | improved; see 2 |
| 2. Attribution | the hung test id is in `failing_tests` for a test hang and a pytest spin; re-runs 0 | met, **except a setUpClass hang**: the file is re-run once, on main and on the watchdog alike (a Phase 0 gap) |
| 3. No false time-outs | **0 in 60 contended runs** (in 10 of them, cachetools, no test was selected). Legitimate CPU and sleep tests with setUpClass: 10 runs each at 14, 28 and 42 spinners (median wall 1.2×, 1.3× and 1.65× the unloaded runs, worst 3.1×). Corpus passing changes: tomli and markdown, 10 runs each at 28 spinners (1.6–3.2×), with every verdict identical to A (cachetools' passing change selects no tests). Largest per-file time under load was 2.9 s, against budgets of at least 5 s | met at the contention reached; "silence ≤ 0.5 × budget" was **not instrumented** |
| 4. Never a pass | stalls are always `timeout`; forged events only delay until the hard limit (tests) | met |
| 5. Base symmetry | base runs keep the hard limit; a hang present at the base is pre-existing (end-to-end test) | met |
| 6. Cleanup | no process left after any measured run (by workspace path) | met |
| 7. Held-out re-run | needs the owner's approval; not run | **pending** |

## Recheck on previously used held-out-5 cases (Session B, 2026-10-23)

**These are rechecks of two projects already used in held-out-5 (h11, koa), not a fresh held-out
set.**

**Builds** (pyenv 3.12.14 venvs from wheels):
- A: main `c8831d7`;
- B: watchdog for unittest/pytest, `b6031b9` (#35 with main merged);
- C: watchdog with node, `6a6f854` (withdrawn afterwards, reverted in `895dd33`; its runs are kept as a record);
- D: the final build `e8a490f` (unittest and pytest, with the review fixes).

**Final code (`e8a490f`):** host suite 1209 passed, 2 xfailed; watchdog and adaptive end-to-end tests in podman, 53 passed; Linux full suite in a container (`b6031b9`), 1113 passed, 97 skipped (no sandbox inside the container), 2 xfailed.

**Conditions:**
- the original images, with digests matching `results/heldout5/images.json`, in the network-less
  podman container (podman machine, applehv, 7 CPUs) on macOS 26, Apple Silicon, 14 cores;
- `wallclock.py --engine new` with `VEV_AMENDMENT_4A=1`: 16 h11 changes, 12 koa changes, then
  repeat, cold and `--workers 1` passes;
- one project and one build at a time;
- the host was shared with other work (load average 5–8).

Summary: `benchmarks/verify-eval/results/watchdog-recheck-2026-10-23/summary.json`.

| Criterion | Result | Status |
|---|---|---|
| 1. Hang cost in podman (pytest) | h11 `mut-04`: **36.8 s → 7.1 s** (B) and 7.0 s (C) | **met in a container** |
| 1. Hang cost in podman (node) | koa `mut-07`: **71–143 s on A and on B** (B does not watch node). The withdrawn node build C measured 20.0 s and 24.5 s | **not improved** (node keeps the hard limit) |
| 3. No false time-outs | every verdict identical to A on all 28 changes, and on the repeat, cold and `--workers 1` passes. This held in every run, including 2 koa sessions per build under 28 extra CPU spinners on top of the host's load (the native suite went from about 5 s to 58–84 s) | met at the contention reached |
| 6. Cleanup | no container or process left after any session | met |
| 7. h11 `mut-04` ≤ 10 s | 7.07 s (B), 7.03 s (C), **6.74 s on the final build D** (`e8a490f`) | **met** (recheck, not fresh) |
| 7. koa `mut-07` ≤ 15 s | 71–143 s, with node withdrawn (C measured 20.0 and 24.5 s before withdrawal) | **missed** |
| 7. No verdict changes on any other change | none, in 16 sessions (including the final build D on h11) | met |

**Why koa misses even with the withdrawn node build C:**
- Its two hung files are in one batch. The first hang cuts the batch, with 5 of 18 files finished.
- The 12 files not yet started run as a second batch, and the second hang cuts that too.
- So two budgets are paid in sequence (17–24 s in all).
- Meeting 15 s would need a change to batching, or smaller budgets. Smaller budgets were not made:
  they would trade false-time-out safety for the number.

**Not measured:**
- Windows: there is no free Windows host. On Windows `verify` runs only in a container. The
  watchdog's Windows-specific code (case-insensitive path mapping, and opening the report without a
  directory descriptor) has unit tests, and any error in the watch turns it off, so the hard limit
  applies.
- "Silence ≤ 0.5 × budget" is still not instrumented.
