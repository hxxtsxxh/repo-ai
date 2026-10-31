---
name: b-skill-12
description: Diagnose and optimize slow SQL queries.
license: MIT
---

# SQL Query Optimization

Find and fix slow queries with evidence, not guesswork.

## Method

- Capture the actual query plan (`EXPLAIN ANALYZE`).
- Look for sequential scans on large tables, nested-loop joins on big inputs, and sorts that
  spill to disk.
- Add indexes that match the query's filter and join columns; verify the plan changes.
- Avoid `SELECT *`; fetch only needed columns.
- Re-measure; keep the change only if it actually helps.

Index deliberately: every index speeds reads but slows writes.
