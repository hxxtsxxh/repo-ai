# Engineering decisions (omniprovider mission)

Earlier launch decisions L-001…L-009 are in `docs/launch/DECISIONS.md` and stay in force.

## O-001 — Claude Code authenticates by its own supported login, never by copied credentials (2026-10-30)
Context: 0.9.0 copied `~/.claude/.credentials.json`/`settings.json`/`.claude.json` into a scratch HOME and still got
"Not logged in". Root cause (INTEGRATIONS.md): keychain lookup needs the real login keychain and `$USER`.
Decision: two modes — `token_env` (CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY, scratch HOME, no keychain) and
`dedicated_config` (repo-ai-owned login dir, HOME read-restricted, keychain DB files only). No copying. A missing login
is `SETUP_REQUIRED` (offline check, no credential read) with the exact one-time command.
Rejected: patch-only host route (loses repository reading for no safety gain over the tool restriction); a
credential broker (more secret-holding code); reusing the personal `~/.claude` (personal hooks/plugins/MCP).

## O-002 — Model-side tool restriction is a required layer, checked per run (2026-10-30)
The OS sandbox bounds writes; the tool list bounds what an injected instruction can make the model do. Claude runs
with file tools only, `--restricted --safe-mode --strict-mcp-config --disable-slash-commands`. Read-only roles get
no edit tools. If `claude --help` lacks any required flag the run is refused (`unsupported_version`), so version
drift fails closed.

## O-003 — Work flows through the public repository by PR (2026-10-30)
Public `hxxtsxxh/repo-ai` is canonical (launch L-009). Specialists work in fresh public clones; the principal merges.
The private `repo-ai-dev` history is never pushed publicly.
