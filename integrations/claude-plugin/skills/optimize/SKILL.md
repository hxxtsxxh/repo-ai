---
name: optimize
description: "(experimental) Propose evidence-backed improvements to repo-ai in this repository and apply only what the Self-Improvement Governor allows, with the user's agreement."
disable-model-invocation: true
---

# Optimise

1. Run `repo-ai optimize` (a read-only plan). Each proposal has a hypothesis, the
   evidence, the experiment that would confirm it and the governor's decision.
2. Present them, most valuable first. Proposals the governor will not apply
   (installs, disabling skills, experiments with cost) need the user: give the
   command and let them decide.
3. Only if the user agrees, run `repo-ai optimize --apply`. Every change is
   journaled; `repo-ai optimize --revert` undoes it.
