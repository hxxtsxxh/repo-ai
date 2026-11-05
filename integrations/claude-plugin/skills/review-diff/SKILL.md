---
name: review-diff
description: "Review the current diff for correctness, security, tests and conventions, citing file:line. Read-only. Use when asked to review changes or a branch."
---

# Review the current changes

1. `git status --short` and `git diff` (use `git diff <base>...HEAD` for a branch).
2. `repo-ai impact --changed` for affected importers and tests.
3. Check, citing `file:line` for every finding:
   - correctness and edge cases; error handling;
   - security: secrets, injection, unsafe deserialisation, missing authz;
   - tests: does each behaviour change have a test? (`repo-ai impact` lists them);
   - conventions in the output of `repo-ai conventions`; generated files must not be hand-edited.
4. Order findings by severity. Do not modify files during a review.
