# Continuous optimisation

repo-ai can tell you which parts of itself earn their context in this
repository, propose evidence-backed improvements, and apply a narrow class
of them automatically under a governor.

**What it works from:** only records kept on this machine:
- episodes (`learning_signals = "outcomes"`);
- the flight recorder (`flight_recorder = true`);
- coding-lab experiments;
- the skill portfolio.

Nothing is sent anywhere.

```sh
repo-ai performance          # what was measured, on how many samples; "not recorded" otherwise
repo-ai capabilities         # coverage map: gaps -> skills/agents -> measured benefit
repo-ai friction             # repeated, evidence-backed waste
repo-ai optimize             # research proposals (read-only)
repo-ai optimize --apply     # apply what the Self-Improvement Governor allows (journaled)
repo-ai optimize --revert [ID]
repo-ai pack list | plan     # Stack Packs from repositories in this repo's zone
```

Inside Claude Code the same views are available as manual-only skills:
`/repo-performance`, `/repo-capabilities`, `/repo-optimize`,
`/repo-discover-skills`, `/repo-skill-audit`, `/repo-skill-recommend` and
`/repo-skill-evaluate`. Manual-only means:
- they cost no always-loaded context;
- they run only when you type them.

## Evidence and its limits

Each prompt is paired with the files edited after it and before the next
prompt. "Edited after the shortlist named it" is a **proxy** for "the
shortlist helped", not proof. That is why every proposal names the
controlled experiment that would confirm it.

## Zero-Value Detector

For each installed skill:
- **origin:** native, generated, third-party or yours;
- **standing context cost:** its description, which Claude loads every
  session unless the skill is manual-only;
- **use count:** across recorded sessions.

A skill with a standing cost and **zero uses in ≥ 10 sessions** is
reported as zero-value, together with an estimate of the tokens it consumed.

**What happens next depends on origin:**
- third-party and generated skills get a `skills disable` command;
- your own skills are only reported, never touched.

The prompt hook is zero-value when an injected file was edited after fewer
than 20 % of ≥ 12 prompts. The proposal is then an ablation experiment, not
a removal.

**Not observable:** subagent use (Claude Code does not report it to the
hooks repo-ai uses) and learned rules (read, not invoked). These are listed
as such.

## Context-budget governor

The governor sizes the prompt shortlist to what sessions actually use:
- From ≥ 12 injected prompts followed by edits, it finds the rank that
  covers the first edited file in 90 % of prompts.
- It proposes `hook_max_files` at that rank, moving at most one halving or
  doubling per step. Its evidence:
  - hit rate (an injected file was edited);
  - precision;
  - the p90 rank;
  - the risk (how many observed prompts would have lost their file).

## Research proposals

`repo-ai optimize` lists hypotheses. Each comes with its evidence, the
command that would confirm it, the metric, the risk, and the governor's
decision. Sources:
- the budget governor;
- reverts (a change after which the hit rate fell by more than 10 points);
- zero-value skills;
- friction;
- the outcome prior's shadow test;
- skill evolution;
- third-party skills without measured benefit;
- the absence of any live experiment.

**Skill evolution** applies to generated skills only:
- **Revise:** sessions using a skill verify significantly less often than
  comparable sessions without it (Fisher exact, p < 0.1). This is labelled
  an association, not a cause.
- **Settle a canary:** two versions both have ≥ 5 uses.

## Self-Improvement Governor

The governor may apply a proposal automatically only if **all** of these
hold:
- it is a `tune` (or the `revert` of one) of a repo-ai-owned retrieval
  knob: `hook_max_files` (2–8) or `hook_budget_tokens` (400–1600);
- the key is **not set explicitly** by you, the repository, the
  environment or a flag (explicit settings always win);
- the step is at most a halving or doubling;
- no other change was applied in the last 7 days.

**Never automatic:** permissions, hooks, installs, disabling skills,
network access, experiments with cost, user-authored files.

**Where changes go:** a machine-local `tuning.json` in the state directory,
never into a committed file. Each change is journaled with its evidence in
`optimize-journal.json`.

**Reverting:**
- `optimize --revert` undoes a change.
- If the hit rate falls after a change, a revert is proposed.
- Tampered `tuning.json` values outside the bounds are ignored.

## Stack Packs (cross-repository learning, one zone)

`repo-ai registry contribute` stores a sanitized per-repository pattern in
the repository's zone. It contains:
- languages, frameworks and test frameworks;
- rule kinds;
- generated skill names;
- outcome counts;
- pinned **public** third-party skills (owner/repo@commit and content hash).

It never contains paths, code, prompts, names or local skill sources.

**How a pack is built:**
- Packs come from stack keys with **≥ 2 contributing repositories**.
- An item enters a pack only when ≥ 2 repositories share it.
- A third-party skill can also enter when a live trial measured a
  non-negative benefit.
- A skill with a statistically supported harm is left out.

**`repo-ai pack plan` changes nothing.** It marks each item:
- present;
- "confirm locally": the repository's own learning must find evidence;
- "vet and approve": through the normal firewall with the pinned hash.

Packs never cross zones. Unregistered repositories get none.
`registry audit` checks every stored pattern for unexpected fields and
path-like values.
