# C13: Claude as a handoff target, attempt (2026-11-01)

**Outcome: BLOCKED (external, authentication).** The handoff capsule was exported, the continuation accepted it,
and the continuation mission received the partial diff. The live Claude step did not run: the record shows no
credential for Claude Code inside repo-ai's isolation (`auth_mode none`, `auth_env_vars: []`). Setup context, not in
the records: the owner had removed the `CLAUDE_CODE_OAUTH_TOKEN` exported for the gates. No model call
(provider returncode -1, provider events `{}`, `continuation_budget.live_seen: false`); `cost_usd` 0.0 with
`cost_status` UNKNOWN.

**Host.** repo-ai **0.11.7** (both records); Claude Code 2.1.316 (`provider.executable`); verification in seatbelt
(executor backend). Setup context, not in the records: macOS Darwin 25.5 arm64.

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
2. **`repo-ai handoff --to claude`** exported a capsule (command line: setup context; the capsule's `next_command`
   and `target_provider` agree).
   - It carries the diff sha256 `8a7115d1…`, three fresh facts (outcome FAIL, original checkout not patched,
     baseline 2 of 2 failing), the constraint "target provider adaptation: claude (requires local verification
     before completion)" and disclosure `LOCAL_ONLY; …`.
   - `--verify` printed VALID (fresh) at the time; that console output was not kept. What the records show: the
     continuation, which refuses an invalid or stale capsule (`mission/runtime.py`, `continue_from`), names it by
     sha256 `1e3dcdd1…` and keeps its three fresh facts.
   - Re-verified afterwards with 0.11.7: **INVALID (stale)**, "stored mission changed since capsule export". The
     continuation had written `continuation_started` into the source mission's record, which the capsule's snapshot
     hash covers, so a capsule cannot be verified again once it has been used. That is consistent with the
     one-continuation rule (a second `--from-handoff` is refused), but the message does not say why.
3. **`repo-ai do --from-handoff <capsule> --agent claude --run`** created continuation mission
   `534f035fb285ffd848fd95ec`.
   - The record's `continued_from` block shows continuation kind `partial_diff_reverified_from_same_frozen_source`,
     `partial_patch_transferred: true`, inherited write path `money.py`, and the prior verdict, provider and cost
     (FAIL, replay, 0.0).
   - The record's seed carries the capsule's diff sha256, with `test_add` fixed and `test_scale` still failing.
   - Baseline and context nodes SUCCEEDED; the edit node FAILED. The record's `provider` block: `auth_mode none`,
     `capture_status not_authenticated`, stage BLOCKED, verification label `LIVE_FAILED`, returncode -1,
     `cost_usd` 0.0 (`cost_status` UNKNOWN).
   - Verdict BLOCKED, recovery category `provider_unavailable`. The reason recorded: "claude not authenticated for
     isolated execution: no dedicated Claude login for repo-ai; run once: CLAUDE_CONFIG_DIR=<home>/.local/share/
     repo-ai/claude-provider claude auth login".

## What this shows and does not show

- **Shows:** the handoff and continuation work locally up to the provider boundary with Claude as the named
  target. The capsule is exported and accepted, the partial diff is carried into a new mission, and an
  unauthenticated provider is refused before any model call, with a recovery action rather than a retry.
- **Does not show:** that Claude completes a handed-off mission. That needs a live run (`token_env` or
  `dedicated_config`) and is the gate's open next action. The source used a simulated provider, so this is no
  cross-provider live result either. The 0.9.0 live codex→agy handoff remains C13's live evidence.
