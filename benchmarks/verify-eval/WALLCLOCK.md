# Developer waiting time and correctness of `verify --run`: the adaptive engine against the previous one

**What this measures:** the whole `repo-ai verify --run` command, as a
developer waits for it, on failing **and** passing changes. Both engines run
in identical conditions. They are compared with the project's own full suite,
run in the same sandbox as one process.

**Script:** `wallclock.py`. Tables: `wallclock_tables.py`. No numbers are
copied by hand.

**Engines:**
- **new:** this branch, installed from a frozen commit (named per table).
- **old:** `cf56523`, `main` before this work: the engine of PRs #21–#23,
  installed separately.

**Per project:**
- **Setup:** a fresh clone at the corpus commit, a clean `init` (committed),
  then `--record`.
- **Session:** the first 8 failing and the first 8 passing changes by the
  ground truth, interleaved, each applied, `verify --run --json`, then
  reverted.
- **Repeat:** the last three changes again, then again with `--rerun` (new
  engine; warm caches).
- **Integrity:** every run is wrapped in a byte-level digest of the clone.

**Conditions:**
- macOS 26, Apple Silicon, `--workers 4`, one project and one engine at a
  time.
- **Sandbox:** the host sandbox (seatbelt, the project's interpreter, Node
  24) for standard-library projects. For projects with a ground-truth image
  (held-out-3) and for peewee, the network-less podman container with that
  image.
- **Native full suite:** the project's reference command in the same
  sandbox, one process, in a disposable copy, median of 3.

**Correctness, against the ground truth** (`truth.json`: test files that pass
at the base and fail with the change, each run alone in the container):
- **missed:** a failing change not reported as `regression`.
- **false alarm:** a `regression` that names a file passing at the base in the
  ground truth and not affected by the change.
- **regression outside the ground truth:** a `regression` naming only files
  that fail at the base *in the container* but pass on the host. The ground
  truth cannot judge these.
- **new reported as pre-existing:** a truly affected file classified as
  already failing at the base. This is the dangerous direction.

**Processes:** the new engine reports its own sandboxed processes. The old
engine's are derived from its evidence (batches + per-file runs + base
re-checks + full suite); its algorithm is deterministic.

The earlier `E2E.md` measurements (engine `75679e9`, a different session
design) stay as recorded.

## Why the previous engine was slow (profiled, engine `cf56523`)

Profiles of single `verify --run` invocations on corpus changes (`cProfile`
plus the engine's own log) showed four causes, in order of cost:

1. **Process count grew with failures.**
   - A failing batch was re-run file by file, and every failing file was then
     re-run whole at the base, each in its own sandboxed process and copy.
   - culori `mut-00`: 47 selected Node files ran as 47 processes, and the 37
     failing files were re-checked as 37 more. The run took 14.8 s, against a
     1.3 s suite.
   - peewee in podman, when a change broke `import peewee`: the batches, then
     46 per-file runs and 46 base re-checks, about 90 container starts. The
     median was 96 s, against a 21 s suite (E2E.md).
2. **Base re-checks re-ran whole files**, even when one test failed.
   - elementpath `mut-02`: 1.4 s of a 3.5 s run was one file re-run at the
     base for three failing tests.
   - Nothing was remembered between runs, so every change on the same base
     re-checked the same pre-existing failures. culori has ten
     environment-specific failures, so every culori change paid for ten base
     re-checks.
3. **Duplicate and unbounded work:**
   - an aggregator file (`tests/__init__.py`, which imports every test module)
     re-ran the whole suite beside the modules it imports;
   - a change that made tests loop forever cost the per-file limit (600 s)
     per hanging file (E2E.md: 602 s and 1228 s maxima);
   - when the full suite was required, the selection ran first, so its tests
     ran twice.
4. **Fixed overhead:**
   - change detection ran twice per run (0.28 s each), and about 19 `git`
     subprocesses ran per run (about 37 ms each);
   - in podman, three container-CLI probes per run cost about 0.9 s.

The remedies are listed in CHANGELOG.md ("Adaptive execution"). Each
safeguard is in VERIFY-THREAT-MODEL.md (T16–T21).

<!-- results below are generated: python wallclock_tables.py results/wallclock-summary.json:<set>-new-<commit> results/wallclock-summary.json:<set>-old-cf56523 (per-run records: results/archives/wallclock-2026-10-22.tar.xz) -->

## What the runs show

**Fresh held-out-4** (frozen engine `ccb0622`), in each project's image:
- the median `verify --run` took **0.62×** the time of the native full suite
  (geometric mean over 8 projects), against 1.06× for the previous engine;
- 0.59× the previous engine's time;
- both engines caught all 55 failing changes;
- neither raised a false alarm or called a new failure pre-existing;
- the tree was byte-identical around every run of both.

**Development corpus** (17 projects of the earlier sets, new engine `43f7b22`):
- 1.16× native against 2.16× for the previous engine;
- 0.54× the previous engine's time.
- **Detection:** 123 of 124 failing changes, against 124. The one is markdown
  `mut-04`, a confirmed new failure reported as `full-suite-failed` after the
  full suite timed out. That verdict bug was fixed in `bcfadc6` before the
  held-out-4 freeze.
- **Shared by both engines:**
  - one false alarm (pyfakefs `mut-09`, a macOS-only code path the Linux
    ground truth does not exercise);
  - two affected files reported as pre-existing (culori `mut-05`: the same
    test already fails at the base in the host's Node).
- **Integrity:** the tree was unchanged around all 502 runs.

**Where it is still slower than native:** suites that take well under a
second (cachetools, tomli, pyflakes, simplejson, tomlkit, jmespath.py,
colorama). Planning, the copy and the integrity check cost about 0.5–1 s.

**`--record`** is 20–150% slower than before, because it now times the
native full suite once.

## Development corpus (17 projects of the earlier sets; regression fixtures, not validation)

New engine `43f7b22` (the first development pass; the fixes it prompted are listed in FREEZE.md), old engine `cf56523`.

| project | sandbox | native full suite | new: median (failing / passing) | old: median (failing / passing) | new / native | old / native | processes per run, new / old (median) | files run twice, new / old |
|---|---|---|---|---|---|---|---|---|
| elementpath | host | 2.32s | 1.33s (1.67s / 1.31s) | 2.44s (3.12s / 1.48s) | 0.57x | 1.05x | 4.00 / 4.00 | 10 / 17 |
| pyfakefs | host | 1.51s | 1.70s (1.74s / 1.42s) | 3.36s (3.82s / 2.88s) | 1.13x | 2.23x | 5.00 / 12.00 | 11 / 97 |
| markdown | host | 0.59s | 1.38s (1.40s / 1.38s) | 3.42s (3.40s / 3.42s) | 2.34x | 5.80x | 1.00 / 11.50 | 2 / 95 |
| culori | host | 1.31s | 1.94s (1.99s / 1.92s) | 4.50s (5.19s / 4.17s) | 1.48x | 3.44x | 1.00 / 22.50 | 0 / 0 |
| simple-statistics | host | 1.81s | 0.90s (0.90s / 0.98s) | 2.31s (2.34s / 2.08s) | 0.50x | 1.28x | 1.00 / 10.00 | 0 / 0 |
| boltons | podman | 2.40s | 1.08s (1.19s / 0.80s) | 1.64s (1.94s / 0.93s) | 0.45x | 0.68x | 1.00 / 2.00 | 0 / 0 |
| toolz | podman | 0.67s | 1.29s (1.30s / 1.27s) | 2.63s (2.67s / 2.04s) | 1.93x | 3.93x | 2.00 / 4.00 | 0 / 12 |
| parse | podman | 0.99s | 1.80s (1.83s / 1.71s) | 4.29s (4.64s / 1.85s) | 1.82x | 4.33x | 1.00 / 6.00 | 0 / 21 |
| itsdangerous | podman | 0.68s | 1.56s (1.98s / 1.50s) | 2.38s (3.89s / 1.54s) | 2.29x | 3.50x | 1.00 / 4.00 | 0 / 0 |
| ZENCHE | podman | 7.85s | 1.33s (3.50s / 0.82s) | 2.44s (4.45s / 1.04s) | 0.17x | 0.31x | 1.00 / 1.50 | 4 / 0 |
| jmgraph | podman | 1.21s | 2.40s (2.42s / 2.30s) | 2.69s (4.16s / 2.42s) | 1.98x | 2.22x | 1.00 / 2.00 | 0 / 0 |
| FEAScript-core | podman | 2.37s | 2.99s (1.89s / 3.00s) | 2.61s (4.15s / 2.60s) | 1.26x | 1.10x | 1.00 / 7.00 | 0 / 0 |
| cachetools | host | 0.24s | 0.70s (0.73s / 0.68s) | 0.79s (0.82s / 0.71s) | 2.92x | 3.29x | 1.00 / 2.50 | 0 / 21 |
| pyflakes | host | 0.63s | 1.19s (1.23s / 1.18s) | 1.18s (1.82s / 1.11s) | 1.89x | 1.87x | 1.00 / 4.00 | 0 / 36 |
| simplejson | host | 0.47s | 0.98s (1.00s / 0.72s) | 1.25s (2.85s / 0.66s) | 2.09x | 2.66x | 1.00 / 7.50 | 0 / 117 |
| tomli | host | 0.23s | 1.21s (1.25s / 1.17s) | 1.61s (1.89s / 1.23s) | 5.26x | 7.00x | 1.00 / 2.00 | 0 / 0 |
| peewee | podman | 22.52s | 2.71s (6.91s / 2.34s) | 52.19s (94.65s / 19.48s) | 0.12x | 2.32x | 4.00 / 30.00 | 69 / 308 |

| project | failing changes | detected, new / old | missed, new / old (confidence) | false alarms, new / old | regressions outside the ground truth, new / old | new reported as pre-existing, new / old | repeat runs agree (new) | tree unchanged, every run (new / old) |
|---|---|---|---|---|---|---|---|---|
| elementpath | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 1 / 1 | 0 / 0 | yes | yes / yes |
| pyfakefs | 8 | 8 / 8 | 0 / 0 | 1 / 1 | 0 / 0 | 0 / 0 | yes | yes / yes |
| markdown | 8 | 7 / 8 | 1 (mut-04 high) / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| culori | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 2 | yes | yes / yes |
| simple-statistics | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| boltons | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| toolz | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| parse | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| itsdangerous | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| ZENCHE | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| jmgraph | 3 | 3 / 3 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| FEAScript-core | 1 | 1 / 1 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| cachetools | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| pyflakes | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| simplejson | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| tomli | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| peewee | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |

Geometric mean of median wall time over the native full suite, 17 projects: new 1.16x, old 2.16x; new over old 0.54x.
Projects where the new engine's median is at or below the native suite: 5 of 17 (old engine: 2).

| project | `--record`, new (includes one native full-suite run) | `--record`, old |
|---|---|---|
| elementpath | 6.70s | 4.61s |
| pyfakefs | 3.84s | 2.30s |
| markdown | 4.55s | 3.63s |
| culori | 6.85s | 5.75s |
| simple-statistics | 9.01s | 7.34s |
| boltons | 6.89s | 5.53s |
| toolz | 3.38s | 3.08s |
| parse | 3.00s | 2.20s |
| itsdangerous | 2.72s | 2.60s |
| ZENCHE | 18.58s | 15.34s |
| jmgraph | 4.30s | 2.86s |
| FEAScript-core | 5.54s | 3.01s |
| cachetools | 1.70s | 1.27s |
| pyflakes | 2.13s | 1.36s |
| simplejson | 2.80s | 2.20s |
| tomli | 2.05s | 1.57s |
| peewee | 56.39s | 32.20s |

## Held-out-4 (fresh; frozen engine `ccb0622`; every run in the project's network-less image)

| project | sandbox | native full suite | new: median (failing / passing) | old: median (failing / passing) | new / native | old / native | processes per run, new / old (median) | files run twice, new / old |
|---|---|---|---|---|---|---|---|---|
| tomlkit | podman | 0.50s | 1.74s (2.15s / 1.24s) | 3.26s (7.88s / 3.21s) | 3.48x | 6.52x | 4.00 / 8.00 | 61 / 59 |
| cattrs | podman | 70.75s | 27.03s (30.72s / 26.10s) | 46.18s (63.38s / 37.03s) | 0.38x | 0.65x | 4.50 / 36.00 | 22 / 284 |
| loguru | podman | 72.81s | 10.52s (19.32s / 10.28s) | 30.62s (34.74s / 10.74s) | 0.14x | 0.42x | 4.00 / 4.00 | 2 / 24 |
| jmespath.py | podman | 0.73s | 1.54s (1.78s / 1.50s) | 2.01s (2.91s / 1.54s) | 2.11x | 2.75x | 1.00 / 4.00 | 0 / 0 |
| colorama | podman | 0.24s | 0.78s (0.81s / 0.49s) | 1.12s (1.67s / 0.64s) | 3.25x | 4.67x | 1.00 / 2.00 | 7 / 8 |
| cloi | podman | 2.02s | 0.78s (0.80s / 0.73s) | 1.53s (1.53s / 0.99s) | 0.39x | 0.76x | 1.00 / 2.00 | 0 / 0 |
| autoplan | podman | 14.20s | 2.13s (- / 2.13s) | 2.51s (- / 2.51s) | 0.15x | 0.18x | 1.00 / 2.00 | 0 / 0 |
| skyhook | podman | 4.81s | 1.42s (1.56s / 1.36s) | 2.56s (3.58s / 1.38s) | 0.30x | 0.53x | 1.00 / 5.00 | 0 / 0 |

| project | failing changes | detected, new / old | missed, new / old (confidence) | false alarms, new / old | regressions outside the ground truth, new / old | new reported as pre-existing, new / old | repeat runs agree (new) | tree unchanged, every run (new / old) |
|---|---|---|---|---|---|---|---|---|
| tomlkit | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| cattrs | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| loguru | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| jmespath.py | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| colorama | 7 | 7 / 7 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| cloi | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| autoplan | 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| skyhook | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |

Geometric mean of median wall time over the native full suite, 8 projects: new 0.62x, old 1.06x; new over old 0.59x.
Projects where the new engine's median is at or below the native suite: 5 of 8 (old engine: 5).

| project | `--record`, new (includes one native full-suite run) | `--record`, old |
|---|---|---|
| tomlkit | 2.35s | 2.34s |
| cattrs | 116.12s | 46.35s |
| loguru | 110.70s | 38.79s |
| jmespath.py | 2.46s | 1.69s |
| colorama | 1.30s | 1.41s |
| cloi | 4.96s | 3.60s |
| autoplan | 39.25s | 27.04s |
| skyhook | 10.49s | 7.46s |
