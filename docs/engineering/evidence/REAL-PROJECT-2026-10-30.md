# Real-project journey: un33k/python-slugify, 2026-10-30

Repository `https://github.com/un33k/python-slugify` at `35aca63` (MIT), cloned into a scratch dir. repo-ai 0.10.0
development wheel (catalog branch, `4f1b91e`), clean venv with only repo-ai and pytest — the project's own optional
dependencies were **not** installed, as a first-time user might run it. Its code ran only inside repo-ai's sandbox
(owner approval, 2026-10-30). macOS seatbelt.

| Step | What | Result |
|---|---|---|
| 1 | `repo-ai quickstart` | 0.14 s; next steps listed |
| 2 | `repo-ai init --agent none` | 0.85 s (adds `.repo-ai/` to `.gitignore`) |
| 3 | deliberate regression in `slugify()` (leading/trailing separators no longer stripped); `repo-ai verify` | 0.37 s; 5 of 6 test files selected (static and string-reference links); confidence MEDIUM with reasons |
| 4 | `repo-ai verify --run` (sandboxed, base comparison) | 2.6 s; **REGRESSION**: 5 tests in `tests/test_release.py` newly fail with assertion details; `tests/test_legacy.py` correctly reported as already failing at the base |
| 5 | regression committed as a "bad commit"; `repo-ai do "... separators are stripped again ..." --agent claude --run --allow-live-provider --allow-write slugify/slugify.py` | first attempt: crashed with `error: docs/release-9/historical-evidence.json` (a 3.4 MB tracked file over the 2 MB per-file bound) → **fixed in `4f1b91e`** (25 MB bound, clear message; also closed a scope-check gap where an over-limit file compared as unchanged) |
| 6 | same `do` after the fix (call #18, $0.035154) | Claude's candidate restored exactly the removed `strip()`; the mission returned **INCONCLUSIVE**: the baseline observation has 2 skipped tests and 20 failures unrelated to the task (environment: optional backends not installed), and missions accept only a suite of pass/fail outcomes that passes completely after the fix |
| 7 | applied Claude's diff to the working tree; `repo-ai verify --run` | 2.6 s; **NO NEW FAILURES** against the bad commit |

## Findings

1. A tracked file over 2 MB made every mission fail with an opaque error — fixed, with tests.
2. The same bound let a change to such a file pass the provider scope check unseen — fixed, with tests.
3. Missions are strict by design (PASS = the identical suite failed, then passed completely, nothing skipped). On a
   real repository with skips or failures that the task does not touch, they abstain. That is honest, but it means
   `verify --run` — not `do` — is today's working path on such repositories. Queued: a reviewed design that allows a
   skip set identical at base and candidate and failures outside the task's tests, without opening a false PASS.
4. `verify` reports new and pre-existing failures but does not name tests a change **fixed**; queued.
5. The quickstart reports the `repo-ai` on PATH (here the user's global install), not the one being run.

## Addendum: the same candidate through a scoped mission (development build of `--expect-fix`, PR #9)

Claude's recorded candidate from step 6 (it restores the removed `strip()`) was replayed as a simulated proposal
(`--agent replay`, $0) against the same bad commit, on a development build of PR #9:

| Mission | Result |
|---|---|
| unscoped | `INCONCLUSIVE — FAIL`: "candidate did not pass every test" (20 unrelated failures in this environment) |
| `--expect-fix` with the three `tests/test_release.py` tests the regression broke | **`PASS_WITH_PRE_EXISTING_FAILURES`**: the declared tests went from failing to passing, nothing that passed at the base fails; the 20 pre-existing failures (all `tests/test_legacy.py`, missing optional backends) are listed; claim `ASSURANCE_PARTIAL` |

The skipped tests were identical at base and candidate, which 0.10.0 already accepts.

## Live, on the published 0.11.0 wheel (2026-10-30T16:47–16:56Z)

`repo-ai-cli==0.11.0` from PyPI in a clean venv, same bad commit, `--expect-fix` with the three
`tests/test_release.py` tests:

| # | Step | Result |
|---|---|---|
| 1 | `repo-ai init --agent none`, then `do` | refused: dirty checkout (repo-ai's own uncommitted `.repo-ai/` files) — a first-run bug |
| 2 | committed `.repo-ai/` as advised; `do --agent claude` | `INCONCLUSIVE — BLOCKED`: "OAuth token revoked" for the dedicated login (external; the owner must log in again); classified `provider_unavailable` with the setup command, no retry |
| 3 | `do --agent codex` | refused: the committed `.repo-ai/config.toml` was compared as a provider deletion — the same first-run bug, second half |
| 4 | development build with the fix (`fix/init-then-do`), `do --agent codex` | **`PASS [LIVE_CANDIDATE_VERIFIED]`, standing `PASS_WITH_PRE_EXISTING_FAILURES`** (20 unrelated failures listed), claim `ASSURANCE_PARTIAL`; the candidate is **byte-identical to the upstream line** (`.strip(DEFAULT_SEPARATOR)`); `apply` (post-apply 131 ran, 0 failed) then `undo` restored the file byte-exactly |

Open question: the post-apply run in the real checkout reported 0 failures where the sandboxed observations saw the 20
legacy failures; the two environments apparently resolve the optional backend differently. Not yet explained.
