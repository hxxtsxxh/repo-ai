---
title: Missions with agents
description: Plan a task offline with repo-ai do, and optionally let a coding agent produce a candidate in isolation, checked against frozen tests, applied only when you say so.
---

:::caution[Experimental]
Missions are an experimental core. Whether they improve on using a coding agent directly is
`NOT_YET_DEMONSTRATED`. Live runs need a provider CLI that is installed and logged in, explicit consent flags, and
send your task text and the files the agent opens to that provider.
:::

A **mission** is one task: a plan, optionally a candidate change, and the evidence about it. By default
`repo-ai do` only plans, offline, with no provider and no tests.

```sh
repo-ai do "Reject emails with surrounding whitespace in login validation" --dry-run
```

Real output from a clean demo repository:

```text
ASK_APPROVAL: External execution requires verified provider policy, explicit disclosure and budget authorization; planning only; trivial change classification refused unnecessary specialist fan-out
Planning only; no provider or tests invoked.
  app/auth/login.py: keyword match; named like the task; auth path
  web/src/components/LoginForm.tsx: keyword match; named like the task; auth path
  app/api/users.py: keyword match; auth path; imports login.py
  …
Unknowns: static import graph only: dynamic imports, reflection, dependency injection, plugin registries and string-based routing are not visible
Orchestration (trivial): merge_owner=controller
```

On a checkout with uncommitted changes the first line is `BLOCKED: Checkout has changes; planning is available,
execution requires a clean pinned tree`.

## The consent ladder

Each step needs its own flag. Nothing is implied.

| Flag | Authorises |
|---|---|
| *(none)* or `--dry-run` | an offline plan; no persistent repository writes |
| `--run` | local sandboxed tests and candidate edits in a disposable worktree |
| `--allow-live-provider` | invoking an external coding agent, in that isolated worktree |
| `--allow-write PATH` | one source path the candidate may change (repeat per path) |
| `--max-cost-usd N` | an explicit cost ceiling (default zero). A ceiling the provider cannot enforce is refused |
| `--max-seconds N` | a wall-clock bound |
| `--apply` | apply the candidate to your working tree after a fresh PASS (otherwise use `repo-ai apply` later) |

`--agent` chooses the provider: `auto`, `none`, `replay`, `codex`, `claude`, `gemini`, `bob` or `agy`. `auto` routes
deterministically and returns `SELECTED`, `NOT_AUTHORIZED` or `NO_AGENT`; it never falls back to an unusable
provider. See [Providers](/repo-ai/docs/providers/) for which ones actually work.

:::caution[Needs a provider login and explicit consent]
```sh
repo-ai do "Fix duplicate charges under concurrent payment retries" \
  --agent bob --allow-live-provider --run --allow-write payments.py --max-cost-usd 0.5
```
This starts IBM Bob as a child process with network access, under repo-ai's outer sandbox.
:::

## What a run requires and checks

- A **clean, committed** Git checkout, explicit source write paths, pytest or `node --test`, and a supported sandbox
  (seatbelt on macOS, bubblewrap on Linux). **Missions are not supported on Windows.**
- The candidate is produced in a disposable worktree. Tests, test-support trees (`tests`, `fixtures`, …) and test
  configuration are **frozen**: a candidate cannot change them.
- The frozen tests run on the base (baseline) and on the candidate, plus a fresh regression run.
- **PASS** means: the candidate came from an isolated worktree, touched only the paths you allowed, and the enumerated
  checks passed, with a failing baseline that now passes. It does **not** mean the change is correct. Use
  [Requirement coverage](/repo-ai/docs/coverage/) to check the requirements you wrote down.
- Missing baseline failure, empty or incomplete tests, changed test IDs, or source and environment changes prevent a
  PASS. A test (or a whole file) skipped **identically** at the base and on the candidate is allowed; a candidate that
  makes a test skip, or un-skips one, never passes. xfail and skipped suites still prevent a PASS.
- From 0.11.0, if the candidate **removes documentation that states a requirement** (a docstring or comment line with
  words such as "raise", "must", "never", "reject"), the result names it and the claim drops to `ASSURANCE_PARTIAL`.

### Suites with failures the task does not touch (`--expect-fix`)

Real repositories often carry failures unrelated to your task (a missing optional dependency, a legacy test). Without
help, a mission cannot PASS there. Declare the tests the task must fix:

```sh
repo-ai do "separators must be stripped again" --agent claude --run --allow-live-provider \
    --allow-write slugify/slugify.py --expect-fix tests/test_release.py::ReleaseRegressionTests::test_empty_and_whitespace
```

Then PASS requires every declared test to fail at the base and pass on the candidate, and **no test that passed at the
base may fail**. Tests that already failed at the base and are not declared may keep failing: they are listed, and the
standing is `PASS_WITH_PRE_EXISTING_FAILURES` (claim `ASSURANCE_PARTIAL`), never a plain whole-suite PASS. `apply` and
handoff continuations keep the same scope; tournaments do not support it yet.

## Offline: replay proposals

To exercise the whole pipeline without a model, give a simulated proposal:

```json
{"schema":"repo-ai.replay/1","label":"explicit simulated proposal","edits":[{"path":"charge.py","before_sha256":"SHA256_OF_CURRENT_FILE","after":"def charge(amount, retries):\n    return amount\n"}]}
```

```sh
repo-ai do "Fix retries in charge.py" --agent replay --replay proposal.json \
  --allow-write charge.py --run --max-cost-usd 0 --max-seconds 120
```

Keep the proposal outside the clean checkout. `repo-ai demo --directory NEW_EMPTY_DIR` builds a self-contained
zero-cost demo (`--language node`, `--tournament` available); it needs pytest or Node and a supported sandbox.

## Inspecting a mission

All of these read local records only; none invokes a provider or reruns tests.

```sh
repo-ai mission list
repo-ai mission status MISSION_ID
repo-ai why MISSION_ID                 # request → baseline → candidate → regression, with hashes and freshness
repo-ai why-test-failed MISSION_ID     # NEW_FAILURE / PRE_EXISTING_FAILURE / FIXED_IN_OBSERVED_SUITE / UNCHANGED_PASS
repo-ai trace MISSION_ID
repo-ai replay MISSION_ID              # reprints checked stored events
repo-ai mission cancel MISSION_ID
repo-ai mission resume MISSION_ID --run --replay ORIGINAL_FILE   # recover an interrupted replay attempt
```

`why-test-failed` returns `INCONCLUSIVE` (exit 2) when the baseline is missing, test bytes changed, tests were
skipped, results contradict each other or evidence is stale.

## Apply and undo

```sh
repo-ai apply MISSION_ID     # re-verifies, then applies; a passing candidate is never applied automatically
repo-ai undo MISSION_ID      # restores receipt-owned bytes; refuses if you edited the files since
```

`apply` is transactional and runs a post-apply sandboxed test gate with rollback. It refuses on user edits, symlinks,
scope or hash mismatches. It supports **existing regular tracked files only**: additions, deletions, renames,
symlinks and mode changes need manual review. Keep editors quiet during apply; the lock cannot control arbitrary
external writers.

## Providers on this machine

```sh
repo-ai agents list       # static availability; no subprocess, no model call
repo-ai agents doctor     # sandboxed --help/--version probes only; no login check, no model call
repo-ai agents route      # which provider --agent auto would pick, and why
repo-ai agents authorize bob --prefer
repo-ai agents revoke bob
```

`repo-ai agents list` on a machine with all five CLIs installed:

```text
codex: PLANNING_ONLY | version not probed | auth UNKNOWN
claude: PLANNING_ONLY | version not probed | auth UNKNOWN
gemini: PLANNING_ONLY | version not probed | auth UNKNOWN
bob: PLANNING_ONLY | version not probed | auth UNKNOWN
agy: PLANNING_ONLY | version not probed | auth UNKNOWN
No model was invoked. Installed executable does not establish authenticated runnable availability.
```

Readiness observations such as `READY` or `USAGE_LIMITED` come only from real runs, are bound to the provider
binary's hash, and expire.

## Where records live

Mission records stay in the repository's `.repo-ai/` state (at most 64 missions of 2 MB each). Task text is redacted,
raw test output is hashed, and proposals containing recognised secret-shaped material are refused; this is not
complete secret detection. Provider binary paths live in a 0600 sidecar and are not exported. `repo-ai privacy audit`
lists the store; `repo-ai uninstall` removes it.

Related: [Tournaments & shortlist](/repo-ai/docs/tournaments/), [Handoff](/repo-ai/docs/handoff/),
[Security & privacy](/repo-ai/docs/security/#live-provider-runs).
