# Release readiness

## 2026-10-25 (evening): main `4d91b85` + docs, the corrective phase (Session B)

**Decision: still not a qualified release. ProofLab stays experimental, and its supported scope was narrowed.**
- **Merged:**
  - #53 (audit F1) with its review fixes;
  - F2b: no repository-located or repository-chosen program runs on the host;
  - X13b: `evidence` and the Stop-hook gate compare the test environment statically;
  - ProofLab's corrective fixes.
- **Session A's eight false-proof instances at `8288b2f`:** fixed, each with a regression test that fails
  on `1832a53`. Three further independent adversarial rounds found 22, 17 and 19 more false proofs, so
  ProofLab's supported scope was narrowed: one entry point, literal inputs, independent expectations,
  a declared subject, no node claims (`docs/PROOFLAB.md`).
- **Open false proof:** a class that already compares equal to anything at the base, kept as a strict
  xfail. It is outside the declared "mistakes, not attacks" scope.
- **Validation:**
  - CI run 40246695220: 13/13 on the exact tree;
  - local macOS: 1687 passed, 6 xfailed;
  - Linux podman: 1362 passed, 319 skipped, 2 xfailed.
- **Spending:** $8.61 of $10.00, after PR #58: the integrity check reconciled with Session A's rework of #53
  (CI run 40251611104, 12/12, macOS local).
- **Still blocking release:**
  - Session A's independent rerun of the probes on this freeze;
  - Session A's fresh evaluation (held-out-7) and release qualification (issue #47).

Until those report, nothing here is a release candidate.

## 2026-10-25: main `7506472` (Session B, final product mission)

**Decision: a validated integration, not a qualified release.**
- **Evidence:** every correctness fix found since held-out-6 is merged, CI is 13/13 on the exact tree, and
  the packaged wheel reproduces the demonstrations.
- **What blocks release:** Session A's release qualification still needs a fresh evaluation of this tree
  on data not used to make the fixes. Until it reports, nothing here may be called a release candidate.

| Gate | Status | Evidence |
|---|---|---|
| Known false-assurance defects (D1–D10, the `nothing-selected` class, X13) closed | **met in code**, not yet re-measured on fresh data | #41, #42, #43, #45, #48, #51, each with tests that fail before the fix |
| ProofLab's known false-proof paths | **closed or documented** | Session A's F1–F5 fixed; four independent challenge rounds (10, 5, 5, 3 findings) fixed. The remaining classes are listed in `PROOFLAB.md` "Limits": an expected value inside declared code under test, a one-value node assert patch, local forgery |
| A fresh independent evaluation of core verification, for the declared scope | **not done** | requested from Session A (PR #24, comment 6402614125) |
| Installs and runs from packaged artifacts | **met** | two byte-identical builds (wheel sha256 `5db829b3…`); the demonstrations run with the installed wheel (`benchmarks/prooflab/results/2026-10-24/summary-run10-final-wheel.json`) |
| CI passes for the exact tree | **met** | run 40227757898 on `643e47d`, whose tree equals main's: 13/13, macOS and Windows included. Run 40225661892 failed on Windows first (release-risk R14) |
| Security and sandbox boundaries | **met for the tested scope** | committed-interpreter fix (#40, T24); macOS detached processes (#50, T7); ProofLab's injection, path and state checks. Residuals: R8, R11, R13 in `RELEASE-INTEGRATION-2026-10-25.md` |
| Experimental features isolated and opt-in | **met** | `prove` is experimental and opt-in; no hook calls it; `/repo-prove` is manual-only |
| Claims match evidence | **met** | agent benefit is **not demonstrated**; demonstrations are labelled as demonstrations, not evaluations |
| Spending | $3.74 of $10.00 | two CI runs; the ledger is in `RELEASE-INTEGRATION-2026-10-25.md` |

**Supported scope, as of this tree:**
- verify's plan, and `--run` on macOS (seatbelt) and Linux (bubblewrap), for unittest, pytest and
  `node --test` (TypeScript by type stripping);
- containers on any OS, with Windows not measured;
- ProofLab is experimental on the same runners, demonstrated on macOS only.

---

## 2026-10-24 (previous milestone)

**Decision: not a release candidate.** Integration is complete: #24, #26, #27, #30, #31, #35, #36,
#37 and #38 are merged. But verify's own release blockers are still open, and a correctness bug
(#37) was found after the last held-out set and has not been measured on a held-out set since.

The gates below check integrity and honesty, not whether repo-ai helps an agent. That benefit is
**not demonstrated**.

| # | Gate | Status | Evidence |
|---|---|---|---|
| R1 | The full suite passes on macOS locally, and on Linux and Windows in CI | **met** | macOS host: 1216 passed, 2 xfailed, on the integrated tree. PR CI 12/12 for #37 (run 40057481206), #35 (40059080528) and #38. The final main run, macOS included, is recorded in PR #24's thread |
| R2 | ruff, mypy and `build_plugin.py --check` are clean | **met** | every head, before each merge |
| R3 | The macOS CI job is green on main | recorded with the final main run | PR #24 thread |
| R4 | The wheel builds reproducibly, installs fresh and passes the user journey | **met** | identical wheel and sdist from two builds. Fresh-wheel journey: init, status, context, impact, `--record`, verify, `--run` (pass, then a regression), evidence (current, then stale), review, inventory, vet, the capability registry, recommend / candidates / select, adapter approval refused from an agent shell, doctor, uninstall |
| R5 | No research data in the wheel or sdist | **met** | checked in CI and locally |
| R6 | No default-on experimental feature: no automatic install or approval, and plugins are `review` at best | **met** | `--deny` always enforced (an unknown class exits 2). `select` executes nothing: a denied id exits 7 and a stale digest exits 6. Approval is refused from agent shells. A vetted plugin is REVIEW, not authorized, and makes no safety claim |
| R7 | Every published claim matches measured evidence, and negative results are visible | **met** | `STATUS.md`: plugin-vet fresh FAIL, discovery Corpus C FAIL, koa watchdog target missed, "agent benefit not demonstrated" |
| R8 | The security regression suites pass | **met** | adapter, menu, skills vet, inventory, review attribution, plugin containment, node attribution |
| R9 | No workflow can publish or change visibility | **met** | one workflow (`ci.yml`) with `contents: read`, no secrets, no environments, a private repository |
| R10 | Known limits are listed | **met** | `STATUS.md` |

## Why it is still not a release candidate

1. **Verify's own release blockers, from `VERIFY-RELEASE-REVIEW-2026-10.md`:**
   - **Speed:** short suites are still slower than native, by about 1 s of fixed cost a run.
   - **Hangs:** improved for unittest and pytest (h11 36.8 → 6.7 s). Node keeps the hard limit, so
     koa `mut-07` stays at 71–143 s, against a 15 s target.
   - **TypeScript:** only a recheck of one previously used project (skyhook, 8 of 8 detected), not a
     fresh validation.
2. **A false pass in node time-out attribution (#37)** existed in the engine that held-out-5
   measured. Its fix is covered by tests and an independent review, not by a held-out set.
3. **Windows:** no host sandbox; a container is required. The CI unit tests pass, but no held-out
   or timing run was made on Windows.
4. **Experimental features:**
   - plugin inspection: the fresh validation failed;
   - capability discovery: the fresh evaluation failed;
   - `--smart`, and third-party skills.
5. **Agent benefit has never been shown in a controlled trial.**

## What would change the decision

- A fresh held-out set measured on the integrated main, with speed and hangs included, and node
  in it.
- Either a node watchdog whose budgets are proven against node's event order, or accepting the node
  hang cost as a documented limit.
- A Windows run in a container.
