# A repo-ai-installed skill on two real hosts, 2026-10-30

Build: wheel of `skills/autopilot` (rebased on the provider stack), installed non-editable; `REPO_AI_HOME` in a
scratch dir. Fixture skill `pin-tests` (SKILL.md + MIT LICENSE, written for this check): "every new test function
must begin with `"""PIN: <requirement>."""`" — an arbitrary, observable convention, so following it can be detected.
Single author, n=1 per arm. This shows load and invocation, **not** that a skill improves outcomes.

## Install (repo-ai)

| Step | Command | Result |
|---|---|---|
| vet | `repo-ai skills discover --from-path src/pin-tests` | `eligible`, licence MIT, `local/pin-tests@0cbbc4e4abac` |
| explain | `repo-ai skills explain pin-tests` | firewall ELIGIBLE, 0 findings; **recommendation: do not install (score 0.051) — matches no evidence-backed gap** (honest: the fixture fills no gap) |
| preview | `repo-ai skills install pin-tests --approve 0cbbc4e4abac --host claude-code,codex --dry-run` | diff with the repo-ai ownership marker |
| install | same without `--dry-run`, full hash | `.claude/skills/pin-tests/` and `.agents/skills/pin-tests/`; codex labelled export-only |
| uninstall | `repo-ai skills disable --third-party pin-tests` | both directories removed; every pre-existing file byte-identical (sha256 list diff); `.repo-ai/skills.lock.json` keeps the disabled entry for rollback |

## Host 1 — Claude Code 2.1.314 (`.claude/skills`)

- **Load** ($0): a host-mode `claude -p` with a locally rejected model name emits its init event without inference;
  `skills` contained `pin-tests` and `slash_commands` contained `/pin-tests`.
- **Invocation and effect** (haiku, `--tools Read,Write,Edit,Glob,Skill`, same prompt "Add a pytest file
  test_slug.py with two tests for slug() in slug.py", calls #14/#15):

| Arm | Tool calls | Tests written | `PIN:` docstrings | pytest | Cost |
|---|---|---|---|---|---|
| skill installed | `Skill(pin-tests)`, Glob, Read, Write (+ an account MCP tool, see below) | 2 | **2** | 2 passed | $0.0242 |
| control (no skill) | Read, Glob, Write (+ account MCP tools) | 2 | **0** | 2 passed | $0.0077 |

  An earlier sonnet pair (calls #12/#13) invoked `Skill(pin-tests)` in the skill arm only, but both runs stopped at
  the $0.30 cap before writing ($0.320 / $0.383: the cap is checked between turns).
- **Confound found:** host mode exposed the account's synced MCP connectors (a shell tool among them); the model used
  them in both arms. Provider runs are not affected (see INTEGRATIONS.md, isolation probe). Future host-mode trials
  must pass `--strict-mcp-config` and use a login separate from the provider login.

## Host 2 — OpenCode 2.2.1 (`.agents/skills`), local qwen3:8b, $0

- With OpenCode's defaults, an explicit "call the skill tool with name pin-tests" returned
  `<skill_content name="pin-tests"> … <!-- repo-ai:managed …` — the bytes repo-ai installed.
- `OPENCODE_DISABLE_CLAUDE_CODE=1` (which repo-ai's provider adapter sets) also disables `.agents/skills`; then the
  skill tool answers "Unable to load skill pin-tests" (3 attempts). `.opencode/skills` loads only when project config
  is enabled. So: repo-ai's isolated OpenCode provider runs without repository skills; OpenCode as a host loads them.
- Unprompted, the 8B model never chose the skill (2 attempts with it installed, 0 `PIN:` docstrings): load and
  explicit invocation verified, model-chosen invocation not observed.

## Status

C09 (two-host install + load + invocation + rollback): demonstrated for Claude Code (model-chosen invocation) and
OpenCode (explicit invocation), n=1. C10 (skill value): **not demonstrated** — the paired Claude result shows the
instruction is followed, not that outcomes improve; no blinded trial was run.
