# capability-fresh-v1: does `capabilities recommend` find the capability a task needs? (preregistered)

Acceptance gate C07. The discovery redesign failed its last fresh measurement (corpus C, 120 tasks: top-3 recall
0.385 against a gate of 0.80; 5 constraint-forbidden items in the top 3), and tuning stopped. This re-measures the
current matcher, unchanged, on a corpus written afterwards. Committed with the scorer before any task exists. $0;
offline; nothing runs but the matcher.

## Corpus (written after this file)

An author agent sees only `catalog-for-authors.json` (each capability's id, title, description, kind, languages and
network flag; not the matcher's need weights, lexicon or code) and `stacks-for-authors.json` (the stack profiles).
It writes **60** realistic developer task statements in `corpus.json`: `{"tasks": [{"id", "task", "repo_stack",
"changed_files", "gold": [capability ids that would genuinely help, possibly empty], "forbidden": [capability ids a
stated constraint rules out]}]}`. At least 15 tasks need none of the catalog (`gold` empty), and at least 10 state a
constraint ("offline", "don't run anything", "no new tools") that rules some capability out. The author does not read
`src/`, `tests/`, `docs/CAPABILITIES.md` or the lexicon, and reports what it read.

## Measurement

`score.py` runs `capabilities.recommend(task, stack, changed_files, manifest, {})` for each task (the same call as
`scripts/research/score_capabilities.py`) and compares its `recommended` ids (at most 3) with `gold`.

| id | measure | gate |
|---|---|---|
| R1 | top-3 recall over tasks with a non-empty `gold` (mean per task of \|recommended ∩ gold\| / \|gold\|) | **≥ 0.80** (the original gate) |
| R2 | recommended items that are in the task's `forbidden` | **0** |
| R3 | tasks with empty `gold` and no recommendation (correct abstention) | reported |
| R4 | top-3 precision (recommended items in `gold`) | reported |

C07 moves from EXPERIMENTAL only if R1 and R2 pass. One run; the matcher is not changed before it is recorded.
