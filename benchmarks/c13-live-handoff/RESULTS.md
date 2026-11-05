# C13 live handoff: results

## Attempt 1 (2026-11-03 UTC): blocked at authentication, $0.00, no model turn

- **Login:** the owner chose the existing dedicated repo-ai login `~/.local/share/repo-ai/claude-eval` (repo-ai's `dedicated_config` mode). The planned `claude-provider` login did not exist. repo-ai only passed the directory to Claude Code; no credential was read, printed or copied.
- **Versions:** repo-ai 0.12.1 installed fresh from PyPI; Claude Code 2.1.317 on macOS (seatbelt).
- **Preflight (no model call):** Claude was eligible, isolated-ready, authorized, and had an enforced ceiling.
- **Source:** an explicitly simulated partial candidate gave verdict FAIL, recovery `partial_progress`. The handoff capsule verified as valid.
- **Live continuation (`--max-cost-usd 0.50`):**
  - The isolation probe passed and the session started.
  - Claude Code then exited 1 with `authentication_failed`: "Failed to authenticate: OAuth token revoked. Please log in again or contact your administrator."
  - Reported cost was $0.00 (OBSERVED), with no assistant turn and no edit. The mission is BLOCKED (LIVE_FAILED).
- **What was not reached:** the oracle and apply/undo steps did not run, because the runner stops when there is no diff.

**Reading.** This is not a C13 result. Nothing was handed to a model, because the login's token had been revoked on the account side. repo-ai reported the failure accurately: BLOCKED, with the provider's own reason and a $0 observed cost.

**Session accounting.** The runner counts an attempt as the approved session unless its record shows a refusal before inference. Its list did not include an authentication failure after the probe, so it now refuses another live start. No inference happened. Running the approved session again after a fresh login needs the owner's confirmation and a corrected rule; any rule change will be recorded here before it is used.

Raw record (paths redacted): [results/attempt-1-2026-11-03.jsonl](results/attempt-1-2026-11-03.jsonl).

## Amendment (2026-11-03, before attempt 2; the owner confirmed re-running the approved session)

`run.py`'s `_no_inference` now also counts an attempt as having made no model call when Claude Code failed to
authenticate (`authentication_failed`) with an observed cost of $0.00, no assistant turn and no diff. The same rule
is applied when past attempts are re-read, so attempt 1 no longer uses up the approved session. Nothing else
changed: one paid session, capped at $0.50 by Claude Code's `--max-budget-usd`, with the same fixture, the same
hidden oracle (in a podman container without network), and the same apply/undo check. Attempt 2 runs with the new
dedicated login `~/.local/share/repo-ai/claude-provider`.

## Attempt 2 (2026-11-03 UTC): PASS, $0.039

The new dedicated login `claude-provider` was used, with repo-ai 0.12.1 from PyPI and Claude Code 2.1.317 on macOS
(seatbelt). Raw record: [results/attempt-2-2026-11-03.jsonl](results/attempt-2-2026-11-03.jsonl).

| Step | Observed |
|---|---|
| Preflight (no model call) | Claude eligible, isolated-ready, enforced ceiling |
| Source | explicitly simulated partial candidate (fixes `add` only): FAIL, recovery `partial_progress` |
| Handoff | capsule verified valid before use |
| Live continuation (`--max-cost-usd 0.50`) | isolation probe passed; Claude Code ran with `dedicated_config`, file tools only (Read, Read, Edit; nothing denied); verdict **PASS**, `LIVE_CANDIDATE_VERIFIED`; reported cost **$0.038988** (OBSERVED); change exercise FULL |
| Partial work | `partial_patch_transferred: true`, `partial_diff_reverified_from_same_frozen_source`; the final diff keeps the transferred `add` fix and adds Claude's `scale` fix |
| Hidden oracle | 4 additional tests, never in the repository or a workspace, run in a podman container without network: **4 passed** |
| Apply / undo | post-apply verification PASS; undo restored tracked and untracked files byte-identically |
| Capsule after | consumed (a second continuation from it is refused) |

**Reading.** This is the first live cross-provider handoff with Claude as the target that passed every step:
repo-ai handed a verified partial candidate (from the replay provider) to Claude Code. Claude ran in repo-ai's
isolated mode on a dedicated login, completed the task from the transferred partial work, passed the frozen tests
and a hidden oracle it never saw, and was applied and undone exactly. One task, one session: this shows that the
path works, not how often it does.

## Live-to-live protocol (predeclared 2026-11-05, before any session)

C13's next action is a live-to-live handoff. Codex (cost UNKNOWN on a plan) and Bob (managed account) are not used,
and no local model server is started, so both sides are Claude Code on the dedicated login: not a cross-provider
result, but the source's partial work is a real model's, not a simulated proposal.

- **Fixture:** `money.py` (`add` returns a - b) and `units.py` (`scale` returns x + k); tests for both.
- **Source (live session 1):** `repo-ai do TASK --agent claude --allow-write money.py --max-cost-usd 0.50`. units.py is
  not writable, so the mission cannot pass. Accepted as a source only if repo-ai classifies it `partial_progress` and
  its diff touches money.py only; otherwise the run stops and that is the result.
- **Handoff:** `repo-ai handoff ID --to claude`, verified with `handoff --verify` before use.
- **Continuation (live session 2):** `repo-ai do --from-handoff CAPSULE --agent claude --allow-write units.py
  --max-cost-usd 0.50` (the widened scope is the user's, recorded in the child's provenance).
- **Checks:** verdict and `partial_patch_transferred` on the child; the hidden oracle (4 tests never in the repository
  or a workspace) on the final diff in a podman container without network; apply (post-apply verification) and undo
  byte-identical.
- **Budget:** at most 2 sessions, each capped at $0.50 by Claude Code's `--max-budget-usd`: at most $1.00 of the owner's
  $10 budget (2026-11-05), accounted from Claude Code's reported `total_cost_usd`. One run in a fresh work directory;
  live starts are counted from its records and nothing is retried after a model call (`run_l2l.py`).
- **Reading:** one task; a pass shows the live-to-live path works, not how often. A source that is not partial, or a
  continuation that fails, is reported as such.
