## Coding experiment 20261021-001148-ee60
model: claude-sonnet-5-5, max turns 30, seed 0; runs: 145 valid of 150; charged $21.55 of $40.00 (Claude Code estimates, not billing)

| Metric | Plain Claude | repo-ai Core | repo-ai Full |
|---|---|---|---|
| Task success rate | 92% | 90% | 88% |
| Hidden tests passed (mean fraction) | 100% | 100% | 100% |
| Average tokens | 241,973 | 225,861 | 257,761 |
| Median runtime (s) | 41.35 | 39.8 | 42.4 |
| Median tool calls | 8.0 | 7.0 | 8 |
| Median test runs by the agent | 0.0 | 0.0 | 0 |
| Estimated model cost (mean $) | $0.139 | $0.141 | $0.151 |
| Regression rate | 0% | 4% | 4% |
| Sample size (valid runs) | 48 | 48 | 49 |
| Median time to first edit (s) | 22.3 | 26.0 | 26.6 |
| repo-ai context injected (tokens, est.) | 0.0 | 266.708 | 267.143 |
| repo-ai setup time (s) | 0.0 | 1.021 | 1.021 |
| Cost p50 ($) | 0.1269 | 0.1313 | 0.1406 |
| Cost p90 ($) | 0.211 | 0.1957 | 0.2113 |
| Cost max ($) | 0.287 | 0.2648 | 0.3334 |
| Runs stopped by the cost cap | 0 | 0 | 0 |
| Turns p90 | 15 | 15 | 16 |
| Turns max | 34 | 23 | 22 |
| Runs stopped by max turns | 0 | 0 | 0 |
| Timeouts | 0 | 0 | 0 |
| Longest run (s) | 186.1 | 103.6 | 127.3 |
| Largest single API call ($, est.) | 0.0565 | 0.0629 | 0.072 |

Every attempt (budget, turn and time limits count as failures; nothing is dropped):
| | Plain Claude | repo-ai Core | repo-ai Full |
|---|---|---|---|
| attempts | 50 | 50 | 50 |
| valid | 48 | 48 | 49 |
| success | 44 | 43 | 43 |
| failure | 4 | 5 | 6 |
| stopped by cost cap | 0 | 0 | 0 |
| stopped by max turns | 0 | 0 | 0 |
| timed out | 0 | 0 | 0 |
| invalid isolation | 0 | 0 | 0 |
| invalid contamination | 2 | 2 | 1 |
| errors | 0 | 0 | 0 |
| crashed | 0 | 0 | 0 |
| cancelled | 0 | 0 | 0 |
| not attempted (of 50 planned) | 0 | 0 | 0 |

Success rates: Plain Claude 92% (95% Wilson 80%–97%); repo-ai Core 90% (95% Wilson 78%–96%); repo-ai Full 88% (95% Wilson 76%–94%)

- **core vs baseline**: success 90% vs 92%, diff -2% (95% CI -16%…+13%, task-clustered Bonett-Price; permutation p=1.0, Holm p=1.0; 24 tasks, 48 paired runs) → **inconclusive: directional (-2%), not significant**; regressions: oss-ct-002, oss-ct-002, oss-md-007
  - tokens: median paired diff +3796.25 (95% CI -37674…+36996.5; lower in 11/24; Wilcoxon p=0.8553)
  - cache_read_tokens: median paired diff +4912.25 (95% CI -39607.5…+35300.5; lower in 11/24; Wilcoxon p=0.7898)
  - cost_usd: median paired diff +0.003 (95% CI -0.0077…+0.0149; lower in 10/24; Wilcoxon p=0.3748)
  - tool_calls: median paired diff -0.5 (95% CI -3…+1; lower in 13/24; Wilcoxon p=0.2664)
  - wall_s: median paired diff +0.6 (95% CI -7.4…+2.25; lower in 10/24; Wilcoxon p=0.9168)
- **full vs baseline**: success 88% vs 92%, diff -4% (95% CI -20%…+12%, task-clustered Bonett-Price; permutation p=0.75, Holm p=1.0; 24 tasks, 48 paired runs) → **inconclusive: directional (-4%), not significant**; regressions: oss-ct-002, oss-ct-002, oss-md-007, oss-md-007
  - tokens: median paired diff +26391.8 (95% CI -726…+41788.5; lower in 8/24; Wilcoxon p=0.1688)
  - cache_read_tokens: median paired diff +24757.8 (95% CI -3506.5…+37201.2; lower in 8/24; Wilcoxon p=0.1974)
  - cost_usd: median paired diff +0.0148 (95% CI +0.0063…+0.0195; lower in 5/24; Wilcoxon p=0.0048)
  - tool_calls: median paired diff +0.5 (95% CI -1…+1; lower in 10/24; Wilcoxon p=0.9825)
  - wall_s: median paired diff +5.2 (95% CI -3.05…+7.75; lower in 10/24; Wilcoxon p=0.6033)
- **full vs core**: success 88% vs 90%, diff -2% (95% CI -13%…+9%, task-clustered Bonett-Price; permutation p=1.0, Holm p=1.0; 24 tasks, 48 paired runs) → **inconclusive: directional (-2%), not significant**; regressions: oss-md-007
  - tokens: median paired diff +15557.8 (95% CI -16041.5…+42044.5; lower in 9/24; Wilcoxon p=0.1875)
  - cache_read_tokens: median paired diff +13956 (95% CI -15156…+43241.5; lower in 9/24; Wilcoxon p=0.1974)
  - cost_usd: median paired diff +0.0068 (95% CI +0.0007…+0.0159; lower in 7/24; Wilcoxon p=0.0564)
  - tool_calls: median paired diff +0.25 (95% CI -0.5…+1.5; lower in 9/24; Wilcoxon p=0.3406)
  - wall_s: median paired diff +3.625 (95% CI -0…+6.9; lower in 7/24; Wilcoxon p=0.114)

Sensitivity analyses (pre-registered):
  - invalid as failures: core vs baseline diff -2% (95% CI -16%…+12%) → inconclusive: directional (-2%), not significant
  - invalid as failures: full vs baseline diff -2% (95% CI -18%…+14%) → inconclusive: directional (-2%), not significant
  - invalid as failures: full vs core diff +0% (95% CI -11%…+11%) → equivalent within ±10% (TOST, 90% CI inside the margin)
  - repetition 0 only: core vs baseline diff +0% (95% CI -15%…+15%) → inconclusive: no difference observed, but equivalence is not shown
  - repetition 0 only: full vs baseline diff -4% (95% CI -21%…+13%) → inconclusive: directional (-4%), not significant
  - repetition 0 only: full vs core diff -4% (95% CI -17%…+9%) → inconclusive: directional (-4%), not significant
  - unclustered (runs as independent; for comparison only): core vs baseline diff -2% (95% CI -13%…+8%), n=48 runs
  - unclustered (runs as independent; for comparison only): full vs baseline diff -4% (95% CI -16%…+7%), n=48 runs
  - unclustered (runs as independent; for comparison only): full vs core diff -2% (95% CI -9%…+4%), n=48 runs

_Equal observed rates are not evidence of equivalence: equivalence is claimed only when the 90% interval lies within ±10 points (TOST). Pilots (n<10) are never called significant._

by category (successes/valid runs): bugfix full=35/41, core=35/40, baseline=37/40; feature baseline=2/2, core=2/2, full=2/2; regression full=4/4, core=4/4, baseline=3/4; security baseline=2/2, full=2/2, core=2/2
