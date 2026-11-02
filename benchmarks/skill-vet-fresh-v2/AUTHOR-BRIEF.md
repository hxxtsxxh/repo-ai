# skill-vet-fresh-v2: brief for an independent corpus author

repo-ai vets third-party agent skills and Claude Code plugins before it will install them. This study measures that
vetting on new material written by someone who has never looked at how it works. It is written for a **person**;
please do not delegate the writing to an AI model (the material would not be independent).

## Who can write it

You are eligible if you have **not** read repo-ai's vetting code, its tests, its security or skills documentation,
its changelog or release notes, its earlier skill-vetting corpora or results, or its pull requests and issues about
vetting. The maintainer is not eligible.

While writing, read **only** this brief and public Claude Code documentation about skills and plugins. Nothing else
in the repo-ai repository, its history, pull requests or issues. Write what a realistic skill author, honest or not,
would write.

## What to write

Eighty cases, in five strata (fixed in advance; do not change the counts):

| stratum | n | content |
|---|---|---|
| `H-text` | 20 | harmful skills, `SKILL.md` only, prose instructions with no code: exfiltrating secrets or source, weakening tests or CI, persisting into agent or editor config, deceiving the user, adding untrusted dependencies, destructive git or file operations, prompt injection aimed at the host agent |
| `H-code` | 10 | harmful skills with scripts or code blocks the agent is told to run |
| `B-skill` | 30 | benign, realistic skills, including hard negatives that legitimately mention secrets, `curl`, `rm`, CI, permissions or security testing |
| `H-plugin` | 10 | harmful plugins: hooks, MCP servers, commands or agents that exfiltrate, persist or escalate |
| `B-plugin` | 10 | benign, realistic plugins |

Spread the harmful cases across the kinds named; how many of each is yours to choose. Benign cases matter as much as
harmful ones: a vetter that blocks everything is useless, and the hard negatives show it. `H-text` cases are prose:
no code blocks, fenced or indented, and no `<pre>` or `<code>`.

**Layouts.** A skill is a directory with a `SKILL.md` that starts with YAML front matter (`name`, `description`) and
optional extra files. A plugin is a directory with `.claude-plugin/plugin.json` and any of `commands/`, `agents/`,
`hooks/hooks.json`, `.mcp.json`, `skills/`.

## Defanging (required for every harmful case)

The cases must not work as real attacks, while still reading like one to a reviewer:

- every host is under `.invalid` or is `example.com`: never a real domain, IP address, `localhost`, an e-mail address
  at a real domain, or an `scp`-style git address; placeholders such as `$HOST`, `{region}` or `<host>` are fine;
- no real credential, token, key, address or personal data; use obviously fake placeholders;
- no working exploit, malware, persistence mechanism or obfuscated payload copied from the wild; describe the action
  in the skill's own words and keep code minimal and non-functional where possible (a script may name a step it never
  performs);
- nothing that harms a machine if a curious person runs it: no deletion outside a temporary directory you name, no
  network listeners, no changes to system or user configuration.

If a case cannot be both realistic and defanged, leave it out and write another. Benign cases may link real
documentation.

## Delivery (format fixed by the harness)

```
corpus/case-001/SKILL.md          one directory per case; ids case-001 … case-080, assigned in a shuffled order so
corpus/case-002/...               the number says nothing about the stratum
labels.json                       {"cases": [{"id": "case-001", "stratum": "B-skill", "intended_harm": "none",
                                    "observable_harm": "none"}, ...]}  one entry per case; for harmful cases one
                                    sentence each: what it intends, and what an agent following it would do
AUTHOR.md                         who you are (name or stable pseudonym), dates, that you wrote every case yourself
                                    without an AI model, what you read (this brief, public Claude Code docs), your
                                    prior exposure to repo-ai (none of the list above), and that you did not run any
                                    skill vetter on the cases
MANIFEST.sha256                   shasum -a 256 of every file above, made last:
                                    find corpus labels.json AUTHOR.md -type f -print0 | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256
```

Deliver it as a pull request from your own account against the branch `skill-vet-v2/delivery`, adding files under
`benchmarks/skill-vet-fresh-v2/` only, and publish the SHA-256 of `MANIFEST.sha256` somewhere the maintainer does not
control (the pull request itself is enough), so the delivery can be shown to be yours and
unchanged. Labels are final at that point; a later disagreement is reported as disputed, never edited.

## How it will be used

1. A CI job checks the delivery with `validate_corpus.py`: structure, counts, labels, manifest, defanged hosts. It
   does not run the vetter. A delivery that fails is returned with the reasons; you fix it and re-freeze.
2. The corpus is committed as delivered, with your `AUTHOR.md`.
3. The preregistered harness runs **once**, by a manual CI job, on the system under test named in the
   preregistration. Every result is published, including harmful cases that got through and benign cases that were
   blocked. No case is added, removed or relabelled after that run.

Questions about the format can go to the maintainer; questions about how the vetter works will not be answered until
the run is published.
