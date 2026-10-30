# Codex finalization recovery ledger

2026-10-27. Branch `codex/reality-engine-20261027`; incoming HEAD
`0481f827f578bb9030ad68b224cc6883bca335db`, tree
`24046bb611b9b18bc24d0f00c4ce11edaef51554`. No ancestor/root/local
AGENTS.md found. Incoming discovery.py edits preserved in
`dist/reality-engine/codex-finalization/incoming.patch`; inventory, worktrees and
bounded process list beside it. `.claude/` is user-owned and untouched. No
pre-existing pytest job was observed. Existing Codex/Antigravity sessions and all
old worktrees retained. No remote mutation or new provider invocation authorized.

## Owner tracker

- Primary: provider capture rescue, integration, installed/frozen validation.
- Native handoff reviewer: capsule checksum/local binding and continuation safety.
- Native apply reviewer: prewrite validation, receipt/undo and assurance cleanup.
These are development reviewers, not product conductor demonstrations.

## Provider capture rescue

Finished the interrupted split stream implementation: both pipes drained and
bounded independently, both EOFs awaited, readers joined, stderr returned;
POSIX readers can stop even with detached pipe holders. Probe default remains
merged. Provider adapters split diagnostics, retain diagnostic hash/length and
redacted summary, detect stderr limits without parsing stderr as agent events,
and extract Codex agent_message items. Nonfinite cost rejected as unobserved.

Failing-first: 5 failed, 6 passed (`channels-red.log`). After correction:
45 passed in 12.39s (`channels-host.log`), provider compileall, Ruff and mypy pass.
Outer sandbox run had 6 sandbox-execution failures, 39 passes; not product passes.
Host test command (explicitly approved to permit nested macOS seatbelt):

```sh
PYTHONPATH=src /private/tmp/repo-ai-rc1-env/bin/python -m pytest tests/test_provider_channels.py tests/test_provider_probe.py tests/test_provider_runtime.py -q
```

This is focused working-tree evidence, not full-suite release qualification.
Provider terminal/schema identity validation and detached-child cleanup guarantees
still require challenge. No live model call or observed new spend.

## Next

First command: `git status --porcelain=v1 -b`.
Integrate independent handoff/apply regressions, then inspect current command
surface and help/version probes, acceptance matrix, installed journeys and exact
frozen source full suite. Historical 1,895-test evidence is ONLY for `aba3507`.
Phase II 191 focused tests and prior Bob $0.091508 are historical, not current
qualification or permission. Comparison lift remains NOT_YET_DEMONSTRATED.

## Security integration checkpoint (2026-10-28)

Provider rescue commit: `790d581`. Native reviewers reproduced capsule field
forgery/budget resets, out-of-scope apply writes and clobbering rollback, and
LIVE_VERIFIED surviving cleanup failure. Handoff /2 now binds checksum to local
export receipt, mission snapshot, contract/source/policy; rejects unsafe partial
continuation, unknown prior live cost and repeated attempts. Apply/undo now uses
preflight sandbox-copy patch validation, existing-file-only scope, POSIX guarded
replacement, repository lock and durable ownership-scoped receipt. Primary
challenge found rechecksummed undo receipt forgery (2 failing tests); receipt file
hash is now bound to trusted mission authorization, and UNDONE verifies bytes.

Native reviewer status: **all three hit usage limits before final independent
review completion**. Their source work is retained. Primary owns integration.
Security/eval/CLI integration: **105 passed, 3 failed in 224.57s**; failures were
selected-patch missing final newline (2 integration tests) and old false privacy
wording expectation (1 test). Fixed and targeted recheck running; no full-suite
claim. Prior reviewer sandbox-denied runs remain failures in their logs.
No provider/model calls. Explicit network-denied probes observed Codex 0.164.0,
Claude 2.1.311, Gemini 0.65.0, Bob 2.0.6; auth/quota/price remain UNKNOWN.

Residuals: arbitrary concurrent editors cannot be serialized by advisory locks;
apply requires a quiescent window, refuses creates/deletes/renames/mode changes,
and preserves conflicts for manual recovery. Live sandbox restricts writes but
allows host reads; not a hostile-agent read-confidentiality boundary. Partial
verified patch transfer and genuine product model-team execution remain blocked.
Next: finish selected-patch grading recheck, commit evaluation/privacy/DX separately,
freeze exact source, full suite and installed Cachetools/Marked replay journeys.

## Product/evaluation repair checkpoint

The integration recheck passed **6 tests in 112.68s**, closing all three earlier
failures. Final focused apply/receipt, provider protocol, evaluator, privacy and
mission-list checks passed **43 tests in 16.38s**. Ruff across sources/tests and
validation scripts, mypy (111 source files), plugin consistency all pass. Full
suite has NOT yet run for this candidate. Next action is the clean detached freeze
and `scripts/finalization_validate.py`; see `FINALIZATION-RELEASE.md` for artifact
locations. No active pre-existing job is carried into the freeze.

Final execution results will be durably recorded in
`dist/reality-engine/codex-finalization/final-results.json` and the frozen suite
verdict, so documentation need not change the already-frozen source commit.
First next command: `git status --short` then inspect that result file and
`dist/reality-engine/codex-finalization/frozen-suite/` before starting another run.

## Bob continuation (2026-10-28)

Branch `codex/reality-engine-20261027`. Commits added: `8be7808` (inherited unittest
attribution uses collected file identity; source-secret filter no longer flags plain
identifiers like `tokenizer`, still blocks quoted credentials/comments; negative-control
test) and `1c39ccb` (test-only: `tests/test_coding_lab.py` isolates `REPO_AI_LAB_HOME`).

Why 1c39ccb: the first full suite at `8be7808` had 1 failure of 2004
(`test_a_denied_attempt_is_recorded_but_does_not_invalidate`). Root cause: the test asserted
on the user's real `~/.local/share/repo-ai/lab/canaries` while a concurrent process created a
canary directory there. Passed in isolation; fixed by isolating the lab home. Product code unchanged.

Frozen full suite at `1c39ccb` (tree `e6809b49141f5293859f8a05fc4d99bb42559c97`, worktree
`dist/reality-engine/frozen-1c39ccb`): 2004 collected, 1996 passed, 8 xfailed, 0 failed,
every ID executed exactly once. Wheel sha256 `92f7be25...0215f`, sdist `aa955d25...6603`
(`dist/reality-engine/bob-final/SHA256SUMS-1c39ccb`). The wheel hash is identical to the one
built at `8be7808` because 1c39ccb touches only tests. Installed in a fresh venv outside the
tree; `pip check` clean; entry point runs. Direct vs sdist-rebuilt wheel reproducibility NOT re-checked.

Installed journeys (wheel from 8be7808, replay, `live:false`, $0 model cost): Cachetools PASS,
Marked PASS. The earlier INCONCLUSIVE results traced to the two defects fixed in 8be7808.

Not done / still open: independent adversarial Explore review of apply/handoff/tests (Gate B);
live provider, real multi-agent and partial-work handoff proof (BLOCKED: no authorization/cost
approval); matched A/B/C evaluation (NOT_YET_DEMONSTRATED); README command audit beyond
quickstart/do/agents/privacy; `repo-ai doctor` warns when a PATH `repo-ai` (0.7.7) differs from
the running one. Nothing pushed, no PR, no tag/release: pushing could trigger CI of unknown cost,
and several acceptance rows remain PARTIAL/BLOCKED. Verdict: local candidate, NO-GO for public release.

Stale detached worktrees under `dist/reality-engine/` (frozen-8be7808, frozen-1c39ccb) are ignored artifacts.
First next command: `git status --short && git log --oneline | head`.

### Update: final candidate 4f718f1

Independent Explore review of 8be7808 found, and I reproduced with old-vs-new comparison
(`dist/reality-engine/bob-final/oldnew.py`), that `source_contains_secret` no longer blocked
unquoted `password: x` / `API_TOKEN=x` in config files or secrets in `--`, `/* */`, `<!-- -->`
comments. Fixed in `4f718f1`: recognised code suffixes keep the identifier-friendly rule
(`tokenizer = expr` allowed); config/unknown files and all comment styles use full redaction.
Failing-first tests added; full suite re-run because product code changed.

Final frozen candidate: commit `4f718f1333913504e2649c1a38739c81d3ba3199`, tree
`c0dab838da58c0e89b0d79f4da1e95e74a29b2a6`, worktree `dist/reality-engine/frozen-final`.
Full suite 2006 collected / 1998 passed / 8 xfailed / 0 failed, each ID once.
Wheel sha256 `79242915f59291904bbbfd7b2dc7840ed72038cffd20421c7785e55e0d033f77`, sdist
`c8c8ad3fa781a24387483227765a9ef1ca82af9f1de82066732e9017961f6a6b` (built in /tmp/rai-build4;
hashes in `bob-final/SHA256SUMS-4f718f1`). Installed journeys on this wheel: Cachetools PASS,
Marked PASS (replay, live:false). Earlier results at 8be7808/1c39ccb are historical.

Known residual: heuristic filter has false negatives (e.g. JSON `"password": "x"` with an
unrecognised quoted form was already undetected by the OLD check too). No orphan processes.
Release verdict unchanged: local candidate, NO-GO for public release (see above). Not pushed.
First next command: `git status --short && git log --oneline | head -5`.

## Bob live-provider checkpoint (d19030d)

Live Bob repair in `dist/reality-engine/bob-live/` (ignored). First real live attempts exposed two
product bugs, both fixed: `bfcdb8f` (provider capped at the 30 s simulated bound; live now bounded by
mission budget, ceiling 900 s) and `d19030d` (capture ceiling not passed through, "invalid probe bounds").
Result: mission 636ded7f PASS/LIVE_CANDIDATE_VERIFIED, cost $0.156 provider-reported; sealed oracle 4/5.
Full suite at `d19030d` (tree a08658427e595ec78794ecb2d2b8cee609542a19): 2008 / 2000 passed / 8 xfailed / 0 failed.
Wheel, sdist, installed journeys and static gates NOT re-run at d19030d.
README now documents `pipx install --suffix=-dev` for side-by-side use; PATH `repo-ai` stays 0.7.7 (pipx, user-owned, untouched).
Still open: P2 real multi-role DAG, P3 live competing candidates, P6 partial-work handoff, P5/P8 consequential demos,
A/B/C evaluation, fresh adversarial review of apply/undo/handoff, wheel-vs-sdist reproducibility, second live stack.
Nothing pushed. First next command: `git status --short && git log --oneline | head -5`.

### Red-team note (58b8a58)

An Explore subagent returned a code-reading report claiming "all attacks failed" with no executed output; it
wrote no scripts. Treated as unverified. I ran `dist/reality-engine/bob-redteam/attack.py` myself: 6/6 DEFENDED
(see acceptance matrix row). Concurrency, crash-mid-write, symlinked parent, TOCTOU timing and handoff-capsule
mutation were not executed in this pass (handoff forgery is covered by existing `tests/test_handoff_integrity.py`).
