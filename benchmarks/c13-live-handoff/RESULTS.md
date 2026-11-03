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
