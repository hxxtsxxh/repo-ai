# Live provider journeys, 2026-10-29 (installed wheel, macOS seatbelt)

All runs used a wheel built from the named commit and installed non-editable into a clean venv
(`repo_ai.__file__` under site-packages), on throwaway **synthetic** projects written for this
check (not upstream code, not a holdout, not used by abc-v1..v4). Providers ran through
`repo-ai do --run --allow-live-provider` only. Costs are subscription-billed and **UNKNOWN**
(never counted as $0). These are n=1 demonstrations of the workflow, not a performance study.
Raw outputs are in the ignored `dist/launch/live-*/` directories.

| # | Journey | Build | Providers | Result |
|---|---|---|---|---|
| 1 | Single provider: plan → live candidate → `coverage` → `apply` (post-apply tests) → `undo` | `dfb6880` | Codex CLI 0.165.0 | mission `f7eb79c9…`: **PASS `LIVE_CANDIDATE_VERIFIED`**, 24.8 s; correct `divmod` fix; source untouched until apply; `coverage` ACCEPTANCE_PARTIAL (3 requirements verified, 1 deliberately unmapped requirement named, exit 2); apply post-apply 4/4; undo restored bytes (sha256 equal) |
| 2 | Live 2-provider tournament + `shortlist` on real candidates | `dfb6880` | Codex + agy 1.4.9 | comparison `d1fcd78d…`: both PASS with **distinct** diffs → **abstained** (exit 2), no auto-apply; `shortlist` strict: evidence table, no preference; `--policy smallest-diff`: labelled `POLICY_PREFERENCE` for Codex (+2/−2 vs +4/−2) with the "not evidence of correctness" disclaimer |
| 3 | Cross-provider handoff with genuine partial progress | `c505f74` | Codex → agy | A (Codex, scoped to `money.py`): FAIL `partial_progress` (1 baseline failure fixed, 2 remain, no regressions). Capsule `handoff --verify`: VALID (fresh). B (agy, `--allow-write fmt.py` added by the user): **PASS `LIVE_CANDIDATE_VERIFIED`**, 27.1 s; A's 29.9 s debited; B kept A's `money.py` diff byte-identical (seed reused, not overwritten) and fixed `fmt.py`. Apply post-apply 4/4; **independent hidden oracle 714/714** (author-written from the docstrings, never shown to either provider); undo restored bytes |

## Defects these journeys found (each fixed with a failing-first test)

1. `c4b0956` — first-run `verify` found no runner for plain pytest-style tests (clean container journey).
2. `8bb4fe4` — `coverage` printed pytest identities twice (`f.py::f.py::test_x`).
3. `5e8dccf` — `shortlist` could not tell that two passing candidates were the same code (journey 2: agy's diff only added a comment). It now reports AST-identical candidates.
4. `c505f74` — a continuation silently ignored `--allow-write` (journey 3, first attempt: agy correctly refused to edit an unapproved file, so the run could never pass).

## Limits

- Constructed synthetic tasks, n=1 each; the same author wrote tasks, visible tests and the hidden oracle.
- The tournament's tie was benign (same code); a tie between behaviourally different candidates was not exercised live.
- Claude Code as an execution provider was not re-tried (blocked in the isolated scratch HOME); Gemini not tried; Bob not re-run this cycle.
- Codex/agy cost: UNKNOWN. Provider calls this cycle: Codex 4, agy 3.

## Re-run on the freeze build `9663ac3` (wheel `b351d80e…`, distribution `repo-ai-cli` 0.9.0)

Fresh venv, fresh clones of the same synthetic projects, same commands. Raw outputs: ignored `dist/launch/qual-9663ac3/live/`.

| # | Result on the freeze build |
|---|---|
| 1 | Codex mission `63139f85…`: **PASS `LIVE_CANDIDATE_VERIFIED`** (26.8 s); `coverage` ACCEPTANCE_PARTIAL, exit 2 (the unmapped requirement named); apply post-apply 4/4; undo restored bytes |
| 2 | Codex + agy comparison `cad60ad4…`: both PASS with **byte-identical** diffs this time, so they were treated as one candidate and the comparison has a single controlled winner (the predeclared rule); `shortlist` says no policy is needed. Provider output varied between runs; the AST same-code report was not exercised live on this build (covered by tests) |
| 3 | Codex (scoped to `money.py`) → `partial_progress` → capsule VALID → agy with user-added `fmt.py`: **PASS `LIVE_CANDIDATE_VERIFIED`** (31.1 s; 36.5 s debited); apply post-apply 4/4; hidden oracle 714/714; undo restored bytes |

Provider calls in this cycle, all runs: Codex 7, agy 5, Claude 1 (failed authentication before any model call). Cost UNKNOWN (subscriptions).
