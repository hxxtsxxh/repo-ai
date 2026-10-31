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

## OpenCode (`opencode`) — local model, account-free

Host: macOS, OpenCode **2.2.1** (Homebrew, MIT), Ollama **0.40.12/0.40.13** serving `qwen3:8b` (5.2 GB) on
`127.0.0.1:11434`, started as a session-owned process (no launchd service). Observations:

* `opencode run --format json` emits `step_start`, `tool_use` (`part.tool`, `part.state.status`, errors such as
  `Permission denied: external_directory`), `step_finish` (`part.cost`, `part.tokens`) and a final `text`; failures
  are `{"type":"error","error":{"message":…}}` with exit 1. A run where the model stops after `step_start` exits 0
  with no `text`: repo-ai treats that as no terminal event.
* Tool permissions default to allow, and 2.2.1 ships an undocumented `execute` (JavaScript) tool. Deny-by-name is
  therefore unsafe; repo-ai sends `"*": "deny"` plus explicit allows. Verified: with the wildcard policy the model is
  offered no execute/bash tool, and edits still work.
* Without `--standalone`, a detached `opencode serve --service` (parent PID 1) outlives the command. repo-ai always
  passes `--standalone`; every run in this cycle left no `opencode` process.
* Seatbelt: `(allow network* (local ip "localhost:*"))` **also admits outbound connections to any host** (observed:
  `nc` reached 1.1.1.1:443). The profile uses `network-outbound (remote ip "localhost:*")` plus loopback inbound/bind,
  and a test probes a real external address.
* Events embed whole tool inputs/outputs: a 28-edit local run produced 68 KB (86 lines), over repo-ai's 64 KB
  default; OpenCode gets a 256 KB bounded capture.

## Gemini CLI

0.9.0 copied the entire `~/.gemini` (OAuth tokens, account list and **agy's per-user state under
`antigravity-cli/`**, including conversation history) into the provider's scratch HOME. Removed: live Gemini now needs
`GEMINI_API_KEY` or `GOOGLE_API_KEY`. A bounded retry on 2026-10-30 (Gemini CLI 0.65.0, OAuth copy still in place)
exited 41 (authentication failure) before any edit; with no key on this host it stays `BLOCKED`.

## Codex CLI — residual risk (disclosed, not fixed)

Codex authenticates from `~/.codex/auth.json`, which repo-ai copies into the provider's scratch HOME, and Codex runs
with its shell tool and network access (its own sandbox is bypassed only under repo-ai's verified outer sandbox).
The model can therefore read that token file; a prompt-injected repository could ask it to send the token out.
repo-ai cannot hide a credential from the process that needs it. Planned mitigation: a dedicated repo-ai Codex login
(`CODEX_HOME`) so a leaked token is a separate, revocable session. Until then the provider matrix states it.

Live re-verification on the 0.10.0 development build (2026-10-30, same durations task and hidden oracle): Codex
0.165.0 PASS in 41 s, oracle 17/17, undo clean; agy 1.4.9 PASS in 43 s, oracle 17/17, undo clean. Bob not re-run
(its account entitlement was not re-checked this cycle).

## Independent adversarial review of provider isolation (2026-10-30) and fixes

A separate reviewer (fresh clone, real `sandbox-exec` probes, no model calls) confirmed, and this cycle fixed with
regression tests:

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | Read rules could open all of HOME: `_install_roots` walked up to a `~/package.json` (left by any `npm install` in HOME), a binary placed directly in HOME allowed its parent (`~`), and `_node_roots` allowed the node prefix (e.g. all of `~/.local`). `cat ~/.ssh/id_rsa` succeeded in the reviewer's probe. | high | package.json search only inside `node_modules`; never HOME, an ancestor or a top-level app-data dir (falls back to the binary as a literal); node exposed as its binary only |
| 2 | `REPO_AI_CLAUDE_CONFIG_DIR` accepted the parent of HOME, `~/.ssh`, `~/.config`; the config dir is writable, so the sandbox appended to `~/.zshrc`. | medium | refused (HOME, ancestors, sensitive dirs) |
| 3 | OpenCode's `(allow network-outbound (remote unix-socket))` reached any unix socket (container engine, ssh-agent) and let DNS leave the machine via mDNSResponder; Claude live runs reached them too. | medium-high | OpenCode: unix sockets under its scratch dir only (localhost still resolves); Claude: mDNSResponder and scratch only |
| 4 | Ollama `*-cloud` models pass as local, but Ollama serves them remotely. | medium | refused; a loopback proxy forwarding off-machine remains the user's responsibility (documented) |
| 5 | `settings.local.json` not audited. | low | audited |
| 6 | 500-line event bound failed long correct OpenCode runs. | low-medium | 4000 lines for OpenCode |
| 7 | A tracked `.venv` symlink in a branch commit. | hygiene | removed from history before merge |

Not fixed (disclosed): a descendant that calls `setsid` survives the process-group kill (still sandboxed; it could
edit the workspace after verification); reads outside HOME (`/tmp`, `/private/var/folders`, `/Users/Shared`) stay
open; keychain access through the Security framework in `token_env` mode was not probed. Repository-local OpenCode
plugins: in 2.2.1, `opencode plugin list` finds none from `.opencode/plugins` and a canary plugin did not load, with
or without repo-ai's settings (observed for this version only). Non-standalone OpenCode commands (`plugin list`)
start the detached service; repo-ai's discovery probes do not (checked).

Live re-verification after the fixes (2026-10-30T05:48Z): Claude `run_provider` READY (`dedicated_config`, tools
Read+Edit, $0.014114, correct edit); OpenCode READY (read+edit, $0, correct edit); no `opencode` process left.

## Account sync reaches every login; a per-run isolation probe checks it (2026-10-30)

A Claude Code login carries what its **account** syncs: in a host-mode (non `--safe-mode`) session from the dedicated
repo-ai login, the init event listed plugins `desktop-commander` (shell), `engineering`, `design`, … and claude.ai
connectors (Gmail, Drive, Calendar connected). `--tools` restricts built-in tools only; the model in that host-mode
run used desktop-commander's `start_process`. That session also wrote the account's sync cache into the login dir
(`skills/synced`, `plugins/synced`). The config-dir audit cannot see account-level state.

repo-ai's provider invocation removes all of it (`--safe-mode`, `--strict-mcp-config`, `--restricted`); this is now
**checked on every live run**: before the real run, repo-ai starts the exact invocation with a model name Claude Code
rejects locally (no API request; `total_cost_usd` 0) and reads the init event. Any tool beyond the requested set,
any MCP server, any non-built-in plugin, or any skill/command refuses the run (`isolation_probe_failed`). Observed on
the real CLI with the sync cache present: the probe passed (tools `Edit, Glob, Grep, Read, Write` only) and the run
succeeded (call #16, $0.010517). The audit now leaves `*/synced` to the probe and still refuses user-authored
skills, hooks, agents and commands.

Lesson for experiments: host-mode skill trials must use a login separate from the provider login.

## Claude `--max-budget-usd` overshoot

The CLI checks its budget between turns: two host-mode runs capped at $0.30 ended at $0.320 and $0.383 (stopped
before finishing). repo-ai already fails a run whose reported cost exceeds the ceiling; budgets should assume one
turn of overshoot.

## Agent Client Protocol (ACP) client, 2026-10-31

`src/repo_ai/providers/acp.py` is one client for every agent that speaks ACP 1 (JSON-RPC 2.0 over stdio, one object
per line). One permission policy covers all of them:
- `fs/read_text_file` is served only inside the workspace, and links are not followed out of it;
- `fs/write_text_file` is served only for the run's allowed paths;
- terminals are not offered;
- `session/request_permission` allows once only `read`/`search`/`edit`/`think` tool calls, rejects
  `execute`/`fetch`/`delete`/`move`/`other`, and never chooses allow-always.

Handshake probes (`AcpClient.probe`: `initialize` only, no session, no model call):

| Agent | Command | Answer |
|---|---|---|
| OpenCode 2.2.1 | `opencode acp` | ACP 1; auth `opencode-login` |
| Gemini CLI 0.65.0 | `gemini --experimental-acp` | ACP 1; auth `oauth-personal`, `gemini-api-key`, `vertex-ai`, `gateway` |

Live run, $0: OpenCode over ACP with the local Ollama `qwen3:8b`, its deny-by-default inline config and a scratch
HOME, on a scratch fixture (`clamp.py`).
- `end_turn` in 44 s; the edit tool calls streamed as `session/update`.
- The agent edited the file **itself**, not through `fs/write_text_file`, and asked no permission (its inline config
  allows `edit`).
- The 8B model wrote a broken edit (literal `\n` escapes); a mission's verification would refuse it.

Conclusion: ACP is a uniform control channel (session, prompt, streamed tool calls, permission answers,
cancellation), not a security boundary. An ACP provider must still run the agent inside repo-ai's OS sandbox and
check the workspace afterwards (`validate_workspace_edits`), as the other providers do. Wiring ACP agents into
`repo-ai do` that way is the next step (queue item 4).
