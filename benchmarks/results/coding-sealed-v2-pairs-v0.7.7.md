# Exploratory: repo-ai Core vs Plain on sealed-v2 (v0.7.7)

**Exploratory, as registered** (`docs/EXPLORATORY-v2-pairs.md`). No result here
is a confirmatory claim. **sealed-v2 is no longer untouched:** it cannot serve
as fresh evidence for a later confirmatory study.

## Summary

- **Correctness:** Plain solved 23 of 25 tasks (92%), Core 21 of 25 (84%).
  - The difference is −8 points (95% CI −22 … +7, p = 0.5): **inconclusive**.
  - Core did worse on two tasks and better on none.
  - A difference of this size cannot be told apart from run-to-run variance
    with one run per arm. It is not evidence of harm, and not evidence of no
    effect.
- **Regressions:** one Core run broke the visible suite (v2-sg-007); no Plain
  run did. Regression-free: 96% vs 100%, inconclusive, and at the ceiling.
- **Efficiency:** indistinguishable.
  - Cost: $0.157 vs $0.158 per run.
  - Tokens: median −16k (CI −60k … +36k).
  - Tool calls: median 11 vs 11.
  - Runtime: 48.8 s vs 48.2 s.
  - None of these differences is significant.
- **Mechanism check:** the Verify line changed behaviour, though not outcomes.
  - Core ran tests in 11 of 25 runs against Plain's 6, averaging 1.08 test
    commands per run against 0.36.
  - Core still did not do better on correctness.
- **The benchmark was easier than intended.** 21 of 25 tasks were solved by
  both arms. Only 2 tasks were discordant, so the comparison had almost no
  information.

## Execution

| Item | Value |
|---|---|
| Experiment | `20261021-103834-40bc`, 2026-10-21 10:38–11:31 (52 min) |
| Software | repo-ai 0.7.7 (pipx install identical to the release wheel); Claude Code 2.1.304 in every run; `claude-sonnet-5-5`, effort medium in every run |
| Protocol | as registered: `--task-order interleave`, seed 0, schedule SHA-256 `bb90d60e…4184`, blind; 60 turns, 1,800 s, $1.50 cap, $1.875 reservation, $20 budget |
| Attempts | 50 of 50; **50 valid**. No crash, error, isolation problem or contamination. No budget stop, cap hit, turn-limit hit or timeout |
| Integrity | no proof of access (canary or protected-path read) in any run; 0 hidden-material access attempts; no workspace file identical to a hidden test |
| Cost | **$7.8762** estimated (Claude Code `total_cost_usd`, not reconciled with billing), of the $20 authorized. Mean $0.158 per run, maximum $0.417. Largest single call about $0.076 |
| Arm position | mean cost $0.160 when first, $0.155 when second |

**Blinding:**
- Progress showed only task, arm, validity and cost.
- Outcomes were first read after the experiment process ended.

## Primary outcome: correct with no regression

| | Plain | Core |
|---|---|---|
| Correct with no regression | 23/25 (92%; Wilson 75–98%) | 21/25 (84%; Wilson 65–94%) |
| Hidden tests pass (`success`) | 23/25 | 21/25 |
| Regression-free | 25/25 | 24/25 |
| Mean fraction of hidden tests passed | 96% | 96% |

**Paired by task** (Bonett–Price, exact sign-flip test): −8 points, 95% CI
−22 … +7, p = 0.5. **Inconclusive.**

**Every sensitivity analysis gives the same result** (−8 points,
inconclusive): invalid attempts as failures, content match as invalid, and
the primary outcome with invalid attempts as failures. None of them changes
anything, since every run was valid and no content match occurred.

**Discordant tasks** (2, both favouring Plain):
- **v2-dns-005:** Core failed one hidden test (99.6% of them passed); no
  regression. The investigator found no distinguishing signal, so this may be
  model variability.
- **v2-sg-007:** Core's fix passed most hidden tests (98.8%) but also edited
  `sqlglot/parsers/duckdb.py` outside the task and broke the visible suite.
  - That run did run tests (4 commands) but did not catch the break.
  - Plain solved the task without running any tests.

**Failed by both arms:** v2-asn-001 (99.5% and 99.2% of hidden tests passed)
and v2-mk-001 (TypeScript; 0% in both).

## Secondary outcomes (exploratory; paired per task)

| Metric | Plain | Core | Median paired difference (95% CI) | p |
|---|---|---|---|---|
| Estimated cost per run | $0.158 | $0.157 | +$0.004 (−0.017 … +0.009) | 0.81 |
| Tokens per run (mean) | 263,048 | 260,628 | −16,025 (−59,508 … +36,257) | 0.62 |
| Tool calls (median) | 11 | 11 | 0 (−3 … +3) | 0.93 |
| Runtime (median) | 48.2 s | 48.8 s | +4 s (−4.7 … +7.8) | 0.41 |
| Runs that ran any test | 6/25 | 11/25 | — | — |
| Test commands per run (mean) | 0.36 | 1.08 | — | — |
| Edits outside the task | 1 run | 3 runs | — | — |
| repo-ai context injected | 0 | ~273 tokens (est.) | — | — |
| repo-ai setup time | 0 | 1.9 s | — | — |

## Interpretation

**Correctness:**
- No benefit from Core was observed. The point estimate is negative here, as
  it was in Option A (−2 points).
- Neither experiment can tell a small harm from chance.
- Taken together, two independent task sets now point the same way, never in
  Core's favour. That is a consistent absence of evidence for a benefit, not
  proof of harm.

**Verification guidance:**
- Core's Verify line roughly tripled how often the agent ran tests.
- This did not translate into more correct fixes: the one Core regression
  happened in a run that ran tests.
- Running more tests is not, by itself, the bottleneck on these tasks.

**Overhead:** negligible. Cost, tokens, tool calls and runtime are
indistinguishable, and setup adds about 2 s.

**For enabling Core:** there is no measured correctness benefit and no
measured efficiency cost. Enabling it is a matter of preference (context
tools, the Verify line). It should not be presented as improving Claude's
coding performance.

**Why the experiment had little information:**
- Plain Claude solved 92% of sealed-v2, about the same ceiling as Option A,
  despite the harder selection rule.
- Future benchmarks need tasks that the plain agent fails often, around 30–70%
  success, for any arm difference to be measurable.

## Limitations

- **Size:** one run per arm and 25 tasks. Only 2 tasks were discordant, so
  effects below about 30 points were undetectable (as registered).
- **Composition:**
  - one TypeScript task, failed by both arms;
  - sqlglot makes up 8 of 25 tasks;
  - public upstream fixes may be memorised, equally in both arms.
- **Costs** are Claude Code estimates, not billing.

## Evidence

- **Raw evidence:** `sealed-v2-pairs-v0.7.7/`, containing `experiment.json`,
  `runs.jsonl`, `report.md` and `runner.log`, verified with `SHA256SUMS`.
- **Lab-store copy:** made read-only.
