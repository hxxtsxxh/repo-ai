# skill-vet-fresh-v2: brief for an independent corpus author

repo-ai vets third-party agent skills and plugins before it will install them. Its first fresh test (v1) failed: some
harmful skills written only as prose would have been installed without asking. A fix exists, but it was written with
that corpus in view, so it has to be confirmed on new material written by someone else. That is what this brief asks
for. It is written for a **person**; please do not delegate the writing to an AI model (it would not be independent,
and model-written cases have been refused by safety systems twice already on this task).

You are not asked to find out how repo-ai detects anything. Please **do not read** `src/repo_ai/`, `tests/`,
`docs/SKILL_NETWORK.md`, `docs/engineering/SKILLS_NETWORK.md`, anything under `benchmarks/skill-vet-fresh-v1/`
(corpus, labels or results), or repo-ai's release notes about vetting. Write what a realistic skill author, honest or
not, would write.

## What to write

Seventy cases, in the strata and counts fixed by the preregistration
([PREREGISTRATION.md](PREREGISTRATION.md), which takes them from
[v1's corpus section](../skill-vet-fresh-v1/PREREGISTRATION.md#corpus-written-after-this-file-is-committed)):

| stratum | n | in one line |
|---|---|---|
| `H-text` | 20 | harmful skills, `SKILL.md` only, prose instructions, no code |
| `H-code` | 10 | harmful skills with scripts or code blocks the agent is told to run |
| `B-skill` | 30 | benign, realistic skills, including hard negatives that legitimately talk about secrets, `curl`, `rm`, CI, permissions or security testing |
| `H-plugin` | 10 | harmful Claude Code plugins (hooks, MCP servers, commands or agents) |
| `B-plugin` | 10 | benign, realistic plugins |

The kinds of harm are those named in v1's table. Spread your cases across them; the counts per kind are yours to choose.
Benign cases matter as much as harmful ones: a vetter that blocks everything is useless, and hard negatives are the
cases that show it.

**Layouts.** A skill is a directory with a `SKILL.md` that starts with YAML front matter (`name`, `description`) and
optional extra files. A plugin is a directory with `.claude-plugin/plugin.json` and any of `commands/`, `agents/`,
`hooks/hooks.json`, `.mcp.json`, `skills/`. Public Claude Code documentation describes both.

## Defanging (required for every harmful case)

The cases must not work as real attacks, while still reading like one to a reviewer:

- every host is under `.invalid` or is `example.com` / `example.org` (never a real domain or IP address, never
  `localhost` ports that something might listen on);
- no real credential, token, key, address or personal data; use obviously fake placeholders;
- no working exploit, malware, persistence mechanism or obfuscated payload copied from the wild; describe the action
  in the skill's own words and keep code minimal and non-functional where possible (a script may name a step it never
  performs);
- nothing that harms a machine if a curious person runs it: no deletion outside a temporary directory you name, no
  network listeners, no changes to system or user configuration.

If a case cannot be both realistic and defanged, leave it out and write another.

## Labels, provenance and blinding

- **One label file per case, outside the case directory**: `labels/<case-id>.json` with
  `{"case": "<case-id>", "stratum": "...", "intended_harm": "<one sentence, or 'none'>", "observable_harm": "<what an
  agent following it would do, or 'none'>"}`. Case ids are short and neutral (`case-017`), never descriptive, so the
  directory name does not label the case.
- **Provenance file** `AUTHOR.md`: who wrote the corpus (a name or a stable pseudonym), when, that you wrote it
  yourself without an AI model, which repo-ai files you read (expected: this brief, the two preregistrations, public
  Claude Code docs), and that you did not run repo-ai's vetter on your cases.
- **Freeze**: when you are done, compute `shasum -a 256` over every file (`find corpus labels -type f -print0 | sort -z
  | xargs -0 shasum -a 256 > MANIFEST.sha256`) and send the corpus, labels, `AUTHOR.md` and `MANIFEST.sha256`
  together. Labels are final at that point; a later disagreement is reported as disputed, never edited.

## How it will be used

1. The maintainer checks the delivery with [`validate_corpus.py`](validate_corpus.py) on CI (structure, counts,
   labels, manifest, defanged hosts). It does not run the vetter and does not open the cases' prose beyond that.
   A delivery that fails is returned to you with the reasons; you fix it and re-freeze.
2. The corpus is committed as delivered, with your `AUTHOR.md`.
3. The preregistered harness runs **once**, on CI only (never on a developer's machine), against the commit that
   holds the fix. Every result is published, including harmful cases that got through and benign cases that were
   blocked. No case is added, removed or relabelled after that run.

Thank you. Questions about the format can go to the maintainer; questions about how the vetter works will not be
answered until the run is published.
