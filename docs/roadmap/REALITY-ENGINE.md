# Repository reality engine — execution ledger

Base: `ed936f5` / v0.8.0rc1. Local branch: `codex/reality-engine-20261027`.
Owner/integrator: Codex primary. No new remote mutations, paid CI, model calls or provider disclosure authorized.
Existing `.claude/` remains user-owned. Prior RC qualification is historical, not validation of this increment.

## Bounded feature DAG

| Milestone | Depends on | Status | Owner / code | Gate / risk |
|---|---|---|---|---|
| P0 contracts and policy | audit | DONE (local experimental scope) | primary; mission/contracts.py | strict schemas; no implicit consent |
| P0 fresh offline context | audit | DONE | architecture agent; mission/context.py | no persistent repository writes; identity-first/quarantine |
| P0 isolated replay edit → evidence | contracts, context | DONE (LIVE_VERIFIED on `bob` + SIMULATED replay) | primary; mission runtime/ledger | clean pinned input, frozen tests, real sandbox execution; `repo-ai apply` with post-apply test gate |
| P0 strict observations | audit | DONE; primary completed interrupted specialist work | verification specialist; mission/verification.py | complete nonempty test IDs; baseline failure; independent candidate observation |
| P1 truthful provider discovery | audit | DONE discovery + `LIVE_VERIFIED` (`bob` 2.0.6, `codex` 0.164.0 rate-limit) | provider agent; providers/ | safe local help/version; lifecycle stages (`NOT_INSTALLED`..`LIVE_VERIFIED`); JSONL contract parsers; unknown-cost fail-closed |
| P2 bounded executing DAG | P0 | DONE complexity-routed DAG (`trivial`..`risky`) + capability broker | primary | read-only fanout, one writer, `skeptic` gating, cancellation and crash recovery |
| P3 candidate comparison | P0, P2 | DONE simulated candidates + `repo-ai compare` | primary | common frozen contract/tests; no self-voting or patch blending |
| P4 explanation/replay | P0 ledger | DONE local records, binary identity freshness & invalidation | primary | hashes, explicit stale/not-checked; provider binary SHA-256 re-verified on `status()` |
| P5 failure detective | P4 runtime observations | DONE observed deltas, flaky detection, TestMap freshness & remediation | primary; mission/diagnosis.py | matched fresh observations; file-hash verified TestMap; no root-cause/proof claim |
| P6 portable handoff | P0 ledger, P1 | DONE `LIVE_VERIFIED` (`--from-handoff` `codex` -> `bob` continuation) | primary | no source upload; root/zone boundary, redaction; budget debit across continuation |
| P7 skill promotion | P4, controlled trials | DONE `mission-verified-playbook` distillery in `optimize.py` | primary; optimize.py | only fresh verified PASS repairs proposed; negative/failed missions refused |
| P8 change futures | P4, explicit enrollment | DONE same-zone futures + `--rehearse` empirical sandbox test (`mission/futures.py`) | primary; mission/futures.py | static/heuristic hypotheses + empirical sandbox rehearsal (`REHEARSAL_PASSED`/`FAILED`) |
| P9 calm CLI & eval protocol | P0–P8 | DONE (`apply`, `compare`, `futures --rehearse`, `demo`, `mission-eval`) | primary; mission/cli.py, eval_protocol.py | zero raw-JSON walls in text mode; held-out independent grader; `NOT_YET_DEMONSTRATED` live lift |

## Design and compatibility

Add a deterministic mission kernel around existing `analyze`, `packet`, `verify.engine`, `verify.results`, `verify.execute`, and `verify.isolate`. Existing orchestrate plan remains advice-only. New default `do` plans offline; execution requires explicit local consent and an explicitly supplied replay edit artifact. Real provider execution is separately gated and NOT_RUN without authorization and enforceable policy.

Six versioned typed contracts describe intent, reality graph, capability, DAG, evidence and handoff. Unknown schema/fields and malformed permissions fail closed. Mission output is a tested **candidate**, never silently applied to the original checkout. Keep snapshots/artifact digests under the existing layout's state directory, with explicit privacy/uninstall integration. Acceptance test/config bytes cannot be edited by replay proposals. Do not equate a verification string or exit zero with repair: require observed baseline failure and complete nonempty equal test identities, followed by fresh full regression verification. Source/environment/contract changes invalidate the result. All source text and model output are untrusted data.

No retrieval experiment or PR #57 merge. ProofLab remains experimental, uncertified and outside every mission completion gate. Product lift: NOT_YET_DEMONSTRATED. Historical tasks are not a new holdout.

## Evidence and checkpoints

- Preflight: tracked checkout clean at ED; `.claude/` untracked preserved. Open draft PRs #52 and #57 inspected read-only. Issues #47/#55/#56/#59 remain historical records.
- Provider preflight: bounded network-denied help/version evidence in ignored `dist/mission-preflight/`; executable availability is not authenticated runnable availability.
- Audit found packet cache/index writes and verification's conditional baseline; new planning uses ephemeral analysis, new strict observations establish the baseline explicitly.
- Test results and checkpoint commits will be appended after execution, never anticipated.

## Research gate

Before any product-lift experiment: preregister repository-disjoint untouched tasks, randomized paired order, matched best-single-agent budgets, independent grading, and task-level confidence intervals. Measure verified success, time, interventions, spend, side effects, context overhead, miss rate and recovery. Paid evaluation and new CI remain BLOCKED pending separate authorization. Targets are aspirations, not achieved results.

### P0 checkpoint — executed

- New mission contract/ledger/context/runtime/CLI and strict observations implement offline planning and explicit isolated simulated edits with real sandbox tests; source checkout remains unmodified. Provider discovery is operational; live execution adapters remain PLANNING_ONLY/NOT_RUN.
- Selected new and adjacent integration suite: **108 passed in 109.39s**. Before implementation, contract/ledger/runtime imports failed as expected; context tests caught Git index timestamp mutation. Strict observer and runtime suite: **32 passed**. CLI privacy/uninstall/handoff integration: **3 passed**.
- Repository-wide Ruff passed; mypy passed on 103 source files; plugin bundle current; git diff --check passed.
- Wheel and sdist built; fresh wheel install plus pytest 9.1.1 and pip check passed. Fresh-wheel duplicate-charge demo: baseline 1 failing test -> candidate 0 failures; original unchanged; local handoff no source bodies. Exact commands/output in ignored dist/reality-engine/p0-wheel-demo/transcript.json and p0-wheel-demo.log. These development artifacts retain project version0.8.0rc1 but are NOT the historical tagged release; their paths/checksums are distinct.
- Independent context and provider specialists completed their slices. Verification specialist and independent red-team reviewer hit the native agent usage limit; final independent challenge is **NOT_COMPLETED**, not a pass. Primary completed integration and test execution. No retry or quota workaround.
- Full original suite, installation on other OSes, live provider execution and product-lift evaluation are not claimed at this checkpoint. Next: P2 scheduler/recovery and P3 frozen candidate comparison, then whole-suite validation.

### P2/P3 source freeze — executed focused checks

- Bounded DAG executes deterministic read-only investigations concurrently when context uncertainty and an explicit concurrency ceiling justify them; they are built-in analyses, not claimed model agents. Their test inventory is checked against the observed baseline. One replay writer edits a disposable candidate; independent sandbox observations and existing verify run against that result.
- Explicit resume preserves prior negative artifacts and carries elapsed time; three attempts maximum. A real SIGKILL at PLANNED resumes; an ambiguous active writer checkpoint blocks. No guarantee of automatic cleanup/recovery after SIGKILL of an active sandbox is claimed.
- Tournament compares two/three isolated simulated proposals under pinned acceptance/test/runtime observations, retains losers, selects only one eligible candidate, and abstains on divergent baselines or multiple passes. Comparison records are durable and explainable.
- Primary challenge found and fixed two genuine false-confidence gaps: contradictory exit/timeout fields, and reporting cleanup success with a leftover workspace. Before-fix failures remain in `redteam-before.log` and `cleanup-before.log`. The corrected challenge/observation/scheduler group passed35 tests. Actual controller-kill and repository-boundary tests passed3 tests. Runtime/CLI/tournament/challenge integration passed17 tests; subsequent cleanup/runtime/CLI/scheduler/tournament/challenge group passed22 tests. Final pre-freeze runtime/tournament/recovery group passed13 tests.
- Kernel source identity now invalidates mission evidence even when package version is unchanged; development version is0.9.0.dev0. Historical RC artifacts/tag/main remain unchanged. Local capsule contains redacted objective, constraints, checked facts, DAG status, permitted paths, diff identity and next local command; no raw source or provider session is sent.
- Existing26-case retrieval regression: recall@5=1.000, MRR=.942, false injection=0; query p50=.176s, p95=.185s. Known regression set, not an untouched holdout or agent-performance evaluation.
- Full suite and final installed-wheel checks are next; do not relabel focused passes as full validation.

## Dependency-ordered remaining work

1. Finish full original/new suite and fresh0.9.0.dev0 install/demo, record failures/skips explicitly.
2. Independent final red-team review when native capacity returns; current primary challenge is not independent.
3. P1 live adapters: first validate executable/runtime closure, transitive permission narrowing and enforceable cost/privacy boundaries; then seek explicit authorization for bounded live smoke tests. Auth/entitlement remains UNKNOWN. No new live calls or remote pushes are currently authorized.
4. P2 provider-backed fanout and stronger active-process crash supervision depend on3; preserve blocked ambiguous recovery.
5. P6 cross-provider execution continuation depends on3/4 and explicit payload/zone approval. Local capsules are already usable manually.
6. P4 fine-grained causal invalidation and P5 failure hypotheses depend on richer independently checked runtime links; keep existing verifier authoritative.
7. P7 skill promotion depends on P4 plus preregistered controlled task-benefit trials; existing negative capability findings remain negative.
8. P8 change futures depends on P4 and explicit same-zone enrollment; no automatic migrations.
9. P9 optional editor/MCP/A2A surfaces follow stable contracts and actual provider support; no mandatory daemon or web replacement.

### Continuation: independent review corrections

Recovered `485adb8` suite completed: **1 failed, 1846 passed, 8 xfailed** in2150.44s (`dist/reality-engine/full-suite.log`). The failure was the old privacy disclosure assertion; the test now requires disclosure of redacted mission task text, candidate diffs, retention and no provider upload. Product disclosure was not weakened. Focused privacy checks passed6 tests.

Independent reviewers reproduced10 failing cases before exhausting native capacity: stale cancel/resume readers overwriting completed records; child DAG budget widening; invalid write owners; acceptance-helper tampering; an omitted Node reporter fingerprint; and a stale tournament winner after a child resume. All10 regressions passed after correction (`independent-findings-fixed.log`). Primary follow-up reproduced4 zone-binding failures, and added3 execution-order challenges. Registered zone/policy now binds planning, execution, status and handoff; moved-zone content is withheld. Old contracts without a policy fingerprint become stale and require replanning. Conventional test-support directories are frozen; arbitrary assertion helpers elsewhere are not statically resolved and remain an explicit scope limit. Final independent review **NOT_COMPLETED**: real findings were integrated, but no independent final approval was obtained.

The earlier485 wheel/sdist matched its Git source (1919 wheel source/eval files,1923 RECORD hashes,2196 sdist files,8 license files), passed fresh installation/pip check and ran the real pytest acceptance demo. These artifacts remain historical under `final-artifacts/`; corrected-source artifacts must use a new directory. No remote operation, model call or paid CI occurred.

### P4/P5 continuation — offline failure explanation

The next usable slice adds `why-test-failed MISSION_ID [--test EXACT_ID]`, backed by the existing strict observation comparator and store. It distinguishes new/persistent/fixed failures and unchanged passes without requiring the whole candidate to win. It refuses stale, skipped, mismatched, missing or contradictory observations; it never upgrades a passport. Static source hypotheses reuse stored context/import evidence and remain explicitly noncausal. `why` now produces a compact evidence-linked explanation; status gives precise invalidation reasons instead of only a stale label. No second proof store, test execution, source upload or provider call is added.

Failing-first collection logs: `diagnosis-before.log`, `explanation-before.log`. Diagnosis/strict-verifier group passed40 tests; diagnosis/CLI/adversarial group passed21 tests. Final integration and package checks are recorded at the next checkpoint. P4 remains coarse whole-mission invalidation; P5 remains PARTIAL (observed deltas/static leads), not stack-trace causal debugging or automatic reproduction synthesis.

Validated checkpoint56b90b3: broader mission/provider/privacy suite **131 passed in125.89s** plus3 ordering challenges. Exact wheel/sdist audited against Git; fresh installed acceptance **11 commands passed**, covering Python FAIL/PASS tournament, tie abstention, Node observed repair, handoff/replay/completed-resume and uninstall preserving human files. Outputs: `artifact-audit-56b90b3.log`, `installed-56b90b3/transcript.json`, `installed-56b90b3/candidate.diff`. Full suite is isolated in `validation-56b90b3`; its result must be read rather than assumed. Current next work must qualify the new diagnostic source separately.

Diagnostic source freeze: mission/provider integration **135 passed in208.70s**; subsequent kernel-closure/runtime/explanation group **15 passed in58.12s**; packaged Python solo/Node tournament demo plus kernel challenges **5 passed in24.17s**. The kernel now fingerprints all root Python helpers, including process cleanup and locking, plus mission/verify/provider runtime assets. Failing-first3-case kernel log is preserved. Ruff, mypy107 source files and generated-plugin consistency passed. The full56b90b3 run is superseded by the expanded candidate: retain its partial log and do not count it as a pass. Final validation must cover every collected test on the new exact snapshot; no earlier full-suite result applies automatically.

### `aba3507` full-suite certification and independent review closure

- **Three-shard `aba3507` full-suite verdict**: All three shards in `dist/reality-engine/suite-aba3507/` completed with `exit_code: 0` (shard-0: `628 passed, 4 xfailed in 1440.40s`; shard-1: `631 passed, 1 xfailed in 920.66s`; shard-2: `628 passed, 3 xfailed in 1209.50s`). Exact set-equality check (`dist/reality-engine/suite-aba3507/verdict.json`) confirmed all **1,895 unique test IDs** in `collection.json` executed once with **1,887 passed, 8 xfailed, 0 failed, 0 skipped**.
- **Artifact & installed demo verification on `aba3507`**: Wheel (`956f750317c83e88ab4969738ec4eb4b3b6599c722bb2f9f7d61314a3518faae`) and sdist (`e1eb280f376b03d14cb83caab362b97e0d0a1a5f5823770bc7792b28b922792c`) matched Git tree and roundtrip wheel rebuild byte-for-byte (`sdist-roundtrip-aba3507.json`); installed wheel acceptance (`installed-aba3507.log`), Python solo demo (`python-demo-aba3507.log`), and Node tournament demo (`node-demo-aba3507.log`) passed.
- **Independent security & correctness review completed**: A 60-step read-only adversarial audit uncovered 6 concrete findings at `aba3507`, all reproduced failing-first (11 failing cases) and fixed:
  1. `tournament.compare_candidates` pre-execution contract/approvals/zone/kernel/repository validation, duplicate-proposal rejection, abstention when any candidate is blocked/incomplete, and third-candidate baseline-instability propagation; `runtime.status` clears `comparison.winner` when comparison evidence is stale.
  2. `runtime.git` preserves leading unstaged status spaces when `-z` is passed (`rstrip('\0\r\n')`); `verification.test_support` is case-insensitive and covers `sitecustomize.py`/`usercustomize.py`; `runtime.proposal` requires exact membership in tracked files.
  3. `runtime.proposal` blocks all `scan_text` secret findings (not only `should_quarantine` subset), and `verification.observe` applies `redact_text` alongside `evidence.scrub` on notes and exceptions.
  4. `providers.discovery` checks `raw.parent.resolve(strict=True) / raw.name` to refuse repository symlinks reached via symlinked parent directories.
  5. `mission.diagnosis` strips `.__init__` from package module names when linking failing test imports.
  6. `mission.cli.cmd_mission` enforces `check_privacy` before mutating `.cancel` or mission state, and `runtime.execute(..., resume=True)` rejects non-existent mission records.

### Vertical Slices B–J and Deterministic Evaluation Protocol

- **Slice B (P1 — Universal Provider Runtime)**: Added `src/repo_ai/providers/adapters.py` with explicit `ProviderContract` definitions for `codex`, `claude`, `gemini`, and `bob`, lifecycle stages (`NOT_INSTALLED`, `DISCOVERED`, `PROBED`, `READY`, `SIMULATED`, `BLOCKED`, `FAILED`, `VERIFIED`), non-shell `build_invocation`, hard USD budget flag enforcement (`enforces_hard_usd_budget`), redacted JSONL `parse_event_stream`, network-denied `run_provider`, and `validate_workspace_edits`. Integrated into `mission/runtime.py` and `repo-ai do --provider-executable` for $0 local contract simulation while keeping live billable execution fail-closed.
- **Slices C & D (P2/P3 — Conductor & `repo-ai compare`)**: Added `inspect_comparison` and `render_comparison` in `src/repo_ai/mission/tournament.py` and top-level `repo-ai compare <id>` CLI command.
- **Slices E & F (P4/P5 — Reality Ledger & Causal Failure Detective)**: Extended `src/repo_ai/mission/diagnosis.py` and `explanation.py` with `FLAKY_OR_INCONSISTENT` detection across attempts on identical test inputs, `TestMap` runtime coverage correlation (`confidence: 'observed'`, `priority: 'runtime-trace-link'`), and deterministic `next_experiments`.
- **Slice G (P6 — 7-Class Recovery Classifier & Handoff Verification)**: Added `RECOVERY_CLASSES`, `classify_recovery`, `handoff(..., target_provider=...)`, and `verify_handoff` in `src/repo_ai/mission/runtime.py`, plus `--to` and `--verify` flags on `repo-ai handoff`.
- **Slice H (P7 — Skill Value Governor)**: Connected verified mission evidence (`mission_stats`) to `src/repo_ai/optimize.py` (`performance()` and `proposals()`).
- **Slice I (P8 — Change Futures)**: Added `src/repo_ai/mission/futures.py` and `repo-ai futures` CLI command for local static blast radius and same-zone cross-repository impact hypotheses (`consumes_api` heuristic and `depends_on_package` static).
- **Slice J & Section 6 (P9 — Grounded DX & Versioned Evaluation Protocol)**: Added `repo-ai demo` CLI command wrapping `src/repo_ai/mission/demo.py` and `src/repo_ai/mission/eval_protocol.py` (`repo-ai mission-eval`) comparing `unassisted_naive_baseline` vs `reality_engine_verified` across frozen local fixtures at $0 model cost.

### Phase II — Truthful Capability Activation & Live Provider Continuation

- **Capability Activation Audit (`docs/roadmap/PHASE2-ACTIVATION.md`)**: Audited `608170a` (`5f7e6df`) across P0–P9 and all 10 adversarial audit questions with three independent reviewer subagents (Adversarial Security, Evaluation Methodology, DX Integration).
- **Live Provider Execution & Cross-Provider Handoff (`LIVE_VERIFIED`)**:
  - Live `codex` (`0.164.0`) mission `b82a5e158916e077cd5ae1fc` executed in an isolated Seatbelt worktree (`dist/reality-engine/live-phase2/codex-live-attempt.json`), hit its live usage limit (`rate_limited: True`), and failed closed (`state: "INCONCLUSIVE"`, `effective_verdict: "BLOCKED"`).
  - Signed `HandoffCapsule` (`dist/reality-engine/live-phase2/handoff-codex-to-bob.json`) exported via `repo-ai handoff b82a5e158916e077cd5ae1fc --to bob` and verified via `repo-ai handoff --verify` (`valid: True`).
  - Live `bob` (`2.0.6`) continuation via `repo-ai do --from-handoff handoff-codex-to-bob.json --agent bob --allow-live-provider --max-cost-usd 0.25 --allow-write charge.py --test-command "python -m pytest" --run` (`dist/reality-engine/live-phase2/bob-live-mission.json`) repaired `charge.py` inside a Seatbelt-jailed disposable worktree, passed baseline-to-candidate and full regression verification (`mission: 23375b36c9c88a626c695166`, `effective_verdict: "PASS"`, `verification_label: "LIVE_VERIFIED"`, `cost_usd: 0.091508`, `cost_status: "OBSERVED"`).
  - Empirical Change Futures rehearsal (`repo-ai futures 23375b36c9c88a626c695166 --rehearse`) applied the candidate diff (`6b23f201d31795b6c6e932f2a52cdf8576f619a4ab71f90f01b392e011083f92`) in a disposable sandbox and verified downstream tests (`observation_sha256: 8e436e18bc0d3556c6445f14bb378b73b1cfc51401e3128ed74ed764bd52650fc`).
  - Safe working-tree application (`repo-ai apply 23375b36c9c88a626c695166`) applied the verified diff and passed post-apply sandboxed test verification (`observation_sha256: 579d8a0e64753c901e3f9a9001870e3bd55745308c18cf73a40e774535dbd4a6`).
- **Scientific Evaluation Integrity (`src/repo_ai/mission/eval_protocol.py`)**: Replaced hardcoded naive booleans with an empirical single-test smoke runner, added held-out `independent_grader_tests` unseen by `compare_candidates`, added a negative-control abstention task (`discount_overflow_negative_control`), added Wilson 95% confidence intervals, and explicitly set `mode = "deterministic_harness_integrity_check"` and `comparative_lift_verdict = "NOT_YET_DEMONSTRATED"`.

### Codex finalization: interrupted provider capture recovered (2026-10-27)

Incoming `0481f82` plus partial discovery.py edits preserved. New channel tests
first failed 5/11; repaired capture and adapter now pass 45 focused tests on the
host (12.39s); compileall, Ruff and provider mypy pass. Evidence lives in
`dist/reality-engine/codex-finalization/`. No new provider/model call or remote
write. The earlier DONE/live labels above describe historical work, not current
release qualification. Independent reviewers have reproduced handoff trust and
apply prevalidation defects; fixes are in progress. See
[recovery ledger](CODEX-FINALIZATION-HANDOFF.md). Full final-candidate suite pending.

### Security boundary repair checkpoint (2026-10-28)

Handoff imports now require version 2 unkeyed integrity plus a trusted local
export receipt; no signature/authentication/portable partial-work claim. Apply
validates actual patch semantics before source writes, records owned bytes and
supports conflict-aware undo. Live candidate assurance is separate from applied
assurance and is demoted on cleanup/freshness failure. Primary receipt forgery
challenge reproduced two additional defects and repaired both. Native reviewers
all hit quota before completing final review. Current results and residual
limitations: [acceptance matrix](FINALIZATION-ACCEPTANCE.md) and
[recovery ledger](CODEX-FINALIZATION-HANDOFF.md). No new live call or spend.
