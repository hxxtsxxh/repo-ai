# c10-confirm-v1: results

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md) (commit `119cb67`, before any material), Amendment 1 (`5cbc855`,
built-in skills, before any material), Amendment 2 (`b662e9d`, ceiling $6 after the first run's cost, before any
grading). Materials frozen at `2364125` ([MATERIALS.md](MATERIALS.md)); the harness process that ran all 48 runs was started from `f5260123` (budget constant $4; `b662e9d` only
raised it to $6, which never came into play).
48 runs on 2026-11-01, the first finishing at 21:06:58Z (before Amendment 2, committed 21:07:33Z) and the last at
21:20:45Z (stream file times). Claude
Code 2.1.316, model `sonnet` (claude-sonnet-5-5), repo-ai 0.11.6 from PyPI for `init` and the
skill install, `token_env` with a new empty `CLAUDE_CONFIG_DIR` per run. Shuffle seed 1323758276. Raw:
[results/](results/): per-run results, mapping, summary, each run's diff, and `trace.json` (each run's init event,
filtered to what validity needs, plus its tool calls and `Skill` call arguments; the full streams stay local because
they carry session metadata). Spend: $3.2509 notional.

## Verdict (preregistered rule): **SUPPORTED**

| task | skill (mean of 3) | control (mean of 3) | difference |
|---|---|---|---|
| t1 | 1.00 | 0.67 | +0.33 |
| t2 | 1.00 | 0.78 | +0.22 |
| t3 | 1.00 | 0.33 | +0.67 |
| t4 | 1.00 | 0.11 | +0.89 |
| t5 | 1.00 | 0.00 | +1.00 |
| t6 | 1.00 | 0.33 | +0.67 |
| t7 | 1.00 | 0.00 | +1.00 |
| t8 | 1.00 | 0.33 | +0.67 |

Skill arm higher on **8 of 8** tasks, control on 0; one-sided exact sign test p = 0.0039. No run was
INVALID: every init event listed only Claude Code's 19 built-in skills (plus `stockroom-conventions` in the skill
arm), only `@builtin` plugins, no MCP server and only the six allowed tools (`results/trace.json`). Every `Skill`
call invoked `stockroom-conventions`.

## Reported alongside (not gates)

- **Convention score:** skill arm 1.000 (every assertion in every run),
  control 0.319.
- **Baseline score** (the requested behaviour, no convention involved): skill 1.000,
  control 0.875. The skill did not cost task correctness.
- **Unprompted invocation:** the skill arm called the `Skill` tool in 24 of 24 runs;
  no request named it.
- **Cost:** skill arm $1.814, control $1.437 (24 runs each).

## Disclosed

- **Three control runs ended without editing** (695c233a and eae5478c on t4, f5e39e65 on t8). They looked for the
  project's files at a mangled absolute path (`…/claude-501/-Users-heetshah-cdbdce7a…` for the real
  `…/claude-501/-Users-heetshah/cdbdce7a…`, one `/` turned into `-`) with Read, Glob and Grep only, made no Edit or
  Write call (their diffs are empty) and ended with `success`. The requested functions were therefore missing and
  every assertion, baseline included, scored 0: the preregistered case "a run that ends without editing is scored as
  it is". It hit 3 of 24 control runs and none of the skill runs, plausibly because invoking the skill shows the model
  the real path, so it may depend on the arm; the unusual work-directory name is a harness artifact. **Sensitivity:**
  without these three runs the result is unchanged (skill higher on 8 of 8, p = 0.0039; control convention 0.365,
  baseline 1.000). The control baseline of 0.875 is therefore not a measured cost of working without the skill.
- **Deviation:** the protocol says nothing changes after the first live call; Amendment 2 raised the spending
  ceiling after run 1 (disclosed, before any grading, no effect on the analysis).
- **Reviewer C** noted a minor leak in t5's request (it reveals rule 9's 0–100 scale, not the type, precision or
  rounding that the convention assertion checks).

## Reading

On this project and these 8 tasks, a project-conventions skill installed with `repo-ai skills install` made Claude
Code's changes follow the project's written conventions (every convention assertion passed in every skill
run, against about a third without it) without lowering task correctness. **Limits, stated in advance:** one fixture
project, one model, one conventions skill whose value is by construction the rules the code does not show; the
authors of the fixture, skill, tasks and oracles and the reviewer were separate model sessions, not people; host mode
only. The control arm had no conventions text at all, so the trial shows that conventions text delivered as a
repo-ai-installed skill beats having none; it does not show a benefit of the skill format over the same text in, for
example, CLAUDE.md. Some oracle inputs reuse the skill's own worked examples. It does not show that third-party
skills in general, or repo-ai's discovery, pick skills that help.
