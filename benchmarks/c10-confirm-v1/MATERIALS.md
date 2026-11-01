# c10-confirm-v1 materials (frozen before the first live call)

Written after the preregistration (commit `119cb67`) and Amendment 1 (`5cbc855`), by three separate agent sessions,
each reading only its own inputs (no `src/repo_ai/`, no pilot material, no result):

- **Author A** (fixture and skill): `fixture/` (`stockroom`, an in-memory stock ledger; 9 modules, 25 visible tests
  passing) and `skill/stockroom-conventions/` (14 numbered conventions; A's notes in `A_NOTES.md`: rules 1–5 visible
  in the code, rules 6–14 not inferable from it).
- **Author B** (tasks and oracles), given only `fixture/` and the SKILL.md text: `tasks.json` (8 tasks) and
  `oracle/test_t1.py`…`test_t8.py`, 30 assertions (8 baseline, 22 convention), all passing on B's own reference
  implementation (discarded). Rule 2 is not exercised (the code already shows it).
- **Reviewer C**, given fixture, SKILL.md, tasks and oracles: `REVIEW.md`. One assertion deleted
  (`test_t7_convention_tuple_in_recorded_order`: rule 5's "several records" may not cover rendered lines). C noted a
  minor leak in t5's request (it reveals the 0–100 scale of rule 9, not its type, precision or rounding).

Frozen set: **29 assertions (8 baseline, 21 convention)**; every task keeps at least one convention assertion. On
the untouched fixture no oracle assertion passes (0 of 29). Harness: `run.py`.
