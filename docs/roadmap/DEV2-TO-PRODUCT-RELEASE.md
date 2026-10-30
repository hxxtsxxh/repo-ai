# dev2 → dev3 checkpoint

Living, succinct. Facts here are tied to a commit; anything older is labelled historical.

## Verified baseline (historical, dev2)

- `v0.9.0-dev2` published from merge `a08c821` (tree `6788b05b`). Frozen-suite result at `d43fae8`: 2192 collected, 2184 passed, 8 xfailed, 0 failed.
- The macOS Actions job is skipped by its own workflow condition; it is not a green macOS result.
- dev2 installed Cachetools/Marked journeys were **replay** (`live:false`).
- PR #64 (docs checkpoint) merged as `694ae71`. Draft PRs #52 and #57 and tags `v0.9.0-dev0/1/2` are untouched.

## RELEASED: `v0.9.0-dev3` (GitHub pre-release, not PyPI)

Merge `bcf5824` (PR #65), tree `e5281154`; code identical to frozen `941c68e`. Wheel `8eaff706…ea65b`, sdist `df34c8de…6693c`; published assets re-downloaded and hash-verified; wheel rebuilt from the merge commit has the same hash. Suite 2208 / 2200 passed / 8 xfailed / 0 failed. 12 CI jobs green; macOS job skipped by its own condition. `v0.9.0-dev0/1/2` untouched. Assets also in ignored `dist/reality-engine/release-941c68e/`.

## RELEASED: `v0.9.0-dev4` (GitHub pre-release, not PyPI)

Merge `245346f` (PR #67), tree `5467a7c6`; `src/` identical to frozen `9822624`. Wheel `c60518a0…241e7` (byte-identical to the qualified wheel and to a wheel rebuilt from the merge commit), sdist `d5f0d8ac…a05fd3` (differs from the frozen sdist only in two roadmap docs and two test files). Published assets re-downloaded and hash-verified. Suite 2246 / 2238 passed / 8 xfailed / 0 failed. 12 CI jobs green on the PR head; `test-macos` skipped by its own condition. Tags `v0.9.0-dev0..3` untouched.

Two CI-found defects fixed on the way (both test-side; `src/` unchanged): a `privacy` regression test that depended on Python 3.14 pathlib internals, and `test_abc_v4_protocol` missing from the POSIX-only list (manifest keys use OS path separators, so Windows failed it like abc-v1..v3 would).

## dev3 scope (branch `next/dev3-20261029`, merged)

| Priority | Status | Evidence |
|---|---|---|
| A. Useful tournament abstention | **Implemented, CORE** | `repo-ai shortlist`, `src/repo_ai/mission/shortlist.py`, 9 new tests in `tests/test_live_tournament.py` (fake providers: shortlist, labelled policy, tie, unknown policy, uncontrolled arm, all-fail, identical, changed source, CLI shortlist → explicit apply) |
| B. Assurance beyond "tests passed" | **Partial, heuristic** | `unechoed_qualifiers` names `whole` for `node-slug`. It also fires on 11 of 12 historical tasks, so it is a prompt for a human and **does not discriminate**. No new disjoint negative-control set was built. |
| C. Provider-neutral routing | **Implemented (additive)** | `status_class`, `observation_stale`, `auth_observed`; zero/one/many/unsupported tests in `tests/test_provider_registry.py`. Hermetic only; no new controlled host run beyond D. |
| D. One bounded Claude probe | **Done** | `claude auth status` logged in; `claude doctor` no issues; one `claude -p` "reply ok", no tools, no API key in env: succeeded, provider-reported $0.0167938 (API-equivalent, not billing truth). Ledger entry `claude-host-probe-20261029`. Quota reset confirmed. |
| E. New preregistered study | **NOT DONE** | No new tasks, no pilot. abc-v1/v2/v3 remain development evidence only. Comparative lift stays `NOT_YET_DEMONSTRATED`. |
| F. Install UX / setup wizard | **Partly** | README fixed (tournament no longer "replay-only"). No `setup` wizard: no evidence it reduces effort. Candidate-wheel journeys: see acceptance table once run. |
| G. Release | see `FINALIZATION-ACCEPTANCE.md` | |

## Provider matrix (as of 2026-10-29, honest)

| Provider | Host | repo-ai isolated live path | Cost |
|---|---|---|---|
| Bob | works | works, hard USD cap | observed |
| Codex | works | works (outer sandbox, inner bypass only under it) | UNKNOWN |
| agy | works | macOS only, keychain-file read | UNKNOWN |
| Claude | **host probe OK** | **BLOCKED**: login is not a copyable file; credential copying is not assumed acceptable. A scratch-HOME path is a separate, unstarted effort | host probe observed |
| Gemini | rejected earlier | not retried | n/a |

## Spend ledger

`dist/reality-engine/bob-live/spend-ledger.json` (ignored): observed ≈ $2.56 of the ≈ $150 envelope; UNKNOWN entries are never summed as 0. No live trial was run for dev3 except the single Claude host probe.

## dev4 scope (branch `next/dev4-assurance`; candidate frozen at `9822624`, tree `98250103`)

- `repo-ai coverage MISSION_ID --requirements FILE`: developer-declared requirement->test map vs observed per-test outcomes. Real `node-slug` reproduction: decoy and reference are indistinguishable until the cross-list-uniqueness requirement is mapped to a test. Never a correctness claim.
- `benchmarks/abc-v4` pilot (`py-semver`, `node-duration`): arm A (bare Codex) CORRECT on both, so B/C NOT_RUN by the preregistered pilot rule. Four studies (v1..v4) have now hit the arm-A ceiling.
- Fix: `privacy audit` crash when a file vanishes during the size walk, found by the installed-journey run (freeze redone).
- Qualification: see the dev4 row in `FINALIZATION-ACCEPTANCE.md` (2246 collected, 2238 passed, 8 xfailed, 0 failed).

## Backlog (priority order)

1. Study E (real): the ceiling is the finding. A study that can measure lift needs tasks the bare provider fails at a non-trivial rate (larger real-repo issues with under-specified prompts), >= 20 paired tasks, repeats and an authorised budget. Preregister first.
2. D follow-up: design a least-privilege Claude path without copying credentials, or leave it BLOCKED.
3. F: `setup` wizard only if a measured first-run flow shows it helps.
4. Live shortlist exercise with real Codex+agy (abc-v3 produced 4/4 distinct double-PASS cells; `shortlist` has only been exercised on fake providers).
5. Coverage: a way to feed `coverage` from a tournament candidate directly (today: pass the candidate ID).

## Resume

```
cd repo-ai && git status --short --branch && git log --oneline -8
export PYTHONPATH=$PWD/src && /private/tmp/repo-ai-rc1-env/bin/python -m pytest tests/test_live_tournament.py tests/test_mission_claims.py tests/test_provider_registry.py -q
```
