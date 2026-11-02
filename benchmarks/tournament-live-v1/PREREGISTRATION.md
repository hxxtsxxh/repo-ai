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

From a clone of main under HOME, after #104 and #105 are merged: a preflight first (no provider starts) must show the
cap split `{"claude": 1.5, "codex": 0.0}`, both providers eligible and the difference classification present, and the
grader container must grade every task's reference CORRECT and its first semantic decoy FALSE_GREEN. Then per task: a fresh repository of
the frozen base (abc-v5's `materialize_w`: repo plus acceptance tests; no `repo-ai init`, which would change the base),
and `repo-ai do PROMPT --tournament codex,claude --run --allow-live-provider --max-cost-usd 1.50 --allow-unknown-cost
--test-command CMD --max-seconds 1200 --allow-write <write paths> --json` (sequential arms, about 600 s each).
Codex runs first: its cost is UNKNOWN and never adds to the observed spend, so Claude's arm always gets its whole
$1.50, which Claude Code's own flag enforces (checked between turns, so a last turn can overshoot it). Each arm's
candidate diff is applied to a clone of the frozen base and graded by abc-v5's `grade.py` (hidden view) **inside a
podman container without network** (built from `Containerfile`: python:3.12-slim pinned by digest, Debian nodejs,
pytest; its image id is recorded): the grader never runs model-written code on the host (repo-ai's own verification
and the providers run in repo-ai's host sandbox, as in any mission). `repo-ai shortlist` runs after each abstention. A ledger at a fixed path under HOME counts sessions and
started tasks across invocations; a lock prevents two runs at once; the harness stops at the first tournament that
records no comparison or no candidate, or where a grade fails in the harness.

**Calls:** 4 tournaments x 2 arms = **8 provider sessions** (4 Claude, 4 Codex), plus repo-ai's isolation probe per
Claude arm (a model name Claude Code rejects before any API request). **Upper bound:** Claude $6.00 (4 x $1.50,
Claude Code's reported `total_cost_usd`, plus any last-turn overshoot); Codex UNKNOWN (ChatGPT plan usage; no USD
figure exists). No retry after a model call; a crashed arm is recorded as is.

## Gates (decided now)

| id | measure | gate |
|---|---|---|
| T1 | winners that are not the only distinct passing candidate (an arbitrary winner) | **0** |
| T2 | comparisons whose `next_step` does not match the decision (a winner: `repo-ai apply WINNER`; no winner: never the winner's instruction) | **0** |
| T3 | pairs classified IDENTICAL or COSMETIC whose hidden-oracle grades (CORRECT, FALSE_GREEN, FAIL) differ; other grades reported apart | **0** |
| T4 | winners graded FALSE_GREEN or FAIL by the hidden oracle | reported; a winner is never called correct |
| R1 | SUBSTANTIVE pairs whose hidden-oracle grades differ (a real behavioural difference) vs not | reported |
| R2 | cost: Claude observed sum; Codex UNKNOWN | reported |

Four tasks give no rate; this is a demonstration with ground truth, reported per tournament. Negative and
inconclusive outcomes are kept.

## Limits stated now

- The hidden oracles are public in repo-ai's repository. Neither agent is given them or pointed to them; the repo-ai
  checkout (which holds them) and the work directory are both under HOME, which the provider sandboxes cannot read on
  macOS; but Codex has a shell and network. A candidate byte-identical to the authored reference is flagged
  (`equals_reference`). T1 checks repo-ai against its own rule, not against ground truth (T4 and R1 do that).
- Codex runs with the owner's personal Codex login, which repo-ai copies into the run's scratch CODEX_HOME where
  Codex's shell can read it (the documented default; the opt-in credential broker is not used here).
- Synthetic tasks written by one agent; the abc-v5 calibration numbers are not reused or pooled.
