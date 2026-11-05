# An identity-preserving hybrid ranker: design only (not implemented, not enabled)

**Status:** a design for after the initial release.
- During the release freeze nothing here is built or switched on.
- The shipped ranker stays M1, the current one in `retrieval.py`.
- PR #57 stays a draft, and is not merged in its present form.

## Why

Session A's preregistered retrieval benchmark is on PR #57's branch, in `benchmarks/retrieval-eval/`: 18 repositories, split by repository; frozen at `29f7e71`; reproduced independently in `REVIEW-SESSION-A.md`. Two of its holdout findings matter here:

| Holdout | M1 (shipped) | M4b (full-text BM25, prototype `3470c7f`) |
|---|---|---|
| recall@5, natural language and error messages (n=296, primary) | 0.320 | **0.531** (+21.1 points, 95% CI [14.7, 25.5]) |
| recall@1, issue_symbol | **0.551** | 0.232 |
| recall@1, renamed | **0.883** | 0.733 |
| recall@1, exact_symbol | **0.858** | 0.750 |

BM25 more than doubles recall on prose queries. But adopted as the ranker, it lets similarity override explicit identity, which the mandate forbids, and it grows the index 2.8–5.7×. The prototype also relaxed tests that pinned identity-first ranking. Those relaxations are not acceptable, and the tests stay as they are.

The goal is to keep M1's identity results and gain BM25's prose recall.

## The design

The ranker works in three tiers. A later tier only orders what an earlier tier did not place.

1. **Identity, first and fixed.**
   - **What counts:** exact path mentions, stack-trace frames (file and line), symbol definitions named in the prompt (identifiers, `Class.member`, a prompt that is one name), and rename edges from history.
   - **How it ranks:** these candidates keep the rank M1 gives them today, and nothing below can displace one.
   - **Bound:** this tier is capped at the current result limit, so a prompt naming twenty symbols cannot crowd out everything else.
2. **Lexical evidence, second.**
   - BM25 over full text (SQLite FTS5, as in M4b) and the existing identifier and doc-text scores order the remaining slots.
   - Graph expansion fills the slots M1's signals leave empty: importers and imports, co-change, and test links, from the existing index.
   - **Bounded:** only a fixed share of the remaining slots, and never above a tier-1 hit.
3. **Local vectors, optional and off.**
   - M7, with local embeddings and no network, is not adopted: it failed its own criterion (+17.2 points against BM25's +21.1, at a higher cost).
   - It could return only as an opt-in tier-3 reorderer, after a new preregistered evaluation shows a benefit over tiers 1 and 2 on fresh repositories.

## Constraints, as acceptance criteria for the evaluation that would precede any merge

- **A preregistered evaluation on fresh repositories,** not the 18 used here, run independently (Session A).
- **Non-regression on identity:** recall@1 on `issue_symbol`, `renamed`, `exact_symbol` and `error_frame` is no lower than M1's, each within its preregistered margin. No test that pins identity-first ranking is relaxed.
- **Primary gain:** holdout recall@5 on natural language and error messages improves over M1, with a confidence interval that excludes zero.
- **Abstention:**
  - the false-injection rate on irrelevant and sensitive prompts does not rise;
  - `benchmarks/run.py`'s false injection stays at 0%.
- **Cost:**
  - index growth at most 2× (M4b grew it 2.8–5.7×);
  - `context` p95 latency at most 1.25× M1's;
  - the prompt hook stays within its token budget.
- **Privacy:**
  - no network, and no new store of prompt text;
  - the full-text index follows the existing quarantine of secret files.

## Known limits of M1 the hybrid would address (documented for the release)

- **Prose queries:** recall@5 of 0.320 on the holdout means a natural-language task often does not surface its files. Use exact names, paths or stack traces where you can, or `repo-ai search`, `symbol` and `related`.
- **Symbols named like common English words** (`mean`, `get`, `update`, `add`):
  - found when the prompt is the name alone (fixed during the freeze; 0 of 1,375 holdout queries change);
  - **not** found when written as a call or in backticks inside prose (`mean()` raises …): those words are stopwords there.
  - Extracting them changes 31 holdout queries, so it belongs to this evaluated change, not to the freeze.
