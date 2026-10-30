# `repo-ai verify`: what your change can break, checked safely

`repo-ai verify` answers three questions about the working tree, against `HEAD`
or any base revision:

1. **What did this change touch?**
   - the changed files;
   - for Python, the exact code units whose lines changed (functions,
     methods, class bodies, module code);
   - comment- and formatting-only edits are recognised as non-behavioural.
2. **Which tests can show whether it broke something, and how sure is that?**
   Every selected test file comes with the evidence that links it to the
   change. The plan states a confidence and every reason that lowered it.
3. **What actually happened when they ran?**
   - With `--run`, the tests run in an OS-enforced sandbox, inside a
     **disposable copy** of the working tree, in whichever shape is expected
     to finish first: the selected files in a few parallel processes, or the
     project's own full suite as one process.
   - Every failing test is compared with the base revision, so new
     regressions are told apart from failures that were already there.
   - The result is stored as evidence tied to the exact change and test
     environment.

Planning is read-only. Repository code runs only with `--run` or `--record`.

## Quickstart

```sh
repo-ai init --agent none     # once: index the repository (no agent needed)
repo-ai verify                # 1-3: changed code, uncertainty, recommended tests and commands (read-only)
repo-ai verify --run          # 4-5: run them sandboxed in a disposable copy; new failures vs. pre-existing
repo-ai evidence              # 6: does the last result still cover the working tree?
repo-ai verify --record       # optional, once: record which code each test executes (sharper, high confidence)
```

What `verify --run` prints, on a real change (cachetools; the full demo is
in [VERIFY-DEMOS.md](VERIFY-DEMOS.md)):

```text
REGRESSION: this change breaks tests that pass at the base
  NEW  7 test files fail with the same error: AssertionError: ValueError not raised
       tests/test_cache.py, tests/test_fifo.py, tests/test_lfu.py, tests/test_lru.py, tests/test_rr.py, tests/test_tlru.py …
       selected because it executed changed __init__ (runtime evidence)
  5 passed
  source tree unchanged
```

If `verify` cannot establish the test command itself, it says so and runs
nothing. Then give it the command once:

```sh
repo-ai verify --test-command "PYTHONPATH=src python -m pytest tests"
# or permanently, in .repo-ai/config.toml:
#   verify_test_command = "PYTHONPATH=src python -m pytest tests"
```

**Dependency-based projects in a container** (strongest isolation): build an
image that has the project's test dependencies, then:

```sh
repo-ai verify --run --sandbox podman --image localhost/myproject-tests:latest
```

The image must already exist locally; repo-ai never pulls it.

## Stable and experimental

| Capability | Status | Basis |
|---|---|---|
| Read-only plan: changed files and code units, linked tests with evidence, confidence and triggers | **stable** | 3 frozen held-out sets; see "Measured" |
| Disposable, isolated execution with before/after integrity checks; cancellation | **stable** | `tests/test_verify_isolation.py` on seatbelt, bwrap and docker in CI; hostile-test suite |
| Base-revision comparison (new versus pre-existing failures, per test) | **stable** | unit and end-to-end tests; demos; both engines on 17 development projects |
| Runtime evidence (`--record`) for Python (`unittest`, `pytest`) and Node (`node --test`) | **stable** for these runners | held-out results |
| Adaptive run shape (full suite or selection, from measured times) | **experimental** | development measurements; held-out-4 (see "Measured") |
| Per-test outcome reports: failure attribution without re-runs, grouped base comparison in the same shape, time-out attribution | **experimental** | equivalence tests against separate runs; development measurements; held-out-4 |
| Base-outcome cache, measured timings, reuse of evidence for an identical state | **experimental** | asymmetric trust rules (threat model T18, T19); repeat runs agree on every measured project |
| Zero-configuration test command (scripts, wrappers, src layouts, discovery) | **experimental** | rules written on known projects; validated on held-out-3 and held-out-4 |
| `--image` for dependency-based projects in containers | **experimental** | held-out-3, held-out-4 |
| `Stop`-hook completion gate (`verify --gate`), blocking or `verify_gate_mode = "report"` | **experimental, opt-in** | effect on agents unmeasured |
| Monorepos with several test runners (workspaces) | **not supported per package** | one runner per invocation: pass `--test-command "cd packages/x && node --test"`; the root's workspace script is opaque and runs as the full suite |
| Jest, Vitest, Mocha and other runners | **not supported** | they are opaque: `verify` requires the full suite and does not split them |

## The default flow, step by step

```text
$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  calc/core.py  [source, modified, units: add]
      evidence: 1 linked test file(s); runtime evidence fresh

selected 1 of 3 test files   (est. 0.1s of 0.4s run file by file, 25%)
  tests/test_add.py  [runtime] executed add (+1 more)

confidence: HIGH: every changed code unit has fresh runtime evidence

test command: python -m unittest discover -s tests -t .   (declared in the project's manifests, CI or docs)

run
  targeted:   python -m unittest tests.test_add
  full suite: python -m unittest discover -s tests -t .   (before merging)
  sandboxed:  repo-ai verify --run   (--full runs the full suite instead)
              tests run in a disposable copy of the working tree, never in it; failures are re-checked against the base

evidence: none yet for this repository
```

**`--run` adds, conclusion first:**
- one headline: `REGRESSION`, `NO NEW FAILURES`, `PASSED`, `UNCONFIRMED
  FAILURES` (order-dependent or flaky), and so on;
- each new failure:
  - its failing tests and the first line of each error;
  - why the test file was selected ("executed changed `__len__` (runtime
    evidence)");
  - one shared error across many files (an import that now fails) is said
    once;
- files already failing at the base, in one line;
- how it ran (the shape, the reason, processes and seconds) and the
  integrity result (`source tree unchanged`).

`--json` returns the same as data, with a `summary` object for agents:
- `verdict`, `new_failures` (file and tests), `pre_existing`, `unconfirmed`;
- `passed`, `no_tests`, `strategy`, `seconds`, `processes`, `reused`;
- `source_tree_unchanged`.

`repo-ai evidence` later tells you whether that result still covers the
working tree, or is stale.

## How tests are linked to a change (a union of evidence, never an intersection)

| Evidence | Meaning |
|---|---|
| `changed-test` | the test file itself changed |
| `runtime` | when recorded: this test file **executed a changed code unit**, or opened a changed data file |
| `static` | it reaches a changed file through imports (the chain is shown). Uses the full transitive closure; a package `__init__.py` reaches every importer of that package |
| `literal-load` | code loads the changed module by a literal name (`importlib.import_module("pkg.mod")`) |
| `string-reference` | it, or a module it imports, names the changed module or its registered entry-point name in a string |

**Confidence:**
- **high:** every changed code unit has fresh runtime evidence. "Fresh" means
  recorded for byte-identical content of that file.
- **medium:** some of the change rests on static evidence only (imports or
  file names), not on runtime evidence.
- **low:** the plan may miss tests, and the full suite is required. Causes:
  - a changed test, build or dependency configuration;
  - a module reachable through **computed-name loading**, with no runtime
    evidence;
  - a changed file nothing explains;
  - a test runner that cannot run single files.

repo-ai never reports a change as safe. A passing run is evidence about the
tests that ran. The full-suite command is always shown.

## Which test command runs

The command is printed before anything runs, with where it came from:
1. `--test-command`, or `verify_test_command` in `.repo-ai/config.toml`: your
   explicit choice, used as given;
2. the project's declared test command, from package.json scripts, a Makefile,
   CI or docs;
3. when the declared command cannot be split per file (`tox`,
   `python runtests.py`) or none exists: a runner inferred from the test files.

**Static rules applied to that command** (each is listed under `test command:`
in the plan; files are read, never executed):
- **Scripts:** `npm`/`pnpm`/`yarn`/`bun run <script>`, `npm test`, and their
  `pre` scripts are resolved. A Makefile recipe counts when its other lines
  only report coverage.
- **`&&` chains:**
  - the step that runs the tests is used when every other step is a lint,
    format or type check, and those steps are named;
  - a build step before the tests keeps the command opaque, because the tests
    may need it.
- **Coverage:** wrappers (`c8`, `nyc`, `coverage run -m`) and node's coverage
  thresholds are not applied to single files.
- **src layouts:** `PYTHONPATH=src` is set when the tests import a package
  that lives only under `src/`.
- **Inferred unittest discovery:** widened until every file that defines
  `TestCase` tests is included. The pattern changes only when the project's
  own naming convention differs from the default.
- **Per-file runs** keep the suite's runner options (`node --import tsx`,
  `pytest -m "not slow"`), minus paths, coverage and cross-file options.

**What is never executed:** anything else. That includes `||`, `;`, pipes,
redirections, unknown tools and build steps; such a command is opaque.
`verify` then requires the full suite and tells you to run it yourself.

## Execution and safety

See [VERIFY-THREAT-MODEL.md](VERIFY-THREAT-MODEL.md) for the full threat
model.

**A disposable copy, never the working tree:**
- **What's in it:** every tracked and untracked, non-ignored file, as it is
  in the working tree (staged and unstaged edits included, deleted files
  absent).
- **What's left out:**
  - `.git`;
  - `.repo-ai/`;
  - ignored files;
  - untracked files that look like credentials (`.env`, `*.pem`, …), which
    are listed as withheld.
- **Dependencies:** dependency directories such as `node_modules` and the
  project's virtualenv are readable, never writable. Editable installs are
  redirected to the copy.
- **Speed:** copies are copy-on-write clones where the filesystem supports
  them (APFS, btrfs, XFS).

**The sandbox:**
- bubblewrap on Linux, seatbelt on macOS (the project's own interpreter),
  or podman/docker (`--image` for dependencies).
- No network and a clean environment. Writes are confined to the copy, and
  the original tree is not even readable.

**Integrity:**
- The whole source tree is snapshotted before and after every run (`.git`
  and ignored files included).
- Any difference marks the evidence invalid and fails the command.
- `GIT_OPTIONAL_LOCKS=0` keeps even git's index refresh out of the tree.

**Cancellation:** Ctrl-C, SIGTERM and SIGHUP kill every test process and
container, delete the copy, and record nothing.

**New or pre-existing:** see "How a run is shaped" below.

**Evidence:**
- Stored in `.repo-ai/state/evidence/`, which is local and git-ignored,
  together with the change fingerprint, the isolation summary and the
  integrity result.
- Credential-looking assignments are masked in output excerpts.

There is no unsandboxed fallback, and no run in the working tree.

## How a run is shaped (adaptive execution)

`verify --run` measures, then chooses. Every shape runs in the same sandbox,
in disposable copies, with the same integrity checks.

**The shape:**
- **The full suite as one process** when it is not expected to be slower
  than the selection. It runs every selected test and more, so it is the
  better choice at the same wait. It is also the only run when the change
  requires the full suite: the selection is not run first, so nothing runs
  twice.
- **The selected files**, otherwise: balanced into at most `--workers`
  processes (unittest and pytest), or one `node --test` invocation (Node runs
  each file in its own child process).
- **The estimate:**
  - each file's measured time alone (from `--record`, then from later runs);
  - the fixed cost of one sandboxed process, measured from earlier runs;
  - a calibration ratio learned from earlier passing selections;
  - the full suite's measured time (`--record` times it once).
- **Without measurements**, the selection runs, and the reason says so.
- The chosen shape and the reason are printed and stored (`strategy`).

**Failures are attributed, not re-run.** Each process reports every test's
outcome as it happens, through a small reporter copied into the disposable
copy (`rai_result.py` for unittest and pytest, `rai_reporter.mjs` for
`node --test`). One process can then stand for many files:
- **A failing batch:** its report says which files failed, and which tests.
  The 0.8 engine re-ran every file of a failing batch, then re-checked each
  failing file at the base, each in its own process.
- **A time-out:** the report names the test that was running. Files that
  had finished keep their results, and only the files not yet started run
  again.
- **When the report is not trusted** (see the threat model, T16), the files
  run one by one as before.
- **One error in many files:** when an import fails in 40 files, the report
  says so once.

**New or pre-existing.** Each failure is compared with the base revision (a
`git archive` copy: no hooks or filters run), **in the shape it happened
in**:
- **Full-suite failures:** compared with the full suite at the base, one
  process. Its per-file outcomes are cached for that base.
- **Other failures:** each failing test alone at the base, all of them in a
  few processes, by test id where the runner can address single tests, else
  by file.
- **Failures from a multi-file process** that pass at the base are also
  re-run alone at the change. A failure that happens only next to other
  files is reported as **order-dependent or flaky**, not as a regression.
- **Classifications:** **new failure**, **new failures in a file that
  already had others**, **already failing at the base** (flagged when the
  failure message changed), or **new test**.

**Remembered, and forgotten:** all local, in `.repo-ai/state/`.

| What | Used when | Forgotten when |
|---|---|---|
| Base outcomes (`verify-baseline.json`) | same base *tree* and same test environment. A pass after one observation; a failure only after two that agree; a test seen both ways is never trusted again | the base, the test command, the interpreter or Node, the installed distributions, `node_modules`, the container image or repo-ai's version change |
| A clean `--record`'s per-file passes and its full-suite outcomes | seed the base outcomes above for the commit they ran on | as above |
| Measured times (`verify-timings.json`) | the shape decision | the environment changes. A wrong time only costs speed |
| The evidence of a run | an identical change, environment, test command and selection, less than a day old: it is **reused** and marked so (`--rerun` runs it again) | anything above changes, or a day passes |

**Other rules:**
- **No tests is not a pass.** A file in which no test ran (a helper module
  matched by the runner's pattern) is reported as `no-tests`. A run in which
  nothing executed is never reported as passing.
- **Aggregators are skipped.** A test file that only re-runs other selected
  files' tests (a package `__init__` that imports every test module) is
  skipped in a selection run, as its own record shows. The full suite still
  runs it.
- **Time limits follow measured times:** 5× plus 10 s, at least 30 s, at most
  600 s, unless `--timeout` is given. A time-out is a failure, never a pass.

## Runtime evidence (`--record`)

Each test file runs once, in its own sandboxed process, under a recorder:
- **Python:** `rai_trace.py`, standard library only. It uses `sys.monitoring`
  on Python 3.12+ and records which code units started and which data files
  were opened.
- **Node:** V8's built-in coverage, `NODE_V8_COVERAGE`.

**What the records hold:**
- Only file paths and code-unit names: never values, output or environment.
- Every record is tied to the content hash of the files it describes, as the
  tests saw them.
- After an edit, evidence about the edited file is used only for the base
  content it was recorded against.
- Stale evidence is ignored and reported, never treated as "no consumer".

**Not visible:** code run in child processes. Such tests fall back to static
links.

## What it adds, and what it leaves to other tools

| Need | Already done well by | What `verify` adds |
|---|---|---|
| Run the tests | the native runner (`pytest`, `unittest`, `node --test`) | nothing: it runs the project's own runner, in its own shapes, and reads its own results through a reporter |
| Run only what changed | `jest --onlyChanged`, `vitest related` (static, JS); `pytest-testmon` (coverage, Python) | one view across Python and Node; evidence per selected test; a confidence that drops to "run everything" when the evidence cannot vouch for the selection |
| Re-run failures | `pytest --lf` | whether each failure is **new or was already there**, checked at the base revision in the same run shape |
| Search and read code | the agent (grep, LSP, file reads) | which tests **actually executed** the changed code (recorded), not only which import it |
| Run tests safely | containers, if you set them up | a disposable copy, no network, the working tree byte-for-byte unchanged and checked, by default |
| Know whether a result still applies | nothing | evidence tied to the exact change and test environment (`repo-ai evidence`, the gate) |

It interoperates rather than re-implements: the native runners do the
running, and `verify` parses their structured output. Jest, Vitest and Mocha
stay full-suite-only. Reading their JUnit reporters the same way is the next
planned extension.

## For coding agents: the completion gate

Agents rarely choose an optional tool. The repo-ai experiments recorded 0
skill invocations in 212 runs.

Instead of asking the model to remember, register the gate as a `Stop` hook:

```json
{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "repo-ai verify --gate"}]}]}}
```

**What it does:**
- It is silent when there is no behavioural change, or when passing evidence
  exists for exactly this change.
- Otherwise it blocks the stop **once per change**, with one sentence, and
  at most `verify_gate_max_blocks` times per agent session (default 3; `0`
  never blocks). The cap bounds how often it can interrupt, however the
  change churns.
- A rewrite after verification that cannot change behaviour still counts as
  verified. This covers, for example, a formatter run by another `Stop` hook
  or by an editor on save:
  - **Python:** the files' syntax trees match. Comments, whitespace, quote
    style and line wrapping are ignored; docstrings are not.
  - **JavaScript and TypeScript:** the files tokenise identically, ignoring
    comments, spaces within a line and the quote style of plain strings.
    Line breaks still count, because automatic semicolon insertion depends on
    them, so a re-wrap asks again.
  - Template literals, regular expressions, JSX and escapes are not
    tokenised; such files count by their exact bytes.
  - Runs, evidence reuse and caches always use the exact content.
- It honours `stop_hook_active` and fails open.
- It is opt-in (`verify_gate`), and it never changes any agent permission.

**Effect on outcomes:** whether the gate improves agent outcomes is
**unmeasured**. That needs its own pre-registered experiment.

## Measured (offline; `benchmarks/verify-eval/`)

**Coverage:**
- 37 public projects in five sets, each frozen before it was measured.
- Python `unittest` and `pytest` (with dependencies in container images);
  JavaScript and TypeScript with `node --test`.
- Ground truth: every test file run individually in a network-less container.
- Changes: seeded mutations and real reverted upstream changes.

**Selection, first results as recorded** (`RESULTS.md`):

| Set | Engine | Detected regressions | With runtime evidence | Static only | 0.7.7 `impact` | grep |
|---|---|---|---|---|---|---|
| held-out | `d9695d3` | 150 | 99.3% no-miss, 44% of per-file suite time (1 miss at *high*) | 99.3%, 88% | 78.7% | 37.3% |
| held-out-2 | `280c03a` | 100 | 100%, 35% | 93.0%, 64% (6 misses at *medium*) | 87.0% | 38.0% |
| held-out-3 | `75679e9` | 92 | 98.9%, 37% (1 miss at *high*) | 100%, 66% | 92.4% | 76.1% |
| **held-out-4** (the adaptive engine) | `ccb0622` | 120 | **100%, 44%** (no miss) | **99.2%, 72%** (1 miss at *medium*) | 55.0% | 35.0% |
| **held-out-5** (the release candidate) | `2f6ea31` | 135 | **100%, 52%** (no miss) | **99.3%, 76%** (1 miss at *medium*) | 74.8% | 24.4% |

- Every earlier miss was fixed after it was recorded. Held-out-3's fix (an
  unobserved file keeps its static links) is validated by held-out-4.
- **Zero-config command:**
  - correct for 6 of 8 fresh projects (held-out-4) and 6 of 7 (held-out-3);
  - post-hoc fixes cover held-out-4's two misses (`tox.ini`, nested
    Makefile variables);
  - those fixes are not validated on a fresh set.

**Waiting time** (`WALLCLOCK.md`): the whole `verify --run` command against
the project's own full suite in the same sandbox, on failing and passing
changes.

| Set | New engine over native (geometric mean of medians) | Previous engine over native | New over previous | Detected (new / previous) |
|---|---|---|---|---|
| **held-out-4**, 8 fresh projects, containers | **0.62×** | 1.06× | **0.59×** | 55/55 / 55/55 |
| development, 17 projects of the earlier sets | 1.16× | 2.16× | **0.54×** | 123/124 / 124/124 (the one: markdown `mut-04`, a verdict bug this run exposed, fixed in `bcfadc6` before the freeze) |

- **Large suites:**
  - loguru: 10.5 s against a 73 s suite;
  - cattrs: 27 s against 71 s;
  - peewee: 2.7 s against 22.5 s;
  - ZENCHE: 1.3 s against 7.9 s.
- **Sub-second suites still take 0.5–1 s longer than running bare:** that is
  the fixed cost of planning, the copy and the integrity check.
- **Processes per run:** a median of 1–5, against up to 72 for the previous
  engine on a failing change.
- **Repeat runs:** an identical state is answered from its evidence in about
  0.5 s, and warm-cache re-runs agreed with the first run on every project.

A share of per-file test time is not waiting time. Only the wall-clock numbers
are.

**Safety, measured:**
- The source tree was unchanged around every measured run, by verify's own
  check and by an independent byte-level digest of the clone. That covers
  held-out-3's 88 runs and every `wallclock.py` run of both engines.
- Hostile tests, forged reports, cancellation, concurrency and time-outs are
  covered by `tests/test_verify_isolation.py` and
  `tests/test_verify_adaptive.py`, on seatbelt, bwrap and docker in CI.

## Limitations

- **Runners:**
  - Runtime evidence covers Python (`unittest`, `pytest`) and Node
    (`node --test`) only. Other languages get file-level static evidence.
  - Jest, Vitest and Mocha are opaque: the full suite is required, and
    `verify` does not run them.
- **Granularity:**
  - Python evidence is per function: a test that executed a changed
    function is selected even if it never ran the changed line, which is
    conservative.
  - Node evidence comes from V8. Lazily compiled, never-run functions may be
    invisible, and then the enclosing script counts.
- **Dynamic loading:** detection is pattern-based (Python AST, JavaScript
  regex). It marks where the static answer may be incomplete; it cannot
  prove absence.
- **Static density:** static selection over a densely connected package
  selects most of the suite. Runtime evidence is what makes selection small.
- **Speed floor:** planning, the disposable copy and the before/after
  integrity check cost about 0.6–1 s per run. On a suite that takes well
  under a second, `verify --run` therefore still takes longer than running
  it bare. There its value is the classification and the evidence, not time.
- **Order dependence inside a batch:** files run in batches. A failure that
  appears only when a file runs *alone* (it relies on state another file sets
  up) is not seen when the batch passes. The project's own full suite would
  not see it either.
- **Skips:** a file that skips every test, or defines none, does not count as
  verified when its tests ran at the base (`not verified: …`). A test that is
  skipped at the base too (platform-specific) is noted and changes nothing.
- **Dependency changes:** the base runs with the dependencies installed now.
  When a dependency-declaring file changed, a failure that also fails at the
  base is reported "not comparable", never pre-existing.
- **Hangs cost their limit:** a change that makes tests loop forever costs a
  time limit per hanging file (5× the measured time plus 10 s, at least 30 s).
- **Monorepos:** one runner per invocation. A workspace script at the root
  (`pnpm -r test`) is opaque and runs as the full suite; per-package
  selection needs `--test-command "cd packages/x && node --test"`.
- **Environment identity** sees installed distributions and dependency
  directories, not every installed file. A hand-edited file inside
  `site-packages` or `node_modules` does not invalidate cached base outcomes
  or reusable evidence; `--rerun` runs again.
