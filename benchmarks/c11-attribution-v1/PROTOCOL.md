# c11-attribution-v1: per-requirement changed-line attribution on real projects, in containers (predeclared)

C11 (requirement/evidence graph). Its next action is "an independent review of fixture-scope (pytest) and per-file
(node) attribution on real projects (host and container runs) before any rule depends on the mapping". This study
**produces** the attribution records on real projects and a package a reviewer can check by reading; it does not
grade them. A separate reviewer judges them later against the rubric below. **$0: no model call**: every mission is
the `replay` agent carrying the upstream fix as an explicit proposal, as journey-live-v1's positive control does.
Committed with the harness (`run.py`) and the four declarations (`requirements/`) before any study run.

## What is under test

repo-ai **0.12.8 from PyPI** (`pip install repo-ai-cli==0.12.8` in a fresh Python 3.12 virtualenv), the first release
whose change-exercise measurement and per-requirement changed-line record run in container missions (`do --sandbox
podman --image IMG`). For a mission run with a frozen declaration (`do --requirements FILE`) that ends PASS, repo-ai
runs the frozen test command a second time under its tracer, in the same image (pinned by digest), and records which
changed executable lines ran while each pytest test ran; `repo-ai coverage ID --json` then lists, per requirement,
the changed lines its own mapped tests ran (`changed_lines_run`), the changed lines only undeclared tests ran, and
those run outside any test (import, collection). Attribution is by time window (setup, call and teardown of the
test), except that each run of a **shared** (session-, package-, module- or class-scoped) fixture's setup is
credited to the tests whose call ran with it active.

## Defects (journey-live-v1's pinned bases and upstream fixes; all MIT-licensed)

| id | repository | base (fix's first parent) | upstream fix | changed source |
|---|---|---|---|---|
| humanize | python-humanize/humanize | `8059ebe1732c89177709476165f6e87cc76fe1b7` | `2968d44280a68f775db73ddeb2f2fc6c05edac84` (#250) | `src/humanize/filesize.py` |
| more-itertools | more-itertools/more-itertools | `c8baa10e66de18662114b71edcfa32f5dfdd2881` | `719a333bccd20ced15a7b4688fb6d47f05d8606d` (#720) | `more_itertools/more.py` |
| pyjwt | jpadilla/pyjwt | `783f324e5d2155462515ced45718fc164dd04db2` | `33022c25525c1020869c71ce2a4109e44ae4ced1` | `jwt/api_jwt.py` |
| marshmallow (optional) | marshmallow-code/marshmallow | `c7152171fbe7c12f5ac77800a43dc7ad8ae2e2cf` | `de5e842aeaf7eacfa42e9231f8b18e0792851c45` (#2772) | `src/marshmallow/schema.py`, `src/marshmallow/utils.py` |

marshmallow is optional and runs last: its test IDs changed between runs in journey-live-v1 (an INCONCLUSIVE
control); repo-ai measures changed lines only after a PASS, so an INCONCLUSIVE marshmallow mission is recorded with
no attribution, as it is.

The task text and the write paths are journey-live-v1's (`DEFECTS` in `../journey-live-v1/run.py`, imported, not
copied).

## Requirement declarations (frozen now, `requirements/<id>.json`)

The requirement texts and the tests they name come from each upstream fix's **test** changes, the test file they
are in, and the fix's commit message. Stated plainly: the author saw the whole upstream diff (source included) while
preparing this study, and the control tests were picked knowing it; no attribution output existed when they were
written. Each requirement names the frozen tests that pin it, by the pytest node id (repo-ai matches `file::test` to
its recorded `file::file::test`). Two kinds:

- **change** requirements, one per behaviour the changed or added test cases state;
- **control** requirements (`kind: preserve`) naming unchanged tests next to the changed one in the same test file:
  the neighbouring parametrized cases (humanize), the other tests of the test class (more-itertools), the issuer
  tests of the same class that the commit message's str-versus-list description covers plus the test right before
  the changed one (pyjwt), the tests right before and after the changed one (marshmallow). They give the reviewer
  tests that should, and tests that should not, reach the changed lines. They are an addition to a strictly
  diff-derived declaration and are labelled "control" in their text.

| id | R | kind | tests |
|---|---|---|---|
| humanize | R1 float 1.0 gives "1 Byte" | change | `test_naturalsize[test_args58-1 Byte]` |
| | R2 str "1" gives "1 Byte" | change | `test_naturalsize[test_args59-1 Byte]` |
| | R3 int 1 still "1 Byte" | preserve | `test_naturalsize[test_args57-1 Byte]` |
| | R4 other sizes keep their format | preserve | `test_naturalsize[test_args56-1.0K]`, `test_naturalsize[test_args60-3.14 MB]` |
| more-itertools | R1 n=1 yields repeats once out of the window | change | `UniqueInWindowTests::test_basic` |
| | R2 repeated items counted in the window | change | `UniqueInWindowTests::test_basic` (the same test: one test ID for both, flagged by `shared_tests`) |
| | R3 key function | preserve | `UniqueInWindowTests::test_key` |
| | R4 n <= 0 raises | preserve | `UniqueInWindowTests::test_invalid_n` |
| pyjwt | R1 partial iss match rejected | change | `TestJWT::test_rasise_exception_on_partial_issuer_match` |
| | R2 str issuer by equality | preserve | `TestJWT::test_check_issuer_when_valid`, `TestJWT::test_raise_exception_invalid_issuer` |
| | R3 list issuer by membership | preserve | `TestJWT::test_check_issuer_list_when_valid`, `TestJWT::test_raise_exception_invalid_issuer_list` |
| | R4 missing iss raises MissingRequiredClaimError | preserve | `TestJWT::test_raise_exception_token_without_issuer` |
| marshmallow | R1 field declared as a class raises at class definition | change | `test_fields_must_be_declared_as_instances` |
| | R2 TypeError from on_bind_field propagates | preserve | `test_bind_field_does_not_swallow_typeerror` |
| | R3 Function field dump (schema built in the `serialized_user` fixture) | preserve | `test_function_field` |

The humanize parametrize indices were counted from the frozen test file (case 0 is `([300], "300 Bytes")`) and agree
with journey-live-v1's recorded IDs for cases 58 and 59. If the prep stage's native run shows a declared ID was not
collected (a typo, not what is studied), the declaration is corrected before any mission and the correction is
recorded as an amendment here.

### Fixture-scope cases (stated before the run)

A static scan of the four frozen test suites (`scope=`, `autouse`, `setUpClass`, `setUpModule`) finds **no
shared-scope fixture** in any of them. Expected consequences, stated now so the reviewer can check them:

- pytest's own unittest integration gives every `TestCase` class (more-itertools) a class-scoped fixture that runs
  `setUpClass` (unittest's default no-op): shared, but it runs no project line.
- The fixtures that do run project code are **function-scoped**, so their setup falls in the test's own time window:
  pyjwt's `jwt` (constructs `PyJWT()`, no changed line expected) and marshmallow's `user`/`serialized_user`
  (`serialized_user` builds and dumps `UserSchema()`, which runs schema-binding code; R3's test uses it).
- marshmallow's `_get_fields` runs when a Schema class is **defined**: classes defined at module import
  (`tests/base.py`, test modules) run it outside any test; classes defined inside a test body run it in that test.

So this study can review function-scoped fixture attribution and import-time attribution on real projects, but
**not** the shared-fixture crediting path (`fixture_lines` / `fixture_uses`), which these suites never exercise with
project code. Likewise **no Node project** is in scope (no node image exists locally and the study builds none), so
per-file (`node --test`) attribution on a real project is not covered, and **no host run** is made (third-party code
runs only in containers). The review package says so; those parts of C11's next action stay open.

## Isolation and network (as journey-live-v1)

- **Host (macOS):** `git clone` of the four public repositories (hooks disabled) into the work directory
  `$HOME/.cache/repo-ai-studies/c11-attribution-v1` (new); repo-ai from PyPI in its own virtualenv. **No project code
  runs on the host**: no install, no import, no test. The host reads the clones only with git.
- **Container (podman machine, rootless):** the existing dependencies-only images
  `localhost/journey-{humanize,more-itertools,pyjwt,marshmallow}-deps:1` (built by journey-live-v1's prep: the
  project installed with its test extras, then uninstalled; the candidate is always imported from the mission
  workspace). Nothing is pulled or built; a missing image skips its defect. repo-ai's runs use its podman backend
  (`--network=none`, read-only root, all capabilities dropped, `no-new-privileges`, pid/memory/CPU limits, only the
  disposable workspace mounted). The harness's native check reuses journey-live-v1's `podman_test` (no network,
  read-only root, no capabilities, `no-new-privileges`, pid/memory limits). `pip show` inside each image confirms the
  project is not installed.
- **Network:** only the git clones. **Side effects:** the work directory; repo-ai's own disposable workspaces under
  `$TMPDIR/repo-ai-ws-$UID` (the harness records any a run leaves behind; only those are removed).

## Run (`run.py`)

1. **prep** (no model, no repo-ai): per defect, on the base commit only the upstream fix's test-file changes
   ("frozen tests"), then the upstream source change as a separate commit kept under `refs/journey/upstream` (the
   replay's source). In the container, the native suite on the frozen tree and on the upstream-fixed tree: a defect
   qualifies when its frozen tests fail at the base and the upstream fix fixes at least one; `--expect-fix` is the
   fixed set when the upstream-fixed tree still has a failing test (pyjwt's `test_get_jwt_set_sslcontext_default`
   needs the network). The outcomes of every declared test on both trees are recorded.
2. **run**: refuses a build other than `repo-ai 0.12.8` or one without `do --requirements`. Per defect, a fresh clone
   of the frozen branch (humanize: the gitignored hatch-vcs version file written as a stub), `repo-ai init --agent
   none` committed, the upstream fix written as a `repo-ai.replay/1` proposal (outside the checkout), then

   ```
   repo-ai do TASK --agent replay --replay FIX.json --run --allow-write PATH... \
       --requirements requirements/<id>.json --sandbox podman --image localhost/journey-<id>-deps:1 \
       --json --max-seconds 900 [--expect-fix TEST]
   repo-ai coverage ID --json
   repo-ai coverage ID
   ```

3. **export**: the records with paths shortened (`<work>`, `<venv>`, `<tmp>`, `<repo>`, `~`) to `results/run-1.jsonl`.
4. **package**: the reviewer's tables (numbered upstream hunks, declarations, declared tests' source, per changed
   line which declared tests ran it) for `REVIEW-PACKAGE.md`.

One run. No model is called, so a harness crash is fixed and the stage rerun (recorded below as an amendment);
repo-ai's own outcome for a defect (a refusal, FAIL, INCONCLUSIVE, a timeout, an UNMEASURED or absent per-test
record) is recorded as it is and not retried.

## What is recorded (per defect)

- the mission ID, the `do` exit code, its verdict as recorded (`verdict`, `effective_verdict`, `standing`,
  `freshness` and reasons) and as observed (journey-live-v1's `observed_verdict`: a completed container mission
  whose only open point is the unchecked image counts by its passport verdict);
- the full `repo-ai coverage ID --json` record and its text form: per requirement `status`, `observed`,
  `changed_lines_run`/`changed_lines_run_count`, `changed_lines_unavailable`; `changed_lines_by_requirement`
  (`measured`, `granularity`, `complete`, `run_by_tests_of_no_requirement`, `run_outside_any_test`, and for node
  `unavailable_test_files`); `shared_tests`; the `declaration` label;
- the mission's change-exercise record from its state file (assurance, unexercised lines, `per_test` by node id,
  `per_test_complete`, `per_test_reason` when absent, `changed_outside_tests`, `backend`, `container` with the pinned
  image digest, and `tracer` with the Python version and `sys.monitoring`/`settrace`), and the baseline and candidate
  executor records;
- the image tag and digest; the repo-ai workspaces each run left behind.

A container mission's freshness reads `not checked` (a read-only command cannot check an image), so `coverage`'s
headline is expected to be INCONCLUSIVE and verified rows `UNVERIFIED_INCONCLUSIVE` (`observed_status` keeps the
observation). The changed-line record is informational and is computed regardless; it is what this study collects.

## Reviewer rubric (applied later, by someone else)

For each defect, from `REVIEW-PACKAGE.md` alone (code, tests, attribution; nothing needs to run):

1. **Credited lines plausible.** For each requirement, is every line in its `changed_lines_run` plausibly executed by
   at least one of its mapped tests, given the fixed code and the test body (inputs, branches taken)?
2. **Missing credit.** Is there a changed executable line that a mapped test clearly executes but that is not in
   the requirement's `changed_lines_run` (and not explained by a stated limit: import time, a teardown, a thread, a
   child process, a cut record)?
3. **Unreachable credit.** Is any line credited to a requirement whose tests cannot reach it (for example a control
   test that raises before the changed code, such as more-itertools R4 and pyjwt R4)?
4. **Undeclared and outside-any-test lines.** Are `run_by_tests_of_no_requirement` and `run_outside_any_test`
   consistent with the code (for example marshmallow's class-definition-time lines)?
5. **Fixture cases.** For marshmallow R3 (`serialized_user`, function-scoped) and pyjwt (`jwt`, function-scoped): are
   lines run during fixture setup credited to the test? Is any shared-fixture credit present at all (none expected)?
6. **Record completeness.** `complete`, `per_test_reason`, `tracer`, the backend and the image digest: does the record
   say what it could not see?

Per defect and requirement the reviewer marks each credited line plausible / implausible / unclear, lists missing
lines, and gives an overall finding (consistent / inconsistent / not measured). A finding about repo-ai is reported
as a product issue; this study changes no code.

## Environment

macOS (Darwin 25.5, arm64), podman machine `podman-machine-default` (applehv, 7 CPUs, 2 GiB), Python 3.12 for the
virtualenv. Results: `results/run-1.jsonl`, `REVIEW-PACKAGE.md`.
