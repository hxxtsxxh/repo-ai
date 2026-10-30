# Design: missions on real test suites (skips and unrelated failures)

Status: proposed (2026-10-30), not implemented. Owner: principal. Gate: C21 (real adopters), C06/C11.

## Problem
`repo-ai do` PASSes only when the identical suite fails at the base and then passes **completely**, with every outcome
`pass`/`fail` (no skip, no xfail). On `un33k/python-slugify` (see `evidence/REAL-PROJECT-2026-10-30.md`) Claude produced
the exact fix, yet the mission abstained: the suite has 2 skipped tests and 20 failures the task does not touch.
Most real repositories have skips (platform, optional dependencies) and some carry unrelated failures, so today
`do` effectively requires a fully green suite.

## Why existing agents don't solve it
Agents run tests and self-report. repo-ai's value is an independent before/after observation; widening it must not
let a candidate *make* tests skip or hide a failure behind an unrelated one.

## Proposal
1. **Skips:** accept `skip`/`xfail` outcomes when the skipped set (ids and reasons class) is **identical** at base
   and candidate, the candidate skips nothing the base ran, and test inputs/config are pinned (they already are).
   Skipped tests count as neither pass nor fail and are listed.
2. **Unrelated failures:** require a declared or derived *task set* (tests failing at the base that the task targets:
   `--expect-fix TEST…`, or all base failures in files linked to the write paths). PASS needs: every task-set test
   fails at base and passes on the candidate; **no** test that passed at the base fails or errors; tests failing at
   base outside the task set may stay failing but are listed as `PRE_EXISTING_UNRELATED` and lower the claim to
   `ASSURANCE_PARTIAL`.
3. Report the new standing explicitly (`PASS_WITH_PRE_EXISTING_FAILURES`), never plain PASS, so scripts can tell.

## Alternatives considered
- Keep strict (status quo): honest but unusable on most real repositories.
- Run only the selected test files in the mission: smaller, but loses the whole-suite regression check.
- Ignore skipped tests entirely: rejected — a candidate could add `pytest.skip` to a failing test (test files are
  frozen, but conftest/plugins and environment-driven skips exist).

## Security / false-PASS threat model
Candidate-introduced skips (environment or code-driven) → refused by set equality. A failing test the candidate
breaks differently → still failing, listed; not counted toward PASS. Flaky base failures → existing flake handling
plus repeat-at-base for the task set. Nothing reads agent self-report.

## Acceptance tests (red-first)
Skip set equal → PASS possible; candidate adds a skip → FAIL; base-passing test fails on candidate → FAIL; task-set
test still fails → FAIL; unrelated base failure remains → `PASS_WITH_PRE_EXISTING_FAILURES` + partial claim;
python-slugify journey reaches that standing with Claude's fix; independent adversarial review before merge.

## Expected marginal benefit (falsifiable)
On a sample of ≥ 5 real repositories with a reproduced bug, the fraction of correct agent fixes that `do` can verify
rises from ~0 (status quo, measured 0/1) to most, with zero false PASS against hidden oracles.
