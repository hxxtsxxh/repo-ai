---
name: locate
description: "Find the files, symbols and line ranges relevant to a coding task, ranked with reasons. Use before exploring or editing unfamiliar code."
argument-hint: "<task description>"
---

# Locate code for a task

1. Run `repo-ai packet "<task>" --format claude`. Use `$ARGUMENTS` as the task
   if given; otherwise restate the user's request. The packet gives ranked
   locations, linked tests with a focused command, learned constraints for
   those files, the blast radius and what is uncertain.
   - Paste error messages or stack traces into the task: file:line frames are
     matched exactly.
   - For a longer ranked list use `repo-ai context "<task>" --agent claude`
     (`--scope diff` for uncommitted work, `--scope branch` for the branch).
2. Read the listed line ranges first. Widen to whole files only if needed.
3. The first one or two locations are the strongest evidence; further entries
   are weaker. If they do not contain the cause, Grep for the symptom's words
   or try `repo-ai symbol <Name>`, and say that the shortlist missed.

Confidence `low` means repo-ai found little evidence: fall back to Grep/Glob.
