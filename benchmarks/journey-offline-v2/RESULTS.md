# journey-offline-v2: results

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md), committed with the harness at fc329dc before the run. One run:
GitHub Actions [41265931090](https://github.com/hxxtsxxh/repo-ai/actions/runs/41265931090) (job offline-v2),
ubuntu runner, bwrap. Raw: [results/run-1.json](results/run-1.json). Spend: $0; no provider, no model.

**7 defects** in 4 projects, each a real upstream fix (3 merged through pull requests) whose test changes alone make
the project's own suite fail. itsdangerous had no qualifying candidate within the scan.

| defect | `verify --record` | test without the fix: native, verify | the fix: native, verify | uninstall vs original |
|---|---|---|---|---|
| pyjwt 33022c25 (merge) | 0 | fail, **regression** | pass, failing (pre-existing: network-dependent test) | clean |
| pyjwt 6dc23b3c (#1005) | 0 | fail, **regression** | not measured (the harness could not apply the whole change) | clean |
| humanize 2968d442 (#250) | 0 | fail, **regression** | pass, **passed** | clean |
| humanize 43d6dc61 (#159) | 0 | fail, **regression** | pass, **passed** | clean |
| more-itertools 719a333b (#720) | 1 (no test command) | fail, refused (no test command) | pass, refused (no test command) | clean |
| more-itertools 146113bb (#714) | 1 (no test command) | fail, refused (no test command) | pass, refused (no test command) | clean |
| marshmallow de5e842a | 0 | fail, **regression** | pass, **passed** | clean |

**Gates.**
- **J1 (no false assurance): 0 of 7, with power.** In all 7 states where the native suite failed, verify did not
  pass; 5 were reported as `regression`, 2 refused for want of a test command.
- **J2 (the fix passes where the native suite passes): 3 of 6.** The 3 others: pyjwt's JWKS tests need the network,
  which verify's sandbox denies (labelled pre-existing; #43's hint names this); more-itertools at these older commits
  gave verify no test command it trusts (its fallback skips a suite whose framework the index left as "unknown",
  although the files are `unittest` tests), so verify refused instead of guessing.
- **J3 (uninstall restores the original revision): 7 of 7**, no tracked difference and no untracked file.

**What this shows for C21 (offline half):** on real fixes from real projects, verify did not give false assurance
and uninstall left the projects exactly as they were; it confirmed the fix in 3 of 6 cases and refused or flagged
the others for stated reasons. The live half (a provider journey) still needs a live-call budget.

**Follow-up (queued):** infer a unittest runner from `TestCase` files when the index's suite framework is
"unknown" and no declared command splits (more-itertools at older commits).
