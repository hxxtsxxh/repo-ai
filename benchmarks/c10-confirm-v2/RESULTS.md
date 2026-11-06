# c10-confirm-v2 results

Preregistered in `PREREGISTRATION.md`. 72 Claude Code sessions (8 tasks x 3 arms x 3 repeats), model
`claude-haiku-5-5`, Claude Code 2.1.319, repo-ai 0.12.8, host mode, token from a mode-600 token file, an empty
config dir per run. Ran 2026-11-06. Cost **$0.7798** (Claude Code's reported `total_cost_usd`, OBSERVED; subscription
token, so notional and metered against the plan).

## Read this first: the validity rules were amended after the run

The first grade marked **all 72 runs INVALID**, so every comparison was empty and its verdict meaningless. Both
causes were defects in the harness's validity rules, identical across arms and independent of outcomes (the
`schedule` built-in skill appears only in authenticated sessions; the "project memory" init-field check compared
path-dependent fields). **Amendment 1** (`PREREGISTRATION.md`, commit `3502440`) fixed both and was committed and
pushed **before any score was read**; grading was then re-run once on the kept streams ($0). The original
all-invalid grade is kept: `results/summary-original-all-invalid.json`, `results/results-original-all-invalid.json`.
Weigh the result with that in mind.

## Results (under amendment 1; 0 runs invalid)

| arm | runs | convention score | baseline score | `Skill` called | not `success` | cost |
|---|---|---|---|---|---|---|
| skill | 24 | **1.000** | 1.000 | 24 / 24 (always `logsift-conventions`) | 0 | $0.2387 |
| claudemd | 24 | **1.000** | 1.000 | 0 | 1 (budget cap) | $0.3312 |
| control | 24 | **0.462** | 1.000 | 0 | 0 | $0.2098 |

Per task, convention score (mean of 3 runs), skill / claudemd / control: t1 1/1/0, t2 1/1/0.75, t3 1/1/0,
t4 1/1/0.78, t5 1/1/1, t6 1/1/0.5, t7 1/1/0.33, t8 1/1/0.33.

| comparison | X higher | Y higher | ties | one-sided sign test | verdict |
|---|---|---|---|---|---|
| **primary** skill vs control | 7 | 0 | 1 (t5) | p = 0.0078 | **SUPPORTED** |
| secondary skill vs claudemd | 0 | 0 | 8 | p = 1.0 | **NO_DIFFERENCE_SHOWN** |
| tertiary claudemd vs control | 7 | 0 | 1 (t5) | p = 0.0078 | TEXT_HIGHER |

## What this does to C10 (the predeclared table)

- Primary SUPPORTED: C10 stays PASS_WITH_LIMITS; "one fixture project, one model" becomes "two fixture projects (a
  Python library, a Python CLI) and two models (Sonnet 5.5, Haiku 5.5); Python only".
- Secondary NO_DIFFERENCE_SHOWN: the limit "the control had no conventions text" is replaced by "on project 2 with
  Haiku, the installed skill did no better than the same text in CLAUDE.md". The claim is about the conventions text
  being present, **not** about the skill format. This is not evidence that the two are equivalent.

## Limits and observations

- **Amended after the run** (above). The amendment was symmetric and committed before scores were read, but it was
  still written after the data existed.
- **Ceiling.** The skill and claudemd arms scored 1.000 on every task, so this design cannot separate them; a harder
  task set would be needed to compare the formats.
- **CLAUDE.md loading is not observed** in the init event (amendment 1 dropped that check). The claudemd arm's 1.000
  vs control's 0.462 shows the text reached the model in practice.
- **Budget overshoot was larger than predicted.** One claudemd run (t1) ended with `error_max_budget_usd` at
  $0.0747 against a $0.05 cap: the last turn went $0.025 over, not "well under a cent" as the preregistration
  assumed. It is scored as it stands (convention 1.0, baseline 1.0). The total stayed far under the $3.60 ceiling.
- No run edited files outside the project. The baseline (the project's own tests) was 1.000 in every arm.
- The project and the model changed together, so a failure could not have been attributed to either. The authors and
  the reviewer were separate model sessions, not people. Python only, host mode only. This says nothing about
  third-party skills or about repo-ai's discovery choosing helpful skills.

Files: `results/results.json` (each run's per-assertion results), `results/summary.json`, `results/mapping.json`,
`results/trace.json`, `results/candidates/`.
