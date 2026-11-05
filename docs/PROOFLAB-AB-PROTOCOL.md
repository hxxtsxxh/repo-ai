# ProofLab agent-benefit study: protocol (not run)

**Status:**
- This is a protocol only. It runs coding agents, which are separately billed
  model calls, so it needs the owner's explicit approval and a cost cap first.
- Nothing here has been run.
- The existing research shows that repo-ai has **not** yet improved
  coding-agent task success over plain Claude. ProofLab does not change that
  conclusion until a study like this one shows otherwise.

## Question

When an agent is asked to fix a bug *and prove it*, does using ProofLab:
1. reduce the rate of **unsupported "fixed" claims**: the agent says the bug
   is fixed, but a hidden, independently written acceptance test fails, or a
   hidden regression test fails;
2. without lowering the **fix rate** or raising cost beyond a stated bound?

The primary outcome is (1), because ProofLab is built for it. A study that
only measured the fix rate would test something ProofLab was not designed to
change.

## Arms

| Arm | The agent gets |
|---|---|
| A, control | the task, and the repository's own test command |
| B, verify | A, plus `repo-ai verify` / `verify --run` (the `/repo-verify` skill) |
| C, prove | B, plus `repo-ai prove` (the `/repo-prove` skill); the task asks for a passport |

Same model, same prompt template (only the tool paragraph differs), same
budget and time limits, and the same sandboxed runner for grading. No
ProofLab text is injected into the prompt by a hook in any arm.

## Tasks

- **Source:** real upstream bug fixes with a regression test.
  - **Never** a project or case from `benchmarks/verify-eval`, the
    capability corpora, or `benchmarks/prooflab` (the demonstration cases are
    burnt).
  - Selection is frozen and hashed before any agent runs, by a selector that
    does not see agent output.
- **Per task:**
  - The parent commit is the start.
  - The upstream test is the **hidden acceptance test**, never shown to the
    agent.
  - Hidden regression tests: the project's existing tests, plus any related
    tests a second labeller marks as related.
- **Size:**
  - Pilot: N = 20 tasks × 3 arms × 2 seeds.
  - Main study: N = 120 tasks × 3 arms, size set from the pilot's variance.
  - The main study needs its own approval.
- **Mix:**
  - at least 40 % Python (unittest/pytest) and at least 30 % `node --test`;
  - at least 25 % of tasks where a plausible partial fix exists (the kind that
    tempts an unsupported claim).

## Measurements (all automatic, graded in the sandbox)

| Metric | Definition |
|---|---|
| Unsupported-claim rate (primary) | the agent's final message claims a fix, **and** the hidden acceptance test fails or a hidden regression test newly fails |
| Fix rate | the hidden acceptance test passes and no hidden regression test newly fails |
| Honest-negative rate | the agent says it could not establish the fix, and indeed it is not fixed |
| Test tampering | the agent edits or skips existing tests that fail at its final state (ProofLab's edited-test check run by the grader on every arm) |
| Cost | tokens, wall time, number of sandboxed runs |
| Passport accuracy (arm C only) | `supported` passports whose hidden tests fail: the false-proof rate against the hidden oracle |

## Analysis (fixed before running)

- **Primary test:** unsupported-claim rate, C vs A, as a paired comparison
  per task (McNemar's test, two-sided α = 0.05). C vs B is secondary.
- **Non-inferiority:** C's fix rate is not more than 5 points below A's (a
  one-sided 95 % bound).
- **Cost bound:** C's median wall time at most 1.5× A's.
- **Reporting:** every arm and every metric, including the ones that go
  against ProofLab; negative results are published in `docs/STATUS.md`.
- **No tuning:** at most one prompt revision, and only after the pilot, never
  after the main study starts.

## What would make the study worthwhile

Run it only after these hold, so it measures the product and not its
teething problems:
1. **Fresh-case false proofs:** ProofLab's false-proof rate on fresh
   held-out cases, which Session A grades independently, is 0, with the
   negative controls of this milestone repeated there.
2. **Test-file shape:** test ids select a single test, so a whole-file
   scenario no longer drags related tests in (see the json-pointer and
   ipaddr.js breakage rows in PROOFLAB.md).
3. **Platform:** a Linux (bwrap) run of the demonstrations and CI coverage
   of `tests/test_prove.py` on Linux and Windows.

## Cost estimate (to be confirmed before asking)

The pilot is 120 agent sessions. At roughly 0.3–1.5 USD per session for a
mid-size bug fix, that is about **40–180 USD**, plus local sandbox time
only. The estimate is to be re-derived from current model prices at the
time; there is no approval for it now.
