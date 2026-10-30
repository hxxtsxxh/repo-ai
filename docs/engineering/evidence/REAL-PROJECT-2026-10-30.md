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
