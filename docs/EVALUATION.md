# Evaluation

`repo-ai eval` measures whether repo-ai helps a coding agent finish real
tasks, not only whether it retrieves plausible files. It has two modes over
one frozen suite.

## The task suite (`benchmarks/tasks/`)

- **59 tasks**: 27 Python (`py-shop`, stdlib only), 20 TypeScript
  (`ts-workspace`, a Node ≥ 22.18 monorepo with type stripping), and 12 Java
  (`java-ledger`, plain Java 17).
- **Categories**: 28 bug fixes, 3 security; 2 each of feature, API,
  refactor, test, config, CI, integration, monorepo, auth, database,
  frontend, performance, migration and architecture tasks. v0.7.0 added 18
  tasks (path traversal, HTML injection, privilege escalation, CSV formula
  injection, unit-of-work rollback, a quadratic slowdown, password hashing
  migration, dependency injection, config v2, retry backoff and more).
- **Authorship**: every repository and task is synthetic, written for this
  project (MIT). No third-party or private code is included.
- **Contents of each task**: a prompt written like a real bug report or
  request; `setup` edits that create the starting state; a reference
  `solution`; `gold_files` (the files a correct fix must touch); and
  *hidden* tests that check behaviour.
- **Hidden tests** are copied into the workspace only after the agent has
  finished. Their names never appear in the prompt or the base repository.
- **Split**: tasks are split deterministically by id hash (`--split
  dev|holdout`). Ranking changes may be tuned on `dev` only, and `holdout`
  numbers are reported, never tuned on.

## Offline mode (default: free, deterministic, no network)

```sh
repo-ai eval                      # oracle validation + localization, all tasks
repo-ai eval --split holdout      # report-only half
repo-ai eval --check benchmarks/results/eval-offline.json   # CI regression gate
```

1. **Oracle validation.** For every task, the hidden tests must fail on the
   starting state and pass after the reference solution, and the visible
   tests must keep passing. A task that fails these checks is reported as
   `INVALID` and fails the gate.
2. **Localization.** From the prompt alone, where do the gold files rank? The
   same tasks are scored for a naive grep baseline (files ranked by how many
   prompt words they contain, with filename hits weighted), so the number has
   a reference point. Also measured: how often the prompt hook injects
   context, whether its payload contains every gold file, and its size
   (estimated as chars / 4).

### Results (v0.7.0, 59 tasks; Python 3.12, macOS)

| Split (tasks) | Ranker | recall@5 | all gold in top 5 | MRR |
|---|---|---|---|---|
| holdout (35) | repo-ai 0.7.0 | 0.674 | 0.600 | 0.574 |
| holdout (35) | naive grep | 0.735 | 0.714 | 0.520 |
| dev (24) | repo-ai 0.7.0 | 0.736 | 0.708 | 0.680 |
| dev (24) | naive grep | 0.694 | 0.625 | 0.543 |
| all (59) | repo-ai 0.7.0 | 0.699 | 0.644 | 0.617 |
| all (59) | naive grep | 0.719 | 0.678 | 0.529 |

On the 41 tasks shared with v0.6, nothing regressed (MRR 0.536 → 0.540).
On the 18 new tasks, which no ranking change was tuned on, repo-ai is
slightly **worse** than grep: MRR 0.793 vs 0.830, recall@5 0.787 vs
0.833. Its first relevant file still ranks higher than grep's across the
whole suite, but grep's top 5 covers more of the gold files. Retrieval was
not re-tuned for v0.7.0.

### Results (v0.6.0 development build, 41 tasks; Python 3.12, macOS)

| Split (tasks) | Ranker | recall@5 | all gold in top 5 | MRR |
|---|---|---|---|---|
| holdout (24) | repo-ai 0.5.1 | 0.496 | 0.458 | 0.403 |
| holdout (24) | **repo-ai 0.6.0-dev** | **0.629** | **0.583** | **0.534** |
| holdout (24) | naive grep | 0.683 | 0.667 | 0.428 |
| all (41) | repo-ai 0.6.0-dev | 0.661 | 0.634 | 0.536 |
| all (41) | naive grep | 0.668 | 0.659 | 0.397 |

How to read this:

- **The suite exposed a real weakness in 0.5.1.** On long, natural bug
  reports, repo-ai ranked below naive grep. Absolute lexical coverage was
  diluted across many incidental words, which let structural priors (hub
  files, recency) and a misfiring "docs" intent dominate.
- **Fixes, tuned on `dev` only:**
  - ranking uses lexical evidence relative to the best match;
  - a new filename-term signal;
  - prose is discounted unless the request is about documentation;
  - quoted plain words are no longer treated as code identifiers;
  - priors count half on files without evidence of their own.
- **Result on the untouched holdout:** MRR rose from 0.403 to 0.534, so the
  first relevant file now ranks higher than with grep. **recall@5 is still
  below grep** (0.629 vs 0.683): grep's top 5 contains more of the gold files.
  This is stated in the `/repo-locate` skill, which tells Claude to grep
  when the top locations do not contain the cause.
- The older retrieval gold set (`benchmarks/run.py`) improved at the same
  time: MRR 0.875 → 0.942, recall@5 1.0, and false injection still 0 %.

These are localization numbers. **They do not show that Claude finishes more
tasks.** Only live mode can show that.

## Three-arm coding experiments

`repo-ai eval coding` compares plain Claude Code, repo-ai core and repo-ai
full on task completion, inside an execution sandbox, with ablations,
tournaments and a Regression Investigator. See docs/CODING_LAB.md. The
paired two-arm `--live` mode below remains available.

## Live mode (opt-in, billable)

**Since 0.7.2, `eval --live` runs in the coding lab** (`eval coding
--compare baseline,full`). Grading is sandboxed (and refused without a
sandbox), with the settings preflight, isolation checks and the statistics
described in docs/CODING_LAB.md. The text below describes the original
design. The host-side runner it mentions was removed, because it executed
model-written tests without isolation.

```sh
repo-ai eval --live --dry-run --max-cost-usd 20              # prints the plan; spends nothing
repo-ai eval --live --max-cost-usd 20 --max-cost-per-run 0.50 \
             --max-turns 30 --model sonnet --seed 1 --split holdout
```

**How a pair runs:**
- Each task runs as a **pair**: two fresh git workspaces from the same
  commit, with the same prompt, model, permissions and tools. The control has
  no repo-ai; the treatment has run `repo-ai init --agent claude --smart`.
- The arm order is randomised by `--seed`. Neither arm sees the other's
  result.
- Claude Code is run headless:

  ```
  claude -p … --output-format stream-json --verbose --max-turns N
    --max-budget-usd X --permission-mode dontAsk
    --setting-sources project,local --no-session-persistence
  ```

  The flags were verified against Claude Code 2.1.303.

**Permissions (identical for both arms):**
- allowed: file tools, the suite's test runners, read-only git, and
  read-only `repo-ai` queries;
- disallowed: web tools, `curl`, `wget`, `git push` and package installs;
- user-level settings and plugins are excluded, and nothing prompts
  (`dontAsk`).

**Budget and cost:**
- Each run is capped at `--max-cost-per-run`, which is passed to Claude as
  `--max-budget-usd`.
- A task's arms start only if one reservation per remaining arm (default
  1.25 × the cap, `--reserve-per-run`) still fits within `--max-cost-usd`.
- A run without cost data is charged its full reservation.
- See docs/CODING_LAB.md, "Money".
- `reported_cost_usd` is Claude Code's client-side estimate, not billing.

**Measured per run:**
- hidden-test success;
- turns and duration;
- input and output tokens;
- reads before the first edit;
- whether the first edit landed on a gold file;
- subagent calls and files changed;
- repo-ai's own injected-context estimate (treatment only, from the
  flight recorder).

**Aggregates:**
- success rate per arm and the paired difference, with a bootstrap 95 %
  interval;
- an exact McNemar test on discordant pairs;
- medians and per-task regressions (control passed, treatment failed).

**Privacy:** transcripts are reduced to metrics in memory, and nothing is
uploaded by repo-ai. Workspaces are deleted unless `--keep-artifacts` is
set.

**Status: live mode has not been run.** Running it needs an explicit budget
from the repository owner. Until a live run is recorded here, nobody should
claim that repo-ai improves task completion.

The pipeline is tested end to end at zero cost with a fake `claude`
(`tests/fake_claude.py`), covering: workspaces, grading, metric parsing, the
budget stop, the dry run, and least-privilege flags.
