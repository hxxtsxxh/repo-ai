# journey-offline-v2: results

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md), committed with the harness at fc329dc before the run. One run:
GitHub Actions [41265931090](https://github.com/hxxtsxxh/repo-ai/actions/runs/41265931090) (job offline-v2),
ubuntu runner, bwrap. Raw: [results/run-1.json](results/run-1.json). Spend: $0; no provider, no model.

**7 defects** in 4 projects, each a real upstream fix (3 are merge commits, 4 squash-merged pull requests) whose test
changes alone make the project's own suite fail. itsdangerous had no qualifying candidate within the scan.

| defect | `verify --record` | test without the fix: native, verify | the fix: native, verify | uninstall vs original |
|---|---|---|---|---|
| pyjwt 33022c25 (merge) | 0 | fail, **regression** | pass, failing (`tests/test_jwks_client.py` pre-existing; likely network, not recorded) | clean |
| pyjwt 6dc23b3c (#1005) | 0 | fail, **regression** | not measured (the harness could not apply the whole change) | clean |
| humanize 2968d442 (#250) | 0 | fail, **regression** | pass, **selected passed** (full suite not run) | clean |
| humanize 43d6dc61 (#159) | 0 | fail, **regression** | pass, **selected passed** (full suite not run) | clean |
| more-itertools 719a333b (#720) | 1 (no test command) | fail, refused (no test command) | pass, refused (no test command) | clean |
| more-itertools 146113bb (#714) | 1 (no test command) | fail, refused (no test command) | pass, refused (no test command) | clean |
| marshmallow de5e842a | 0 | fail, **regression** | pass, **selected passed** (full suite not run) | clean |

**Gates.**
- **J1 (no false assurance): 0 of 7.** In all 7 states where the native suite failed, verify did not pass; 5 were
  reported as `regression` (these test detection), 2 refused for want of a test command (these pass the gate by
  refusing). Each failing test was one of the changed test files, which verify selects directly: the easiest case for
  selection. Small samples: 0 of 7 bounds the false-assurance rate at about 35% (95%), 0 of 5 at about 45%.
- **J2 (the fix passes where the native suite passes): 3 of 6**, each as "selected passed (full suite not run)". The 3
  others: pyjwt's `tests/test_jwks_client.py` failed at base and change alike (pre-existing); that it needs the
  network is an inference (the harness did not keep verify's `sandbox_network_suspected` field). more-itertools gave
  verify no test command it trusts ("no trustworthy test command"), so verify refused instead of guessing; the likely
  cause, from the source (`testing.py` recognises `import unittest` / `unittest.TestCase`, not `from unittest import
  TestCase`), is a suite framework left "unknown", which the fallback skips; not shown by this run, and the pinned
  v10.7.0 was not measured.
- **J3 (uninstall restores the original revision): 7 of 7**, no tracked difference and no untracked, non-ignored
  file. Ignored leftovers, `.git/` and repo-ai's registry outside the repository were not checked.

**Deviation from the preregistration:** it says "fresh clone at the base B"; the harness reused one clone per project,
so each project's second defect ran after the first one's install and uninstall (`git clean -fdq` keeps ignored
files). The whole-change apply failure for pyjwt 6dc23b3c is unexplained (the harness discarded `git apply`'s error).

**What this shows for C21 (offline half):** on real fixes from real projects, verify did not give false assurance
(small sample) and uninstall left no tracked or untracked difference; it confirmed the fix in 3 of 6 cases and refused or flagged
the others for stated reasons. The live half (a provider journey) still needs a live-call budget.

**Follow-up (queued):** check, then fix, the likely cause of more-itertools' missing test command (a `from unittest
import TestCase` suite left "unknown").
