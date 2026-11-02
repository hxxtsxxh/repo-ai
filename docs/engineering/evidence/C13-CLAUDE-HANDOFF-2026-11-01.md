# C13: Claude as a handoff target, attempt (2026-11-01)

**Outcome: BLOCKED (external, authentication).** The handoff capsule was exported and verified, and the continuation
mission received the partial diff. The live Claude step did not run: when the attempt was made, the host had no
credential for Claude Code inside repo-ai's isolation. The owner had removed the `CLAUDE_CODE_OAUTH_TOKEN` it had
exported for the gates. $0 spent; no model call.

**Host.** macOS Darwin 25.5 arm64; repo-ai **0.11.7** (both records); Claude Code 2.1.316. Verification ran in
seatbelt.

## Fixture

The fixture is a two-bug toy repository: `money.py`, where `add` returns `a - b` and `scale` returns `x + k`, and
`tests/test_money.py`, which has `test_add` and `test_scale`. The baseline shows both tests failing.

## Steps and records

1. **Source mission** `af5534525fc0516a493cf783`, run with the `replay` provider. It is labelled SIMULATED and its
   proposal is labelled "explicit simulated proposal: fixes add only".
   - Verdict FAIL. The two reasons recorded: "candidate did not pass every test" and "fresh whole-change regression
     verification did not pass".
   - Recovery category `partial_progress`. The record recommends `do --from-handoff <capsule.json> --agent <provider>
     --run`: the carried diff fixed 1 baseline-failing test without new failures, and 1 test still fails.
2. **`repo-ai handoff --to claude`** exported a capsule.
   - It carries the diff sha256 `8a7115d1…`, three fresh facts (outcome FAIL, original checkout not patched,
     baseline 2 of 2 failing), the constraint "target provider adaptation: claude (requires local verification
     before completion)" and disclosure `LOCAL_ONLY`.
   - `--verify` reported VALID (fresh), recovery category `partial_progress`.
3. **`repo-ai do --from-handoff <capsule> --agent claude --run`** created continuation mission
   `534f035fb285ffd848fd95ec`.
   - The record's recovery block shows continuation kind `partial_diff_reverified_from_same_frozen_source`,
     `partial_patch_transferred: true`, inherited write path `money.py`, and the prior verdict, provider and cost
     (FAIL, replay, $0).
   - The record's seed carries the capsule's diff sha256, with `test_add` fixed and `test_scale` still failing.
   - Baseline and context nodes SUCCEEDED. The edit node FAILED at the provider preflight: `auth_mode none`,
     `capture_status not_authenticated`, stage BLOCKED, verification label `LIVE_FAILED`, cost $0.
   - Verdict BLOCKED, recovery category `provider_unavailable`. The reason recorded: "claude not authenticated for
     isolated execution: no dedicated Claude login for repo-ai".

## What this shows and does not show

- **Shows:** the handoff and continuation work locally up to the provider boundary with Claude as the named
  target. The capsule is exported and verified, the partial diff is carried into a new mission, and an
  unauthenticated provider is refused before any model call, with a recovery action rather than a retry.
- **Does not show:** that Claude completes a handed-off mission. That needs a live run (`token_env` or
  `dedicated_config`) and is the gate's open next action. The source used a simulated provider, so this is no
  cross-provider live result either. The 0.9.0 live codex→agy handoff remains C13's live evidence.
