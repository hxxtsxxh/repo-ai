# Configuration

Precedence, from lowest to highest:

1. built-in defaults
2. `~/.config/repo-ai/config.toml`
3. `<repo>/.repo-ai/config.toml`, written once by `init`
4. `<repo>/.repo-ai.toml` or `repo-ai.toml`
5. `REPO_AI_*` environment variables
6. CLI flags

Keys are flat. A `[repo-ai]` or `[tool.repo-ai]` table is also accepted.
Invalid values keep the default and are reported by `repo-ai doctor`.

| Key | Default | Meaning |
|---|---|---|
| `agents` | set by init | `["claude"]`, `["bob"]` or both |
| `learning_policy` | `suggest` | `off` · `suggest` · `safe-auto` · `manual-only-for-risky` ([LEARNING.md](LEARNING.md)) |
| `learning_signals` | `off` | `off` · `known-commands` · `outcomes` (local, minimal; `--smart` sets `outcomes`; see LEARNING.md) |
| `always_loaded_budget_tokens` | 1500 | cap on repo-ai's always-loaded context; `repo-ai budget --check` and doctor warn above it |
| `max_generated_skills` | 8 | at most this many active generated skills (explicit requests win, then confidence) |
| `skills_llm` | `off` | `on` allows opt-in Tier-2 skill drafting (billable; zone policy must allow it; docs/SKILLS.md) |
| `claude_cmd` | `claude` | Claude Code executable for drafting |
| `feature_set` | `core` for new installs | `core` · `full`. **core**: verification guidance, context, hooks, curated skills. **full**: also the read-only subagents, the `repo-skeptic` reviewer, orchestration hints and `skills_mode = "auto"`. `init --feature-set full` records it. Any key set explicitly wins over the set. A config from before 0.7.6 (no `feature_set` line) keeps the earlier defaults (subagents on). Full is **not** shown to improve task success (Option A: no subagent or skill was invoked, at about 10% higher cost). |
| `skeptic_reviewer` | `false` | install the advisory read-only `repo-skeptic` subagent |
| `orchestration` | `off` | `suggest` reserved for mentioning `repo-ai orchestrate plan`; advice only either way |
| `flight_recorder` | `false` | record prompt-hook decisions locally, without prompts (`repo-ai debug last`) |
| `skills_mode` | `curated` | `off` · `curated` · `auto` (Skill Factory) |
| `out_dir` / `state_dir` | auto | custom docs / index location (must be inside the repo) |
| `commit_context` | `true` | `false` gitignores generated docs and the learning ledger |
| `local_only` | `false` | personal setup: `settings.local.json`, `CLAUDE.local.md`, everything gitignored |
| `hook_budget_tokens` | 1200 | hard cap for prompt-hook injection |
| `hook_max_files` | 8 | files per prompt injection |
| `hook_min_prompt_chars` | 20 | shorter prompts get no retrieval |
| `context_budget_tokens` / `max_context_files` | 6000 / 14 | CLI `context` limits |
| `query_cache` | `true` | cache retrieval results in the index |
| `refresh_debounce_seconds` | 15 | minimum gap between hook-triggered refreshes |
| `extra_excludes` / `include_overrides` | `[]` | gitignore-style patterns |
| `max_file_bytes`, `max_files`, `git_history_days`, `git_max_commits`, `workers` | — | analysis limits |
| `detect_secrets` | `true` | content secret scan (path quarantine always applies) |
| `write_claude_md`, `write_claude_rules`, `write_claude_skills`, `write_claude_agents`, `write_claude_hooks` | `true` (agents: per `feature_set`) | switch off individual Claude outputs. Switching agents off retires only unedited repo-ai agents |
| `write_agents_md`, `write_skill`, `write_hooks`, `write_bobignore` | `true` | switch off individual Bob outputs |
| `summarize`, `bob_binary`, `summarize_max_cost` | `false`, `bob`, `0.50` | opt-in narrative via `bob run` (sends facts, not code) |
| `verify_gate` | `false` | `true` turns on the experimental `Stop`-hook completion gate: when the working tree has behavioural Python or JavaScript/TypeScript changes with no passing `repo-ai verify` evidence for that exact change, the agent is asked once to run `repo-ai verify --run` ([CLAUDE_CODE.md](CLAUDE_CODE.md#hooks)). Its effect on agents is unmeasured |
| `verify_gate_mode` | `block` | `block` · `report`. `report` never blocks: it shows you one line about the change's evidence status instead |
| `verify_gate_max_blocks` | 3 | the gate blocks at most this many times per agent session (`0`: never) |
| `verify_test_command` | `""` | the test command `repo-ai verify` uses, as given, instead of establishing one from the project's files; set it when verify cannot establish one, for example `"PYTHONPATH=src python -m pytest tests"`. `--test-command` wins over it. It runs only with `--run` or `--record`, sandboxed. A repository's own config file can set it, so `verify` prints the command and its origin before running anything ([VERIFY.md](VERIFY.md#which-test-command-runs)) |

Environment variables used internally (`REPO_AI_IN_HOOK`, `REPO_AI_HOOK_DEBUG`,
`REPO_AI_NO_BACKGROUND`, `REPO_AI_EVAL_SUITE`, `REPO_AI_HOME` (registry location)) are
not read as configuration.
