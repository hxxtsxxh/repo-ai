# Coverage of the task-clustered success interval (v0.7.4)

**Question.** The 0.7.3 analysis put a Newcombe paired interval on
*fractional* task-level counts: each task's repetitions were averaged into
fractions of "both", "A only", "B only" and "neither". Is its frequentist
coverage right? If not, what should replace it?

**Answer.** No. With one run per task it undercovers: 85% for a nominal 95%
at 10 tasks, and 92% at 25. With two or more runs per task it is valid but
very conservative: a median coverage of about 99%, so repetitions buy almost
no precision. It is replaced by a task-clustered Bonett–Price adjusted Wald
interval, `stats.clustered_diff_ci`, which held nominal coverage in every
simulated condition.

Synthetic data only. No experiment outcome, sealed or otherwise, was read.

## The interval now used

Let d_t be task t's success difference averaged over its repetitions (in
[−1, 1]), for n tasks.

1. Add two pseudo-tasks, one with d = +1 and one with d = −1.
2. Estimate m = Σ d_t / (n + 2).
3. Compute the standard error SE = √(Σ_augmented (d − m)²) / (n + 2).
4. The interval is m ± z·SE, clipped to [−1, 1].

Properties:
- **One run per task:** this is exactly Bonett & Price (2012), "Adjusted Wald
  confidence interval for a difference of binomial proportions based on
  paired data" (J. Educ. Behav. Stat. 37:479–488). That method is among those
  recommended for small paired samples (Fagerland, Lydersen & Laake 2014).
- **Repetitions:** they help only as far as they reduce the between-task
  spread of d_t. A task never counts as more than one unit.
- **Agreeing tasks:** the pseudo-tasks keep the interval from collapsing when
  every task agrees. 25 all-success tasks give ±10.3 points.

The test is unchanged: an exact (≤ 20 tasks) or Monte Carlo sign-flip
permutation test on d_t. With one run per task it is the exact McNemar
test.

## Simulation design

**Scripts:** `benchmarks/statistics/coverage_explore.py` (candidates) and
`coverage_validate.py` (the confirmation run). They need numpy and are
analysis-only.

**Estimand:** the superpopulation mean E[p_B,t − p_A,t]. Tasks are treated
as a sample.

**Sizes:** 10, 25 and 50 tasks, crossed with 1, 2 or 3 runs per task, or a
mix of 1–3 runs (what a budget stop or excluded invalid attempts leave
behind).

**Data model "logit"** (864 cells):
- logit p_A,t = μ + u_t and logit p_B,t = μ + u_t + β + v_t;
- base success of about 0.10, 0.50, 0.80 or 0.95;
- effect β of 0, 0.5 or 1.5 on the logit scale;
- task-difficulty spread SD(u) of 0, 1.5 or 4 (4 means near-deterministic
  tasks);
- effect heterogeneity SD(v) of 0 or 1.

**Data model "mixture"** (72 cells): each task is one of five kinds:
- always solved by both;
- never solved;
- solved deterministically by B only;
- solved deterministically by A only;
- flaky.

There are six mixes, spanning ceiling, floor and mid-range, with null and
non-null effects.

**Runs:**
- **Exploration:** 2,000 simulations per cell. It compared six candidates:
  - the old method;
  - a task-level t interval;
  - Agresti–Min adjusted Wald with z and with t;
  - Bonett–Price adjusted Wald with z and with t.
- **Validation:** fresh seeds, 5,000 simulations per cell, 936 cells, at
  95% and 90% (the TOST level). Monte Carlo SE is about 0.3 points at 95%.

## Results (validation run; minimum and median over the data-model cells)

| Tasks | Runs per task | Old 95%: min / median | New 95%: min / median | Old 90%: min | New 90%: min | Mean width (95%), old → new |
|---|---|---|---|---|---|---|
| 10 | 1 | 0.852 / 0.952 | 0.959 / 0.996 | 0.807 | 0.902 | 0.568 → 0.653 |
| 10 | 2 | 0.933 / 0.994 | 0.983 / 0.999 | 0.887 | 0.948 | 0.579 → 0.575 |
| 10 | 3 | 0.943 / 0.999 | 0.987 / 1.000 | 0.898 | 0.950 | 0.582 → 0.546 |
| 10 | 1–3 (mixed) | 0.929 / 0.990 | 0.978 / 0.999 | 0.874 | 0.944 | 0.577 → 0.589 |
| 25 | 1 | 0.923 / 0.948 | 0.951 / 0.974 | 0.864 | 0.894 | 0.367 → 0.391 |
| **25** | **2** | **0.951 / 0.994** | **0.963 / 0.987** | **0.912** | **0.928** | **0.371 → 0.320** |
| 25 | 3 | 0.957 / 0.999 | 0.966 / 0.993 | 0.911 | 0.931 | 0.372 → 0.292 |
| 25 | 1–3 (mixed) | 0.944 / 0.989 | 0.962 / 0.986 | 0.899 | 0.922 | 0.370 → 0.333 |
| 50 | 1 | 0.929 / 0.949 | 0.947 / 0.962 | 0.874 | 0.897 | 0.260 → 0.269 |
| 50 | 2 | 0.954 / 0.993 | 0.957 / 0.974 | 0.907 | 0.913 | 0.262 → 0.210 |
| 50 | 3 | 0.961 / 0.999 | 0.958 / 0.980 | 0.913 | 0.911 | 0.262 → 0.187 |
| 50 | 1–3 (mixed) | 0.954 / 0.989 | 0.955 / 0.972 | 0.907 | 0.910 | 0.262 → 0.221 |

Bold: the Option A design (25 tasks × 2 repetitions).

**Across all 936 cells:**

| Method | Data model | Min coverage at 95% | Min coverage at 90% | Cells more than 1 point below nominal (95% / 90%) |
|---|---|---|---|---|
| New | logit | 0.949 | 0.894 | 0 / 0 |
| New | mixture | 0.947 | 0.897 | 0 / 0 |
| Old | logit | 0.852 | 0.807 | 50 / 77 |
| Old | mixture | 0.922 | 0.857 | 8 / 8 |

**Rejected in exploration:**
- **Task-level t interval:** it collapses when tasks agree. Minimum coverage
  was 0.47.
- **Agresti–Min adjusted Wald:** 0.915 at the ceiling (p_A ≈ 0.95,
  p_B ≈ 0.99, 50 tasks, one run).
- **Bonett–Price with a t quantile:** valid, but needlessly wider than with
  z.

## What it changes

- **Primary analysis:** `compare_clustered`, the pre-registered primary
  analysis, uses the new interval for every design, including one run per
  task. So the "repetition 0 only" sensitivity analysis uses it too.
- **Sensitivity analysis 3:** `compare_binary` (Newcombe and McNemar on
  runs) remains, explicitly labelled as the ordinary unclustered
  analysis.
- **Precision:** at the Option A design the interval is about 14% narrower
  than before, while keeping at least nominal coverage.
- **Remaining conservatism:** the median coverage of 0.987 shows that the
  interval is still conservative when most tasks are deterministic.
