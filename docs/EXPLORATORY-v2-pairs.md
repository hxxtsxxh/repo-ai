# Exploratory, budget-limited: repo-ai Core vs Plain on sealed-v2

**Status:** registered on 2026-10-21. Authorized by the owner the same day
(this exact command, $20 maximum) and **run**: experiment
`20261021-103834-40bc`, 50/50 valid, $7.88 estimated. Results:
`benchmarks/results/coding-sealed-v2-pairs-v0.7.7.md`. No amendment was made.

**Relation to other registrations:**
- This is a separate, **explicitly exploratory** experiment. It does not
  replace `PREREGISTRATION-v2.md` (150 runs, three arms), which stays as
  registered.
- No result from it is a confirmatory claim.
- **Running it ends sealed-v2's untouched status.** Once any model has run on
  these tasks and its outcomes have been read, sealed-v2 is no longer fresh
  evidence. `PREREGISTRATION-v2` could then run only as a replication on
  seen tasks, never as a confirmatory test on unseen ones.
- A later confirmatory study would need a new sealed set built by the same
  fixed rule. Nothing in repo-ai may be tuned on this experiment's outcomes
  and then judged on sealed-v2.
- The old 25-task `final` set (analysed in Option A) is not used and supports
  no claim about 0.7.6.

The schedule (`benchmarks/preregistration/sealed-v2-pairs-schedule.json`,
SHA-256 below) and this file are committed before any model call. Changes
before the first run are recorded as dated amendments at the end.

## 1. Question

On fresh, harder, real-repository tasks, does repo-ai Core (the default for
new installs since 0.7.6) change how often Claude Code produces a **correct
fix without breaking the rest of the suite**? And at what cost in tokens,
dollars, time and tool calls?

The priorities, in order:
1. correctness;
2. avoiding regressions;
3. token and dollar efficiency;
4. runtime and tool-call efficiency.

**Full is omitted.** Option A showed no benefit from its extra features, and
it cost about 10% more.

## 2. Software and model (pinned)

**repo-ai:** v0.7.7, from the release.
- Its only changes from v0.7.6 are in the evaluation runner and its analysis
  (§10): task order, a missing-toolchain refusal, outcome reporting, and the
  shared deny list.
- Everything the Core arm installs is byte-identical to 0.7.6. The one
  exception is the version string recorded in repo-ai's own metadata files.
- A resume under another build is refused.

**Claude Code:** 2.1.304, as installed. Auto-update is off for agent runs, and
a version change stops the experiment.

**Model and effort:** `claude-sonnet-5-5`, effort `medium`, for both arms. A
run reporting another model is invalid.

**Isolation:**
- the dedicated, audited eval config directory;
- no MCP servers;
- only the built-in `cc-plugin-*` plugins;
- argv identical across arms apart from the per-run settings path.

## 3. Tasks and order

**Tasks:** all 25 sealed-v2 tasks (`docs/SEALED_V2.md`), with contents and
grading unchanged.

**Order:** fixed in advance by `--task-order interleave --seed 0`, using
`coding_lab.interleave_by_base`. It is round-robin across the eight projects,
with a seeded project order in each round and a seeded task order within each
project. Every project gets its first task before any project gets its second.
In every prefix, no project is more than one task ahead of a project that
still has tasks.

| # | Task | # | Task | # | Task | # | Task | # | Task |
|---|---|---|---|---|---|---|---|---|---|
| 1 | v2-dns-004 | 6 | v2-lk-002 | 11 | v2-sg-005 | 16 | v2-dns-003 | 21 | v2-sg-008 |
| 2 | v2-ac-001 | 7 | v2-sg-004 | 12 | v2-lk-001 | 17 | v2-ac-004 | 22 | v2-sg-003 |
| 3 | v2-mi-001 | 8 | v2-te-001 | 13 | v2-ac-003 | 18 | v2-sg-006 | 23 | v2-dns-006 |
| 4 | v2-asn-001 | 9 | v2-dns-005 | 14 | v2-sg-007 | 19 | v2-dns-002 | 24 | v2-sg-002 |
| 5 | v2-mk-001 | 10 | v2-asn-002 | 15 | v2-ac-002 | 20 | v2-dns-001 | 25 | v2-sg-001 |

**Coverage by position:**
- **1–8:** all eight projects.
- **9–13:** the second task of the five projects that have one.
- **14–19:** asn1crypto completes; sqlglot and dnspython continue.
- **20–25:** sqlglot and dnspython only.

So an early stop drops the *later* sqlglot and dnspython tasks first. That
reduces the suite's sqlglot imbalance rather than worsening it.

**Arm order within each task:** it alternates by position (`arm_order` with
two arms), so in every prefix each arm goes first within ±1 of the other.
Prompt caching can make a task's second run cheaper, which makes this balance
matter for cost.

**Schedule SHA-256:**
`bb90d60ef963f8c09b5a8d73b37616f10ce51dde17c5cf31fe47917ad7334184`
(the `schedule` list, `json.dumps(..., sort_keys=True)`). A test checks that
the runner reproduces it exactly.

## 4. Arms

| Arm | Features | Product equivalent |
|---|---|---|
| baseline | none: plain Claude Code | — |
| core | hooks, packet (CLAUDE.md block with the Verify line, curated skills, task packets), learned rules | `feature_set = "core"` |

Both arms get identical tools, permissions (`dontAsk`, same allow and deny
lists), OS sandbox, workspaces, prompts, limits and grading.

## 5. Design

- **Size:** 25 tasks × 2 arms × 1 repetition = **50 planned runs**. Each task
  is one analysis unit.
- **Pairs stay together:** a task starts only if both of its runs'
  reservations fit the remaining budget, so a budget stop never splits a
  task's arms.
  - A mid-task stop by another rule (§9) can leave a task with one arm. That
    task is listed as "not compared", never dropped silently.
- **Workspaces:**
  - each run gets a fresh workspace;
  - the suite, the lab home and `benchmarks/authoring` are denied to Bash (OS
    sandbox) and to the file tools (permission rules);
  - hidden tests are never in the workspace;
  - grading runs in the podman sandbox, on a copy without `__pycache__`.
- **Blind:** `--blind`. Progress shows only "done", validity and spend. No
  outcome is read (by the owner or by Claude) until the experiment finishes
  or stops.

## 6. Limits and money

**Per run:** 60 max turns, 1,800 s timeout, cap C = **$1.50**
(`--max-budget-usd`).

**Reservation:** R = 1.25 × C = **$1.875** per run, so **$3.75** per task.
- Claude Code checks its cap between API calls, so a run can end one call past
  it. The reservation covers that call; the largest single call seen so far is
  about $0.07.

**The gate:**
- A task starts only if at least $3.75 of the budget remains.
- Spending is charged at each run's reported cost.
- A run that reports no cost, or that crashes, is charged R.
- A run reporting more than R stops the experiment.
- So the charged total never exceeds B as long as no run exceeds R.

**Completion:** with B = $20, the 25th task starts only if at most $16.25 has
been charged after 24 tasks. All 25 tasks therefore complete when the mean
cost per run is at most (B − 3.75) / 48 = **$0.339**.

**Worst case:** if every run cost its full reservation, $20 would complete
⌊20 / 3.75⌋ = **5 tasks** (10 runs, $18.75). Completing all 50 runs is
*guaranteed* only at 50 × R = **$93.75**, which is not proposed.

**Costs are estimates:** they are Claude Code's client-side estimates
(`total_cost_usd`). The $20 limit is enforced against those estimates. It is
**not** an independent guarantee on provider billing.

**No cost measurement exists for sealed-v2:** any measurement would have
meant running it.
- **Reference:** Option A averaged $0.144 per run (maximum $0.33) on easier
  tasks.
- **Estimates:** sealed-v2 tasks change more files in larger repositories.
  The table assumes 1× to 3× that mean.

**Tasks completed (of 25), and charged total, by budget and mean cost per run:**

| Mean cost per run | $10 | $15 | $20 |
|---|---|---|---|
| $0.144 (Option A mean) | 22 ($6.34) | 25 ($7.20) | 25 ($7.20) |
| $0.22 (1.5×) | 15 ($6.60) | 25 ($11.00) | 25 ($11.00) |
| $0.29 (2×) | 11 ($6.38) | 20 ($11.60) | 25 ($14.50) |
| $0.43 (3×) | 8 ($6.88) | 14 ($12.04) | 19 ($16.34) |
| $1.875 (every run at R) | 2 ($7.50) | 4 ($15.00) | 5 ($18.75) |

**Runtime estimate:** Option A averaged about 48 s of agent time per run. With
harder tasks and sandboxed grading of the larger suites, 50 runs should take
roughly 1.5–4 hours.

## 7. Outcomes

**Primary (exploratory):** *correct with no regression*. The hidden upstream
tests pass **and** the base's runnable visible suite, with the updated test
files installed, still passes. This is success as `docs/SEALED_V2.md` defines
it. The analysis computes it as `success and not regression` from the two
grading results the runner records. The grader is unchanged (Amendment 1 of
PREREGISTRATION-v2 explains why).

**Secondary (exploratory):**
1. **Hidden-test success:** the runner's `success` field; all hidden tests
   pass. This is Option A's definition.
2. **Regression-free:** the visible suite passes.
3. **Efficiency, paired per task:**
   - estimated cost;
   - tokens (cache-neutral), cache reads, uncached input;
   - wall time, tool calls, turns;
   - test runs by the agent.
4. **Frequencies per arm, compared and never assumed equal:**
   - cost-cap hits, turn-limit hits and timeouts;
   - unnecessary edits (execution artifacts excluded);
   - abandoned runs.

**Mechanism check (descriptive):** does Core make the agent run tests more
often? The Verify line exists to make it do so. A difference in test runs
with no difference in correctness would itself be informative.

**Intention to treat:**
- Cap, turn-limit and timeout stops are valid failures.
- Invalid attempts are excluded from the primary analysis and listed with
  their reasons. They include isolation problems, proof of access to hidden
  material, infrastructure errors and crashes.
- Every attempt appears in the report's outcome table.

## 8. Analysis (`repo_ai.stats` and `coding_lab.summarize`, v0.7.7)

**Comparison:** Core vs Plain, paired by task. The task is the unit, with one
run per arm.

**Methods:**
- **Interval:** Bonett–Price 95%.
- **Test:** an exact sign-flip test, identical to exact McNemar with one run
  per arm.
- **Holm:** applied within each outcome. With one comparison per outcome it
  changes nothing.
- **Continuous metrics:** paired median differences with bootstrap 95%
  intervals and Wilcoxon p-values.

**Verdict labels** (all exploratory):
- *Better or worse:* p < 0.05 and the 95% interval excludes 0.
- *Equivalent:* the 90% interval lies inside ±10 points. The design is very
  unlikely to show this (below).
- *Otherwise:* inconclusive.

**A non-significant result is not evidence of no effect**, and it is never
reported as equivalence.

**Sensitivity analyses** (all in `summarize`, labelled in the report):
1. invalid attempts counted as failures, for both the primary outcome and
   hidden-test success;
2. runs with a workspace file identical to a hidden test treated as invalid
   (a diagnostic, not proof; new in 0.7.7, as PREREGISTRATION-v2 §8
   promised).

If the budget stops early, the analysis covers exactly the tasks reached, in
schedule order. Tasks not attempted are reported as such.

**Precision:** with one run per arm, only discordant tasks inform the
comparison, those where exactly one arm succeeds.
- At least 6 discordant tasks, all in one direction, are needed for p < 0.05.
- **80% power** (exact, α = 0.05), by tasks completed:

  | Tasks completed | Effect detectable at 80% power |
  |---|---|
  | 25 | about 30 points if the effect is concentrated in few tasks; about 40 if 50–60% of tasks are discordant |
  | 19 | about 40 points |
  | 13 or fewer | no realistic effect (power at most about 43% even for 40 points) |

- **Example 95% intervals with 25 tasks:**
  - 5 discordant tasks for Core and 2 for Plain: +12 points (−10 … +32);
  - 3 and 3: 0 points (−21 … +21);
  - 6 and 0: +24 points (+3 … +41), the smallest supported result.
- **Efficiency metrics are more sensitive than correctness**: they are paired
  continuous measures on every task. They are still exploratory.

## 9. Stopping rules

1. **Budget gate (§6).** A run above R stops the experiment.
2. **Claude Code version change:** stop.
3. **More than 20% invalid attempts after at least 9 attempts:** stop and
   investigate before spending more.
4. **No interim looks:** blind.
5. **Interruptions:** `--resume <id>` continues the same experiment with the
   same protocol, task order and build.
   - Finished attempts are never rerun.
   - An attempt that crashed or was killed is charged R and rerun once.
6. **Missing toolchain:** a live run with a missing host toolchain is
   refused before anything runs. Before 0.7.7 the task was silently skipped.

## 10. Runner changes in 0.7.7 (made before any run; no change to tasks or grading)

1. **`--task-order interleave`:** the order in §3.
   - The order is recorded in the experiment's `tasks` and `schedule`, and a
     resume with another order is refused.
   - The default (`suite`) is unchanged.
2. **Missing toolchain:** a live run refuses to start instead of silently
   skipping that task. The dry run lists missing toolchains.
3. **Reporting:**
   - per-arm rates and paired comparisons for *correct with no regression*
     and *regression-free*;
   - an "invalid counted as failures" sensitivity analysis for the primary
     outcome;
   - the content-match sensitivity analysis;
   - an explicit list of tasks with a valid run in only one arm.
   - These are computed from recorded fields only.
4. **One deny list:** runs, the settings preflight and the dry run share it,
   so the dry run shows the authoring-notes denial actually applied.

## 11. What the result can and cannot say about enabling Core

| Result (primary outcome) | What it would mean |
|---|---|
| Core better, supported | First evidence of a correctness benefit on unseen tasks, large (≥ ~25 points). Worth a confirmatory study on a new sealed set before claiming it. |
| Core worse, supported | Evidence of harm. Core should not be the default until the cause is found (`eval regressions`). |
| Inconclusive, direction favours Core | No demonstrated benefit. A small or moderate benefit is not excluded. |
| Inconclusive, direction favours Plain | No demonstrated benefit. A small or moderate harm is not excluded. |

Inconclusive is the most likely result for any true effect below about 30
points.

**Efficiency:** this is where the experiment is most informative about
enabling Core. Paired cost, token and time differences over 25 tasks can show
whether Core's overhead is negligible or material.

**Combined with Option A** (no correctness benefit, slightly negative, Core
cost about equal to Plain), an inconclusive correctness result would mean:
Core has no demonstrated correctness benefit and only a measured overhead.
Enabling it is then a matter of preference (the Verify line, context tools),
not of proven performance.

## 12. Integrity risks of the smaller design

1. **It consumes the sealed set** (above). This is the largest cost of running
   it now.
2. **One repetition:** run-to-run model variance is indistinguishable from an
   arm effect within a task. A single discordant task is weak evidence.
3. **Early stop:** the tasks reached depend on total spend, but never on
   which arm did better. Both arms of a task always run together, so the
   comparison stays paired and unbiased. The *population* changes, though,
   toward fewer sqlglot and dnspython tasks.
4. **The primary outcome is defined in analysis, not in the grader:** it is
   fixed here, before any run, and derived from fields the grader already
   records.
5. **Cost estimates are not billing.** A run above R stops the experiment;
   provider billing can still differ from the estimates.
6. **Outcome peeking:** blind mode hides outcomes in progress lines. The raw
   `runs.jsonl` still contains them and must not be read until the
   experiment ends.
7. **Arm position:** balanced in every prefix, but not within each project.
   Core goes first in 4 of 8 sqlglot, 4 of 6 dnspython and 3 of 4 asn1crypto
   tasks. Arm position had no detectable cost effect in Option A (mean cost
   by position: $0.141, $0.146, $0.145).

## 13. Command (only after authorization)

```sh
repo-ai eval coding --suite benchmarks/sealed-v2 --split sealed-v2 --compare baseline,core \
  --task-order interleave --repeat 1 --seed 0 --model claude-sonnet-5-5 --effort medium \
  --max-turns 60 --timeout 1800 --max-cost-per-run 1.50 --max-cost-usd 20 --blind
```

Run it from the repository root, with repo-ai 0.7.7 installed.

## Amendments

(none yet)
