# Option A results: plain Claude Code vs repo-ai Core vs repo-ai Full (v0.7.5)

**Experiment:** `20261021-001148-ee60`. Pre-registered in docs/PREREGISTRATION.md (Amendments 1 and 2),
and run blind.

**Raw evidence:** `option-a-v0.7.5/` (`experiment.json`, `runs.jsonl`, the runner's own `report.md`,
`runner.log`, SHA256SUMS). The owner's lab store keeps a read-only copy.

**Authorization:** the owner authorized up to $40 for this experiment only.

## Bottom line

**Inconclusive. This experiment gives no evidence that repo-ai improves Claude Code's coding correctness.**
- **Success:** the observed success rates are slightly *lower* with repo-ai: −2 points for Core and −4 for
  Full against plain Claude. No comparison is close to significant (Holm-adjusted p = 1.0 for all three).
- **Interval width:** the intervals are wide (about ±15 points). Neither a gain nor a loss of roughly 10–15
  points is ruled out.
- **No equivalence claim:** no primary 90% interval lies inside ±10 points, so equivalence is not shown
  either.
- **Strongest secondary signal: Full costs more** (exploratory; see Efficiency).
- **One clear harm, with a known cause:** repo-ai's generated guidance steered agents to lint rather than run
  the test suite on one task.

## What ran

| | Plain Claude | repo-ai Core | repo-ai Full | Total |
|---|---|---|---|---|
| Planned / attempted | 50 / 50 | 50 / 50 | 50 / 50 | 150 / 150 |
| Valid | 48 | 48 | 49 | 145 |
| Success (valid runs) | 44 | 43 | 43 | 130 |
| Failure: hidden test failed | 4 | 3 | 4 | 11 |
| Failure: regression (visible tests broken) | 0 | 2 | 2 | 4 |
| Invalid: contamination flag (see below) | 2 | 2 | 1 | 5 |
| Invalid: isolation, error, crash, cancelled | 0 | 0 | 0 | 0 |
| Stopped by the cost cap / turn limit / timeout | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 |
| Not attempted (budget stop) | 0 | 0 | 0 | 0 |

**Run integrity:**
- **Pinning:** every run used `claude-sonnet-5-5` on Claude Code 2.1.304, and repo-ai 0.7.5 throughout.
- **Grading and loading:** every run was graded in podman. Every arm loaded the same two built-in plugins and
  no MCP servers. There were no isolation problems.
- **Stops:** no stopping rule fired: no budget stop, a 3% invalid rate, and no version change. All 150
  reservations closed.

**Cap and limit frequency (checked per arm, not assumed equal):** zero cost-cap hits, zero turn-limit hits
and zero timeouts in every arm.
- The most expensive run cost $0.33 against the $0.75 cap.
- The largest single call cost about $0.072.
- One plain-Claude run reported 34 turns while staying under `--max-turns 30` (subtype `success`). Claude
  Code's reported `num_turns` evidently counts differently from the limit it enforces.

**Cost:** $21.5482 estimated (Claude Code's `total_cost_usd`, not reconciled with billing), of the $40
authorized. Cumulative estimated live spend across all experiments is $25.90.

**Invalid attempts (5, all oss-tl-001):**
- **Why flagged:** the contamination check flags a workspace file that is byte-identical to a hidden test.
  This task's hidden test differs from the visible `tests/test_misc.py` in only three numeric constants.
- **Why it's a false positive:** a correct fix that updates the existing test naturally produces the
  upstream file. The recorded commands show no access outside the workspace, and the flag hit every arm.
- **Handling:** as pre-registered, these runs are excluded from the primary analysis. Full's one valid
  oss-tl-001 run has no valid partner, so every comparison uses **24 tasks**.
- The pre-registered sensitivity analysis "invalid counted as failures" gives the same conclusions.

## Primary analysis (task-clustered, pre-registered)

Each task's two repetitions are averaged per arm. Interval: task-clustered Bonett–Price. Test: sign-flip
permutation, then Holm across the three comparisons.

| Comparison | Success | Difference | 95% CI | 90% CI | Permutation p | Holm p | Verdict |
|---|---|---|---|---|---|---|---|
| Core vs Plain | 90% vs 92% | −2.1 pts | −16.5 … +12.7 | −14.2 … +10.3 | 1.0 | 1.0 | inconclusive |
| Full vs Plain | 88% vs 92% | −4.2 pts | −19.8 … +12.1 | −17.2 … +9.5 | 0.75 | 1.0 | inconclusive |
| Full vs Core | 88% vs 90% | −2.1 pts | −13.2 … +9.4 | −11.4 … +7.6 | 1.0 | 1.0 | inconclusive |

**Per-arm success** (95% Wilson): Plain 92% (80–97%), Core 90% (78–96%), Full 88% (76–94%).

**Hidden tests:** the mean hidden-test pass fraction is 100% after rounding in every arm. The failures are
near-misses (0.91–0.99 of the hidden tests pass) or regressions of the visible suite.

**Pre-registered sensitivity analyses** (all agree):
- **Invalid counted as failures:** −2 / −2 / 0 points, all inconclusive. Full vs Core is "equivalent within
  ±10" under this sensitivity only, not in the primary analysis.
- **Repetition 0 only:** 0 / −4 / −4 points, all inconclusive.
- **Unclustered** (for comparison only, not valid inference): −2 / −4 / −2 points.

## Where the arms differed (5 of 25 tasks)

| Task | Plain | Core | Full | Reading |
|---|---|---|---|---|
| oss-ct-002 | 2/2 | 0/2 (regression ×2) | 0/2 (regression ×2) | **repo-ai harmed.** Cause found (below). |
| oss-md-007 | 2/2 | 1/2 | 0/2 | **repo-ai harmed** (directional). One hidden test failed (0.992); cause not determined. |
| oss-md-005 | 1/2 | 2/2 | 2/2 | Plain failed one run (0.909); looks like run-to-run variation. |
| oss-md-009 | 1/2 | 2/2 | 2/2 | Plain failed one run (0.971); looks like run-to-run variation. |
| oss-tl-001 | invalid ×2 | invalid ×2 | 1 valid | Excluded (contamination false positive). |

**No difference:**
- 19 tasks: every arm succeeded in every run (a near-ceiling task set).
- oss-md-008: every arm failed every run (a floor task; 0.97–0.98 of the hidden tests pass).

**The discriminating tasks are few:** only 4 of 24 analysable tasks distinguish the arms. That is why the
intervals are so wide.

### Cause on oss-ct-002 (investigated from the recorded commands; results unchanged)

- **Plain Claude (both runs):**
  - ran the whole suite (`pytest tests -q`);
  - looked at the shared helper in `tests/__init__.py`;
  - updated a visible test, and passed.
- **Core and Full (all four runs):**
  - edited only `cachetools/__init__.py`;
  - checked with `ruff check .` and either `tests/test_rr.py` alone or ad-hoc `python -c`;
  - never ran the full suite, and broke a visible test elsewhere.
- **What repo-ai's always-loaded CLAUDE.md block says for this repository:**
  - it lists one command, the lint `ruff check .`;
  - it gives one learned project rule: "Run `ruff check .` before finishing a change that touches source
    code";
  - it gives **no test command**.
- **What the generated TESTING.md says:**
  - "No test command detected";
  - it lists `cachetools/` under "Source directories without nearby tests", which is wrong;
  - it gives the suite command only in a table.

The plausible mechanism is that the repo-ai arms followed the lint rule in place of verification. This rests
on one task, so it is not a general effect. Across all tasks, the share of runs that ran any test was
similar: Plain 23/50, Core 23/50, Full 18/50.

## Efficiency (secondary, exploratory; no multiplicity claims pre-registered)

| Per arm (50 runs) | Plain | Core | Full |
|---|---|---|---|
| Est. cost total (mean per run) | $6.90 ($0.138) | $7.08 ($0.142) | $7.57 ($0.151) |
| Output tokens | 158,480 | 153,398 | 170,855 |
| Cache-read tokens | 10.75 M | 10.08 M | 11.59 M |
| Cache-creation tokens | 1.06 M | 1.13 M | 1.17 M |
| Uncached input tokens | 752 | 684 | 756 |
| Turns / tool calls (total) | 516 / 466 | 480 / 429 | 513 / 463 |
| Wall time (total) | 2,459 s | 2,244 s | 2,406 s |
| Runs that ran any test / the whole suite | 23 / 17 | 23 / 17 | 18 / 14 |
| Runs with an unnecessary edit | 4 | 5 | 3 |
| Runs leaving execution artifacts | 11 | 13 | 13 |
| repo-ai context injected (mean) | 0 | ~267 tokens | ~267 tokens |
| Hook events / subagent calls / skills invoked | 0 / 0 / 0 | 504 / 0 / 0 | 748 / 0 / 0 |

**Paired, task-level comparisons** (median paired difference; Wilcoxon p unadjusted):
- **Full vs Plain, cost:** +$0.0148 per run (bootstrap 95% CI +$0.0063 … +$0.0195), lower in only 5 of 24
  tasks, p = 0.0048.
  - This is the strongest secondary signal: Full costs about 10% more.
  - It is exploratory: with 15 secondary tests, a Bonferroni threshold (0.0033) would not be met.
- **Full vs Core, cost:** +$0.0068 (CI +$0.0007 … +$0.0159), p = 0.056.
- **Core vs Plain:** no detectable difference in cost (+$0.003, p = 0.37), tokens, tool calls (−0.5,
  p = 0.27) or runtime.
- **Arm position:** mean cost was flat (1st $0.141, 2nd $0.146, 3rd $0.145).

**Full's extra features went unused:** no subagent was spawned and no skill was invoked in any of its 50 runs.
In practice Full was Core plus more hook activity, which explains its extra cost.

## Integrity notes

- **Blinding:** no pass/fail was shown during the run. One exception, for an integrity check: when
  oss-tl-001 was flagged, I read that run's commands and the task's test diff to rule out a hidden-test leak.
  This showed the agent's fix approach on that task, but no success outcome. Nothing was changed as a result.
- **Clock:** the system clock moved back about 3 hours during the run, consistent with a time-zone change.
  As a result, `finished` (2026-10-20T23:35) reads earlier than `started` (2026-10-21T00:11). Per-run
  durations use a monotonic clock and are unaffected.
- **Toolchain reads:** agents read and ran the host's Python toolchain (`~/.pyenv`, `/opt/homebrew`), which
  the sandbox allows by design. The suite and the lab were denied, and no run accessed them.
- **No changes after unblinding:** repo-ai was not changed after any outcome was seen. The sealed tasks'
  results stand as recorded.

## Limitations

- **Too few discriminating tasks:** 25 tasks, 24 analysable, and only 4 that discriminate. Detecting
  effects much under about 15–30 points needs a larger and harder task set.
- **Contamination:** public projects; memorization of upstream fixes is possible and equal across arms.
- **One model and one effort setting:** Sonnet 5.5 at medium. Results may differ for weaker models or
  harder tasks.
- **The sealed set has now been used:** any change motivated by these results (e.g. the oss-ct-002 cause)
  must be validated on new, untouched tasks.

## Recommendations for the next version (not implemented; awaiting the owner)

1. **Fix the testing guidance.**
   - Always put the project's test command in the CLAUDE.md block.
   - Never let a learned lint rule stand in for verification ("run the tests, then lint").
   - Fix the test-detection heuristics behind "No test command detected" and "no nearby tests" for root
     `tests/` layouts.
   - This is the one concrete harm the experiment found.
2. **Reconsider Full.** Its extras were never used on these tasks, and it cost about 10% more. Default to
   Core, or make Full's extras opt-in, until a benefit is shown.
3. **Fix the contamination detector.** Flag only text that appears in the hidden test but not in the visible
   one (not whole-file equality), and pre-register the change before reuse.
4. **Don't market a correctness benefit.** It remains **UNVERIFIED**, and the observed direction is slightly
   negative.
5. **Next experiment, if any:**
   - a new pre-registration on a fresh, larger and harder sealed set (far fewer ceiling tasks);
   - efficiency or regression rate as a co-primary outcome;
   - optionally a weaker model.
