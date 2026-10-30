# Experiments and live-call ledger

Cumulative envelope referenced by the mission: ≈ $150 of model spend across sessions. Recorded before this cycle:
≈ $34.3 (metered Claude-eval runs, Oct 20–21) plus subscription calls with UNKNOWN cost (see
`docs/launch/EVALUATION.md`). Stream `cost_usd` on a subscription login is notional, not billing truth.
Every live call is listed here; none is deleted, including failures.

| # | When (UTC) | Provider / model | Purpose | Outcome | Cost (stream) | Authorization |
|---|---|---|---|---|---|---|
| 1 | 2026-10-30T02:41Z | claude 2.1.314 / `no-such-model-xyz` | startup + flag probe under seatbelt | `unrecognized_model` before inference | $0 | n/a (no inference) |
| 2 | 2026-10-30T02:43Z | claude / sonnet | first sandboxed edit | 401 token expired (refresh blocked by sandbox) | $0 | owner's /goal (small pilot) |
| 3 | 2026-10-30T02:44Z | claude / sonnet | unsandboxed refresh check ("reply ok") | success | $0.0064 | same |
| 4 | 2026-10-30T02:49Z | claude / sonnet | `run_provider` isolated edit | LIVE_READY, correct edit | $0.0139 | same |

Cycle total so far: $0.0203 notional (Max subscription). Further live runs wait for an explicit owner authorization.

## Open experiment protocols (not run)

- **C03 Claude end-to-end journey**: `repo-ai do --agent claude --run --allow-live-provider --allow-write durations.py
  --max-cost-usd 0.50` on a fresh synthetic project; frozen visible tests (2/3 failing at base) and a hidden oracle of
  17 cases kept outside the repository; then `coverage`, `apply`, `undo`. Predeclared pass: mission verdict PASS
  `LIVE_CANDIDATE_VERIFIED`, hidden oracle 17/17, undo restores bytes. A hidden-oracle miss is reported as a failure.
- abc-v5 confirmatory study (from 0.9.0): needs blinded task authors; unchanged.
