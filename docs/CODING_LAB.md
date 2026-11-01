# Coding Performance Research Lab

`repo-ai eval coding` asks one question: **does repo-ai make Claude Code
better at finishing programming tasks than plain Claude Code?** It answers
with controlled experiments, not anecdotes. (`repo-ai eval` measures
localization: where the right files rank. The lab measures outcomes.)

Nothing here runs a model unless you give it an explicit budget.

## Arms

Each arm is a set of independent feature flags, so an ablation is one flag
away.

| Arm | What Claude gets |
|---|---|
| `baseline` | plain Claude Code: no repo-ai file, hook, rule or skill |
| `core` | `hooks`, `packet` (CLAUDE.md block, curated skills, task packets), `rules` (approved project rules) |
| `full` | core + `skills` (generated), `agents` (subagents), `outcomes` (episode recording), `orchestration` (skeptic reviewer), `thirdparty` (approved third-party skills) |
| `full-packets`, `full-rules`, `full-skills`, `full-thirdparty`, `full-outcomes`, `full-subagents` | Full without one attributed feature: context packets; learned project rules; generated skills; approved external skills; outcome-aware retrieval; subagents and orchestration |
| `ablations` | shorthand for Full plus all six of the above |
| `full-<feature>` | Full without one raw feature flag |

```sh
repo-ai eval coding --compare baseline,core,full --max-cost-usd 10 --dry-run
repo-ai eval coding --pilot --compare baseline,core,full --max-cost-usd 10 --max-cost-per-run 0.50 --model sonnet
repo-ai eval ablate --feature skills --max-cost-usd 10        # full vs full-skills
repo-ai eval coding --split final --compare ablations --max-cost-usd 90 --dry-run
repo-ai eval list | report <id> | compare <id> | regressions <id>
repo-ai eval coding --resume <id> --max-cost-usd 10           # continue an interrupted experiment
```

`--pilot` selects 6 held-out tasks with one repetition per arm. A pilot is
**directional only**: verdicts refuse to say "significant" with fewer than
10 pairs.

**Task sets:**
- `--split dev|holdout` (`all` means both) select the synthetic tasks.
- `--split final` selects the sealed set of 25 re-injected upstream bugs in
  real open-source projects (benchmarks/tasks/README.md). It is never
  included implicitly.

`repo-ai eval --live` is the same lab with `--compare baseline,full`. The
older host-side runner, which executed model-written tests without a
sandbox, was removed in 0.7.2.

## Fairness and isolation

Every arm gets the same things:
- the frozen task snapshot, prompt, model, effort, max turns and timeout;
- one Claude settings file:
  - the OS sandbox on for Bash, with `failIfUnavailable` and no unsandboxed
    escape hatch;
  - no network;
  - reads of your home directory, the task suite and the lab's own home
    denied, both to Bash (sandbox) and to the file tools (`Read(//…)` deny
    rules);
  - WebFetch and WebSearch denied;
  - auto-memory off;
- a **dedicated Claude config directory**
  (`~/.local/share/repo-ai/claude-eval`, or `--claude-config`), so your
  personal `~/.claude` skills, hooks, plugins, memory and CLAUDE.md cannot
  leak into any arm;
  - before each experiment the directory is audited for skills, agents,
    commands, plugins and output styles;
- `--setting-sources project,local`;
- a fresh disposable git workspace per run, with arm order randomised per
  task by seed.

Two checks protect the experiment:
- **Preflight.** Claude Code silently ignores invalid settings in `-p` mode,
  which would silently drop the sandbox. So the settings are validated with
  `claude doctor` (no model call) first, and the experiment refuses to run if
  Claude reports a problem.
- **Isolation check.** Each run's `system/init` event (the skills, agents,
  plugins and MCP servers Claude actually loaded) and its hook events are
  checked against what that arm should have loaded. A mismatch marks the run
  invalid, and it is excluded from every statistic.

**Hidden tests** never enter the workspace. The suite sits outside every
readable path, and each agent may read and write only its own workspace.
The agent runs with an allowlisted environment, so no host credentials are
passed.

**Contamination is proof of access, not similarity** (0.7.6,
`repo_ai.integrity`). A run is invalid only when:
- a per-run **canary** turns up in the workspace or transcript. The canary is
  a fresh token in a decoy hidden-test tree placed in the lab home, which
  every agent is denied, and removed after the run;
- or a tool call **reads**, or a tool result **reveals**, protected material
  (the suite, the task's case directory, the lab) without a denial.

Two other signals are recorded but never invalidate a run on their own:
- `hidden_access_attempts`: denied attempts;
- `hidden_content_match`: workspace files identical to a hidden test, and the
  share of hidden-only lines present.

Option A invalidated five legitimate oss-tl-001 runs on content alone: a
correct fix reproduced the upstream test. The tests in
`tests/test_coding_lab.py` cover real access, denied access, a silent sandbox
escape (caught by the canary) and a legitimate matching edit.

**After the agent exits:**
- its process group is killed;
- the workspace is copied;
- the visible tests (for regressions) and the hidden tests run on **the
  copy**, inside the sandbox (below).

A process the agent left behind can touch only the original, never the
graded copy. With `--keep-artifacts`, kept workspaces move under the lab
home, which every arm is denied.

## Execution sandbox (`repo-ai sandbox status|pull`)

Model-written code and task code are untrusted. Grading runs in the
strongest backend available:

| Backend | Where | Isolation |
|---|---|---|
| `podman` / `docker` | any OS with a container engine | `--network none`, read-only root, tmpfs `/tmp`, `--cap-drop ALL`, `no-new-privileges`, pids/memory/CPU/file-size limits, private IPC, `--pull never`, only the workspace mounted, a minimal environment. Docker runs as your uid, never container root. |
| `seatbelt` | macOS `sandbox-exec` | deny-by-default profile: reads only system code directories, toolchains and the workspace (stat metadata only on their ancestors), writes only the workspace, no Mach services (so no LaunchServices `open` or Apple Events), signals only inside the sandbox, no network; rlimits; process-group kill on timeout |
| `bwrap` | Linux bubblewrap | new namespaces (including network), read-only system binds, only the workspace writable |

- There is **no unsandboxed fallback**. With no backend available, grading
  refuses to run.
- A temp directory, a git worktree or a virtualenv is never treated as a
  boundary.
- Workspaces with symlinks pointing outside are refused.
- Hidden tests run on a copy without `__pycache__`, so they always import
  the agent's source. Planted bytecode whose header matches a source file's
  mtime and size would otherwise be loaded instead.
- `tests/test_sandbox.py` runs escape tests against every available backend
  (read outside, read home, network, inherited environment, write outside,
  symlink escape, timeout kills the process tree). CI runs them with Docker.

## Metrics

**Per run:**
- success (hidden tests pass, and visible tests still pass);
- hidden-test pass fraction;
- regressions;
- abandoned and timed-out runs;
- turns, tool calls, wall time, time to first edit, reads before the first
  edit;
- files changed and unnecessary edits. Untracked interpreter and test-tool
  caches (`__pycache__/<module>.<tag>.pyc`, `.pytest_cache/`, `.mypy_cache/`,
  `.ruff_cache/`, `.hypothesis/`, `.coverage*`) are counted separately as
  `execution_artifacts`. Running the tests is not an edit. Tracked files and
  module-level `.pyc` files still count;
- the agent's Bash commands (first 100, each truncated to 300 characters) and
  how many of them ran a test suite;
- input and output tokens, with uncached input, cache reads and cache
  creation recorded separately;
- Claude Code's reported cost (a client estimate, not billing);
- repo-ai's injected context (estimate);
- skills invoked;
- isolation problems.

**Per arm:**
- success rate with a 95% Wilson interval. 6/6 is reported as 100% (61–100%),
  never as certainty;
- standard deviations of tokens and tool calls.

**Repetitions:** with `--repeat 2` or more, the task is the unit of
analysis. Each task's repetitions are averaged per arm before comparing, so
25 tasks × 2 repetitions is 25 units, not 50.
- **Interval:** a task-clustered Bonett–Price adjusted Wald interval
  (`stats.clustered_diff_ci`). Its coverage was verified by simulation
  (docs/STATISTICS_COVERAGE.md). The 0.7.3 interval, Newcombe on fractional
  counts, undercovered with one run per task and was over-conservative with
  repetitions.
- **Test:** an exact (≤ 20 tasks) or seeded Monte Carlo sign-flip
  permutation test on the per-task differences.
Holm's correction applies across the experiment's comparisons, and a result
significant only before correction is reported as inconclusive. The
ordinary unclustered analysis is shown only as a labelled sensitivity line.

**Per comparison** (paired by task and repetition; `repo_ai.stats`):
- **Success difference.** The task-clustered interval above. With one run
  per task it is Bonett–Price (2012). It never collapses: 25 agreeing
  all-success tasks give ±10 points, not 0…0.
- **Exact McNemar** test on the discordant pairs, with one run per task
  (identical to the sign-flip test there).
- **Unclustered sensitivity line:** Newcombe's paired score interval on
  runs. It is labelled as such.
- **Equivalence** is claimed only by TOST: the 90% interval must lie inside
  ±10 points. *Observing equal rates is not evidence of equivalence.*
- **Ceiling and floor flags** when both arms are ≥ 95% (or ≤ 5%): the task
  set cannot discriminate between them.
- **Continuous metrics** (tokens, cache reads, cost, tool calls, turns,
  runtime): the paired median difference with a bootstrap 95% interval
  (marked rough below 10 pairs), how many tasks were lower or higher, and an
  exact Wilcoxon signed-rank p-value.

**Verdicts:**
- "better/worse (statistically supported)";
- "equivalent within ±10% (TOST)";
- "inconclusive: no difference observed, but equivalence is not shown";
- "inconclusive: directional (±x%), not significant";
- "inconclusive (pilot)".

Each can carry a ceiling or floor note.

**Planning:** `stats.mcnemar_pairs_needed` and
`stats.mcnemar_detectable_effect` give the sample-size arithmetic. See
docs/EXPERIMENT_PLAN.md.

**Regression Investigator** (`eval regressions <id>`): lists tasks the
reference arm passed and the candidate failed. For each, it gives evidence:
a large injected context, a first edit outside the gold files, more reads,
turns or timeouts. Where no signal stands out it says "may be model
variability".

## Protocol for confirmatory runs

- **Pinned:** `--model claude-sonnet-5-5 --effort medium`. Every arm gets
  the same argv apart from its per-run settings path. A run reporting a
  different model is invalid.
- **One Claude Code version:** auto-update is disabled for agent runs. A run
  reporting another version is invalid and stops the experiment.
- **Balanced, pre-registered arm order:** every permutation is used about
  equally often, and repetitions of a task get different orders. The order
  is a pure function of the protocol and appears in the dry run's
  `schedule`. Prompt caching makes later runs of a task cheaper, so balance
  matters for cost.
- **`--task-order interleave`** (0.7.7) runs tasks round-robin across their
  bases, in a seeded order.
  - Every prefix is spread over the projects, so a budget stop still leaves
    a comparison over as many projects as possible.
  - The order is part of the recorded `tasks` and `schedule`, and a resume
    with another order is refused.
  - The default `suite` keeps task-id order.
- **Missing toolchain:** a live run refuses to start (0.7.7). It used to skip
  that task silently. The dry run lists missing toolchains.
- **`--blind`:** progress lines show only "done", validity and spend, never
  pass/fail.
- **Every attempt is accounted for.** The report has an outcome table:
  - attempts, valid, success, failure;
  - stopped by the cost cap, by max turns, timed out (all valid failures);
  - invalid (isolation or contamination), errors, crashed, cancelled;
  - not attempted.
- **Outcomes beside `success`** (hidden tests pass), computed from recorded
  fields; the grader is unchanged:
  - `correct_no_regression`: the hidden tests and the visible suite pass;
  - `regression_free`: the visible suite passes.
  - Each gets per-arm rates and its own paired comparisons, with Holm within
    each outcome.
- **Tasks with a valid run in only one arm** are listed as "not compared",
  never dropped silently.
- **Pre-registered sensitivity analyses:**
  - invalid counted as failures (also for `correct_no_regression`);
  - repetition 0 only;
  - a workspace file identical to a hidden test treated as invalid;
  - unclustered.
- **Stopping rules:** a budget gate; a Claude Code version change; more than
  20% invalid attempts after 9 attempts.
- **Resume:** `--resume <id>` refuses a different protocol (arms, tasks,
  model, effort, caps, seed, blind). It never reruns a finished attempt.
- **Token accounting:** taken from `modelUsage` (all of a session's models,
  subagents included) when Claude Code reports it. Fresh input, cache reads
  and cache creation are recorded separately. "Tokens" is the cache-neutral
  volume.
- **Cost calibration:** `--split calibration` (4 real-repository tasks
  outside the sealed set).
  - The report gives, per arm: cost p50/p90/max, cap hits, turns p90/max,
    max-turn hits, timeouts, the longest run, and the largest single API
    call.
  - It also gives the main run's limits by the pre-registered rule
    (`coding_lab.preregistered_limits`).

## Money

- Live runs need `--max-cost-usd`.
- Before any model call, the experiment refuses to start if a task's
  toolchain has no grading sandbox.
- Each run is capped with `--max-cost-per-run` C (passed to Claude as
  `--max-budget-usd`). Every arm gets the same cap.
- **Reservation.** Claude checks the cap between API calls, so a run can end
  one call past C. Each pending run therefore holds a reservation R:
  - by default R = 1.25 × C;
  - `--reserve-per-run` sets a larger R;
  - each run's estimated largest single call (`max_call_cost_usd_est`) is
    recorded so the margin can be checked.
- **Gate.** A task's arms start only if every remaining arm's R fits the
  remaining budget, so pairs are never broken by money.
- **Never over budget.** The money charged never exceeds `--max-cost-usd`
  as long as no run costs more than R. A run that does stops the
  experiment at once. Regression tests cover runs at 0, C, 0.99 R and R,
  missing costs, overshoot, and a randomized property check.
- **Completion budget.** Planned runs × R is the smallest budget guaranteed
  to complete without crashes. Each crashed attempt reruns once and needs
  one more R. Planned runs × C is **not** enough: runs costing exactly C
  stop before the last task. The dry run prints the completion budget.
- A reservation is written before each attempt. An attempt that crashes or
  is killed is charged its full reservation and runs again on resume. It is
  never double-counted.
- A run that reports no cost is charged its full reservation.
- Results are appended as runs finish, so `--resume` continues without
  paying twice.
- Ctrl-C stops cleanly.

## What has been measured

The measurement table is in `docs/EXECUTION_LEDGER.md` (v0.7.0), which stays in the
private development history; anything it marks "Not run" is **unverified**. The public
record is [STATUS.md](STATUS.md). A fake client (`tests/fake_claude_lab.py`)
tests the pipeline end to end at zero cost, and its reports carry a FAKE
banner. Fake results are never evidence about Claude.
