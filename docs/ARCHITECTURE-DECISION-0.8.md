# Architecture decision: repo-ai as a change-verification engine (2026-10-21)

**Status:** proposed with a working vertical slice (`repo-ai verify`). It is
not released and not merged.

**Inputs:**
- `docs/PRODUCT_REVIEW-v0.8.md` (PR #21);
- `docs/RESEARCH-2026-10.md`;
- the two controlled coding experiments;
- the offline audits;
- `benchmarks/verify-eval/` (results in `RESULTS.md`).

## 1. The problem, ranked

Each candidate problem is scored from 1 to 5 on five criteria: **impact**,
**frequency**, **feasibility** (offline and deterministic), **open space**
(not already solved well), and **measurable** (can a difference be shown
without paid model runs).

| Problem | Impact | Frequency | Feasible | Open space | Measurable | Notes |
|---|---|---|---|---|---|---|
| **Knowing whether a change was actually verified** (by an agent or a person) | 5 | 5 | 5 | 4 | 5 | Agents claim "done"; superpowers asks for evidence in prose; nobody produces machine-checked evidence tied to the exact change |
| **Finding the tests that can catch a regression in *this* change** | 5 | 5 | 4 | 3 | 5 | testmon (pytest only), Jest/Vitest (JS, static, or new and experimental), Nx (project-level) |
| **Indirect consequences / blast radius** | 4 | 4 | 4 | 2 | 4 | GitNexus and Serena exist. Static only, with uncalibrated confidence |
| **Being honest where static analysis is blind** (dynamic loading) | 4 | 3 | 4 | 4 | 5 | 0.7.7 reported "risk: low" while missing 12 of 13 failing cases on Python-Markdown |
| Tracing failing tests to root cause | 4 | 4 | 3 | 3 | 3 | partly follows from runtime evidence (which test ran which changed unit) |
| Telling new failures from pre-existing ones | 3 | 4 | 5 | 4 | 5 | cheap: re-run failing tests on the base revision |
| Persistent project knowledge | 3 | 4 | 3 | 1 | 2 | crowded (claude-mem and others); repo-ai's own learned rules caused 3 wrong instructions |
| Cross-repository dependencies | 3 | 2 | 3 | 3 | 3 | later |
| Safe specialist workflows (skills) | 2 | 2 | 3 | 2 | 1 | 0 invocations in 212 runs; benefit unmeasurable cheaply |
| Making the model smarter with more context | ? | 5 | 5 | 1 | 1 | two experiments showed no benefit; retrieval ties grep on fresh tasks |

## 2. Decision

**repo-ai becomes an evidence-driven change-verification engine.** It tells
developers and coding agents three things:
- what a change touched;
- which tests can show whether it broke something, and how sure that is;
- what running them in a sandbox actually showed.

The answer is a **machine-checkable record** tied to the exact change.

**The capability plain Claude Code lacks** is not more instructions. It is
**runtime evidence**: which code units each test actually executed, recorded
once in a sandbox and keyed to file content. This is joined with the static
import graph and with an explicit model of where both are blind. The model
cannot get this from grep. The research found no other tool that combines:
- per-test runtime evidence, including import-time code and data files that
  testmon misses;
- a static closure that falls back explicitly;
- dynamic-loading detection that lowers confidence;
- sandboxed execution with baseline classification;
- change-fingerprinted evidence for agents.

**Challenge to the owner's hypothesis.** It holds, with one refinement:
"guardian" should not mean interrupting edits. The evidence on activation
(0 skill invocations, CLAUDE.md being "context, not enforcement") favours
two surfaces:
- a **completion gate**, the `Stop` hook, which is silent unless the change
  is unverified;
- the **CLI/JSON** for humans and CI.

It should not be an after-every-edit hook that injects context.

## 3. Architecture (what the slice implements)

```
              changes.py ──┐                  ┌── execute.py (sandbox: bwrap/seatbelt with the
 git diff ──▶ code units   │                  │    project interpreter, or podman/docker)
              (Python AST) ├─▶ select.py ─────┼─▶ engine.run_plan ─▶ evidence.py (fingerprinted record)
 index (static graph) ─────┤  union/authority │    baseline re-run of failures (git archive)
 dynamic.py (blind spots) ─┤  + triggers      │
 testmap.py (runtime) ─────┘  + confidence    └── gate.py (Stop hook)   report.py (terminal)
            ▲
            └── rai_trace.py (sys.monitoring, stdlib-only) / NODE_V8_COVERAGE, recorded in the sandbox
```

**Layer A, the code-intelligence graph.**
- **Existing:** the import graph. A src-layout resolution bug was fixed.
- **New:**
  - code units, keyed `firstlineno:name`, the same key the tracer records;
  - runtime test→unit edges;
  - opened data files;
  - dynamic-loading sites and entry-point registrations, with provenance.
- **Deferred:** call graphs and precise references (SCIP or language
  servers).

**Layer B, the change guardian.**
- **Implemented:**
  - changed units, with comment-only edits recognised as non-behavioural;
  - static and runtime consumers, with explanation chains;
  - triggers;
  - confidence classes (evidence classes, not invented numbers).

**Layer C, execution-backed verification.**
- **Implemented:**
  - sandboxed per-file runs;
  - baseline classification;
  - failure excerpts;
  - a full-suite fallback;
  - JSON evidence.
- **Deferred:** coverage.py and Vitest recorder import.

**Layer D, verified memory.**
- **Deliberately minimal:** the evidence store and the testmap are verified
  facts keyed to content hashes, invalidated by content change.
- **Not built:** no prose memory. No speculative rule becomes guidance.

**Layer E, delivery.**
- **Implemented:**
  - the CLI;
  - JSON schemas `repo-ai.verify-plan/1` and `repo-ai.verify-evidence/1`;
  - the gate;
  - the updated `/repo-verify` skill.
- **Deferred:** MCP (not needed for activation), CI annotations.

## 4. Keep, simplify, isolate, retire

| Component | Decision | Why |
|---|---|---|
| Index, scanner, parser, import graph, `impact`, `review` | **Keep** (the verify engine builds on them) | correct and fast; impact recall was the strongest prior measurement |
| Sandbox, evaluation lab, statistics, integrity | **Keep** | they make claims checkable |
| Security, privacy, uninstall guarantees | **Keep** | non-negotiable |
| Prompt hook shortlist and `context` retrieval | **Simplify to opt-in** | on fresh tasks it ties grep; Claude searches on its own |
| CLAUDE.md block and generated context docs | **Simplify** to a short pointer; docs on demand | never read in recorded runs; some labels wrong |
| Learned rules | **Isolate**: proposals only, never auto-applied by default | three incorrect instructions found; PR #22 fixes two |
| Curated skills | **Keep two** (`/repo-verify`, `/repo-impact`), manual-friendly | model invocation was 0 of 212; the gate replaces "remember to verify" |
| Subagents, skeptic, orchestration (Full) | **Retire from defaults**, keep opt-in | no use or benefit measured; about 10% extra cost |
| Third-party skill network | **Isolate as experimental** (PR #22 contains its defects) | discovery partial, ranking unevaluated, screening static, benefit unmeasured |
| Outcome learning, governor, optimize, performance, friction, Stack Packs, crossrepo | **Freeze** (no new work) and label experimental | proxy metrics only |

None of this is applied by this slice except the `/repo-verify` skill text.
Defaults change only with the owner's approval.

## 5. Positioning

> **repo-ai is the local verification layer that tells you, and your coding
> agent, what a change touched, which tests can catch a regression in it,
> and what running them actually showed, with evidence and honest
> uncertainty.**

**What is differentiated:**
- runtime-evidence test selection that covers import-time code and data
  files;
- an explicit, tested model of static blind spots;
- baseline-classified, change-fingerprinted evidence;
- a completion gate that does not depend on the model choosing a tool.

**Why install it:**
- a faster, explained "which tests matter for this diff";
- an honest "run everything" when it cannot know.

**Why keep it after a week:**
- evidence is reused across edits (record once, select many times);
- `repo-ai evidence` answers "did this exact change pass?";
- the gate catches unverified agent "done" claims.

That last point is a hypothesis to measure.

**What works without any model:** everything above.

**What an agent adds:** the gate turns "verify before done" from an
instruction into a check.

**What proof would justify productivity or correctness claims:**
- **Offline (now):** the measured no-miss rate and the share of suite time
  on held-out repositories (`RESULTS.md`).
- **For agents (not yet):** a pre-registered experiment on tasks where
  plain Claude often *ships regressions*, comparing gate on and off for
  regressions shipped and false "done" claims. That needs separate
  authorization and budget.

## 6. Roadmap after the slice (priority order)

1. **Shadow validation (`verify --shadow`).** Occasionally run the full
   suite and report what the selection would have missed, building a
   per-repository recall record (testmon #89 never shipped this).
2. **Interoperate:**
   - import coverage.py contexts and pytest-testmon data when present;
   - read Vitest's recorded dependencies;
   - this avoids re-recording.
3. **Precise references for changed symbols** (SCIP or language servers),
   to narrow static selection when runtime evidence is stale.
4. **Ship the gate:** an `init --verify-gate` option with an uninstall path;
   Codex/Cursor/Gemini adapters for the same entry point.
5. **CI mode:** `repo-ai verify --base origin/main --run --json` with
   annotations; evidence as a build artifact.
6. **Default changes:** advisory install (from PR #21), with rules as
   proposals.
7. **Only then** a paid, pre-registered agent experiment, on a task set where
   plain Claude often breaks unrelated tests.
