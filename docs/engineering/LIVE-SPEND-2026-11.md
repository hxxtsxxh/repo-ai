# Live-call spend, November 2026

Budget: **$20.00**, authorized by the owner on 2026-11-01 for the acceptance gates that need live model calls (C03
token mode, the Linux live run, C10, C14, C15, live C21). Each experiment is preregistered before it runs; the
notional cost is the provider's own reported cost (`cost_status: OBSERVED`) as repo-ai records it. With a Claude
subscription token the money is notional (usage counts against the subscription), but it is accounted the same way.
Spending stops at $20.

| when (UTC) | gate | what | provider, mode | result | cost |
|---|---|---|---|---|---|
| 2026-11-01 | C03 | `repo-ai do` on a 4-module toy repository with a seeded bug in `f3` (`--expect-fix` both of its tests, `--allow-write src/toy/m3.py`, `--max-cost-usd 0.50`), published 0.11.6 from PyPI | Claude Code 2.1.316, `token_env`: the running shell had `CLAUDE_CODE_OAUTH_TOKEN` set and `ANTHROPIC_API_KEY` unset (checked by presence, no value read) | PASS, assurance FULL, full suite passed; diff `x + 30` → `x + 3`; tools Read, Edit; no denied action | $0.0145 |
| 2026-11-01 | C03/C04 (Linux) | the same toy journey in a disposable `ubuntu:24.04` container on the existing podman machine, repo-ai 0.11.6 from PyPI, bubblewrap sandbox | Claude Code 2.1.316, `token_env` (token passed by name) | PASS, assurance FULL, `LIVE_CANDIDATE_VERIFIED`; same one-line diff; Read, Edit; no denied action | $0.0129 |
| 2026-11-01 | queue 11 (Linux) | read-boundary probe: asked to Read `/proc/self/environ` and `/etc/os-release` (outside the workspace) without quoting | same | a Read outside the workspace refused (recorded); `/proc/self/environ` refused per the model's report (not recorded); candidate then blocked by repo-ai's source-only scope rule | $0.0138 |
| 2026-11-01 | C10 | c10-confirm-v1: 48 preregistered host-mode runs (8 tasks x 2 arms x 3), skill vs control | Claude Code 2.1.316, sonnet, `token_env`, empty config dir per run | SUPPORTED (8 of 8 tasks, p = 0.0039); `benchmarks/c10-confirm-v1/RESULTS.md` | $3.2509 |

**Total: $3.2921 of $20.00.**

The run record (0.11.6) does not yet name the auth mode. `claude_auth.plan()` chooses `token_env` whenever one of
its token variables is set; the shell that ran it had only `CLAUDE_CODE_OAUTH_TOKEN` (no `ANTHROPIC_API_KEY`), so
this was the subscription token and the cost is notional. From the next release the mission record keeps
`provider.auth_mode` and `provider.auth_env_vars` (variable names only).

## 2026-11-02: the $20 ceiling is not renewed; per-batch approvals

The owner restated the goal on 2026-11-02: the $20 experiment ceiling above is closed (not renewed or increased), and
every paid or subscription-metered batch needs its own approval with the call count, upper bound and accounting basis
shown first. Unknown provider cost stays UNKNOWN, never $0. Approved that day (none run yet, **$0 spent**):

| batch | sessions | upper bound | accounting |
|---|---|---|---|
| C13 live handoff | 1 Claude Code | $0.50 (`--max-budget-usd`) | Claude Code's reported `total_cost_usd`; on a subscription login metered against the plan |
| C21 journey-live-v1 | at most 4 Claude Code | $4.00 ($1.00 each) | same |
| C12 tournament-live-v1 | 4 Claude Code + 4 Codex | Claude $6.00 ($1.50 each); Codex UNKNOWN | Claude as above; Codex: ChatGPT plan usage, no USD figure |

Claude Code checks `--max-budget-usd` between turns, so a last turn can overshoot a cap; the reported cost is recorded
as is. All three wait for the owner's dedicated Claude login; C13 and C21 also run from the 0.12.0 release.

| 2026-11-03 | C13 attempt 1 (claude-eval login, token revoked) | Claude Code | $0.00 OBSERVED (no model turn) |
| 2026-11-03 | C13 attempt 2 (claude-provider login) | Claude Code | $0.038988 OBSERVED (cap $0.50) |
| 2026-11-03 | C21 journey-live-v1 humanize | Claude Code | $0.040707 OBSERVED (cap $1.00) |
| 2026-11-03 | C21 journey-live-v1 more-itertools | Claude Code | UNKNOWN (killed at the capture limit; cap $1.00) |
| 2026-11-03 | C21 journey-live-v1 pyjwt | Claude Code | $0.046787 OBSERVED (cap $1.00) |
| 2026-11-03 | C12 tournament-live-v1 (4 Claude arms) | Claude Code | $0.2028 OBSERVED (cap $1.50 per arm) |
| 2026-11-03 | C12 tournament-live-v1 (4 Codex arms) | Codex | UNKNOWN (ChatGPT plan usage) |

## 2026-11-04: C21 re-run approved

The owner approved, after seeing the call count, upper bound and accounting basis (none run yet, **$0 spent** on it):

| batch | sessions | upper bound | accounting |
|---|---|---|---|
| C21 journey-live-v1 re-run (humanize, more-itertools; amendment 4) | at most 2 Claude Code | $2.00 ($1.00 each) | Claude Code's reported `total_cost_usd`; on the subscription login metered against the plan; unreported cost is UNKNOWN |
| 2026-11-04 | C21 journey-live-v1 re-run humanize (amendment 4) | Claude Code | $0.00 OBSERVED (authentication_failed before any model turn; cap $1.00) |
| 2026-11-04 | C21 journey-live-v1 re-run more-itertools (amendment 4) | Claude Code | $0.00 OBSERVED (the same) |
| 2026-11-05 | C21 journey-live-v1 retry more-itertools (amendment 5) | Claude Code | $0.084002 OBSERVED (cap $1.00) |
| 2026-11-05 | C21 journey-live-v1 retry humanize (amendment 5) | Claude Code | $0.039266 OBSERVED (cap $1.00) |
