---
title: Status matrix
description: What in repo-ai is stable, a stable candidate, experimental, opt-in, disabled or unsupported, with the evidence behind each label.
---

Condensed from `docs/STATUS.md` in the source tree, which remains the record when the two differ.

## Labels

| Label | Meaning |
|---|---|
| **stable** | declared stable, with held-out or CI evidence for its main claim |
| **stable candidate** | implemented and tested, but its main claim has not had a fresh, preregistered validation |
| **experimental** | a fresh validation failed, or there is none; the output says so |
| **opt-in** | off by default |
| **disabled** | present in the registry or design, but repo-ai will not run it |
| **not supported** / **not demonstrated** | as written; the latter is for benefit claims |

## Evidence: verify

| Area | Status | Evidence, in brief |
|---|---|---|
| `verify`, overall (pytest, `node --test`) | qualified, conditional with explicit limitations | held-out-7 on `903984a`: 0 false assurances in 127 failing states; tree unchanged 234/234. See [Evaluation](/repo-ai/docs/evaluation/) |
| `verify --run` isolation and the base comparison | **stable** | isolation tests on seatbelt, bwrap and Docker in CI; hostile-test suite. Cancellation passes for the tested windows only |
| Read-only plan (changed units, linked tests, confidence) | stable candidate | three frozen held-out sets; held-out-6 found two selection defects on fresh data (a staged rename selected nothing; TypeScript tests under node's default discovery were not listed) |
| `verify --record` runtime evidence | stable candidate for pytest and `node --test` | held-out-7, containers only; unittest works but is not qualified |
| Adaptive run shape, per-test reports, caches, evidence reuse | experimental | development measurements and held-out-4 |
| Zero-configuration test command | experimental | 6 of 7 correct on held-out-5 |
| `--image` (dependencies in a local container) | experimental | held-out-3 and held-out-4 |
| TypeScript (type stripping) | rechecked, not freshly validated | one project; no held-out TypeScript quota |
| Hang watchdog | improved for unittest and pytest; node unchanged | rechecks on previously used projects; node target missed |
| Speed | experimental; target missed | slower than native on short suites |
| `Stop`-hook completion gate | experimental, opt-in | its tests pass; effect on agents not measured |
| Jest, Vitest, Mocha; monorepos with several runners | **not supported** | opaque runners: full suite only, one runner per invocation |

## Evidence: platforms

| Platform | Status |
|---|---|
| macOS | seatbelt host sandbox; containers |
| Linux | bubblewrap host sandbox (CI job); containers |
| Windows | **no host sandbox**: containers required for `verify --run`; missions not supported; unit tests pass in CI; never measured on fresh data |

## Context, review and setup

| Area | Status | Evidence, in brief |
|---|---|---|
| `context` (identity-first shortlist) | stable candidate | retrieval holdout, 18 repositories: strong on symbol names, weak on prose (recall@5 0.320) |
| `evidence`, `review`, `privacy`, `uninstall` | stable candidate | release-freeze journey: uninstall left the tree byte-identical; no network. `review` does not yet read verify evidence |
| Two sessions in one repository | stable candidate | locking and atomic writes covered by tests and an adversarial review |
| `--smart` (learned rules, generated skills) | experimental, opt-in | no benefit shown |
| `--feature-set full` | opt-in; no benefit shown | no subagent or skill invoked, about 10% higher cost |

## Missions and providers

| Area | Status |
|---|---|
| `repo-ai do` offline plan, `why`, `why-test-failed`, `agents doctor` | usable; no model needed |
| Live execution with IBM Bob, Codex CLI, agy (macOS) | works on small tasks; small n; Codex and agy cost `UNKNOWN` |
| Claude Code as a mission provider | **experimental** from 0.10.0 (macOS live-verified, n = 1 journeys; own login, file tools only) |
| Provider routing (`--agent auto`, `agents route`) | deterministic; does not check login or quota before a run |
| `apply` / `undo` | transactional; existing regular tracked files only |
| Live tournament (`--tournament`) / replay comparison (`--candidate`) | experimental; abstains on several distinct passes |
| `shortlist`, `coverage` | added in the 0.9.0 cycle; never correctness claims |
| Handoff and `--from-handoff` | experimental; integrity, not authentication; small constructed demos |
| `--role investigator` / `adversary` | experimental, advisory; same provider, so not independent review |
| Benefit over plain provider use | **NOT_YET_DEMONSTRATED** |

## Skills and capabilities

| Area | Status |
|---|---|
| `skills inventory` | stable candidate; offline, read-only |
| `skills vet` (skills) | stable candidate; pinned, quarantined, read-only |
| Plugin inspection | experimental; its fresh validation failed, plugins are never reported eligible |
| Third-party skills (discover, install, trials) | experimental; no controlled benefit shown for third-party skills (a preregistered trial showed a project-conventions skill installed by repo-ai raised convention adherence on one project: 8 of 8 tasks; see the Evidence Lab) |
| Capability registry (`capabilities list`, `show`) | stable candidate |
| Ruff security adapter | stable candidate; needs your approval in a terminal |
| Capability discovery (`recommend`, `candidates`, `select`) | experimental; preregistered evaluation failed |
| Constraints (`--deny`) | enforced when passed |
| Semgrep and dependency-audit adapters | disabled / not implemented |

## ProofLab

`repo-ai prove` is **not qualified**: experimental, opt-in and excluded from the supported capabilities. Its release
qualification found false proofs inside the narrowed scope; three are open and named in every report it writes. No
hook or gate calls it.

## Agent benefit

Does repo-ai make a coding agent succeed more often? **Not demonstrated.** The studies are summarised on
[Evaluation & methodology](/repo-ai/docs/evaluation/).
