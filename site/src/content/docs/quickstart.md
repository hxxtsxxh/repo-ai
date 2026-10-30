---
title: Quickstart (no agent)
description: Index a repository, get task context, verify a change in a sandbox and read the evidence, without any coding agent.
---

Everything on this page is offline and needs no agent or account. The output shown is real, captured from a small
demo repository (a Python web app with three test files), trimmed where marked with `…`. Absolute paths are
shortened to `.../demo`.

## 1. Index the repository

```sh
cd your-git-project
repo-ai init --agent none
```

```text
  repo-ai … — demo: 25 files, 212 LOC, 2 component(s) [Python, TypeScript]
  agents: none (docs only)   learning: suggest   skills: curated   layout: .repo-ai/context/
  changed 13 file(s)
    create  .gitignore
    create  .repo-ai/config.toml
    (+ 11 generated docs under .repo-ai/context/)
  rules: 0 active, 3 proposed (`repo-ai learn` to review)
```

`--agent none` builds the index and its generated docs under `.repo-ai/` (plus a `.gitignore` block). It writes no
`CLAUDE.md`, skills or hooks. Re-running `init` on an unchanged tree is byte-identical.

`repo-ai quickstart` tells you where you are and what to run next at any point.

## 2. Ask where to start

```sh
repo-ai context "fix the login validation bug"
```

```text
Retrieved by repo-ai for this request. Confidence: high. Task class: auth, bug. …

Verify with: `make test`

| # | File | Why | Look at |
|---|------|-----|---------|
| 1 | `app/auth/login.py` — Login flow: credential validation and token issuance. | keyword match, named like the task, auth path, imported by test_login.py | L1-24 (class LoginError, function validate_credentials) |
| 2 | `tests/test_login.py` | keyword match, named like the task, auth path, imports login.py | whole file (8 lines) |
| 3 | `web/src/components/LoginForm.tsx` | keyword match, named like the task, auth path, imported by LoginForm.test.tsx | L1-10 (function LoginForm) |
…
```

Every row says why it ranked. `repo-ai explain "<task>"` shows the full score breakdown. Off-topic prompts get
nothing rather than a guess.

## 3. See what a file can reach

```sh
repo-ai impact app/auth/login.py      # or: repo-ai impact --changed  (your uncommitted diff)
```

```text
impact of: app/auth/login.py   risk: medium
component(s): demo

direct importers (2):
  app/api/users.py
  tests/test_login.py
transitive importers (1):
  app/main.py  (depth 2)
tests (1):
  tests/test_login.py  [import]
routes in affected files:
  POST /login  app/api/users.py:10
  GET /users/{user_id}  app/api/users.py:15
…
uncertainty:
  - static import graph only: dynamic imports, reflection, dependency injection, plugin registries and string-based routing are not visible
```

## 4. Make a change, then plan verification

After editing `validate_credentials` in `app/auth/login.py`:

```sh
repo-ai verify
```

```text
repo-ai verify: 1 changed file against HEAD

changed
  app/auth/login.py  [source, modified, units: validate_credentials]
      evidence: 1 linked test file(s); runtime evidence none

selected 1 of 3 test files
  tests/test_login.py  [static] imports app/auth/login.py

confidence: MEDIUM: some of the change rests on static evidence only (imports or file names), not on runtime evidence
…
test command: make test   (declared in the project's manifests, CI or docs)
```

The plan is read-only: nothing runs.

## 5. Run the tests, sandboxed

```sh
repo-ai verify --run
```

```text
verifying 1 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…
  command: make test  [declared in the project's manifests, CI or docs]
  isolated copy: 31 files (clone, 0.0s)
  pass    tests/test_login.py (0.4s)
…
PASSED: every selected test passed (the full suite was not run)
  1 passed
  source tree unchanged
  ! no runtime evidence: selection rests on static imports only (`repo-ai verify --record` records which code each test executes)
  …
evidence saved; `repo-ai evidence` shows whether it still covers the working tree.
This covers only the tests that ran; it is not proof the change is correct.
```

Note what it says and does not say: the selected tests passed, the full suite was not run, and the working tree was
not modified. Run `repo-ai verify --run --full` before merging, or `repo-ai verify --record` once for sharper,
runtime-based selection.

## 6. Check the evidence later

```sh
repo-ai evidence
```

```text
verification evidence 2026-10-29T15:30:04-07:00  (seatbelt sandbox)
applies to the current working tree

PASSED: every selected test passed (the full suite was not run)
…
```

Edit the code again and `evidence` will say it no longer covers the working tree.

## 7. Before a pull request

```sh
repo-ai review --changed     # change passport: what the diff touches, tests, risks, blind spots
repo-ai privacy audit        # every store repo-ai keeps, where, and whether it is committed
```

`review` does not read `verify` evidence yet, so it may report "no recorded test run" right after a passing
`verify --run`. It under-claims rather than over-claims.

## 8. Remove it

```sh
repo-ai uninstall --dry-run
```

```text
  dry run — nothing was removed. …
    delete  .gitignore
    delete  .repo-ai/config.toml
    delete  .repo-ai/context/ARCHITECTURE.md
…
    delete  .repo-ai/state/evidence/  (repo-ai state)
```

Next: [Verify a change](/repo-ai/docs/verify/) explains every flag, and [Status matrix](/repo-ai/docs/status/) says
which parts are stable.
