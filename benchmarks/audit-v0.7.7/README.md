# Offline tool audit (repo-ai 0.7.7, 2026-10-21)

These are the measurements behind `docs/PRODUCT_REVIEW-v0.8.md`. They made no
model calls and used no network.

**Corpus:** public, permissively licensed snapshots already in this repository:
- the 6 `benchmarks/tasks/bases/oss-*` projects;
- the 8 sealed-v2 bases;
- repo-ai's own `src/` and `tests/`.

Each was copied to a scratch directory, committed once, and indexed with
`repo-ai init`, using an isolated `HOME`.

| Measurement | Script | Ground truth | Result |
|---|---|---|---|
| Symbol lookup | `scripts/symbols.py` | Python `ast` definitions; 40 seeded names per repository, 15 repositories | `results/symbols.json` |
| Test selection (impact) | `scripts/mut_plan.py`, `mut_inside.py`, `mut_score.py` | **Mutation:** one function body replaced with `raise`, then the project's own test suite run in the podman sandbox (`--network=none`). Failing test files are recorded. 16 seeded mutations per repository, 10 repositories | `results/impact-mutation-score.json`, `results/mutations-*.json` |
| Localization (file ranking from the prompt) | `repo-ai eval --offline --no-validate` | each task's gold files | `results/localization.json` |

**Reproducing:**
1. Run the planner and scorer on the host, and the inner script inside a
   container, as `mut_inside.py` documents.
2. Use the seeds (0) and the per-base test commands from `bases.json`.

**Caveats:**
- **Python only.**
- Mutations work at function-body level and are scored at test-file level.
- sealed-v2 localization was run here for the first time. It is therefore no
  longer unexamined for retrieval work.
