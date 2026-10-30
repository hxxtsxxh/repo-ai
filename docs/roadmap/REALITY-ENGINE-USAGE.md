# Experimental local mission workflow

Mission workflow (introduced in 0.9.0.dev0; live providers added in dev1 and later). `repo-ai do` plans offline by default; live model execution happens only with `--run --allow-live-provider`. It makes no agent-performance claim: comparative lift is `NOT_YET_DEMONSTRATED`. The existing `verify`, evidence gate, identity-first retrieval and setup commands remain compatible. `quickstart` already exists.

```sh
repo-ai do "Fix duplicate charges caused by retries" --dry-run --json
repo-ai agents list --json          # static executable availability; no subprocess probe
repo-ai agents doctor --json        # explicit sandboxed help/version only; no login/model call
python -m repo_ai.mission.demo --directory /path/to/new-empty-demo
```

`do` without `--run` plans only, using temporary static analysis. `auto` proposes an approval boundary rather than secretly invoking an agent. `none` retrieves context without an agent. Actual safe probes found Codex 0.164.0, Claude 2.1.308, Gemini 0.65.0 and Bob 2.0.1; authentication, entitlement, prices and live execution remain UNKNOWN/NOT_RUN. CLI declarations are not demonstrated isolation or cost enforcement.

For an existing clean committed pytest or Node repository, supply a **simulated replay** JSON proposal:

```json
{"schema":"repo-ai.replay/1","label":"explicit simulated proposal","edits":[{"path":"charge.py","before_sha256":"SHA256_OF_CURRENT_FILE","after":"def charge(amount, retries):\n    return amount\n"}]}
```

```sh
repo-ai do "Fix retries in charge.py" --agent replay --replay proposal.json \
  --allow-write charge.py --run --max-cost-usd 0 --max-seconds 120 --json
repo-ai mission status MISSION_ID --json
repo-ai why MISSION_ID --json
repo-ai trace MISSION_ID --json
repo-ai handoff MISSION_ID --format json
repo-ai replay MISSION_ID --json
repo-ai mission cancel MISSION_ID
```

Keep the proposal outside the clean checkout, or explicitly ignore it. No patch is applied to the original checkout. The output carries the candidate diff, hashes, baseline and candidate observations, and a fresh regression record. Tests/config cannot be changed in a replay proposal; each source path needs explicit command-line permission. Initial execution supports full `python -m pytest` or `node --test`, regular existing source files, and an available supported sandbox. Missing baseline failure, skipped/empty/incomplete tests, changed test IDs, source/environment changes or unmet bounds prevent PASS. PASS means this frozen suite demonstrated a failing baseline and passing candidate; it does not establish general correctness.

State resides under the existing layout's `state/missions`: at most 64 records of 2 MB each. The privacy command discloses it; uninstall removes managed records and preserves user exports. Task text is redacted, raw test output is hashed, and source proposals containing recognized secret-shaped material are refused. This is not complete secret detection. Hashes detect corruption, not a malicious local writer who can forge records. Handoffs contain local identities and evidence links, no source bodies or native provider sessions; exporting or sending them remains the user's explicit action.

`mission resume ID --run --replay ORIGINAL_FILE` explicitly reconstructs a disposable candidate after a recoverable interruption or an inconclusive completed attempt. The exact proposal and source must match; prior negative evidence stays recorded, elapsed time carries forward, and three attempts is the ceiling. A durable completed write is never silently repeated in place. Active interrupted test/write phases with unconfirmed cleanup are BLOCKED rather than guessed safe; SIGKILL of an active sandbox is not promised to be instantly clean. Cancellation takes effect between bounded test phases.

When static context is uncertain and `--max-parallel 2` permits it, two deterministic read-only investigations produce import/blind-spot and frozen test-inventory artifacts. They are **built-in analysis, not extra model agents**. A bounded DAG joins their results before the sole simulated writer; fresh verification runs on the resulting candidate. Tiny tasks remain sequential. These routing rules are heuristics, not measured economic benefit.

Opt-in isolated candidate comparison uses the same frozen source, test inputs, runtime observations and aggregate time allowance:

```sh
repo-ai do "Fix charge.py retries" --agent replay --run --allow-write charge.py \
  --candidate /outside/checkout/a.json --candidate /outside/checkout/b.json --json
repo-ai compare COMPARISON_ID --json
repo-ai futures MISSION_ID --rehearse --json
repo-ai handoff MISSION_ID --to bob --format json > capsule.json
repo-ai handoff --verify capsule.json --json
repo-ai do --from-handoff capsule.json --agent bob --allow-live-provider \
  --allow-write charge.py --max-cost-usd 0.25 --run --json
repo-ai apply MISSION_ID --json
repo-ai demo --directory /new/empty-demo --json
repo-ai mission-eval --json
```

A single eligible candidate may be selected; multiple passing candidates, no eligible candidate, differing baselines or stale source cause abstention. Rejected alternatives and reasons remain in their mission records. Verified candidate diffs are applied to the working tree only when `repo-ai apply MISSION_ID` (or `repo-ai do ... --apply`) is explicitly invoked and passes post-apply sandboxed test verification. No daemon is installed. Replay reprints checked stored events; it does not rerun a model or tests.

ProofLab remains experimental and uncertified, with its known false-proof classes unchanged; it is never used as a mission completion gate. Comparative multi-task LLM product lift is NOT_YET_DEMONSTRATED.

## Support and explicit gaps

| Area | Current support | Limits |
|---|---|---|
| P0 | Offline planning, simulated and live (`--allow-live-provider`) candidate edits, real sandboxed baseline/candidate/regression tests, safe `repo-ai apply` with post-apply test gate and rollback | Clean Git checkout, existing approved regular source files, full pytest or Node command, bounded repository |
| P1 | Static inventory, network-denied help/version probes, and live sandboxed provider invocation (`LIVE_VERIFIED` demonstrated on `bob` 2.0.6 and rate-limit detection on `codex` 0.164.0) | Unknown-cost outputs fail closed when a positive USD budget is set; `codex` and `gemini` lack hard USD CLI flags |
| P2 | Complexity-classified (`trivial`..`risky`) bounded local DAG, parallel static readers (`impact`, `acceptance`), one writer, `skeptic` gating, explicit checkpoint recovery/cancel | Ambiguous active crash cleanup blocks; no daemon |
| P3 | Two or three isolated candidates, frozen comparison (`repo-ai compare`), negative evidence and abstention | Comparative multi-model tournament lift is not yet benchmarked on live holdout suites |
| P4 | Local why/trace/replay, source/environment/kernel/provider-binary/TestMap invalidation and content-addressed observations | Coarse whole-mission invalidation |
| P5 | Read-only new/pre-existing/fixed/flaky failure diagnosis; file-hash verified `TestMap` runtime coverage links + static leads + remediation & playbook candidate extraction | No stack-trace causal model or automatic reproduction synthesis |
| P6 | Local-store-bound redacted receipt (`--to`, `--verify`); authorized fresh candidate continuation (`repo-ai do --from-handoff capsule.json`) | v2 unkeyed integrity checksum plus trusted local export receipt; debits time and known prior live cost. Carries a verified partial patch (re-derived from stored observations, re-verified from the frozen base) but never proprietary sessions; live A->B transfer not yet demonstrated. |
| P7/P8 | `mission-verified-playbook` Skill Distillery in `repo-ai optimize` (only from fresh verified PASS repairs) and same-zone Change Futures with empirical sandbox rehearsal (`repo-ai futures <id> --rehearse`) | Cross-repo rehearsal requires same-zone enrollment |
| P9 | Calm human text output (zero raw JSON walls unless `--json` is passed), `repo-ai demo`, and held-out `repo-ai mission-eval` with empirical naive smoke runner and negative-control abstention | Offline `mission-eval` is a deterministic harness integrity check (`comparative_lift_verdict: NOT_YET_DEMONSTRATED`) |

Container-image freshness remains `not checked` on read-only status when the existing engine cannot check it. Source-report hashes and structured test identities detect missing/inconsistent evidence, but repository code produces the test report: this is not remote attestation or a security certificate. Independent final red-team review could not finish because native subagents hit their usage limit; the primary-agent challenge tests are labeled separately.

Review hardening: conventional test-support trees (`test`, `tests`, `__tests__`, `testing`, `fixtures`, `__fixtures__`) are frozen along with discovered tests and configuration. Arbitrary helpers outside these trees are not proven independent of candidate code. Mission contracts bind the current registered zone and policy; moving zones blocks old trace/handoff content, and policy changes invalidate evidence. Legacy contracts without this binding need a fresh plan. A tournament becomes stale if a linked proposal or passport changes; a resumed child does not silently change the old winner.

## Explain failures without rerunning anything

```sh
repo-ai why MISSION_ID
repo-ai why-test-failed MISSION_ID --json
repo-ai why-test-failed MISSION_ID --test 'EXACT_RECORDED_TEST_ID'
```

`why` now gives a short request → baseline → candidate → regression explanation with content hashes and precise source/kernel/environment/policy invalidation reasons. JSON retains the evidence identities without copying source bodies.

`why-test-failed` compares the already recorded individual candidate observations. It separates `NEW_FAILURE` (passing base, failing candidate), `PRE_EXISTING_FAILURE`, `FIXED_IN_OBSERVED_SUITE`, and `UNCHANGED_PASS`. Only a fresh, complete experiment with identical test identities, frozen test inputs and runtime can receive `OBSERVED`. Missing baseline, changed test bytes, skipped tests, contradictory results or stale evidence yield `INCONCLUSIVE` and exit2. The command never reruns tests, changes a passport or invokes a provider. Use a candidate mission ID, not a tournament ID.

Source leads reuse recorded context and, when present, the DAG's static imports. They are labeled static and never presented as proven causes or runtime coverage. Repeated failures may have different causes; this first failure-detective slice does not retain stack traces, infer dynamic imports completely, or automatically synthesize reproductions. Reports show at most200 test rows with an explicit omitted count and exact-ID filtering.

The installed demo supports either runner and an optional candidate tournament:

```sh
python -m repo_ai.mission.demo --directory /new/python-demo
python -m repo_ai.mission.demo --directory /new/node-demo --language node --tournament
```

It writes the exact executable transcript, candidate passport, handoff, explanation and failure diagnosis. A tournament also records the rejected superficial fix and selected candidate. Node must be installed for the Node demo; pytest must be installed in the Python environment for the Python demo. Both require a supported local sandbox. Existing nonempty directories are refused.

### Handoff integrity and continuation limits

New exports use `repo-ai.handoff/2`. Re-export old v1 capsules from their original
mission; importing v1 does not infer authority. The SHA-256 checksum is unkeyed
integrity, **not a signature or authentication**. Verification also requires the
matching export receipt in the original local mission store, the same absolute
repository identity and privacy zone, an unchanged mission snapshot and fresh
source/tool/policy evidence. Editing a capsule and recomputing its checksum does
not create a matching local receipt. A local owner who can rewrite both files is
outside this integrity boundary. Capsules are not portable snapshots for new
machines or empty stores. Export adds bounded receipt metadata to the local store.

Continuation starts a fresh isolated candidate from the same frozen source. When
the original mission has *validated partial progress* (a stored diff, comparable
baseline and candidate observations, at least one baseline-failing test now passing
and no regressions), that diff is re-derived from the local store (never trusted from
the capsule), applied to the fresh checkout as an untrusted seed together with the
still-failing test IDs, and the final tree is re-verified from the frozen base. A
stored diff WITHOUT validated progress is refused (not silently dropped), and the capsule's
`diff_sha256` must match the stored diff. A mission with no diff continues from the plain base.
Provider sessions are never transferred. It requires prior local
execution approval and explicit new-provider live authorization, preserves the
write scope, debits elapsed time without a minimum-time refill, and subtracts
observed prior live spend. Unknown prior live cost blocks further live continuation;
subscription use is not recorded as observed zero dollars. A zero-cost offline
step cannot erase that unknown-cost history. Completed or unsafe missions, exhausted
budgets, and more than two continuation steps refuse.

Each source mission permits one continuation attempt, recorded before execution
under its local lock. If interrupted, inspect the child's mission state; replaying
the capsule or re-exporting the parent cannot silently repeat external side effects.
When execution was interrupted before a child was recorded, a fresh explicitly
approved plan is required. A handoff file contains task text, file names, redacted
facts and hashes, so treat it as private even though it contains no source patch.

List saved missions without invoking a provider:

```sh
repo-ai mission list --json
repo-ai undo MISSION_ID --json
```

Undo restores receipt-owned bytes only, refuses staged or later edits, and supports
recovery of interrupted apply receipts. Apply/undo currently supports existing
regular tracked files only; additions, deletions, renames, symlinks and mode changes
require manual review. Keep editors quiescent during apply: the lock cannot control
arbitrary external writers. See [release/recovery notes](FINALIZATION-RELEASE.md).
