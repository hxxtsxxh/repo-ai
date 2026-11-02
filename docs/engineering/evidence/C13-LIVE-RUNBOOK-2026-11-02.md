# C13 live handoff: runbook and readiness (2026-11-02)

**Approved by the owner on 2026-11-02:** a zero-cost preflight, then **one** live Claude continuation session capped by
Claude Code's `--max-budget-usd 0.50` (accounting: Claude Code's reported `total_cost_usd`; on a subscription login
it is metered against the plan, the actual charge otherwise UNKNOWN). Nothing else.

**Blocked on one owner action (interactive, outside the agent's session):**

```sh
CLAUDE_CONFIG_DIR=$HOME/.local/share/repo-ai/claude-provider claude auth login
```

This creates repo-ai's dedicated Claude login (separate from `~/.claude`; no personal hooks, plugins, MCP servers or
memory). The agent never copies, prints or reads the token; repo-ai's `dedicated_config` mode lets the provider read
only that directory, the Claude installation and the two keychain database files.

**Readiness checked today (no model call):** `repo-ai agents route --allow-live-provider --max-cost-usd 0.5` reports
`claude [SETUP_REQUIRED -> BLOCKED_AUTH]: no dedicated Claude login for repo-ai`, so the preflight correctly stops.

**The run (scripted, refuses a second live session):**

1. Fixture: the two-bug repository (`money.py`: `add` returns `a - b`, `scale` returns `x + k`; `tests/test_money.py`)
   with its own virtualenv; `repo-ai init`; published repo-ai from PyPI.
2. Preflight: `agents route` must no longer say `SETUP_REQUIRED`; repo-ai's isolation probe then starts Claude Code
   once with a model name it rejects before any API request and checks the session would load only the file tools.
3. Source: an explicitly simulated replay proposal that fixes `add` only (labelled simulated), verified by repo-ai's
   own frozen-test runs: FAIL with partial progress.
4. `repo-ai handoff ID --to claude`, `handoff --verify` (VALID, fresh).
5. The one live session: `repo-ai do --from-handoff capsule.json --agent claude --allow-live-provider --max-cost-usd
   0.50 --run --json`. The carried diff is the frozen source; scope (`money.py`), tests and prior outcome are kept.
6. Hidden oracle (never in the repository or the workspace): extra cases for `add` and `scale`, run on the candidate
   diff applied to a copy, **in a podman container without network** (model-written code is not run natively).
7. `repo-ai apply` (post-apply verification), `repo-ai undo`; the tracked and untracked file hashes after undo must
   equal those before apply. `handoff --verify` afterwards must report the capsule consumed.

**Negative credential-access tests:** the dedicated-login profile tests in `tests/test_provider_claude_isolation.py`
(a file elsewhere in HOME and `~/.ssh` unreadable; the login's customisation files unwritable; only the two keychain
database files writable; token mode cannot read the keychain or `~/.claude`) run on CI's macOS job, never on the
managed development Mac (they attempt credential-path reads by design). The live record keeps only the auth mode and
variable names, never a value.
