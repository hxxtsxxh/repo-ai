---
title: Handoff
description: Export an integrity-checked capsule from an unfinished mission and continue it with another provider, re-verified from the same frozen base.
---

:::caution[Experimental · continuation needs a provider login and explicit consent]
Exporting and verifying a capsule is local. Continuing it with `--from-handoff` and a live agent sends task text and
opened files to that provider.
:::

When a mission ends without a PASS but made some verified progress, you can hand it to another provider (or another
run of the same one) instead of starting over.

```sh
repo-ai handoff MISSION_ID --to bob --json > capsule.json   # export
repo-ai handoff --verify capsule.json                        # check it against the current repository state
repo-ai do --from-handoff capsule.json --agent bob --allow-live-provider \
  --allow-write charge.py --max-cost-usd 0.25 --run          # continue
```

`--to` accepts `none`, `replay`, `codex`, `claude`, `bob`, `agy`, `opencode` or `opencode-acp`. `--format text|json` controls the
export format.

## What a capsule is, and is not

New exports use `repo-ai.handoff/2`. A capsule carries task text, file names, redacted facts, hashes and evidence
links. It carries **no source patch body and no provider session**. Treat it as private anyway.

:::note[Integrity, not authentication]
The capsule's SHA-256 checksum is unkeyed. Verification also requires the matching export receipt in the original
local mission store, the same repository identity and privacy zone, an unchanged mission snapshot and fresh source,
tool and policy evidence. Editing a capsule and recomputing its checksum does not create a matching receipt, but
someone who controls both the capsule and your local store can forge one. Capsules are not portable to other machines
or empty stores.
:::

## How continuation works

- A continuation starts a **fresh isolated candidate** from the same frozen source.
- If the original mission has **validated partial progress** (a stored diff, comparable baseline and candidate
  observations, at least one baseline-failing test now passing, and no regressions), that diff is re-derived from the
  local store, never trusted from the capsule, and applied to the fresh checkout as an untrusted seed together with
  the still-failing test IDs. The final tree is re-verified from the frozen base.
- A stored diff **without** validated progress is refused, not silently dropped. The capsule's `diff_sha256` must
  match the stored diff. A mission with no diff continues from the plain base.
- The write scope is inherited; a capsule can never widen it. You can widen it yourself by passing
  `--allow-write PATH` on the continuation command: those paths go through the same checks as any plan (frozen
  tests and configuration stay refused) and are recorded in the child as `write_paths_added_by_user`. Elapsed time is debited, and observed prior live spend is subtracted from the budget.
  Unknown prior cost blocks a continuation that has a USD ceiling.
- Each source mission permits **one** continuation attempt; more than two continuation steps, completed or unsafe
  missions and exhausted budgets refuse.

## What has been demonstrated live

All four are small, constructed scenarios, n = 1 each:

| Route | Result |
|---|---|
| Bob → Bob | the second session finished the remaining work; PASS, then apply and undo checked. A second Bob session is not an independent provider |
| agy → Codex | validated partial state crossed providers; the Codex child reached PASS and was independently re-verified. Codex rewrote the file itself, so "kept the partial work" is not claimed |
| Codex → agy | the partial diff transferred and was re-verified; agy kept it unchanged and the mission correctly stayed incomplete, because the write scope never covered the remaining failures |
| Codex → agy, 2026-10-29 | Codex, scoped to one file, fixed 1 of 3 failing tests; agy continued with a second file added by the user (`--allow-write fmt.py`), kept Codex's diff byte-identical and reached PASS (`LIVE_CANDIDATE_VERIFIED`); an author-written hidden oracle passed 714/714; apply and undo checked. The first attempt found that `--allow-write` was silently ignored on continuations, now fixed. Evidence: `docs/launch/evidence/LIVE-JOURNEYS-2026-10-29.md` in the source tree. |

None of these shows that a handoff is faster or cheaper than restarting. Codex and agy costs were `UNKNOWN`.
