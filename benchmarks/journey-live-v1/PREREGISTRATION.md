# journey-live-v1: live adopter journeys on real upstream defects, project code in containers (preregistered)

C21 (real adopter proof), live half. Approved by the owner on 2026-11-02 with this scope: the four defects below, project
code only in podman-machine containers, **at most 4 Claude sessions, each capped at `--max-budget-usd 1.00`, $4.00 in
total** (Claude Code's reported `total_cost_usd`; on a subscription login it is metered against the plan, and the
actual charge is otherwise UNKNOWN). Nothing is pushed upstream. Committed with the harness (`run.py`) before the run.

## Defects (pinned; each base is the fix's first parent; all MIT-licensed)

| id | repository | base | upstream fix | release containing it | write paths given to the agent |
|---|---|---|---|---|---|
| humanize | python-humanize/humanize | `8059ebe1732c89177709476165f6e87cc76fe1b7` | `2968d44280a68f775db73ddeb2f2fc6c05edac84` (#250) | 4.12.3 | `src/humanize/filesize.py` |
| marshmallow | marshmallow-code/marshmallow | `c7152171fbe7c12f5ac77800a43dc7ad8ae2e2cf` | `de5e842aeaf7eacfa42e9231f8b18e0792851c45` (#2772) | 4.0.0 (`84b15960`) | `src/marshmallow/schema.py`, `src/marshmallow/utils.py` |
| more-itertools | more-itertools/more-itertools | `c8baa10e66de18662114b71edcfa32f5dfdd2881` | `719a333bccd20ced15a7b4688fb6d47f05d8606d` (#720) | v10.0.0 (`5c1fb20d`) | `more_itertools/more.py` |
| pyjwt | jpadilla/pyjwt | `783f324e5d2155462515ced45718fc164dd04db2` | `33022c25525c1020869c71ce2a4109e44ae4ced1` | 2.10.1 (`3ebbb22f`) | `jwt/api_jwt.py` |

The write paths are the non-test, non-changelog files the upstream fix changed: the agent is told where to edit
(localisation is given, a stated limit). The upstream fixes are public and older than the model's training data, so a
candidate matching upstream may be recall; this is an adopter journey, not a capability benchmark.

## Task given to the agent (fixed now)

- humanize: "`humanize.naturalsize` no longer accepts a float such as `1.0` or a numeric string such as `\"1\"`; both
  should give `\"1 Byte\"`, as an int does. Fix it in src/humanize/filesize.py without changing the tests."
- marshmallow: "A Schema subclass that declares a field as a class (`name = fields.String`) instead of an instance
  must raise `TypeError('Field for \"name\" must be declared as a Field instance')` when the class is defined, not
  later when it is used. Fix it in src/marshmallow/ without changing the tests."
- more-itertools: "`unique_in_window(iterable, n)` gives wrong results: `list(unique_in_window([1, 2, 3, 4, 4, 4],
  1))` should be `[1, 2, 3, 4, 4, 4]`, and `list(unique_in_window([0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 2, 3, 4, 2], 2))`
  should be `[0, 1, 0, 2, 3, 4, 2]`. Fix it in more_itertools/more.py without changing the tests."
- pyjwt: "`jwt.decode(token, key, issuer=\"urn:expected\", algorithms=[\"HS256\"])` accepts a token whose `iss` is
  `\"urn:\"` (a partial match). It must raise `InvalidIssuerError` unless `iss` equals the issuer (or one of them,
  when a list is given). Fix it in jwt/api_jwt.py without changing the tests."

## Isolation and network

- **Host (macOS):** `git clone` of each repository with hooks disabled; repo-ai from PyPI (the first release with
  `do --sandbox/--image`) in its own virtualenv; Claude Code in repo-ai's isolated live mode (dedicated login, file
  tools only, no shell, web or MCP; writes only to the mission workspace). No project code runs on the host: no
  install, no import, no test.
- **Container (podman machine, rootless):** one image per project, `FROM docker.io/library/python:3.12-slim` pinned
  by digest at build time. The base checkout is installed with its test extras, then the project itself is
  uninstalled, so the image holds **dependencies only** (the candidate is always imported from the mission
  workspace). Network only while building; `pip freeze` and the image digest are recorded. Every test run (native
  checks, `repo-ai verify` and missions) uses repo-ai's podman backend: `--network=none`, read-only root, all
  capabilities dropped, `no-new-privileges`, pid/memory/CPU limits, only the disposable workspace mounted.
- **Side effects:** scratch directories and local images, removed after the run; the dedicated Claude login.

## Journey per defect

1. **Frozen tests.** On the base, commit only the upstream fix's test-file changes ("frozen tests"). In the container,
   the native suite must fail on the frozen tests and pass with the upstream fix applied; a defect that does not
   behave this way is reported and dropped before any model call.
2. **Onboarding.** `repo-ai init --agent none` (committed), `repo-ai verify --run --sandbox podman --image IMG
   --json`: recorded as is.
3. **Live mission.** `repo-ai do TASK --agent claude --allow-live-provider --max-cost-usd 1.00 --run --allow-write
   PATH... --sandbox podman --image IMG --json` (with `--expect-fix` for the frozen tests when the base already has
   failing tests in the container; decided by step 1's observation, recorded).
4. **Hidden oracle (upstream differential).** The test files the fix touched, as of the release containing it, are
   copied onto (a) base + upstream fix and (b) base + the candidate, and run natively in the container. A test that
   passes on (a) and fails on (b) is a behavioural difference. The agent never sees these files.
5. **Apply and undo** (only on a PASS): `repo-ai apply ID` (post-apply verification in the container), then
   `repo-ai undo ID`; the tree after undo must be byte-identical to the tree before apply (tracked and untracked).
6. **Failure recovery** (once, humanize, no model call): the same mission with an image that lacks pytest must not
   report a pass, and must name the cause.

## Preparation already run (no model call), 2026-11-02

`run.py prep` on the podman machine: base image `python:3.12-slim@sha256:b224e2fe…`; four dependencies-only images
(the project not installed in any); in each, the frozen tests fail at the base and pass with the upstream fix. Two
harness parsing fixes were needed before that held (pytest colour forced by a project's configuration; pytest 9
`SUBFAILED` subtest lines); no gate, defect or task changed. humanize's release 4.12.3 is the fix commit itself, so
its hidden oracle equals its frozen tests (no independent holdout for that defect). A no-model check with the
development build: `repo-ai verify --run --base <base> --sandbox podman --image <more-itertools image>` on the frozen
tests reports `regression` (the subtest failure is seen). Records: `results/prep-records.jsonl`.

## Gates (decided now)

| id | measure | gate |
|---|---|---|
| L1 | missions reported PASS whose candidate fails the frozen tests natively in the container | **0** |
| L2 | PASS candidates with a behavioural difference from upstream on the hidden oracle | reported, never called correct |
| L3 | applies whose undo leaves the tree not byte-identical | **0** |
| L4 | project code executed on the host (any install, import or test outside the container) | **0** (by construction; the harness never calls a host interpreter on project code) |
| L5 | the failure-recovery mission reported as passing | **0** |
| L6 | Claude sessions / reported cost | ≤ 4 / ≤ $4.00 |

Pass rate (missions PASS out of 4) is reported, with no gate: four defects have no power for a rate. One run. A harness
crash before any model call is fixed and rerun; after a model call, the record is kept as is and no session is
repeated. Results: `RESULTS.md`, raw records under `results/`.
