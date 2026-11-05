---
title: Skills
description: See every skill, hook and MCP server Claude Code loads in a repository, and vet a third-party skill before anyone installs it.
---

Two skill commands are read-only and are **stable candidates**. Everything else in the skill and capability
lifecycle is experimental and says so in its output.

## `skills inventory`: what is already loaded

```sh
repo-ai skills inventory            # summary and issues
repo-ai skills inventory --all      # every item
repo-ai skills inventory --check    # exit 1 on a high-severity issue (for CI or a pre-session check)
repo-ai skills inventory --json
```

Offline and read-only: nothing is run, enabled or changed. It reads personal and project skills, commands and agents,
the `npx skills` store, enabled plugins (their skills, hooks, `.mcp.json`, `bin/` and settings), hooks in settings and
front matter, and MCP servers. Per item it reports scope and origin, whether Claude Code loads it, whether the model can
invoke it on its own, its description tokens, and a firewall verdict on a quarantined copy.

Issues include blocked or review-level firewall findings, an always-loaded description budget above about 2,000
tokens, name collisions across scopes, hooks that use the network, unpinned MCP launches, and a whole plugin sitting in
a skills directory. MCP environment values and secrets are never printed.

**Limits:** project skills are read from the repository root only (nested `.claude/skills` are not scanned),
enterprise-managed skills are not read, and the firewall is pattern-based with known false positives.

## `skills vet`: before you install

:::caution[Network, opt-in]
Vetting a GitHub URL needs `--online`. A local directory needs no network.
:::

```sh
repo-ai skills vet https://github.com/OWNER/REPO --online
repo-ai skills vet ./a-skill-someone-sent-you
repo-ai skills install NAME --approve CONTENT_HASH --online   # only after reading the findings
```

`vet` resolves the source to a pinned commit, copies each skill into quarantine, and inspects it as text. It installs
and runs nothing. A skipped skill, a request-cap failure, a truncated tree, a renamed repository or an off-branch commit
makes the result **incomplete** (exit 3), and `install` then refuses. Licences are parsed as whole SPDX expressions;
restricted or unrecognised licences block install. Installation always needs the exact content hash you reviewed.

On 12 held-out repositories (397 skills), 16 were blocked: 5 false positives and 4 real dangers. That is a small
sample. "Eligible" means no known problem was found, not that a skill is safe.

:::note[Experimental: plugin inspection]
`vet` and `inventory` also inspect plugin components. That inspection's fresh, preregistered validation **failed**,
so a plugin is never reported as eligible: `review` at best.
:::

## Experimental parts

| Feature | Status |
|---|---|
| `skills discover --online` (Skill Radar), third-party install and trials | experimental; no third-party skill has been shown to help in a controlled trial |
| `skills list`, `test`, `promote`, `canary`, `draft` and the rest of the lifecycle | experimental |
| `capabilities list` / `show` (a curated registry of 15 records with separate lifecycle states) | stable candidate; `validated` means the output matched its schema, never that it helped |
| `capabilities recommend`, `candidates`, `select` | experimental; a preregistered evaluation failed (top-3 recall 0.385 against a gate of 0.80). Pass constraints with `--deny`, which is always enforced |
| `init --smart` (learned rules, generated skills) | experimental, opt-in; no benefit shown |
| `init --feature-set full` (subagents, skeptic reviewer) | opt-in; no benefit shown, about 10% higher cost in one study |
| `prove` (ProofLab) | not qualified; experimental, with known open false-proof classes. Not a supported capability |

`skills draft` and skill trials can call Claude Code and are billable; they need an explicit `--max-cost-usd`.

See [Status matrix](/repo-ai/docs/status/) for the evidence behind each row.
