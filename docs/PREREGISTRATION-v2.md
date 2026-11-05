# Pre-registration v2: repo-ai 0.7.6 on the sealed-v2 benchmark

**Status:** registered, **not run**, and **not authorized**. Nothing here may
run without the owner's explicit authorization of this experiment and its
budget. This file and the schedule
(`benchmarks/preregistration/sealed-v2-schedule.json`, SHA-256 below) are
committed before any model call. Later changes are recorded as dated
amendments before the experiment starts.

## 1. Question

**Primary:** on fresh, harder real-repository tasks it was not tuned on, does
repo-ai Core (the 0.7.6 default) change Claude Code's task correctness, that
is, solving the task without breaking the rest of the suite?

**Secondary:**
- Does Full differ from Core?
- Do the arms differ in regressions, cost, tokens, runtime, or how often the
  agent runs the tests?

The 0.7.6 verification guidance (tests first, full suite before finishing)
answers a harm measured in Option A. Whether it *helps* is what this
experiment would measure. Until then that is **unverified**.

## 2. Software and model (pinned)

- **repo-ai:** v0.7.6, from the release wheel. A resume under another build
  is refused.
- **Claude Code:** the version current at launch, recorded. Auto-update is
  off, and a version change stops the experiment.
- **Model and effort:** `claude-sonnet-5-5`, effort `medium`, the same for
  every arm.
- **Isolation:** the dedicated, audited eval config directory; no MCP; only
  the built-in `cc-plugin-*` plugins; argv identical across arms except the
  settings path.

## 3. Tasks

All 25 tasks of `benchmarks/sealed-v2` (docs/SEALED_V2.md):

| Base | Tasks |
|---|---|
| sqlglot | v2-sg-001 to 008 |
| dnspython | v2-dns-001 to 006 |
| asn1crypto | v2-ac-001 to 004 |
| pyasn1 | v2-asn-001, 002 |
| lark | v2-lk-001, 002 |
| more-itertools | v2-mi-001 |
| typing_extensions | v2-te-001 |
| marked | v2-mk-001 |

- **Selection:** a rule fixed in advance.
- **Oracles:** all valid in the sandbox.
- **Prior use:** none. No run (real or fake) has used them, and nothing was
  tuned on them.

## 4. Arms

| Arm | Features | Product equivalent |
|---|---|---|
| baseline | none: plain Claude Code | — |
| core | hooks, packet (CLAUDE.md block with the Verify line, curated skills, task packets), learned rules | `feature_set = "core"` (default for new installs) |
| full | core + generated skills, subagents, outcome recording, skeptic, orchestration hint | `feature_set = "full"` |

## 5. Design

- **Size:** 25 tasks × 3 arms × 2 repetitions = **150 runs**.
- **Order:** repetition 0 of every task, then repetition 1.
- **Arm order:** within each (task, repetition), the balanced seeded schedule
  (seed 0). Schedule SHA-256: `fbbd8d69e8656707acf925d1f44818074afb014d76ba9bca911610d84a64e673`.
- **Workspaces:** each run gets a fresh workspace, with the suite and the
  authoring notes denied. Hidden tests are never in the workspace. Grading
  happens in the sandbox, on a copy without `__pycache__`.
- **Blind:** `--blind`. No outcome is looked at until the experiment finishes
  or stops.

## 6. Limits (fixed now; no calibration step)

- **Turns and time:** 60 max turns, 1,800 s timeout.
- **Money per run:** cap C = $1.50, reservation R = $1.875 (1.25 × C).
- **Guaranteed-completion budget:** 150 × R = **$281.25**.
- **Recommended budget:** 147 × u + 3 × R, rounded up to $5 = **$75**. Here
  u = 3 × the Option A mean per run ($0.146 → $0.44), allowing for harder,
  multi-file tasks in larger repositories.
- **Owner's choice:** the owner approves B. Below $281.25, a budget stop is
  possible. It happens only between tasks, so a task's arms are always
  compared together.

## 7. Outcomes

**Primary:** task success. All hidden upstream tests pass **and** the base's
runnable visible suite (with the updated test files) passes.

**Key secondary (confirmatory, its own Holm family):** regression-free runs,
where the visible suite still passes.

**Secondary (exploratory, no multiplicity claims):**
- estimated cost, cache-neutral tokens, cache reads and runtime;
- tool calls and turns;
- test runs by the agent (any, and full-suite);
- unnecessary edits (execution artifacts excluded);
- cap-, turn-limit- and timeout-hit **frequencies per arm**, compared, never
  assumed equal.

**Intention to treat:**
- Cap, turn-limit and timeout stops are valid failures.
- Invalid attempts (isolation, proof of hidden-material access, infrastructure
  error, crash) are excluded, and every one is listed with its reason.

## 8. Analysis (`repo_ai.stats`, as in Option A)

- **Unit:** the task. Repetitions are averaged per arm.
- **Comparisons:** Core vs Plain (primary), Full vs Plain, Full vs Core.
- **Interval:** task-clustered Bonett–Price 95% (90% for TOST).
- **Test:** sign-flip permutation, with Holm across the three comparisons.
- **Decision rules:**
  - improvement or regression: Holm p < 0.05 **and** the 95% interval excludes
    0;
  - equivalence: the 90% interval lies inside ±10 points;
  - otherwise: inconclusive;
  - ceiling and floor flags as before.

**Sensitivity analyses:**
1. invalid attempts counted as failures;
2. repetition 0 only;
3. runs with a workspace file identical to a hidden test (a content-match
   diagnostic, not proof) treated as invalid;
4. the unclustered analysis, labelled as such.

**Power:** with 25 tasks, 80% power at α = 0.05 detects about 30–38 points
(30–50% discordant tasks). Smaller true effects will most likely be reported
as inconclusive, and that is the honest result.

## 9. Stopping rules

1. **Budget:** the reservation gate (§6). A run above R stops the experiment.
2. **Claude Code version change:** stop.
3. **More than 20% invalid attempts after at least 9 attempts:** stop and
   investigate.
4. **No interim looks:** blind.
5. **Interruptions:** `--resume` continues the same experiment under the same
   protocol and build. Finished attempts are never rerun, and a crashed
   attempt is charged R and rerun once.

## 10. Command (only after authorization)

```sh
repo-ai eval coding --suite benchmarks/sealed-v2 --split sealed-v2 --compare baseline,core,full \
  --repeat 2 --seed 0 --model claude-sonnet-5-5 --effort medium --max-turns 60 --timeout 1800 \
  --max-cost-per-run 1.50 --max-cost-usd <B> --blind
```

## Amendments

**Amendment 1 (2026-10-21, before any run; no model calls).** Appended; the
plan above is unchanged.

1. **Success needs a derived outcome.** §7 defines success as hidden tests
   passing *and* the visible suite passing.
   - The runner's recorded `success` field is the hidden tests alone; the
     visible suite is recorded separately as `regression`.
   - From 0.7.7, the analysis reports the §7 outcome as
     `correct_no_regression` (`success and not regression`), with its own
     paired comparison.
   - The grader is unchanged.
   - An analysis of this plan uses `correct_no_regression` as its primary
     outcome.
2. **The content-match sensitivity analysis (§8, item 3) is now
   implemented** (`content_match_as_invalid`, 0.7.7). It was not in 0.7.6.
3. **A separate, exploratory, budget-limited experiment is registered** in
   `EXPLORATORY-v2-pairs.md`: Core vs Plain, 50 runs, at most $20.
   - **If it runs, sealed-v2 is no longer untouched.** This plan could then
     run only as a replication on seen tasks, not as a confirmatory test on
     unseen ones.

**Amendment 2 (2026-10-21).** The exploratory experiment ran
(`20261021-103834-40bc`). sealed-v2 is therefore no longer untouched, and
this plan is **not** a confirmatory test any more. It is retained for the
record only.
