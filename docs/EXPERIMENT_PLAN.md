# Proposed live experiments

> **Next (0.7.6):** a fresh, harder sealed set and a pre-registered comparison on it,
> docs/SEALED_V2.md and docs/PREREGISTRATION-v2.md. Not run; it awaits authorization.
>
> **Option A was run on 2026-10-21** (benchmarks/results/coding-option-a-v0.7.5.md).
> - **Result:** inconclusive. Success was 92% for plain Claude, 90% for Core and 88% for Full; no
>   comparison was significant (Holm p = 1.0), and equivalence was not shown.
> - **Cost:** Full cost about 10% more (exploratory).
> - **Sealed set:** the `final` split is now used. Options B and C would need a fresh sealed set and a new
>   pre-registration.

> **Updated after the v0.7.3 preflight.** Option A is pre-registered in
> docs/PREREGISTRATION.md, which supersedes the details below wherever they
> differ. Three corrections:
> 1. **Repetitions are not independent tasks.** The analysis is
>    task-clustered, so Option A has 25 analysis units, not 50. Its
>    detectable effect is about 29 points, not 21.
> 2. **The $0.50 per-run cap may be too low** for real repositories. The cap
>    and the turn limit are now set from a 12-run calibration on tasks
>    outside the sealed set, by a rule fixed in advance.
> 3. **Model and effort are pinned** (`claude-sonnet-5-5`, `medium`), and so
>    is the Claude Code version (auto-update disabled; a version change
>    stops the run).
>
> **Corrected in v0.7.4** (PREREGISTRATION.md, Amendment 1):
> - **The hard caps below were runs × C.** The runner reserves
>   R = 1.25 × C per pending run (more if calibration shows large single
>   calls), so the budget that guarantees completion is **runs × R**.
>   Runs × C stops before the last task when runs cost their full cap.
> - **The success interval** is now a task-clustered Bonett–Price interval
>   with simulation-verified coverage (docs/STATISTICS_COVERAGE.md).

Nothing in this file has been run. Each experiment needs the owner's explicit
approval of the experiment and its maximum spend. The original pilot
authorization ($10, $3.08 used) does not cover these.

**Common setup:**
- **Tasks:** the sealed `final` split. 25 re-injected upstream bugs in six
  real open-source projects (benchmarks/tasks/README.md). No model run has
  used them.
- **Client:** Claude Code headless from the dedicated eval config, with
  sandboxed grading, settings preflight and per-run isolation checks. Every
  arm gets the same prompt, model, effort, 30 turns and timeout.
- **Model:** Sonnet (the pilot model). Haiku 4.5 is cheaper, and a weaker
  model may also avoid the ceiling effect the pilot hit. It would answer a
  different question ("does repo-ai help a smaller model?").
- **Cost:**
  - The pilot averaged **$0.085 per run** on the small synthetic repositories.
  - These repositories are larger, so we expect **$0.10–$0.25 per run**. That
    is an estimate, not a measurement.
  - Every run is capped at **$0.50** (`--max-cost-per-run`).
  - The guaranteed-completion budget below is runs × R (R = 1.25 × cap by
    default). The experiment refuses to start a task whose arms'
    reservations might not fit.
- **Statistics:**
  - Task-clustered paired analysis of success: a sign-flip permutation test
    (exact McNemar with one run per task) and a Bonett–Price 95% interval.
  - Equivalence only by TOST within ±10 points.
  - Ceiling and floor flags.
  - Paired Wilcoxon tests for tokens, cache reads, cost, tool calls and
    runtime.
- **Detectable effect:** 80% power at α = 0.05, assuming 30% of pairs are
  discordant (`stats.mcnemar_detectable_effect`).

## Option A (recommended): does repo-ai help, and is Full better than Core?

```sh
repo-ai eval coding --split final --compare baseline,core,full --repeat 2 --seed 0 \
    --model claude-sonnet-5-5 --effort medium --max-turns 30 --timeout 1800 \
    --max-cost-per-run 0.75 --max-cost-usd 40 --blind   # limits: PREREGISTRATION.md Amendment 2
```

| Runs | Expected cost (calibrated) | Proposed budget | Guaranteed-completion budget | Pairs per comparison | Detectable success difference |
|---|---|---|---|---|---|
| 150 (25 tasks × 3 arms × 2) | about $16 at the calibration mean, about $34 at the planning upper estimate | **$40** (awaiting authorization) | 150 × R = **$140.63** | 25 tasks (50 runs) | about 29 points |

With $40 a budget stop is possible if sealed-task runs average more than
about $0.25. It stops between tasks, never between a task's arms.

A smaller budget is allowed: the pre-registered recommended budget is
147 × u + 3 × R (PREREGISTRATION.md §9). With it, a budget stop is
possible and is reported as such.

This answers three paired comparisons: Core vs plain, Full vs plain, and Full
vs Core. Effects smaller than about 30 points will most likely show as "inconclusive",
which is the honest result for that sample.

## Option B: feature attribution screen (after A)

```sh
repo-ai eval coding --split final --compare ablations --model claude-sonnet-5-5 --effort medium \
    --blind --max-cost-per-run <C> --max-turns <T> --max-cost-usd <B>
```

| Runs | Expected cost | Guaranteed-completion budget | Pairs per ablation | Detectable difference |
|---|---|---|---|---|
| 175 (25 tasks × 7 arms) | $18–$44 | **175 × R** ($109.38 at C = $0.50) | 25 | about 29 points |

The arms are Full and Full without each of:
- context packets;
- learned project rules;
- generated skills;
- approved external skills (a no-op unless skills are installed);
- outcome-aware retrieval;
- subagents and orchestration.

This is a screen: it can flag a feature that clearly helps or hurts, not
rank small effects.

**Known limitation:** in a fresh, single-session workspace the outcome prior
has no history. The `outcomes` ablation therefore measures only recording
overhead, not outcome-aware ranking. A meaningful test needs warm-started
episodes, which this plan does not include.

## Option C: minimal confirmatory run

```sh
repo-ai eval coding --split final --compare baseline,full --repeat 2 \
    --model claude-sonnet-5-5 --effort medium --blind --max-cost-per-run <C> --max-turns <T> \
    --max-cost-usd <B>
```

| Runs | Expected cost | Guaranteed-completion budget | Pairs | Detectable difference |
|---|---|---|---|---|
| 100 | $10–$40 | **100 × R** | 25 tasks (50 runs) | about 29 points |

## Limitations (for all options)

- **Sample size.** 25 tasks is small. A 10-point improvement would need
  about 155–235 pairs to detect, assuming 20–30% of pairs are discordant. A larger sealed task set is the most valuable
  next investment.
- **Contamination.** These projects are public, and some fixes predate the
  model's training data. Re-injecting a bug into a newer snapshot reduces
  the effect of memorization but does not remove it.
- **One language** (Python) and **one model** per run. Results do not
  transfer automatically.
- **Claude Code version** is recorded per run. Comparisons across versions
  are not paired.
- **Cost figures** are Claude Code's client-side estimates, not billing.

Until one of these runs completes, any coding-performance benefit of repo-ai
is **UNVERIFIED**.
