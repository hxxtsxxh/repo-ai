---
title: Compared with other tools
description: What repo-ai adds next to the tools you already use, where it is worse, and how the idea was chosen.
---

repo-ai is a local tool for one question: **did this change break something, and how do you know?** For a
developer, it shows which tests can catch a regression in the change, runs them sandboxed, and separates new failures
from ones already present at the base commit. For coding agents, it treats their output as an untrusted candidate.
Each claim below is backed by a measurement on the linked page. Where there is none, it says so.

## What it adds, and what it leaves to other tools

| Need | Already done well by | What repo-ai adds |
|---|---|---|
| Run the tests | the project's own runner (`pytest`, `unittest`, `node --test`) | nothing: `verify --run` runs that runner and reads its own results |
| Run only what changed | `pytest-testmon` (coverage, Python); `jest --onlyChanged`, `vitest related` (static, JavaScript) | for pytest and `node --test`: one view across Python and Node, the evidence behind each selected test, and confidence that falls back to "run everything" when the evidence cannot vouch for the selection. Jest and Vitest projects run their full suite |
| Re-run failures | `pytest --lf` | whether each failure is **new or was already there**, checked against the base commit with the same run shape |
| Run tests without touching your files | a container you set up | by default a disposable copy, no network, and a check that the working tree is byte-for-byte unchanged |
| Know whether a result still applies | nothing common | evidence tied to the exact change and test environment (`repo-ai evidence`, and a completion gate for agents) |
| Use a coding agent | the agent's own CLI | (experimental) an isolated worktree, frozen tests, repo-ai's own run of the frozen tests on the candidate, and you decide whether to apply it |

Measured for `verify` (held-out-7, five public projects in containers, build `903984a`): **0 false assurances in 127
failing states**, 0 new failures called pre-existing, 0 false alarms, and the working tree unchanged in 234 of 234
runs. The scope and the projects it does not cover are on [Evaluation & methodology](/repo-ai/docs/evaluation/).

## Where it is worse

- **Slower than running the suite yourself.** On 30 real upstream commits in five small pure-Python projects
  (speed-v1), `verify --run` took 1.84× the native suite (geometric mean) in the preregistered run, slower on 24 of
  30, and 2.23×, 2.00× and 1.96× in three later runs, slower on 30, 30 and 28 of 30. It does not save time on small
  suites. A profile on a generated 40-test project traced most of the fixed cost to source-tree snapshots and git
  calls, since reduced; the speed-v1 projects themselves have not been profiled.
  ([Evaluation](/repo-ai/docs/evaluation/); [speed-v1 results](https://github.com/hxxtsxxh/repo-ai/blob/main/benchmarks/speed-v1/RESULTS.md);
  [changelog](/repo-ai/docs/changelog/))
- **Fewer runners.** Jest, Vitest and Mocha are not supported for selection (full suite only). unittest and
  TypeScript have no held-out qualification. ([Status matrix](/repo-ai/docs/status/))
- **It runs in the project's environment.** If the project's test runner is not installed where verify runs the
  tests, nothing is verified. 0.11.8 exits 1 but labels that run "NO NEW FAILURES … at the base" (and its `prove`
  and `--expect-fix` missions counted it as no new failures); 0.11.9 says NOT VERIFIED.
  ([changelog](https://github.com/hxxtsxxh/repo-ai/blob/main/CHANGELOG.md))
- **Not shown to make agents better.** In a preregistered, blinded study (150 runs, 25 tasks) plain Claude scored 92%,
  and repo-ai's two context configurations 90% (Core) and 88% (Full). Every difference was inconclusive, and
  equivalence was not shown either. Whether repo-ai improves an agent's results is `NOT_YET_DEMONSTRATED`.
  ([Evaluation](/repo-ai/docs/evaluation/))
- **No host sandbox on Windows.** `verify --run` needs containers there, and missions are not supported. The unit
  tests pass in CI, but Windows has never been measured on fresh data. ([Status matrix](/repo-ai/docs/status/))

## How the idea was chosen

In October 2026, ten candidate problems were scored from 1 to 5 for impact, frequency, feasibility offline, open space
(not already solved well) and whether a difference could be measured without paid model runs. Two experiments and the
offline audits fed into the scores. The highest score went to **knowing whether a change was actually verified**,
with machine-checkable evidence tied to the exact change.

Rejected or deferred, with the reason:
- **Giving the model more context**: two experiments showed no benefit, and retrieval tied with grep on fresh tasks.
- **Persistent project knowledge**: a crowded space, and repo-ai's own learned rules had produced three wrong
  instructions.
- **Safe specialist workflows (skills)**: 0 skill invocations in 212 runs, and no cheap way to measure a benefit.
  A later preregistered trial (one fixture project, one model, one project-conventions skill) did measure a
  benefit; its limits are on the [Evidence Lab](/repo-ai/docs/evidence/).
- **Blast-radius analysis on its own**: other tools already do it statically, with uncalibrated confidence.

The full scoring is [`docs/ARCHITECTURE-DECISION-0.8.md`](https://github.com/hxxtsxxh/repo-ai/blob/main/docs/ARCHITECTURE-DECISION-0.8.md). The prior-art
survey behind it (pytest-testmon, Jest and Vitest, and others, with their documented gaps) is
[`docs/RESEARCH-2026-10.md`](https://github.com/hxxtsxxh/repo-ai/blob/main/docs/RESEARCH-2026-10.md).
