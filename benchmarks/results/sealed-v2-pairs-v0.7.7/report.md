## Coding experiment 20261021-103834-40bc
model: claude-sonnet-5-5, max turns 60, seed 0; runs: 50 valid of 50; charged $7.88 of $20.00 (Claude Code estimates, not billing)

| Metric | Plain Claude | repo-ai Core |
|---|---|---|
| Task success rate | 92% | 84% |
| Correct with no regression | 92% | 84% |
| Regression-free | 100% | 96% |
| Hidden tests passed (mean fraction) | 96% | 96% |
| Average tokens | 263,048 | 260,628 |
| Median runtime (s) | 48.2 | 48.8 |
| Median tool calls | 11 | 11 |
| Median test runs by the agent | 0 | 0 |
| Estimated model cost (mean $) | $0.158 | $0.157 |
| Regression rate | 0% | 4% |
| Sample size (valid runs) | 25 | 25 |
| Median time to first edit (s) | 29.25 | 23.55 |
| repo-ai context injected (tokens, est.) | 0.0 | 273.04 |
| repo-ai setup time (s) | 0.0 | 1.933 |
| Cost p50 ($) | 0.1607 | 0.1386 |
| Cost p90 ($) | 0.185 | 0.2316 |
| Cost max ($) | 0.4174 | 0.3583 |
| Runs stopped by the cost cap | 0 | 0 |
| Turns p90 | 18 | 19 |
| Turns max | 36 | 28 |
| Runs stopped by max turns | 0 | 0 |
| Timeouts | 0 | 0 |
| Longest run (s) | 156.1 | 163.9 |
| Largest single API call ($, est.) | 0.062 | 0.0756 |

Every attempt (budget, turn and time limits count as failures; nothing is dropped):
| | Plain Claude | repo-ai Core |
|---|---|---|
| attempts | 25 | 25 |
| valid | 25 | 25 |
| success | 23 | 21 |
| failure | 2 | 4 |
| stopped by cost cap | 0 | 0 |
| stopped by max turns | 0 | 0 |
| timed out | 0 | 0 |
| invalid isolation | 0 | 0 |
| invalid contamination | 0 | 0 |
| errors | 0 | 0 |
| crashed | 0 | 0 |
| cancelled | 0 | 0 |
| not attempted (of 25 planned) | 0 | 0 |

Success rates: Plain Claude 92% (95% Wilson 75%–98%); repo-ai Core 84% (95% Wilson 65%–94%)

- **core vs baseline**: success 84% vs 92%, diff -8% (95% CI -22%…+7%, task-clustered Bonett-Price; permutation p=0.5, Holm p=0.5; 25 tasks, 25 paired runs) → **inconclusive: directional (-8%), not significant**; regressions: v2-dns-005, v2-sg-007
  - tokens: median paired diff -16025 (95% CI -59508…+36257; lower in 14/25; Wilcoxon p=0.615)
  - cache_read_tokens: median paired diff -17373 (95% CI -53398…+35199; lower in 14/25; Wilcoxon p=0.615)
  - cost_usd: median paired diff +0.0036 (95% CI -0.0173…+0.0088; lower in 11/25; Wilcoxon p=0.8119)
  - tool_calls: median paired diff +0 (95% CI -3…+3; lower in 12/25; Wilcoxon p=0.9345)
  - wall_s: median paired diff +4 (95% CI -4.7…+7.8; lower in 9/25; Wilcoxon p=0.4146)
- correct with no regression (hidden tests and visible suite pass), **core vs baseline**: 84% vs 92%, diff -8% (95% CI -22%…+7%; permutation p=0.5, Holm p=0.5; 25 tasks) → **inconclusive: directional (-8%), not significant**
- regression-free (visible suite passes), **core vs baseline**: 96% vs 100%, diff -4% (95% CI -16%…+9%; permutation p=1.0, Holm p=1.0; 25 tasks) → **inconclusive: directional (-4%), not significant; ceiling effect: both arms ≥95%**

Sensitivity analyses (pre-registered):
  - invalid as failures: core vs baseline diff -8% (95% CI -22%…+7%) → inconclusive: directional (-8%), not significant
  - repetition 0 only: core vs baseline diff -8% (95% CI -22%…+7%) → inconclusive: directional (-8%), not significant
  - content match as invalid: core vs baseline diff -8% (95% CI -22%…+7%) → inconclusive: directional (-8%), not significant
  - correct no regression invalid as failures: core vs baseline diff -8% (95% CI -22%…+7%) → inconclusive: directional (-8%), not significant

_Equal observed rates are not evidence of equivalence: equivalence is claimed only when the 90% interval lies within ±10 points (TOST). Pilots (n<10) are never called significant._

by category (successes/valid runs): bugfix core=21/25, baseline=23/25
