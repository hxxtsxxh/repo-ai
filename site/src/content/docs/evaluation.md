---
title: Evaluation & methodology
description: What has been measured about repo-ai, how, with what caveats, and what remains NOT_YET_DEMONSTRATED.
---

This page reports results as recorded, including the ones that did not go repo-ai's way. Every number has a scope;
none of them generalises beyond it.

## Methodology, in common

- **Preregistration.** Hypotheses, task sets, arms and decision rules are written down and frozen before any measured
  run. A `manifest.json` records the SHA-256 of tasks, hidden tests and the grader; a script re-checks it.
- **Hidden graders.** Agent studies grade candidates with hidden tests that never enter an agent's workspace or
  prompt, in a separate copy. Only the allowed write paths of a candidate are graded.
- **Controls.** Each task ships free controls: the untouched repository must grade FAIL, a reference solution
  CORRECT, and a plausible decoy FALSE_GREEN. These caught defects in the study materials before freezing.
- **Deviations are disclosed** in each study's results, and invalid runs are kept and flagged rather than deleted.
- **Authorship caveat.** The agent-study tasks, hidden tests, harnesses and write-ups were authored by an AI agent,
  and the tasks are small and synthetic. These are not independent evaluations.

## Verify: held-out-7

The current qualification of `repo-ai verify`, run by a separate evaluation session on build `903984a`.

| Measure | Result |
|---|---|
| False assurances (a failing state reported as passing) | **0 in 127 failing states** |
| New failures classified as pre-existing | 0 |
| False alarms | 0 |
| Runtime no-miss rate | 96.7% |
| Working tree unchanged | 234 of 234 runs |
| Speed vs. the native suite | slower on 3 of 5 projects (1.44–2.31×); no general speed advantage |

**Scope:** five public projects, frozen and independently labelled, using pytest and `node --test`, run in podman
containers. The verdict is *conditional, with explicit limitations*. **Not qualified:** unittest and TypeScript (no
held-out quota), Jest/Vitest, and host sandboxes on held-out data (they are covered by the test suite and CI sandbox
jobs). This is evidence for that build and container scope, not for every later build, and not evidence that verify
helps a coding agent.

Earlier held-out sets (held-out through held-out-5, 37 projects in all) measured selection and wall-clock time; they
found and fixed defects along the way, recorded in `docs/VERIFY.md` in the source tree.

## Missions: the abc studies

Each study compares arm A (the bare provider CLI) with arm B (the same provider through `repo-ai do`), and sometimes
arm C (a tournament). One run per cell.

| Study | Provider | Tasks | Result | What it shows |
|---|---|---|---|---|
| abc-v1 | IBM Bob | 4 | A: 2 CORRECT, 1 FALSE_GREEN, 1 FAIL. B: 3 CORRECT, 1 FALSE_GREEN | One task of four differs; consistent with noise. On `node-slug`, repo-ai reported PASS for a candidate that failed a hidden requirement the visible tests never stated: the counterexample to reading PASS as "correct" |
| abc-v2 | Codex CLI | 4 | 8 of 8 cells CORRECT | Ceiling effect: no evidence of lift or of harm |
| abc-v3 | Codex (A/B), Codex + agy (C) | 4 | A and B CORRECT on all 4; C **abstained** 4 of 4 | Ceiling again. Both tournament arms passed with different diffs every time, so the no-tie-breaker rule abstained |
| abc-v4 (pilot) | Codex CLI | 2 | A CORRECT on both; B and C NOT_RUN by the preregistered pilot rule | The bare provider was already at the ceiling on longer, exact specifications |

**Verdict: comparative lift over a standalone agent is `NOT_YET_DEMONSTRATED`.** On small, fully specified tasks a
strong provider already succeeds alone, so these designs cannot measure lift. Measuring it would need tasks the bare
provider fails at a non-trivial rate, at least 20 paired tasks, repeated runs and an authorised budget. That would be a
new study, not a change to these.

Cost was provider-reported for Bob and `UNKNOWN` for Codex and agy (subscription logins).

## Context: retrieval

| Set | Result |
|---|---|
| Retrieval holdout, 18 repositories (shipped ranker) | recall@1: exact symbol 0.858, renamed symbol 0.883, symbol named in an issue 0.551 |
| Same holdout, natural-language and error-message queries | recall@5 **0.320**: prose queries are weak |
| Sealed split, 25 re-injected upstream bugs in 6 projects (recall@5 / all-gold@5 / MRR) | 0.853 / 0.800 / 0.606, against 0.580 / 0.560 / 0.420 for grep |
| Synthetic holdout | MRR 0.574 against 0.520 for grep, but recall@5 below grep (0.674 vs 0.735) |

The bundled `benchmarks/run.py` gold set is small and serves as a regression guard, not as evidence of quality.

## Claude Code with repo-ai context

| Study | Result |
|---|---|
| Option A (preregistered, blinded; 150 runs, 25 real-repository tasks) | plain Claude 92%, repo-ai Core 90%, repo-ai Full 88%. Every difference inconclusive; equivalence not shown either. Full cost about 10% more |
| Sealed-v2 pairs (exploratory; 25 tasks, one run each) | plain 92%, Core 84%; the −8 points are inconclusive (95% CI −22 … +7) |

**Agent benefit: not demonstrated.** Earlier recorded runs also showed agents rarely call optional tools (0 skill
invocations in 212 runs), which is why the verify completion gate exists; its effect on agents is unmeasured.

## Not yet demonstrated

- Comparative lift of `repo-ai do` (or tournaments, or handoffs) over using a provider directly.
- That repo-ai context makes Claude Code or any agent succeed more often.
- That the opt-in verify completion gate changes agent outcomes.
- That a tournament beats a single agent, or that a handoff beats a restart.
- Any qualification of ProofLab (`prove`): it is not qualified and has known open false-proof classes.
- Any fresh-data evaluation on Windows.

The status of each capability, with its evidence, is on the [Status matrix](/repo-ai/docs/status/).
