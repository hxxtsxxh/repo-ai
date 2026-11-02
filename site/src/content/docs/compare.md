---
title: Compared with other tools
description: What repo-ai adds next to the tools you already use, where it is worse, and how the idea was chosen.
---

repo-ai is a local tool for one question: **did this change break something, and how do you know?** For a
developer, it shows which tests can catch a regression in the change, runs them sandboxed, and separates new failures
from ones already present at the base commit. For coding agents, it treats their output as an untrusted candidate.
Everything below links to the measurement behind it. Where there is none, it says so.

## What it adds, and what it leaves to other tools

| Need | Already done well by | What repo-ai adds |
|---|---|---|
| Run the tests | the project's own runner (`pytest`, `unittest`, `node --test`) | nothing: `verify --run` runs that runner and reads its own results |
| Run only what changed | `pytest-testmon` (coverage, Python); `jest --onlyChanged`, `vitest related` (static, JavaScript) | one view across Python and Node; the evidence behind each selected test; confidence that falls back to "run everything" when the evidence cannot vouch for the selection |
| Re-run failures | `pytest --lf` | whether each failure is **new or was already there**, checked against the base commit with the same run shape |
| Run tests without touching your files | a container you set up | by default a disposable copy, no network, and a check that the working tree is byte-for-byte unchanged |
| Know whether a result still applies | nothing common | evidence tied to the exact change and test environment (`repo-ai evidence`, and a completion gate for agents) |
| Use a coding agent | the agent's own CLI | an isolated worktree, frozen tests, an independent check of the candidate, and you decide whether to apply it |

Measured for `verify` (held-out-7, five public projects in containers, build `903984a`): **0 false assurances in 127
failing states**, 0 new failures called pre-existing, 0 false alarms, and the working tree unchanged in 234 of 234
runs. The scope and the projects it does not cover are on [Evaluation & methodology](/repo-ai/docs/evaluation/).

## Where it is worse

- **Slower than running the suite yourself.** On 30 real upstream commits in five small pure-Python projects
  (speed-v1), `verify --run` took 1.84× the native suite in the preregistered run, and 1.96–2.23× in three later
  runs, slower on most changes. It costs time to buy the base comparison and the sandbox. It does not save time on
  small suites.
- **Fewer runners.** Jest, Vitest and Mocha always run the full suite (no per-test selection). unittest and
  TypeScript have no held-out qualification.
- **It runs in the project's environment.** If the project's test runner is not installed where verify runs the
  tests, nothing is verified, and verify never reports that as a pass.
- **Not shown to make agents better.** In a preregistered, blinded study (150 runs, 25 tasks) plain Claude scored 92%,
  and repo-ai's two configurations 90% and 88%. Every difference was inconclusive. Whether repo-ai improves an agent's
  results is `NOT_YET_DEMONSTRATED`.
- **No host sandbox on Windows.** `verify --run` needs containers there, and missions are not supported. The unit
  tests pass in CI, but Windows has never been measured on fresh data.

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
  A later trial with one conventions skill did measure one, with design limits stated on the evaluation page.
- **Blast-radius analysis on its own**: other tools already do it statically, with uncalibrated confidence.

The full scoring is `docs/ARCHITECTURE-DECISION-0.8.md` in the source tree. The prior-art survey behind it
(pytest-testmon, Jest and Vitest, and others, with their documented gaps) is `docs/RESEARCH-2026-10.md`.
