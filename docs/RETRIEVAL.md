# Retrieval: how `repo-ai context` ranks files

Lexical + structural + historical, fully explainable. Run
`repo-ai explain "<task>"` to see the per-signal breakdown for any prompt.
There are no embeddings; earlier releases advertised an embeddings extra that
was never implemented, and it has been removed.

## Pipeline

1. **Classify the prompt** into task classes (auth, api, database, ci, deploy,
   test, frontend, config, performance, security, observability, dependency,
   docs, refactor, bug, feature), using whole-word matching for short keywords.
   Then extract:
   * identifiers (camelCase, snake_case, PascalCase, `Class.member`, quoted);
   * file paths and `@path` mentions;
   * URL paths;
   * **stack-trace frames** (Python, JS/TS, Go/Rust/C-style `file:line`, Java/Kotlin);
   * terms, with stop and conversational words removed and identifiers split
     into subwords.
2. **Score**, with every contribution recorded per file:

| Signal | Weight | Counts as evidence? |
|---|---|---|
| `trace_frame` — a stack frame points into the file | 8.0 | yes |
| `path_literal` — the path is named in the prompt | 9.0 | yes |
| `symbol_exact` — a named identifier is defined here (0.35× for fuzzy matches) | 6.0 | yes |
| `lexical` — BM25 (identifiers 3× text) × IDF-weighted term coverage × vocabulary hit | 5.0 | yes |
| `route_match` — a URL in the prompt is served here (0.4× for a term inside a route) | 4.0 | yes |
| `intent_canonical` — the canonical file for the task class (CI workflow, Dockerfile, manifest…) | 5.5 | yes |
| `intent_path`, `intent_role` | 2.4, 1.6 | no (damped to 0.45× without evidence) |
| `centrality`, `recency`, `churn`, `entrypoint` | 2.2, 1.5, 0.9, 1.2 | no |
| `neighbour` (imports/importers of evidenced seeds), `coupling` (co-change), `test_of` (test links) | 1.8, 1.5, 1.8 | no, but they qualify a file |
| penalties: generated, vendored, depth, low-value files | −6, −4, −0.18/level, −4 | — |

3. **Gate.** A file reaches the list only with content evidence, or as a
   neighbour, co-change partner or linked test of an evidenced file. Priors
   alone never qualify a file. Confidence is computed as follows:

   | Confidence | Condition |
   |---|---|
   | `high` | a trace frame, path, symbol or route hit; or lexical strength ≥ 0.45 with ≥ 2 matched terms |
   | `medium` | lexical strength ≥ 0.25 with ≥ 2 matched terms; or a canonical file with lexical support |
   | `low` / `none` | otherwise |

   With `none` the result is empty. The prompt hook injects only `medium` and
   `high` results.
4. **Assemble.** Drop results below 22 % of the top score. Merge line ranges:
   symbol and frame ranges come first; if there are none, use the symbols
   whose names share a word with the task. Then apply a directory-diversity
   cap (`max(3, limit // 3)`) and promote the top source file's
   import-linked test into the first five results.
5. **Budget.** The CLI uses `context_budget_tokens` (6000). The hook keeps the
   leaders (≥ 35 % of the top score), at most `hook_max_files` (8), within
   `hook_budget_tokens` (1200) and 9,000 characters.

Scopes restrict the candidate set, plus neighbours and tests:
`--scope diff`, `branch[:base]`, `component:<name>`, `lang:<language>`,
`path:<glob>`, `tests`.

Results are cached in the index (`query_cache`). The cache key covers the
prompt, the options, the weights, the repo-ai version, and a fingerprint of
every indexed file's hash plus HEAD, so any edit or deletion invalidates it.
`diff` and `branch` scopes are never cached.

## Index facts that feed ranking

* **FTS5** with Porter stemming. The identifier column holds path segments,
  symbol names and their subwords (`validate_credentials` → `validate
  credentials`), and route path words. Terms of five or more characters also
  match as prefixes (`route` → `router`). User text is always quoted, so FTS
  operators in a prompt are inert.
* **Import graph**, with tsconfig/jsconfig path aliases, relative imports,
  index/`__init__`/`mod.rs` probing, Python `from pkg import module` (an
  optional edge, kept only if the module file exists), first-party package
  detection, and suffix lookup. The whole graph is re-resolved on every
  update, so a deleted file leaves no stale edges.
* **Test links**: tests that import a source file (strong) or name it by
  convention (`test_x.py`, `x.test.ts`, `x_test.go`, `XTest.java`; used only
  when the match is unique).
* **Git**: churn, recency (60-day half-life), and co-change coupling
  (commits of 2–25 files, ≥ 3 co-changes).

## Evaluation

`benchmarks/run.py` copies each fixture in `tests/fixtures/`, gives it a
deterministic git history, runs `repo-ai init`, and evaluates the cases in
`benchmarks/gold.json`. There are 20 relevant tasks across Python/TS, Go,
TS-monorepo, Java and .NET fixtures, and 6 irrelevant prompts. Every call is
a subprocess, so latency includes interpreter start-up.

| Metric | v0.4.0 | v0.5.0 |
|---|---|---|
| recall@5 | 0.875 | **1.0** |
| MRR | 0.822 | **0.875** |
| irrelevant prompts that still inject context | **100 %** | **0 %** |
| relevant prompts that get hook context | 100 % (unconditional) | 95 % (gated) |
| Bob-format hook tokens, mean (relevant) | 455 | 321 |
| Claude hook payload, mean (relevant) | — | ~185 tokens (738 chars) |
| query latency p50 / p95 | 0.115 / 0.117 s | 0.105 / 0.110 s |
| Claude prompt-hook round trip p50 / p95 | — | 0.067 / 0.073 s |
| `init` p50 (fixtures) | 0.57 s | 0.61 s |

A synthetic 4,002-file repository (Python + TSX) gave:

* `init --agent claude --smart`: 1.8 s
* single-file `update`: 0.58 s
* `context`: about 0.10 s
* prompt hook: about 0.13 s
* index size: 6.1 MB

Raw numbers: `benchmarks/results/*.json` (macOS, Python 3.12).

**Caveats.** The gold set is small and was written alongside these changes, so
treat the numbers as regression guards, not as general accuracy claims. The
one relevant prompt that gets no hook context
("transfers should reject overdrafts…") matches a single term; the CLI still
returns the right file, but at `low` confidence.

Add your own cases to `gold.json`. If a change raises recall but also raises
the false-injection rate, that is a regression.

## Tuning

All weights are in `WEIGHTS` in `src/repo_ai/retrieval.py`. Change one, rerun
`python benchmarks/run.py`, and compare against `benchmarks/results/v0.5.0.json`.

## v0.7.2 recall investigation (tried, measured, **not shipped**)

**Why we looked.** repo-ai trailed grep on recall@5 in the synthetic
holdout. The dev split (24 tasks) showed three causes:
1. Only the first 16 query terms were searched (`classify` capped at 30).
   Long reports name the decisive word late.
2. Filename matches counted fully even for words found in most files
   ("orders").
3. Java same-package references have no import edge, so neighbour expansion
   missed them, and the score floor cut short lists to one or two files.

**What was tried** (all tuned on dev only):
- every query term (up to 48), de-duplicated case-insensitively;
- IDF-weighted filename matches;
- same-package sibling expansion;
- a minimum of 5 candidates;
- reciprocal-rank fusion and coverage union.

The last two were discarded on dev already.

**Results** (recall@5 / all-gold@5 / MRR):

| Split | v0.7.1 | with the changes | paired test (MRR) |
|---|---|---|---|
| dev 24 (tuned on) | 0.736 / 0.708 / 0.680 | 0.833 / 0.792 / 0.738 | 7 better, 0 worse, Wilcoxon p = 0.016 |
| holdout 35 (measured once, not tuned) | 0.674 / 0.600 / 0.574 | 0.746 / 0.686 / 0.608 | 10 better, 5 worse, p = 0.29 |
| **final 25 (sealed real-repo tasks)** | 0.853 / 0.800 / 0.606 | 0.833 / 0.800 / 0.564 | 6 better, 5 worse, p = 0.56 |

**Decision.**
- The only significant gain is on the split the changes were tuned on.
- On held-out synthetic tasks the gain is not significant.
- On real repositories the changes are neutral to slightly worse.

That does not meet the bar for shipping a ranking change, so v0.7.2 keeps
the v0.7.1 ranker. Both versions are far ahead of grep on the real
repositories (grep: 0.580 / 0.560 / 0.420).

**Next time:**
- Evaluate on a larger sealed set first. The 25 final tasks have now been
  examined for *localization*, so retrieval work needs a fresh sealed set.
  No model run has used them, so they are still unexamined for coding
  experiments.
- Ship only what holds there.
