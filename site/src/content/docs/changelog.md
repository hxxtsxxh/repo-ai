---
title: Changelog
description: Release notes for repo-ai 0.9.0 and the pre-releases and release candidate that led to it.
---

A condensed view. The full history, back to 0.4.0, is `CHANGELOG.md` in the source tree.

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
