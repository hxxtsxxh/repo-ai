---
title: Introduction
description: What repo-ai is, the three things it does, who it is for, and what it does not claim.
---

repo-ai is a command-line tool that runs on your machine, inside a Git repository. It has three parts, and each
works without the ones after it.

| Part | What it does | Needs an agent? | Runs your code? |
|---|---|---|---|
| **Context** | Indexes the repository offline and answers "where should I start for this task?", "what can this change reach?" and "why was this file ranked?" | No | No |
| **Evidence** | `repo-ai verify` lists what a change touched and which tests can show a break; `verify --run` runs them sandboxed in a disposable copy and separates new failures from ones already present at the base commit | No | Only with `--run`, sandboxed |
| **Agents** (optional, experimental) | `repo-ai do` plans a task offline and, only with explicit consent, asks a coding agent for a candidate in an isolated worktree, checks it against frozen tests, and leaves applying it to you | Only for live runs | Only with `--run`, sandboxed |

## Who it is for

- Developers who want a quick, explainable answer to "which files and tests matter for this change?"
- Anyone who wants to run the relevant tests before pushing without letting those tests touch the working tree.
- People experimenting with coding agents who want the agent's output treated as an untrusted candidate, not as
  a finished change.

## What it is not

- **Not a proof of correctness.** A PASS means the frozen tests observed a pass. It does not mean the task is
  correct: the tests may not state the requirement that matters. See [Requirement coverage](/repo-ai/docs/coverage/).
- **Not a hosted service.** There is no daemon, no account and no telemetry. Nothing goes over the network unless you
  pass a flag that asks for it (listed on [Security & privacy](/repo-ai/docs/security/)).
- **Not shown to make agents better.** Whether repo-ai improves a coding agent's results over using the agent alone is
  `NOT_YET_DEMONSTRATED`. The studies so far are on [Evaluation & methodology](/repo-ai/docs/evaluation/).

## Where to go next

1. [Install](/repo-ai/docs/install/) — Python 3.10–3.14, macOS, Linux or Windows.
2. [Quickstart](/repo-ai/docs/quickstart/) — index a repository and verify a change, no agent needed.
3. [Verify a change](/repo-ai/docs/verify/) — the plan, the sandboxed run and the evidence it keeps.
4. [Status matrix](/repo-ai/docs/status/) — what is stable, experimental or unsupported, and why.

If you want agents in the loop, read [Missions with agents](/repo-ai/docs/missions/) and
[Providers](/repo-ai/docs/providers/) before running anything live.
