# Live coding pilot: v0.7.0 development build (commit 6419111)

**Status: PILOT, directional only.**
- **Design:** 6 held-out tasks × 3 arms × 1 run.
- **Setup:** Claude Code 2.1.304, Sonnet, at most 30 turns, $0.50 cap per
  run, seed 0. Sandboxed grading (podman).
- **Budget:** $10 authorized. **$3.08 spent in total** (Claude Code's own
  estimates, not billing):
  - $1.46 on an excluded first attempt;
  - $0.08 on a one-run validity probe;
  - $1.54 on this experiment.

**Excluded first attempt** (experiment `20261020-111422-bd51`, 18 runs):
- Every run was excluded by an isolation rule that wrongly rejected plugins
  built into Claude Code (`cc-plugin-agents-md`,
  `cc-plugin-plugin-authoring`). These are compiled into the binary and
  identical in every arm.
- The rule was fixed in `6419111`: built-in plugins are allowed and
  recorded per run. Any other plugin or MCP server still invalidates a run.
- None of those runs is used below. For the record, all 18 had passed their
  hidden tests.

## Experiment 20261020-112547-fcda

18 valid runs of 18. $1.54 charged against a $8.46 cap.

| Metric | Plain Claude | repo-ai Core | repo-ai Full |
|---|---|---|---|
| Task success rate | 100% | 100% | 100% |
| Hidden tests passed (mean fraction) | 100% | 100% | 100% |
| Average tokens (input + output, cache included) | 172,410 | 133,176 | 135,304 |
| Median runtime (s) | 23.25 | 25.2 | 30.3 |
| Median tool calls | 8.0 | 5.5 | 4.0 |
| Estimated model cost (mean $) | $0.087 | $0.084 | $0.085 |
| Regression rate | 0% | 0% | 0% |
| Sample size (valid runs) | 6 | 6 | 6 |
| Median time to first edit (s) | 12.35 | 14.2 | 15.4 |
| repo-ai context injected (tokens, est.) | 0 | 226 | 226 |
| repo-ai setup time (s) | 0 | 1.2 | 1.2 |

Paired comparisons:
- **core vs baseline:** 100% vs 100%, diff +0%, 95% CI +0%…+0%,
  McNemar p=1.0, h=0.0, n=6. **Inconclusive (pilot).**
- **full vs baseline:** same numbers. **Inconclusive (pilot).**
- **full vs core:** same numbers. **Inconclusive (pilot).**

## Per task (paired)

| Task | Tokens baseline / core / full | Tool calls | Est. cost ($) |
|---|---|---|---|
| java-ledger-005-uneven-expense-split | 177k / 120k / 125k | 9 / 5 / 5 | 0.097 / 0.076 / 0.080 |
| py-shop-021-receipt-html-injection | 167k / 123k / 205k | 9 / 9 / 10 | 0.084 / 0.083 / 0.110 |
| ts-workspace-004-daily-job-runs-twice | 143k / 73k / 98k | 7 / 3 / 3 | 0.078 / 0.062 / 0.066 |
| ts-workspace-007-cli-duration-syntax | 337k / 281k / 210k | 14 / 12 / 10 | 0.139 / 0.145 / 0.132 |
| ts-workspace-011-flag-value-with-equals | 91k / 127k / 99k | 3 / 6 / 3 | 0.055 / 0.082 / 0.066 |
| ts-workspace-013-root-test-script | 116k / 71k / 73k | 6 / 2 / 2 | 0.068 / 0.055 / 0.058 |

## What this does and does not show

**Task success: no difference.**
- Every arm solved every task. That is a ceiling effect: these tasks are
  within Sonnet's reach unaided.
- With n=6 and no discordant pairs, there is no evidence either way. **The
  claim that repo-ai improves task completion remains UNVERIFIED.**

**Efficiency: directional only.**
- Median tool calls fell from 8 to 5.5 (core) and 4 (full).
- Tokens fell on 5 of 6 tasks for each arm, but rose on one task for each:
  ts-workspace-011 for core, py-shop-021 for full.
- Mean estimated cost was about the same.
- Runtime and time to first edit were slightly *longer* with repo-ai,
  including about 1.2 s of setup.

**What would measure success differences:**
- harder tasks, or a weaker or cheaper model;
- at least 10 paired tasks;
- repetitions.

For example:

```sh
repo-ai eval coding --compare baseline,core,full --split holdout --max-tasks 20 \
    --max-cost-usd <budget> --max-cost-per-run 0.50 --model sonnet
```

## Re-analysis with the v0.7.2 statistics (same runs, no new model calls)

The v0.7.0 report printed the paired success interval as "+0%…+0%". That
was a bootstrap that collapses when all pairs agree. It overstated the
certainty.

**Success:**
- Each arm: 6/6, which is 100% with a 95% Wilson interval of 61–100%.
- Each paired difference: +0 points, 95% Newcombe interval −39…+39, with a
  ceiling flag.
- Verdict: **inconclusive**. Equivalence is not shown either.

**Efficiency** (paired Wilcoxon, n = 6; none significant):

| Comparison | Tokens (median diff, lower in) | Tool calls | Cost |
|---|---|---|---|
| core vs baseline | −50k, 5/6, p = 0.06 | −3, 4/6, p = 0.19 | −$0.007, 4/6, p = 0.69 |
| full vs baseline | −44k, 4/6, p = 0.16 | −4, 4/6, p = 0.13 | −$0.008, 4/6, p = 0.84 |
| full vs core | +3k, 2/6, p = 0.84 | 0, 2/6, p = 0.50 | +$0.003, 2/6, p = 0.84 |

Regenerate with `repo-ai eval report 20261020-112547-fcda`.
