# Next milestone: lower fixed per-run overhead (Part 7: sub-second suites)

## Problem (measured)
- held-out-4, engine ccb0622: the "no execution-time regression" target was missed on all three
  sub-second suites — tomlkit 1.74 s vs 0.50 s native (3.48x), jmespath.py 1.5 vs 0.7 (2.11x),
  colorama 0.8 vs 0.2 (3.25x). The extra 0.6–1.2 s is fixed cost, not test time.
- Performance audit (docs/VERIFY-AUDIT-2026-10.md), cachetools (0.19 s suite): `verify --run`
  0.87–0.97 s; the test process 163 ms. 17 subprocesses; 16 helper spawns ≈ 0.65 s, serial:
  rev-parse 58 ms; build_plan ls-files 42 + detect 155 ms (rev-parse, diff, cat-file per changed
  file, ls-files --others); _same_tree diff 39; 2 interpreter probes 56; worktree_files 2x ls-files
  73; fingerprint re-check (3 spawns) 170; xcode-select 17; `ps` reap 35 per test process.
  Duplicates: ls-files x5, rev-parse --verify x2, diff --name-status x2.
- P3: planning alone is 0.27–0.34 s median, p95 over 300 ms on 9/9 projects.

## Acceptance criteria (development corpus only; never held-out-5)
1. Spawn budget: a `verify --run` of one changed file with a passing targeted run starts at most
   7 helper processes besides test processes (today 16). Asserted by a test that counts spawns.
2. Overhead: on cachetools, tomli and markdown (host sandbox), median `verify --run` wall time
   minus the median native suite drops by >= 40% against the frozen build 2f6ea31, same machine,
   interleaved runs (wallclock.py, `--engine` new/old), and planning (`verify --json`) median
   <= 0.25 s.
3. No correctness change: on the development wallclock set the detected / missed / false-alarm /
   new-as-pre-existing counts equal the frozen build's, and every run keeps the tree unchanged.
4. Guarantees unchanged: the plan-to-copy fingerprint check and the before/after integrity
   snapshot still run on every `--run` (they may get cheaper, not optional).

## Smallest viable change
- One file listing per invocation: `git ls-files -z --cached --others --exclude-standard` once,
  passed to build_plan, detect/fingerprint and worktree_files (today five listings).
- Base resolved once per invocation; `_same_tree` and `diff --name-status` computed once.
- Changed-file blobs read with one `git cat-file --batch` instead of one spawn per file.
- Interpreter/toolchain probe cached by the binary's (path, size, mtime, inode) in the state
  directory (part of the environment key already).
- macOS reaping in-process (libproc / sysctl KERN_PROCARGS2 via ctypes), `ps` as fallback.
- The fingerprint re-check after the copy reuses the listing and the cat-file batch (still a real
  check against the working tree; no mtime trust).

## Out of scope
- Skipping integrity checks, trusting mtimes, caching plans across invocations, changing the run
  shape or the cost model, anything specific to a benchmark project.

## Risks
- Shared listing goes stale if the tree changes mid-invocation: the integrity snapshot (separate
  read) still catches it; the fingerprint re-check must read files, not the cached listing.
- libproc via ctypes: fall back to `ps` on any error; Linux untouched.
- Probe cache: key must include everything the probe result depends on.

## Independent review (Part 8, Loop 1) and the revised plan

The review read the code only; it ran nothing. Its findings change the plan.

**Dropped:**
- **A re-check that reuses the planning-time listing, base or diff.** An edit
  to an unchanged tracked file between planning and copying, or a moved HEAD,
  would pass. The before-snapshot is taken after that edit, so it would pass
  too, and stale evidence would be accepted.
- **The re-check stays fresh after the copy.** Its three git calls may run
  concurrently, which saves wall time but no spawns.
- **Criterion 1 (7 spawns)** is not reachable safely: about 8–10 spawns must
  remain. It is replaced by:
  - a helper wall-time budget;
  - an ordering assertion that the re-check's git calls run after the copy.

**First subset (safe):**
- one `rev-parse` for root resolution;
- `_same_tree` cached by commit pair (immutable);
- the fresh re-check's git calls run concurrently;
- `semantic_fingerprint` reuses the fresh re-check's entries, but still reads
  file contents from disk;
- `cat-file --batch` keyed by blob id from `diff --raw -z -M`, where any
  non-blob is `None`.

**Later, only with oracle tests:**
- **One listing:** raw bytes once, decoded and filtered per consumer, aware of
  submodules, and raising on failure.
  - Oracle fixture: a submodule, a non-UTF-8 name, symlinks, a secret-like
    untracked file and `.claude/`.
  - Must be identical to today's output.
- **The interpreter-probe cache:**
  - key: the invoked path, the resolved stat, and the stat and hash of
    `pyvenv.cfg`;
  - only the prefixes and site directories are cached;
  - shim resolution is never cached.

**Deferred:** in-process reaping on macOS. It is safety-critical parsing
code, to save about 35 ms per process.

**Acceptance (revised):**
- **C2:** at least 10 interleaved runs per project, with a bootstrap 95%
  interval on the median overhead; a p95 target for planning.
- **C3:** add the adversarial tests:
  - an edit during the copy;
  - an empty commit during the copy;
  - names with newlines and non-UTF-8 bytes;
  - gitlink, symlink and binary changes.
- **The goal is stated as absolute overhead.** A 0.2 s suite stays slower
  than running it bare; no ratio is promised.

## Result of the first subset (Part 8, Loop 4)

**Measurement:** `benchmarks/verify-eval/overhead.py`, 10 interleaved rounds
per project on the development corpus. Raw data:
`benchmarks/verify-eval/results/overhead-2f6ea31-vs-p7.json`.
- A is the frozen release candidate `2f6ea31`.
- B is this branch.
- Both run the same change and command in the host sandbox.
- Intervals are bootstrap 95%.

| project | `verify --run` A / B (median) | B − A [95% interval] | plan A / B (median) | plan B − A [95% interval] | plan p95, B | verdicts agree |
|---|---|---|---|---|---|---|
| cachetools | 1.131 / 0.954 s | −0.177 s [−0.208, −0.159] | 0.367 / 0.294 s | −0.073 s [−0.089, −0.069] | 0.333 s | 10/10 |
| tomli | 1.726 / 1.528 s | −0.199 s [−0.262, −0.183] | 0.364 / 0.291 s | −0.074 s [−0.079, −0.068] | 0.331 s | 10/10 |
| markdown | 1.648 / 1.513 s | −0.135 s [−0.208, −0.089] | 0.371 / 0.306 s | −0.064 s [−0.073, −0.057] | 0.341 s | 10/10 |

**Acceptance:**

| Criterion | Status |
|---|---|
| **C1** helper wall-time budget, plus "the re-check reads git after the copy" | ordering **met** (`test_the_re_check_reads_git_after_the_copy`); spawns: per changed file → 1 batch; root `rev-parse` and repeated `_same_tree` removed; semantic fingerprint without 3 extra spawns |
| **C2** fixed overhead −40%; plan median ≤ 0.25 s | **not met.** Overhead fell by about 13–20% (−0.14 to −0.20 s a run; native times are from the stored development measurement, so the percentage is approximate). The plan median is 0.29–0.31 s and its p95 is 0.33–0.34 s, still above the 300 ms budget of proposal P3 |
| **C3** no correctness change | **met** for these runs (verdicts agree 10/10 on each project). Oracle tests: batched blobs equal the per-file reads (rename, delete, binary, symlink, gitlink, a newline in a name, unicode); one listing gives the same two fingerprints; edit and commit during the copy are caught. The full suite passes (657) |
| **C4** guarantees unchanged | **met:** the fingerprint check after the copy is read fresh, and the integrity snapshots are unchanged |

**Remaining overhead, for the next iteration:**
- the two interpreter probes (about 56 ms, cache with the strengthened key);
- the duplicate `ls-files` listings (about 115 ms, one listing with oracle
  tests);
- `ps` reaping (about 35 ms per test process);
- planning's fixed work: the dynamic-loading scan and the index.

These are bounded follow-ups. None is in this branch.
