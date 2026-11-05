---
title: Verify a change
description: How repo-ai verify plans, runs and records the tests your change can break, in a sandboxed disposable copy compared against the base commit.
---

`repo-ai verify` answers three questions about the working tree, against `HEAD` or another base revision:

1. **What did this change touch?** Changed files and, for Python, the exact functions, methods, class bodies and
   module code whose lines changed. Comment- and formatting-only edits are recognised as non-behavioural.
2. **Which tests can show whether it broke something, and how sure is that?** Every selected test file comes with the
   evidence linking it to the change, and the plan states a confidence and every reason that lowered it.
3. **What happened when they ran?** With `--run`, in a sandbox, in a disposable copy of the working tree.

Planning is read-only. Repository code runs only with `--run` or `--record`, and only inside a sandbox.

```sh
repo-ai verify            # read-only plan: changed units, selected tests with evidence, confidence, the command
repo-ai verify --run      # run them sandboxed; new failures vs. failures already at the base
repo-ai evidence          # does the last result still cover the working tree?
repo-ai verify --record   # optional, once: record which code each test executes (sharper selection)
```

## The plan

Tests are linked by a **union** of evidence, never an intersection:

| Evidence | Meaning |
|---|---|
| `changed-test` | the test file itself changed |
| `runtime` | recorded by `--record`: this test file executed a changed code unit, or opened a changed data file |
| `static` | it reaches a changed file through imports (the chain is shown) |
| `literal-load` | code loads the changed module by a literal name |
| `string-reference` | it, or a module it imports, names the changed module in a string |

**Confidence** is `HIGH` when every changed unit has fresh runtime evidence, `MEDIUM` when some of it rests on static
evidence only, and `LOW` when the plan may miss tests and the full suite is required (a changed test, build or
dependency configuration; computed-name loading; a changed file nothing explains; a runner that cannot run single
files). repo-ai never reports a change as "safe". The full-suite command is always shown.

## Running: `--run` and `--full`

`verify --run` runs the selection, or the project's whole suite, whichever measured times say finishes first.
`--full` runs the full suite (it includes the selection). Each run prints a headline first: `REGRESSION`,
`NO NEW FAILURES`, `PASSED`, `UNCONFIRMED FAILURES` (order-dependent or flaky), and so on.

**New or pre-existing.** Every failure is compared with the base revision, in the shape it happened in. A failure is
classified as a new failure, a new failure in a file that already had others, already failing at the base (flagged
if the message changed), or a new test. A failure that appears only next to other files is reported as
order-dependent or flaky, not as a regression.

**No tests is not a pass.** A file in which no test ran is reported as `no-tests`; a run in which nothing executed is
never reported as passing. A time-out is a failure, never a pass.

### The disposable copy and the sandbox

- The copy holds every tracked and untracked, non-ignored file as it is in the working tree. It leaves out `.git`,
  `.repo-ai/`, ignored files, and untracked files that look like credentials (listed as withheld).
- Dependency directories such as `node_modules` and the project's virtualenv are readable, never writable.
- The sandbox is seatbelt on macOS, bubblewrap on Linux, or podman/Docker. No network, a clean environment, writes
  confined to the copy. There is no unsandboxed fallback.
- The whole source tree is snapshotted before and after every run. Any difference invalidates the evidence and fails
  the command.
- Ctrl-C, SIGTERM and SIGHUP kill every test process and container, delete the copy, and record nothing.

## Flags you will use

| Flag | What it does |
|---|---|
| `--base REV` | compare the working tree with this revision (default `HEAD`) |
| `--run` | run the selected tests in the sandbox (executes repository code) |
| `--full` | with `--run`: run the full suite |
| `--record` | run every test file once under a tracer, sandboxed, to record which code each executes |
| `--rerun` | with `--run`: run again even when evidence for this exact change and environment exists |
| `--test-command CMD` | the project's test command, when repo-ai cannot establish it |
| `--sandbox NAME` | where `--run`/`--record` execute: `auto` (default), `seatbelt`, `bwrap`, `podman` or `docker` |
| `--image REF` | with podman/docker: a **local** image that has the project's dependencies (never pulled) |
| `--deadline SECONDS` | with `--run`: a total wall-clock budget; tests it cuts or leaves unstarted make the run "not verified" |
| `--timeout SECONDS` | per test process (default: 5× its measured time + 10 s, at least 30 s, at most 600 s) |
| `--paths A,B` | plan only for these changed files (read-only preview; never with `--run`) |
| `--json` | the same result as data, with a `summary` object for agents |

If `verify` cannot establish the test command it says so and runs nothing. Give it once:

```sh
repo-ai verify --test-command "PYTHONPATH=src python -m pytest tests"
```

or permanently, as `verify_test_command = "..."` in `.repo-ai/config.toml`.

For projects with dependencies, the strongest isolation is a container image you built yourself:

```sh
repo-ai verify --run --sandbox podman --image localhost/myproject-tests:latest
```

On **Windows** there is no host sandbox, so `--run` needs `--sandbox podman` or `--sandbox docker`.

## Evidence

Each `--run` stores its result in `.repo-ai/state/evidence/` (local, git-ignored) with the change fingerprint, the
isolation summary and the integrity result. `repo-ai evidence` says whether it still applies to the current working
tree. Evidence for an identical change, environment, test command and selection, less than a day old, is reused and
marked as reused; `--rerun` runs again.

## `--record`: runtime evidence

Each test file runs once, in its own sandboxed process, under a recorder (`sys.monitoring` on Python 3.12+, V8
coverage on Node). Records hold only file paths and code-unit names, tied to the content hash of the files they
describe. Stale evidence is ignored and reported. Code run in child processes is not visible; such tests fall back to
static links.

## What "verified" means

A passing run is evidence about **the tests that ran**, in that environment. With no linked tests the plan
abstains; if the full suite is not required, no linked test means **NOT VERIFIED**. It is not a proof that the change
is correct. The output says so every time.

## Limitations

- **Runners:** runtime evidence covers `unittest`, `pytest` and `node --test`. Jest, Vitest and Mocha are opaque: the
  full suite is required and `verify` does not split them. One runner per invocation (for a monorepo, pass
  `--test-command "cd packages/x && node --test"`).
- **Qualified scope:** the held-out evaluation covered pytest and `node --test` in containers. unittest and
  TypeScript are tested but not qualified; host sandboxes are covered by the test suite and CI jobs, not by held-out
  data. See [Evaluation](/repo-ai/docs/evaluation/).
- **Speed:** planning, the copy and the integrity check cost about 0.6–1 s per run, so short suites are slower under
  `verify` than run bare. There is no general speed advantage.
- **Dynamic loading** detection is pattern-based. It marks where the static answer may be incomplete; it cannot prove
  absence.
- **Hangs** cost their time limit per hanging file. A progress watchdog ends stalled unittest and pytest runs sooner;
  node runs keep the hard limit.
- **Dependency changes:** the base runs with the dependencies installed now, so when a dependency file changed, a
  failure that also fails at the base is reported "not comparable", never pre-existing.

The full threat model is `docs/VERIFY-THREAT-MODEL.md` in the source tree.
