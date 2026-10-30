# verify-eval results (2026-10-21)

**What this measures:** whether `repo-ai verify` selects the test files that
catch real regressions, and at what share of the test-suite time.

**How:**
- Offline and model-free. Ground truth comes from running every test file
  individually in a network-less podman container.
- Protocol: `PROTOCOL.md`, frozen before any held-out measurement.
- Raw data: `results/archives/raw-2026-10-21.tar.xz` (see `ARTIFACTS.md`;
  committed uncompressed as `results/raw/` at `f34818d`).
- Tables come straight from `tables.py`; no hand-copied numbers.

**What it does not measure:** whether coding agents ship fewer regressions.
That needs a separate, pre-registered model experiment.

## The three frozen results

Each result is reported as first measured, on the commit named:

| Set | Engine | Projects | Detected regressions | `verify` with runtime evidence | `verify` static only | 0.7.7 `impact` | grep |
|---|---|---|---|---|---|---|---|
| dev (built on) | `d9695d3` | 7 (5 Py, 2 JS) | 129 of 201 changes | 100% no-miss, **56%** of suite time | 100%, 86% | 42.6%, 49% | 18.6%, 24% |
| **held-out** | `d9695d3` (frozen) | 8 (5 Py, 3 JS) | 150 of 240 | **99.3% (149/150), 44%**. One miss at *high* confidence | 99.3%, 88% (1 miss at *medium*) | 78.7%, 68% | 37.3%, 23% |
| **held-out-2 (fresh)** | `280c03a` (frozen, after fixing the held-out miss) | 7 (4 Py, 3 JS) | 100 of 193 | **100% (100/100), 35%**. No miss at any confidence | **93.0%, 64%. 6 misses at *medium*** | 87.0%, 53% | 38.0%, 13% |

How to read the columns:
- **No-miss:** the share of detected regressions whose failing test files
  were all selected.
- **Suite time:** the share of the sum of per-file test times, measured at
  baseline.
- **"Policy" variant:** run the full suite whenever `verify` reports *low*
  confidence. Its numbers are in the per-set tables below.

## Against the targets set in advance

| Target (PROTOCOL.md) | Result |
|---|---|
| ≥ 95% no-miss on a fresh held-out set | **Met with runtime evidence**: 99.3% on held-out, 100% on held-out-2. **Not met by static-only selection on held-out-2**: 93.0%; 94.0% with the low-confidence fallback |
| Material reduction in test time at comparable detection | **Met with runtime evidence**: 44% and 35% of suite time, saving 56–65%. Static-only saves 11–36% |
| No unsupported confident verdicts | **Not met:** 1 miss at *high* (held-out, runtime) and 6 at *medium* (held-out-2, static). The causes were fixed afterwards; see below |
| No fabricated or invalid commands | **Met:** every per-file command that exited cleanly ran at least one test. One pony file defines no tests and ran 0 tests by design |
| No regression against simpler alternatives | **Met:** `verify` caught more regressions than grep and 0.7.7 `impact` on every set. grep is cheaper only because it misses most regressions |

## Every miss, and what was done about it

**held-out, elementpath `rev-01`:** missed with runtime evidence at *high*
confidence, and statically at *medium*.
- **What happened:** `tests/test_package.py` reads the package's `.py` files
  as text to check version strings. The recorder treated every opened `.py`
  file as an import and ignored it, and static analysis cannot see a glob
  read.
- **Fix** (`edef2ae`, after the result):
  - a `.py` file opened by anything other than the import system is recorded
    as a data read;
  - tests that glob `*.py` are linked to every Python source change.

**held-out-2, svgwrite `mut-09/11/12/16`:** missed statically at *medium*.
- **What happened:** `svgwrite/base.py` begins with a UTF-8 byte-order mark.
  The indexer parsed decoded text, where a BOM is a syntax error, so the file
  had no import edges. Every test reaching the package through it was cut
  off.
- **Fix** (after the result): strip a leading BOM before parsing, in the
  indexer and in `verify`.

**held-out-2, pony `mut-09/11`:** missed statically at *medium*.
- **What happened:** `orm/core.py` loads providers with
  `import_module("pony.orm.dbproviders." + name)`. The changed module is
  imported only by those providers. The prefix loader was detected, but it
  lowered confidence only for the providers themselves.
- **Fix** (after the result):
  - a prefix loader gets an inferred edge to every module under its prefix;
  - a change reached only through such an edge, without runtime evidence, is
    reported at *low* confidence.

**held-out-2, pony `mut-01`:** missed statically at *low*. This is correctly
flagged, and the full-suite policy catches it.

Results with these fixes applied (`post-hoc` tables below) were measured on
the same changes the fixes came from. **They are not validation.** The only
fresh validation of the current static mode would be a third held-out set,
which was not run.

## Post-hoc re-scoring with all fixes (not validation)

These use the same changes, the same ground truth and the current engine.
They show that the fixes remove the misses they targeted without new ones on
the other sets. Because the held-out fixes were made after seeing the
held-out misses, they are **not** evidence of generalisation.

| Set | `verify` with runtime evidence | `verify` static only | static + full suite when low |
|---|---|---|---|
| dev | 100% no-miss, 56% of suite time | 100%, 86% | 100%, 93% |
| held-out | 100% (150/150), 45% | 100%, 89% | 100%, 91% |
| held-out-2 | 100% (100/100), 35% | 99.0%, 70% (the 1 miss is at *low*) | 100%, 82% |

Tables: `results/*-tables-posthoc2.md`.

## Per-set tables (first measurement)

See `results/heldout-tables-frozen-d9695d3.md`,
`results/heldout2-tables-frozen-280c03a.md` and `results/dev-tables.md`.
Re-scorings after each fix are in `results/*-posthoc*.md`, clearly
labelled.

## Zero-configuration test commands (`results/zero-config-commands.json`)

With no `--test-command`, the command repo-ai infers was directly usable for
per-file selection on **7 of 15** dev and held-out projects.

The rest need `--test-command`:
- src layouts without `PYTHONPATH=src`;
- non-default unittest patterns (`-p *_test.py`, `-p *.py`);
- a too-narrow start directory (genshi);
- suites wrapped in `c8`, `pnpm` or a multi-step `make` target, which stay
  opaque. With an opaque command `verify` says the full suite is required; it
  never guesses.

## Cost of using it

| | Measured |
|---|---|
| `repo-ai init` (index) | 0.4–2.7 s on these projects; 3.9 s / 140 MB on sqlglot (247 Python files, ~147k lines) |
| `verify` plan | median 0.27–0.45 s per change in the harness (dev, held-out, held-out-2); 0.4–1.0 s and 27–72 MB on the larger held-out repositories; 1.6 s / 74 MB on sqlglot |
| `--record` (one-time, sandboxed) | 1–12 s for most projects; 49 s for peewee (whose full suite takes about 60 s); one run of each test file |
| Index on disk | 0.7–4 MB |

## Limitations

**Corpus:**
- Python projects use `unittest` (stdlib-only, so offline grading was
  possible). pytest projects are supported by the runner but not measured
  here.
- JavaScript projects use `node:test` with zero dependencies. Projects using
  Jest, Vitest or a build step are not measured.
- Test files that fail at baseline in the sandbox (missing optional
  dependencies, network tests) are excluded from scoring, as the protocol
  specifies.

**Changes:**
- Seeded single-site operator mutations, plus reverted upstream source
  changes. Real regressions can be subtler.
- Undetected changes (no test fails) are counted, but they cannot test
  selection.

**Granularity and measurement:**
- Test-file level. A selected file is run whole.
- "Suite time" is the sum of per-file process times, so it includes
  interpreter start-up for each file.

**Recorder:**
- It cannot see code run in child processes. Such tests are marked
  incomplete and fall back to static links.

**What was not compared:**
- pytest-testmon, Jest and Vitest were not run. They would need third-party
  dependencies installed into the sandbox, and none applies to these
  zero-dependency suites without a configuration change. Their mechanisms are
  compared in `docs/RESEARCH-2026-10.md`.

---

## Addendum (2026-10-22): zero-configuration commands, measured reproducibly

The 7-of-15 figure above was a judgement over plan output. It is kept as
recorded. It has been replaced by a reproducible measurement, `zeroconfig.py`:
- The runner `verify` establishes with no `--test-command` is compared with
  the corpus reference command, first by **universe** (test files missing or
  extra).
- Then by **execution**: every reference test file, plus any extra file, runs
  with the *inferred* per-file command in the same network-less container as
  the baseline. Outcomes must agree.

**Classes:**
- `correct`: nothing missing, outcomes agree, extras pass.
- `partial`: something is missing, outcomes disagree, or an extra file fails.
- `runner-not-installed`: the inferred runner, pytest, is absent from the
  stdlib-only image.
- `opaque`: no per-file runner.

| Engine | correct | partial | runner not installed | opaque |
|---|---|---|---|---|
| `c04e03b` (before the zero-config rules) | **11 / 22** (7 of the 15 dev and held-out projects, which reproduces the earlier judgement) | 6 | 1 | 4 |
| `21ddf5d` (after), **post-hoc** | **20 / 22** | 1 (pony: widened discovery adds `pony/utils/tests`, one of whose files fails in the stdlib image) | 1 (oauthlib) | 0 |

**Caveats:**
- The rules were written while looking at these 22 projects. The "after" row
  is **not** validation.
- The fresh measurement is held-out-3 (PROTOCOL.md, Amendment 2).
- Files: `results/zero-config-before-c04e03b.json` and
  `results/zero-config-after-21ddf5d-posthoc.json`.

---

## Held-out-3 (PROTOCOL.md Amendment 2): the first result, as recorded

**Engine:** frozen at `75679e9` (`FREEZE.md`). It includes the disposable
workspace, zero-config, batching and the held-out-2 static fixes.

**Corpus:** 7 public projects, none seen before. Selected mechanically, with
the replacements recorded before measurement:
- **Python, pytest, with test dependencies baked into per-project images:**
  itsdangerous, parse, toolz, boltons.
- **JavaScript, `node --test`:** ZENCHE, jmgraph, FEAScript-core (with npm
  dependencies).
- **Vitest control:** found.

**Ground truth:** as before. 193 changes, of which 92 are detected.

**Committed** in `fb899ef` (selection), `e202d7d` (zero-config) and `d9a33f0`
(actual time), before any investigation.

### Selection

| Method | No-miss | Mean recall | Test files selected | Suite time (per-file) | Misses by confidence |
|---|---|---|---|---|---|
| `verify` with runtime evidence | **98.9%** (91/92) | 98.9% | 30% | **37%** | **high: 1 of 92** |
| `verify` runtime + full suite when low | 98.9% | 98.9% | 30% | 37% | high: 1 |
| `verify` static only | **100%** (92/92) | 100% | 55% | **66%** | medium: 0 of 92 |
| `verify` static + full suite when low | 100% | 100% | 60% | 70% | medium: 0 |
| repo-ai 0.7.7 `impact` | 92.4% | 94.7% | 37% | 40% | 7 missed |
| grep | 76.1% | 84.9% | 22% | 25% | 22 missed |

Per project: `results/heldout3-tables-frozen-75679e9.md`.

**Against the targets:**

| Target | Result |
|---|---|
| ≥ 95% no-miss | **Met:** runtime 98.9%, static 100% |
| A material time reduction | **Met:** runtime saves 63% of per-file suite time, static 34% |
| No unsupported confident verdicts | **Not met:** 1 miss at *high* (below) |
| No invalid commands | **Met** |
| Better than the simpler alternatives | **Met** on every project with detected changes |

**Static-only selection** (the BOM and computed-loader fixes from held-out-2,
never validated before) has **no miss** on this fresh set.

**The one miss: ZENCHE `rev-00`, runtime, *high* confidence.**
- **What happened:**
  - The changed file `ai-server/admin/app.js` is a browser script. The server
    reads it and serves it as text, and `test/admin-api.test.mjs` fetches it
    and checks its content.
  - No test *executes* it, so V8 coverage holds nothing for it.
  - The Node recorder, unlike the Python one, does not record files read as
    data.
  - Fresh-but-empty evidence was treated as authoritative and overrode the
    static link that would have caught it.
- **Fix** (`a8653bc`, **post-hoc**): a changed file that no recorded test
  executed, loaded or opened is "unobserved". Its static links apply, and
  confidence is at most *medium*.

**The Vitest control:**
- `verify` reported the suite opaque, with low confidence, and said the full
  suite is required.
- It offered no sandboxed run of a command it cannot parse.
- File: `results/heldout3/control-found-plan.json`.

### Zero-configuration commands (first fresh measurement of these rules)

**6 of 7 correct** (`results/zero-config-heldout3-frozen-75679e9.json`).
- itsdangerous: the inferred command was correct with `PYTHONPATH=src`
  established from the src layout.
- **toolz: partial.**
  - The inferred bare `pytest` is exactly the command in the project's own
    `tox.ini`. But it also collects `bench/test_*.py`, and one of those files
    fails in the evaluation image.
  - The reference command (`pytest toolz/tests`) is narrower.

### Actual verification time and working-tree safety (`actual.py`)

**Setup:**
- 10 detected and up to 5 undetected changes per project.
- `repo-ai verify --run --sandbox podman --image <project image>`, as a
  developer would run it.
- Compared with the project's full suite in the same container, as one
  process.

| Project | Full suite (wall) | `--record` | `verify --run` median | Ratio | Runs | Errors | Tree unchanged (verify's check / independent digest) |
|---|---|---|---|---|---|---|---|
| itsdangerous | 0.99 s | 2.74 s | 3.87 s | 3.9× | 15 | 0 | 15/15 · 15/15 |
| parse | 1.10 s | 2.57 s | 4.46 s | 4.1× | 14 | 0 | 14/14 · 14/14 |
| toolz | 0.88 s | 3.40 s | 2.94 s | 3.4× | 15 | 0 | 15/15 · 15/15 |
| boltons | 2.46 s | 5.77 s | 2.29 s | 0.93× | 15 | 0 | 15/15 · 15/15 |
| ZENCHE | 7.78 s | 14.78 s | 2.66 s | **0.34×** | 15 | 0 | 15/15 · 15/15 |
| jmgraph | 1.42 s | 3.14 s | 2.89 s | 2.0× | 8 | 0 | 8/8 · 8/8 |
| FEAScript-core | 2.51 s | 3.24 s | 1.18 s | **0.47×** | 6 | 0 | 6/6 · 6/6 |

- **Ratio:** the median `verify --run` time divided by the full-suite time.
  Below 1 means faster than the full suite.
- **Working-tree safety:** 88 of 88 runs reported the tree unchanged, and an
  independent byte-for-byte digest taken immediately before and after each
  run agreed. Each whole clone was identical after the run, except
  `.git/index`, which the harness's own `git checkout` between changes
  rewrites.
- **Waiting time:** on suites that take about a second, `verify --run` waits
  **longer** than the full suite. It is faster only where the suite takes
  several seconds: ZENCHE, FEAScript-core, and boltons about even.
- **One slow run:** ZENCHE `mut-03` made a test hang until the 600 s per-file
  timeout. The full suite would hang as well.

### Post-hoc re-scoring of all sets (engine `a8653bc`+, NOT validation)

The `a8653bc` fix was made after seeing the held-out-3 miss. These numbers come
from the same changes, so they are **not** validation:

| Set | Runtime: no-miss / suite time | Static: no-miss / suite time | Misses |
|---|---|---|---|
| dev | 100% / 57% | 100% / 86% | none |
| held-out | 100% / 45% | 100% / 89% | none |
| held-out-2 | 100% / 35% | 99% / 70% | the one at *low* (pony `mut-01`; the full-suite policy catches it) |
| held-out-3 | 100% / **45%** (was 37%) | 100% / 66% | none |

Keeping static links for unobserved files costs held-out-3 8 points of suite
time. Validating this fix needs a fourth fresh set.

**Raw outputs:** `results/archives/raw-2026-10-22.tar.xz`, verified, 82 files.
The frozen held-out-3 selections are `selections.json`; the post-hoc ones for
every set are `selections-posthoc3.json`.

## Held-out-4 (PROTOCOL.md Amendments 3 and 3b): the first result, as recorded

**Engine:** frozen at `ccb0622` (`FREEZE.md`): the adaptive engine of this
branch, plus held-out-3's post-hoc selection fix (`a8653bc`).

**Corpus:** 8 public projects, none seen before. Selected mechanically, with
every decision and replacement recorded before measurement:
- **Python, pytest, with test dependencies baked into per-project images:**
  tomlkit, cattrs, loguru.
- **Python, standard library only:** jmespath.py (pytest), colorama
  (`unittest`; it replaced chardet, whose checkout fails 43 of 52 files at
  baseline).
- **JavaScript, `node --test`:** cloi, autoplan.
- **TypeScript through Node's type stripping:** skyhook.

**Ground truth:** as before. 221 changes, of which 120 are detected. autoplan
contributes none: no generated change breaks a test that passes there at
baseline.

**Committed** in `207eb2d` (selection) and `03e9376` (zero-config) before any
investigation.

### Selection

| Method | No-miss | Mean recall | Test files selected | Suite time (per-file) | Misses by confidence |
|---|---|---|---|---|---|
| `verify` with runtime evidence | **100%** (120/120) | 100% | 38% | **44%** | high: 0 of 119; medium: 0 of 1 |
| `verify` runtime + full suite when low | 100% | 100% | 39% | 45% | none |
| `verify` static only | **99.2%** (119/120) | 99.2% | 65% | **72%** | medium: 1 of 119 |
| `verify` static + full suite when low | 99.2% | 99.2% | 71% | 78% | medium: 1 |
| repo-ai 0.7.7 `impact` | 55.0% | 55.9% | 38% | 40% | 54 missed |
| grep | 35.0% | 44.1% | 11% | 15% | 78 missed |

Per project: `results/heldout4-tables-frozen-ccb0622.md`.

**Against the targets:**

| Target | Result |
|---|---|
| ≥ 95% no-miss | **Met:** runtime 100%, static 99.2% |
| A material time reduction | **Met:** runtime saves 56% of per-file suite time, static 28% |
| No unsupported confident verdicts | **Met:** no miss at *high*. The one static miss (cattrs `mut-18`, `tests/test_dicts.py`) is at *medium* |
| No invalid commands | **Met** |
| Better than the simpler alternatives | **Met** on every project with detected changes |

**Held-out-3's post-hoc fix** (an unobserved file keeps its static links) is
validated here for the first time: no runtime miss on this fresh set.

### Zero-configuration commands (`results/zeroconfig-heldout4-ccb0622.json`)

**6 of 8 correct:** tomlkit, cattrs, loguru, and the three Node projects
(`npm run test` resolved to `node --test`, `--experimental-strip-types`
included). The other two:
- **jmespath.py, partial:**
  - The project declares its command only in `tox.ini`
    (`commands = python -m pytest tests`), which was not read.
  - `unittest` discovery was inferred instead. It disagrees with the reference
    on one file.
- **colorama, opaque:**
  - `make test` runs `$(python) -m unittest discover -p *_test.py`, where
    `python=$(virtualenv)/bin/python` is defined through another variable.
  - The resolver expanded one level only.

Both have post-hoc fixes in this PR (labelled; measured on the projects that
motivated them, not validated on a fresh set).

### Execution: waiting time and correctness of `verify --run` (`wallclock.py`; `WALLCLOCK.md`)

Both engines are measured under identical conditions: the frozen engine
(`ccb0622`) and the previous one (`cf56523`), in each project's network-less
image. Each project gets the first 8 failing and the first 8 passing changes,
then three repeats and three `--rerun`s. Committed in `826143d`.

| | New engine | Previous engine |
|---|---|---|
| Median wall time over the native full suite (geometric mean, 8 projects) | **0.62×** | 1.06× |
| Median wall time, new over previous (geometric mean) | **0.59×** | |
| Failing changes reported as `regression` | **55 of 55** | 55 of 55 |
| False alarms; new failures reported as pre-existing | 0; 0 | 0; 0 |
| Working tree unchanged, every run | yes | yes |
| Repeat runs (reused evidence and warm-cache `--rerun`) agree with the first run | yes, every project | (no reuse) |

**Targets (PROTOCOL.md Amendment 3), stated plainly** (added after the
results, from the same data):
- "No execution-time regression against the native full suite": **missed on
  3 of 8 projects** (tomlkit 3.48×, jmespath.py 2.11×, colorama 3.25×).
- No high-confidence miss: met.
- ≥ 95% no-miss: met.
- Correct results on passing and failing changes: **partly missed**. Three
  of tomlkit's passing changes reported `full-suite-failed` (below).

**How to read the 0.62×:**
- **The baseline:** the native suite runs as *one process*. Verify runs up
  to 4 processes at a time, so the ratio mixes test selection with
  parallelism. cattrs, for example, ran all 57 of its files and still took
  26 s against 71 s.
- **The aggregate:** the geometric mean hides the tails. From the archived
  per-run records:

| Aggregate over projects of (median wall time / native suite) | New | Previous |
|---|---|---|
| Geometric mean, all changes (the headline) | 0.62× | 1.06× |
| Arithmetic mean, all changes | 1.27× | 2.06× |
| Largest project ratio | 3.48× (tomlkit) | 6.52× |
| Geometric mean, failing changes only (7 projects; autoplan has none) | 0.91× | 1.95× |
| Geometric mean, passing changes only | 0.55× | 0.72× |

- **The slowest single run:** 112.6 s (cattrs, against its 70.8 s suite);
  for the previous engine, 723.9 s (loguru).
- **Source:** computed from the per-project summaries in
  `results/wallclock-summary.json` (sets `heldout4-new-ccb0622` and
  `heldout4-old-cf56523`), prompted by the pre-release audit
  (`docs/VERIFY-AUDIT-2026-10.md`).

**Per project** (median; the native suite runs in the same image, one process):
- **Large suites are where the time goes, and where the new engine saves it:**
  - loguru: 10.5 s against a 72.8 s suite (previously 30.6 s);
  - cattrs: 27.0 s against 70.8 s (previously 46.2 s);
  - autoplan: 2.1 s against 14.2 s;
  - skyhook: 1.4 s against 4.8 s;
  - cloi: 0.8 s against 2.0 s.
- **Sub-second suites still wait longer than running everything bare:**
  - tomlkit: 1.7 s against 0.5 s;
  - jmespath.py: 1.5 s against 0.7 s;
  - colorama: 0.8 s against 0.2 s.

  This is the fixed cost of planning, the disposable copy and the integrity
  check. The previous engine took 3.3 s, 2.0 s and 1.1 s on these.
- **`--record` costs more:** it now also times the native full suite once.
  cattrs: 116 s against 46 s.

**One defect found (tomlkit), fixed post-hoc in `8498671`:**
- tomlkit's pre-existing collection error (a missing git submodule) stops its
  own pytest session at collection, every time.
- When the cost model chose the full suite for speed, that result could not be
  attributed to files. The fallback selection then ran and passed.
- Three of tomlkit's eight passing changes were reported `full-suite-failed`.
  Each of those runs paid for the full suite and the selection. No regression
  was missed, but those passing changes did not read as passing.
- The fix: a full suite that was not required and cannot be attributed no
  longer decides the verdict, and is not chosen for speed again in that
  environment. It is measured post-hoc below, not validated on a fresh set.

### Post-hoc measurements after the first held-out-4 results (NOT validation)

**tomlkit, engine `c33e4a4`**, same protocol
(`results/wallclock-summary.json`, set `heldout4-posthoc-tomlkit-c33e4a4`):
- **Run shape:** the full suite was tried once, then not chosen for speed
  again.
- **Passing changes:** all 7 report `failing (all failures pre-existing at
  the base)`, which is tomlkit's submodule test. Before the fix, 3 reported
  `full-suite-failed`.
- **Time:** median 1.58 s (was 1.74 s); files run twice, 17 (was 61).
- **Detection:** 8 of 8 failing changes are still detected.

**Zero-config, engine `c33e4a4`**, on all five sets
(`results/zeroconfig-posthoc-c33e4a4.json`):
- 34 of 37 correct, held-out-4 8 of 8 among them.
- The other three are unchanged from earlier records: pony partial, oauthlib
  runner-not-installed, toolz partial.
- The first post-hoc rule (`3b57a88`) took any `tox.ini` pytest command. It
  turned genshi and supervisor into runner-not-installed: their tests are
  `unittest` tests. `c33e4a4` takes a pytest command only when a test file
  imports pytest.

These fixes were written after the held-out-4 result. They are measured on
the projects that prompted them and on the earlier sets, and have not been
validated on a fresh set.


## P3: per-edit planning cost (engine `debe17e`; planning only, no test executed)

Script: `p3_plan.py`. Data: `results/p3-plan-debe17e.json`.

**Setup:**
- 9 development-corpus projects, 4 three-file edit sessions each. parse is
  listed with 0 sessions: no change set spans three files.
- The machine was otherwise idle.
- In-process `build_plan` calls, 5 repeats each; the first whole-change call
  (cold) is excluded from the warm statistics.

| project | whole change, median / p95 | per path, median / p95 | union = whole | "full suite required" agrees | per-path JSON / text (median) |
|---|---|---|---|---|---|
| cachetools | 0.31 / 0.40 s | 0.31 / 0.33 s | 4/4 | 4/4 | 4.6 / 2.1 kB |
| markdown | 0.34 / 0.39 s | 0.34 / 0.37 s | 4/4 | 4/4 | 12.6 / 4.0 kB |
| boltons | 0.35 / 0.36 s | 0.34 / 0.42 s | 4/4 | 4/4 | 2.4 / 1.1 kB |
| humanize | 0.31 / 0.36 s | 0.31 / 0.36 s | 4/4 | 4/4 | 3.3 / 1.6 kB |
| python-pathspec | 0.27 / 0.28 s | 0.27 / 0.33 s | 4/4 | 4/4 | 6.9 / 2.4 kB |
| culori | 0.31 / 0.33 s | 0.31 / 0.38 s | 4/4 | 4/4 | 16.0 / 3.3 kB |
| simple-statistics | 0.31 / 0.39 s | 0.31 / 0.34 s | 4/4 | 4/4 | 23.3 / 4.5 kB |
| busboy | 0.29 / 0.30 s | 0.29 / 0.30 s | 4/4 | 4/4 | 6.5 / 2.8 kB |
| cel-js | 0.30 / 0.32 s | 0.30 / 0.37 s | 4/4 | 4/4 | 12.2 / 3.4 kB |

**Reading:**
- Scoping a plan to one file does not make it cheaper: the cost is fixed per
  call.
- The 300 ms p95 budget of the proposal is missed on every project.
- Scoped plans are consistent with the whole-change plan (36 of 36
  sessions).
- The decision is in `docs/VERIFY-AGENT-CONTRACT.md` (P3).


## Held-out-5 (PROTOCOL.md Amendments 4 and 4a; engine `2f6ea31`, the release candidate)

First results, committed unchanged. Every number below is generated from
the files named here, not copied by hand:
- **The set:** 7 projects, frozen and selected before measurement
  (`FREEZE.md`).
  - Python with dependencies: marshmallow, attrs, pluggy.
  - Python, standard library only: sqlparse, h11.
  - JavaScript (`node --test`): koa, MusicBot.
  - The TypeScript quota was **not met** (0 of 22 metadata-eligible
    candidates passed checks 3, 4 and 7). TypeScript type stripping is
    therefore not re-validated here.
- **Every project ran in its network-less podman image.** The digests are in
  `results/heldout5/images.json`.
- **Raw evidence:** `results/raw-2026-10-23-heldout5.tar.xz` (60 files,
  verified with `archive.py verify`). It holds the per-project outputs, the
  per-run wall-clock records of both engines, the probe records and the run
  logs.

### Selection (no test executed by the method; ground truth from each change's affected files run alone in the container)

Source: `results/heldout5-score-frozen-2f6ea31.json`.

### heldout5: all projects

| Method | Detected changes | No-miss | Mean recall | Test files selected | Suite time | Misses by reported confidence |
|---|---|---|---|---|---|---|
| run every test file | 135 of 202 | **100.0%** | 100.0% | 100% | **100%** | - |
| grep (imports or mentions) | 135 of 202 | **24.4%** | 28.8% | 11% | **11%** | -: 102 missed of 135 |
| repo-ai 0.7.7 `impact` | 135 of 202 | **74.8%** | 84.0% | 61% | **62%** | -: 34 missed of 135 |
| `verify`, static evidence | 135 of 202 | **99.3%** | 100.0% | 74% | **76%** | medium: 1 missed of 135 |
| `verify` static + full suite when confidence is low | 135 of 202 | **99.3%** | 100.0% | 79% | **81%** | medium: 1 missed of 135 |
| `verify` with runtime evidence | 135 of 202 | **100.0%** | 100.0% | 48% | **52%** | high: 0 missed of 135 |
| `verify` runtime + full suite when confidence is low | 135 of 202 | **100.0%** | 100.0% | 48% | **52%** | high: 0 missed of 135 |

### heldout5: per project

| Project | Lang | Detected | verify-runtime no-miss / time | verify-static no-miss / time | policy-static time | 0.7.7 impact no-miss | grep no-miss |
|---|---|---|---|---|---|---|---|
| marshmallow | python | 24 of 30 | 100% / 51% | 100% / 91% | 91% | 67% | 25% |
| attrs | python | 17 of 30 | 100% / 61% | 94% / 67% | 77% | 35% | 59% |
| pluggy | python | 22 of 30 | 100% / 80% | 100% / 80% | 100% | 77% | 14% |
| sqlparse | python | 20 of 30 | 100% / 65% | 100% / 100% | 100% | 95% | 15% |
| h11 | python | 19 of 30 | 100% / 42% | 100% / 54% | 54% | 100% | 0% |
| koa | node | 26 of 30 | 100% / 35% | 100% / 99% | 99% | 65% | 15% |
| MusicBot | node | 7 of 22 | 100% / 15% | 100% / 32% | 36% | 100% | 100% |

### heldout5: every `verify` miss

| Project | Change | Kind | Method | Confidence | Missed test files |
|---|---|---|---|---|---|
| attrs | mut-02 | mutation | verify-static | medium | tests/test_pyright.py |

### Execution: wall clock and correctness

**What ran:** `wallclock.py` with Amendment 4a on, the frozen build
(`2f6ea31`) against the held-out-4 engine (`ccb0622`), with engine order
alternated per project.

**Sources:**
- data: `results/wallclock-summary.json` (sets `heldout5-new-2f6ea31` and
  `heldout5-old-ccb0622`);
- tables: `results/heldout5-wallclock-tables-2f6ea31.md`;
- regenerate with `wallclock_tables.py ... --extended`.

| project | sandbox | native full suite | new: median (failing / passing) | old: median (failing / passing) | new / native | old / native | processes per run, new / old (median) | files run twice, new / old |
|---|---|---|---|---|---|---|---|---|
| marshmallow | podman | 1.27s | 1.60s (1.38s / 2.01s) | 1.54s (1.39s / 1.65s) | 1.26x | 1.21x | 4.00 / 6.00 | 1 / 2 |
| attrs | podman | 5.92s | 4.89s (5.88s / 2.40s) | 4.55s (4.95s / 2.33s) | 0.83x | 0.77x | 5.00 / 8.00 | 42 / 35 |
| pluggy | podman | 0.56s | 1.31s (1.67s / 0.55s) | 1.25s (1.36s / 0.56s) | 2.34x | 2.23x | 2.50 / 1.50 | 27 / 0 |
| sqlparse | podman | 1.16s | 1.41s (1.35s / 1.41s) | 1.34s (1.35s / 1.34s) | 1.22x | 1.16x | 4.00 / 4.00 | 2 / 3 |
| h11 | podman | 0.44s | 1.11s (1.15s / 1.08s) | 1.08s (1.15s / 1.05s) | 2.52x | 2.45x | 1.50 / 1.50 | 4 / 0 |
| koa | podman | 4.56s | 2.71s (2.71s / 3.31s) | 2.60s (2.60s / 3.28s) | 0.59x | 0.57x | 1.00 / 3.50 | 12 / 0 |
| MusicBot | podman | 6.17s | 1.08s (1.04s / 2.41s) | 0.93s (0.91s / 2.29s) | 0.18x | 0.15x | 1.00 / 2.00 | 0 / 0 |

| project | failing changes | detected, new / old | missed, new / old (confidence) | false alarms, new / old | regressions outside the ground truth, new / old | new reported as pre-existing, new / old | repeat runs agree (new) | tree unchanged, every run (new / old) |
|---|---|---|---|---|---|---|---|---|
| marshmallow | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| attrs | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| pluggy | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| sqlparse | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| h11 | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| koa | 8 | 8 / 8 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | yes | yes / yes |
| MusicBot | 7 | 7 / 7 | 0 / 0 | 0 / 0 | 1 / 1 | 0 / 0 | yes | yes / yes |

Geometric mean of median wall time over the native full suite, 7 projects: new 0.96x, old 0.91x; new over old 1.06x.
Projects where the new engine's median is at or below the native suite: 3 of 7 (old engine: 3).

| project | `--record`, new (includes one native full-suite run) | `--record`, old |
|---|---|---|
| marshmallow | 4.24s | 4.17s |
| attrs | 13.70s | 13.86s |
| pluggy | 2.54s | 2.48s |
| sqlparse | 3.29s | 3.27s |
| h11 | 2.16s | 2.24s |
| koa | 11.26s | 11.14s |
| MusicBot | 9.81s | 9.76s |

| project | native exit codes | max run / native | passing changes not reported as passing (new) | `--workers 1` median (new) / detected | cold run agrees, verdict and files (new) |
|---|---|---|---|---|---|
| marshmallow | [0, 0, 0] | 1.92x | 6 | 3.10s / 8 | True |
| attrs | [1, 1, 1] | 2.15x | 4 | 7.50s / 8 | True |
| pluggy | [0, 0, 0] | 3.62x | 0 | 1.52s / 8 | True |
| sqlparse | [0, 0, 0] | 1.85x | 0 | 1.99s / 8 | True |
| h11 | [0, 0, 0] | 252.52x | 0 | 1.16s / 8 | True |
| koa | [1, 1, 1] | 19.98x | 4 | 2.71s / 8 | True |
| MusicBot | [1, 1, 1] | 1.13x | 2 | 1.44s / 7 | True |

- all changes, new (7 projects): geometric mean 0.96x, arithmetic mean 1.28x, max 2.52x
- all changes, old (7 projects): geometric mean 0.91x, arithmetic mean 1.22x, max 2.45x
- failing changes, new (7 projects): geometric mean 1.00x, arithmetic mean 1.37x, max 2.98x
- failing changes, old (7 projects): geometric mean 0.92x, arithmetic mean 1.26x, max 2.61x
- passing changes, new (7 projects): geometric mean 0.91x, arithmetic mean 1.11x, max 2.45x
- passing changes, old (7 projects): geometric mean 0.87x, arithmetic mean 1.05x, max 2.39x
- `--workers 1`, new (7 projects): geometric mean 1.27x, arithmetic mean 1.66x, max 2.71x

**Reading, per project.** The geometric mean hides the slow projects.
- **Correctness: every measured target was met by both engines.**
  - 55 of 55 failing changes detected, with no misses.
  - No false alarms.
  - No new failure reported as pre-existing.
  - The tree was unchanged around every run.
  - The first run, the reused run, the warm `--rerun` and (new engine) the
    cold run agreed, on the verdict and on the files reported.
- **The one regression outside the ground truth** is MusicBot `mut-08`, and
  both engines report it:
  - `test/binaries.test.js` already fails at the base, so the file-level
    ground truth cannot judge it.
  - verify compares test by test, and reports the `unzip` tests that the
    change (`src/core/unzip.js`) newly breaks inside that file.
  - It is not counted as a false alarm, and it is not claimed as a detection.
- **Speed: the release candidate is slower than the held-out-4 engine.**
  - The geometric means are 0.96× native against 0.91×, so the candidate is
    1.06× the previous engine.
  - Per project, it is 1.03–1.16× slower everywhere. The likely sources
    are the audit's fixes: the reporters' `collected` lists, the guardian,
    the base runs for all-skipped files and the bounded output drain. They
    were **not measured separately**, so this is a hypothesis.
- **Faster than the native suite on 3 of 7 projects** (attrs 0.83×, koa
  0.59×, MusicBot 0.18×).
- **Slower than native on 4 of 7, each a suite of about a second or less:**
  - marshmallow 1.26×;
  - sqlparse 1.22×;
  - pluggy 2.34× (0.56 s suite);
  - h11 2.52× (0.44 s suite).

  The target "no execution-time regression against the native full suite" is
  **missed on these 4 projects**.
- **Tails: two hang mutations cost their time limit with both engines.**
  - h11 `mut-04` took 111 s against a 0.44 s suite.
  - koa `mut-07` took 91 s against a 4.6 s suite.
  - These are the largest single costs measured. A per-test watchdog (Part 7,
    option 1) would bound them.
- **`--workers 1`** (selection without parallelism) has a geometric mean of
  1.27× native. On suites this small, parallel batches are part of the
  speed.
- **The native suite exits non-zero on attrs, koa and MusicBot** because of
  their files that already fail at the base. Their native time includes
  those files.
- **Passing changes not reported as passing:**

  | project | new engine | previous engine |
  |---|---|---|
  | marshmallow | 6 of 6 | identical |
  | attrs | 4 of 8 | identical |
  | koa | 4 of 4 | identical |
  | MusicBot | 2 of 8 | identical |

  - Every one is `failing (all failures pre-existing at the base)`, from a
    file that already fails at the base, except MusicBot `mut-08` above.
  - **Marshmallow's 6 come from a runner-inference gap**, found here. Its
    three `tests/mypy_test_cases/test_*.py` files are excluded by the
    project's own pytest configuration (`norecursedirs`). verify's runner
    still counts them as test files, and they fail when run.
  - This is reported as found. It is not fixed in the frozen build.

### Cancellation probe (`cancelprobe.py`; protocol delay 1.5 s)

Source: `results/cancelprobe-heldout5-2f6ea31.json`.

**First attempt.** The probe script crashed after the first SIGTERM of each
project (`ValueError` unpacking `ps` rows), so nothing was recorded.
- A check right after it found no leftover processes, containers or
  workspaces.
- The attempt is kept under `_superseded` in the results file.
- The fix is to the probe script only (`cancelprobe.py`), not the engine.

**The probe as specified, 21 runs:**
- No surviving process, no marker-carrying process, no container and no
  leftover workspace in any of the 21 runs. The tree was unchanged.
- marshmallow, attrs and koa: 9 of 9 runs were cancelled (exit 130).
- pluggy, sqlparse, h11 and MusicBot: 12 of 12 runs **had already finished**
  when the signal arrived (exit 1: the regression verdict). Their whole run is
  shorter than the protocol's 1.5 s delay, so **cancellation was not
  exercised** on these four projects by the protocol probe.

**POST-HOC, not validation** (`results/cancelprobe-heldout5-posthoc-delay0.2-2f6ea31.json`):
- What: the same probe with a 0.2 s delay, on those four projects.
- Result: 12 of 12 runs were still running when signalled, exited 130, and
  left nothing behind.

### Zero-config (`results/zeroconfig-heldout5-2f6ea31.json`)

- 6 of 7 inferred test commands are correct.
- attrs is partial: the inferred command runs one extra file, which fails.

### Targets (Amendment 4)

| Target | Result |
|---|---|
| no high-confidence miss | **met** (0; runtime and execution) |
| ≥ 95% runtime no-miss | **met** (selection 135/135; execution 55/55) |
| no false alarm | **met** (0; one regression the ground truth cannot judge, explained above) |
| every cancellation probe clean | **met for cleanup** (21 of 21 runs left nothing). **Not exercised** on 4 of 7 projects by the protocol probe; post-hoc 12 of 12 clean |
| tree unchanged around every run | **met** |
| no execution-time regression against the native suite | **missed on 4 of 7** (the sub-second suites) |
| faster than the previous adaptive engine | **not met**: 1.06× slower (geometric mean); slower on every project |
