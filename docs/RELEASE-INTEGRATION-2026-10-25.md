# Release integration, 2026-10-25 (Session B, main-branch owner)

**Starting point:** main `083b6f1`. Session A's fresh evaluation of it, held-out-6
([VERIFY-PHASE2-RESULTS-2026-10.md](VERIFY-PHASE2-RESULTS-2026-10.md)), **missed the
false-assurance gate**:
- D9, a staged rename gives `nothing-selected`, reproduced on 5 of 5 fresh projects;
- D10, TypeScript tests under plain `node --test`, gives verify no test file at all.

That failure stands. Nothing below re-labels it.

## Open PRs and their heads

| PR | Head | What | Owner | Contained in |
|---|---|---|---|---|
| #39 | `7aafa48` | evidence contract `repo-ai.proof-evidence/1`, version 1.1 | A | #44 holds the older head `501e6dd` |
| #40 | `5af9e70` | verify never executes a committed virtualenv interpreter (T24) | B | #44 |
| #41 | `516b6cc` | D9: a renamed module is a behavioural change | A | #44 |
| #42 | `d4f3939` | D1–D4: the report outranks exit status 0; xfail, node no-test files, base time-outs | A | #44 |
| #43 | `fd6e61b` | D5–D8: the fingerprint covers every byte the copy reads | A | #44 holds the older head `0fdf497` |
| #45 | `56e57f8` | D10: node's default discovery includes TypeScript tests | A | no |
| #46 | `648b40c` | held-out-6 results, findings, STATUS | A | no |
| #48 | `a8a954a` | **abstention**: nothing selected on a behavioural change is `not verified`, as is a required full suite that cannot run | A | no |
| #49 | `3e7a8aa` | `--deadline` governor: a run cut by its time budget is never a pass (stacked on #42) | A | no |
| #50 | `b2a0e70` | macOS: a seatbelt run's processes are found by their sandbox and killed (T7) | A | no |
| #51 | `0688348` | the environment key sees a package edited in place (X13; stacked on #43) | A | no |
| #52 | `4247f5e` | evidence graph foundation, not wired (**draft**) | A | not integrated: a draft |
| #44 | see below | ProofLab | B | — |

**Overlapping files:**
- `verify/changes.py`: #41 and #43, in different functions; the merge is clean.
- `docs/STATUS.md`: #46 and #44; auto-merged.
- `docs/VERIFY-PHASE2-FINDINGS-2026-10.md`: #39 and #46, the same content.

## Integration batches

| Batch | Branch | Contents (merge order) | Why this order |
|---|---|---|---|
| 1, correctness | `prove/prooflab-mvp` (#44), which merges them in this order | #40, #41, #43@`fd6e61b`, #42, #45, #39@`7aafa48`, #46, #48, #50, #49, #51 | the fixes first, the contract and the results after |
| 2, ProofLab | the same branch | ProofLab, with every finding of Session A's assessment and of four independent challenge rounds fixed or documented | #44 already held old heads of #39 and #43. Merging the new heads brings them in with no duplicate commits; the old heads are their ancestors |

**Two conflicts, resolved on that branch:**
- **#48 and #49** both change `evidence.verdict`. It now takes both `behavioural` (#48) and `incomplete` (#49).
- **#51 and #42** both change `verify/cache.py`. It keeps #42's `RULES` and #51's content-aware `_tree_id`.

**Superseded:** Session B's own abstention commit (`61d0310`, on `fix/verify-abstain`) duplicated #48 and is reverted on the integrated branch (`275e55c`). #48, the verification authority's version, is the one integrated. It covers one more case: a required full suite that cannot run.

**Merging to main:**
- Each PR merges with a merge commit, in the batch order above, **after one CI run on the exact final
  tree** (the head of #44).
- The tree on main after the last merge must equal the tested tree (`git diff` empty). Only then do
  the merge commits carry `[skip ci]`; otherwise main's own push run decides.

## Abstention (#48)

**The invariant:** repo-ai never claims a change is verified when the evidence it needs is missing,
incomplete, stale, unsupported or contradictory.

**How #48 applies it:**
- **Behavioural change, nothing selected:** that used to pass as `nothing-selected`. It is now `not verified:
  no test is linked to the behavioural change (nothing was selected)`, which exits 1.
- **Full suite required but not runnable:** `not verified: the full suite is required for this change and
  could not be run`.
- **Unchanged:** documentation, comment and formatting changes still pass as `nothing-selected`.

**Migration:** consumers that follow `VERIFY-AGENT-CONTRACT.md` (pass only on the three passing prefixes)
need no change, and now fail safe on these runs. To verify such a change, run `verify --run --full`.

## Release-risk register

| # | Risk | State | Mitigation / owner |
|---|---|---|---|
| R1 | False assurance in verify (D1–D10) on fresh data | **open until re-measured** | fixes #41–#45 merged in batch 1; a **fresh** evaluation of the integrated tree by Session A is required before any "verified" release claim |
| R2 | `nothing-selected` reads as success | closed by #48 | `tests/test_verify_nothing_selected.py` |
| R3 | ProofLab false proofs | **3 documented classes remain** (see `PROOFLAB.md` "Limits") | Session A's F1–F5 and 4 rounds of independent challenge (10, 5, 5, 3 findings) fixed; awaits Session A's re-assessment |
| R4 | Detached processes outlive a run on macOS (T7) | closed by #50, pending CI | `tests/test_sandbox_descendants.py` |
| R10 | An installed package edited in place keeps the environment key (X13) | closed by #51 | `tests/test_verify_environment_key_in_place.py` |
| R11 | `repo-ai evidence` and the gate never compare the environment (X13b, raised by Session A) | **open** | a separate decision: the gate runs on every Stop hook |
| R12 | A hung test costs the whole hard limit | improved by #49 (`--deadline`) | opt-in |
| R13 | Windows: #51's tree identity is not stable between two reads (CI 40225661892) | **open** (Windows only) | it only prevents evidence reuse there, never yields a wrong verdict; the test is `xfail` on Windows with this reason |
| R14 | CI run 1 failed on Windows: 9 and 10 tests | resolved, pending CI run 2 | not defects in the product: fixtures that assumed no `core.autocrlf` (GitHub's Windows runners set it) and `Path.write_text`'s CRLF; a venv-layout test skipped on Windows; `signal.SIGKILL` (absent on Windows) replaced by a fallback in the macOS sweep. The line-ending behaviour itself was checked under `core.autocrlf=true` on macOS: the fingerprint changes as it should |
| R5 | Windows: no host sandbox, never measured | **open** | support scope: Windows needs a container backend; claims say "not validated" |
| R6 | Verify speed on sub-second suites | open (performance) | not a correctness blocker |
| R7 | Local passports can be forged by anyone who can write `.repo-ai/state` | accepted, documented | ProofLab "checks for mistakes, not a hostile candidate"; reviewers re-run |
| R8 | An untracked virtualenv planted in the working tree is executed by the host-side interpreter probes | accepted, documented (T24 residual) | run the probes inside the sandbox (post-release) |
| R9 | Agent benefit unmeasured | open | A/B protocol `docs/PROOFLAB-AB-PROTOCOL.md`; not run, because it has no budget |

## Spending ledger (shared by both sessions; cap $10.00 for this mission)

Session B coordinates every paid workflow. The rates are GitHub's published per-minute prices, applied
conservatively: Linux $0.008, Windows $0.016, macOS $0.08. Every job is rounded up to the minute.

| # | Date | Session | Purpose | Workflow | Reserved | Actual | Remaining |
|---|---|---|---|---|---|---|---|
| — | 2026-10-25 | — | start | — | — | — | $10.00 |
| 1 | 2026-10-25 | B | CI on the exact final tree (13 jobs including macOS) before merging #39–#51 and #44 | `ci.yml` dispatch, run 40225661892 on `8288b2f`: 11 of 13 passed, Windows failed | $4.00 (estimate $1.90) | **$1.79** (Linux 40, Windows 32, macOS 12 minutes) | $8.21 |
| 2 | 2026-10-25 | B | re-run after the Windows fixes (R14) | `ci.yml` dispatch, run 40227757898 on `643e47d`: **13/13** | within the same $4.00 reservation ($2.21 left of it) | **$1.95** (Linux 38, Windows 38, macOS 13 minutes) | **$6.26** |
| 3 | 2026-10-25 | B | PR #53 (audit F1) with the integrator's fixes, before integrating it | `ci.yml` dispatch, run 40230548016 on `4c22808` (`integration/pr53`): **13/13**, bwrap included | $2.00 | **$1.86** (Linux 39, Windows 37, macOS 12 minutes) | **$4.40** |

| 4 | 2026-10-25 | B | the corrective integration (#53 with its review fixes, F2b, X13b, ProofLab's false-proof fixes) | `ci.yml` dispatch, run 40246695220 on `4d91b85` (`integration/corrective-20261025`): **13/13**, bwrap included | $2.30 | **$2.21** (Linux 42, Windows 37, macOS 16 minutes) | **$2.19** |

#53 was **not** integrated after run 3. An independent security review then found that a committed config
could still exclude `.git/`, `.git/hooks`, `.bob/...` or ignored and absent directories from the integrity
check. Those were fixed in `e80a903`, and the defensive reviews' findings in `dc560b8` and `7121341`. #53 is
integrated with the corrective phase: main was fast-forwarded to the CI-tested `4d91b85`, then this
docs-only commit was added.

| 5 | 2026-10-26 | B | PR #58: the integrity check reconciled with Session A's rework of #53 (`dcf1e24`) | `pull_request` run 40251611104 on `765cc3c`: **12/12** (`test-macos` skipped on pull requests, by the workflow; macOS ran locally: 1689 passed) | $1.00 | **$0.80** (Linux 40, Windows 30 minutes) | **$1.39** |

**Spent: $8.61 of the shared $10.00 (5 runs); $1.39 remains.** Any further run needs the owner's go-ahead: a
full dispatch costs about $2.20.

**Merged to main** on 2026-10-25: `7506472`, as merge commits in the batch order. Its tree equals the
tested tree `0f8ac0ab…`, so the merge commits carry `[skip ci]`, and no push run was needed.
