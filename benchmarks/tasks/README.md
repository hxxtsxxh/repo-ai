# repo-ai held-out coding tasks

A frozen benchmark of **84 coding tasks**:
- **59 synthetic tasks** across three small repositories written for repo-ai
  (Python, TypeScript monorepo, Java), split into `dev` (24) and `holdout`
  (35) by id hash;
- **25 re-injected upstream bugs** in six real open-source projects: the
  sealed **`final`** split (see "Open-source tasks" below).

It measures two things:

1. **End-to-end task success**: a coding agent (with or without repo-ai) gets a
   developer-style prompt, edits the workspace, and hidden tests decide pass/fail.
2. **Retrieval quality**: how well repo-ai locates each task's `gold_files` from the
   prompt alone.

The agent must never see `cases/*/hidden/` or `task.json`. Only the base repository
(after `setup`) and the `prompt` are exposed.

## Layout

```
benchmarks/tasks/
  README.md
  bases.json                 # per-base language, visible-test commands, toolchain
  bases/<base>/...           # the three base repositories (plain folders, not git repos)
  cases/<task-id>/task.json  # one task
  cases/<task-id>/hidden/... # hidden test files, copied to the paths in task.json
```

### Bases

| Base | Language | What it is | Visible tests |
| --- | --- | --- | --- |
| `py-shop` | Python 3.10+, stdlib only | Order management service: `shop/api` (route table + tiny router + handlers), `shop/services` (orders, payments, inventory, pricing, discounts, shipping, notifications, auth, users), `shop/models`, `shop/repository`, `shop/utils`, `shop/config.py`; `Makefile`, `pyproject.toml` | 56 `unittest` tests |
| `ts-workspace` | TypeScript on Node >= 22.18 (native type stripping, no build, no deps) | npm-workspaces job scheduler: `packages/core` (durations, schedules, retry, semver, config, events, rate limiter, lifecycle), `packages/api` (HTTP-shaped API with scopes, cursors, rate limiting), `packages/cli` (`jobs` CLI). Relative `.ts` imports, erasable syntax only | 39 `node:test` tests |
| `java-ledger` | Java 17, no Maven/Gradle needed | Double-entry ledger: `Money`, `Account`, `Transaction`, `Ledger`, `InterestCalculator`, `ExpenseSplitter`, `io.CsvParser`/`io.CsvImporter`, `report.ReportFormatter`; tests use an in-repo `Check` helper | 27 checks via `AllTests` |

`bases.json` gives each base's visible-test command list (same placeholders as task
commands, below):

```json
{"py-shop": {"language": "python",
             "visible_tests": [["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", "."]],
             "toolchain": ["python"]}, ...}
```

## task.json

```json
{
  "id": "py-shop-001-percent-coupon-rounding",
  "base": "py-shop",
  "language": "python",
  "category": "bugfix",
  "difficulty": "easy",
  "prompt": "Support ticket: ...",
  "setup":    [{"file": "shop/utils/money.py", "find": "...", "replace": "..."}],
  "solution": [{"file": "shop/utils/money.py", "find": "...", "replace": "..."}],
  "gold_files": ["shop/utils/money.py"],
  "hidden": [{"src": "hidden/test_hidden_pct_coupon.py", "dest": "tests/test_hidden_pct_coupon.py"}],
  "commands": [["{python}", "-m", "unittest", "tests.test_hidden_pct_coupon"]],
  "timeout_s": 120,
  "attribution": "Synthetic task authored for repo-ai (MIT)."
}
```

* `setup` / `solution`: ordered exact-substring replacements. Each `find` occurs
  **exactly once** in its file at the moment it is applied. `setup` produces the
  starting state (injects the bug, removes the feature); it is `[]` when the base itself
  is the starting state. An edit of the form `{"file": ..., "create": "..."}` adds a new
  file. Some setups use it to extend a base with realistic code that exists only in that
  task's starting state (for example a `packages/web` dashboard package, a media
  endpoint, or a `store` package with schema migrations); the shared bases are never
  modified, so other tasks are unaffected. `solution` is a minimal reference fix and is
  never shown to the agent.
* `gold_files`: repo-relative POSIX paths a correct fix modifies (or, for `test` tasks,
  creates). Used for retrieval scoring.
* `hidden`: files copied from the case folder into the workspace after the agent is done.
  No hidden destination exists in any base, and no hidden file name appears in a base or
  a prompt.
* `commands`: argv lists run in order with cwd = workspace root; the task succeeds only if
  every command exits 0. Placeholders:
  * `{python}`: the Python interpreter
  * `{node}`: the node binary
  * `{glob:PATTERN}`: expands to the sorted workspace files matching a POSIX glob (`**` supported)
  * `{out}`: a fresh empty temp directory, shared by all commands of one task run

  Java tasks compile everything into `{out}` and then run one hidden test class, e.g.
  `["javac", "-d", "{out}", "{glob:src/main/java/**/*.java}", "{glob:src/test/java/**/*.java}"]`,
  then `["java", "-cp", "{out}", "com.example.ledger.HiddenMonthEndTest"]`.

Hidden tests check behaviour, not source text, so any correct fix passes. Performance
tasks never rely on wall-clock timing: they count work through test-owned hooks (a
counting `dict` swapped into a repository, a counting property getter on input objects)
and assert a linear bound. Tasks that ask for a new API (migration, architecture) name
the required functions, classes or settings in the prompt. Each suite also
includes one or two regression assertions on existing behaviour. They are deterministic
(fixed clocks, no randomness), offline and fast. The two `test`-category tasks use
mutation checks: they run the repository's own tests (without the hidden file) against
deliberately broken variants of the code and require that the suite fails, and that it
passes on the real code.

Harness note: run the base's visible tests **before** copying hidden files in. Hidden
files live inside the test folders, so discovery-based commands would otherwise pick
them up.

## Categories and counts

59 tasks: 27 on `py-shop` (python), 20 on `ts-workspace` (typescript), 12 on
`java-ledger` (java).

| Category | Meaning | py-shop | ts-workspace | java-ledger | Total |
| --- | --- | --- | --- | --- | --- |
| bugfix | A defect with a symptom-level report | 13 | 9 | 6 | 28 |
| feature | New behaviour inside one package | 1 | 0 | 1 | 2 |
| api | Route / endpoint / contract change | 1 | 1 | 0 | 2 |
| refactor | Remove drifted duplicate logic; checked by behaviour | 1 | 0 | 1 | 2 |
| test | Add missing tests; checked by mutation | 1 | 1 | 0 | 2 |
| config | Wrong configuration value or precedence | 1 | 1 | 0 | 2 |
| ci | Broken build / test script | 1 | 1 | 0 | 2 |
| integration | Cross-module behaviour | 1 | 0 | 1 | 2 |
| monorepo | Change that has to flow across workspace packages | 0 | 2 | 0 | 2 |
| security | Vulnerability report: path traversal, HTML injection, CSV formula injection | 2 | 0 | 1 | 3 |
| auth | Authentication / authorisation rules: impersonation checks, key expiry | 1 | 1 | 0 | 2 |
| database | Persistence semantics: transaction rollback, schema-migration ordering | 1 | 0 | 1 | 2 |
| frontend | UI rendering and UI state logic (pure render-to-string, form reducer) | 0 | 2 | 0 | 2 |
| performance | Quadratic work on large inputs; checked by operation counts, not timing | 1 | 1 | 0 | 2 |
| migration | Move to a new scheme or format while keeping the old one working | 1 | 1 | 0 | 2 |
| architecture | Introduce a seam (injected clock, storage interface) a test can substitute | 1 | 0 | 1 | 2 |

Difficulty: 14 easy, 36 medium, 9 hard.

`py-shop-027`, `ts-workspace-020` and `java-ledger-012` are multi-file bugfixes: each
injects related defects into three files, and the reference fix with any one of them
left out still fails the hidden tests.

| Task | Category | Difficulty |
| --- | --- | --- |
| py-shop-001-percent-coupon-rounding | bugfix | easy |
| py-shop-002-nested-order-route | bugfix | medium |
| py-shop-003-cancel-pending-restock | bugfix | medium |
| py-shop-004-session-lifetime | bugfix | easy |
| py-shop-005-tampered-token-accepted | bugfix | medium |
| py-shop-006-last-page-unreachable | bugfix | easy |
| py-shop-007-accented-slugs | bugfix | easy |
| py-shop-008-free-standard-shipping | feature | medium |
| py-shop-009-cancel-order-endpoint | api | medium |
| py-shop-010-coupon-exceeds-subtotal | bugfix | medium |
| py-shop-011-dedupe-money-formatting | refactor | medium |
| py-shop-012-pagination-contract-tests | test | medium |
| py-shop-013-make-test-runs-nothing | ci | easy |
| py-shop-014-mobile-orders-untaxed | bugfix | easy |
| py-shop-015-payment-retry-idempotency | integration | hard |
| py-shop-016-plus-address-signup | bugfix | easy |
| py-shop-017-saturday-delivery-estimate | bugfix | medium |
| py-shop-018-partial-refunds-overrun | bugfix | medium |
| py-shop-019-page-size-limit | config | easy |
| py-shop-020-media-path-traversal | security | medium |
| py-shop-021-receipt-html-injection | security | medium |
| py-shop-022-act-as-privilege-escalation | auth | medium |
| py-shop-023-unit-of-work-rollback | database | medium |
| py-shop-024-catalog-import-slowdown | performance | medium |
| py-shop-025-scrypt-password-hashes | migration | hard |
| py-shop-026-inject-clock-into-auth | architecture | medium |
| py-shop-027-order-total-mismatch | bugfix | hard |
| ts-workspace-001-millisecond-durations | bugfix | easy |
| ts-workspace-002-backoff-ignores-max | bugfix | easy |
| ts-workspace-003-caret-range-zero-major | bugfix | medium |
| ts-workspace-004-daily-job-runs-twice | bugfix | medium |
| ts-workspace-005-cursor-pagination-gaps | bugfix | medium |
| ts-workspace-006-filter-jobs-by-status | api | medium |
| ts-workspace-007-cli-duration-syntax | monorepo | medium |
| ts-workspace-008-pause-and-resume-jobs | monorepo | hard |
| ts-workspace-009-rate-limit-never-recovers | bugfix | hard |
| ts-workspace-010-read-only-key-can-write | bugfix | medium |
| ts-workspace-011-flag-value-with-equals | bugfix | easy |
| ts-workspace-012-env-overrides-config-file | config | medium |
| ts-workspace-013-root-test-script | ci | easy |
| ts-workspace-014-truncate-unit-tests | test | medium |
| ts-workspace-015-key-validity-last-day | auth | medium |
| ts-workspace-016-jobs-table-rendering | frontend | medium |
| ts-workspace-017-job-form-stuck-after-error | frontend | medium |
| ts-workspace-018-execution-order-quadratic | performance | hard |
| ts-workspace-019-config-file-v2 | migration | medium |
| ts-workspace-020-retry-backoff-attempts | bugfix | hard |
| java-ledger-001-month-end-balance | bugfix | easy |
| java-ledger-002-csv-quote-characters | bugfix | medium |
| java-ledger-003-interest-half-cent | bugfix | medium |
| java-ledger-004-failed-transfer-leaks-debit | integration | hard |
| java-ledger-005-uneven-expense-split | bugfix | medium |
| java-ledger-006-trial-balance-totals | feature | medium |
| java-ledger-007-importer-account-id-rules | refactor | medium |
| java-ledger-008-mixed-currency-sum | bugfix | easy |
| java-ledger-009-csv-export-formula-injection | security | medium |
| java-ledger-010-migration-version-order | database | medium |
| java-ledger-011-journal-store-interface | architecture | medium |
| java-ledger-012-transaction-reversal | bugfix | hard |

Prompts read like real bug reports or feature requests. Some include an error message or
stack trace, some describe only a symptom. Many name a file, symbol or flag; migration and
architecture prompts state the required interface. No prompt names a hidden test or
spells out the code change.

## Validation procedure

Every task was validated offline with Python 3.13, Node 24 and OpenJDK 17, as follows:

1. Each base's visible tests (`bases.json`) pass on the untouched base.
2. Static checks: `task.json` has exactly the keys above, in order; category, difficulty
   and language are valid; hidden destinations don't exist in the base; hidden file names
   appear neither in the prompt nor anywhere in the base.
3. **Starting state must fail**: copy the base to a temp dir, apply `setup` (asserting that
   each `find` occurs exactly once), copy the hidden files in, run `commands`. At least one
   command must exit non-zero. Each failure was also inspected to confirm it is an
   assertion about the intended behaviour, not a harness error.
4. **Reference solution must pass**: fresh copy, apply `setup` then `solution` (same
   exactly-once rule), run the base's visible tests (must pass), copy the hidden files
   in, run `commands`. All must exit 0.

The visible tests also pass on every starting state, so the injected bugs don't show
up in the existing suite.

## Licence and attribution

The synthetic `py-shop`, `ts-workspace` and `java-ledger` bases, prompts,
solutions and tests are original material written for repo-ai under its MIT
licence. The `oss-*` bases and their upstream-derived tests retain their own
notices and licences, listed below; they are also bundled in installed wheels. Names, e-mail addresses
(`*.invalid`, `example.com`), API keys (`dev-*-key`) and secrets
(`dev-only-not-a-secret`) are placeholders. No code or test touches the network.


## Open-source tasks (`final` split, sealed)

**Bases.** Six frozen snapshots of permissively licensed, dependency-free
Python projects. Each keeps its licence file, and `bases.json` records the
upstream URL, commit and licence:

| Base | Project | Licence | Tasks |
|---|---|---|---|
| `oss-markdown` | Python-Markdown @ b41e0aaf | BSD-3-Clause | 10 |
| `oss-pyflakes` | pyflakes @ f0a8b981 | MIT | 4 |
| `oss-cachetools` | cachetools @ 6f23e2a7 | MIT | 4 |
| `oss-simplejson` | simplejson @ 9950b7e5 | MIT or AFL-2.1 | 3 |
| `oss-bottle` | bottle @ 8ec5fe29 | MIT | 3 |
| `oss-tomli` | tomli @ 43a86ade | MIT | 1 |

**Vendoring changes** (all mechanical):
- `src/<pkg>` moved to `<pkg>`;
- docs, CI and tooling removed;
- Python-Markdown gets a minimal `Markdown-3.11.2.dist-info` generated from
  its own `pyproject.toml`, so its extension entry points resolve without
  installation;
- Python-Markdown's `tests/test_apis.py` is dropped because it needs PyYAML.

**How tasks were selected.** One rule, applied to every commit in the
mining window, newest first; no hand-picking. Every examined commit and its
outcome is listed in [`oss-manifest.json`](oss-manifest.json): 3,760
commits examined, 25 kept, 3 excluded. A commit is kept only if:
1. it is a non-merge commit that changes at least one package source file
   and at least one test module;
2. 3–200 source lines change, over at most 4 files;
3. it is not a docs, lint, CI or release commit;
4. its diff reverse-applies onto the frozen snapshot, which re-injects the
   bug;
5. it passes the oracle, run **inside the podman sandbox** (third-party code
   never runs on the host). The bugged state passes the visible suite and
   fails the upstream regression tests; the fixed state passes them;
6. the hidden test checks user-observable behaviour. Three otherwise valid
   commits were excluded because their tests assert private internals. Each
   reason is in the manifest.

**What the agent sees** is the snapshot with the bug re-injected and the
pre-fix versions of the touched test files, as a single git commit (no
history to read). The prompts are written by hand as bug reports from the
regression tests: symptoms and examples, never file names or the fix.

**Grading** (`visible_after_hidden`):
- **Success:** the upstream regression test modules (hidden) pass.
- **Regression:** the whole suite runs with those modules installed, and
  failures of test methods *defined in* them are ignored, since they are the
  task. Anything else failing (including import errors) is a regression.

**Contamination.** These are public repositories, and a model may have seen
them or the fixes:
- 17 of the 25 fixes are from 2025–2026. Eight are older:
  - Python-Markdown: 2023, 2024, 2024;
  - pyflakes: 2018, 2018, 2023;
  - bottle: 2018, 2024.
- The bug is re-injected into a newer snapshot, so memorising the old diff is
  not enough.
- Any benefit measured on these tasks is still subject to this caveat.

**Sealed:**
- `--split all` (the default) means dev + holdout. `final` is evaluated only
  when named (`--split final`).
- No ranking change was tuned on these tasks. Their localization numbers were
  computed once, for the v0.7.2 report.
