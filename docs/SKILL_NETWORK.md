# Skill Intelligence Network

repo-ai can find third-party agent skills that fill this repository's real
capability gaps. It vets them in quarantine and installs one only when you
approve a specific version. It can then measure whether the skill helps.

**Principles:**
- Nothing here runs during normal `init`/`update`, and nothing reaches the
  network unless you pass `--online`. That covers `discover`, installing a
  remote skill, and `updates`; since 0.8 each refuses without the flag.
- **Experimental.** No third-party skill has been shown to help in a
  controlled trial, and screening is static (pattern-based), not a safety
  guarantee.
- Everything downloaded is data, never instructions.
- "No additional skills are necessary" is a successful outcome.

```
profile → radar (search) → quarantine → firewall → recommend → approve+install → trial → canary/promote
```

## 1. Capability profile (`repo-ai capabilities`)

The profiler derives gaps from evidence repo-ai already has: the index,
facts and recorded episodes. Each gap carries its evidence and a strength.

| Gap | Evidence |
|---|---|
| accessibility | UI component files and no accessibility test dependency |
| migrations | migration directories or tooling |
| api-contract | many HTTP routes, no OpenAPI spec |
| test-coverage | most source files have no linked test |
| ci-debugging | CI present and repeated failing known commands |
| security-review | authentication code present |

A gap that an installed skill or a built-in command already covers keeps
40 % of its strength. Coverage is judged from **skill descriptions** (what
Claude matches on), never from bodies that merely mention a word.
`repo-ai capabilities` prints the coverage map:
- gaps, with what covers them;
- each third-party skill's measured benefit;
- possibly redundant skill pairs.

## 2. Skill Radar (`repo-ai skills discover --online`)

Providers: Anthropic's official skills, Vercel's agent skills, GitHub
search, configured plugin marketplaces and trusted publishers
(`skill_marketplaces`, `skill_publishers`), and skills.sh.
- skills.sh's API needs a Vercel OIDC token (`SKILLS_SH_TOKEN`). Without
  one, that provider is skipped and the skip is reported.

**Privacy:**
- Search queries are built only from a fixed technology vocabulary: known
  languages, frameworks and capability words. Repository names, paths,
  identifiers and code never appear in a query.
  - `tests/test_skill_network.py::test_19` checks this with secrets and
    unusual names planted in the repository.
- Online discovery is a zone policy (`discovery`): `personal` allows it,
  `work` denies it, and unregistered repositories allow it only when you
  pass `--online` explicitly.

**Network hygiene:**
- Only `api.github.com` and `skills.sh` are contacted for metadata.
- Archives come only from `codeload.github.com`, pinned to a commit.
- Every redirect is checked against that allowlist.
- Responses are size-capped.
- A per-run request cap applies (`--max-requests`).
- The GitHub token (from `gh auth token` or `GITHUB_TOKEN`) is sent only to
  `api.github.com`.
- Results are cached by commit.

## 3. Quarantine and firewall

Each candidate is downloaded by **immutable commit** into
`~/.local/share/repo-ai/quarantine/`:
- outside every repository and outside every directory Claude Code
  discovers;
- files are written `0600`, exclusively, with no symlink following;
- every blob is verified against its git SHA-1;
- symlinks, submodules, oversized files and unsafe paths are recorded as
  findings and not stored.

**Nothing is executed to inspect a skill.** The inspection layers are:

1. **Specification** (agentskills.io): name rules, description length,
   front matter, SKILL.md size.
2. **Instructions:** prompt injection, authority claims, hidden Unicode,
   hidden HTML comments, requests to change permissions, settings or memory.
3. **Code:** pipe-to-shell and remote eval, exfiltration (environment or
   file contents to the network, netcat), credential files and keychain
   CLIs, destructive commands, persistence, encoded or hex blobs that are
   decoded and run, executable binaries.
4. **Dependencies and network:** URL and git dependencies, typosquats
   (edit distance 1, including transpositions), npm lifecycle scripts,
   `setup.py`, cloud-metadata and private IPs, external hosts.
5. **Provenance:** publisher impersonation, forks, archived repositories,
   adoption.
6. **Licence:** a skill with no usable licence is not installable.
   Copyleft is flagged.
7. **Compatibility:** required services and network access.
8. **Conflicts:** name collisions, trigger overlap with existing skills,
   over-broad triggers.

**How findings are classified:**
- Each finding is `confirmed`, `suspected` or `unknown`, with `file:line`
  evidence and secrets redacted.
- Matches are context-aware. A dangerous command named in a "never do
  this" sentence is downgraded. A match inside a comment is skipped. Prose
  is treated differently from code.

**Verdicts:**
- `blocked`: any critical finding. Never installable, whatever the
  relevance.
- `review`: any high finding, or incomplete evidence. Installable only
  after you read the findings and pass `--accept-review`.
- `eligible`: no known problem. That is not proof of safety.

Audit with `repo-ai skills audit <id>` or `repo-ai skills audit --all`.

## 4. Recommendations (`repo-ai skills recommend | explain | compare`)

Two separate questions:
- **Allowed?** The firewall verdict and the licence. A gate that
  relevance can never override.
- **Worth it?** A transparent score:
  - the evidence-backed gaps the skill addresses, weighted by strength;
  - for a local skill (`discover --from-path`) only: whether its
    description names one of this repository's own Python packages
    (`ledger_core`, `ledger-core` and `ledger core` all count; common names
    such as `app`, `data` or `models` never do). Such a skill states project
    knowledge that no gap detector can see. A network skill that names the
    package gets no credit for it, because naming a package is easy to fake.
    "Local" means only that you gave the path, not that the skill was written
    here, so this is advice: autopilot never auto-installs a skill on this
    ground, only when you name it;
  - minus redundancy with existing skills;
  - documentation quality;
  - provenance (stars count only weakly);
  - minus context-token cost;
  - plus or minus measured trial evidence.

At most one skill is recommended per gap. A skill written for this
repository is judged on its own, even when a stronger candidate takes a gap
it also matched.

## 5. Portfolio (`.repo-ai/skills.lock.json`)

```sh
repo-ai skills install <name> --approve <hash≥12> [--online]   # --online for a remote skill
repo-ai skills portfolio | health | updates --online
repo-ai skills disable <name> | disable --third-party --all   # kill switch
repo-ai skills enable <name> | rollback <name>
```

**At install time:**
- The candidate is re-fetched, its hash compared with the approval, and
  re-inspected.
- Scripts need `--allow-scripts`.
- SKILL.md front matter is reduced to an allowlist: `name`, `description`,
  `license`, `compatibility`, `metadata`, `argument-hint` and
  `disable-model-invocation`. Every other key is removed, in any spelling or
  quoting, including `allowed-tools`, `hooks` and model or agent overrides.
  A skill must never widen Claude's permissions.
- A committed lockfile is untrusted. Entries with invalid names, paths or
  hashes are ignored (and preserved, never deleted). Content restored from
  the object store is re-hashed first.
- Files are written through repo-ai's ownership-checked plan, **byte for
  byte**. The one exception is SKILL.md front-matter sanitization, which is
  recorded in the lockfile. A skill containing non-UTF-8 (binary) files is
  refused rather than written through a lossy text decode.
- Trial evidence in the committed lockfile is a claim, not evidence.
  - Promotion and the registry count it only when this machine holds the
    experiment record it cites.
  - A pilot (fewer than 10 pairs) never promotes.

**After install:**
- The lockfile pins source, commit, content hash, licence, verdict and
  approval time.
- Uninstalling repo-ai removes third-party skills too, but only files you
  have not modified.

## 6. Trials, tournaments and canary stages

```sh
repo-ai skills benchmark <name> --max-cost-usd 5 --dry-run   # plan, spends nothing
repo-ai skills benchmark <name> --max-cost-usd 5             # full without it vs with it
repo-ai skills tournament <a> <b> [c] --max-cost-usd 10      # one arm per candidate, same control
repo-ai skills promote <name>                                # canary -> promoted
```

**How trials run:**
- Trials use the Coding Performance Lab (docs/CODING_LAB.md) on the exact
  pinned content, in sandboxed, budget-capped, paired runs.
- In a tournament each arm receives only its own candidate.
- A winner is declared only on statistically supported evidence.
- The invocation rate shows whether Claude used the skill at all.

**Stages:**
- `canary` at install.
- `promoted` only after a live trial (pilot or full) that was not worse.
- `harmful` when a trial shows a statistically supported harm. Health
  then says to disable it.

## 7. What is already installed (`repo-ai skills inventory`)

Skills now arrive from many installers:
- `npx skills add <url>` copies them into `~/.agents/skills` and links them
  into `~/.claude/skills`;
- `/plugin install` caches them under `~/.claude/plugins`;
- claude.ai syncs some;
- some are committed to the project;
- sometimes the agent is simply told to "install this skill from this repo".

The firewall above vets what *repo-ai* installs. `inventory` looks at
everything Claude Code can load in this repository, whoever installed it.
It is offline and read-only: nothing is run, enabled or changed.

```sh
repo-ai skills inventory            # summary + issues
repo-ai skills inventory --all      # every item
repo-ai skills inventory --json     # schema repo-ai.skills-inventory/1
repo-ai skills inventory --check    # exit 1 on a high-severity issue (CI, pre-session)
repo-ai skills inventory --no-firewall   # ~0.1 s instead of ~2.6 s
```

**What it reads:**
- personal skills, commands and agents (`~/.claude/…`);
- claude.ai-synced skills;
- project `.claude/…`;
- the `npx skills` store and its locks (`~/.agents/.skill-lock.json`,
  `skills-lock.json`);
- for enabled plugins (`installed_plugins.json` and `enabledPlugins`, later
  settings scopes winning): their skills, commands, agents,
  `hooks/hooks.json`, `.mcp.json`, `bin/` and `settings.json`. The default files are always
  read, and any paths the plugin manifest names are read as well. A manifest path that leaves the
  plugin is refused and reported (`plugin-path-escape`);
- hooks declared in the front matter of skills, agents and commands;
- hooks configured in settings;
- MCP servers in `.mcp.json` and `~/.claude.json`.

**What it reports per item:**
- scope and origin;
- whether Claude Code loads it, and whether the model can invoke it on its own;
- its description tokens;
- the firewall verdict on a temporary quarantined copy, for skills and also for agents and
  commands.

Text output shows every repository-controlled string inertly: control characters, terminal
escapes, bidi and zero-width characters, and newlines are printed as visible escapes. A hook is
labelled `(repo-ai)` only when its path and script bytes are exactly what repo-ai writes.

Licence findings are left out of this verdict: a licence governs
redistribution, not whether an installed skill is safe.

**Issues:**

| Rule | Severity | Meaning |
|---|---|---|
| `firewall-blocked` / `firewall-review` | high / medium | A loaded skill has a critical, or high/incomplete, firewall finding. |
| `always-loaded-budget` | medium | The descriptions of model-invocable skills exceed ~2,000 tokens. Claude Code lists descriptions within 1% of the context window (about 2,000 tokens at 200k) and drops the least-used past that, so some skills are never found. |
| `name-collision` | medium | The same bare name exists in several scopes; personal wins over project. |
| `trigger-overlap` | low | Two model-invocable descriptions overlap (≥ 0.5). |
| `unpinned-source` | low | An `npx skills` install records no commit. |
| `hook-network` | high | A hook command uses the network. |
| `hook-context` / `hook-gating` | info | A hook runs on every session/prompt, or can block the agent. |
| `mcp-unpinned` | medium | `npx`/`uvx` launches a package without a version, or with `@latest`. |
| `mcp-remote` | info | A remote MCP server: data leaves the machine. |
| `plugin-path` / `plugin-settings` | medium | An enabled plugin adds executables to PATH, or ships settings. |
| `plugin-in-skills-dir` | high | A whole plugin sits in a skills directory, loaded without the plugin trust prompt. |
| `claude-code-patched` | high | tweakcc has patched the Claude Code executable. |

MCP environment values, headers and secrets in arguments are never printed;
only variable names are.

**Limits:**
- Project skills are read from the repository root only; nested
  `.claude/skills` and `--add-dir` are not scanned.
- Enterprise-managed skills are not read.
- The firewall is pattern-based, with known false positives (below).

## 8. Vet a skill URL before installing it (`repo-ai skills vet`)

When a README, a colleague or a video says "install this skill from
github.com/…", vet it first:

```sh
repo-ai skills vet https://github.com/<owner>/<repo>[/tree/<ref>/<path>] --online
repo-ai skills install <name> --approve <hash> --online   # after reading the findings
```

`vet` takes these steps:
1. Resolves the ref to a 40-hex commit.
2. Counts every `SKILL.md` under the path, then vets up to `--vet-limit` of them (default 200).
   It reports "vetted N of M". A skipped skill, a request-cap failure, a truncated tree, a
   repository whose `full_name` differs from the URL (a rename or transfer), or a pinned SHA that
   is not on the default branch makes the result **incomplete**: exit 3, and `install` refuses.
3. Quarantines each skill with the same limits and git blob-SHA integrity
   check as discovery.
4. Runs the firewall.
5. Records the candidates, so that `install` re-fetches the same commit,
   re-inspects it and refuses any content change.

It then inspects what the repository would *run* as a plugin (section 9).
repo-ai installs only skill directories, and installing the repository as a
plugin would activate those other parts too.

`repo-ai skills vet <local-dir>` vets a checkout someone sent you. It needs no
network and records nothing; integrity is `local-unverified` because there is
no pinned commit.

An install hint is printed only for a plain skill name (`[a-z0-9]+(-[a-z0-9]+)*`): a name that
could carry shell syntax gets no hint. Licences are matched as whole SPDX expressions:
- restricted terms (non-commercial, source-available, Commons Clause, `LicenseRef-*`) give
  `license-restricted`;
- anything unrecognised gives `license-unrecognized`.

Both block install, like `no-usable-license`.

Only `https://github.com/<owner>/<repo>` sources are accepted, and nothing is
fetched for a refused URL. Network use needs `--online` and follows the zone
policy (`discovery=deny` refuses it).

**Measured precision.** In
`docs/research/vet-eval-2026-10.md` (private development history), vetting real
skill repositories found real `curl … | bash` install steps. It also found
false positives, which led to two rule fixes. A third class (negated mentions
of credential paths, such as "don't read `.env`") stays blocking by design.

## 9. Plugin components (`pluginvet`)

A plugin's power is outside its skills. Hooks, hooks modules, MCP and LSP
servers, monitors, `bin/`, status lines and helpers all run unsandboxed with
your permissions once the plugin is enabled. For each executable component,
`vet` (and `inventory`, for enabled installed plugins) does the following:

1. Resolves the command: exec or shell form, `${CLAUDE_PLUGIN_ROOT}` with
   defaults, and nested `$(…)`.
2. Maps the interpreter (`node`, `python`, `bash`, a `.cmd` launcher, a bare
   path, `node -e` bootstraps) to a script **inside the repository**.
3. Reads that script and up to two hops of local `require`, `import`,
   `source` and `__dirname` references. Symlinks are followed only while
   they stay in the repository.
4. Applies the firewall rules plus plugin rules:
   - model re-runs (`claude -p`) on the transcript;
   - permission auto-approval;
   - `CLAUDE_ENV_FILE` writes;
   - network calls in source;
   - dynamic code;
   - unpinned `npx`/`uvx`/`docker` runners;
   - hardcoded credentials in MCP headers or env;
   - `defaultMode: bypassPermissions` and broad `allow` rules;
   - hooks modules;
   - marketplace `command` sources and unpinned refs;
   - trust claims;
   - look-alike characters.
5. Marks as **dynamic-unknown** what it cannot resolve: package runners and
   project runners (`npm run`, `make`, `pip install` …), computed paths,
   binaries, minified bundles, references beyond two hops, oversized files,
   and programs the repository does not ship. Common formatters and linters
   (prettier, eslint, ruff …) and language servers are listed as installed
   tools instead. Anything unknown forces *review*.

**Verdicts for plugins: `blocked` or `review`, never `eligible`.**
- `blocked` means a critical finding.
- Everything else is `review`: experimental static inspection does not approve a plugin, even when
  it finds nothing.

The result keeps these dimensions apart:
- skill content;
- plugin configuration;
- executable source (inspected and unresolved counts);
- dynamic unknowns;
- **evidence**, counted by kind:
  - `observed`: a component would do this;
  - `risky`: a lesser risk in a component;
  - `quoted`: text such as prompts or docs that mentions or instructs it;
  - `unresolved`: what runs could not be determined;
  - `unsupported`: binaries, minified bundles, truncated listings, absolute or Windows paths.
- source integrity (`verified-blob-sha` or `local-unverified`);
- licence;
- authorization, which is always `not-authorized`: repo-ai never installs or
  enables a plugin.

A claim of trust (`"trusted": true`, "pre-approved by Anthropic") is a
finding and never lifts a verdict.

Evidence: `docs/research/plugin-vet-eval-2026-10.md` (private development history)
covers a 41-case adversarial corpus, 10 development repositories and 6 fresh
held-out repositories.

**Status: experimental.** A preregistered fresh validation
(`docs/research/plugin-vet-fresh-2026-10/RESULTS.md`, private development history;
44 cases, analyser frozen) **failed** on false alarms and executable coverage:
- 12 of 42 benign cases were blocked, mostly quoted prohibitions and detection regexes;
- executable-resolution coverage was 0.25.

It never reported a critical or unresolvable case as eligible. Attack detection was not freshly
validated: the synthetic attacks could not be produced.

**Containment since then:**
- **No safe verdict.** A plugin is never reported `eligible`.
- **One narrow fix.** Markdown emphasis no longer defeats the existing negation check: `**DO NOT**
  use …` reads as a prohibition. The checks were not loosened in any other way, including those that
  catch real permission bypasses.
- **Fresh evaluation unchanged.** The fresh results above are unchanged by this containment.

Treat `blocked` as "look closely" and `review` as "read it yourself before enabling".

## 10. Autonomy policy and autopilot (experimental)

```sh
repo-ai skills policy                      # show the level (default PROPOSE) and what each level allows
repo-ai skills policy set SAFE_AUTO        # run it yourself: refused with agent/CI markers or no TTY
repo-ai skills policy revoke               # back to PROPOSE; removes what the policy installed
repo-ai skills autopilot [names] [--dry-run]
repo-ai skills install <name> --approve <hash> --host claude-code,codex --dry-run   # diff + conflicts
```

**Levels:** `OFFLINE`, `DISCOVER_ONLY`, `PROPOSE` (default), `SAFE_AUTO`, `TRIAL`, `MANUAL_ONLY`.
- The level is stored outside the repository, so a clone cannot grant itself autonomy.
- Refusing to raise the level from an agent shell is defence in depth, not a boundary: an agent can
  unset the markers and fake a terminal. Your agent's permission prompt for the command is the boundary.
- **What `SAFE_AUTO` may install:** only an **inert** skill, under every one of these conditions:
  - its directory holds a SKILL.md and plain licence files, and nothing else;
  - it is pinned to the hash that was vetted and re-checked at install;
  - it declares no permissions, hooks, URLs, network commands, accounts or hidden characters;
  - its text has no non-ASCII letters (look-alike letters defeat text checks) and no instruction-risk prose
    (below), whether phrased as a request or as a prohibition;
  - the firewall found nothing that matters.
  
  It installs into the Claude Code project skills directory only, and only a
  skill that fills an evidence-backed gap or that you name: a recommendation
  that rests on naming this repository's package is never acted on alone.
- **At every level:** scripts, hooks, MCP servers, plugins, binaries, provider adapters, static tools,
  external accounts, permission changes and network execution need your approval.
- **`eligible` is not inert:** a firewall verdict of `eligible` never qualifies a skill on its own.
- **Measured, and failed:** an unseen 80-case corpus (`benchmarks/skill-vet-fresh-v1`) found that `SAFE_AUTO`
  would have installed 8 of 30 harmful skills. All were prose-only: instructions that take over the agent, hide
  results, bypass approvals, weaken checks, write into agent configuration, delete data or take over commit
  identity. Such prose is now a `high` firewall finding (`instruction-risk`), so `SAFE_AUTO` asks. The fix is not
  yet confirmed on a second unseen corpus. Phrase-based checks can be paraphrased around, so keep `SAFE_AUTO`
  for skills whose source you trust.

**Installs:**
- Every install carries a repo-ai ownership marker and never adds permissions.
- A file repo-ai does not own refuses the whole install. Nothing is overwritten.
- Uninstall, `disable` and `rollback` put back exactly the bytes that were there before.
- **Other hosts are export-only:** Codex and Antigravity (`.agents/skills`), Gemini CLI
  (`.gemini/skills`) and IBM Bob (`.bob/skills`) are labelled `CAPABILITY_EXPORT_ONLY`. repo-ai has
  not observed those hosts load a skill.

Engineering notes and the diagnosis of the failed validations:
[engineering/SKILLS_NETWORK.md](engineering/SKILLS_NETWORK.md).

## Threats considered

These scenarios have adversarial fixtures in `tests/test_skill_network.py`:
- a malicious SKILL.md;
- prompt injection;
- hidden Unicode;
- scripts that download and run code;
- secret reading;
- environment exfiltration;
- destructive commands;
- typosquatted dependencies;
- npm lifecycle scripts;
- publisher impersonation;
- symlink escapes;
- `allowed-tools` escalation;
- hooks and settings edits;
- a useful-looking skill that harms outcomes;
- unavailable services;
- missing licences;
- over-broad triggers;
- incomplete evidence;
- secrets in queries;
- work-zone denial.
