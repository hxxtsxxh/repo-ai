# Pre-registration: Option A (plain Claude Code vs repo-ai Core vs repo-ai Full)

**Status:** **run** on 2026-10-21 (experiment `20261021-001148-ee60`, 150/150 attempted, 145 valid). Result: inconclusive on every comparison; see `benchmarks/results/coding-option-a-v0.7.5.md`. Registered before any model call. This file, the schedule
(`benchmarks/preregistration/option-a-schedule.json`, SHA-256 below) and the
code are committed before any model call. Each change after registration is
recorded under "Amendments", with its date, *before* the main experiment
starts.

## 1. Question

Does repo-ai change Claude Code's ability to fix real bugs in real
repositories? Is the Full configuration better than Core?

## 2. Software and model (pinned)

- **repo-ai:** v0.7.5 [A2], installed from the release wheel. Experiments refuse
  to resume under a different protocol.
- **Claude Code:** 2.1.304. Auto-update is disabled for every run
  (`DISABLE_AUTOUPDATER=1`). A run reporting a different version is
  invalid and **stops the experiment** (§8).
- **Model:** `claude-sonnet-5-5`, set with `--model`. A run whose `system/init`
  reports a different model is invalid.
- **Effort:** `medium`, set with `--effort`. Identical for every arm.
- **Same for every arm:** the Claude command, settings file, tools,
  permissions, max turns, timeout and per-run cost cap. Verified offline:
  the argv is byte-identical across arms except for the per-run settings
  path.
- **Client config:** a dedicated, audited directory
  (`~/.local/share/repo-ai/claude-eval`).
  - No user skills, agents, commands or plugins.
  - No MCP servers (`--strict-mcp-config`).
  - Only Claude Code's built-in `cc-plugin-*` plugins, which are identical
    in every arm and recorded per run.

## 3. Tasks

The 25 tasks of the sealed `final` split:

| Base | Tasks |
|---|---|
| oss-markdown | oss-md-001 to oss-md-010 |
| oss-pyflakes | oss-pf-001 to oss-pf-004 |
| oss-cachetools | oss-ct-001 to oss-ct-004 |
| oss-simplejson | oss-sj-001 to oss-sj-003 |
| oss-bottle | oss-bt-001 to oss-bt-003 |
| oss-tomli | oss-tl-001 |

- **Construction:** re-injected upstream bugs, selected by one fixed rule
  (benchmarks/tasks/README.md, oss-manifest.json).
- **Oracles:** all 25 valid in the sandbox (CI too).
- **Prior use:**
  - no live model run has used these tasks;
  - two were exercised with the deterministic fake client while the grader
    was being built;
  - all 25 had localization measured once (docs/RETRIEVAL.md);
  - no feature was tuned on them.

## 4. Arms

| Arm | Features |
|---|---|
| baseline | none: plain Claude Code |
| core | hooks, packet (CLAUDE.md block, curated skills, task packets), rules |
| full | core + generated skills, subagents, outcome recording, orchestration (skeptic), third-party skills |

No third-party skills are approved, so the `thirdparty` feature is inert:
Full means "Full without external skills". In a fresh single-session
workspace the outcome prior has no history, so `outcomes` contributes only
recording.

## 5. Design

- **Size:** 25 tasks × 3 arms × 2 repetitions = **150 runs**.
- **Order:** repetition 0 of every task (sorted by id), then repetition 1.
- **Arm order per task and repetition:** the balanced, seeded schedule
  (seed 0).
  - Each of the 6 permutations is used 8–9 times.
  - Each arm goes first 16–17 times.
  - A task's two repetitions use different orders.
  - Schedule SHA-256:
    `876a5f2308315c2fd9b71283ffd69b50fb17662e509aef2de6dc850fe1541fd4`.
- **Every run:**
  - starts from a fresh workspace;
  - the agent can read and write only its own workspace;
  - hidden tests are never in the workspace;
  - grading happens in the sandbox on a copy;
  - environment credentials are never passed.
- **Blinding:** the experiment runs with `--blind`, so per-run pass/fail is
  not shown while it runs. No one looks at outcomes until it finishes or
  stops (§8).

## 6. Outcomes

**Primary:** task success per run (all hidden upstream regression tests
pass).

**Intention to treat:**
- runs stopped by the cost cap, the turn limit or the timeout are **valid
  failures**;
- invalid attempts (isolation, contamination, infrastructure error, crash)
  are excluded from the primary analysis, but every one is listed with its
  reason.

**Secondary (exploratory, no multiplicity claims):**
- cache-neutral token volume (fresh + cached + output);
- Claude-reported cost;
- tool calls, turns and runtime;
- regressions (other tests broken);
- unnecessary edits: files changed outside the task's gold files and tests,
  excluding untracked execution artifacts [A2];
- test runs by the agent (recorded Bash commands) [A2].

## 7. Analysis (fixed in advance; `repo_ai.stats`)

**Unit of analysis: the task.** A task's two repetitions are averaged per
arm. The 150 runs are never treated as independent.

**Primary comparisons:** Core vs baseline, Full vs baseline, Full vs Core,
each paired by task:
- the mean task-level difference in success rate;
- a 95% task-clustered Bonett–Price adjusted Wald interval on the
  task-level differences (`stats.clustered_diff_ci`; coverage verified in
  docs/STATISTICS_COVERAGE.md) [A1];
- an exact or Monte Carlo sign-flip permutation p-value on the task-level
  differences;
- Holm correction across the three comparisons.

**Decision rules:**
- **Improvement / regression:** Holm-adjusted p < 0.05 *and* a 95% interval
  that excludes 0.
- **Equivalence:** only if the 90% interval (same method) lies inside ±10
  points (TOST).
- **Inconclusive:** anything else. A ceiling or floor flag is attached when
  both arms are ≥ 95% (or ≤ 5%).

**Secondary metrics:** per-task means, then paired Wilcoxon signed-rank and a
seeded bootstrap interval for the median difference. Cost is also reported
by arm position, because prompt caching makes later runs of a task cheaper.

**Sensitivity analyses:**
1. invalid attempts counted as failures;
2. repetition 0 only;
3. the ordinary unclustered paired analysis, shown for comparison and
   labelled as such.

**Power:** with 25 tasks and about 30% discordant tasks, the detectable
difference at 80% power is about 29 points. Smaller true effects will most
likely be reported as inconclusive.

## 8. Stopping rules

1. **Budget.** Each run is reserved R = C + M (§9) [A1]. The runner never
   starts a task unless every remaining arm's reservation R fits the
   remaining budget.
   - Runs are charged their reported cost; a crashed run or one with no
     reported cost is charged R.
   - A run whose reported cost exceeds R stops the experiment (the
     reservation's assumption failed).
   - A budget stop is reported with its "not attempted" counts.
   - The analysis then uses the attempted task-repetitions.
2. **Claude Code version change.** Automatic stop. This experiment is not
   resumed; a new one is registered.
3. **More than 20% invalid attempts** after at least 9 attempts. Automatic
   stop, investigate, register a new experiment.
4. **No interim efficacy looks** (blind mode).
5. **Operational interruptions** (Ctrl-C, a crash, a reboot):
   - `--resume <id>` continues the same experiment under the same protocol;
   - attempts that already finished are never rerun;
   - a crashed attempt is charged its full cap and rerun once.

## 9. Limits (set by the calibration run, with a rule fixed now)

The calibration (§10) runs first, on 4 tasks outside the sealed set.

**Per-run cost cap C:** the smallest of $0.75, $1.00, $1.50 and $2.00 that is
at least 2 × the largest per-arm calibration p90 cost, and above every
calibration run's cost.

**Max turns T:**
- 30 if no calibration run used more than 24 turns or hit the limit;
- otherwise 50 if none used more than 40;
- otherwise 80.

**Timeout:** 1,800 s, raised to 2 × the longest calibration wall time if that
is higher.

**Reservation margin M** [A1]: Claude Code checks `--max-budget-usd` between
API calls, so a run can exceed C by up to one call.
- M = max(0.25 × C, 2 × the largest single-call cost estimated in
  calibration, rounded up to $0.05).
- R = C + M is passed as `--reserve-per-run` whenever it exceeds 1.25 × C.

**Total budget B** [A1]: the owner's approved figure.
- **Guaranteed completion:** B = 150 × R, provided no run costs more than R
  (§8.1) and no attempt crashes. Each crashed attempt is rerun once and
  needs one more R.
- The 0.7.3 text said "150 × C", which was wrong. Runs costing exactly C
  would stop before the last task.
- **Recommended budget:** B_rec = 147 × u + 3 × R, rounded up to $5. Here
  u = 2 × the largest per-arm mean calibration cost, but at least the
  overall calibration p90 and at most R. The factor 2 allows for the sealed
  tasks being harder than the calibration tasks, which are 1–2 line fixes.
- A smaller B is allowed, with §8.1 applying.

The values chosen are recorded as Amendment 2 before the main run (done: see below).

## 10. Calibration (outside the sealed set)

**Tasks:** cal-md-001, cal-pf-001, cal-sj-001 and cal-bt-001.
- They come from the same six projects: each is the newest fix that was
  outside the final selection rule (a fix of 1–2 lines, or excluded for
  testing internals).
- Their oracles are valid in the sandbox.

**Design:** 4 tasks × 3 arms × 1 repetition = 12 runs, with a generous cap
($1.50) and turn limit (60), so the uncapped cost and turn distributions are
observed. Success on these tasks is not analysed and informs nothing but the
§9 limits.

**Calibration budget** [A1]: $24. That is at least 12 × R = 12 × $1.875 =
$22.50, so calibration is guaranteed to complete (§9).

**Reported per run:** cost, turns, wall time, timeout, cap and turn-limit
hits, validity, and the estimated largest single-call cost (for M).

## Amendments

### Amendment 1 (2026-10-20, before calibration and before any main-run call)

Made under the owner's instruction to reconcile the budget rule with the
runner and to verify the interval's coverage. The sealed task selection,
schedule (SHA-256 unchanged), arms, model, effort, outcomes, decision rules
and stopping rules 2–5 are unchanged. No live outcome was inspected.

1. **Budget formula (§8.1, §9, §10).**
   - Was: "B = 150 × C (guaranteed completion)".
   - Now: B = 150 × R, with R = C + M.
   - The runner reserves R (default 1.25 × C) per pending run, so 150 × C
     cannot guarantee completion. Regression tests:
     `tests/test_coding_lab.py::test_planned_runs_x_cap_is_not_a_completion_budget`
     and the near-cap and property tests after it.
   - The margin M now has a rule.
   - A run above R stops the experiment.
   - The recommended (smaller) budget has a formula fixed before
     calibration.
2. **Success interval (§7).**
   - Was: "a 95% Newcombe interval on task-level fractional counts".
   - Now: a task-clustered Bonett–Price adjusted Wald interval.
   - Simulation showed the old interval undercovered with one run per task
     (85% at 10 tasks) and was over-conservative with two or more (median
     about 99%).
   - The new interval held nominal coverage in all 936 simulated conditions
     at 95% and at 90% (docs/STATISTICS_COVERAGE.md).
   - The test (sign-flip), Holm correction and decision rules are
     unchanged.
3. **Software (§2):** repo-ai v0.7.4, which contains 1 and 2.

### Amendment 2 (2026-10-20, after calibration, before any main-run call)

Records the limits that the §9 rules produce from the calibration, plus one
measurement correction and two integrity fixes found during it. The sealed
task selection, schedule (SHA-256
`876a5f2308315c2fd9b71283ffd69b50fb17662e509aef2de6dc850fe1541fd4`, unchanged),
arms, seed, model, effort, primary outcome, analysis, decision rules,
stopping rules and blinding are unchanged. No sealed task was used. Nothing
was tuned on calibration success, which was 12/12 in every arm.

1. **Calibration.**
   - Experiment `20261020-222831-1ee7`: 12/12 valid runs, $1.2694 estimated
     cost (Claude Code estimates, not billing).
   - No cap, turn or timeout hits.
   - Largest run $0.1307; largest single call about $0.0475.
   - Details and raw rows: `benchmarks/results/coding-calibration-v0.7.4.md`.
2. **Limits by the §9 rules,** computed by `coding_lab.preregistered_limits`:
   - **C** = $0.75 per run;
   - **R** = $0.9375 (the default margin, 0.25 × C);
   - **T** = 30 turns;
   - **timeout** = 1,800 s.
3. **Budget.**
   - Proposed B = $40, the recommended budget: 147 × $0.2237 + 3 × R =
     $35.70, rounded up to $5.
   - $40 does **not** guarantee completion. The no-crash
     guaranteed-completion budget is 150 × R = $140.63.
   - Under §8.1 a budget stop happens only between tasks, so a task's three
     arms are always compared together.
   - Repetition 0 of all 25 tasks runs before repetition 1.
   - B becomes final only with the owner's authorization.
4. **Measurement correction (secondary metric).**
   - Bytecode and test-tool caches are execution artifacts, not edits. The
     0.7.4 "unnecessary edits" counted untracked `__pycache__/*.pyc` left by
     running Python, which penalised arms whose agents ran the tests.
   - Now excluded only when untracked and only for interpreter or tool cache
     names (`__pycache__/<module>.<tag>.pyc`, `.pytest_cache/`,
     `.mypy_cache/`, `.ruff_cache/`, `.hypothesis/`, `.coverage*`).
   - Tracked files, module-level `.pyc` files and everything else still count
     as edits.
5. **Grading integrity.**
   - Hidden tests run on a copy without `__pycache__`, so they always import
     the agent's source.
   - Planted bytecode whose header matches the source's mtime and size could
     otherwise have been imported instead.
   - The success criterion (all hidden upstream tests pass) is unchanged; it
     is now enforced on source.
6. **Instrumentation.**
   - Each run records its Bash commands and a count of test runs
     (exploratory).
   - Experiments also record the repo-ai version, and a resume under a
     different build is refused.
7. **Software (§2):** repo-ai v0.7.5, which contains 4–6.

**Main experiment command** (runs only after the owner authorizes B):

```sh
repo-ai eval coding --split final --compare baseline,core,full --repeat 2 --seed 0 \
  --model claude-sonnet-5-5 --effort medium --max-turns 30 --timeout 1800 \
  --max-cost-per-run 0.75 --max-cost-usd 40 --blind
```

