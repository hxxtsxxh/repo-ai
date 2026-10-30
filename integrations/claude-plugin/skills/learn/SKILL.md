---
name: learn
description: "(experimental) Review repo-ai's proposed project rules and skills with their evidence, and apply the ones the user approves."
disable-model-invocation: true
---

# Review learned project guidance

1. Run `repo-ai learn status`, then `repo-ai learn review` for proposals with
   confidence and evidence (and a promotable outcome prior, if any).
2. For any the user asks about, run `repo-ai learn explain <id>`.
3. Apply only what the user approves: `repo-ai learn approve <id>`; reject with
   `repo-ai learn reject <id>`. `repo-ai learn friction` lists repeated waste.
4. `repo-ai learn history` and `repo-ai learn rollback <event>` undo changes.

repo-ai edits only its own managed blocks and files; never hand-edit them, and
never move human-written CLAUDE.md text.
