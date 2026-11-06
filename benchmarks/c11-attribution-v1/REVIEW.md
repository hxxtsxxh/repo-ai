# c11-attribution-v1: independent review

Written by a reviewer that did not produce the records (a separate agent instance, given PROTOCOL.md, REVIEW-PACKAGE.md, run-1.jsonl and read-only access to the pinned clones; no project code run). Reproduced as delivered.


Reviewer: independent (did not produce the records). Date: 2026-11-05.
Branch reviewed: `study/c11-attribution-real` at `3b737afe6e7465b2abfdc71976f98c50173e1536`. The worktree was already
at `origin/study/c11-attribution-real` ("up to date"). Because no network was allowed, I did not run `git fetch`.
Inputs: `PROTOCOL.md`, `REVIEW-PACKAGE.md`, `results/run-1.jsonl`, `requirements/*.json`, and the upstream clones in
`~/.cache/repo-ai-studies/c11-attribution-v1/<defect>/repo`. I read the clones with `git show` / `git grep` only.
I also read the mission state files under `<defect>/mission/.repo-ai/state/missions/` to get the test command and to
cross-check `per_test`. No project code was run, imported or installed. To check branch reach in more-itertools and
pyjwt I wrote my own replica of each fixed function, annotated with the upstream line numbers, and ran it on every
input the declared tests use. That script is in `scratchpad/c11sim/sim.py`; it imports nothing from the projects.

## Verdict summary

| defect | R | kind | credited | verdict |
|---|---|---|---|---|
| humanize | R1 | change | 94 | CORRECT |
| humanize | R2 | change | 94 | CORRECT |
| humanize | R3 | preserve | 94 | CORRECT |
| humanize | R4 | preserve | (none) | CORRECT |
| more-itertools | R1 | change | 4276, 4280-4283, 4285, 4287-4290 | CORRECT at test granularity (caveat below) |
| more-itertools | R2 | change | same 10 | CORRECT |
| more-itertools | R3 | preserve | same 10 | CORRECT |
| more-itertools | R4 | preserve | (none) | CORRECT |
| pyjwt | R1 | change | 422, 423 | CORRECT |
| pyjwt | R2 | preserve | 422, 423 | CORRECT |
| pyjwt | R3 | preserve | 422, 426 | CORRECT |
| pyjwt | R4 | preserve | (none) | CORRECT |
| marshmallow | R1-R3 | - | not recorded | CANNOT-JUDGE (not measured: the mission was INCONCLUSIVE) |

Counts: 12 CORRECT, 0 MISSING-LINES, 0 FALSE-CREDIT, 3 CANNOT-JUDGE.

I found no case where repo-ai credited a line that a requirement's tests cannot reach. I also found none where it
left out a changed line that those tests run. `run_by_tests_of_no_requirement` and `run_outside_any_test` are empty
in all three records, and that matches the code, relative to the pytest collection (see limit L1).

A note on rubric question 4. The brief asks whether crediting nothing to the controls is correct. Only three controls
are credited nothing: humanize R4, more-itertools R4 and pyjwt R4, and for those three nothing is the right answer.
The other controls (humanize R3, more-itertools R3, pyjwt R2 and R3) do reach the changed lines. Crediting them
nothing would have been a false "not run", and repo-ai credited them correctly.

## Preliminary checks

- **The replayed source is the real upstream fix.** For each defect, the diff `journey..refs/journey/upstream` on the
  source file has the same changed lines as the upstream fix commit (`fix^..fix`). I compared hashes of the +/- lines,
  and they match for humanize, more-itertools and pyjwt. The pyjwt fix's parent is the declared base `783f324`.
- **The frozen test changes are test-only and as described.** In more-itertools, the n=1 expectation changed and the
  R2 case was added. In pyjwt, `test_rasise_exception_on_partial_issuer_match` was added. In humanize, two cases were
  added (lines 72-73).
- **The humanize parametrize indices are right.** Case 0 is at line 14, so line 70 is case 56 `[1024, False, True]`,
  71 is case 57 `[1]`, 72 is case 58 `[1.0]`, 73 is case 59 `["1"]` and 74 is case 60 `[3141592, ..., "%.2f"]`.
- **The test command repo-ai froze is the full pytest suite.** It is `python -m pytest`, and for humanize
  `PYTHONPATH=src python -m pytest`. This comes from the mission state files (`baseline.pin.command`,
  `regression.full_suite.command`). The study's exported records do not carry it.
- **`per_test` in the exported `mission-state` rows matches the on-disk mission state files exactly.**
- **Predeclaration order.** `a59cb31` (protocol, harness, declarations) is dated 07:12:26Z, and the first prep row is
  07:12:35Z, so the declarations came first. The requirement files did not change afterwards.
- **The two `requirements_sha256` values both check out.** `mission-start` records the sha256 of the file, and
  `coverage` records a different value. I reproduced the coverage value for humanize as
  sha256(`json.dumps(requirements, sort_keys=True, separators=(',', ':'))`). This is a canonical hash, not a mismatch,
  but the package does not explain it.

## humanize (`src/humanize/filesize.py`, one changed executable line: 94)

The fixed code is at `refs/journey/upstream`. Lines 86-89 turn a str into `float(value)` and leave any other value
alone. Line 91 is `abs_bytes = abs(bytes_)`, line 93 is `if abs_bytes == 1 and not gnu:`, and line 94 is
`return f"{int(bytes_)} Byte"`.

Test body: it calls `naturalsize(*args)`. It then negates the first argument (`*= -1` for an int, the string
`f"-{x}"` otherwise) and calls again.

- **R1, case 58 `[1.0, False, False]`.** The first call reaches 94 because abs is 1.0 and gnu is False. The negated
  call is `"-1.0"`, which becomes -1.0 and also reaches 94. Credited {94}: **CORRECT.**
- **R2, case 59 `["1", False, False]`.** `float("1")` is 1.0, so 94 runs. The negated `"-1"` also reaches 94.
  Credited {94}: **CORRECT.**
- **R3, case 57 `[1, False, False]`.** 1 and -1 both reach 94. Credited {94}: **CORRECT.** This control does reach
  the changed line: the int path also goes through the changed f-string.
- **R4, cases 56 `[1024, False, True]` and 60 `[3141592, False, False, "%.2f"]`.** abs is never 1, and case 56 also
  has gnu=True. Line 94 cannot be reached. Credited nothing: **CORRECT.**
- **Undeclared tests.** No other test or source module calls `naturalsize`. `src/humanize/__init__.py` only
  re-exports it. Case 78 `[1.123456789]` has abs 1.12, so it does not reach 94. `tox.ini [pytest]` sets
  `--doctest-modules`, but pyproject's `[tool.pytest.ini_options]` takes precedence (`testpaths = ["tests"]`, no
  doctest). Either way, none of the docstring examples (lines 48-63) use ±1, so an empty undeclared set is correct.

Overall: **consistent.** It is a single line, so the per-requirement precision is trivial. The discriminating evidence
here is that R4 got nothing while its tests run the same function in the same test function.

## more-itertools (`more_itertools/more.py`, 10 changed executable lines)

The fixed `unique_in_window` is at lines 4255-4291. `defaultdict` is imported at line 3. Lines 4272-4273 hold the
`n <= 0` raise, which runs inside the generator when it is first iterated.

My replica gives these results:

| test / subcase | lines reached |
|---|---|
| test_basic, `range(9)` n=10 | 4276, 4280, 4287, 4288, 4289, 4290 |
| test_basic, `range(20)` n=10 | adds 4281, 4282, 4283 |
| test_basic, `[1,2,3,4,4,4]` n=1 (R1's case) | 4276, 4280-4283, 4287-4290 (**not 4285**) |
| test_basic, `[1,2,3,4,4,4]` n=2 | all 10, including 4285 |
| test_basic, R2's case n=2 | all 10 |
| test_basic, union | all 10 |
| test_key | all 10 (keys 0,0,1,1,1,2,2,2,3 with n=3: the first discard of key 0 hits `-= 1` at 4285, the next hits `del` at 4283) |
| test_invalid_n | none (raises at 4273, before 4276) |

- **R1 (`test_basic`).** Credited all 10, and `test_basic` does run all 10: **CORRECT at the declared test
  granularity.** Caveat: R1's own behaviour case (n=1) never runs line 4285. That credit comes from other subTest
  cases in the same test (n=2 and R2's case). The package says in general that test granularity cannot separate
  subTest cases, and `shared_tests` flags the test. It does not state this concrete overstatement for R1.
- **R2 (`test_basic`).** Credited all 10. Its own case also reaches all 10: **CORRECT.**
- **R3 (`test_key`).** Credited all 10, including both branches 4283 and 4285: **CORRECT** (confirmed by trace).
- **R4 (`test_invalid_n`).** Credited nothing. `ValueError` is raised at 4273, which is unchanged, before 4276:
  **CORRECT.**
- **Excluded lines.** Line 4284 (`else:`) has no line event and is correctly left out of the changed executable set.
  4286 is blank, and 4291 `window.append(k)` is unchanged.
- **Shared test.** R1 and R2 name the same test, and `shared_tests` lists it with both requirement texts. Their
  credited sets are identical because they come from the same test. The record is honest about this (rubric item 5),
  but a reader of R1's row alone could take 4285 as evidence for R1's behaviour.
- **Undeclared tests.** Under pytest, only `test_basic` and `test_key` call `unique_in_window` (I grepped the whole
  frozen tree). `tests/test_more.py:37-39` defines `load_tests`, which adds `DocTestSuite('more_itertools.more')`.
  That suite includes the docstring examples at more.py:4259-4267, which would run the changed lines (the
  `'abAcda'`/key example reaches 4285). pytest ignores the unittest `load_tests` protocol, so with `python -m pytest`
  they are not collected and the empty undeclared set is correct. The project's own runner is unittest, though
  (`tox.ini`: `python -m unittest`; CI: `coverage run ... -m unittest`). So "no undeclared test ran a changed line"
  is true only for pytest's collection. See L1.

Overall: **consistent.** It is the richest case: two controls with opposite expected outcomes, and branch-level
discrimination that the trace confirms.

## pyjwt (`jwt/api_jwt.py`, 3 changed executable lines: 422, 423, 426)

The fixed `_validate_iss` is at lines 415-427:

- line 416 `if issuer is None: return`;
- line 419 `if "iss" not in payload: raise MissingRequiredClaimError` (line 420);
- line 422 `if isinstance(issuer, str):`, then 423 `!=` and 424 raise;
- line 425 `else:`, then 426 `not in` and 427 raise.

It is reached from `_validate_claims` at line 264 (`options["verify_iss"]`). `_validate_required_claims` (lines
283-285) uses `options["require"]`, which is empty by default, so it cannot raise earlier.

- **R1 (`test_rasise_exception_on_partial_issuer_match`).** str issuer `"urn:expected"`, iss `"urn:"`: runs 422, then
  423, then raises at 424 (unchanged). Credited {422, 423}: **CORRECT.**
- **R2 (`test_check_issuer_when_valid` and `test_raise_exception_invalid_issuer`).** Both pass a str issuer and both
  run 422 and 423. Credited {422, 423}: **CORRECT.**
- **R3 (`test_check_issuer_list_when_valid` and `test_raise_exception_invalid_issuer_list`).** A list issuer makes
  422 false, so they run 426. Credited {422, 426}: **CORRECT.** Line 423 is correctly absent.
- **R4 (`test_raise_exception_token_without_issuer`).** The payload has no `iss`, so it raises at 420, before 422.
  Credited nothing: **CORRECT.**
- **Undeclared tests.** `issuer=` appears only in these six tests (I grepped the whole frozen tree, tests and `jwt/`).
  With `issuer=None`, every other decode returns at 417. An empty undeclared set is correct.
- **Fixture.** All six tests take the function-scoped `jwt` fixture (`return PyJWT()`, test_api_jwt.py:27-29). It
  runs no changed line, so fixture-setup crediting cannot be observed here, as the package says.
- **Tracer run.** It exited 1 because of the network-dependent `test_get_jwt_set_sslcontext_default`, and the record
  is still marked complete. That is plausible for the lines in question. However, the tracer run's per-test outcomes
  are not recorded, so it cannot be confirmed that the traced run's pass/fail set equals the verified run's (see L5).

Overall: **consistent.** It discriminates by branch (str vs list) exactly as the code dictates.

## marshmallow

There is no exercise record: the mission was INCONCLUSIVE because the clock-parametrized test IDs differed between
the baseline and candidate runs, and the measurement runs only after a PASS. R1-R3 are **CANNOT-JUDGE**. The package
reports this accurately.

Product issue (message accuracy): `coverage` gives the reason "not measured (recorded for pytest and node --test
missions run with a frozen --requirements declaration)". This mission is a pytest mission with a frozen declaration.
The real cause, that the verdict was not PASS, is not stated. The package already points this out, and I confirm it
from the raw record (run-1.jsonl row 21, `changed_lines_by_requirement.reason`).

## Product findings about repo-ai

1. **No wrong attribution was found** in 12 measured requirements across 14 changed lines. There is no false "ran"
   and no false "not run".
2. **The marshmallow not-measured reason is misleading** (described above).
3. **The record cannot show a negative positively.** `per_test` lists only tests that ran at least one changed line.
   A declared test that was traced and ran nothing (the three R4 controls) looks the same as a test that was never
   traced or was dropped from the record. "Credited nothing is correct" rests on the code plus `per_test_complete:
   true`, not on positive evidence that those test IDs were seen by the tracer. Suggestion: record the set or count of
   traced test IDs, or mark each declared test as traced.
4. **The tracer run's outcomes are not recorded.** `exit_code` 0 or 1 counts as a full run. A divergence between the
   traced run and the verified run, such as a test that fails only under tracing, would go unseen.
5. **Per-requirement credit is test-level, not subcase-level.** more-itertools R1 is credited 4285, which its own n=1
   case never runs. This is inherent and flagged through `shared_tests`. It is still a real overstatement whenever one
   test carries several behaviours, so a rule built on `changed_lines_run` should treat shared tests as one unit.

## The protocol's stated limits

- **"No fixture-scope evidence": accurate as revised in the package.** The protocol said before the run that the study
  "can review function-scoped fixture attribution and import-time attribution". That expectation depended entirely on
  marshmallow, and the package correctly withdraws it. I repeated the static scan over the whole frozen tree of all
  four projects with a wider pattern set: `scope=`, `autouse`, `setUpClass`, `setUpModule`, `tearDownClass`,
  `setup_module`, `setup_class`, `setup_method`, `setup_function`, `def setUp`, `pytest_configure` and
  `pytest_sessionstart`. Nothing matched. The protocol's own list left out pytest's xunit-style `setup_module` /
  `setup_class`, which become module- or class-scoped fixtures, but none exist here, so the conclusion holds. One
  nuance: more-itertools' implicit class-scoped unittest fixture is shared, so the shared-fixture path may run with
  nothing to credit. That is not evidence either way, and the protocol says so.
- **"No Node": accurate.**
- **"No host": accurate.** All three measured exercise records show `backend: podman` with the image digest pinned,
  and the digest equals the candidate executor's.
- **"marshmallow not measured": accurate.** It should also say that this was foreseeable. journey-live-v1 had already
  recorded marshmallow going INCONCLUSIVE on test IDs that change between runs, and marshmallow was the only defect
  carrying the function-scoped fixture and import-time cases. The design put both of its stated reviewable fixture
  paths on the defect most likely to produce no record.

### Limits that should also be stated

- **L1. The measured test set is pytest's collection, and the records do not say which command was run.** The frozen
  command, `python -m pytest`, is only in repo-ai's mission state, not in `run-1.jsonl` or the package. In
  more-itertools, the project's own runner (unittest, through `load_tests`) adds doctests that run the changed lines.
  Under pytest they do not exist. "Undeclared tests: empty" and "the project configures no `--doctest-modules`" are
  true for pytest but incomplete.
- **L2. Test granularity hides subcases.** State the concrete case: more-itertools R1's own case does not reach 4285.
- **L3. Negative credit is not positively evidenced** (product finding 3).
- **L4. The changed-line set is new-side executable lines only.** Pure deletions are invisible: marshmallow's
  `utils.py` change is deletion-only, and the removed old-side lines in more-itertools and pyjwt are not attributed.
  Lines with no line event, such as `else:` at more-itertools 4284 and pyjwt 425, are left out. The package mentions
  `else:` only for more-itertools.
- **L5. The tracer run's own test outcomes are not recorded.** For pyjwt, exit 1 was accepted as complete.
- **L6. This is one run on one interpreter** (CPython 3.12.16 with `sys.monitoring`). The `settrace` fallback was not
  exercised.
- **L7. The cases are easy.** There are 14 lines in 3 single-file changes, all inside function bodies, with
  generators consumed inside the test body, and no threads, subprocesses, teardown work or cross-test leakage. The only
  negative controls raise at an obviously earlier line. The study shows attribution is right on simple cases. It does
  not show discrimination on hard ones.
- **L8. Amendment 1 leaves out one harness change.** The `package` stage now filters `source_files` to `.py`, which
  drops marshmallow's `CHANGELOG.rst` from the displayed diff. It has no effect on any record, but the amendment says
  only the test-source lookup and the once-per-function listing changed.
- **L9. The controls were chosen with the source diff in view** (already stated in the protocol). This matters little
  here because the controls were judged by code tracing, not taken as given.

## Overall

| defect | finding |
|---|---|
| humanize | consistent (4/4 CORRECT) |
| more-itertools | consistent (4/4 CORRECT; R1's credit is test-level, flagged as shared) |
| pyjwt | consistent (4/4 CORRECT) |
| marshmallow | not measured (3 CANNOT-JUDGE) |

repo-ai 0.12.8's per-requirement changed-line attribution is correct on every measured requirement in this study. The
study gives no evidence on shared-fixture crediting, function-scoped fixture-setup crediting, import-time attribution,
Node, or host runs, so those parts of C11's next action remain open.
