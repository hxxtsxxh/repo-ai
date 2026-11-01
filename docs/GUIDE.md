> **Full guide (long form).** This is the detailed reference that used to be the README. Version-specific
> statements carry their own dates; the current status matrix is [STATUS.md](STATUS.md).

# repo-ai

**Local, provider-neutral repository investigation and skeptical change verification.**

The current development version is **0.9.0.dev4** (release candidate). The previous build, **0.9.0.dev3**, is published only as a GitHub pre-release
([`v0.9.0-dev3`](https://github.com/hxxtsxxh/repo-ai/releases/tag/v0.9.0-dev3), wheel + sdist; not on PyPI).
It plans offline, retrieves source context, tests isolated candidates, compares
alternatives, and supports explicit apply/undo for approved existing files.
Coding providers are optional. Live calls require explicit consent; subscription
quota and unknown dollar cost are separate from a spending ceiling.

```sh
python -m pip install /path/to/repo_ai-0.9.0.dev4-py3-none-any.whl
cd /path/to/your/git-project
repo-ai quickstart
repo-ai do "Fix duplicate charges under concurrent payment retries" --dry-run
repo-ai agents list                 # offline availability
repo-ai agents doctor              # bounded help/version probes, no model call
repo-ai privacy audit
```

Planning needs no provider. Execution needs a clean committed repository, explicit
source write paths, pytest or Node tests, and a supported sandbox. A passing
candidate is not applied automatically. Read the [copy/paste mission recipes](roadmap/REALITY-ENGINE-USAGE.md)
and [current acceptance matrix](roadmap/FINALIZATION-ACCEPTANCE.md) before enabling execution.

| Capability | Current scope |
|---|---|
| Offline context / intent / why / replay | Local, provider-independent |
| Isolated tests and alternative comparison | pytest or Node; incomplete evidence abstains |
| Apply / undo | Explicit, receipt-backed existing regular file updates; refuses conflicts |
| Handoff | Checksummed local-store receipt (integrity, not authentication). A carried partial diff is accepted only if stored observations show a fixed baseline failure, no regressions and a remaining failure; it is re-verified from the frozen base. Cross-provider transfer demonstrated once live (agy → Codex, constructed scenario, n=1) |
| Live providers | Bob, Codex CLI and Antigravity (`agy`, macOS only) each produced a model-generated, independently re-verified change through `repo-ai do` here (small tasks, n≥2 each; costs UNKNOWN for Codex/agy). Claude: not usable in repo-ai's scratch HOME (login is not a copyable file; a weekly usage limit was also observed). Gemini: rejected for the tested account |
| `--role investigator|adversary` | Opt-in. Separate read-only provider processes; same provider as the implementer, so not independent review; advisory only |
| Team agents, skill benefit, causal debugging | Experimental or not demonstrated |
| Comparative model benefit | NOT_YET_DEMONSTRATED |

This is not a qualified release. ProofLab remains uncertified with known false
proofs. The older [0.8.0rc1 record](release/RC1.md) and historical test results
apply only to their stated revisions. No hosted service or daemon is required.

## First run

```sh
cd /path/to/any/git-project
repo-ai init --agent claude   # index the repository and wire Claude Code (core set)
repo-ai verify                # read-only: what your uncommitted change touched, which tests can show a break
repo-ai verify --run          # run those tests sandboxed, in a disposable copy of the working tree
claude                        # start (or restart) Claude Code here
```

Without an agent, `repo-ai init --agent none` gives you the index and its
commands (`context`, `impact`, `search`, `related`, `review`) and `verify`. It
builds the index and its generated docs under `.repo-ai/` (plus a
`.gitignore` block), and writes no `CLAUDE.md`, skills or hooks.

`repo-ai uninstall --agent claude --dry-run` shows exactly what removing the
Claude Code wiring would delete.

No daemon, no MCP server, no embeddings. No network calls unless you ask
for one: mission execution with `--allow-live-provider`, `repo-ai skills discover --online`, `repo-ai skills vet --online`,
`repo-ai skills install --online` and `repo-ai skills updates --online`
(GitHub), `repo-ai prove report --publish-pr` (posts through `gh`), and
`repo-ai sandbox pull` (container images). Runtime
dependencies: `pathspec`, plus `tomli` on Python 3.10.

What is stable, experimental or unsupported, with the evidence for each:
[docs/STATUS.md](STATUS.md).

## `repo-ai prove` (experimental): did the change do what it claims?

Pin a claim and an acceptance test, and ProofLab runs the same test bytes against the original code and the
change, in verify's sandbox. It checks the change for regressions, including ones hidden by editing or skipping
existing tests, and writes a verification passport for the pull request. It says what it does not establish.
See [docs/PROOFLAB.md](PROOFLAB.md).

```sh
repo-ai prove pin --claim "mean([]) returns 0" --scenario tests/test_accept.py --subject src/stats.py   # before fixing
repo-ai prove plan        # read-only
repo-ai prove run         # sandboxed
repo-ai prove report --out .repo-ai/proof.md
```

## `repo-ai verify`: the consequences of a change, checked safely

`repo-ai verify` works with or without an agent. It answers three questions
about your change:
- What did it touch?
- Which tests can show whether it broke something, and how sure is that?
- What did running them actually show?

Tests run sandboxed in a **disposable copy** of your working tree, never in
it. It runs the selection or the project's whole suite, whichever measured
times say finishes first. It attributes failures from per-test reports
rather than re-running files. It tells new failures from ones already at the
base, comparing like with like.

```sh
repo-ai verify            # read-only: changed code units, selected tests with evidence, confidence, the command
repo-ai verify --run      # run them in a disposable copy; new failures vs. failures already at the base
repo-ai evidence          # does the last result still cover the working tree?
repo-ai verify --record   # optional, once: record which code each test executes (sharper selection)
```

**Capability status:**
- **Stable candidate:** the plan, isolated execution and the base comparison;
  qualification is limited to the scope and builds in the release manifest.
- **Experimental:**
  - the adaptive run shape, per-test attribution, caches and evidence reuse;
  - zero-config command inference and `--image`;
  - the agent gate.

Details are in [docs/VERIFY.md](VERIFY.md) and the threat model in
[docs/VERIFY-THREAT-MODEL.md](VERIFY-THREAT-MODEL.md).

**Measured offline:** Session A's frozen held-out-7 evaluation of `903984a`
covered five pytest and `node --test` projects in podman containers.
- **Correctness:** zero false assurances in 127 failing states, no new failure
  classified as pre-existing, no false alarms, and 96.7% runtime no-miss.
- **Integrity:** the working tree was unchanged in 234 of 234 runs.
- **Performance:** slower than the native suite on three of five projects
  (1.44–2.31×); no general speed advantage. Hanging node tests settled in
  about 36 seconds.
- **Limits:** this is evidence for the evaluated build and container scope,
  not exact-candidate CI or demonstrated benefit to coding agents. See the
  [release manifest](release/RC1.md) for changes and additional checks.

## Why, when Claude Code already has search, LSP and memory

Claude can grep and read anything. What it lacks at the start of a task is a
cheap answer to *where to look first in this repository*. Without one, it
spends tokens and turns exploring, and the files it reads are not always the
ones that matter.

repo-ai precomputes the structure Claude would otherwise rediscover on every
task:

* the import graph, with aliases, monorepos and Python submodules;
* test-to-source links;
* routes;
* entrypoints;
* git churn, recency and co-change history;
* declared commands;
* generated and quarantined paths.

From that it answers with a ranked shortlist **only when it has evidence**.
Off-topic prompts get nothing injected.

**Before** — "fix the login validation bug: users with a valid email are
rejected" starts with Claude listing directories and grepping for "login".

**After** — the prompt arrives with this already attached (about 185 tokens):

```
<repo-ai-context confidence="high" task="auth, bug">
Files likely relevant to this request (ranked by repo-ai; read the line ranges first, verify before relying on them):
1. app/auth/login.py:1-24 — Login flow: credential validation and token issuance. (keyword match; auth path; imports tokens.py)
2. app/auth/tokens.py — JWT issuance and verification. (keyword match; auth path; imported by login.py)
3. app/api/users.py:5-17 — User endpoints. (keyword match; auth path; imports login.py)
4. tests/test_login.py:1-8 (keyword match; auth path; imports login.py)
...
Verify with: `pytest tests/test_login.py`
</repo-ai-context>
```

Measured on the bundled benchmark against v0.4.0:

| Metric | v0.4.0 | v0.5.0 |
|---|---|---|
| recall@5 | 0.875 | 1.0 |
| MRR | 0.822 | 0.875 |
| Irrelevant prompts that get context injected | 100% | 0% |
| Prompt-hook round trip p50 | — | 67 ms |

The gold set is small; the methodology and caveats are in
[docs/RETRIEVAL.md](RETRIEVAL.md).

## Install

repo-ai is not on PyPI. Install from GitHub or from a local clone:

```sh
pipx install 'git+https://github.com/hxxtsxxh/repo-ai.git'
pipx install /path/to/repo-ai                  # local clone
# or: uv tool install /path/to/repo-ai
repo-ai --version
```

**Trying 0.9.0.dev4 next to an existing install.** If `repo-ai --version` already
prints an older version (for example 0.7.x from an earlier `pipx install`), do not
overwrite it to test a development build. Install the build under a different
command name; both then coexist:

```sh
pipx install --suffix=-dev /path/to/repo_ai-0.9.0.dev4-py3-none-any.whl   # or a local clone
repo-ai-dev --version        # 0.9.0.dev4
repo-ai --version            # your existing install, unchanged
```

`repo-ai doctor` warns when the `repo-ai` on `PATH` differs from the one running.
Hooks written by `init` call `repo-ai` by name, so they use whichever version is on
`PATH`. To switch for good, run `pipx install --force` on the new build (this
replaces the old one). Checked with the 0.9.0.dev0 wheel (same mechanism in dev1) under an isolated `PIPX_HOME`.

The `repo-ai` executable must be on `PATH`. Hooks call it by name, and do
nothing if it is missing. Optional, for higher-fidelity non-Python symbols:
`pipx inject repo-ai 'tree-sitter>=0.23' 'tree-sitter-language-pack>=0.7,<1.0'`.

## Per repository

```sh
repo-ai init --agent claude                # Claude Code, core set (the recommended start)
repo-ai init --agent none                  # index and docs only: enough for `repo-ai verify`
repo-ai init --agent both                  # Claude Code + IBM Bob, no duplicated guidance
repo-ai init                               # v0.4 behaviour: IBM Bob only
repo-ai init --agent claude --dry-run      # show what would change (--diff for a patch)
repo-ai init --agent claude --local-only   # personal: settings.local.json, all outputs gitignored
repo-ai init --agent claude --smart        # experimental: self-maintenance (below)
repo-ai init --agent claude --feature-set full   # adds subagents; no benefit shown (Option A, below)
```

Re-running `init` never duplicates anything and never edits human text. On an
unchanged tree it is byte-identical (this is tested).

**What `--smart` means (experimental: no benefit has been shown).** For keys
your config file does not already set, it turns on:

* `learning_policy = "safe-auto"`: high-confidence, evidence-backed rules are
  applied to repo-ai-owned blocks and files only;
* `skills_mode = "auto"`: validated repo-specific skills are generated, and
  risky ones are written manual-only;
* `learning_signals = "outcomes"`: minimal local signals and per-session outcomes (which files were
  suggested and edited, whether a known test passed afterwards); never prompts,
  output or unknown commands.

It does not authorise repo-ai to edit source code, run deploys, push, or spend
money on LLM calls. See [docs/LEARNING.md](LEARNING.md).

### What Claude Code gets

* A **marked block in `CLAUDE.md`** (about 200–300 tokens): declared commands,
  repo-wide learned rules, how to ask for context, and boundaries.
* **Path-scoped rules** in `.claude/rules/repo-ai-*.md` (`paths:` front
  matter), for example test conventions that load only when Claude touches tests.
* **Skills:**
  * curated: `/repo-orient`, `/repo-locate`, `/repo-impact`, `/repo-verify`,
    `/repo-debug`, `/repo-review`, and the manual-only `/repo-learn`, `/repo-pr` and experimental `/repo-prove`;
  * generated per repository, only with `skills_mode = "auto"` (set by
    `--smart` or `--feature-set full`): `/repo-add-endpoint`, `/repo-tests`,
    `/repo-add-component`, and the manual-only `/repo-db-migration` and
    `/repo-release`;
  * manual-only management commands, which cost no always-loaded context:
    `/repo-capabilities`, `/repo-performance`, `/repo-optimize`,
    `/repo-discover-skills`, `/repo-skill-audit`, `/repo-skill-recommend`
    and `/repo-skill-evaluate`.
* **Subagents** (only with `--feature-set full`; the default core set installs
  none): `repo-explorer`, `repo-impact-analyst`, `repo-verifier`, and a
  shell-less `repo-security-reviewer`.
* **Hooks**, merged into `.claude/settings.json` without touching your
  entries or permissions. Prompt context is gated by confidence. Edits mark
  the index dirty. A debounced, lock-protected background refresh runs on
  `Stop`. SessionStart reports freshness. An opt-in completion gate on `Stop`
  (`verify_gate = true`) asks the agent to run `repo-ai verify --run` once per
  unverified change; it is experimental and its effect on agents is unmeasured.

Details, hook contracts and verification steps: [docs/CLAUDE_CODE.md](CLAUDE_CODE.md).

## Lifecycle

```
init ──► index (.repo-ai/state) + docs (.repo-ai/context) + agent wiring
  │
claude session:
  SessionStart ─► freshness line (stale? background refresh)
  each prompt  ─► ranked shortlist, or nothing
  edits        ─► .dirty marker
  Stop         ─► debounced `repo-ai refresh` (incremental update)
                    └─► learning cycle: rules/skills re-derived from evidence;
                        stale ones retired; changes recorded with rollback snapshots
```

## Everyday commands

```sh
repo-ai packet "fix auth token refresh"    # task briefing: locations, tests, constraints, blast radius
repo-ai context "fix the login bug"        # ranked shortlist (--format json|paths|claude, --scope diff)
repo-ai explain "fix the login bug"        # why each file ranked (score breakdown)
repo-ai impact --changed                   # blast radius of your diff + focused tests
repo-ai review --changed                   # pre-PR change passport (evidence, not approval)
repo-ai graph app/auth/login.py            # evidence graph with provenance (also symbol:/route:)
repo-ai status                             # freshness + active capabilities (exit 2 when stale)
repo-ai doctor --agent claude              # wiring, hook latency, Claude's own validator
repo-ai learn status | review | friction   # what repo-ai learned, why, and repeated waste
repo-ai skills list | discover | test | promote | canary
repo-ai workflow list | plan <name>        # compiled playbooks (read-only previews)
repo-ai orchestrate plan "<task>"          # zero/one/few read-only specialists (advice only)
repo-ai budget                             # always-loaded and per-prompt context (estimates)
repo-ai capabilities                       # coverage map: gaps -> skills/agents -> measured benefit
repo-ai performance                        # what repo-ai measurably did here ("not recorded" otherwise)
repo-ai optimize [--apply|--revert]        # research proposals; governor-bounded tuning
repo-ai skills discover --online           # Skill Radar: vetted third-party skills (network, opt-in)
repo-ai skills recommend | audit | install <name> --approve <hash>
repo-ai pack list | plan                   # Stack Packs from repos in this repo's zone
repo-ai sandbox status                     # execution sandbox backends for grading
repo-ai privacy audit                      # every store, where, committed or not
repo-ai debug last                         # what the prompt hook injected/omitted (opt-in recorder)
repo-ai quickstart                         # where you are and what to run next
repo-ai completion bash|zsh|fish           # shell completion script
repo-ai uninstall --agent claude --dry-run # exactly what would be removed
```

Cross-repository features are opt-in, by zone (`repo-ai registry`,
`repo-ai crossrepo`): see [docs/CROSSREPO.md](CROSSREPO.md). The skill
lifecycle, workflows and orchestration are in [docs/SKILLS.md](SKILLS.md).
Third-party skills (radar, firewall, portfolio, trials):
[docs/SKILL_NETWORK.md](SKILL_NETWORK.md). The coding lab and sandbox:
[docs/CODING_LAB.md](CODING_LAB.md). Optimisation, the governor and Stack
Packs: [docs/OPTIMIZATION.md](OPTIMIZATION.md).

## Capabilities and skills

```sh
repo-ai skills inventory                   # every skill, plugin, hook and MCP server Claude Code loads here
repo-ai skills vet <github-url> --online   # pin, quarantine and inspect a skill before anyone installs it
repo-ai capabilities list                  # the curated registry and each record's lifecycle state
repo-ai capabilities candidates --task-file task.txt --deny no-network   # experimental
```

* **`skills inventory`** is offline and read-only: nothing is run, enabled or
  changed.
* **`skills vet`** resolves the source to a pinned commit, copies it into
  quarantine and inspects it as text. It installs and runs nothing, and needs
  `--online` for a GitHub URL. Licences are parsed as whole SPDX expressions;
  restricted or unrecognised licences block install.
  **Plugin inspection is experimental:** its fresh, preregistered validation
  failed, and a plugin is never reported as safe (`review` at best).
* **`capabilities`** is a curated registry of 15 records with separate
  lifecycle fields (reviewed, approved, available, invoked, validated). The
  one adapter that runs a local binary, the ruff security adapter, needs your
  own approval in a terminal: `approve` refuses without one, or when an agent
  or CI marker is set. That is defence in depth; Claude Code's permission
  prompt is the real boundary.
* **`capabilities recommend` and `candidates` / `select` are experimental.** A
  fresh preregistered evaluation failed: top-3 recall 0.385 against a gate of
  0.80. Constraints written in the task text are detected only partly, so
  pass them with `--deny`, which is always enforced.

Details: [docs/SKILL_NETWORK.md](SKILL_NETWORK.md) and
[docs/CAPABILITIES.md](CAPABILITIES.md). Status and evidence:
[docs/STATUS.md](STATUS.md).

## Measured, and not yet measured

* **Offline task suite** ([docs/EVALUATION.md](EVALUATION.md)):
  * 59 synthetic tasks (dev and holdout splits);
  * a sealed `final` split of 25 re-injected upstream bugs in six real
    open-source projects.

  From the prompt alone, repo-ai ranks the files a fix must touch better
  than naive grep (recall@5 / all-gold@5 / MRR):
  * on the real-repository tasks: 0.853 / 0.800 / 0.606, against
    0.580 / 0.560 / 0.420 for grep;
  * on the synthetic holdout: MRR 0.574 against 0.520 for grep, but
    recall@5 is still below grep's (0.674 vs 0.735).
* **Task completion with Claude: no benefit shown.**
  * **The experiment:** a pre-registered, blinded experiment (Option A,
    v0.7.5; [results](../benchmarks/results/coding-option-a-v0.7.5.md)). It ran
    150 runs on 25 real-repository tasks with Sonnet 5.5.
  * **Success:** plain Claude 92%, repo-ai Core 90%, repo-ai Full 88%. Every
    difference is inconclusive (Holm p = 1.0), and equivalence was not shown
    either.
  * **Cost:** Full cost about 10% more, with no subagent or skill ever
    invoked.
  * **One harm found:** lint-only verification guidance on one task. 0.7.6
    fixes it ([CLAUDE_CODE.md](CLAUDE_CODE.md#verification-guidance-076)),
    and new installs default to Core. Whether that *helps* is unverified.
  * **Second test (exploratory, 0.7.7):** Core vs plain Claude on 25 fresh
    sealed-v2 tasks, one run each
    ([results](../benchmarks/results/coding-sealed-v2-pairs-v0.7.7.md)).
    * **Success:** plain 92%, Core 84%. The −8 points are inconclusive
      (95% CI −22 … +7).
    * **Efficiency:** cost, tokens, tool calls and runtime are
      indistinguishable.
    * **Mechanism:** Core's Verify line tripled how often the agent ran
      tests, without improving correctness.
    * **Verdict:** no correctness benefit has been shown on either task set.

## Safety and privacy

* Local only, with no telemetry. Repository content, prompts and indexes never
  leave the machine. The one exception is opt-in `--summarize` (Bob), which
  sends facts, never code.
* Secrets:
  * credential files (`.env*`, keys, `credentials.json`, kubeconfig,
    tfstate, …) are quarantined before they are read;
  * embedded private keys and AWS secret keys quarantine the file that
    contains them;
  * other findings are reported with a 4-character prefix and a length,
    never the value;
  * credentials in git remote URLs are redacted.
* Hostile input:
  * symlinks are never followed out of the repository;
  * control-character filenames are skipped;
  * `out_dir` cannot point outside the repository;
  * FTS queries are always quoted;
  * subprocesses use argument vectors with timeouts.
* Repository text is data, never instructions. Nothing found in a README,
  comment or prompt is executed.
* repo-ai never adds permission allow rules, never sets `bypassPermissions`,
  and never declares `allowed-tools` in skills.
* Hooks fail open: zero bytes and exit 0 on any error. They can never block a
  prompt.
* Everything repo-ai writes carries an ownership marker or sits inside a
  marked block. `uninstall` removes only that, keeps anything you edited, and
  supports `--dry-run`. Every overwritten file is backed up first.

## Token and cost behaviour

| Item | Cost |
|---|---|
| CLAUDE.md block | about 200–300 tokens per session |
| Skill descriptions | about 240 tokens for the default set's six model-invocable skills; the ten manual-only skills add nothing (measured with `repo-ai skills audit` on a fresh core install) |
| Prompt context | 0 tokens on irrelevant prompts; about 185 tokens on average for relevant ones (hard cap `hook_budget_tokens = 1200`) |
| SessionStart line | under 200 tokens |

repo-ai itself makes no model calls, except in these opt-in commands:
* `repo-ai eval --live` and `repo-ai eval coding` run Claude Code (billable;
  a real run needs an explicit, positive `--max-cost-usd`);
* skill trials (`repo-ai skills benchmark` and `tournament`) run Claude Code
  under the same budget rule;
* skill drafting (`repo-ai skills draft`) sends minimised evidence, never file
  contents, to Claude Code. It needs `skills_llm = "on"` and `--max-cost-usd`;
* `repo-ai init --summarize` runs `bob run`, which sends facts, never code.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No context appears in Claude | Restart the session (hooks load at start). Then run `repo-ai doctor --agent claude`. |
| Context appears but looks stale | `repo-ai status`, then `repo-ai update`. |
| Context still doesn't appear | `which repo-ai` from the shell Claude uses. |
| Results look off | `repo-ai explain "<task>"` shows the score breakdown. |
| Hook diagnostics needed | Set `REPO_AI_HOOK_DEBUG=1` before starting `claude`. |
| `settings.json is not valid JSON` | repo-ai will not overwrite it. Fix the JSON, then `repo-ai update`. |
| An index from a newer repo-ai | Upgrade repo-ai, or `repo-ai rebuild`. |

## Migrating from repo-ai 0.4 (Bob only)

Nothing moves: `.bob/context/` stays the docs and index location, and the
index migrates in place. Run `repo-ai init --agent claude` to add
Claude Code next to Bob. See [docs/COMPATIBILITY.md](COMPATIBILITY.md).

## Plugin (optional)

`integrations/claude-plugin/` is a Claude Code plugin with the same skills,
agents and hooks, and `.claude-plugin/marketplace.json` lists it:
`claude plugin marketplace add /path/to/repo-ai && claude plugin install repo-ai@repo-ai`.
You still run `repo-ai init` per repository, because that is where the index
comes from.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                      # unit + CLI integration + hooks + security
python benchmarks/run.py              # retrieval quality + latency vs benchmarks/results/
python scripts/build_plugin.py        # regenerate the plugin bundle
repo-ai eval                          # repo-ai's own bundled 59-task suite, offline and free (not your repository)
repo-ai eval coding --compare baseline,core,full --max-cost-usd 10 --dry-run   # 3-arm lab (billable when run)
```

`repo-ai eval` measures repo-ai itself: it validates the oracles of its
bundled task suite and measures localization on it. It does not evaluate the
repository you run it in.

Architecture: [docs/ARCHITECTURE.md](ARCHITECTURE.md) ·
Product spec: [docs/PRODUCT_SPEC.md](PRODUCT_SPEC.md) ·
Learning: [docs/LEARNING.md](LEARNING.md) ·
Evaluation: [docs/EVALUATION.md](EVALUATION.md) ·
Configuration: [docs/CONFIGURATION.md](CONFIGURATION.md) ·
Changes: [CHANGELOG.md](../CHANGELOG.md) · License: MIT

## Missions: `repo-ai do` (0.9.0 pre-release, experimental core)

```bash
repo-ai agents doctor                      # which agent CLIs exist; no model call, no code sent
repo-ai do "Fix duplicate charges under concurrent payment retries" --dry-run   # offline plan; the default
repo-ai do "..." --agent bob --allow-live-provider --run --allow-write payments.py --max-cost-usd 0.5
repo-ai why MISSION_ID                     # evidence, freshness, what was and was not checked
repo-ai apply MISSION_ID                   # re-verifies, then applies; repo-ai undo MISSION_ID reverts
repo-ai do "..." --tournament codex,agy --allow-live-provider --run --allow-write payments.py   # live; may abstain
repo-ai shortlist COMPARISON_ID --policy smallest-diff   # after an abstention: evidence table, applies nothing
repo-ai coverage MISSION_ID --requirements reqs.json   # your requirement->test map vs observed per-test outcomes
repo-ai handoff MISSION_ID --to bob --json > capsule.json   # then: repo-ai do --from-handoff capsule.json --agent bob ...
```

What a PASS means: the candidate was produced in an isolated worktree, it only touched the paths you allowed, and the
**enumerated checks** (your existing tests, run before and after in a sandbox, plus a regression run) passed. It does
**not** mean the change is correct: in our own study a Bob candidate passed repo-ai's visible-test oracle and failed a
requirement those tests did not state ([benchmarks/abc-v1/RESULTS.md](../benchmarks/abc-v1/RESULTS.md)). Write the
requirement as a test first if it matters.

`repo-ai coverage` makes that concrete: you declare (`repo-ai.requirements/1` JSON) which existing test pins each
requirement, and it checks the map against the baseline/candidate per-test outcomes recorded in the mission. A
requirement is `VERIFIED_FAIL_TO_PASS` only if its test failed before and passes after; a test that already passed
(`NOT_DISCRIMINATING`), a missing test, or a requirement with no test (`UNMAPPED`) is reported as such. The headline
`ACCEPTANCE_MAPPED_ALL` means every *declared* requirement is pinned by a discriminating test; `task_correct` is always
`CLAIM_UNVERIFIED`. It only knows the requirements you wrote down.

| Capability | Status |
|---|---|
| Platforms for `repo-ai do` | macOS (seatbelt) tested locally; Linux needs `bubblewrap` (tested in the `sandbox-bwrap` CI job); **Windows: unsupported for missions** (apply needs POSIX no-follow), the rest of repo-ai is unchanged |
| Offline plan, source lookup, `why`, `why-test-failed`, `doctor` | usable, no model needed |
| Live agent = **IBM Bob** (`--agent bob`) | works; hard USD cap enforced by Bob's `--max-cost`; cost is provider-reported |
| Live agent = Codex CLI | works (`--agent codex`): Codex runs under repo-ai's outer sandbox with its own sandbox bypassed (only when repo-ai confirmed the outer one); 8 abc-v2 cells and a handoff child produced verified changes; **cost UNKNOWN** (subscription auth) |
| Live agent = Claude Code | **Not supported live**: the login is not a copyable file, so repo-ai's scratch HOME cannot authenticate (repo-ai does not work around that); a weekly usage limit was observed earlier on the tested account; a single host-side `claude -p` probe on 2026-10-29 after the reset succeeded, which says nothing about repo-ai's isolated path. Do not depend on it |
| Live agent = Antigravity `agy` (macOS only) | works (`--agent agy`, headless `--print`, edits only, shell denied, never `--dangerously-skip-permissions`). Refused on other platforms. It must read the encrypted login keychain file to authenticate; the rest of HOME (incl. its conversation history) is unreadable to it. **Cost UNKNOWN** (tokens only) |
| Provider routing (`--agent auto`, `agents route/authorize/revoke`) | deterministic; outcomes `SELECTED` / `NOT_AUTHORIZED` / `NO_AGENT`; never falls back to an unusable provider. Does not check login or quota before a live run |
| Partial-work handoff (`handoff`, `--from-handoff`) | proven live Bob→Bob and **agy→Codex** (constructed scenario, n=1: validated partial diff re-verified from the frozen base). Checksum is integrity, not authentication |
| `apply` / `undo` | transactional, refuses on user edits, symlinks, scope or hash mismatch |
| Multi-candidate tournament | `--candidate` is **replay-only**. `--tournament A,B[,C]` is **live** (independent candidates from 2–3 providers, one frozen commit, identical tests). Exactly one distinct PASS wins; several distinct PASSes **abstain**. After an abstention, `repo-ai shortlist ID` prints an evidence table of the passing candidates; `--policy smallest-diff` adds a clearly labelled `POLICY_PREFERENCE` (a tie rule, not correctness). Nothing is ever applied automatically |
| Read-only `--role investigator/adversary` | experimental, advisory, same provider |
| `skills discover --online`, skill distillation, cross-repo futures | experimental / off by default |
| Benefit over plain provider use | **NOT_YET_DEMONSTRATED** (4 tasks, Bob only; no significance claim) |

Privacy: nothing is sent anywhere unless you pass `--allow-live-provider`; then the task text and the workspace files
the agent opens go to that provider under that provider's terms. Mission records stay in `<repo>/.repo-ai/`; provider
binary paths live in a 0600 sidecar and are not exported in handoffs. Records written by earlier dev builds may contain
absolute paths. Details: [usage and limits](roadmap/REALITY-ENGINE-USAGE.md), [ledger](roadmap/REALITY-ENGINE.md).
