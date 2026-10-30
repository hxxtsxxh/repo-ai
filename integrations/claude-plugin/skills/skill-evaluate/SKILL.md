---
name: skill-evaluate
description: "(experimental) Measure whether an installed third-party skill improves task success with a controlled, sandboxed with/without trial (billable; needs a budget)."
argument-hint: "<installed skill name>"
disable-model-invocation: true
---

# Evaluate a skill (billable)

1. Ask the user for a maximum spend in USD. Do not guess one.
2. Plan the trial first: `repo-ai skills benchmark $ARGUMENTS --dry-run --max-cost-usd <B>`.
   Show the number of runs and the worst-case cost.
3. Only after the user confirms, run it without `--dry-run`. Report the verdict,
   number of pairs and invocation rate. Fewer than 10 pairs is a pilot:
   directional, not significant.
4. If outcomes were worse with the skill, suggest `repo-ai skills disable <name>`.
