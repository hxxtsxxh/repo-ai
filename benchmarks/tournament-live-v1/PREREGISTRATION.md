# tournament-live-v1: live tournaments with a hidden oracle (preregistered)

C12 (tournament quality): "real candidate comparison, independent frozen base, honest cost/limits, meaningful
tie-handling, evidence expansion and human-choice mechanism; no self-certified winners". The 0.9.0 evidence is one
live abstention and one byte-identical tie. This study runs live two-provider tournaments on tasks that have a sealed
hidden oracle, so selection, abstention and the new difference classification can be checked against ground truth.

Approved by the owner on 2026-11-02 with exactly this scope (8 sessions; Claude capped at $1.50 per arm; Codex cost
UNKNOWN). It runs after `--allow-unknown-cost` (#105) and the difference classification (#104) are on main, from a
checkout of main, with the owner's dedicated Claude login.

## Tasks and oracle

The 4 abc-v5 calibration tasks (`benchmarks/abc-v5/tasks/cal-*`: synthetic, MIT, written for repo-ai; two Python, two
Node). Each has a frozen repository with visible acceptance tests, a task statement with numbered requirements, and a
sealed hidden oracle (`hidden/`), graded by abc-v5's `grade.py` (CORRECT / FALSE_GREEN / FAIL / INVALID). The hidden
tests never enter a workspace or a prompt. These tasks are calibration-only for abc-v5 and are not used confirmatorily
there; using them here does not change that.

## Run

Per task: a fresh repository of the frozen base, `repo-ai init`, then `repo-ai do PROMPT --tournament claude,codex
--run --allow-live-provider --max-cost-usd 1.50 --allow-unknown-cost --allow-write <the task's write paths> --json`.
Claude Code's arm is capped at $1.50 by its own CLI flag; Codex's cost is UNKNOWN (not capped by its CLI). Each arm's
candidate diff is graded by `grade.py` (hidden view). `repo-ai shortlist` is run after each abstention.

**Calls:** 4 tournaments x 2 arms = **8 provider sessions** (4 Claude, 4 Codex), plus repo-ai's isolation probe per
Claude arm (a model name Claude Code rejects before any API request). **Upper bound:** Claude $6.00 (4 x $1.50,
Claude Code's reported `total_cost_usd`); Codex UNKNOWN (ChatGPT plan usage; no USD figure exists). No retry after a
model call; a crashed arm is recorded as is.

## Gates (decided now)

| id | measure | gate |
|---|---|---|
| T1 | winners that are not the only distinct passing candidate (an arbitrary winner) | **0** |
| T2 | comparisons without a `next_step` taken from the decision | **0** |
| T3 | pairs classified IDENTICAL or COSMETIC whose hidden-oracle grades differ | **0** |
| T4 | winners graded FALSE_GREEN or FAIL by the hidden oracle | reported; a winner is never called correct |
| R1 | SUBSTANTIVE pairs whose hidden-oracle grades differ (a real behavioural difference) vs not | reported |
| R2 | cost: Claude observed sum; Codex UNKNOWN | reported |

Four tasks give no rate; this is a demonstration with ground truth, reported per tournament. Negative and
inconclusive outcomes are kept.

## Limits stated now

- The hidden oracles are public in repo-ai's repository. Neither agent is given them or pointed to them, the work
  directory is under HOME (unreadable to the provider sandboxes on macOS), but Codex has a shell and network; a
  candidate byte-identical to the authored reference is flagged (`equals_reference`).
- Codex runs with the owner's personal Codex login, which repo-ai copies into the run's scratch CODEX_HOME where
  Codex's shell can read it (the documented default; the opt-in credential broker is not used here).
- Synthetic tasks written by one agent; the abc-v5 calibration numbers are not reused or pooled.
