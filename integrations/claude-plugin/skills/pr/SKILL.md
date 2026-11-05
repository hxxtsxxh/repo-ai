---
name: pr
description: "Prepare a pull request for the current change: an evidence-based change passport and a draft PR description. Never pushes or opens the PR itself."
disable-model-invocation: true
---

# Prepare a pull request

1. Run `repo-ai review --changed` (or `--branch` for the whole branch). It lists
   changed components, reverse dependencies, recommended tests and whether they
   were seen passing, API/migration/dependency/CI risks, secret-scanner findings
   in added lines, and blind spots. It is evidence, not an approval.
2. Run the recommended test commands that have not been seen passing, and fix
   failures before going on.
3. Draft the PR description: a summary of what changed and why, the risks from
   the passport and how each was handled, the tests run and their results, and
   anything left unverified, stated plainly.
4. Show the draft to the user. Do not push, open the PR or merge unless the user
   explicitly asks; those actions go through the normal permission prompts.
