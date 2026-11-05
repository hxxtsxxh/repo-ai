# ProofLab (`repo-ai prove`): did the change do what it claims? (experimental)

> **⚠️ Experimental, opt-in, not certified, and excluded from repo-ai's stable verification claims.**
> - **Certification:** Session A's independent, sealed certification is blocked.
> - **Qualification:** Session A's release qualification (held-out-7) found ProofLab NOT QUALIFIED, and
>   its sealed certification is blocked. Three false proofs are known and open; every passport names
>   them, and code review lists further untested paths (issue #59):
>   - **`swallowed-assertion`** (#59, 1d): a context manager of the code under test, edited to swallow
>     exceptions, hides the scenario's failing assertion;
>   - **`importorskip-zero-entry-points`** (#59, 1e): `pytest.importorskip` leaves no entry point that
>     ProofLab follows, so a change to the scenario's input reads as supported;
> - **Known open false proof, `always-equal-class`:** a value of a class that *already* compares equal
>   to anything at the base (an `__eq__` that always returns True), returned by the change, passes a
>   comparison with a literal, so ProofLab reports the claim supported although nothing is fixed. It
>   is kept as a strict expected failure:
>   `tests/test_prove_review8_eq_regress.py::test_e3_with_the_subject_declared`.
> - **Where the passport says so:**
>   - in its `experimental` object (`certified: false`, `known_false_proofs`);
>   - in its first limitations, its headline and the Markdown banner;
>   - in the in-toto predicate;
>   - in the evidence record's `not_established`.
>
> A supported verdict is a local experiment record, not a proof. The release candidate's scope is in
> [release/RC1.md](release/RC1.md).

`repo-ai verify` answers **"what can this change break, and did it?"**
ProofLab answers the question a reviewer asks next about a bug fix:

> **Does the original code show the bug, does the change fix it, under the
> same test, and what is still unproven?**

It pins a behavioural claim and an acceptance scenario (a test file, by its
exact bytes). Then it runs those same bytes against the original code and
against the change, in verify's sandbox, under the same conditions. It also
checks the change for regressions, and writes a **verification passport**: a
JSON record plus a Markdown report you can attach to a pull request.

**Status: experimental, opt-in.** Nothing runs unless you call `repo-ai prove
run`. No hook calls it. It is shown on two real upstream fixes with
negative controls (below); it has **not** been evaluated on a held-out set or
with coding agents.

## What it adds to `verify`

| | `verify --run` | `prove run` |
|---|---|---|
| Runs the existing tests the change can break, sandboxed, compared with the base | yes | yes (it calls verify) |
| Shows that the **original code fails** the acceptance test | no | yes: the scenario runs at the base, `--repeat` times |
| Uses **the same test bytes** before and after, even when the test exists only in the change | no | yes: pinned bytes are injected into both copies |
| Stops when the change **edits the acceptance test**, its `conftest.py`, pytest config, helpers or data | no | yes: `scenario-changed` / `conditions-differ` |
| Catches a regression **hidden by editing or skipping the existing test** that showed it, or a helper, fixture, plugin or golden file it reads | no: the edited test passes | yes: the **subject-only check** runs the whole suite on the base plus only the code under test, so none of those edits is present |
| Tells a test that **cannot load** on the old code (new API) from one that shows the bug | no | yes: `load-failure` is not a reproduction |
| A reviewer-facing record of what was claimed, observed before and after, and **not** proven | no | yes |

ProofLab adds no second engine. The copies (`isolate`), the sandboxes
(`execute`), the per-test reports (`results`, untrusted unless they agree with
the process), the source-tree integrity check and the regression check
(`engine.run_plan`) are verify's own.

## First run (installed wheel)

```sh
pip install repo_ai-*.whl            # or: pipx install ./repo_ai-*.whl
cd your-project
repo-ai init --agent none            # once: index (no agent needed)
git add -A && git commit -m "repo-ai init"

# 1. Write (or get from a reviewer) a test that shows the bug, then pin it BEFORE fixing
repo-ai prove pin --claim "mean([]) returns 0 instead of raising ZeroDivisionError" \
                  --scenario tests/test_accept_empty.py --subject src/stats.py
# 2. Read-only: what will run, and whether it can be a comparison at all
repo-ai prove plan
# 3. Fix the code, then run the experiment (executes repository code, sandboxed)
repo-ai prove run
# 4. Later: does the passport still describe the working tree?
repo-ai prove status
# 5. For the pull request (under .repo-ai/ or outside the repository: a report written
#    into the working tree is part of the change, and the passport would be stale)
repo-ai prove report --out .repo-ai/proof.md     # Markdown; --format json | in-toto
gh pr comment --body-file .repo-ai/proof.md      # you post it; repo-ai makes no network call
```

What `prove run` prints for that fix (on a real run, macOS seatbelt, 2.8 s):

```text
CLAIM SUPPORTED for the pinned scenario: the original code fails it, the candidate passes it, and no regression was detected
claim test-accept-empty-a71734: mean([]) returns 0 instead of raising ZeroDivisionError
scenario tests/test_accept_empty.py  sha256 ffe5e2b612615a1f  (worktree)
  before  b37d59134955: 0 of 1 passed, 1 failed  [reproduced]
            test_accept_empty.Accept.test_mean_of_empty_is_zero: ZeroDivisionError: division by zero
  after   working tree: 1 of 1 passed  [passed]
  regressions: none-detected  (verify: selected-passed (full suite not run))
  integrity: source tree unchanged; 2.5s
not established by this passport:
  - A passing scenario shows the claim only for what this scenario checks; ...
  - The scenario was pinned from an agent session: if the agent that wrote the candidate also wrote the scenario, the oracle is not independent. ...
```

Example Markdown passports from the demonstrations are in
[`benchmarks/prooflab/results/2026-10-24/`](../benchmarks/prooflab/results/2026-10-24/).

## Commands

| Command | Runs repository code | Writes | Exit codes |
|---|---|---|---|
| `prove pin [ID] (--claim TEXT \| --claim-stdin) --scenario PATH [--from REV \| --file PATH] [--support PATH]… [--target ID]… [--expect-failure RE] [--supersedes ID]… [--redact-claim] [--replace]` | never | the claim and the pinned bytes, under `.repo-ai/state/prove/` | 0; 1 error; 3 refused (replacing or removing a terminal pin from an agent shell) |
| `prove pin ID --remove` | never | removes the claim and its passports | 0; 1; 3 as above |
| `prove plan [ID] [--base REV] [--json]` | never | nothing | 0 ready; 2 not ready (nothing would run); 1 error |
| `prove run [ID] [--base REV] [--repeat N] [--timeout S] [--no-regressions] [--keep-going] [--sandbox …] [--image …]` | yes, sandboxed, in disposable copies. **Needs the user's authorization**, like `verify --run` | a passport; verify's evidence for the regression check | 0 supported; 1 anything else, or an error; 130 cancelled (nothing recorded) |
| `prove status [ID] [--json]` | never (it asks the test interpreter for verify's environment key with `-I -S`; an interpreter inside the repository is never executed, #40) | nothing | 0 fresh and supported; 1 no passport; 2 stale; 3 fresh but not supported. With several claims and no `ID`: lists them (0) |
| `prove report [ID] [--format md\|json\|in-toto] [--out FILE]` | never | `--out` only | 0 fresh; 2 stale (the report says so); 1 no passport |
| `prove report [ID] --publish-pr N [--public-ok]` | never | a comment on pull request N, through your own `gh` | 0 posted. Refused without posting: a passport that is not fresh, a public repository without `--public-ok`, `gh` missing |

`ID` defaults to the only pinned claim. `--test-command` works as for
verify. It is part of the pin, and a command given to `pin` is reused by the
later commands.

**Test ids** (`--target`, `--supersedes`) are the ids `prove run` prints:
- unittest: `module.Class.test_name`, for example
  `tests.WrongInputTests.test_string_not_indexable`;
- pytest: `path::test_name[param]`;
- node: the names joined with ` > `, for example
  `ipaddr > matches IPv4 CIDR correctly`.

A target the scenario never reports is named, with the closest id it did
report.

**The base is the original code**, `HEAD` by default:
- If you already committed the fix, `plan` says so and suggests
  `--base <commit>~1`.
- A branch name means its tip, not the merge-base, as for verify: pass the
  merge-base commit (`git merge-base main HEAD`) when the branch has moved.

## How one experiment works

1. **Preflight, read-only.** These problems stop the experiment before
   anything runs, and the passport records why:
   - **scenario-changed**: the working tree holds other bytes at the scenario's
     path, or at a pinned support file's path;
   - **conditions-differ**: the test command differs from the pinned one, or
     an *oracle input* differs between the base and the change. Oracle inputs
     are:
     - every `conftest.py` from the scenario's directory up to the root;
     - the pytest sections of `pyproject.toml`, `setup.cfg` and `tox.ini`, and
       `pytest.ini`;
     - for node, `package.json` `type`/`imports`;
     - when the scenario is in a test directory, every non-test file below
       that directory: helpers, data, `__init__.py`;
     - the **test code the scenario imports**, followed through test code
       only: a helper that is itself a test file (`tests/test_common.py`),
       anything under a test directory, or a file next to the scenario when
       its directory is not a Python package (a `checks/` folder);
     - **data files next to the scenario** (expected outputs, golden
       files), in such a dedicated directory;
     - the modules a `conftest.py` in that chain declares in `pytest_plugins`,
       and the test code it imports;
     - a module of constants, or a JSON file, that the scenario or its test
       helpers import directly; a data file whose name they spell out.

     The passport also names every changed file the scenario reaches by
     imports, and every changed data file, for a reviewer to check.

     A dependency bump in `pyproject.toml` is not an oracle input. A file you
     need to change on purpose can be pinned with `--support`; both runs then
     use its pinned bytes;
   - **conditions-differ**, too, when the change adds or edits a file that
     could stand in for the test machinery itself: a module named `pytest`,
     `unittest`, `pluggy`, `sitecustomize` … anywhere in the tree, or a `.pth`
     file;
   - **environment-unavailable**: no sandbox, or a runner other than unittest,
     pytest or `node --test`;
   - **incomplete**: the working tree has no change against the base (the fix
     is already committed; `plan` suggests `--base <commit>~1`), or more than
     40 existing test files would need their base versions re-run.

   Preflight also reads the scenario's syntax tree, with the test code it
   imports (and that the `conftest.py` files above it import) and those
   `conftest.py` files (`prove/dataflow.py`). It asks whether the scenario
   **checks the change's behaviour, or only something the change set up for
   it**. Examples of the latter:
   - an input helper changed from `[]` to `[0]` and passed to an unchanged
     `mean` (Session A's G4);
   - a registry, an environment variable or a file that a second call reads.

   Seven review rounds found a new way to hide such a dependency each time,
   so this is a **narrow allow-list**. The experiment still runs, but the
   claim is never `supported` (it is `incomplete`, and `abstain[]` says why)
   unless all of these hold:
   - **One entry point.** Everything the scenario, its fixtures and hooks
     call in the repository is one function or class, or methods of objects
     it returns. `configure()` then `mean([])`, or `mean(empty())`, is two.
   - **Literal inputs.** Nothing from the repository (a value, a function, an
     attribute) is passed to the repository's code, or to code that may call
     it (`map`, `functools.partial`).
   - **Independent expectations.** A value from the repository is compared
     only with literals, computations on literals outside the repository
     (`pytest.approx(0)`), enum members or classes. A module constant of the
     repository is not independent: the code could set it.
   - **A form ProofLab reads.** The scenario must not use:
     - dynamic names or imports (`getattr`, `setattr`, `importlib`, `exec`);
     - star imports from the repository;
     - decorators other than pytest's and unittest's, or decorators with
       non-literal arguments;
     - fixtures that are neither pytest's own (`tmp_path`, `capsys` …) nor
       defined in the scenario, the `conftest.py` files above it or the test
       code they import; `monkeypatch` and `request` are excluded too;
     - `pytest_generate_tests`;
     - module-level code beyond definitions and assignments.
   - **No import-time edits, no new comparison rules.** The change does not
     edit:
     - statements that run when a subject module is imported, other than
       definitions, assignments to names and guarded imports;
     - a class's `__eq__`, `__bool__`, `__len__` or similar methods;
     - and no definition it edits builds classes or attributes at run time
       (`type(name, bases, dict)`, `locals()`, `setattr`, `exec` …).
   - **A declared subject.** The code under test was declared when the claim
     was pinned (`prove pin --subject`). An inferred subject is what the
     change edits, so the change would choose its own subject (the eighth
     review): such a claim is `incomplete`.
   - Entry points are told apart by their full name: `api.configure` and
     `api.mean`, or `Stats.configure` and `Stats()`, are two. Fixtures come
     from every definition pytest could use, including `usefixtures`, the
     plugins pytest loads (`pytest_plugins`, `-p`) and imported xunit hooks
     (`setup_module`).

   **Node scenarios are not parsed, so a node claim is never supported**:
   the observations are recorded, and the verdict is `incomplete`.

   The cost is false "incomplete" verdicts. A genuine fix is refused when it
   is:
   - observed through a second function (`render(parse(x))`);
   - compared with an object the code builds (`== Token("a")`) or with a
     module constant;
   - set up by a fixture that calls the repository.

   Write the scenario as calls of the changed function or class, with literal
   inputs and literal expectations.
   - **environment-unavailable**, too, when a `.gitattributes` file marks
     files `export-ignore` or `export-subst`: the base copies (`git archive`)
     would leave them out or rewrite them.
2. **Copies.**
   - The base is taken with `git archive`, as verify does.
   - **The candidate side of the scenario is the base plus only the change's
     code under test** (its *subject*), never the whole working tree. No other
     edit of the change can reach the scenario's run, whether a fixture
     module, a plugin, a `conftest.py`, a helper, an expected value or a data
     file.
     - The subject is what the claim declares with `prove pin --subject GLOB`.
     - Otherwise it is the changed files the scenario reaches through
       imports, test code, conftest files and modules of constants excepted.
     - A change with no subject stops before anything runs.
     - When a fix also needs a file outside the subject, the scenario fails at
       the candidate, and the reason names that file and says to declare it.
       This fails closed: a missed file means a false "not established",
       never a false proof.
     - `supported_by_controlled_comparison` needs a **declared** subject.
   - The pinned scenario and support bytes are written into both sides.
   - A repository with git submodules is refused: `git archive` leaves out
     their content.
   - The same tree, base plus subject without the scenario, is the copy for
     the **subject-only check** (step 5).
   - **The whole working tree, as the change ships it**, with the same
     pinned scenario, support and canary, is a fourth side (Session A's S1,
     S2d, S5). A file the subject leaves out, such as a package's
     `__init__.py` or data the fixed code reads, can restore the bug in what
     ships while the base plus the subject passes.
3. **Runs, in parallel, each in a fresh clone:**
   - the scenario at the base and at the change, `--repeat` times each
     (default 2);
   - on a **control**, `--repeat` times as well: a second, independent copy of
     the base, which must fail the same way. Session A's contract (1.1) calls
     it the negative control, and counts it as a side.

     Each side's repeats run one after another, each in a fresh clone; the
     sides run in parallel;
   - an **assertion canary** in the scenario's own process: five tests that
     must fail, under a name drawn afresh for every experiment.
     - unittest and pytest: a separate file next to the scenario.
     - node: appended to the scenario's copy, at both sides, in its ES-module
       or CommonJS form.

     Code under test that disables assertions makes one pass, and the run is
     then not trusted. **Expected failures** (`xfail`, `@expectedFailure`)
     verify nothing and count like skips;

   Every process writes verify's per-test report. A report that is not
   trusted makes the run **incomplete**, never passing. Untrusted means the
   process timed out, ended early, disagreed with its exit code, or failed
   outside the tests it was given.
4. **Judgement**:
   - **Base:**
     - `reproduced`: at least one test fails, every pinned `--target` fails,
       the outcome is identical on every repeat, and the failure is
       behavioural;
     - `load-failure`: every failure is an import, syntax or module-not-found
       error, an unexpected keyword or positional argument, or a missing
       method on a non-builtin object. That shows the interface is new, not
       that the old behaviour was wrong, unless `--expect-failure` pins that
       error;
     - `not-reproduced`;
     - `incomplete`.
   - **Change:**
     - `passed`: every test of the scenario passes on every repeat, the base's
       failing targets ran and passed, and no test that ran at the base is
       skipped, **both** on the base plus the subject and on the whole
       working tree, with the same outcome for every test;
     - `failed` when either fails (the reason says which), otherwise
       `incomplete`.
5. **Regression checks**, both of them, once the scenario stage succeeds:
   - **The subject-only check:**
     - The project's full suite runs on the base, and on the base plus only
       the code under test. A test that ran at the base and is skipped or
       gone there counts as a regression. Any other code the change edits must
       be part of the subject, or the check is incomplete. So must every other edit except:
       - the change's tests and test support (a collected test file, a `conftest.py`, anything in a
         `tests/`, `test/` or `__tests__/` directory);
       - documentation at the root or in `docs/`;
       - the root configuration and lockfiles (`pyproject.toml`, `setup.cfg`, `package.json` …).

       That includes data the code reads, anywhere and whatever its type (`settings.ini`,
       `mypkg/banner.md`), and a package named like test support (`mypkg/snapshots/`,
       `mypkg/testing.py`). The edits excepted here still join the second regression tree (step 5),
       because code can read them too (a `setup.cfg` section, a `docs/` text, a module under
       `mypkg/tests/`). Every other edit of the change is absent: an
       edited test, a skip marker, a helper, a fixture or plugin (however it
       is loaded), a golden or snapshot file, a value imported dynamically.
     - So no such edit can hide a regression the code under test causes.
     - A test that passes or is absent at the base and fails here, or that no
       longer runs, is a regression, unless the claim declares it
       `--supersedes` (its old expectation replaced on purpose).
     - An untrusted run of either suite makes the check incomplete.
     - **When the change edits files outside the subject**, the same suite
       also runs on the base plus **every** such edit. A regression there is
       then detected even when the change also edits the test that would show
       it (Session A's S17; the sixth review's data and `testing.py` cases). A
       new failure in either tree is `regressions-detected`. With nothing
       detected the check stays incomplete, as above.
   - `verify --run` on the same change and environment: verify's own
     selection, shapes and base comparison.
   - `nothing-selected` there counts as **no evidence** (`incomplete`), and so
     does verify's abstention (below).
   - It runs only after the scenario stage succeeds. Once that stage already
     rules the claim out, it is skipped, to save time and to avoid running a
     hanging scenario twice; `--keep-going` runs it anyway.
   - It obeys `--timeout`.
6. **Integrity:** the source tree is snapshotted before and checked after, as
   for verify, and the change's fingerprint is checked again at the end. Any
   difference makes the result `incomplete`.

## The passport (`repo-ai.proof-passport/1`)

Fields are only ever added within this schema id. A consumer ignores fields
it does not know, and trusts only `verdict.state == "supported"` together with
`repo-ai prove status` reporting `fresh`.

| Field | What it holds |
|---|---|
| `claim` | `id`, `text` (or `null` with `--redact-claim`), `sha256`, `settings` (a digest of the whole pin), `targets`, `expect_failure`, `supersedes`, `pinned.agent_shell` and the variables that showed it, `replaced` (how often it was re-pinned) and the earlier scenario hashes |
| `scenario`, `support` | path, `sha256`, size, provenance (`worktree`, `git` with commit and blob, or `file` with its name only), whether the candidate and base trees hold the same bytes, static notes (skip markers, no assertion) |
| `baseline`, `candidate` | the base revision and commit; the change's fingerprint and changed files |
| `conditions` | the runner command and its identity hash; the oracle inputs checked and which differ |
| `environment` | backend, OS, the interpreter or node version (asked with `-I -S`, so no repository code runs on the host), image digest for containers, repo-ai version |
| `observations.baseline`, `observations.candidate` | the state, the reason, and every repeat: exit code, time-out, whether its report was trusted (and why not), each test id's outcome, failure messages (cleaned, at most 300 characters, credentials masked). `observations.candidate.shipped` is the same for the whole working tree |
| `abstain` | why the scenario may not check the change's behaviour (preflight's dataflow rules); any entry keeps the verdict from `supported` |
| `edited_tests` | the subject-only check: per test file, its new failures, superseded ones, state; the number of tests compared; `code_edits_check`, the same suite on the base plus every code edit |
| `regressions` | verify's verdict, new failures, pre-existing failures, selection size, confidence, full-suite status, evidence path |
| `integrity` | verify's source-tree check |
| `verdict` | `state`, `supported`, `level`, `headline`, `reasons[]` |
| `limitations`, `untested` | what the passport does not establish; what never ran |
| `reproduce` | the `repo-ai` command and the steps by hand |
| `evidence[]` | one `repo-ai.proof-evidence/1` record (Session A's [evidence contract](PROOF-EVIDENCE-CONTRACT.md), v1.0), embedded whole, with its own `claim.level` |
| `digest` | sha256 of the passport itself: it detects a damaged or hand-edited record, not a forgery by someone who can write the state directory |

**Verdicts:**

| State | Meaning |
|---|---|
| `supported` | the base shows the targeted failure, the change passes the same scenario under the same conditions, no regression is detected, and the tree was untouched |
| `candidate-failed` | the change fails the scenario |
| `baseline-not-reproduced` | the original code passes the scenario, fails it differently than pinned, or cannot load it |
| `regressions-detected` | verify found new failures, or the subject-only check did (an existing test fails on the base plus only the code under test) |
| `incomplete` | missing, untrusted, inconsistent or interrupted evidence, a skipped regression check, or a source tree that changed |
| `environment-unavailable` | no sandbox or no supported runner: nothing ran |
| `scenario-changed` | the change edits the pinned scenario or a support file: nothing ran |
| `conditions-differ` | the scenario would not run under the same conditions: nothing ran |

Only `supported` is a supported claim. Its headline says "for the pinned
scenario", and the report lists what it does not establish.

**Evidence levels** (the embedded record, by the contract): `verdict.level`
repeats the record's `claim.level`, and the verdict never says more than it:

| ProofLab sees | Record level | Headline |
|---|---|---|
| supported, the scenario independent of the change (below), 2+ conclusive agreeing runs on each side, **the control included**, no changed data file | `supported_by_controlled_comparison` | "supported by a controlled comparison" |
| supported, but the scenario is part of the change (pinned from the working tree or from the fix commit) | `behavior_observed` | "supported … not a controlled comparison" |
| supported, but verify's fingerprint has a known gap (the contract's §6, D5–D9: a submodule, a skip-worktree or assume-unchanged entry, a rename, a CRLF file in the change, a virtualenv in a host sandbox) | `test_passed` | the verdict becomes `incomplete`. **Since #41 and #43 the engine covers these, so the cap no longer applies** (`contract.ENGINE_COVERS_D5_D9`) |
| anything else | `not_established` | not established |

**A claim that is not established carries no level.** When the verdict is not
`supported` (a regression, an incomplete check, a shipped tree that fails),
the record's `claim.level` and `verdict.level` are `not_established`, and
`not_established[]` says why. What the scenario comparison alone reached is
kept, for display only, as `claim.scenario_level` (Session A's S1, S2d, S17).

**Freshness:** `prove status` is fresh only while all of these are still
those of the passport:
- the claim's pin;
- the base revision's commit;
- the change's exact fingerprint;
- verify's environment key: interpreter, installed packages, `node_modules`,
  image, repo-ai version.

When the key cannot be computed (no sandbox here), the state is `unknown`.
**Every export shows one view** (`passport.export_view`): Markdown, `--format
json`, `--format in-toto` and `prove status --json`. Each carries
`freshness {state, reasons}`. A passport that is not fresh (`stale` or
`unknown`) is exported with `verdict.state` `stale`, `supported` false and
`level` `not_established`; the recorded verdict is kept under
`verdict.recorded`. Its embedded record is shown at `not_established`, with
`claim.recorded_level` (Session A's E1). The Markdown says "STALE", and `prove
report` exits 2. A fresh export carries the passport's verdict exactly.

**In-toto:** `--format in-toto` prints an **unsigned** in-toto Statement v1
whose subjects are the candidate (`repoAiFingerprint`) and the scenario
(`sha256`), with the base as `gitCommit` in the predicate. Signing (DSSE,
cosign) is left to the user; repo-ai makes no network call and claims no SLSA
level.

## Independence of the oracle

A test written by the same agent that wrote the fix can be wrong in the same
way. ProofLab cannot know who wrote a test, so it records what it can:

- **`--from REV`** pins the scenario as the blob at a reviewer's commit.
  Anyone can check that blob with `git cat-file`, and the passport names it.
- **`--file PATH`** pins a file kept outside the repository: it is injected,
  never part of the change.
- **Pinned from an agent shell** (Claude Code, a hook or CI: the same
  variables as capability approval): recorded as `scenario.pinned_from:
  "agent"`. Such a pin is **never** independent, whatever its kind: an agent
  can commit its own test before fixing, or write the outside file itself.
- **Independent** (contract §3) means all of these:
  - pinned from a terminal;
  - a blob identical at the base, or a file kept outside the repository;
  - every `--support` file identical at the base.
- **A claim pinned from a terminal** cannot be replaced from an agent shell
  (exit 3). Replacing any pin needs `--replace`, keeps the old hashes in the
  pin's history, and makes earlier passports stale.
- **What is checked:** pinned bytes are checked against their sha256 before
  every run, and a pin edited outside `prove pin` is refused.

All of this is defence in depth, not a boundary. An agent with shell access
can write repo-ai's state directory; the passport digest and the scenario
hash are what a reviewer compares.

## Safety

- **Only in the sandbox:** every test process runs through verify's
  `Executor`: bwrap, seatbelt, or podman/docker. There is **no unsandboxed
  fallback**, and nothing runs in the working tree.
- **What runs on the host:** git plumbing, and the interpreter's version
  check with `-I -S`.
- **Pinned files:**
  - paths are repository-relative, with no `..`, and not under `.git` or
    `.repo-ai`;
  - injected files are never written through a link;
  - a scenario is at most 1 MiB.
- **Output:**
  - failure messages and test ids come from the code under test, so they are
    masked for credentials, stripped of control and escape sequences, and
    bounded;
  - in Markdown they appear only inside code spans, and the claim is
    escaped, so a report cannot ping people or inject HTML;
  - no source code is printed, and JSON reports leave out local paths.
- **Cancellation:** Ctrl-C, SIGTERM or SIGHUP stops every sandboxed process,
  deletes the copies, and records nothing.

## Demonstrations (2026-10-24)

`benchmarks/prooflab/demo.py` reproduces everything below from public
commits. It clones them, or uses `--mirror` for local copies, and drives the
`repo-ai` CLI. Every control's expected verdict is fixed in the script before
anything runs.

| Case | Licence | Original | Fix | Runner | Upstream test |
|---|---|---|---|---|---|
| [python-json-pointer](https://github.com/stefankoegl/python-json-pointer): a token applied to a string indexed into it | BSD-3-Clause | `f15abac` | `16c4c8e` (PR #76) | `python -m unittest tests` | `tests.WrongInputTests.test_string_not_indexable` |
| [ipaddr.js](https://github.com/whitequark/ipaddr.js): `match()`/`subnetMatch()` accepted invalid CIDR prefix lengths | MIT | `40708ee` | `74ee4c5` | `node --test` | 3 new tests in `test/ipaddr.test.js` |

**Controls, per case:**
- **The fix:** the upstream source fix, with the upstream test pinned `--from`
  the fix commit, with `--target`.
- **Stale:** an edit after the supported run.
- **Partial:** a fix that still fails the target.
- **Breakage:** a fix that breaks related behaviour.
- **Hang:** the change hangs on the claimed path (`--timeout 20`).
- **Weaken:** the change weakens the pinned test.
- **Baseline:** the target is an existing test that already passes.
- **Separate acceptance file** (the upstream test verbatim, kept outside the
  repository and pinned with `--file`):
  - the fix;
  - the breakage;
  - **hidden:** the breakage plus `skip` markers on exactly the existing
    tests it breaks.

Run 4, the final code (macOS, seatbelt, Python 3.12.14, node v24.19.0). Runs 2 and 3 gave the same
verdicts; [the results README](../benchmarks/prooflab/results/2026-10-24/README.md) covers all four.

| Control | Expected | json-pointer | ipaddr.js | Evidence level |
|---|---|---|---|---|
| fix | supported | supported (4.6 s) | supported (4.6 s) | `behavior_observed` (the scenario is the fix's own test) |
| stale | stale | stale | stale | |
| partial | candidate-failed | candidate-failed | candidate-failed | |
| breakage | regressions-detected | **candidate-failed** | **candidate-failed** | |
| hang | incomplete | incomplete (23.5 s) | incomplete (22.6 s) | |
| weaken | scenario-changed | scenario-changed (nothing ran) | scenario-changed (nothing ran) | |
| baseline | baseline-not-reproduced | baseline-not-reproduced | baseline-not-reproduced | |
| separate-fix | supported | supported (4.1 s) | supported (3.1 s) | `supported_by_controlled_comparison` |
| separate-breakage | regressions-detected | regressions-detected | regressions-detected | |
| hidden | regressions-detected | regressions-detected; **`verify --run` alone: passing (exit 0)** | regressions-detected; **`verify --run` alone: passing (exit 0)** | |

- **No false proofs:** 18 of 20 controls matched their expectation, and 0
  false proofs (no control expected to fail was reported `supported`).
- **The two mismatches are recorded, not hidden.**
  - Both upstream projects keep the related tests in the same file as the new
    test. The pinned scenario is that whole file, so the breakage fails the
    scenario itself: the claim is still not established, by another route.
  - The `separate-breakage` control was added after this was seen, and
    declared before it ran.
  - Run 1 is kept as recorded too. Its `hidden` control skipped nothing,
    because the list of broken tests came from a regression check that had
    been skipped. It is therefore not evidence for the hidden-regression
    check.
- **What `hidden` shows** is what ordinary test runs miss. An agent "fixes"
  the failures its change caused by skipping those tests:
  - `verify --run` passes;
  - ProofLab runs the base's version of the edited file against the change,
    and names the 2 (json-pointer) and 8 (ipaddr.js) tests that now fail.

**What these runs do not show:**
- They are not a held-out evaluation. A scout picked the cases and had
  checked them beforehand.
- They are not evidence that agents do better with ProofLab.
- They cover Windows, Linux, pytest and TypeScript not at all.

## Cost

- **Time:** ProofLab runs the scenario `2 × repeat` times on each of the three
  sides (base, control, candidate), the full suite twice (the subject-only
  check), then verify. On a large suite, the two full runs dominate.
- **Measured** (run 4, both projects have suites under 2 s): a supported run
  took 3.1–4.6 s wall, including the control run, the canary and verify's
  regression check. A run stopped by preflight took about 1 s. A hang costs
  the `--timeout`.
- **Money:** nothing. Everything is local, with no model call, no network and
  no new dependency.

## External tools (researched, not integrated)

The first milestone integrates **no** external tool ([the research](PROOFLAB-EXTERNAL-TOOLS.md)): the demonstrations need
none.

| Tool | Verdict for now | Why |
|---|---|---|
| Hypothesis (MPL-2.0) | supported as part of a scenario, not an adapter | a property test is just a test file; pin `--hypothesis-seed` in the command, and keep `.hypothesis/` ignored so a saved example cannot change the oracle |
| coverage.py (Apache-2.0) | the first candidate adapter | could show the scenario executes the changed lines; only when the project already has it |
| Playwright, Stryker/mutmut/cosmic-ray, LSPs, ast-grep | deferred | browsers and servers, per-mutant cost, approximate reachability, or JS/TS-only value; none is needed for a first proof |
| GitHub checks | not used | check runs need a GitHub App; `prove report --out` writes the Markdown, and you post it (`gh pr comment --body-file proof.md`) |
| in-toto / DSSE / cosign | format only | `--format in-toto` is unsigned; signing needs your own key or identity and the network |

**An adapter contract, specified for later and not implemented.** Every
future scenario adapter must declare:
- `id`, `version` and the tool's digest;
- `executes_repo_code`: none, tests-only, app-server or arbitrary;
- filesystem and process permissions;
- `network`: none, loopback, egress or fetch-at-setup;
- the credentials it needs, by name;
- execution: runs per side or per mutant, deterministic or not, the seed;
- resources and cost;
- the output schema id;
- completeness: exhaustive, sampled, heuristic or best-effort, plus what it
  skipped;
- provenance;
- platforms.

**Rules for adapters:**
- Any adapter whose network is not `none`, or that has a cost, is off by
  default and needs explicit approval.
- A completeness other than `exhaustive` is shown in the passport and never
  turned into a pass.

## Limits

**Challenged, and what remains.** An independent adversarial reviewer challenged the exact implementation
over four rounds (`164c678`, `7fa342d`, `f1281ec`, `b4ebb93`).
- **Found:** 10, 5, 5 and 3 false proofs.
- **Each round's fixes:** every finding was fixed with a regression test in `tests/test_prove.py`. The
  structural changes that closed whole classes:
  - the subject: the scenario runs on the base plus only the code under test;
  - the subject-only check: the whole suite runs on the base plus only that code;
  - fail-closed rules for code outside the subject.

**What remains open, by design or by limit:**
- **Fifth round (Session A, `8288b2f`):** 8 false-proof instances (S1, S2d, S5, S17 declared and inferred,
  G4 declared and inferred, E1). Each now has a regression test (the probes, vendored as
  `tests/test_sa_redteam_*.py`, and `tests/test_prove_false_proofs.py`) that fails on `1832a53`. The fixes:
  - the level follows the verdict;
  - the scenario must also pass on the whole working tree;
  - a second regression tree;
  - preflight's dataflow abstention;
  - one export view.

  Session A has not yet rerun them independently.
- **Sixth round (independent adversarial review of `473c41a`):** 22 more false proofs in 15 fixtures. They
  bypassed the first dataflow check (a block-list) through parametrize, aliases, class attributes, mutation,
  defaults, fixtures named with `name=`, `functools.partial`, unchanged non-test helpers, expected values
  computed by the change, and node re-exports. Others hid regressions in data or in a module named
  `testing.py`, made the `prove status` list show the recorded verdict, or used a new keyword.
  - The fixes: the allow-list above, the wider outside-subject rule, the export view in the list, and the
    new-interface patterns.
  - Their probes are vendored as `tests/test_prove_review6_*.py`, with the static ones inverted to the safe
    result.
- **Seventh round (independent adversarial review of `0ec0516`):** 17 more. They went through:
  - a decorator registry, `__init_subclass__`, a mutation through a local alias, a data file as the subject,
    an environment variable set by a second call;
  - values bound by `except … as` or `match`;
  - a CommonJS re-export;
  - a class whose `__eq__` always holds;
  - `export-ignore`;
  - runtime files the outside rule still excluded (a root `.ini`, nested `.md` and `package.json`, a package
    named `snapshots`);
  - new functions and constructors judged as behaviour.

  The response was to **narrow the supported scope** rather than patch each form: one entry point, literal
  inputs and independent expectations; node claims never supported; every non-test edit outside the subject
  checked; `export-ignore` refused; new comparison rules refused; more new-interface messages. Their probes
  are vendored as `tests/test_prove_review7_*.py`.
- **Eighth round (independent adversarial review of `54830b9`, inside the narrowed scope):** 19 more. All of
  them had an inferred subject. They went through:
  - a module alias, `sorted(key=…)`, `usefixtures`, plugin modules, an imported `setup_module`, fixture
    shadowing, methods of one module object or class counted as one entry;
  - a module constant inside an operand, an enum the change edits;
  - classes that compare equal to anything;
  - runtime-read files the outside rule excepted.

  The fixes:
  - a supported claim needs a declared subject;
  - each analyser gap above is closed;
  - dynamic class building in changed code abstains;
  - the excepted files join the second regression tree.

  With the subject declared, every one of the 19 is now refused except one case, kept as a strict expected
  failure (`tests/test_prove_review8_eq_regress.py::test_e3_with_the_subject_declared`): a class that
  **already** compares equal to anything at the base, returned by the change. That needs code written to
  cheat. It is outside the declared scope ("Mistakes, not attacks" below), and it is still an open way to get
  a false `supported`.
- **An expected value inside the code under test.** When a file the scenario imports holds both code and
  the expected values (no pytest or unittest import in it), ProofLab cannot tell which is which.
  - An expected value the repository computes (`assert f(x) == core.expected_for(x)`) or holds as a module
    constant abstains: only literals, enum members and classes are independent expectations.
  - With an inferred subject the level stays at `behavior_observed`, and the passport names the file.
  - With a declared subject the declaration is trusted; the passport says so.
- **The dataflow rules are static.** They read the scenario, its test helpers and the `conftest.py` files
  above it, and only the import-time statements and comparison methods of the code under test.
  - The one entry point is trusted to be what the claim is about: its own side effects between calls, and
    what it reads that the change also edits outside the subject, are its behaviour. The second regression
    tree checks the latter against the base's tests.
  - A class that already compares loosely at the base (an `__eq__` that always holds) is not noticed.

  The rules abstain on some genuine fixes (see "How one experiment works").
- **node, in-process:** a candidate that patches `node:assert` for one specific value is not caught. The
  canary only shows that assertions still fail in general.
- **Local forgery:** see "Mistakes, not attacks" below.
- **New interfaces:** a claim about a function that does not exist at the base cannot reach `supported`.
  The base cannot load the scenario, so its failure is a load failure, not a reproduced behaviour. This is
  a false negative.
- **The subject-only check runs once a side:** a test that fails flakily at the base, while the change
  breaks it, is not counted as new.
- **Code outside the subject:** a change that edits code the scenario does not reach gets an incomplete
  regression check until that code is declared with `--subject`. This is deliberate, because a module named
  like code can hold expected values.

- **Mistakes, not attacks:** ProofLab checks for mistakes, not for a hostile
  candidate.
  - Code under test runs in the scenario's own process and can defeat any
    check made there, the canary included, if it sets out to.
  - The passport is a local record: anyone who can write `.repo-ai/state`
    can forge one.
  - A reviewer who must rely on it re-runs `repo-ai prove run`.

- **Runners:** unittest, pytest and `node --test` only. Jest, Vitest and
  other opaque runners are `environment-unavailable`.
- **One claim:** a scenario is one file, so a claim needing several test
  files needs several claims.
- **The scenario is what is tested:**
  - a passing scenario shows the claim only for what it checks;
  - no tool checks that the scenario tests what the claim's words say;
  - code that detects it is under test and behaves differently is not
    detected.
- **Oracle inputs** are found by layout (conftest chain, pytest config, the
  test directory). A test helper imported from outside the test directory is
  not compared.
- **The regression check** has verify's limits: its selection confidence,
  and the full suite only when required or asked for. Session A's #41–#43
  fix the false passes D1–D9 that it would otherwise inherit.
- **Repeats:** two by default, so rarer flakiness is not ruled out.
- **No measured agent benefit:** see
  [PROOFLAB-AB-PROTOCOL.md](PROOFLAB-AB-PROTOCOL.md) for how that would be
  measured.
- **A known defect, inherited from verify's sandbox layer:** on macOS, a test
  process that detaches into its own session outlives the run. It stays
  inside the seatbelt profile, with no network and writes only to the
  deleted copy. It was reported on PR #24 (comment 6385386478); it is not
  fixed yet.
