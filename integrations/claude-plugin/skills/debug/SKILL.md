---
name: debug
description: "Debug a failure in this repo: locate from the error, reproduce with a focused test, fix minimally, re-run tests. Use for bugs and stack traces."
argument-hint: "<error, stack trace, or symptom>"
---

# Debug a failure

1. Locate: `repo-ai context "<error message and stack trace>" --agent claude`.
2. Hypothesise: state the most likely cause in one sentence, citing file:line.
3. Reproduce: run the narrowest existing test for that code
   (`repo-ai impact <path>` lists them), or write a minimal failing test next
   to the existing ones.
4. Fix: the smallest change that makes the reproduction pass.
5. Verify: re-run the focused test, then the broader suite for that component.

Stop and ask if the reproduction does not fail the way the report says.
