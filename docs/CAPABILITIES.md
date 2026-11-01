# Capabilities: what can help with this task, and is it trusted?

`repo-ai capabilities` answers one question without an LLM: which capabilities help with the work in front of you, and what state is each in here? It draws on:
- repo-ai's own commands;
- approved local tools;
- a few vetted external ones.

It is not a marketplace. The registry is a small curated manifest (`src/repo_ai/capabilities.json`, 15 records), plus state computed on your machine. repo-ai never installs a tool, never writes Claude Code settings, hooks, MCP configuration or permission rules, and adds no always-loaded context.

## Quickstart

```sh
repo-ai capabilities list                       # every record and its lifecycle state
repo-ai capabilities show adapter.ruff-security # the full record

# experimental: see "Recommend" below
repo-ai capabilities recommend --task-file task.txt --deny no-network

# the one adapter that runs a local binary: a human approves it
repo-ai capabilities prepare adapter.ruff-security          # writes nothing; prints the hash (--executable PATH to pick a binary)
repo-ai capabilities approve adapter.ruff-security --sha256 <prefix>   # you, in a terminal
repo-ai capabilities run adapter.ruff-security --json       # findings on lines this change adds
repo-ai capabilities evidence --json                        # does the last result still describe this change?
repo-ai capabilities revoke adapter.ruff-security           # undo; nothing else changes
```

With no action, `repo-ai capabilities` prints the coverage map as before.
What is stable and what is experimental here: [STATUS.md](STATUS.md).

Inside Claude Code, `/repo-capabilities <what you are doing>` follows the agent loop below
(`candidates`, then `select`). The skill is manual-only, so it costs no context until you type it.
The agent contract is in [CAPABILITY-AGENT-CONTRACT.md](CAPABILITY-AGENT-CONTRACT.md).

## Lifecycle: six separate fields, never one status

| Field | Meaning | Source |
|---|---|---|
| `discovered` | the record exists | curated manifest |
| `reviewed` | someone read the source: `first-party`, `reviewed`, `discovered` or `not-reviewed` | manifest, with a reference |
| `approved` | `not-required` (built-ins), `approved` / `not-approved` (the ruff adapter), `not-applicable` (adapters with no implementation: semgrep, dependency-audit), `not-managed` (external tools you install) | `~/.local/share/repo-ai/repos/<id>/capabilities.json`, outside the repository |
| `available` | it can run here now, or why not: `needs repo-ai init`, `not_installed`, `not_approved`, `binding_changed`, `no_adapter`, `not_managed_by_repo_ai` | computed at read time |
| `invoked` | runs through repo-ai, and the last status | `~/.local/share/repo-ai/repos/<id>/capability-runs/runs.jsonl`, outside the repository (a clone cannot forge it) |
| `validated` | the last output matched its schema (`sarif-2.1.0`, `json-valid`) | run log; `measured_effect` is always `null` |

`validated` means the output was well-formed. It does **not** mean the capability helped an agent; nothing in the registry claims that.

## Recommend

**Experimental.** It failed its own recall gate (below), says so in every answer, and is not the
default experience: `repo-ai capabilities` with no action still prints the coverage map.

`recommend` is deterministic and offline, and runs no tool. The CLI reads git state; the matching
starts no process. It has two parts, kept apart:

1. **Discovery** (`capdiscovery`) proposes candidates. It works from a frozen facet lexicon of about 40
   general concepts (action, object, quality and symptom). An intent fires when two or three facets meet
   in the same or the next clause. Ambiguous words never fire alone. Changed files only strengthen
   evidence the text already gives, and stated constraints ("offline", "don't run anything", "only
   built-in tools") are detected as phrases.
2. **Trust gates** (`capselect`) decide what may be offered. A ranking never changes a gate:
   - language and front-end fit;
   - reviewed, pinned, approved and available;
   - the read-only command allowlist;
   - the task's constraints, which rule capabilities out entirely.

It returns at most three `recommended` items, with weaker matches listed under `consider`, which are
never recommended. Each item carries a need id (never the task's wording), what it adds beyond native
Claude Code, its availability, and a next step with no runnable install or approval command.

**Measured limits.**
- The first matcher was precise (0.91–0.93) and conservative (recall 0.43–0.58) on two 60-task
  corpora (`docs/research/capability-eval-2026-10.md`, private development history).
- The discovery redesign was measured once, on a fresh 120-task corpus, under a protocol frozen
  beforehand. It **failed**: top-3 recall 0.385 against a gate of 0.80, and shortlist recall@6 0.736
  (`docs/research/capability-discovery-C-2026-10/RESULTS.md`, private development history).
  It still beat both baselines: lexical 0.088, repository-only 0.286.
- **Stated constraints are detected only partly** (9 of 18). Pass them with `--deny`, which is always
  enforced, on `recommend`, `candidates` and `select` alike. The output separates `explicit`
  (`--deny`, authoritative) from `inferred` (from the task text, best-effort), and an unknown
  `--deny` class is an error rather than being ignored.
- After three unsuccessful passes, tuning of the deterministic matcher has stopped.
- Treat silence as "not recognised", not as "not useful".

**Task text is untrusted.**
- Pass it with `--task-file` or `--task-stdin` (at most 8,000 bytes of valid UTF-8) rather than on the
  command line.
- The JSON never echoes it: it carries `task_sha256` and need ids, not the matched wording.

## The agent menu: `candidates` and `select`

```sh
repo-ai capabilities candidates --task-file task.txt --deny no-network --json   # at most 6 gated candidates, a digest
repo-ai capabilities select <id|none> --digest <d> --task-file task.txt --deny no-network --json
```

Both take the same inputs as `recommend`: the task (`--task-file`, `--task-stdin` or `--task`), the
changed files (`--files A,B`, or the working tree against `--base`, or none with `--no-changes`) and
`--deny`. `select` must be given the same inputs as the `candidates` call whose digest it carries.

- **`candidates`:** a compact menu, at most 6 entries and 1,800 bytes. Each entry has only closed
  fields: id, kind, `gate` (`ready` or `human`), tier, fit codes, risk codes, availability and a
  curated "adds" line. Entries ruled out by a constraint are listed as `blocked`. `none` is always valid.
- **`select`:**
  - recomputes everything from scratch, and refuses a stale digest (exit 6) or an id not on the menu
    (exit 7);
  - on `ready`, returns the exact `argv`, built from manifest constants only;
  - on `human`, returns a fixed sentence for the user;
  - executes nothing, and a selection never counts as an invocation;
  - logs one line, without the task text, to `selections.jsonl` outside the repository.
- **`--deny`** takes a comma-separated list of `no-network`, `no-exec`, `static-only`, `no-install`
  and `no-third-party`. It only tightens; no input loosens a gate. An unknown class is an error (exit 2).

  | Class | Rules out |
  |---|---|
  | `no-network` | the semgrep and dependency-audit adapters, browser evidence, and an online `skills vet` |
  | `no-exec` (no repository code runs) | mutation testing, property testing and browser evidence. `repo-ai.verify` stays, as a plan only, because running tests needs your authorization. The ruff adapter stays too: ruff parses the code and never runs it |
  | `static-only` (no process beyond repo-ai's read-only commands) | the `no-exec` set, every `adapter.*`, and LSP references |
  | `no-install` | everything not available on this machine, except what only needs `repo-ai init` |
  | `no-third-party` | every `adapter.*` and `ext.*` |

- **`--all`** puts every record through the same gates, without the 6-entry and 1,800-byte limits. It
  never lifts a gate.

**External tools you add yourself.** For browser evidence, the reviewed pin is
`chrome-devtools-mcp` at commit `106d672`, run with `--isolated --no-usage-statistics`. You add the
MCP server yourself; repo-ai never prints or runs an install command.

## The ruff security adapter

`adapter.ruff-security` runs your installed ruff with a curated set of 51 stable flake8-bandit rules on the changed Python files.

**What it reports:**
- only findings on lines the change adds;
- findings on untouched lines as a `pre_existing` count;
- the raw SARIF, stored with its sha256 next to the run log, outside the repository.

**Trust model:**
- **Approval binds** the executable's real path, sha256, size, `--version` and the adapter definition. Any change blocks the run (exit 4) until you approve again.
- **The binary must live outside the repository.** Any path inside it is refused, git-ignored virtualenvs included, and containment is checked by file identity (case-insensitive file systems too). Relative, `.` and in-repository PATH entries are ignored.
- **What runs is what was hashed.** Each run copies the approved binary into a private 0700 directory, re-hashes the copy and executes the copy. A swap after the check does not run.
- **`approve` is refused** when stdin is not a terminal, or when any agent or CI marker is set, even
  to an empty value: `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_SSE_PORT`, `REPO_AI_IN_HOOK`,
  `REPO_AI_AGENT`, `CI` or `GITHUB_ACTIONS`. It also checks that `REPO_AI_HOME` is outside the
  repository. That is defence in depth: Claude Code's permission prompt is the real boundary, and
  **anything that can write your approvals file can approve.**
- **A self-test at approval** lints an empty file with the exact rule set, so a ruff that rejects a rule is refused then rather than at the first scan.
- **Every run is fixed:** fixed arguments (`check --isolated --no-cache --no-fix --ignore-noqa --output-format sarif --select … -- <files>`), a clean environment and a temporary `HOME`, a 60 s timeout. `--ignore-noqa` means a `# ruff: noqa` line in the scanned code cannot silence the scan.
- **Tool output is parsed into typed fields.** Unknown rules are dropped, and so are paths outside the repository. The tool's own message text is kept as `untrusted_message` (200 characters, control and invisible characters removed).
- **Every incomplete scan is an `error` (exit 5), never a clean result.** That covers:
  - a crash, a timeout or invalid SARIF;
  - a file that is not UTF-8;
  - a result for a rule repo-ai did not select, such as a syntax error;
  - a result without a location;
  - more than 5,000 results.

  "No changed Python files" is `nothing-to-scan`, which is also not a clean result.
- **Changed-line attribution is the adapter's own.** It counts the lines each diff hunk declares and
  runs git with `--text` and literal pathspecs. Every setting that could hide or shift lines (colour,
  context, prefixes, external diff) is overridden on the command line, and no `GIT_*` variable reaches
  git. User and system config are kept, because `core.autocrlf` decides how a Windows working tree
  compares with the base. So `.gitattributes`, colour or context settings, and file names that look
  like pathspecs cannot hide a new finding. A file that is new against the base counts as all new.

## Static-security evidence

`repo-ai capabilities evidence --json` returns the last ruff result **only while it still describes
this change**. It never runs anything. The result is `fresh` only if all of these hold:
- the run was validated;
- the same binary is still approved and bound, and the adapter is unchanged;
- the fingerprint matches: the base commit, plus the bytes and staged blobs of every changed Python
  file, `.claude/` hooks included;
- no changed Python file was skipped.

Otherwise the result is `stale`, `incomplete` or `none`, and the command exits 3. It is informational and never part of a
pass/fail verdict. This is the producer side of proposal P4 in
`docs/research/VERIFY-INTERFACE-PROPOSALS-2026-10.md` (private development history).

**What it is not:** a pattern lint, not dataflow analysis. Authorization, CSRF and logic flaws are invisible to it. The native `/security-review` is model-based and nondeterministic; this adapter is deterministic and offline.

## Built-in capabilities

`repo-ai capabilities run <repo-ai.*>` runs the corresponding public command (`impact --changed`, `verify` plan, `review`, `skills inventory`, `budget`, `context --task`) and records the JSON result. Test execution stays with `repo-ai verify --run`, which has its own sandbox and approval. Built-ins follow their own contracts: for example, `verify --json` never runs repository code but writes its scan cache under the repository's state directory (see `docs/VERIFY-AGENT-CONTRACT.md`). Writing nothing in the repository is the ruff adapter's guarantee: its temporary files, run log and SARIF live outside it.

## Rollback

- `revoke <id>` or `revoke --all` deletes only repo-ai's approval entries. The journal records the event.
- `repo-ai uninstall` deletes the approvals, the journal and the run log.
- Tests check that approve → run → revoke leaves the repository and `~/.claude` byte-identical, including through the CLI.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ran (or `nothing-to-scan`); findings, if any, are in the output. `evidence`: `fresh`. `candidates`: the menu. `select`: a `ready` choice or `none` |
| 2 | invalid input: an unknown `--deny` class; a task over 8,000 bytes, not UTF-8 or unreadable; a malformed id or digest; for `candidates` and `select`, a base that is not a commit |
| 3 | not approved or not available; `evidence` is not `fresh`; `select` chose a `human`-gated entry |
| 4 | the approved binary changed |
| 5 | the tool failed, or the scan was incomplete |
| 6 | `select`: the digest is stale (anything it covers changed since `candidates`) |
| 7 | `select`: the id is unknown, ruled out by a gate, or not on the menu |
