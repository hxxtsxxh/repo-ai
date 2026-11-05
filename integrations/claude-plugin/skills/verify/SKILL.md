---
name: verify
description: "Pick and run the smallest reliable set of tests and checks for the current changes, then widen if needed. Use before declaring work done."
---

# Verify the current change

1. `repo-ai verify`: the changed code, the tests that can show whether it
   broke something (each with the evidence linking it), and a confidence.
   It is read-only.
2. With the user's go-ahead (it runs repository code, sandboxed):
   `repo-ai verify --run` runs those tests and checks every failure against
   the base revision (new failure vs. already failing). When the plan says
   the full suite is required, it runs that too.
3. Fix new failures. Report failures that were already present separately.
4. Before declaring the work done, run the full suite: the project's test command (see TESTING.md)
   (or, with the same go-ahead, `repo-ai verify --run --full`). Run the lint/type-check commands from
   TESTING.md when the change touches typed or linted code.

Report exactly which commands ran and their results (`repo-ai evidence`).
Never claim a check passed if it did not run; a passing targeted run is not
proof that the change is correct.
