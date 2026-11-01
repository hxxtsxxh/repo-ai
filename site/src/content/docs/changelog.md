---
title: Changelog
description: Release notes for repo-ai 0.9.0 through 0.11.5, and the pre-releases that led to 0.9.0.
---

A condensed view. The full history, back to 0.4.0, is `CHANGELOG.md` in the source tree.

## 0.11.5

0.11.4 was qualified but never published; its changes are listed here and ship in 0.11.5.

- **Added** `repo-ai agents conformance --acp-executable PATH [--acp-arg ARG]`: a handshake-only conformance kit for
  Agent Client Protocol agents repo-ai has no adapter for. It runs `initialize` alone (no session, no model call) in
  the network-denied probe sandbox, refuses repository-owned executables and reports what the agent advertises. A
  conformant agent is still `PLANNED` for execution. Gemini CLI 0.65.0 conforms; OpenCode 2.2.1 needs network to
  start its ACP mode and does not.
- **Security** the probe sandbox of `agents doctor` (and the kit) did not deny LaunchServices `open` or Apple events
  on macOS, so a probed program could start an application outside the sandbox. It now does; on Linux the probe gets
  its own process namespace.
- **Security** (disclosed, measured) on macOS the OpenCode providers' "loopback only" network reaches no other host,
  but seatbelt's `localhost` rule also admits the machine's own addresses and lets the agent listen on every
  interface. Earlier "loopback-only" wording (0.10.0, 0.11.3) is qualified by this.
- **Security** (opt-in `SAFE_AUTO`) a preregistered unseen-corpus evaluation (skill-vet-fresh-v1) **failed**: 8 of 30
  harmful prose-only skills would have installed without asking, and 6 of 10 harmful script-bearing skills were rated
  `eligible`. The firewall now reads prose for seven instruction-risk classes (a match asks) and reads code for more
  harmful behaviour (now `review` or `blocked`). This is a hardening, not a validated detector: the confirming corpus
  (v2) is not yet available.
- **Added** verify flags failures that look like its sandbox's missing network (`summary.sandbox_network_suspected`;
  no verdict changes).
- **Fixed** in real projects: a build-time version file (setuptools-scm, hatch-vcs) was missing from verify's copy; a
  lint-only `make check` was run as the test suite; `from unittest import TestCase` now marks a unittest suite.
- **Evaluation** speed-v1: `verify --run` took 1.84× the native suite on 30 real commits, a negative result.
  journey-offline-v2: on 7 real upstream fixes, verify never reported a pass for the broken state (0 of 7) and
  confirmed the fix in 3 of 6; uninstall left no tracked or untracked difference in 7 of 7. capability-fresh-v1: the
  capability recommender **failed** (top-3 recall 0.69, gate 0.80); the deterministic matcher is a negative result
  and Skill Radar stays experimental.
- **Tests** provider routing is checked over every provider under macOS and Linux platform names; tests that write
  attack-like fixtures run on CI and are skipped on developer machines unless `REPO_AI_SECURITY_FIXTURES=1`.

## 0.11.3

- **Security** (opt-in, macOS) a credential broker for Codex (`REPO_AI_CODEX_BROKER=1`). Without it, the login's
  token is copied into the run's scratch `CODEX_HOME`, where the model can read it (disclosed). With it, Codex gets a
  per-run dummy key and talks to a loopback proxy in repo-ai, which swaps in the real credential and vets each request;
  the sandbox reaches only that port (and unix sockets in its scratch directory) and cannot read the login's
  directory. Three independent security-review rounds; two live runs with a ChatGPT login on a development build
  (an API-key login is not yet verified). See [Providers](/repo-ai/docs/providers/).
- **Added** `repo-ai do --agent opencode-acp`: OpenCode over the Agent Client Protocol under exactly the `opencode`
  isolation, with an ACP client that applies one permission policy to every ACP agent. The first 64 KiB of its stderr
  are kept and every byte is hashed, with a redacted diagnostic summary. Live $0 PASS with a local `qwen3:8b` on a
  scratch fixture (n = 1).
- **Added** `repo-ai verify --run --show-fixed` names the tests a change fixed, each confirmed alone: failing at the
  base and passing at the change.
- **Changed** a live tournament refuses two providers that run the same executable (`opencode` and `opencode-acp`).
- **Changed** in a scoped mission (`--expect-fix`), a test that errors at setup the same way at the base and on the
  candidate may stand; errors in teardown or the body still make the observation incomplete.
- **Fixed** mission workspaces dropped `export-ignore` files and rewrote `export-subst` ones; `apply` always printed
  "0 failed" after post-apply verification; a custom `out_dir` with `init --agent none` wrote no ignore entries.
- **Fixed** a repository tracking a file named `.repo-ai` failed with a bare `Not a directory`; repo-ai now names the
  file. Sandboxed runs and missions still need a `.repo-ai/` directory and stay unavailable in such a repository.
- **Security** whatever exists at a repo-ai state path after a mission workspace is built is removed, however it got
  there (a case-insensitive filesystem let a tracked link reach `.claude/`; it stayed inside the workspace).
- **Faster** on APFS, a parallel test process's workspace is one copy-on-write clone (about 0.07 s against 0.31 s per
  process on repo-ai's own 2,742-file tree).

## 0.11.2

- **Fixed** (found on python-humanize) mission tests ran with the first `python3` on PATH instead of the project's
  virtualenv; a tracked file that `.gitignore` also matches was dropped from mission workspaces; `init`'s managed
  `.gitignore` block made the next `repo-ai do` refuse a "dirty checkout".
- **Fixed** `verify --run --full` printed "0 passed" when no test file was selected; for pytest it now quotes
  pytest's own final line when it agrees with repo-ai's per-test report.
- **Changed** `skills recommend` / `explain` count a local skill as relevant when it names one of the repository's own
  packages. Advice only: autopilot never installs on this ground.

## 0.11.1

- **Fixed** `repo-ai init` followed by `repo-ai do` failed either way: repo-ai's own `.repo-ai/` files made the
  checkout dirty, or, once committed, were read as a provider deleting them.

## 0.11.0

- **Added** `repo-ai do --expect-fix TEST` for real suites with failures the task does not touch: the declared tests
  must fail at the base and pass on the candidate, and nothing that passed may fail. The result is
  `PASS_WITH_PRE_EXISTING_FAILURES` (`ASSURANCE_PARTIAL`), never a plain PASS. See [Missions](/repo-ai/docs/missions/).
- **Added** requirement erasure: a candidate that deletes documentation stating a requirement ("raise", "must",
  "never") is named, and a clean PASS drops to `ASSURANCE_PARTIAL`; it never changes a verdict. Observed live on
  0.10.0: a local model removed "Raise ValueError if lo > hi" with the behaviour, and the visible tests passed. Python
  lines are placed with the parser; JS/TS use a diff heuristic.

## 0.10.0

- **Added** Claude Code as an isolated `repo-ai do` provider (blocked in 0.9.0), with its own supported login and
  nothing copied; file tools only, and every live run first confirms at no cost that no other tool, MCP server,
  plugin or skill would load.
- **Added** OpenCode with a local model: loopback-only network, deny-by-default tools, cloud-routed models refused.
- **Security** no Claude or Gemini credential file is copied into the sandbox any more (0.9.0 copied Claude
  credential files and the whole `~/.gemini`). Codex's login token still is, readable by its model (disclosed; see
  the 0.11.3 broker), and so is Bob's `~/.bob/settings`; see [Security](/repo-ai/docs/security/#live-provider-runs).
  Every process a seatbelt run starts is killed before verification; Codex runs are HOME read-restricted. An
  independent adversarial review's findings are fixed.
- **Added** skills safe autopilot: autonomy levels (default PROPOSE), a strict inert check, installs with ownership
  markers and byte-exact uninstall and rollback.
- **Added** `repo-ai agents catalog`: 24 coding agents and what repo-ai can honestly do with each.
- **Evidence** comparative lift over a standalone agent remains `NOT_YET_DEMONSTRATED`; skill benefit is not
  demonstrated.

## 0.9.0

The first release of the 0.9 line. It collects the pre-releases below: missions, live providers, tournaments,
handoff, `shortlist` and `coverage`, on top of the 0.8 verification engine. See [Install](/repo-ai/docs/install/)
for how it is distributed. Comparative lift over a plain provider remains `NOT_YET_DEMONSTRATED`.

- **Changed** the PyPI distribution is `repo-ai-cli` (the command stays `repo-ai`); uninstall a pre-release
  `repo-ai` wheel first. See [Install](/repo-ai/docs/install/#upgrade).
- **Fixed** first-run `verify` on plain pytest-style tests (top-level `def test_*()` without `import pytest`), which
  found no runner before.
- **Fixed** handoff continuations silently ignoring `--allow-write`; user-added paths now widen the scope and are
  recorded (a capsule still cannot widen anything).
- **Added** `shortlist` reports candidates whose Python code is identical apart from comments and formatting.
- **Fixed** `coverage` text showing pytest identities twice; a dirty-checkout block now names the changed paths.
- **Added** a CLI reference generated from the parser, a release workflow with SBOM, checksums, provenance and PyPI
  Trusted Publishing, this site, and community files.
- **Evidence** (n = 1 each, synthetic tasks): live Codex mission with coverage, apply and undo; live Codex + agy
  tournament that abstained, then `shortlist`; live Codex → agy handoff that carried verified partial work.

## 0.9.0.dev4 (pre-release candidate)

- **Added** `repo-ai coverage MISSION_ID --requirements FILE`: checks a developer-declared requirement-to-test map
  (`repo-ai.requirements/1`) against observed per-test outcomes. `task_correct` is always `CLAIM_UNVERIFIED`; exit 0
  only for `ACCEPTANCE_MAPPED_ALL`. See [Requirement coverage](/repo-ai/docs/coverage/).
- **Added** the abc-v4 preregistered pilot. Codex arm A was correct on both tasks, so arms B and C were not run: a
  fourth study at the ceiling.
- **Fixed** `privacy audit` crashing when another process deleted a file during its walk.
- **Changed** `shortlist` output points to `coverage` and restates that PASS is not task correctness.

## 0.9.0.dev3 (pre-release candidate)

- **Added** `repo-ai shortlist COMPARISON_ID [--policy strict|smallest-diff]` for abstained tournaments: an evidence
  table, with an opt-in, labelled `POLICY_PREFERENCE`. It never applies anything.
- **Added** claims that name scope words a requirement uses but the tests never do (`unechoed_qualifiers`), as a
  heuristic prompt only.
- **Added** `status_class` in `agents route` (`NOT_INSTALLED`, `NOT_AUTHORIZED`, `BLOCKED_AUTH`, `BLOCKED_QUOTA`,
  `BLOCKED_SANDBOX`, `UNSUPPORTED`, `ISOLATED_READY`).

## 0.9.0.dev2 (GitHub pre-release)

- **Added** a claim taxonomy separating "frozen tests observed a pass" from "task correct".
- **Added** the live multi-provider tournament, `--tournament A,B[,C]`: one distinct passing candidate wins; several
  distinct passes, a crash, a no-op or a baseline mismatch abstain.
- **Added** provider readiness states, observed only from real runs and bound to the binary hash; handoff attack tests;
  the abc-v3 study and tournament and handoff demos.
- **Docs** the Codex inner-sandbox bypass and agy keychain-file read in the security notes.

## 0.9.0.dev1 (GitHub pre-release)

- **Added** the Antigravity `agy` adapter (macOS seatbelt only).
- **Added** capability-based provider routing (`agents route`, `authorize`, `revoke`); `--agent auto` returns
  `NO_AGENT` or `NOT_AUTHORIZED` instead of defaulting to a provider.
- **Added** a change-exercise disclosure; Codex runs under repo-ai's outer sandbox.
- **Evaluation** abc-v2 with Codex: all cells correct, a ceiling effect.

## 0.9.0.dev0 (GitHub pre-release)

- **Added** `repo-ai do` offline plans; isolated candidate execution with baseline and regression observations;
  `why`, `why-test-failed`, `compare`, transactional `apply` / `undo`, `handoff` and `--from-handoff`.
- **Added** live provider execution behind `--allow-live-provider --run`, with a sandboxed scratch HOME and a hard USD
  cap where the provider supports one (IBM Bob).
- **Fixed** candidate diffs losing their final newline (found by the abc-v1 study).
- **Privacy** provider executables and workspaces are stored as basenames; absolute binary paths go in a 0600 sidecar.

## 0.8.0rc1 (release candidate, not released)

- **Added** `repo-ai verify`, `verify --run`, `verify --record`, `repo-ai evidence` and the opt-in `verify --gate`
  completion gate: the verification engine, qualified *conditional with explicit limitations* on `903984a` for pytest
  and `node --test`.
- **Added** `repo-ai prove` (ProofLab), experimental and not qualified.
- **Fixed** many attribution and isolation defects found by four independent pre-release reviews, each with a
  regression test.
