# Publication audit (summary)

Date: 2026-10-29. Read-only audit of everything a visibility flip of the private repository
would expose: all 166 origin refs (82 branches, 17 tags, 66 `refs/pull/*`), 5,566 reachable
blobs including extracted archives, issues, PRs, comments, releases, Actions metadata, and
the wheel/sdist built from `main` `2d64217`. The full report with commit IDs stays local
(it names personal details); this summary is safe to publish.

**Verdict: PUBLISHABLE_AFTER_FIXES for a curated export; a flip of the existing repository
needs an owner decision on two findings that only a history rewrite could remove.**

| Finding | Severity | Fixable by a new commit? |
|---|---|---|
| No real credential anywhere (scanner hits are planted canaries, test fixtures, vendor example keys, upstream test keys) | – | n/a |
| No employer-internal material (only public IBM Bob product docs/CLI behaviour) | – | n/a |
| F01: 8 commits carry a corporate work address as author/committer (4 reachable from `main` and the release tags) | high | **no** (history; `refs/pull/*` cannot be rewritten by the owner) |
| F02: the sealed-v2 confirmatory set, its authoring notes (upstream fixes) and held-out labels are in history; the project's own docs say they stay private. Publishing ends their use as holdouts | high | **no** |
| F03/F04: mutated upstream sources in `benchmarks/verify-eval/results` and sealed-v2 bases without a complete notices file (recorded licences are permissive; ~11 unconfirmed) | medium/low | yes (notices) — or excluded |
| F05–F08: local paths, spend notes, provider account states, personal research notes | low | partly (history keeps them) |
| F09–F11: fake canary tokens and upstream test keys will trigger secret-scanning alerts | low/info | accept |

## Options for the owner

1. **Publish a curated export (recommended).** `python scripts/public_export.py --out DIR` builds a
   fresh repository with one commit (noreply author) of the current tree minus the sealed set,
   authoring notes, verify-eval results, research ledgers, the spend ledger and per-run
   records, and audits it for corporate addresses, local paths and private-only text. It
   resolves F01–F08 without touching the private history. Pushing it to a public repository
   (for example after renaming the private one) is a separate, explicit step.
2. **Flip the existing repository to public**, accepting F01 and F02 (and retiring the sealed
   sets as holdouts).
3. **Stay private**: then G15/G16 can still ship (Pages from a private repo on the Pro plan; a
   PyPI release from the private repo's workflow), but G18 cannot pass.
