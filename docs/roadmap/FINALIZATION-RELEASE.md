# Local development candidate: release decision and recovery

The version remains **0.9.0.dev0** (a development pre-release; never PyPI-published from this procedure, no paid CI). Recommend 0.9.0a1 only after the acceptance matrix's
blocking safety/installed-journey gates are reviewed; a public RC is not yet
justified by comparative or multi-agent evidence.

## Supported experimental scope

Offline planning/context needs no provider. Explicit replay candidate execution
supports clean committed Git repositories with pytest or Node tests and a working
sandbox. It requires a reproduced baseline failure, identical frozen test inputs,
nonempty complete results, fresh runtime evidence and confirmed cleanup. Compare
abstains when alternatives are incomparable. Why/diagnosis/replay inspect local
evidence and do not re-run models. A PASS covers the frozen suite, not general
correctness. Hostile repository-generated test reports are not attestation.

`repo-ai mission list`, `mission status ID`, `why ID`, `why-test-failed ID`,
`compare ID`, `replay ID`, `handoff ID`, `futures ID`, `apply ID`, `undo ID`,
`quickstart`, `agents doctor`, `privacy audit` expose the current CLI.
See [recipes](REALITY-ENGINE-USAGE.md) for full arguments. New source files,
deletions, renames and mode changes are intentionally refused by automatic apply.

## Migration and permissions

Handoff /1 is no longer trusted on import: re-export from the original store with
`repo-ai handoff ID --to PROVIDER --json`. /2 is a local-store-bound receipt with
an unkeyed SHA-256 integrity checksum, not a signature or authentication. It does
not move a session or verified partial patch to another machine. Partial patch
continuations refuse. Continuation from an unknown prior live cost cannot establish
remaining budget; start a separately approved plan instead of laundering cost.

Old evidence becomes stale when verifier code changes; recreate the mission rather
than editing hashes. New evidence distinguishes LIVE_CANDIDATE_VERIFIED from
LIVE_VERIFIED after explicit tested application; cleanup and freshness failures
remove green assurance. A synthetic provider executable is still simulation even
when it emulates a real provider event format.

A provider-specific live call can disclose the objective and source the agent reads.
The current host sandbox limits writes; it does not isolate host reads. Privacy
regexes cannot prove secrets absent. No model-call permission is granted by this
document, old state files, an installed binary or a previous subscription charge.
Codex/Gemini have no verified hard USD flag; unknown subscription cost is not $0.
Any new trial needs approved provider/model, source/prompt scope, maximum calls,
time, quota consumption and observable USD budget or an explicit unknown-cost
subscription policy. Unknown auth/quota remain separate from installed version.

## Apply, undo and crash recovery

Review `why ID`, the patch, and `privacy audit` first. Close writers to affected
files for the application window; the local lock serializes repo-ai operations,
not arbitrary editors. `repo-ai apply ID --json` prevalidates patch/hash/scope and
writes a durable receipt under the mission store's `applications/` directory.
Each file replacement checks current bytes and path components. Post-apply tests
must reproduce the pinned comparison. Failure restores only owned unchanged bytes.

`repo-ai undo ID --json` checks baseline identity, staging and receipt-owned bytes.
If you edited a target after apply, undo refuses and preserves your content. A
PREPARED/VERIFYING receipt after a crash can be inspected and undone by the same
command; conflicting bytes require manual review using the receipt. Never reset
hard or reverse a patch speculatively. Keep receipts until recovery is finished.
A malicious owner able to rewrite both local mission store and receipt is outside
the integrity threat model. Missing/corrupt receipts refuse automatic recovery.

Uninstall previews are available with `repo-ai uninstall --dry-run`; user exports
and remote provider retention are not deleted by local uninstall. Copy recovery
receipts before uninstall if still needed.

## Validation and reproducibility

The final source identity, full collected test IDs, per-shard structured reports,
JUnit, exit codes and exact-once reconciliation are saved under
`dist/reality-engine/codex-finalization/frozen-suite/`. The definitive verdict is
its `verdict.json`; absence of that file means unfinished validation. Build/install
artifacts and their SHA-256 manifest live under the adjacent `build/` directory.
Installed upstream journeys write source manifests, CLI transcripts, candidate
comparisons and restoration results under `installed-journeys/`.

```sh
# Clean detached worktree at the commit being qualified:
/path/to/test-env/bin/python scripts/finalization_validate.py --source /path/to/frozen --out /path/to/evidence
# Fresh wheel environment; command launches outside repository and strips PYTHONPATH:
/path/to/wheel-env/bin/python scripts/finalization_journeys.py --source /path/to/frozen --out /path/to/new/journeys
```

These replay journeys use previously evaluated Cachetools and Marked snapshots
with historical upstream bug reproductions. They are substantial integration
checks, not fresh holdouts or live AI demonstrations. The deterministic evaluator
now grades the selected patch rather than a hard-coded answer; its A/B labels
remain synthetic harness arms. A real matched provider A/B/C study still needs
frozen repository-disjoint tasks, independent oracle/analysis preregistration,
approval and paired trial observations. Verdict: NOT_YET_DEMONSTRATED.
