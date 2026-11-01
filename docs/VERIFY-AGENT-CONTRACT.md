# `repo-ai verify` for agent integrations: decisions on P1–P3 and the contract

This file answers Session B's proposals
(`docs/research/VERIFY-INTERFACE-PROPOSALS-2026-10.md`, branch
`research/instagram-skills-20261022`, both in the private development history). It also fixes the interface that
skills, hooks and plugins may rely on. It describes PR #25 as of the
held-out-5 freeze; `benchmarks/verify-eval/FREEZE.md` names that commit.

## Decisions

### P1: gate block cap

**Status: implemented.**

- **Was it already covered?** No. "Once per change fingerprint" does not bound
  blocks while the change keeps changing: every edit is a new fingerprint.
- **What changed:** `verify_gate_max_blocks` (default 3) caps blocks per agent
  session, keyed by the Stop payload's `session_id`. The count is kept in
  the gate's state, `<state>/gate.json`; the 20 most recent sessions are
  remembered.
  - `0` never blocks.
  - Report mode (`verify_gate_mode = "report"`) never blocks and is not
    capped.
  - A payload without `session_id` counts under one shared empty key, so it
    is still bounded.
- **Tests** (`tests/test_verify_gate.py`):
  - `test_gate_never_blocks_more_than_n_times_per_session`;
  - `test_gate_counter_is_per_session_not_global`;
  - `test_the_report_mode_is_not_bounded_by_the_block_cap`;
  - `test_a_gate_state_file_from_before_the_cap_is_still_read` (state files
    from 0.7.6 still load).

### P2: coexistence with other Stop hooks

**Status: the hazard was real and is now fixed; both proposed tests are
pinned.**

- **The hazard:** a formatter rewrote the code after a passing verification.
  The exact fingerprint changed, and the gate blocked again for a change that
  is still behavioural against HEAD.
- **What changed:** evidence from a clean run now also stores a
  `semantic_fingerprint`, and the gate accepts passing evidence whose
  semantic fingerprint matches.
- **What counts as "the same":**
  - **Python:** the same syntax tree, from the bytes and with the
    interpreter's own decoding. Comments, whitespace, quote style and line
    wrapping are ignored; docstrings count.
  - **JS/TS:** the same conservative token stream. Comments, spaces within a
    line and the quote style of a backslash-free string are ignored.
    - Line breaks count, because automatic semicolon insertion depends on
      them, and so does whitespace between operator characters
      (`a + +b` ≠ `a ++b`).
    - Template literals, regular-expression literals, JSX, escapes and any
      non-UTF-8 file fall back to exact bytes.
    - A prettier re-wrap therefore still asks for verification once more.
      That is accepted: the alternative risks accepting evidence for a
      different program.
  - **Every other file:** exact bytes.
- **Not affected:** runs, evidence reuse and caches always use the exact
  fingerprint.
- **Tests:**
  - `test_formatting_only_rewrite_after_verification_does_not_reblock_python`
    and `…_javascript`;
  - `test_gate_is_silent_when_another_stop_hook_continues_the_agent`;
  - `test_failing_evidence_still_blocks_after_a_formatting_rewrite`;
  - a parametrised tokenizer suite with the cases that must *not* compare
    equal;
  - `test_a_real_run_records_the_semantic_fingerprint`, end to end in the
    sandbox.

### P3: edit-time verification

**Status: no automated test execution per edit. A read-only per-path plan
exists. A per-edit hook is not recommended yet.**

- **Interface:** `repo-ai verify --json --paths <file>[,<file>]`
  (`engine.build_plan(..., paths=[...])`).
  - It plans for the changed files among those paths only.
  - Its fingerprint covers only them, and the JSON says
    `"scope": {"paths": [...], "partial": true}`.
  - It never runs or records: `--paths` with `--run` or `--record` is an
    error before anything starts.
  - It is never evidence.
- **Measurements:** `benchmarks/verify-eval/p3_plan.py`; results in
  `benchmarks/verify-eval/results/p3-plan-debe17e.json`.
  - **Scope:** 9 development-corpus projects (5 Python, 4 JavaScript), 4
    three-file edit sessions each. A tenth, parse, has no change set spanning
    three files.
  - **Latency:** a per-path plan took a median of 0.27–0.34 s and a p95 of
    0.30–0.42 s, about the same as the whole-change plan. Most of the cost is
    fixed work: the file listing, the dynamic-loading scan and the index.
    Scoping to one file barely reduces it.
  - **Budget:** the proposal's 300 ms p95 is **missed on all 9** (busboy
    came closest, at 0.304 s).
  - **Union equivalence:** the union of per-path selections equals the
    whole-change selection in **36 of 36** sessions. "Full suite required"
    agrees in 36 of 36. Selection is per changed file, so this is expected;
    the script checks it rather than assuming it.
  - **Context cost:** a per-path plan is 2.4–23 kB of JSON (median per
    project) or 1.1–4.5 kB of text. Injected after every edit, that is
    noise.
- **Recommendation:**
  - Do not wire a `PostToolUse` hook that injects a plan after every edit.
  - If Session B wants an edit-time signal, use the existing `Stop` gate in
    report mode, or call `verify --paths` from a skill **on request**, not
    on every edit.
  - Revisit once fixed planning cost is cut: the duplicate git and
    interpreter spawns in the audit's performance section.

## The contract

**Stability:** within schema `repo-ai.verify-plan/1` and
`repo-ai.verify-evidence/1` (the `schema` field), fields are only ever *added*.
A consumer must ignore fields it does not know. A rename or removal changes
the schema id.

### Commands

| Command | Runs repository code | Writes | Exit codes |
|---|---|---|---|
| `repo-ai verify [--json] [--paths P] [--base REV]` | never | the dynamic-scan cache under the state dir | 0; `error: …` and exit 1 on bad input (no index, a path outside the repository, a `--base` that does not resolve to a commit) |
| `repo-ai verify --run [--json] [--full] [--rerun] [--workers N] [--timeout S]` | yes, sandboxed, in a disposable copy. **Requires the user's explicit authorization** | evidence, base-outcome and timing caches | 0 passing verdict; 1 any other verdict, or an error (`error: …`, never run unsandboxed); 130 cancelled (SIGINT, SIGTERM, SIGHUP), nothing recorded |
| `repo-ai verify --record` | yes, sandboxed | `testmap.json` (including, for pytest, the files pytest itself collected and a fingerprint of every collection input) | 0; 1 on error |
| `repo-ai evidence [--json]` | never (nor the project's interpreter) | nothing | 0 the latest evidence covers this exact tree in the same test environment; 2 stale; 1 none |
| The completion gate: the installed `Stop` hook `repo-ai hook claude stop`, active when `verify_gate = true` (stdin: the hook payload) | never | `gate.json` | always 0, and fails open. Stdout is empty, or one JSON object `{"decision": "block", "reason": …}` (block mode) or `{"systemMessage": …}` (report mode). It always compares the working tree with `HEAD`, so evidence recorded with another `--base` never satisfies it. `repo-ai verify --gate` computes the same decision but is an ordinary command (a bad argument exits 2): hooks should call `repo-ai hook claude stop` |

**Passing verdicts** are exactly the strings starting with
`selected-and-full-suite-passed`, `selected-passed (full suite not run)` and
`nothing-selected`.

**`nothing-selected` only for changes without behaviour.** It is produced only when no changed file
can alter what a test observes: documentation, comments, formatting, or repo-ai's own managed block.
Two other cases of nothing selected are not passes, and exit 1:
- a behavioural change that no test is linked to, when the full suite is not required, gives
  `not verified: no test is linked to the behavioural change (nothing was selected)`;
- a change that requires the full suite, when the full suite cannot be run, gives
  `not verified: the full suite is required for this change and could not be run`.

If the full suite is required and runs successfully, the verdict can be
`selected-and-full-suite-passed` even with an empty selection. This establishes
that the existing suite passed, not that it covers the unlinked change.

Both abstentions start with `not verified:`, which this contract already lists as not passing. **Compatibility:**
before this rule, both cases were reported as `nothing-selected` with exit 0. The schema ids are
unchanged.

**Every other verdict means "not verified as passing"**:
- `regression`;
- `failing (…)`;
- `full-suite-failed`;
- `not verified: …`;
- `selected-passed; full suite REQUIRED but not run`;
- `selected-passed; full suite failed (not required; …)`;
- `no tests ran: …`;
- `invalid: the source tree changed during the run`.

A consumer must not parse the text after the prefix.

### JSON

**Plan** (`verify --json`; `schema: "repo-ai.verify-plan/1"`):
- `fingerprint`, `base`;
- `confidence` (`high` | `medium` | `low` | `none`);
- `full_suite_required`, `triggers[]`, `uncertainty[]`;
- `selected[]` (`test`, `reasons[]`);
- `changed_files[]`, `runner`, `test_files_total`;
- with `--paths`: `scope`;
- without `--paths`: `evidence_status` (`state: current|stale|none`,
  `verdict`, and `stale_reason`: `change` or `environment`).

**Run** (`verify --run --json`): `{"summary", "plan", "evidence"}`.
- `summary`:
  - `verdict`;
  - `new_failures[]` (`test_file`, `tests[]`, `status`);
  - `pre_existing[]` (and `sandbox_network_suspected[]`: those whose output looks like the sandbox's missing
    network), `failing_differently[]`, `unverified[]`;
  - `unconfirmed[]`, `not_compared[]`;
  - `passed`, `seconds`, `processes`, `reused`;
  - `source_tree_unchanged`.
- `evidence`: the full record (below).

**Evidence** (`repo-ai evidence --json`):
`{"current", "same_behaviour", "stale_reason", "environment_check",
"environment_detail", "evidence"}`, every key in every state (with no
evidence: `false`, `false`, `null`, `"not checked"`, `""`, `null`, exit 1).
- `current`: the exact tree is the one verified, in a test environment that
  is still installed (see Freshness).
- `same_behaviour`: the gate's rule (exact, or the same Python syntax tree or
  JS/TS tokens), with the same environment condition.
- `stale_reason`: `null` when `current`; `"change"` (the tree differs) or
  `"environment"` (the same change, but the recorded test environment changed).
- `environment_check`: `"unchanged"`, `"changed"` (`environment_detail` says
  what, e.g. `<path> no longer exists`), `"not recorded"` (a record written
  before 2026-10-25: the fingerprint's answer stands, and the text output says
  the environment is not compared) or `"not checked"` (the change already
  differs, or there is no evidence).
- The record holds `schema`, `fingerprint`, `semantic_fingerprint` (from runs
  that left the tree unchanged), `verdict`, `results[]` (per test file:
  `status`, `classification`, `baseline`, `failing_tests`,
  `changed_failures`, `unverified`), `source_tree`, `processes` and `created`.
- `environment_static` (since 2026-10-25; add-only): `{"version": 1,
  "interpreter", "interpreter_id", "files", "dirs", "digest"}` and, for a
  container run, `"unchecked": ["container image"]`. `files` are the
  interpreter (or Node) and a virtualenv's `pyvenv.cfg`, identified by `stat`;
  `dirs` are the site-packages and read-only dependency directories
  (`node_modules`), identified by every entry's path, type, size,
  modification and change time (`cache._tree_id`). `digest` covers both.
- `created` is ISO 8601 local time with its UTC offset (`2026-10-23T06:40:35-07:00`). Records
  written before this change have no offset. It is for display: never order records by it.

### Freshness

- **Evidence covers exactly one state:** the exact fingerprint (base commit
  plus every changed file's content, including untracked files) or, for the
  gate, the semantic fingerprint.
- **Reuse:** `verify --run` reuses evidence younger than 24 h, recorded under
  the same reuse key (change, environment, test command, selection, explicit
  `--timeout`). `--rerun` forces a run.
- **The test environment:** a run records `environment_static` (above)
  from the state before its tests started. `repo-ai evidence` and the
  completion gate recompute its digest from the recorded paths alone (`stat`,
  `scandir`, `readlink`; no interpreter, no repository code, nothing opened)
  and treat any difference, a recorded path that no longer exists, or a
  malformed or unknown-version identity as stale: after `pip install -U`, a
  recreated virtualenv or an edit inside site-packages, a pass of the same
  change no longer counts. The gate then shows the change once more as
  unverified (block mode: blocks, at most once per stale pass and within the
  per-session bound; report mode: one line). Records without the field keep
  the fingerprint-only answer (`environment_check: "not recorded"`); the gate
  stays silent for them, as before.
  - Cost (2026-10-25, Apple M-series, warm metadata cache, median of 21): 0.2 ms
    for a small project (12 entries), 25-29 ms for this repository's dev
    virtualenv (4,834 entries), 137 ms for a 25,504-entry site-packages:
    about 5.4 µs an entry, paid only when the record would otherwise pass.
  - Not covered: a container image (re-checking it needs the container
    engine), the standard library, and code reached outside the recorded
    directories (an editable install's source, a `.pth` line pointing
    elsewhere). A directory of more than 400,000 entries never matches, so its
    passes are always stale.
- **What a consumer should do:** call `repo-ai evidence --json`. Trust only
  `current` (or `same_behaviour`) **and** a passing verdict. Never trust a
  record because it exists.
- **Parallel sessions:** `latest.json` is the newest valid run in this
  state directory, possibly another session's run of another state.
  - When it does not match the working tree, the gate and `repo-ai evidence`
    use the newest valid history record of *this* change: the exact
    fingerprint, or for the gate the semantic one.
  - The newest record by write time decides, so a later failing run is never
    passed over for an earlier pass.
  - An `invalid: …` run is kept in the history but never becomes the latest.
  - The source-tree check ignores git bookkeeping and repo-ai's own context
    and learning directories, which other sessions write during a run.
    `.git/HEAD`, the commit it resolves to, `.git/config`, `.git/hooks/` and
    every linked worktree's and submodule's config and hooks stay checked.

### Permissions

- **Nothing in this interface grants an agent new tools or permissions**, or
  edits agent settings.
- **Running tests is the only action that executes repository code.** It is
  `verify --run` or `--record`, always sandboxed, and must be started by the
  user or with the user's explicit authorization.
- **A hook or skill may call** `verify --json` (with or without `--paths`),
  `evidence --json` and `--gate`. None of them runs repository code.
- **The gate never runs anything itself.** It asks the agent to run
  `verify --run`.

### Errors

- **On stderr:** `error: <reason>`.
- **Errors are not verdicts:** a consumer must treat a non-zero exit with no
  JSON on stdout as "no result".
- **No silent fallback:** when no sandbox is available, `verify --run` fails
  with `error: …`. It never runs unsandboxed.

### Diagnostics from optional tools (specified; not implemented)

An optional, approved external tool (for example a static security analyzer
that Session B's capability layer runs) may attach structured findings to a
change. **Diagnostics never change the verdict, the exit code, the gate's
decision or any evidence record.** The core engine knows nothing about how
a tool was approved.

- **Schema** `repo-ai.verify-diagnostics/1`, one file per producer:
  `<state>/evidence/diagnostics/<fingerprint>/<producer-id>.json`, mode 0600,
  written atomically, the 50 most recent fingerprints kept.

  ```json
  {"schema": "repo-ai.verify-diagnostics/1", "fingerprint": "<64 hex, exact>",
   "producer": {"id": "adapter.<name>", "version": "...", "output_sha256": "<64 hex>"},
   "created": "...Z", "status": "ran|error|nothing-to-scan", "scanned_files": ["app/x.py"],
   "findings": [{"rule": "S602", "severity": "high|medium|low|info", "path": "app/x.py",
                 "line": 8, "column": 5, "untrusted_message": "..."}],
   "counts": {"total": 1, "by_severity": {"high": 1}}, "truncated": false}
  ```
- **Writer:** a library call, `verify.diagnostics.attach(root, state_dir, base, doc)`;
  there is no command that writes diagnostics.
  - It recomputes the change's exact fingerprint and refuses a document for any
    other state.
  - The capability layer calls it only after its own approval decision.
- **Limits**, checked on write and again on read:
  - 256 KiB per file, 8 producers and 200 findings (beyond that `truncated: true`);
  - `rule` matches `[A-Za-z0-9._/-]{1,64}`;
  - `path` must be one of the change's files;
  - `line` and `column` are integers;
  - `untrusted_message` is at most 300 characters, with control and ANSI
    characters removed.
- **Reader:** `repo-ai evidence --json` gains a separate top-level key:
  `"diagnostics": {"advisory": true, "affects_verdict": false, "state":
  "current|stale|none|unsupported", "items": [...]}`.
  - `items` is non-empty only when the diagnostics' fingerprint equals the
    *exact* current fingerprint. A semantic match is not enough: line
    numbers move.
  - Text output shows one line of counts, never the messages.
  - The gate, hooks, `verify --run` output and evidence records never read
    diagnostics.
- **Tests that must exist with the implementation:**
  - every verdict × {no diagnostics, many high findings, error, malformed,
    oversize, unknown schema}: identical exit codes, `current`, gate decision
    and evidence object;
  - the gate and hooks never import the module;
  - a stale fingerprint is refused, and after an edit the state is `stale`;
  - a message containing `{"decision":"block"}`, markdown, ANSI or NUL never
    reaches gate, hook or text output.

## Handoff to Session B (PRs #24, #26, #27)

**State (2026-10-23):**
- PR #25 (the verify engine) is merged into `main` (`bc72d50`).
- PR #28 (lower fixed overhead) is retargeted to `main`, with `main` merged
  in, and has no history rewritten.
- The corrective branch `fix/core-correctness` changes nothing in Session B's
  files.

**Compatibility, checked read-only** (in-memory `git merge-tree`, and a
throwaway clone merging everything):

| Merge | Conflicts | Tests |
|---|---|---|
| `main` × #24, `main` × #26, `main` × #27, #26 × #27 | none | — |
| `main` + #24 + #26 + #27, merged in turn | none (`cli.py` and README merge automatically) | 366 passed, 2 skipped, on the selected suites; `build_plugin --check` up to date |

- **Overlap:** the PRs share `cli.py` with `main`, but in `cmd_skills`,
  `cmd_capabilities` and the parser, never in `cmd_verify` or `cmd_evidence`.
- **Untouched:** none of the three touches `config.py`, `hooks.py`,
  `paths.py` or `verify/`.
- **Behind main:** #24 is about 50 commits behind `main`.

**What Session B relies on:**
- #27's manifest runs `repo-ai verify --json`, the read-only plan, and checks
  only that the output is valid JSON. That stays supported.
- Its P4 "static-security" slot maps onto the diagnostics interface above.
  - Its SARIF output belongs under the producer's own machine directory,
    attached through `attach()`.
  - Note: #27's text says `<state_dir>/capabilities/runs`, but its code writes
    `machine_dir/capability-runs/sarif`.

**Merge order:**
1. The corrective branch.
2. PR #28 (re-validated on top of it).
3. Then #24, #26 and #27, rebased by Session B.

Each needs the owner's approval.

**Not to rely on:**
- the text after a verdict prefix;
- a field not listed here;
- calling `repo-ai verify --gate` from a hook (use `repo-ai hook claude stop`);
- any per-edit `--run`.
