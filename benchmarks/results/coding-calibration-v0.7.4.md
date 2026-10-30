# Calibration run (v0.7.4): Option A limits

**Experiment:** `20261020-222831-1ee7`, run 2026-10-20 from 22:28 to 22:37 local time. The raw rows are in
`calibration-v0.7.4/` (`experiment.json`, `runs.jsonl`, SHA256SUMS). The owner's lab store keeps a
read-only copy.

**Authorization:** the owner authorized this 12-run calibration only, with a maximum of $24. It is separate
from the earlier $10 pilot.

**Protocol (PREREGISTRATION.md §10, Amendment 1):**
- **Build:** repo-ai 0.7.4, from the pipx install, which is byte-identical to the release wheel.
- **Claude Code:** 2.1.304, with auto-update disabled.
- **Model and effort:** `claude-sonnet-5-5`, effort `medium`.
- **Design:** seed 0, one repetition.
- **Limits:**
  - 60 turns and a 1,800 s timeout;
  - a $1.50 per-run cap with a $1.875 reservation per run;
  - a $24 budget, of which 12 × $1.875 = $22.50 is reserved.
- **Not blind:** calibration success informs nothing but the limits.
- **Tasks:** cal-bt-001, cal-md-001, cal-pf-001 and cal-sj-001, all outside the sealed set.

**Costs:** these are Claude Code's client-side `total_cost_usd` estimates. They have **not** been reconciled
with provider billing or account usage. "Spent" below always means estimated.

## Every run

| Task | Arm | Position | Result | Est. cost | Turns | Tool calls | Fresh input | Output | Cache read | Cache creation | Wall time | Largest call (est.) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cal-bt-001 | Full | 1 | pass | $0.1148 | 10 | 9 | 12 | 2,377 | 153,850 | 18,906 | 45.2 s | $0.0463 |
| cal-bt-001 | Core | 2 | pass | $0.1106 | 11 | 10 | 12 | 2,501 | 148,043 | 17,700 | 32.7 s | $0.0433 |
| cal-bt-001 | Plain | 3 | pass | $0.1057 | 12 | 11 | 14 | 2,117 | 175,848 | 16,733 | 39.9 s | $0.0363 |
| cal-md-001 | Core | 1 | pass | $0.0933 | 6 | 5 | 10 | 1,566 | 122,323 | 16,358 | 36.2 s | $0.0424 |
| cal-md-001 | Plain | 2 | pass | $0.0625 | 4 | 3 | 8 | 743 | 84,868 | 11,642 | 16.0 s | $0.0378 |
| cal-md-001 | Full | 3 | pass | $0.0955 | 6 | 5 | 10 | 1,495 | 124,914 | 16,999 | 25.1 s | $0.0440 |
| cal-pf-001 | Core | 1 | pass | $0.1132 | 12 | 11 | 12 | 3,002 | 150,520 | 17,021 | 36.6 s | $0.0465 |
| cal-pf-001 | Full | 2 | pass | $0.1248 | 13 | 12 | 14 | 3,440 | 184,268 | 17,996 | 52.7 s | $0.0475 |
| cal-pf-001 | Plain | 3 | pass | $0.1307 | 16 | 15 | 20 | 3,644 | 258,550 | 17,086 | 69.3 s | $0.0370 |
| cal-sj-001 | Plain | 1 | pass | $0.0928 | 9 | 8 | 12 | 1,662 | 144,444 | 15,427 | 45.7 s | $0.0378 |
| cal-sj-001 | Core | 2 | pass | $0.1132 | 11 | 10 | 14 | 2,303 | 183,553 | 17,937 | 37.7 s | $0.0425 |
| cal-sj-001 | Full | 3 | pass | $0.1123 | 11 | 10 | 14 | 2,200 | 183,645 | 17,980 | 35.0 s | $0.0435 |

**Per arm:**

| Arm | Est. cost (total / mean) | Turns | Tool calls | Output | Cache read | Cache creation | Wall time |
|---|---|---|---|---|---|---|---|
| Plain | $0.3917 / $0.0979 | 41 | 37 | 8,166 | 663,710 | 60,888 | 170.9 s |
| Core | $0.4303 / $0.1076 | 40 | 36 | 9,372 | 604,439 | 69,016 | 143.2 s |
| Full | $0.4474 / $0.1119 | 40 | 36 | 9,512 | 646,677 | 71,881 | 158.0 s |

**Totals:**
- **Estimated cost:** $1.2694, a mean of $0.1058 per run. With the $3.08 pilot, cumulative estimated
  live spend is $4.35.
- **Mean cost by arm position:** 1st $0.104, 2nd $0.103, 3rd $0.111.

## Integrity

- **Completion:** 12/12 valid; 0 invalid, crashed, cancelled or errored. No cost-cap or turn-limit hits,
  and no timeouts.
- **Isolation:** no isolation problems or contamination, and no regressions (visible tests passed in
  every run).
- **Pinning:** every run reported `claude-sonnet-5-5` (the only model used) and Claude Code 2.1.304.
- **Grading:** in podman, in every run.
- **Plugins and MCP:** every arm loaded the same two built-in plugins (`cc-plugin-agents-md`,
  `cc-plugin-plugin-authoring`) and no MCP servers.
- **Arms behaved as configured:**
  - Plain had no repo-ai context and no hook events.
  - Core and Full had 188–330 tokens of repo-ai context, and their hooks fired: 8–16 hook events for Core,
    10–20 for Full.
  - Full used no subagents and invoked no skills.
- **Budget:**
  - The most expensive run was $0.1307 against a $1.875 reservation.
  - The largest estimated single call was $0.0475, against the $0.375 margin.
  - Reservations were written before every run, and every one closed.

**Success:** 4/4 in every arm (Wilson 51–100%). This is not an efficacy result: the tasks are 1–2 line fixes
chosen only for calibration, n = 4, and every arm was at the ceiling.

## Measurement defect found (fixed in 0.7.5)

**What was wrong:**
- Core and Full were reported with "unnecessary edits" on cal-pf-001 and cal-sj-001.
- Every flagged file was interpreter bytecode (`__pycache__/*.cpython-312.pyc`) that running Python in
  the workspace leaves untracked.
- Reproduced offline: running the code writes the same untracked bytecode in **every** arm, and no arm's
  `.gitignore` covers it.

**Where the difference between arms came from:**
- repo-ai's project settings add hooks only: no environment changes, and no hook runs tests.
- The difference is in what the agents ran. Core and Full left bytecode from their test runs (43 files in
  Full on cal-sj-001, consistent with a whole-suite run), while Plain's Bash calls left none.
- 0.7.4 did not record Bash commands, so which commands each agent ran cannot be checked after the fact.

**The fix:**
- Untracked interpreter caches and test-tool caches are now counted separately as `execution_artifacts`.
- Tracked files, module-level `.pyc` files and anything else still count as edits.
- Every Bash command is recorded, along with a count of test runs.

**Grading hardening (also 0.7.5):**
- Grading now copies the workspace without `__pycache__`, so hidden tests always import the agent's
  source.
- Before this, bytecode whose header matched a source file's mtime and size would have been imported
  instead of the source. A regression test demonstrates this.
- No calibration result depended on this: all 12 fixes were source edits.

## Limits by the pre-registered rule

Computed in code (`coding_lab.preregistered_limits`) from the raw rows above.

| Limit | Value | Basis |
|---|---|---|
| Per-run cap C | **$0.75** | smallest allowed value ≥ 2 × the largest per-arm p90 ($0.1307) and above every run's cost |
| Reservation R | **$0.9375** | C + max(0.25 × C = $0.1875, 2 × $0.0475 rounded up to $0.10) = $0.75 + $0.1875; the default, so no `--reserve-per-run` |
| Max turns T | **30** | no run used more than 24 turns (most: 16) or hit the limit |
| Timeout | **1,800 s** | 2 × the longest run (69.3 s) is lower |
| Mean-cost upper estimate u | $0.2237 | 2 × the largest per-arm mean ($0.1119), which is above the overall p90 ($0.1248) |
| Recommended budget | **$40** | 147 × u + 3 × R = $35.70, rounded up to $5 |
| Guaranteed-completion budget | **$140.63** | 150 × R, with no crashes |

## 150-run cost outlook (estimates)

- **At the calibration mean:** about $16.
- **At the planning upper estimate u:** about $34.
- **If every run cost its full reservation:** $140.63.

A **$40 budget does not guarantee** that all 150 runs finish:
- The gate starts a task only when all its remaining arms' reservations fit, so a budget stop never breaks a
  task's three-arm comparison.
- All 75 repetition-0 runs come first.
- A budget stop becomes likely only if sealed-task runs average more than about $0.25.
