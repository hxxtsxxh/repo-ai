# repo-ai architecture

Three layers with one direction of dependency: adapters and learning consume
the engine; the engine knows nothing about agents.

```
            ┌──────────────────────── Layer C: learning & orchestration ────────────────┐
            │ learning.py  rules from evidence → ledger → policy → history/rollback     │
            │ skills.py    Skill Factory: candidates → validate → provenance → rollback │
            │ signals.py   opt-in local signals (known commands, task classes)          │
            └──────────────┬───────────────────────────────────────────────┬────────────┘
                           │ active rules / skills                         │ facts, index
            ┌──────────────▼──────── Layer B: agent adapters ───────────────┴────────────┐
            │ adapters/claude.py  CLAUDE.md block, .claude/{rules,skills,agents,hooks}   │
            │ adapters/bob.py     AGENTS.md block, .bob/{skills,rules,commands,hooks}    │
            │ hooks.py            Claude hook runtime (prompt/session/edit/stop)         │
            └──────────────┬─────────────────────────────────────────────────────────────┘
                           │ RepoFacts + Index + retrieval API
            ┌──────────────▼──────── Layer A: deterministic engine ──────────────────────┐
            │ scanner → parser → analyze (imports, manifests, frameworks, components,    │
            │ routes, tests, docs, git) → index (SQLite + FTS5) → render (Markdown docs) │
            │ retrieval.py (ranking) · impact.py (blast radius) · security.py            │
            └────────────────────────────────────────────────────────────────────────────┘
```

Beside the three layers, v0.7 adds opt-in subsystems that never run during
`init`/`update` and never run on a hook:

```
 evaluation    evals.py (suite, offline gate) · coding_lab.py (3-arm lab) · sandbox.py
 skill network radar.py (profile, search) → firewall.py (quarantine, inspect)
               → recommend.py → portfolio.py (lockfile, install, kill switch, trials)
 optimisation  optimize.py (zero-value, budget governor, proposals, Self-Improvement
               Governor, machine-local tuning) · stackpacks.py (zone patterns → packs)
```

The tuning layer is read on every config load (`optimize.apply_tuning`). It
can change only `hook_max_files` and `hook_budget_tokens`, and only when
nobody set them explicitly.

`workspace.generate()` owns generated repository configuration and context. Explicit verification and mission execution also write bounded runtime records under the resolved state directory. `init`,
`update`, `rebuild`, `refresh`, `learn --apply` and `skills generate` all call it.

## Data flow of one `repo-ai update`

1. **Lock** `state/update.lock` (exclusive; hooks use a non-blocking try-lock).
2. **Scan** with the ignore pipeline and secret quarantine. repo-ai's own
   directories and managed blocks are excluded, so nothing repo-ai writes can
   become evidence for anything repo-ai learns.
3. **Analyse** changed files; recompute every *derived* fact (import
   resolution, centrality, test links, conventions) over the whole repo from
   the index, so `update` output equals `rebuild` output (tested).
4. **Render** docs into a `Plan`. Writes that differ only in a timestamp are
   skipped, so identical inputs leave files byte-identical.
5. **Learn** (`run_cycle`) and **run the factory** (`run_factory`): deterministic
   candidates, compared with the ledger, gated by policy.
6. **Adapters** add their changes to the same `Plan`.
7. **Apply** the plan atomically (temp file + `os.replace`), with a backup of
   every file it overwrites under `state/backups/` (last 8 runs).
8. **Record** a learning event with before/after snapshots when rules or skills
   changed, for `learn --rollback`.

## Layouts and file ownership

| Path | Owner | In git? |
|---|---|---|
| `.repo-ai/config.toml` | human (created once; repo-ai only edits the `agents` line) | yes |
| `.repo-ai/context/` | repo-ai (regenerated; `NOTES.md` is human) | yes, unless `commit_context=false` |
| `.repo-ai/learning/` | repo-ai (ledger, history, skill provenance) | yes, unless local-only |
| `.repo-ai/state/` | repo-ai (index, cache, locks, signals, backups) | **never** (managed `.gitignore` block) |
| `CLAUDE.md` / `AGENTS.md` | human, plus one marked repo-ai block each | yes |
| `.claude/settings.json` | human; repo-ai owns only hook entries pointing at `.claude/hooks/repo-ai.sh` | yes |
| `.claude/{skills,agents,rules}/repo-*` | repo-ai, while the checksum marker matches | yes |
| `.bob/…` | as v0.4 (now with ownership markers) | yes |

The v0.4 layout (`.bob/context/` holding docs *and* `index.db`) is detected and
kept. An explicit `out_dir` always wins and is validated to stay inside the
repository.

**Ownership markers.** Every whole file repo-ai writes carries
`<!-- repo-ai:managed kind=… sha=… -->` (or a `#` comment). The sha covers the
rest of the file. If it no longer matches, a human edited the file, and repo-ai
treats it as theirs: it will not overwrite it or delete it on uninstall.
Shared files use BEGIN/END marker blocks, and text outside the markers is
never modified.

## Consistency guarantees

* **Determinism**: same tree → same bytes (docs, facts, rules, skills). Tested
  by `test_reinit_is_byte_identical_fixed_point`.
* **Incremental = rebuild**: tested by `test_incremental_update_matches_fresh_rebuild`.
* **Concurrency**: SQLite WAL with `busy_timeout`; one writer at a time via the
  update lock; hooks never wait on it. Four concurrent refreshes leave an
  index that passes `PRAGMA integrity_check` (tested).
* **Schema evolution**: `SCHEMA_VERSION` with in-place migration (v4→v5 adds
  tables, recreates the FTS table and flags a one-time re-analysis). An index
  from a *newer* repo-ai is refused with a message, never wiped.

## Security boundaries

* No network calls on any default path (tested by patching sockets). `--summarize`
  shells out to `bob run` and sends facts only — opt-in.
* Untrusted input: repository files, prompts and hook payloads are data. Nothing
  found in them is executed. Subprocesses use argument vectors, never a shell,
  and every one has a timeout.
* Quarantined files never reach the index, the docs, hook output or the
  ledger. Values are never stored, only a 4-character prefix and a length.
* repo-ai never adds permission `allow` rules, never sets `bypassPermissions`,
  and never writes `allowed-tools` into skills.
* Hooks fail open: zero bytes and exit 0 on any error. The dispatcher script
  can never return 2, which would block a prompt.

See [CLAUDE_CODE.md](CLAUDE_CODE.md), [LEARNING.md](LEARNING.md) and
[RETRIEVAL.md](RETRIEVAL.md) for the individual subsystems.

## Experimental mission kernel (0.9.0.dev0, extended in dev1 and after)

`mission/` composes ephemeral analysis/packet context, typed contracts, bounded DAG actions and the existing verify sandbox/reporting engine. `providers/` discovers capabilities without invoking models. Explicit simulated proposals are edited only in disposable candidates; mission evidence stays separate from the original checkout's verify gate. See [the implementation ledger](roadmap/REALITY-ENGINE.md) for executed checks, limitations and remaining increments.
