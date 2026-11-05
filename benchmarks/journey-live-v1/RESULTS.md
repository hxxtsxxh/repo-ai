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
   full run. The mission observation still counted them as discovered and called both observations incomplete
   (verify only notes such files; `verify --record` removes them from pytest's own recorded collection). #131
   accepts such a file as absent when the project's `norecursedirs` explains it by a confirmed reading and pytest
   did not collect it (`config_excluded`, with tests). Re-run with #131: both observations complete, 1104 tests,
   baseline 1 failure, candidate 0 (`results/followup-marshmallow-control-2026-11-04.jsonl`).
2. **A property of the project.** `test_invalid_datetime_deserialization` is parametrized with the current time, so
   its test IDs differ between any two runs, and a baseline and candidate can never have the same tests. repo-ai's
   refusal is correct; its message now names the differing IDs (in the same record).

So marshmallow stays INCONCLUSIVE by design, for a reason that is now visible and stated, not hidden behind an
incomplete-observation message. The original records are unchanged; this was not a new session and changed no
verdict above.

## Re-run under amendment 4 (2026-11-04 UTC): BLOCKED again, by a revoked login ($0, no model turn)

Owner-approved scope: humanize and more-itertools, at most 2 Claude sessions, $1.00 cap each. repo-ai 0.12.4 fresh
from PyPI, Claude Code 2.1.318, the dedicated login, a new work directory. Raw records (paths redacted, mission
records summarised as above): [results/rerun-2026-11-04.jsonl](results/rerun-2026-11-04.jsonl).

- **prep (no model):** both defects qualified again (frozen tests fail at the base, pass with the upstream fix, in
  dependencies-only images).
- **control (no model):** both PASS as observed (exit 2 only because a container image is reported `not checked`,
  the amendment-3 reading).
- **First `run` attempt (no model call):** the harness refused both defects: two repo-ai workspaces were left in the
  shared workspace directory outside HOME. They came from a local test run of repo-ai's own suite that had been
  stopped midway (toy `charge.py` fixtures, creating process gone), not from this study. They were removed and the
  stage re-run, as the protocol allows before any model call. The guard did its job.
- **Second `run` attempt: 2 sessions started, both BLOCKED before any model turn.** Claude Code reported
  `authentication_failed`: "OAuth token revoked. Please log in again". Reported cost $0.00 for each (OBSERVED), no
  tool call, no candidate. `claude auth status` on the same login still says `loggedIn: true` (expiry 2026-12-02):
  it checks only locally. The credential file's access-token expiry was set to 0 by the CLI at the failure; the
  refresh token is still dated 2026-12-02 locally, so the revocation was server-side. Nothing points to repo-ai's
  sandbox as the cause (the config directory and keychain files stay writable for refreshes, and the CLI did write
  the file).

| defect | verdict | reported cost | what happened |
|---|---|---|---|
| humanize | BLOCKED | $0.00 (OBSERVED) | provider error `authentication_failed` (OAuth token revoked) before any model turn |
| more-itertools | BLOCKED | $0.00 (OBSERVED) | the same |

Gates: L1 0 (no PASS), L3 not reached, L4 0, L6 2 sessions / $0.00. repo-ai handled it correctly as far as it
goes: BLOCKED, never a pass, cost observed. Its recovery advice was generic (`repo-ai agents setup <provider>`); the
exact re-login step is added in #143. No session was repeated. The two defects' live journeys on a fixed repo-ai
remain undemonstrated: a further attempt needs the owner to log the dedicated login in again
(`CLAUDE_CONFIG_DIR=~/.local/share/repo-ai/claude-provider claude auth login`) and a decision on whether the
approval for these 2 sessions (none of which reached a model) covers one more attempt.

## Retry under amendment 5 (2026-11-05 UTC): both journeys PASS end to end ($0.1233)

After the owner logged the dedicated login in again: repo-ai 0.12.4 (PyPI), Claude Code 2.1.318, a third work
directory, prep and positive controls PASS again. Raw records (paths redacted, mission records summarised):
[results/retry-2026-11-05.jsonl](results/retry-2026-11-05.jsonl).

| defect | mission | reported cost | L1 (native, frozen) | hidden oracle | apply / undo |
|---|---|---|---|---|---|
| more-itertools | PASS (Grep, Grep, Edit) | $0.084002 (OBSERVED) | 0 frozen still failing, 0 new failures vs upstream | 0 behavioural differences | applied (post-apply PASS, 595 tests in the container); undo byte-identical |
| humanize | PASS (Read, Edit) | $0.039266 (OBSERVED) | 0 / 0 | 0 differences (this defect's oracle equals its frozen tests: no independent holdout) | applied; undo byte-identical |

- Both missions exit 2 only because the container image is reported `not checked` (amendment-3 reading; the
  passport is PASS and `apply` re-runs the tests in that image).
- The first `run` invocation started more-itertools but refused humanize before any model call: one repo-ai workspace
  existed at that moment in the shared workspace directory, from a concurrent local test run of repo-ai's own suite.
  humanize was run once the directory stayed empty, as the protocol allows before a model call. Session count from
  the records: 2 of 2.
- Gates for this retry: L1 0, L3 0 (2 successful applies, both undone byte-identically outside `.repo-ai/`), L4 0,
  L6 2 sessions / $0.1233 of $2.00. L5 (failure recovery) was not re-run: the harness runs it only after all four
  defects were started or skipped in the work directory, and amendments 4 and 5 leave pyjwt and marshmallow out; the
  2026-11-03 recovery result stands.
- With the 2026-11-03 run, three of the four defects (pyjwt, more-itertools, humanize) now have a live Claude journey
  that passed every gate on a released repo-ai; marshmallow stays INCONCLUSIVE by design. The upstream fixes predate
  the model's training data, so a candidate matching upstream may be recall (a stated limit of this study).

