# journey-live-v1: results (2026-11-03 UTC)

**Setup.** The protocol is [PREREGISTRATION.md](PREREGISTRATION.md), including amendment 3, which was written before
any live session. Raw records (paths redacted): [results/run-2026-11-03.jsonl](results/run-2026-11-03.jsonl).
- repo-ai 0.12.1, installed fresh from PyPI.
- Claude Code 2.1.317, in repo-ai's isolated live mode on the dedicated login `claude-provider`.
- macOS (seatbelt) host, with every project test run inside podman containers built from pinned images.
- One run.

## Stages

- **prep (no model):** the four MIT defects qualified at their pinned bases. The frozen tests fail natively, and the
  upstream fix makes them pass.
- **control (no model):** the first control stage gave INCONCLUSIVE for all four. The harness was reading the
  effective verdict of container runs; amendment 3 fixed that, and the stage was re-run:
  - humanize: PASS;
  - more-itertools: PASS;
  - pyjwt: PASS_WITH_PRE_EXISTING_FAILURES;
  - **marshmallow: INCONCLUSIVE.** Its baseline and candidate observations were judged "untrusted, incomplete,
    environmentally unstable or not cleaned up". Under the protocol it got no session.
- **onboarding (zero provider):** `repo-ai verify --run --sandbox podman` on each project reported the frozen failing
  tests as a regression, with targeted selection. These are the same tests the native check found.
- **live (3 Claude sessions):**

| Defect | Verdict | Cost | What happened |
|---|---|---|---|
| humanize | BLOCKED | $0.040707 (OBSERVED) | Claude used Read and Edit. repo-ai refused the result: "provider created untracked file outside frozen tracked set: src/humanize/_version.py". **This is a repo-ai defect:** repo-ai itself copies the declared hatch-vcs version file into the candidate, then blamed it on the provider (fixed in #125) |
| more-itertools | BLOCKED | UNKNOWN (capped at $1.00 by `--max-budget-usd`) | Claude used Grep, Read, Grep and Edit. One event line (a Read of the 150 KB `more.py`) went past repo-ai's 64 KB capture, so the run was killed (-9) and its cost lost. **This is a repo-ai defect** (fixed in #125) |
| pyjwt | **PASS** | $0.046787 (OBSERVED) | Claude used Grep, Read and Edit. On the frozen tests natively in the container, nothing that upstream fixed still fails and there are no new failures. The hidden upstream oracle shows no behavioural difference from upstream. Post-apply verification PASS; undo byte-identical |

- **recovery (no model):** a failure-recovery mission was classified `environment` and not reported as passing.

## Gates

| id | Measure | Result |
|---|---|---|
| L1 | PASS missions still failing natively | **0** (pyjwt: none) |
| L2 | PASS candidates with a behavioural difference from upstream | 0 of 1 (reported, not called correct) |
| L3 | applies whose undo is not byte-identical | **0** |
| L4 | project code executed on the host | **0** (by construction) |
| L5 | failure recovery reported as passing | **0** |
| L6 | Claude sessions / reported cost | 3 of ≤ 4; $0.0875 reported, plus one UNKNOWN session capped at $1.00: total **UNKNOWN**, at most $1.09 |

Pass rate: 1 of 3 sessions (1 of 4 defects), with no gate. Three sessions have no power for a rate.

## Reading

The journey works end to end on a real project. On pyjwt, repo-ai onboarded with no provider, ran Claude Code in
isolation on a real upstream defect, and verified the candidate against the frozen tests and a hidden upstream
oracle. The change was applied and undone exactly, and every gate held.

The two failed sessions were repo-ai's fault, not Claude's:
- a build-generated version file was blamed on the provider;
- a large tool result killed the run.

Both now have fixes and tests (#125), which also rules out the false PASS that a lenient fix might have introduced.
These results describe repo-ai 0.12.1. Rerunning with the fixes would be a new, separately approved run, not a
correction of this one.

**Follow-up (2026-11-04, no model call): the marshmallow control.** The control was re-created exactly as the
harness does it (same work clone, upstream fix as a replay, same podman image) and kept its records this time. It
had two causes:
1. **A repo-ai defect.** marshmallow's `norecursedirs` keeps `tests/mypy_test_cases/test_*.py` out of pytest's
   full run. The mission observation still counted them as discovered and called both observations incomplete, even
   though verify already handles this. That is fixed in the follow-up PR (`config_excluded`, with tests); with the
   fix, both observations are complete (1104 tests, baseline 1 failure, candidate 0).
2. **A property of the project.** `test_invalid_datetime_deserialization` is parametrized with the current time, so
   its test IDs differ between any two runs, and a baseline and candidate can never have the same tests. repo-ai's
   refusal is correct; its message now names the differing IDs.

So marshmallow stays INCONCLUSIVE by design, for a reason that is now visible and stated, not hidden behind an
incomplete-observation message. The original records are unchanged; this was not a new session and changed no
verdict above.
