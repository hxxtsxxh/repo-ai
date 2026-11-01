# journey-offline-v2: the offline workflow on real fixes whose tests fail without them (preregistered)

C21 (real adopter proof), offline half. v1 was inconclusive: its selection skipped fixes merged through pull
requests and its defects never made the native suite fail ([../journey-offline-v1/RESULTS.md](../journey-offline-v1/RESULTS.md)).
Committed with the harness (`run.py`) before the run; the existing `journey.yml` workflow runs it on `journey/**`
pushes (CI runner only). Spend: $0; no provider, no model.

## Projects (pinned)

jpadilla/pyjwt 2.10.1, python-humanize/humanize 4.12.3, more-itertools/more-itertools v10.7.0, pallets/itsdangerous
2.2.0, marshmallow-code/marshmallow 4.0.0; each installed editable in its own `.venv` with its test dependencies.

## Defect selection (mechanical)

Candidates, newest first along `--first-parent` from the pinned ref (at most 200): a merge commit counts as its pull
request's whole change (`M^1..M`); any other commit as itself. A candidate qualifies when its message (subject and
body) matches `(?i)\bfix(e[sd])?\b|\bbug\b|\bregression\b`, it changes at least one non-test `.py` file and at least
one test file, no dependency or configuration file, at most 400 lines, **and** applying only its test-file changes on
its base makes the project's own suite fail (`python -m pytest -q -p no:cacheprovider`, non-zero exit) while the base
suite passes. The first **2** qualifying candidates per project are the defects (at most 15 candidates tried).

## Journey per defect (fresh clone at the base B, repo-ai from the commit under test)

`repo-ai quickstart`, `repo-ai init --agent none` (its files committed), `repo-ai verify --record`; then
- **test without the fix:** apply only the test-file changes; `repo-ai verify --run --json`; revert;
- **fix:** apply the whole change; native suite and `repo-ai verify --run --json`; revert;
- `repo-ai uninstall --agent all --yes`, then compare with B: `git diff --stat B` (tracked) and
  `git ls-files --others --exclude-standard` (untracked), recorded in full.

## Gates (decided now)

| id | measure | gate |
|---|---|---|
| J1 | test-without-fix states (native fails by construction) that verify reports as passing (exit 0) | **0** |
| J2 | fix states with a passing native suite that verify reports as passing | reported (expected: all) |
| J3 | projects where uninstall leaves no tracked difference from B and no untracked file | reported (expected: all) |

One run. A harness crash is fixed and rerun without changing projects, selection or gates. Results: `RESULTS.md`.
