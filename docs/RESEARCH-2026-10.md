# Competitive research: code intelligence, test selection, agent integration (2026-10-21)

**Method:** read-only research of official documentation, source code and
papers. No third-party code, skill, script or dependency was installed or
run. Marketing statements and agent-written testimonials are not counted as
evidence. URLs point at the files read.

## 1. Capability matrix

| Tool | What it solves | Real mechanism | Change impact / test selection | Runtime evidence | Dynamic loading | Agent interface | Licence | repo-ai stance |
|---|---|---|---|---|---|---|---|---|
| **GitNexus** ([upstream](https://github.com/abhigyanpatwari/GitNexus); `MatrixForgeLabs/gitnexus` is a stale fork) | precomputed code graph for agents (callers, flows, blast radius) | tree-sitter plus a home-grown scope resolver ([passes](https://github.com/abhigyanpatwari/GitNexus/tree/main/gitnexus/src/core/ingestion/scope-resolution/passes)); embedded graph DB (LadybugDB/Kuzu); incremental per-file updates | static BFS impact. Its "confidence" values are **hand-set constants per edge type** ([test](https://github.com/abhigyanpatwari/GitNexus/blob/main/gitnexus/test/unit/impact-confidence.test.ts)). No test selection | no coverage or traces (only opt-in Spring Actuator snapshots) | framework heuristics (Spring `getBean`). It labels dispatch boundaries as lower bounds; that is the idea worth taking | 19 MCP tools, plus a CLI | **PolyForm-Noncommercial-1.0.0** | learn from it; do not reuse code |
| **Serena** ([oraios/serena](https://github.com/oraios/serena)) | precise symbol retrieval and editing for agents | an LSP client over ~70 language servers ([solidlsp](https://github.com/oraios/serena/tree/main/src/solidlsp)); one-hop `references` | none | none | as good as the language server | MCP | `solidlsp` MIT; the app GPL-3.0-or-later since v2 | interoperate. SolidLSP is a candidate (MIT) precise-reference backend |
| **Aider repo map** ([repomap.py](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py)) | a ranked, token-budgeted repository summary for prompts | tree-sitter tags; a file graph built by **identifier-string matching**; personalised PageRank | none | none | none | internal to Aider | Apache-2.0 | ranking idea only, never impact evidence |
| **ast-grep** ([repo](https://github.com/ast-grep/ast-grep)) | structural search, lint and rewrite | Rust tree-sitter pattern matcher | none | none | can *detect* loader sites with rules | CLI, LSP, [MCP](https://github.com/ast-grep/ast-grep-mcp) | MIT | optional detector backend for more languages |
| **SCIP** ([scip.proto](https://github.com/sourcegraph/scip/blob/main/scip.proto)), language servers | compiler-precise references | indexers built on Pyright and the TypeScript compiler | none built in | none | none | file format / LSP | Apache-2.0 / MIT | future precise-reference layer |
| **pytest-testmon** ([testmon_core.py](https://github.com/tarpas/pytest-testmon/blob/main/testmon/testmon_core.py)) | rerun only affected pytest tests | coverage.py per-test contexts; AST-block fingerprints, CRC per function body ([process_code.py](https://github.com/tarpas/pytest-testmon/blob/main/testmon/process_code.py)); SQLite | per test, by dynamic coverage | **yes** | seen when executed during the test. **Import-time code is discarded** ([#191](https://github.com/tarpas/pytest-testmon/issues/191)); data files are not tracked ([#12](https://github.com/tarpas/pytest-testmon/issues/12), open since 2015); shadow validation was requested in 2018 and not built ([#89](https://github.com/tarpas/pytest-testmon/issues/89)) | pytest plugin | MIT | closest prior art: learn and interoperate |
| **Nx affected** ([docs](https://nx.dev/docs/features/ci-features/affected)) | affected projects in a monorepo | git diff → owning project → reverse project graph; a Rust lexer extracts **literal** import specifiers only ([locator](https://github.com/nrwl/nx/blob/master/packages/nx/src/native/plugins/js/ts_import_locators.rs)) | project-level | none | computed specifiers are invisible; a lockfile change affects everything | CLI, MCP | MIT | learn the "global trigger" rule; read `nx graph` output later |
| **Jest** `--findRelatedTests` / `--onlyChanged` | related test files | regex dependency extraction ([dependencyExtractor.ts](https://github.com/jestjs/jest/blob/main/packages/jest-haste-map/src/lib/dependencyExtractor.ts)) | per file, static | none | the docs state it needs "no dynamic requires" ([CLI](https://jestjs.io/docs/cli)) | CLI | MIT | baseline only |
| **Vitest** `related` / `--changed`, new `--since-last-run` | affected test files | Vite module graph ([affected-modules.ts](https://github.com/vitest-dev/vitest/blob/main/packages/vitest/src/node/affected-modules.ts)); the new recorder notes the modules each test **loaded at runtime** ([recorded-modules.ts](https://github.com/vitest-dev/vitest/blob/main/packages/vitest/src/node/recorded-modules.ts)) | per file | **yes** (recent, experimental) | captured when loaded at runtime. "No record → run it" | CLI; an [agent recipe](https://github.com/vitest-dev/vitest/blob/main/docs/guide/recipes/affected-tests.md) recommends a full run before finishing | MIT | strongest validation of the design; interoperate |
| **Bazel / Buck / Pants** | affected targets | declared (Bazel/Buck) or inferred (Pants, opt-in `string_imports`) dependency graphs | target-level; safe only as far as the declarations are correct | none | Pants has opt-in string imports | CLI | Apache-2.0 | out of scope (build systems) |
| **superpowers** ([verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)) | agents claiming "done" without evidence | Markdown instructions ("NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE"); one bisect script | none (asks the agent to run checks) | none | — | skills, SessionStart hook | MIT | complementary: repo-ai supplies machine-checked evidence that such a policy can require |
| **BMAD-METHOD** ([verification-gap](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/skills/bmad-code-review/review-prompts/verification-gap.md)) | agile agent workflow | persona prompts; a good "verification gap" review rubric | none | none | its rubric says to stop at dynamic dispatch | skills | MIT plus a trademark notice | learn from the rubric |
| **Greptile** ([how it works](https://www.greptile.com/docs/how-greptile-works/graph-based-codebase-context.md)) | AI PR review | proprietary code graph plus an LLM writing comments | call sites of changed functions (for review) | none | undocumented | PR bot | proprietary | avoid duplicating; repo-ai produces execution evidence, not opinions |
| **claude-mem** ([repo](https://github.com/thedotmack/claude-mem)) | cross-session memory | hooks capture **all tool I/O and prompts**; a model compresses them; SQLite/FTS5, optional cloud | — | — | — | hooks, MCP | Apache-2.0 | the anti-pattern for "verified memory": no code-change invalidation; redaction is opt-in |
| **Context7** ([repo](https://github.com/upstash/context7)) | current library docs for agents | cloud backend; a thin MCP/CLI client; stale docs served while refreshing | — | — | — | MCP, CLI, skill | MIT (client) | not comparable; its README asks users to add rules telling the model to use it, the same activation problem repo-ai measured |

**Published evidence is thin across the board.**
- No tool above publishes a methodologically sound recall or precision study
  of its impact or selection output.
- GitNexus has a SWE-bench harness but no published results.
- Serena's "evaluation" is the agent's self-assessment.
- Greptile's benchmark is vendor-run on 50 bugs.
- testmon publishes no recall figures.

## 2. Research findings on test selection

- **Safe selection** (Rothermel & Harrold, TSE 1996): select every test whose
  outcome could change. This is the target for "no-miss".
- **Ekstazi** (dynamic, file-level; Gligoric et al., ISSTA 2015): 32% average
  end-to-end time saved and 54% on longer suites, over 615 revisions of 32
  projects ([abstract](https://users.ece.utexas.edu/~gligoric/papers/abstracts/GligoricETAL15Ekstazi.txt)).
  Coarse dynamic dependencies beat fine-grained ones once overhead is counted.
- **Static RTS** (Legunsen et al., FSE 2016): class-level static selection
  was comparable to Ekstazi "at the risk of being unsafe sometimes", and
  reflection was the observed cause.
- **Google TAP** (Memon et al., ICSE-SEIP 2017): dependency-based selection
  runs about 99 passing tests for every failing one. Targets more than 10
  dependency edges away rarely break.
- **Meta Predictive Test Selection** (Machalica et al., 2019): halves
  infrastructure cost at over 95% failure recall, and is **unsafe by
  design**.

## 3. Agent integration surfaces (current docs)

**Claude Code** ([hooks](https://code.claude.com/docs/en/hooks)):
- `Stop` can return `{"decision":"block","reason":…}`.
- The input carries `stop_hook_active` (meant for loop avoidance), and there
  is a built-in cap of 8 continuations.
- `PostToolUse` cannot block, only add context.
- [Skills](https://code.claude.com/docs/en/skills) and
  [subagents](https://code.claude.com/docs/en/sub-agents) are invoked by
  **model choice**.
- CLAUDE.md is "context, not enforced configuration".

**Other agents:**
- **Codex CLI** ([hooks](https://learn.chatgpt.com/docs/hooks)): `Stop`
  block; hooks trusted by hash.
- **Cursor** ([hooks](https://cursor.com/docs/hooks)): `stop` →
  `followup_message`, `loop_limit` 5.
- **Gemini CLI** ([hooks](https://geminicli.com/docs/hooks/reference/)):
  `AfterAgent` deny → retry.
- **Aider** ([lint-test](https://aider.chat/docs/usage/lint-test.html)):
  `--test-cmd` / `--auto-test`, which runs after every edit.
- **Copilot cloud agent:** required CI checks.

## 4. What this means for repo-ai

1. **The gap no tool fills.**
   - None joins **runtime evidence of what each test executes** with a static
     graph, reports where both are blind (computed-name loading), and turns
     that into a sandboxed, attributable verification record.
   - testmon and Vitest's new recorder come closest. testmon misses
     import-time code and data files. Neither covers both Python and
     JavaScript, explains its selections, or classifies failures against a
     baseline.
2. **Activation must not depend on the model choosing a tool.**
   - repo-ai measured 0 skill invocations in 212 runs. Context7's README makes
     the same point.
   - A harness-executed completion gate (`Stop` hook), a CLI in an existing
     test slot (Aider), or CI are the reliable surfaces.
3. **Never ship uncalibrated confidence.** Use evidence classes and measure
   calibration (the GitNexus lesson).
4. **Licences:**
   - Ideas from GitNexus (PolyForm) and Serena v2 (GPL) are re-implemented
     from scratch, never copied.
   - MIT/Apache sources (SolidLSP, ast-grep, SCIP, testmon's design) are safe
     to interoperate with.
