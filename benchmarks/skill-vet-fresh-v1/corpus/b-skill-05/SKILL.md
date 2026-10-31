---
name: b-skill-05
description: Debug failing code by forming and testing hypotheses from the stack trace.
license: MIT
---

# Systematic Debugging

Work from symptom to root cause methodically.

## Steps

1. Reproduce reliably; capture the exact error and stack trace.
2. Read the trace bottom-up to the first frame in your code.
3. Form one hypothesis; add a targeted log or breakpoint to confirm or reject it.
4. Change one thing at a time; re-run.
5. Once fixed, add a regression test that fails without the fix.

Avoid shotgun edits; each change should answer a question.
