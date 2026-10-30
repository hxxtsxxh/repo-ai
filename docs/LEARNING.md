# Learning: evidence-backed rules and generated skills

repo-ai maintains project guidance it can **prove**. Every rule and every
generated skill comes from a deterministic extractor over the index, carries
pointers to its evidence (`path:line`), a confidence, a placement reason and a
version, and is retired when that evidence disappears. There is no free-form
LLM authoring in this release.

## What can change on its own

| Policy (`learning_policy`) | Rules | Safe generated skills | Risky generated skills |
|---|---|---|---|
| `off` | nothing | nothing | nothing |
| `suggest` (default) | proposed only — `repo-ai learn --apply …` | only via `repo-ai skills generate …` | only via `skills generate` |
| `safe-auto` (`--smart`) | high-confidence (≥ 0.8), deterministic, safe rules are applied | written | written **manual-only** (`disable-model-invocation: true`) |
| `manual-only-for-risky` | as safe-auto | written | never written automatically |

"Applied" means written into a **repo-ai-owned** place: the marked CLAUDE.md
block, or `.claude/rules/repo-ai-*.md`, or `.claude/skills/repo-*/`. repo-ai
never edits text outside its markers. It also never touches
`~/.claude/CLAUDE.md`, managed or enterprise policy, your own skills, or a
generated file you have edited (once the checksum differs, the file is yours).

What `--smart` sets, for keys your config file does not already set:
`learning_policy = "safe-auto"`, `skills_mode = "auto"`,
`learning_signals = "known-commands"`.

## Rule extractors

| Kind | Evidence | Placement | Confidence |
|---|---|---|---|
| `tests` | test files of a suite plus where its command is declared | `.claude/rules/repo-ai-testing.md`, `paths:` = suite root | 0.9 with ≥ 3 test files |
| `naming` | ≥ 12 sampled functions in one language, ≥ 85 % one style | `repo-ai-<lang>-style.md`, `paths:` = that language's files | 0.6–0.95 by sample size |
| `generated` | files classified generated (path pattern or banner) | `repo-ai-generated.md`, `paths:` = that directory | 0.9 |
| `lint` | lint command and the manifest/Makefile line declaring it | CLAUDE.md block | 0.85 |
| `boundary` | one-way imports between components (≥ 3, none back) | CLAUDE.md block | 0.6 — **always proposal only** |
| `generated-edits` | (signals) repeated edits to generated files | CLAUDE.md block | 0.85 |

Placement rule: a stable repo-wide invariant goes in CLAUDE.md; an invariant
for some paths goes in a path-scoped rule; volatile facts (file lists, counts)
never become instructions and stay in the index and the docs.

**Dedupe against humans.** Before applying, repo-ai reads your own
CLAUDE.md / CLAUDE.local.md / AGENTS.md text (outside its blocks) and your
non-repo-ai `.claude/rules`. If a rule is already stated there it is marked
`covered` and not added.

**No self-reference.** Evidence must point at repository content repo-ai does
not own. Its own directories are never scanned, managed blocks are stripped
before indexing, and every evidence pointer is checked again
(`_admissible()`). A rule can therefore never be justified by an earlier rule.

## Lifecycle

```
candidate ──► proposed ──(policy or --apply)──► active ──(evidence gone)──► retired
                 │                                 │
                 └──(--reject / rollback)──► rejected   (re-proposed only if evidence changes)
       (already in your instructions) ──► covered
```

Evidence changes bump the rule's version. An active rule stays active only if
it is still auto-eligible; otherwise it goes back to `proposed`.

```sh
repo-ai learn                     # list: * active  ? proposed  = covered  x rejected
repo-ai learn --explain tests:tests
repo-ai learn --apply tests:tests  |  --apply-safe  |  --reject boundary:web->core
repo-ai learn --history
repo-ai learn --rollback <event-id>   # restores files; marks the rules rejected
```

Rollback restores each file from the event snapshot if it is unchanged since
the event. If it has changed since, only the repo-ai managed block is restored.
A failed write leaves the previous files intact, and every overwritten file is
also backed up under `state/backups/`.

## Skill Factory

Candidates, each with its evidence and a validation report:

| Skill | When | Risk |
|---|---|---|
| `repo-add-endpoint` | ≥ 3 routes in one framework | safe |
| `repo-tests` | test suites with known frameworks | safe |
| `repo-add-component` | ≥ 3 UI components in one directory | safe |
| `repo-precheck` | (signals) the same lint/test/build sequence in ≥ 3 sessions | safe |
| `repo-db-migration` | Alembic, Prisma, Rails, Django, Flyway or Knex artefacts | **risky → manual-only** |
| `repo-release` | declared deploy/publish commands | **risky → manual-only** |

Validation (`repo-ai skills audit`) checks:

* front matter is a strict YAML subset;
* the name is valid, matches its directory, and is not a built-in command;
* the description is ≤ 1024 characters;
* referenced repo paths exist;
* no `allowed-tools`;
* any skill whose commands match deploy, migrate, publish, credential or
  production patterns must be manual-only.

Claude Code's own validator also passes: `claude plugin validate .claude`.

On a name collision the user, team, personal or plugin skill wins, and the
candidate is blocked. Versions and the last five bodies are kept in
`.repo-ai/learning/skills.json`:

```sh
repo-ai skills candidates | list | audit
repo-ai skills generate --safe          # or: generate repo-tests repo-add-endpoint
repo-ai skills rollback repo-tests      # remove; not regenerated unless evidence changes
repo-ai skills rollback repo-tests --previous   # pin the previous version
```

## The four stores

repo-ai keeps four separate kinds of memory. They never mix.

| Store | What | Where | Shared? |
|---|---|---|---|
| 1. Project facts | deterministic analysis: commands, conventions, structure, the evidence graph | index + `.repo-ai/context/` | docs are committed |
| 2. Episodic outcomes | per session: task classes, candidate/injected/edited paths, known-command results, status | `.repo-ai/state/episodes/` | never (machine-local) |
| 3. Candidate rules and skills | evidence, confidence, counterevidence, status, history, rollback snapshots | `.repo-ai/learning/` | committed (reviewable policy) |
| 4. Portable patterns | opt-in, sanitized stack recipes and aggregate outcomes | outside every repo, per zone (`repo-ai registry`) | only within its zone |

Human-written instructions always outrank everything repo-ai synthesises.
repo-ai never edits text outside its managed blocks. A rule a human already
states becomes `covered`, not duplicated.

## Signal levels (`learning_signals`)

| Level | Records | Who sets it |
|---|---|---|
| `off` (default) | nothing | |
| `known-commands` | which of the repository's **declared** commands ran or failed; task classes of prompts; edits to generated files | v0.5 `--smart` |
| `outcomes` | the above, plus per-session episodes: candidate and injected files per prompt, edited paths, known test runs, and the session status | `--smart` since 0.6 |

Never recorded at any level: prompt text, command output, unknown commands,
file contents, or secret values. Session ids are hashed. repo-ai never reads
Claude transcript files. No extra hooks are needed for `outcomes`: it reuses
the prompt, edit, Bash and Stop hooks.

### Session status

| Status | Meaning |
|---|---|
| `verified` | a known test command passed after the last edit |
| `failed` | the last known test after the last edit failed |
| `unverified` | files were edited but no test ran after the last edit |
| `no-change` | nothing was edited |

`verified` means tests passed, **not** that the task was done.

## Outcome-aware ranking (shadow first)

Episodes produce a candidate **outcome prior**, a per-file ranking
adjustment:
- **Raised** for files that sessions ended up editing after repo-ai listed
  them as candidates.
- **Lowered** for files that were listed but never touched.
- **Ignored**: failed sessions, which are not evidence of where a fix
  belongs.

The prior changes a candidate's score by at most ±30 %. It only re-orders
files that already have evidence and never adds one.

```sh
repo-ai learn shadow             # leave-one-session-out evaluation on recorded candidate lists
repo-ai learn approve ranking    # promote (refused unless the shadow gate passes; --force overrides)
repo-ai learn rollback ranking   # back to evidence-only ranking
```

**Promotion gate**: at least 8 prompts across at least 3 sessions, an MRR
gain of at least 0.02 for the first edited file, and more prompts improved
than worsened. Every prompt is scored with a prior learned from *other*
sessions only. Promotion and rollback are recorded in `repo-ai learn history`.

## Counterevidence

A rule that recommends a command which keeps failing in recorded sessions
is never auto-applied. A rule that failed twice and never passed is
demoted from `active` to `proposed`, with the reason in its note, so a
human decides. This is the only way outcomes change rules. Outcomes never
write rule text.

## Friction radar

`repo-ai learn friction` reports at most five items with evidence and a
suggestion. It is a digest you ask for, never an interruption:

- **missed-file**: a file edited in two or more sessions but never in the
  injected shortlist;
- **failing-command**: a known command that keeps failing and never passes;
- **unverified**: most sessions with edits end without a test run;
- **stale-context**: prompts answered from a stale index.

## Commands

```sh
repo-ai learn status                    # policy, signal level, rules, sessions, prior, friction
repo-ai learn review                    # proposed rules (with evidence) and a promotable prior
repo-ai learn explain <id>              # evidence and placement of one rule
repo-ai learn approve <id> | reject <id>
repo-ai learn history | rollback <event>
repo-ai learn forget [--what episodes|signals|flight|ranking|all] [--older-than DAYS]
repo-ai learn export [--portable]       # JSON: active rules + aggregate outcomes
repo-ai privacy audit                   # every store, its size, whether it is committed; exit 1 on a violation
```

The v0.5 flags (`--apply`, `--explain`, `--history`, `--rollback`,
`--forget-signals`) still work.

Retention: episodes are kept 30 days and capped at 400 sessions; signals at
2,000 lines over 60 days; the flight recorder at its last 200 entries. All of
them live in the gitignored state directory, and `repo-ai uninstall`
removes them.
