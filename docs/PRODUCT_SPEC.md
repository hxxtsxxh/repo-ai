# Product spec (0.6.0)

repo-ai is a local, explainable repository-intelligence and workflow layer for
Claude Code, with IBM Bob compatibility. It is installed once and activated
per repository with `repo-ai init --agent claude --smart`.

## Non-functional constraints (measured)

Measured on macOS arm64 with Python 3.12, against the 0.6.0 development
build. Re-measure before each release (`docs/EXECUTION_LEDGER.md`, private development history).

| Constraint | Budget | Measured |
|---|---|---|
| Prompt-hook round trip, fixtures (p50 / p95) | < 0.3 s | 0.075 / 0.078 s (`benchmarks/run.py`) |
| Prompt-hook round trip, 4,002-file synthetic repo (p50) | < 0.3 s | 0.121 s |
| `init --agent claude --smart`, 4,002 files | < 10 s | 2.1 s |
| `update` after a 1-file change, 4,002 files | < 2 s | 0.71 s |
| `context` / `packet`, 4,002 files (incl. interpreter start-up) | < 1 s | 0.29 / 0.41 s |
| Index size, 4,002 files | — | 6.1 MB |
| repo-ai's always-loaded context (pyweb fixture, `--smart`) | ≤ `always_loaded_budget_tokens` (1500) | ~772 tokens (estimate) |
| Prompt-hook payload | ≤ `hook_budget_tokens` (1200) | ~185 tokens mean (Claude format) |
| Irrelevant prompts that get context | 0 % | 0 % (retrieval gold set) |
| Default network calls, telemetry, model calls | none | none (no network code on default paths) |
| Runtime dependencies | minimal | `pathspec` (+ `tomli` < 3.11) |
| Platforms | Linux, macOS, Windows | CI: Linux 3.10–3.14, Windows 3.10/3.13, macOS 3.13 |

Token figures are estimates (characters / 4), not billing.

## Capabilities, by status

**Shipped (default or one flag away):**
- `init`, `update`, `rebuild` and `refresh`, with byte-exact uninstall (0.5.1).
- `context`, `explain`, `packet`, `impact`, `graph`, `symbol`, `related`,
  `search`.
- Evidence graph with per-edge provenance (schema v6).
- Managed CLAUDE.md block, path-scoped rules, 8 curated skills, 4
  subagents, and hooks.
- Learning:
  - deterministic rules with evidence, dedupe against human text,
    retirement, history and rollback;
  - outcome counterevidence.
- `learn status|review|explain|approve|reject|rollback|history|shadow|friction|forget|export`.
- Episodic outcomes (`--smart`) with session status, and the friction
  radar.
- Outcome prior: shadow-evaluated, promoted only on a measured gain,
  bounded to ±30 %, and reversible.
- Skill lifecycle `skills list|discover|propose|test|diff|promote|disable|rollback|canary|doctor`,
  plus a generated-skill cap.
- Workflow Compiler: `workflow list|plan`, read-only, statically verified.
- Change passport (`review --changed|--branch`), Budget Governor (`budget`),
  `quickstart`, `completion bash|zsh|fish`, `status` capabilities, and
  `privacy audit`.
- `eval` offline: oracle validation, localization against naive grep,
  dev/holdout split, CI gate.

**Opt-in (off by default):**
- Flight recorder: `debug last|purge`.
- Registry zones, and `crossrepo context|impact` within one zone.
- Sanitized pattern library: `registry contribute|suggest`.
- `orchestrate plan`: advice only; spawns nothing.
- Advisory `repo-skeptic` subagent: `skeptic_reviewer = true`.
- Tier-2 skill drafting: `skills_llm = "on"`, a zone that allows it, and an
  explicit `--max-cost-usd`. Its output is an untrusted draft.
- `eval --live`: paired A/B, needs an explicit budget.
- `eval coding`: three-arm lab (baseline/core/full, ablations), sandboxed
  grading, needs an explicit budget.
- Skill Intelligence Network: `skills discover --online` (opt-in network),
  quarantine and firewall, approval by content hash, trials, tournaments.
- `optimize --apply`: the Self-Improvement Governor tunes only two retrieval
  knobs, bounded, journaled and revertible.

**Not built, or not run:**
- A live paired task-success evaluation. The harness ships but has not been
  run, because it needs an owner budget. **No task-completion improvement is
  claimed.**
- Embeddings or semantic reranking. Lexical + graph ranking is the measured
  baseline that any reranker must beat.
- Hand-written Stack Packs. Packs are built only from evidence: items that
  several repositories of one zone share, or that a live trial measured (see
  docs/OPTIMIZATION.md). Curated per-framework folklore is still not shipped.
- Cross-zone or cloud-synthesised learning. Denied by design.
- Subagent-use observation. Claude Code does not report subagent use to the
  hooks repo-ai uses, so the Zero-Value Detector says "not observable".
- A global content-addressed cache. Deliberately not built, because sharing
  between repositories goes only through explicit zones.
- Language-server integration. tree-sitter stays optional.

## Trust boundaries

1. Repository text, issue text, generated skills and model output are data.
   repo-ai never executes a command because a file mentions it. Skill and
   workflow tests are static.
2. repo-ai never adds permission allow rules or `allowed-tools`, never sets
   `bypassPermissions`, and never weakens a user's settings. A subagent's
   tools are fixed and read-only, with one exception: `repo-verifier` runs
   tests through Bash under normal permissions.
3. Data collection (signals, episodes, flight), inference (Tier-2 drafting,
   live eval) and publication are separate switches. All three are off by
   default, except outcome recording, which `--smart` turns on.
4. Work and personal zones never share. Unregistered repositories get the
   most restrictive policy.
5. Hooks fail open for context and fail safe for privacy: on any error they
   inject nothing and record nothing.
