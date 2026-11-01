# Live-call spend, November 2026

Budget: **$20.00**, authorized by the owner on 2026-11-01 for the acceptance gates that need live model calls (C03
token mode, the Linux live run, C10, C14, C15, live C21). Each experiment is preregistered before it runs; the
notional cost is the provider's own reported cost (`cost_status: OBSERVED`) as repo-ai records it. With a Claude
subscription token the money is notional (usage counts against the subscription), but it is accounted the same way.
Spending stops at $20.

| when (UTC) | gate | what | provider, mode | result | cost |
|---|---|---|---|---|---|
| 2026-11-01 | C03 | `repo-ai do` on a 4-module toy repository with a seeded bug in `f3` (`--expect-fix` both of its tests, `--allow-write src/toy/m3.py`, `--max-cost-usd 0.50`), published 0.11.6 from PyPI | Claude Code 2.1.316, `token_env`: the running shell had `CLAUDE_CODE_OAUTH_TOKEN` set and `ANTHROPIC_API_KEY` unset (checked by presence, no value read) | PASS, assurance FULL, full suite passed; diff `x + 30` → `x + 3`; tools Read, Edit; no denied action | $0.0145 |
| 2026-11-01 | C10 | c10-confirm-v1: 48 preregistered host-mode runs (8 tasks x 2 arms x 3), skill vs control | Claude Code 2.1.316, sonnet, `token_env`, empty config dir per run | SUPPORTED (8 of 8 tasks, p = 0.0039); `benchmarks/c10-confirm-v1/RESULTS.md` | $3.2509 |

**Total: $3.2921 of $20.00.**

The run record (0.11.6) does not yet name the auth mode. `claude_auth.plan()` chooses `token_env` whenever one of
its token variables is set; the shell that ran it had only `CLAUDE_CODE_OAUTH_TOKEN` (no `ANTHROPIC_API_KEY`), so
this was the subscription token and the cost is notional. From the next release the mission record keeps
`provider.auth_mode` and `provider.auth_env_vars` (variable names only).
