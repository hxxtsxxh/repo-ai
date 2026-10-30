# End-to-end cost of `repo-ai verify` (wall clock, measured)

**What this measures:** the time a developer actually waits. That is the whole
`repo-ai` command, measured as the wall-clock time of the process:
- planning;
- the disposable copies;
- sandbox start-up;
- the selected tests;
- base-revision re-checks of failures;
- evidence and integrity checks.

**Compared with:** the project's own full-suite command, run once in the same
sandbox with the same interpreter.

**What this is not:** the per-file "share of suite time" in `RESULTS.md`. That
is the sum of per-file test times, a selection-efficiency measure. The two
differ because each selected file pays its own interpreter start-up, while the
full suite pays it once.

**Script:** `e2e.py`. Tables: `e2e_tables.py`. No numbers are copied by hand.

**Environment:**
- macOS 26 (Apple Silicon), host sandbox `seatbelt`, the project's interpreter
  (CPython 3.12) and Node 24.
- `--workers 4`.
- Each project is a fresh clone at its corpus commit.
- Projects from the dev and held-out sets, not held-out-3.

**Scenarios, per project:**
- clean `init`;
- `--record`;
- one detected change;
- three successive edits to one file;
- five changes in five files ("broad");
- a configuration edit (`pyproject.toml` / `package.json`), which requires
  the full suite;
- stale evidence (a change committed, then a second change);
- `--run --full`;
- a session of ten detected changes.

`saved per change` = full-suite wall time − mean `verify --run` wall time over
the session. `break-even` = (`init` + `--record`) / saved per change.

## Results: host sandbox (seatbelt), engine `75679e9`

| project | full suite (sandboxed, one process) | init | `--record` | plan (median) | `verify --run` median (10 changes) | min / max | saved per change | break-even changes | tree unchanged, every run |
|---|---|---|---|---|---|---|---|---|---|
| elementpath | 2.34s | 1.54s | 4.37s | 0.40s | 3.35s | 1.99s / 6.25s | -1.45s | never | yes |
| pyfakefs | 1.61s | 1.19s | 2.61s | 0.41s | 4.01s | 3.30s / 8.85s | -3.32s | never | yes |
| markdown | 0.55s | 1.29s | 3.99s | 0.40s | 3.53s | 2.66s / 602.09s | -63.20s | never | yes |
| culori | 1.33s | 0.90s | 5.87s | 0.38s | 5.28s | 4.51s / 14.02s | -6.89s | never | yes |
| simple-statistics | 1.57s | 0.89s | 7.09s | 0.38s | 2.49s | 2.45s / 3.06s | -1.06s | never | yes |

**elementpath** (`python -m unittest discover -s tests -t .`)

| scenario | selected / universe | confidence | wall time | verdict |
|---|---|---|---|---|
| one change | 2 / 29 | high | 3.15s | regression |
| same file, edit 1 | 2 / 29 | high | 3.22s | regression |
| broad (5 files) | 8 / 29 | high | 7.00s | regression |
| config edit (pyproject.toml) | 2 / 29 | low | 5.36s | full-suite-failed |
| stale evidence (change committed, new change) | 4 / 29 | high | 3.15s | regression |
| re-record after the commit | - | - | 3.99s | - |
| `--run --full` | 2 / 29 | high | 5.28s | full-suite-failed |

**pyfakefs** (`python -m unittest discover -s pyfakefs/tests -t . -p *_test.py`)

| scenario | selected / universe | confidence | wall time | verdict |
|---|---|---|---|---|
| one change | 15 / 16 | high | 3.58s | regression |
| same file, edit 1 | 15 / 16 | high | 3.54s | regression |
| same file, edit 2 | 13 / 16 | high | 3.32s | regression |
| same file, edit 3 | 15 / 16 | high | 5.15s | regression |
| broad (5 files) | 15 / 16 | high | 6.29s | regression |
| config edit (pyproject.toml) | 15 / 16 | low | 5.29s | full-suite-failed |
| stale evidence (change committed, new change) | 15 / 16 | medium | 3.64s | regression |
| re-record after the commit | - | - | 2.48s | - |
| `--run --full` | 15 / 16 | high | 4.92s | full-suite-failed |

**markdown** (`python -m unittest discover -s tests -t .`)

| scenario | selected / universe | confidence | wall time | verdict |
|---|---|---|---|---|
| one change | 10 / 32 | high | 3.42s | regression |
| same file, edit 1 | 10 / 32 | high | 3.41s | regression |
| same file, edit 2 | 29 / 32 | high | 5.50s | regression |
| same file, edit 3 | 5 / 32 | high | 3.47s | regression |
| broad (5 files) | 22 / 32 | high | 665.67s | regression |
| config edit (pyproject.toml) | 10 / 32 | low | 4.42s | full-suite-failed |
| stale evidence (change committed, new change) | 31 / 32 | medium | 6.44s | regression |
| re-record after the commit | - | - | 4.23s | - |
| `--run --full` | 10 / 32 | high | 4.08s | full-suite-failed |

**culori** (`node --test test/**/*.test.js`)

| scenario | selected / universe | confidence | wall time | verdict |
|---|---|---|---|---|
| one change | 47 / 58 | high | 13.46s | regression |
| same file, edit 1 | 47 / 58 | high | 13.70s | regression |
| same file, edit 2 | 47 / 58 | high | 13.63s | regression |
| same file, edit 3 | 37 / 58 | high | 13.05s | regression |
| broad (5 files) | 47 / 58 | high | 14.42s | regression |
| config edit (package.json) | 47 / 58 | low | 14.91s | full-suite-failed |
| stale evidence (change committed, new change) | 11 / 58 | high | 4.67s | regression |
| re-record after the commit | - | - | 5.70s | - |
| `--run --full` | 47 / 58 | high | 15.14s | full-suite-failed |

**simple-statistics** (`node --test test/*.test.js`)

| scenario | selected / universe | confidence | wall time | verdict |
|---|---|---|---|---|
| one change | 6 / 80 | high | 2.81s | regression |
| same file, edit 1 | 6 / 80 | high | 2.75s | regression |
| broad (5 files) | 12 / 80 | high | 4.90s | regression |
| config edit (package.json) | 6 / 80 | low | 4.55s | full-suite-failed |
| stale evidence (change committed, new change) | 5 / 80 | high | 2.56s | regression |
| re-record after the commit | - | - | 7.28s | - |
| `--run --full` | 6 / 80 | high | 4.45s | full-suite-failed |

### What this shows

**On fast suites, selection does not save waiting time.**
- These five suites take 0.5–2.3 s as one sandboxed process.
- `verify --run` waits **2.5–5.3 s (median)**: planning (about 0.4 s), the
  disposable copies, one interpreter start per batch or file, and a
  base-revision re-check of every failing file (all ten session changes are
  detected regressions, so every run re-checks).
- `saved per change` is negative, so `init` + `--record` never pay back here.
- The per-file "suite time" share in `RESULTS.md` (35–56%) is a
  selection-efficiency measure. As these numbers show, it is **not** waiting
  time.

**Hanging tests dominate the mean.** A mutation that loops forever costs the
per-file timeout (600 s by default) in `verify --run`, and the full suite would
hang as well. Python-Markdown's broad change and one session change hit it.
Medians are reported for that reason.

**What a run gives in exchange for its cost:**
- which failures are new and which are pre-existing (per test, against the
  base);
- evidence tied to the exact change, which `repo-ai evidence` reports as
  current or stale;
- the guarantee that the tests never touched the working tree. That held for
  every run: 0 errors and the tree unchanged in all 50 session runs plus the
  scenario runs.

**Stale evidence works as designed.** After a commit changes a recorded file,
the plan falls back to static links for it (pyfakefs, markdown: *medium*).
Re-recording costs one more `--record` (2.5–7.3 s here).

**A configuration edit** (`pyproject.toml` / `package.json`) makes the full
suite required. `verify --run` then runs the selection and the full suite:
4.4–15 s here.

**Not measured on the host:** peewee. Its SQLite queue tests fail with
`disk I/O error` or hang under the macOS seatbelt profile; the cause was not
identified. The developer would see the same behaviour from the sandboxed full
suite. peewee is measured in podman below.

## Results: podman (the ground-truth image), peewee, engine `4602296`

| project | full suite (sandboxed, one process) | init | `--record` | plan (median) | `verify --run` median (10 changes) | min / max | saved per change | break-even changes | tree unchanged, every run |
|---|---|---|---|---|---|---|---|---|---|
| peewee | 21.12s | 2.47s | 31.49s | 0.80s | 96.08s | 51.25s / 1228.41s | -286.12s | never | yes |

**peewee** (`python -m unittest discover -s tests -t . -p *.py`)

| scenario | selected / universe | confidence | wall time | verdict |
|---|---|---|---|---|
| one change | 46 / 46 | high | 96.76s | regression |
| same file, edit 1 | 46 / 46 | high | 104.64s | regression |
| same file, edit 2 | 12 / 46 | high | 38.29s | failing (all failures pre-existing at the base) |
| broad (5 files) | 46 / 46 | high | 107.58s | regression |
| config edit (pyproject.toml) | 46 / 46 | low | 101.72s | full-suite-failed |
| stale evidence (change committed, new change) | 12 / 46 | high | 12.40s | failing (all failures pre-existing at the base) |
| re-record after the commit | - | - | 9.59s | - |
| `--run --full` | 46 / 46 | high | 97.24s | full-suite-failed |

**peewee is the clearest negative result.** Its suite takes 21 s as one
process, and `verify --run` waits **96 s (median)**. The cause:
- **Failing changes are expensive.**
  - When a mutation breaks `import peewee`, all 46 selected files fail.
  - Each failing batch is re-run file by file, and each failing file is
    re-checked at the base. In a container that is about 90 container starts
    for one change.
- **The aggregator file runs the whole suite.** `tests/__init__.py` imports
  every test module, so selecting it means running the whole suite once more
  as one "file".
- **Hanging mutations stack up.** Mutations that loop forever keep several
  files at the 600 s per-file timeout in parallel.

**What would change this** (not implemented):
- attribute a failing batch's failures from its output instead of re-running
  each file;
- re-check only the failing tests at the base, in one process;
- report an import-time failure once.


