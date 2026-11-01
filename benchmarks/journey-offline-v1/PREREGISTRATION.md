# journey-offline-v1: the offline workflow on real projects, with defects their own history chose (preregistered)

Acceptance gate C21 (real adopter proof), offline half. Committed with the harness (`run.py`) and workflow
(`.github/workflows/journey.yml`, `journey/**` pushes only) before any run. Third-party code runs only on the
disposable GitHub runner. Spend: $0; no provider and no model.

## Projects (pinned)

python-humanize/humanize 4.12.3, pallets/itsdangerous 2.2.0, marshmallow-code/marshmallow 4.0.0, each installed
editable into its own `.venv` with its test dependencies.

## Defect selection (mechanical)

Walking back from the pinned ref (`--no-merges --first-parent`), the first commit F whose subject matches
`(?i)\bfix(e[sd])?\b`, that changes at least one non-test `.py` file **and** at least one test file, no dependency or
configuration file, and at most 300 lines. P is its parent.

## Journey (fresh clone at P, repo-ai installed from the commit under test)

1. `repo-ai quickstart`, `repo-ai init --agent none`, `repo-ai verify --record`.
2. **Fix:** apply F's whole diff; `repo-ai verify --run --json`; revert.
3. **Test without the fix:** apply only F's test-file changes; `repo-ai verify --run --json`; revert.
4. `repo-ai privacy audit`; `repo-ai uninstall --agent all --yes`; `git status --porcelain` must be empty.

Native reference for each state: the project's full suite, `python -m pytest -q -p no:cacheprovider`.

## Gates (decided now)

| id | measure | gate |
|---|---|---|
| J1 | test-without-fix states that verify reports as passing (exit 0) while the native suite fails | **0** (no false assurance) |
| J2 | fix states, native suite passing, that verify reports as passing | reported (all expected) |
| J3 | uninstall leaves the working tree unchanged | all projects |
| R | per project: verdicts, selected files, timings, disagreements with the native suite, each explained | reported |

A project whose fix state fails natively is reported, not excluded. One run; a harness crash is fixed and rerun
without changing projects, selection or gates. Results: `RESULTS.md` with the run URL.
