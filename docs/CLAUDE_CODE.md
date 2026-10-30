# repo-ai and Claude Code

Verified against **Claude Code 2.1.303** (the binary's own schemas, and
`claude plugin validate`). Older 2.x clients should work for everything except
`PostToolUseFailure`, which is only used with `learning_signals = "known-commands"`
or `"outcomes"`.

## What `repo-ai init --agent claude [--smart]` writes

| File | Purpose | Loaded |
|---|---|---|
| `CLAUDE.md` — one marked block | project summary, declared commands, learned repo-wide rules, how to ask for context, boundaries | every session (~200–300 tokens) |
| `.claude/rules/repo-ai-<topic>.md` | path-scoped learned rules (`paths:` front matter) | only when Claude works with matching files |
| `.claude/skills/repo-*/SKILL.md` | 8 curated workflow skills (`repo-learn` and `repo-pr` manual-only) plus generated, repo-specific ones | description always; body on use |
| `.claude/agents/repo-*.md` | 4 subagents: explorer, impact-analyst, verifier, security-reviewer (only with `feature_set = "full"`; new installs are `core`) | when delegated to |
| `.claude/hooks/repo-ai.sh` | hook dispatcher (always exits 0) | on hook events |
| `.claude/settings.json` | hook entries merged in; nothing else touched | — |

With `--local-only`, hooks go to `.claude/settings.local.json`, the block goes
to `CLAUDE.local.md`, and every repo-ai output is gitignored.

### Verification guidance (0.7.6)

The managed block carries one **Verify** line, built from a verification plan
(`repo_ai.testing.verification_plan`):

- **Tests are the verification.** Run the relevant tests, then the full
  suite before finishing: a passing targeted test can hide a break elsewhere.
- **The test command:** declared by the project (manifests, CI, docs), with
  root-level commands first. Without one, it is inferred from the tests
  themselves for standard runners only (unittest, pytest, `go test`,
  `cargo test`, `dotnet test`), and the line says so ("inferred; confirm it
  runs").
- **When no trustworthy command exists,** the line says that, and why,
  instead of inventing one.
- **Static checks, type checks, builds and formatters are complementary.**
  A learned lint rule is named only while it is an active rule, and always
  as "complements the tests, never replaces them". Formatters are never
  turned into rules.
- **Disclosure.** "If tests cannot run, say so; never report a change as
  verified without running them."
- **Human instructions win.** If your CLAUDE.md or AGENTS.md already has a
  testing section or names the test command, the line defers to it, and
  your text is never edited.
- **Only plain runner invocations are written.** Commands with shell
  plumbing, network fetchers, `sudo`, deploy/publish steps and the like are
  kept out of the instructions and listed in TESTING.md for review. repo-ai
  never runs any of them.

This came out of the Option A experiment: on one task the block named only
`ruff check .`, and the agents linted instead of running the suite. That
**fixes a measured harm**; whether the new guidance improves real-model
success is **unverified** until a new controlled evaluation.

### CLAUDE.md and AGENTS.md

By default Claude Code loads `AGENTS.md` **only when there is no `CLAUDE.md`**
(the `agents_md` mode `claude-md-or-agents-md`). Consequences repo-ai handles:

* A repo with only `AGENTS.md`: repo-ai creates `CLAUDE.md` with an
  `@AGENTS.md` import first, so your AGENTS.md keeps loading. On uninstall that
  CLAUDE.md is removed again.
* `--agent both`: shared guidance lives in the AGENTS.md block, which Bob reads
  and Claude imports. The CLAUDE.md block shrinks to Claude-specific lines, so
  nothing is injected twice.
* An existing `CLAUDE.md` that does not import AGENTS.md is left as it is.
  `repo-ai doctor` mentions that Claude will not see AGENTS.md.

## Hooks

| Event | Matcher | What repo-ai does | Output |
|---|---|---|---|
| `SessionStart` | (all sources, including `compact`) | freshness line; starts a background refresh if the index is stale | `additionalContext`, under 200 tokens |
| `UserPromptSubmit` | — | ranked file shortlist with line ranges, **only** at medium/high confidence; skips `/…`, `!…`, `#…`, acknowledgements and short prompts | `additionalContext`, capped by `hook_budget_tokens` (1200) and 9,000 characters |
| `PostToolUse` | `Write\|Edit\|MultiEdit\|NotebookEdit` | appends the edited path (inside the repo only) to `state/.dirty` | none |
| `Stop` | — | if dirty and no update is running, starts a debounced, detached `repo-ai refresh`; ignores `stop_hook_active` turns | none |
| `Stop` (same entry) | — | **opt-in verify gate, only with `verify_gate = true`**: when the working tree has behavioural Python or JavaScript/TypeScript changes with no passing `repo-ai verify` evidence for that exact change, asks the agent to run `repo-ai verify --run` and report the result. Once per change, at most `verify_gate_max_blocks` (3) times per session, never on `stop_hook_active` turns; fails open. With `verify_gate_mode = "report"` it never blocks and shows you one line of evidence status instead. **Experimental:** its effect on agents is unmeasured | `{"decision": "block", "reason": …}`, or `systemMessage` in report mode |
| `PostToolUse` / `PostToolUseFailure` | `Bash` | **only with `learning_signals = "known-commands"` or `"outcomes"`**: records whether one of the repo's declared commands ran or failed | none |
| `PostToolUse` | `Skill` | **only with `learning_signals = "outcomes"`** (`post-skill`): records which skill a session used, by name and version, so skill versions can be compared on outcomes. Only well-formed skill names; arguments are never recorded | none |

The gate is the only hook that can ever ask the agent to continue, and it is
off unless you set `verify_gate = true` (see [CONFIGURATION.md](CONFIGURATION.md)
and [VERIFY.md](VERIFY.md)).

Not used, deliberately: `PreToolUse` (repo-ai never gates tools),
`PreCompact`/`PostCompact` (SessionStart with source `compact` already
re-orients, and no transcripts are stored), `SessionEnd` (Stop already covers
refresh, and SessionEnd has a 1.5 s budget).

Guarantees, all covered by tests:

* exit code 0 always, so a broken repo-ai never blocks a prompt;
* zero bytes on malformed or empty stdin, a missing index, or irrelevant prompts;
* a hard 6 s internal alarm, under the 10 s hook timeout;
* no prompt text, file content or secrets in logs or state;
* measured round trip: about 67 ms on the fixtures and about 130 ms on a
  4,000-file synthetic repository (see `benchmarks/`).

Set `REPO_AI_HOOK_DEBUG=1` in the environment Claude Code runs in to see hook
diagnostics on stderr.

## Skills

Curated (always written unless `skills_mode = "off"`): `/repo-orient`,
`/repo-locate`, `/repo-impact`, `/repo-verify`, `/repo-debug`, `/repo-review`,
and the manual-only `/repo-learn` and `/repo-pr`. Manual-only management
commands, which cost no always-loaded context: `/repo-capabilities`,
`/repo-performance`, `/repo-optimize`, `/repo-discover-skills`,
`/repo-skill-audit`, `/repo-skill-recommend` and `/repo-skill-evaluate`.
Generated (Skill Factory, only with `skills_mode = "auto"`; see
[LEARNING.md](LEARNING.md)): for example `/repo-add-endpoint`, `/repo-tests`,
`/repo-add-component`, and the manual-only `/repo-db-migration` and
`/repo-release`.

None declares `allowed-tools`, so Claude Code's normal permission prompts
still apply to every command a skill suggests.

## Subagents

| Agent | Tools | Notes |
|---|---|---|
| `repo-explorer` | Read, Grep, Glob, Bash | told to use Bash for read-only commands only |
| `repo-impact-analyst` | Read, Grep, Glob, Bash | same |
| `repo-verifier` | Read, Grep, Glob, Bash | runs tests and checks; told never to edit, install, deploy or migrate |
| `repo-security-reviewer` | Read, Grep, Glob | no shell at all |

The `tools` list restricts these agents. It grants nothing: Claude Code's
permission rules still apply.

## Verifying the setup

```sh
repo-ai doctor --agent claude       # wiring, hook round-trip latency, skill validation
claude plugin validate .claude      # Claude Code's own validator for skills and agents
```

Inside Claude Code: `/hooks` lists the repo-ai entries, `/skills` lists the
skills, `/agents` lists the subagents, and `/context` shows what the CLAUDE.md
block costs. **Restart** sessions that were open before `init`: hooks, skills
and CLAUDE.md are read at session start.

## Plugin channel (optional)

`integrations/claude-plugin/` is a valid Claude Code plugin, and
`.claude-plugin/marketplace.json` at the repository root lists it. Both pass
`claude plugin validate`. The plugin is generated from the same source as the
project files (`scripts/build_plugin.py`; a test fails if it goes stale).

```sh
claude plugin marketplace add /path/to/repo-ai     # or the repository's git URL
claude plugin install repo-ai@repo-ai
```

The plugin's skills are namespaced (`/repo-ai:locate`, `/repo-ai:review-diff`,
…). Its hooks do nothing in a repository without an index. When the plugin is
enabled, `repo-ai init --agent claude` skips project hooks so they don't run
twice, and `doctor` reports which channel provides them.
