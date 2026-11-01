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

**Total: $0.0412 of $20.00.**

The run record (0.11.6) does not yet name the auth mode. `claude_auth.plan()` chooses `token_env` whenever one of
its token variables is set; the shell that ran it had only `CLAUDE_CODE_OAUTH_TOKEN` (no `ANTHROPIC_API_KEY`), so
this was the subscription token and the cost is notional. From the next release the mission record keeps
`provider.auth_mode` and `provider.auth_env_vars` (variable names only).
