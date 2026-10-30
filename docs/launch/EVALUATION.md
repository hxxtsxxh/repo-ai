# Evaluation ledger (launch program)

## Comparative lift: `NOT_YET_DEMONSTRATED`

| Study | Design | Result | Status |
|---|---|---|---|
| Option A (v0.7.5) | preregistered, 25 tasks × 3 arms × 2, Claude Sonnet | plain 92%, Core 90%, Full 88% | inconclusive; no benefit shown |
| sealed-v2 pairs (v0.7.7) | exploratory, 25 tasks | plain 92%, Core 84% (95% CI −22…+7) | inconclusive |
| abc-v1 | preregistered, 4 tasks, Bob | A 2/4, B 3/4; repo-ai PASSed one false green (node-slug) | inconclusive (n=4) |
| abc-v2 | Codex A/B, 8 cells | all CORRECT | ceiling |
| abc-v3 | 4 tasks, A/B/C | A/B 4/4, C abstained 4/4 | ceiling |
| abc-v4 | pilot, 2 tasks | arm A CORRECT 2/2 → B/C NOT_RUN by rule | ceiling |

**Finding carried forward:** small, well-specified tasks are solved by the bare provider; another
solve-rate study of that shape cannot show lift. The launch thesis (DECISIONS L-001) is therefore
tested on a *safety* outcome instead: whether repo-ai's evidence catches false greens.

## Prospective study abc-v5 (false-green detection)

Preregistered in `benchmarks/abc-v5/` (stage-W freeze `13f5b67`, FULL freeze `598ed2d`, calibration run `d22ecf2`;
`selfcheck.py`: 0 failing checks; covered by `tests/test_abc_v5_protocol.py`). **Calibration only** (4 synthetic
tasks, 29 candidates, $0, no model calls; NOT confirmatory; one author wrote tasks, decoys and oracle):

| false greens accepted | A "tests pass" | A_clean careful developer | B repo-ai | B+ directed follow-up tests | A++ test every requirement |
|---|---|---|---|---|---|
| semantic decoys (9) | 9 | 9 | 5 | 7 | 0 |
| test-gaming controls (10) | 10 | 2 | 0 | 0 | 2 |
| correct candidates declined (of 4) | 0 | 0 | 2 (abstentions) | 0 | 0 |

Task-level discrimination of B: **0 of 4** (its semantic catches were abstentions it also gave the correct
reference). Power (`power.py`): at n = 24 the primary test cannot succeed if B's catches only come from untested
requirements. Consequence: thesis narrowed (DECISIONS L-007); confirmatory phase **NOT_RUN** pending authorised
task authoring. Primary result: `NOT_YET_DEMONSTRATED`.

## Live provider runs this cycle

See [evidence/LIVE-JOURNEYS-2026-10-29.md](evidence/LIVE-JOURNEYS-2026-10-29.md). Workflow
demonstrations, n=1 each, synthetic tasks; they are not evidence of lift.

## Spend ledger

| Item | Known USD | Notes |
|---|---|---|
| Claude live evaluations (Oct 20–21: pilot, calibration, Option A, v2 pairs) | 33.78 | provider-reported, from earlier sessions' records |
| Bob live missions (dev0) | 0.515 | provider-reported (0.156 + 0.079 + 0.102 + 0.055 + 0.123, from the acceptance matrix and `dist/reality-engine/bob-live/spend-ledger.json`); other runs UNKNOWN |
| Claude host probe (dev3) | 0.017 | provider-reported, API-equivalent |
| Codex / agy runs (dev1–dev4, and this cycle: Codex 7, agy 5) | **UNKNOWN** | subscription; never counted as $0 |
| GitHub Actions on the private repository | billed, not attributed per run here | October usage for this repo: Windows 6,722 min, macOS 642 min (≈ $95 net at list price, account-level) |

Known model spend ≈ $34.3 of the ≈ $150 envelope; UNKNOWN entries are excluded from that sum,
so the true total is higher. Actions billing is separate from the model envelope.
