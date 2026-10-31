# CLI reference

Generated from the installed parser by `scripts/gen_cli_reference.py`; do not edit by hand.
`repo-ai <command> --help` prints the same arguments. Commands marked *(experimental)* are
described in the status matrix.

## Commands

| Command | Summary |
|---|---|
| [`init`](#repo-ai-init) | analyse a repository and wire up agents |
| [`update`](#repo-ai-update) | incremental re-analysis |
| [`rebuild`](#repo-ai-rebuild) | full re-analysis from scratch |
| [`refresh`](#repo-ai-refresh) | debounced update for hooks (never blocks) |
| [`status`](#repo-ai-status) | freshness check (exit 2 when stale) |
| [`context`](#repo-ai-context) | retrieve relevant files for a task |
| [`explain`](#repo-ai-explain) | show why each file was retrieved (score breakdown) |
| [`impact`](#repo-ai-impact) | change impact for paths or symbols |
| [`verify`](#repo-ai-verify) | what a change can break, which tests show it, and (with --run) what running them in a sandbox showed |
| [`evidence`](#repo-ai-evidence) | the latest verification evidence and whether it covers the current change |
| [`prove`](#repo-ai-prove) | (experimental) ProofLab: show that the original code fails a pinned scenario and the change passes it: pin \| plan \| run \| status \| report |
| [`privacy`](#repo-ai-privacy) | audit what repo-ai stores, where, and whether it is committed |
| [`packet`](#repo-ai-packet) | small, source-linked task briefing (locations, tests, constraints, blast radius) |
| [`review`](#repo-ai-review) | pre-PR change passport: what the diff touches, tests, risks, blind spots |
| [`budget`](#repo-ai-budget) | budget governor: always-loaded and per-prompt context, limits (estimates) |
| [`capabilities`](#repo-ai-capabilities) | capability coverage map (no action), or the capability registry: list \| show \| prepare \| approve \| revoke \| run \| evidence; recommend \| candidates \| select are experimental |
| [`performance`](#repo-ai-performance) | repo-ai's measured effect here: hook, shortlist, sessions, experiments |
| [`optimize`](#repo-ai-optimize) | (experimental) research proposals; --apply only what the Self-Improvement Governor allows |
| [`friction`](#repo-ai-friction) | friction radar: repeated, evidence-backed waste (same as learn friction) |
| [`quickstart`](#repo-ai-quickstart) | where you are and what to run next |
| [`completion`](#repo-ai-completion) | shell completion script: bash \| zsh \| fish |
| [`orchestrate`](#repo-ai-orchestrate) | advise zero, one or a few read-only specialists for a task (spawns nothing) |
| [`graph`](#repo-ai-graph) | evidence graph around a file, symbol:&lt;name&gt;, route:&lt;METHOD path&gt; or component:&lt;name&gt; |
| [`debug`](#repo-ai-debug) | context flight recorder: what the prompt hook injected or omitted, and why |
| [`sandbox`](#repo-ai-sandbox) | isolated execution backends for untrusted code: status \| pull |
| [`eval`](#repo-ai-eval) | paired coding-task evaluation (offline by default; --live is opt-in) |
| [`search`](#repo-ai-search) | lexical search over the index |
| [`symbol`](#repo-ai-symbol) | find where a symbol is defined |
| [`related`](#repo-ai-related) | importers, imports, co-changes, tests of a file |
| [`deps`](#repo-ai-deps) | show declared dependencies |
| [`architecture`](#repo-ai-architecture) | print ARCHITECTURE.md |
| [`overview`](#repo-ai-overview) | print PROJECT_OVERVIEW.md |
| [`map`](#repo-ai-map) | print REPOSITORY_MAP.md |
| [`tests`](#repo-ai-tests) | print TESTING.md |
| [`conventions`](#repo-ai-conventions) | print CONVENTIONS.md |
| [`hotspots`](#repo-ai-hotspots) | print HOTSPOTS.md |
| [`learn`](#repo-ai-learn) | (experimental) evidence-backed rules and outcome learning: status \| review \| explain \| approve \| reject \| rollback \| history \| shadow \| friction \| forget \| export |
| [`skills`](#repo-ai-skills) | skill lifecycle (experimental, except the read-only inventory and vet): list \| discover \| propose \| test \| diff \| promote \| disable \| rollback \| canary \| draft \| doctor \| inventory \| vet \| policy \| autopilot |
| [`workflow`](#repo-ai-workflow) | compiled playbooks from verified workflows (read-only previews) |
| [`registry`](#repo-ai-registry) | opt-in cross-repo registry with isolated zones |
| [`pack`](#repo-ai-pack) | Stack Packs: evidence-backed bundles from repositories in this repo's zone |
| [`crossrepo`](#repo-ai-crossrepo) | context or impact across repositories in this repo's zone only |
| [`doctor`](#repo-ai-doctor) | diagnose installation and agent wiring |
| [`uninstall`](#repo-ai-uninstall) | remove what repo-ai created |
| [`hook`](#repo-ai-hook) | agent hook entry point (reads JSON on stdin) |
| [`why-test-failed`](#repo-ai-why-test-failed) | explain recorded baseline/candidate test failures; no execution |
| [`futures`](#repo-ai-futures) | experimental static/heuristic change futures across local and same-zone peers |
| [`apply`](#repo-ai-apply) | apply a fresh verified mission diff to the working tree and verify post-apply state |
| [`shortlist`](#repo-ai-shortlist) | evidence table for an abstained tournament; optional labelled policy preference; applies nothing |
| [`coverage`](#repo-ai-coverage) | map developer-declared requirements to the tests that observed them; no execution, never a correctness claim |
| [`undo`](#repo-ai-undo) | restore receipt-owned applied bytes; refuse later user edits |
| [`demo`](#repo-ai-demo) | run a zero-cost simulated local acceptance demo in an empty directory |
| [`mission-eval`](#repo-ai-mission-eval) | run deterministic zero-cost Reality Engine vs naive baseline protocol |
| [`do`](#repo-ai-do) | plan an outcome offline; run an isolated replay or authorized live provider candidate |
| [`agents`](#repo-ai-agents) | local provider availability; doctor runs sandboxed help/version only |
| [`mission`](#repo-ai-mission) | inspect, cancel or recover local mission checkpoints |
| [`why`](#repo-ai-why) | local mission why; no provider disclosure |
| [`trace`](#repo-ai-trace) | local mission trace; no provider disclosure |
| [`handoff`](#repo-ai-handoff) | local mission handoff; no provider disclosure |
| [`replay`](#repo-ai-replay) | local mission replay; no provider disclosure |
| [`compare`](#repo-ai-compare) | local mission compare; no provider disclosure |

## Global options

| Argument | Description |
|---|---|
| `--version` | show program's version number and exit |

## `repo-ai init`

analyse a repository and wire up agents

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--workers` `WORKERS` | parser threads (default: auto) |
| `--max-file-bytes` `MAX_FILE_BYTES` | skip files larger than this (default: 1500000) |
| `--git-history-days` `GIT_HISTORY_DAYS` | git window for hotspots (default: 365) |
| `--summarize` | add a narrative summary via `bob run` (sends facts, not code) |
| `--no-symbols` | skip AST parsing (much faster, less useful) |
| `--no-secrets` | disable the secret scanner (not recommended) |
| `--no-commit-context` | gitignore the generated docs instead of committing them |
| `--no-bob` | (v0.4 compatibility) skip Bob wiring |
| `--dry-run` | show what would change; write nothing |
| `--diff` | like --dry-run, with a unified diff |
| `--agent` `AGENT` | claude \| bob \| both \| auto \| none (default: bob, as in v0.4) (one of `claude`, `bob`, `both`, `auto`, `none`) |
| `--smart` | (experimental; no benefit shown) evidence-based self-maintenance: learning_policy=safe-auto, skills_mode=auto, learning_signals=outcomes |
| `--local-only` | personal setup: settings.local.json / CLAUDE.local.md, all outputs gitignored |
| `--feature-set` `FEATURE_SET` | capability set recorded in .repo-ai/config.toml: core (default for new installs) or full (experimental, no benefit shown: adds subagents, the skeptic reviewer, orchestration hints) (one of `core`, `full`) |
| `--force` | rebuild the index from scratch |

## `repo-ai update`

incremental re-analysis

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--workers` `WORKERS` | parser threads (default: auto) |
| `--max-file-bytes` `MAX_FILE_BYTES` | skip files larger than this (default: 1500000) |
| `--git-history-days` `GIT_HISTORY_DAYS` | git window for hotspots (default: 365) |
| `--summarize` | add a narrative summary via `bob run` (sends facts, not code) |
| `--no-symbols` | skip AST parsing (much faster, less useful) |
| `--no-secrets` | disable the secret scanner (not recommended) |
| `--no-commit-context` | gitignore the generated docs instead of committing them |
| `--no-bob` | (v0.4 compatibility) skip Bob wiring |
| `--dry-run` | show what would change; write nothing |
| `--diff` | like --dry-run, with a unified diff |

## `repo-ai rebuild`

full re-analysis from scratch

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--workers` `WORKERS` | parser threads (default: auto) |
| `--max-file-bytes` `MAX_FILE_BYTES` | skip files larger than this (default: 1500000) |
| `--git-history-days` `GIT_HISTORY_DAYS` | git window for hotspots (default: 365) |
| `--summarize` | add a narrative summary via `bob run` (sends facts, not code) |
| `--no-symbols` | skip AST parsing (much faster, less useful) |
| `--no-secrets` | disable the secret scanner (not recommended) |
| `--no-commit-context` | gitignore the generated docs instead of committing them |
| `--no-bob` | (v0.4 compatibility) skip Bob wiring |
| `--dry-run` | show what would change; write nothing |
| `--diff` | like --dry-run, with a unified diff |

## `repo-ai refresh`

debounced update for hooks (never blocks)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--background` | detach and return immediately |
| `--force` | ignore the debounce window |

## `repo-ai status`

freshness check (exit 2 when stale)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--brief` | one-line output for a SessionStart hook |
| `--json` | machine-readable JSON output |

## `repo-ai context`

retrieve relevant files for a task

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `task` | the task, in plain language (stack traces welcome) |
| `--scope` `SCOPE` | diff \| branch[:base] \| component:&lt;name&gt; \| lang:&lt;language&gt; \| path:&lt;glob&gt; \| tests |
| `--max-context-files` `MAX_CONTEXT_FILES` |  |
| `--context-budget-tokens` `CONTEXT_BUDGET_TOKENS` |  |
| `--no-tests` | exclude test files from results |
| `--no-cache` | bypass the query cache |
| `--format` `FORMAT` | one of `markdown`, `claude`, `hook`, `json`, `paths`, `mentions` |
| `--agent` `AGENT` | output style for an agent (one of `claude`, `bob`) |
| `--explain` | print the score breakdown |

## `repo-ai explain`

show why each file was retrieved (score breakdown)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `task` | the task, in plain language (stack traces welcome) |
| `--scope` `SCOPE` | diff \| branch[:base] \| component:&lt;name&gt; \| lang:&lt;language&gt; \| path:&lt;glob&gt; \| tests |
| `--max-context-files` `MAX_CONTEXT_FILES` |  |
| `--context-budget-tokens` `CONTEXT_BUDGET_TOKENS` |  |
| `--no-tests` | exclude test files from results |
| `--no-cache` | bypass the query cache |

## `repo-ai impact`

change impact for paths or symbols

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `targets` | paths or symbol names |
| `--changed` | use uncommitted changes as targets |
| `--branch` `BASE` | use changes since the merge-base with BASE (default: origin/HEAD or main) |
| `--depth` `DEPTH` | transitive importer depth (default 3) |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai verify`

what a change can break, which tests show it, and (with --run) what running them in a sandbox showed

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--base` `BASE` | compare the working tree with this revision (default HEAD) |
| `--run` | run the selected tests in the sandbox (executes repository code) |
| `--full` | with --run: run the full suite (it includes the selection) |
| `--show-fixed` | with --run: run the base revision's full suite once (cached) to name tests the change fixed |
| `--paths` `PATH[,PATH]` | plan only for these changed files (read-only; a per-edit preview: never with --run or --record, never evidence for the whole change) |
| `--rerun` | with --run: run again even when evidence for this exact change and environment exists |
| `--record` | run every test file once under a tracer (sandboxed) to record which code each one executes (executes repository code) |
| `--test-command` `CMD` | the project's test command, when repo-ai cannot establish it |
| `--sandbox` `SANDBOX` | where --run/--record execute (default: a host sandbox with the project's interpreter, else a container) (one of `auto`, `seatbelt`, `bwrap`, `podman`, `docker`) |
| `--image` `REF` | with --sandbox podman/docker: a local image that has the project's dependencies (never pulled; the default images have only the standard library) |
| `--no-runtime` | ignore recorded runtime evidence |
| `--workers` `WORKERS` | parallel test processes (default 4) |
| `--timeout` `TIMEOUT` | seconds per test process (default: 5x its measured time + 10s, at least 30s, at most 600s; 600s when nothing has been measured) |
| `--deadline` `SECONDS` | with --run: a total wall-clock budget for every test process of the run; no limit is extended past it, and tests it cuts or leaves unstarted make the run 'not verified' (never a pass) |
| `--gate` | (experimental) agent completion gate (Stop hook): silent unless the current change is unverified |
| `--json` | machine-readable JSON output |

## `repo-ai evidence`

the latest verification evidence and whether it covers the current change

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--json` | machine-readable JSON output |

## `repo-ai prove`

(experimental) ProofLab: show that the original code fails a pinned scenario and the change passes it: pin \| plan \| run \| status \| report

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | pin a claim and its scenario; plan (read-only); run (sandboxed, executes repository code); status (is the passport fresh); report (Markdown, json or in-toto) (one of `pin`, `plan`, `run`, `status`, `report`) |
| `ID` | the claim (default: the only one pinned); with pin: the id to give it |
| `--claim` `TEXT` | pin: what the change is supposed to do |
| `--claim-stdin` | pin: read the claim from stdin |
| `--scenario` `PATH` | pin: the acceptance test file, repository-relative (its exact bytes are pinned) |
| `--from` `REV` | pin: take the scenario (and --support files) from this commit, e.g. a reviewer's |
| `--file` `PATH` | pin: take the scenario's bytes from a file outside the repository |
| `--support` `PATH` | pin: a helper or data file the scenario needs; both runs use its pinned bytes |
| `--subject` `GLOB` | pin: the code under test (a path or glob, repeatable). The scenario runs on the base plus only these files of the change; without it, the changed files the scenario imports |
| `--target` `TEST_ID` | pin: a test id that must fail at the base (default: any test of the scenario) |
| `--expect-failure` `REGEX` | pin: the base must fail with a message matching this |
| `--supersedes` `TEST_ID` | pin: a test of an edited test file whose old expectation the change replaces on purpose |
| `--redact-claim` | pin: store only the claim's hash, not its text |
| `--replace` | pin: replace a claim pinned with other settings |
| `--remove` | pin: unpin the named claim and forget its passports |
| `--base` `BASE` | the original code: this revision (default HEAD) |
| `--repeat` `REPEAT` | run: runs of the scenario on each side (default 2) |
| `--no-regressions` | run: skip the regression check (the claim then cannot be supported) |
| `--rerun` | run: do not reuse verify evidence for the regression check |
| `--keep-going` | run: run the regression check even when the scenario already rules the claim out |
| `--test-command` `CMD` | the project's test command, as for verify |
| `--sandbox` `SANDBOX` | run: where the tests execute (as for verify) (one of `auto`, `seatbelt`, `bwrap`, `podman`, `docker`) |
| `--image` `REF` | run: with podman/docker, a local image (never pulled) |
| `--workers` `WORKERS` | run: parallel test processes (default 4) |
| `--timeout` `TIMEOUT` | run: seconds per test process (default 300 for the scenario, verify's own for regressions) |
| `--format` `FORMAT` | report: the output format (one of `md`, `json`, `in-toto`) |
| `--out` `FILE` | report: write to this file |
| `--publish-pr` `N` | report: post the Markdown passport on pull request N with your `gh` (opt-in; a fresh passport only) |
| `--public-ok` | report --publish-pr: allow posting on a public repository |
| `--json` | machine-readable JSON output |

## `repo-ai privacy`

audit what repo-ai stores, where, and whether it is committed

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `audit` |
| `--json` | machine-readable JSON output |

## `repo-ai packet`

small, source-linked task briefing (locations, tests, constraints, blast radius)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `task` |  |
| `--format` `FORMAT` | one of `markdown`, `claude`, `json` |
| `--max-files` `MAX_FILES` |  |
| `--budget-tokens` `BUDGET_TOKENS` | hard cap (estimate; default 900) |

## `repo-ai review`

pre-PR change passport: what the diff touches, tests, risks, blind spots

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--changed` | uncommitted changes (default) |
| `--branch` `BASE` | changes since the merge-base with BASE |
| `--format` `FORMAT` | one of `markdown`, `json` |

## `repo-ai budget`

budget governor: always-loaded and per-prompt context, limits (estimates)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--json` | machine-readable JSON output |
| `--check` | exit 1 when over budget |

## `repo-ai capabilities`

capability coverage map (no action), or the capability registry: list \| show \| prepare \| approve \| revoke \| run \| evidence; recommend \| candidates \| select are experimental

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | recommend \| candidates \| select are experimental (one of `list`, `show`, `recommend`, `candidates`, `select`, `prepare`, `approve`, `revoke`, `run`, `evidence`) |
| `ids` | capability ids |
| `--task` `TASK` | recommend (experimental) / run repo-ai.context: what you are working on |
| `--task-stdin` | read the task from stdin (at most 8000 bytes); keeps pasted text out of the shell |
| `--task-file` `PATH` | read the task from a file (at most 8000 bytes): the safest way for an agent to pass it |
| `--files` `A,B` | recommend / run: changed files (default: the working tree against --base) |
| `--no-changes` | recommend: ignore the working tree |
| `--base` `BASE` | compare the working tree with this revision (default HEAD) |
| `--executable` `PATH` | prepare / approve: the binary to bind (absolute path) |
| `--sha256` `PREFIX` | approve: the hash `prepare` printed |
| `--all` | revoke: every approval; candidates/select (experimental): every record |
| `--deny` `C,C` | recommend / candidates / select (experimental): rule out capabilities (no-network, no-exec, static-only, no-install, no-third-party); always enforced, only ever tightens |
| `--digest` `DIGEST` | select (experimental): the digest `candidates` printed |
| `--json` | machine-readable JSON output |

## `repo-ai performance`

repo-ai's measured effect here: hook, shortlist, sessions, experiments

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--json` | machine-readable JSON output |

## `repo-ai optimize`

(experimental) research proposals; --apply only what the Self-Improvement Governor allows

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `ids` | --apply: only these proposal ids |
| `--apply` | apply governor-approved tuning (journaled) |
| `--revert` `ID` | undo one journaled change (default: all active) |
| `--json` | machine-readable JSON output |

## `repo-ai friction`

friction radar: repeated, evidence-backed waste (same as learn friction)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--json` | machine-readable JSON output |

## `repo-ai quickstart`

where you are and what to run next

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai completion`

shell completion script: bash \| zsh \| fish

| Argument | Description |
|---|---|
| `shell` | one of `bash`, `zsh`, `fish` |

## `repo-ai orchestrate`

advise zero, one or a few read-only specialists for a task (spawns nothing)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `plan` |
| `task` |  |
| `--json` | machine-readable JSON output |

## `repo-ai graph`

evidence graph around a file, symbol:&lt;name&gt;, route:&lt;METHOD path&gt; or component:&lt;name&gt;

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `node` |  |
| `--depth` `DEPTH` |  |
| `--kind` `KIND` | only these edge kinds (repeatable) (one of `contains`, `defines`, `imports`, `tests`, `co_changes`, `uses`, `exposes`, `consumes_api`) |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai debug`

context flight recorder: what the prompt hook injected or omitted, and why

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `last`, `purge` |
| `-n` `N` | how many recent decisions (default 1) |
| `--json` | machine-readable JSON output |

## `repo-ai sandbox`

isolated execution backends for untrusted code: status \| pull

| Argument | Description |
|---|---|
| `action` | one of `status`, `pull` |
| `--toolchain` `TOOLCHAIN` | one of `python`, `node`, `java` |
| `--json` | machine-readable JSON output |

## `repo-ai eval`

Alias: `benchmark`.

paired coding-task evaluation (offline by default; --live is opt-in)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | coding: three-arm task-completion experiment (baseline,core,full); report/compare/regressions/list: read recorded experiments; ablate --feature X: full vs full-without-X (one of `coding`, `report`, `compare`, `regressions`, `ablate`, `list`) |
| `targets` | experiment ids (report/compare/regressions) |
| `--compare` `COMPARE` | coding: arms to run (baseline, core, full, full-&lt;feature&gt;) |
| `--feature` `FEATURE` | ablate: feature to remove from full |
| `--pilot` | coding: a small held-out pilot (6 tasks, 1 repeat) unless --tasks/--max-tasks |
| `--effort` `EFFORT` | coding: thinking effort, identical for every arm |
| `--resume` `EXPERIMENT` | coding: continue an interrupted experiment |
| `--results` `RESULTS` | coding: results directory (default: the lab home) |
| `--claude-config` `CLAUDE_CONFIG` | coding: dedicated Claude config dir (default: ~/.local/share/repo-ai/claude-eval) |
| `--sandbox` `SANDBOX` | coding: grading sandbox backend (one of `auto`, `podman`, `docker`, `bwrap`, `seatbelt`) |
| `--reserve-per-run` `USD` | coding: worst-case cost of one run for the budget gate (cap + its largest API call; default 1.25 x --max-cost-per-run) |
| `--blind` | coding: do not show pass/fail while running (pre-registered experiments) |
| `--fake` | coding: the --claude-cmd is a deterministic fake (no budget; results FAKE) |
| `--offline` | free, deterministic (default) |
| `--live` | run Claude Code (billable; needs --max-cost-usd) |
| `--suite` `SUITE` | task suite directory (default: the bundled suite) |
| `--tasks` `REGEX` | only task ids matching REGEX |
| `--max-tasks` `MAX_TASKS` | random sample of N tasks (seeded) |
| `--split` `SPLIT` | dev: tune on these; holdout: report only (by task id); final: the sealed test set, only when named (all = dev + holdout) (one of `all`, `dev`, `holdout`, `final`, `calibration`, `sealed-v2`) |
| `--seed` `SEED` | sampling and arm-order seed (default 0) |
| `--task-order` `TASK_ORDER` | coding: suite (task id order) or interleave (round-robin across bases, seeded; an early budget stop still covers every project) (one of `suite`, `interleave`) |
| `--concurrency` `CONCURRENCY` | parallel tasks (offline) |
| `--dry-run` | list what would run; run nothing |
| `--no-network` | guarantee no network use (offline only; rejected with --live) |
| `--no-validate` | offline: skip oracle validation |
| `--no-localization` | offline: skip localization |
| `--check` `BASELINE.json` | fail if worse than a saved offline report |
| `--max-cost-usd` `MAX_COST_USD` | live: total budget (required for --live) |
| `--max-cost-per-run` `MAX_COST_PER_RUN` | live: cap per Claude run, passed as --max-budget-usd (default 1.00) |
| `--max-turns` `MAX_TURNS` | live: turns per run (default 30) |
| `--timeout` `TIMEOUT` | live: seconds per run (default 900) |
| `--repeat` `REPEAT` | live: repetitions per task |
| `--model` `MODEL` | live: model alias or id (same for both arms) |
| `--claude-cmd` `CLAUDE_CMD` | live: Claude Code command (default: claude) |
| `--keep-artifacts` | live: keep workspaces |
| `--artifacts-dir` `ARTIFACTS_DIR` | live: where workspaces go (default: a temp dir) |
| `--out` `OUT` | also write the JSON report here |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai search`

lexical search over the index

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `terms` |  |
| `--limit` `LIMIT` |  |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai symbol`

find where a symbol is defined

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `name` |  |
| `--limit` `LIMIT` |  |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai related`

importers, imports, co-changes, tests of a file

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `file` |  |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai deps`

show declared dependencies

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `name` | filter by substring |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai architecture`

print ARCHITECTURE.md

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai overview`

print PROJECT_OVERVIEW.md

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai map`

print REPOSITORY_MAP.md

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai tests`

print TESTING.md

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai conventions`

print CONVENTIONS.md

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai hotspots`

print HOTSPOTS.md

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |

## `repo-ai learn`

(experimental) evidence-backed rules and outcome learning: status \| review \| explain \| approve \| reject \| rollback \| history \| shadow \| friction \| forget \| export

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--workers` `WORKERS` | parser threads (default: auto) |
| `--max-file-bytes` `MAX_FILE_BYTES` | skip files larger than this (default: 1500000) |
| `--git-history-days` `GIT_HISTORY_DAYS` | git window for hotspots (default: 365) |
| `--summarize` | add a narrative summary via `bob run` (sends facts, not code) |
| `--no-symbols` | skip AST parsing (much faster, less useful) |
| `--no-secrets` | disable the secret scanner (not recommended) |
| `--no-commit-context` | gitignore the generated docs instead of committing them |
| `--no-bob` | (v0.4 compatibility) skip Bob wiring |
| `action` | one of `status`, `review`, `explain`, `approve`, `reject`, `rollback`, `history`, `shadow`, `friction`, `forget`, `export` |
| `target` | rule id, event id, or `ranking` (the outcome prior) |
| `--what` `WHAT` | forget: which store (default all) (one of `episodes`, `signals`, `flight`, `ranking`, `all`) |
| `--older-than` `DAYS` | forget: only episodes older than DAYS |
| `--portable` | export: drop paths and repo specifics |
| `--force` | approve ranking: promote despite the shadow gate |
| `--apply` `ID` | apply a proposed rule |
| `--apply-safe` | apply every high-confidence safe proposal |
| `--reject` `ID` | reject a rule (not re-proposed unless its evidence changes) |
| `--explain` `ID` | show evidence for one rule (or all) |
| `--history` | list learning events |
| `--rollback` `EVENT` | undo a learning event |
| `--forget-signals` | delete locally recorded signals |
| `--all` | include retired rules |
| `--json` | machine-readable JSON output |

## `repo-ai skills`

skill lifecycle (experimental, except the read-only inventory and vet): list \| discover \| propose \| test \| diff \| promote \| disable \| rollback \| canary \| draft \| doctor \| inventory \| vet \| policy \| autopilot

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `list`, `discover`, `candidates`, `propose`, `test`, `diff`, `promote`, `generate`, `disable`, `rollback`, `canary`, `draft`, `doctor`, `audit`, `recommend`, `explain`, `install`, `portfolio`, `updates`, `compare`, `benchmark`, `health`, `enable`, `tournament`, `inventory`, `vet`, `policy`, `autopilot` |
| `names` |  |
| `--online` | allow network access: discover (Skill Radar), install of a remote skill, updates; off by default |
| `--providers` `PROVIDERS` | discover --online: providers to query |
| `--from-path` `DIR` | discover: vet a local skill directory |
| `--max-requests` `MAX_REQUESTS` | network request cap (default 60; vet: 400) |
| `--audit-limit` `AUDIT_LIMIT` | discover --online: candidates to quarantine and inspect (default 12) |
| `--vet-limit` `VET_LIMIT` | vet: skills to quarantine and inspect (default 200); any beyond it make the result incomplete (exit 3) |
| `--all` | audit: every quarantined candidate; disable --third-party: the kill switch; inventory: list every item |
| `--no-firewall` | inventory: skip the static firewall pass over installed skills |
| `--third-party` | disable: third-party skills |
| `--approve` `HASH` | install, enable, rollback: the content hash you reviewed |
| `--accept-review` | install: accept high-severity findings you have read |
| `--allow-scripts` | install, enable, rollback: the skill ships scripts |
| `--host` `HOSTS` | install: comma-separated hosts (default claude-code; codex, gemini-cli, antigravity and ibm-bob are export-only) |
| `--check` | updates: check upstream (network); inventory: exit 1 on a high-severity issue |
| `--max-cost-per-run` `MAX_COST_PER_RUN` | benchmark: cap per run |
| `--trial-tasks` `REGEX` | benchmark: task ids to use |
| `--trial-max-tasks` `TRIAL_MAX_TASKS` | benchmark: number of held-out tasks |
| `--trial-fake` | benchmark: use a fake client (tests) |
| `--trial-claude-cmd` `TRIAL_CLAUDE_CMD` | benchmark: Claude command (fake client in tests) |
| `--safe` | promote: every valid safe candidate |
| `--previous` | rollback: pin the previous version |
| `--apply` | canary: act on the decision |
| `--draft` | promote: activate the reviewed Tier-2 draft |
| `--dry-run` | draft: print exactly what would be sent; send nothing; install: show the diff and conflicts; autopilot: decide only |
| `--max-cost-usd` `MAX_COST_USD` | draft / benchmark: hard cap in USD (required for live use; billable) |
| `--json` | machine-readable JSON output |

## `repo-ai workflow`

compiled playbooks from verified workflows (read-only previews)

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `list`, `plan` |
| `name` |  |
| `--json` | machine-readable JSON output |

## `repo-ai registry`

opt-in cross-repo registry with isolated zones

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `add`, `list`, `inspect`, `remove`, `audit`, `purge`, `policy`, `contribute`, `suggest` |
| `--zone` `ZONE` | personal \| work \| &lt;name&gt; (zones never share data) |
| `--label` `LABEL` | add: display name (default: directory name) |
| `--move` | add: move from its current zone |
| `--set` `KEY=VALUE` | policy: llm=allow\|deny or patterns=on\|off |
| `--json` | machine-readable JSON output |

## `repo-ai pack`

Stack Packs: evidence-backed bundles from repositories in this repo's zone

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `list`, `show`, `plan` |
| `pack` | pack id (default: best match) |
| `--json` | machine-readable JSON output |

## `repo-ai crossrepo`

context or impact across repositories in this repo's zone only

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `context`, `impact` |
| `task` |  |
| `--json` | machine-readable JSON output |

## `repo-ai doctor`

diagnose installation and agent wiring

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--agent` `AGENT` | one of `claude`, `bob`, `all` |
| `--json` | machine-readable JSON output |

## `repo-ai uninstall`

remove what repo-ai created

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--agent` `AGENT` | default: all (one of `claude`, `bob`, `all`) |
| `-y`, `--yes` | do not ask for confirmation |
| `--dry-run` | list what would be removed; remove nothing |
| `--diff` | like --dry-run, with a unified diff of edited files |

## `repo-ai hook`

agent hook entry point (reads JSON on stdin)

| Argument | Description |
|---|---|
| `agent` | one of `claude` |
| `event` | session-start \| prompt \| post-edit \| stop \| post-bash \| post-bash-failure \| post-skill |

## `repo-ai why-test-failed`

explain recorded baseline/candidate test failures; no execution

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | individual candidate mission ID |
| `--test` `EXACT_ID` | filter to one recorded test identity |
| `--json` | machine-readable JSON output |

## `repo-ai futures`

experimental static/heuristic change futures across local and same-zone peers

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | optional mission ID whose write_paths will be analyzed |
| `--target-path` `PATH` | explicit relative source path to analyze |
| `--rehearse` | rehearse mission candidate diff against linked tests in an isolated sandbox |
| `--json` | machine-readable JSON output |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai apply`

apply a fresh verified mission diff to the working tree and verify post-apply state

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | verified mission or comparison ID |
| `--json` | machine-readable JSON output |

## `repo-ai shortlist`

evidence table for an abstained tournament; optional labelled policy preference; applies nothing

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | tournament comparison ID |
| `--policy` `POLICY` | strict (default) only lists candidates; smallest-diff additionally marks a POLICY_PREFERENCE (one of `strict`, `smallest-diff`) |
| `--json` | machine-readable JSON output |

## `repo-ai coverage`

map developer-declared requirements to the tests that observed them; no execution, never a correctness claim

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | single candidate mission ID |
| `--requirements` `FILE` | **required.** JSON {schema: repo-ai.requirements/1, requirements: [{text, kind: change\|preserve, tests: [ids]}]} |
| `--json` | machine-readable JSON output |

## `repo-ai undo`

restore receipt-owned applied bytes; refuse later user edits

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | applied candidate mission ID |
| `--json` | machine-readable JSON output |

## `repo-ai demo`

run a zero-cost simulated local acceptance demo in an empty directory

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--directory` `DIR` | **required.** new or empty directory for the demo |
| `--language` `LANGUAGE` | one of `python`, `node` |
| `--tournament` | compare a superficial fix against a valid fix |
| `--json` | machine-readable JSON output |

## `repo-ai mission-eval`

run deterministic zero-cost Reality Engine vs naive baseline protocol

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `--directory` `DIR` | optional directory to persist eval-report.json |
| `--json` | machine-readable JSON output |

## `repo-ai do`

plan an outcome offline; run an isolated replay or authorized live provider candidate

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `task` | the outcome you want, in plain language |
| `--dry-run` | plan only (the default); no persistent repository writes |
| `--run` | authorize local sandboxed tests and candidate edits in a disposable worktree |
| `--allow-live-provider` | authorize live external coding agent invocation in an isolated worktree |
| `--from-handoff` `FILE` | continue an interrupted/failed mission from a verified handoff capsule JSON file |
| `--apply` | apply the candidate diff to the working tree after fresh PASS verification |
| `--json` | machine-readable JSON output |
| `--agent` `AGENT` | one of `auto`, `none`, `replay`, `codex`, `claude`, `gemini`, `bob`, `agy`, `opencode`, `opencode-acp` |
| `--replay` `FILE` | explicitly simulated bounded JSON edit proposal; never a live agent |
| `--provider-executable` `FILE` | local non-billable provider executable for contract simulation |
| `--candidate` `FILE` | opt-in tournament: repeat for 2–3 isolated simulated proposals |
| `--tournament` `A,B[,C]` | live tournament: independent candidates from 2-3 providers; abstains unless exactly one distinct candidate passes |
| `--allow-write` `PATH` | allow one source path in the isolated candidate |
| `--max-cost-usd` `MAX_COST_USD` | explicit cost ceiling; default zero; replay requires zero |
| `--max-parallel` `MAX_PARALLEL` | ceiling 1–4; P0 executes one writer sequentially |
| `--max-seconds` `MAX_SECONDS` | wall-clock limit per provider run (default: 120) |
| `--test-command` `TEST_COMMAND` | one of `python -m pytest`, `node --test` |
| `--expect-fix` `TEST` | a test id the task must fix (repeatable; e.g. tests/test_x.py::test_y). With it, tests that already fail at the base and are not declared may keep failing; they are listed, and the result is PASS_WITH_PRE_EXISTING_FAILURES, never a plain whole-suite PASS |
| `--role` `ROLE` | opt-in separate read-only provider process; refused for trivial changes; advisory, never a verdict (one of `investigator`, `adversary`) |
| `--resume` `ID` | inspect/recover an interrupted checkpoint; no automatic model retry |

## `repo-ai agents`

local provider availability; doctor runs sandboxed help/version only

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `list`, `doctor`, `route`, `authorize`, `revoke`, `setup`, `catalog` |
| `provider` | provider name for authorize/revoke/setup |
| `--prefer` | with authorize: also prefer this provider in routing |
| `--allow-live-provider` | route: evaluate as if this run were authorized |
| `--max-cost-usd` `MAX_COST_USD` | route: require an enforceable USD ceiling when &gt; 0 |
| `--json` | machine-readable JSON output |

## `repo-ai mission`

inspect, cancel or recover local mission checkpoints

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `action` | one of `list`, `status`, `cancel`, `resume` |
| `id` | mission ID (list takes none) |
| `--json` | machine-readable JSON output |
| `--run` | explicitly resume a recoverable isolated replay attempt |
| `--replay` `FILE` | same proposal bytes as the interrupted mission |

## `repo-ai why`

local mission why; no provider disclosure

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | mission ID |
| `--json` | machine-readable JSON output |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai trace`

local mission trace; no provider disclosure

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | mission ID |
| `--json` | machine-readable JSON output |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai handoff`

local mission handoff; no provider disclosure

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | mission ID |
| `--json` | machine-readable JSON output |
| `--format` `FORMAT` | one of `text`, `json` |
| `--to` `TO` | optional target provider for local handoff adaptation (one of `none`, `replay`, `codex`, `claude`, `gemini`, `bob`, `agy`, `opencode`, `opencode-acp`) |
| `--verify` `FILE` | verify a local handoff capsule JSON file against current repository state |

## `repo-ai replay`

local mission replay; no provider disclosure

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | mission ID |
| `--json` | machine-readable JSON output |
| `--format` `FORMAT` | one of `text`, `json` |

## `repo-ai compare`

local mission compare; no provider disclosure

| Argument | Description |
|---|---|
| `-C`, `--path` `DIR` | repository directory (default: cwd) |
| `-v`, `--verbose` | more detail; on an error, print the traceback |
| `-q`, `--quiet` | less output |
| `id` | mission ID |
| `--json` | machine-readable JSON output |
| `--format` `FORMAT` | one of `text`, `json` |
