# Provider integrations: observed facts

Each row is an observation bound to a binary version, a platform and a date. "Declared" means read from `--help`
or official docs; "observed" means a run on this project's host. Nothing here is inferred from a binary being on PATH.

## Claude Code (`claude`) — isolated execution provider

Host: macOS (Darwin 25.5, Apple silicon), Claude Code **2.1.314** (native install, `~/.local/share/claude/versions/`),
account type Max subscription (cost reported by the stream is notional; real billing is subscription quota, so USD is
`OBSERVED` from the stream but **not billing truth**).

### Why 0.9.0 reported "Not logged in" (root cause, 2026-10-30)

Free probes (`claude auth status --json`, no model call; only `loggedIn`/`authMethod` were recorded):

| # | HOME | USER | CLAUDE_CONFIG_DIR | Sandbox | loggedIn |
|---|---|---|---|---|---|
| A | real | set | default | none | true |
| B | real | set | repo-ai dedicated dir | none | true |
| C | scratch | **unset** | dedicated dir | none | false |
| D | scratch | unset | default | none | false |
| E | real | **unset** | dedicated dir | none | false |
| F | real | set | dedicated dir | none | true |
| G | real | set | dedicated dir | seatbelt, HOME unreadable incl. keychain | false |
| H | real | set | dedicated dir | seatbelt, HOME unreadable except dedicated dir, install dir, `login`/`metadata.keychain-db` | **true** |
| I | scratch | set | dedicated dir | none | false |

Conclusions: the login is a keychain item found through the user's login keychain (located via `HOME`) and the
account name (`USER`); `CLAUDE_CONFIG_DIR` selects a distinct item, so a dedicated config dir is a separate login from
the user's personal one. 0.9.0 ran Claude with a scratch HOME and only passed `USER` when set, and also **copied**
`~/.claude/.credentials.json`, `settings.json` and `~/.claude.json` into the scratch HOME — that copying never helped
on macOS and is credential copying; it is removed.

A token refresh is written by the CLI back to the keychain (atomic `login.keychain-db.sb-*` replace) and to
`<config>/.claude.json`. With those writes denied, an expired access token failed as
`401 OAuth access token has expired` (observed 2026-10-30T02:43Z); the same login refreshed and succeeded outside the
sandbox. The isolated profile therefore allows writes to exactly those two database files (and their `.sb-*` temp
siblings) and to the dedicated config dir minus its customisation files.

### Design chosen (mission §3 option 1 + 3)

Ranked alternatives considered:

1. **Credential-aware isolated invocation** (chosen). `token_env`: `CLAUDE_CODE_OAUTH_TOKEN` (from `claude
   setup-token`) or `ANTHROPIC_API_KEY` in repo-ai's environment → scratch HOME, keychain unreadable.
   `dedicated_config`: a repo-ai-owned login dir (`~/.local/share/repo-ai/claude-provider`, or
   `REPO_AI_CLAUDE_CONFIG_DIR`) the user logs in once (`CLAUDE_CONFIG_DIR=<dir> claude auth login`) → real HOME,
   seatbelt denies every read under HOME except that dir, the Claude install and the two keychain database files.
2. **Host-authenticated patch-only** (prototype not needed). A tool-less host request returning a diff would avoid
   the keychain exposure but loses the agent's ability to read the repository; with (1) working, it adds no safety the
   tool restriction does not already give. Kept as the fallback if a future Claude Code removes the isolation flags.
3. **User-mediated isolated login** — this is the `dedicated_config` half of (1).
4. Credential broker / RPC bridge — rejected: more code holding secrets than (1), no smaller attack surface.

Model-facing restrictions (all declared by `claude --help` 2.1.314 and checked before every live run; a missing flag
blocks the run as `unsupported_version`): `--tools Read,Edit,Write,Glob,Grep` (`Read,Glob,Grep` for read-only roles),
`--restricted` (no code-running tools, file tools confined to the working dir, user/project/local settings ignored),
`--safe-mode` (no CLAUDE.md, skills, plugins, hooks, MCP, custom agents), `--strict-mcp-config`,
`--disable-slash-commands`, `--permission-mode acceptEdits`, `--permission-prompts none`, `--no-session-persistence`,
`--max-budget-usd` (hard ceiling the CLI enforces). Never `--dangerously-skip-permissions` or `bypassPermissions`.

Observed init event under this profile (bogus-model probe, $0): `tools: [Edit, Glob, Grep, Read, Write]`,
`mcp_servers: []`, `skills: []`, `slash_commands: []`, plugins only the built-in `cc-plugin-*`.

### Residual exposure (disclosed)

* `dedicated_config`: the Claude process can read and replace the (encrypted) login keychain database files and can
  reach keychain items through the Security framework like any process of this user. The model itself has no shell
  or code tool, so it cannot invoke `security`; the boundary is Claude Code's tool restriction plus seatbelt, not
  seatbelt alone. `token_env` has no keychain access at all and is the recommended mode.
* Network is allowed for live runs (the API needs it); the model has no web or shell tool to use it.
* Linux: the bwrap profile hides HOME with a tmpfs and re-exposes only the install, `node` prefix and the dedicated
  dir. **Not live-verified on Linux.** Windows: no supported sandbox → refused.

### Live observations

| When (UTC) | Path | Model | Result | Notional cost |
|---|---|---|---|---|
| 2026-10-30T02:43Z | raw probe, seatbelt denying keychain writes | sonnet | `401 OAuth access token has expired` (refresh blocked) | $0 |
| 2026-10-30T02:44Z | raw, unsandboxed, dedicated login (refresh check, "reply ok") | sonnet | success | $0.0064 |
| 2026-10-30T02:49Z | `run_provider` (repo-ai code path), dedicated login, seatbelt | sonnet | `LIVE_READY`, protocol valid, model edited `calc.py` correctly (`a - b` → `a + b`) | $0.0139 |

The end-to-end `repo-ai do --agent claude --run --allow-live-provider` journey (frozen visible tests, hidden oracle,
apply/undo) is **pending owner authorization of live spend** (the session's tool guard classifies it as a spending
action). Until it runs, C03 stays `EXPERIMENTAL`, not PASS.

## Other providers

See `docs/launch/LAUNCH_REPORT.md` (0.9.0): Codex 0.165.0 and agy 1.4.9 live-verified n=1 on macOS; Bob earlier;
Gemini rejected (account) and not retried. Provider-fabric research for further agents: in progress.
