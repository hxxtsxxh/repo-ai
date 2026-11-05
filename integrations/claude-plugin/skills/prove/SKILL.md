---
name: prove
description: "(experimental) Show that the original code fails a pinned acceptance scenario and the change passes it, with no regression: a verification passport for the PR."
argument-hint: "<the claim, in one sentence>"
disable-model-invocation: true
---

# Prove a change (ProofLab, experimental)

1. Agree with the user on the claim (one sentence) and the acceptance
   scenario: a test file that checks the observable behaviour. Prefer one the
   user or a reviewer wrote: `--from <their commit>` or `--file <path>`. If
   you write it yourself, say so; the passport records that the oracle may
   not be independent.
2. Pin it before you change the code (reads files, runs nothing):

   ```sh
   repo-ai prove pin --scenario tests/test_x.py --subject "$SUBJECT" --claim-stdin <<'CLAIM'
   $ARGUMENTS
   CLAIM
   ```

   Set `SUBJECT` to the repository-relative path of the declared code under
   test before running the command; an inferred subject cannot support a claim.
   Do not edit the pinned scenario, its helpers or conftest.py afterwards. If
   the scenario is wrong, tell the user: re-pinning shows in the passport.
3. `repo-ai prove plan` (read-only). Resolve every NOT READY item it lists.
4. Make the change.
5. With the user's go-ahead (it runs repository code, sandboxed):
   `repo-ai prove run`.
6. Report the headline, the reasons and the "not established" list as they
   are printed. Only the verdict `supported` supports the claim, and only
   for the pinned scenario.
7. `repo-ai prove report --out .repo-ai/proof.md` writes the passport for the pull
   request; `repo-ai prove status` says whether it still covers the tree.
