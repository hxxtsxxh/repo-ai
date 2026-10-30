# repo-ai launch report

**Status: `ENGINEERING_READY_PENDING_PUBLICATION`** — not `PUBLIC_LAUNCH_COMPLETE`. The release candidate is built,
qualified locally and documented; publication (public source, PyPI, website) waits on owner actions listed in
[Blocked items](#blocked-items-and-the-exact-owner-actions). No public URL below exists until those steps run.

## Product

repo-ai is a local-first CLI that tells you what a change touched, which tests can show a break, and what running
them in a sandbox against the base actually showed — never more — with optional, consented, isolated coding agents.
Its measured value is honest evidence: it **names the requirements your tests do not pin and resists test gaming**;
it does not judge semantic correctness, and comparative lift over a standalone agent is `NOT_YET_DEMONSTRATED`.

## Release candidate

| Item | Value |
|---|---|
| Version | `0.9.0` (final, beta; pre-1.0 CLI — see DECISIONS L-002); PyPI distribution `repo-ai-cli` (L-008) |
| Freeze commit (private development history) | `9663ac3ad0145c1100f7a1a3204d7225e408c5d8` (tree `d83320bb`); later commits change only docs, site content and launch tooling |
| Wheel / sdist sha256 (local freeze build) | `b351d80e737764d749c52ed0f9af8d96c5e3ec313ed25f68ca743ab2238db17f` / `0f1802e407003f67bc9e75868f00b5e060d8999e94dd3fa0b54dbb3fad306b96`; wheel rebuilt from sdist byte-identical |
| Public export | single commit (noreply author) built by `scripts/public_export.py`; its SHA is recorded in the published section below |

## Gate matrix

See [ACCEPTANCE.json](ACCEPTANCE.json) for evidence paths, SHAs and limitations. Summary at the freeze:

<!-- gate-table:begin -->
Launch status in the registry: `NOT_LAUNCHED`. Counts: BLOCKED_EXTERNAL 1, INCONCLUSIVE 1, NOT_RUN 5, PASS 15.

| Gate | Result | At | Limits / blocker |
|---|---|---|---|
| G01 | **PASS** | 9663ac3 | Scope, stable/experimental/unsupported labels and limits are stated in README, STATUS and the site; thesis is falsifiable and was narrowed after the abc-v5 calibration (L-007). Workflows backing it are recorded in evide… |
| G02 | **PASS** | 9663ac3 | No agent installed (clean containers): quickstart, agents list/route (NO_AGENT, all NOT_INSTALLED), do --dry-run, init, context, impact, verify (linked test, inferred pytest), verify --run (sandboxed where a backend wor… |
| G03 | **PASS** | 9663ac3 | Zero (container: NO_AGENT), many (host: NOT_AUTHORIZED without consent; no billable call in list/route/doctor/dry-run), one real provider through the sanctioned path (Codex, agy). Claude re-observed BLOCKED_AUTH from a … |
| G04 | **PASS** | 9663ac3 | Full suite incl. hostile-repository, symlink/traversal, sandbox-escape and #56 tests on macOS; Linux bwrap suites in a privileged container; independent adversarial review (fixed). OS limits disclosed: Windows has no ho… |
| G05 | **PASS** | 9663ac3 | Synthetic constructed tasks, n=1 per build; Codex and agy only; macOS seatbelt; same author wrote task, tests and hidden oracle. |
| G06 | **PASS** | 9663ac3 | PASS never means correct (claims + coverage CLAIM_UNVERIFIED); stale/changed/skipped/interrupted/no-op handled by tests; this cycle fixed a launcher failure being reported as pre-existing failures. abc-v5 calibration sh… |
| G07 | **PASS** | 9663ac3 | Live runs: one abstention with distinct passing diffs (dfb6880) and one byte-identical pair resolved by the equivalence rule (9663ac3). A behaviourally different live tie was not exercised; the AST same-code report is c… |
| G08 | **PASS** | 9663ac3 | Constructed scenario (stage A scoped to one file to force partial progress), n=1 per build; seed reuse confirmed byte-identical. |
| G09 | **PASS** | 9663ac3 | Baseline/new/pre-existing/fixed separated per test; leads labelled static, never causal. No new held-out evaluation of diagnosis quality this cycle. |
| G10 | **PASS** | 9663ac3 | Inventory/vet are read-only stable candidates; discovery, install, trials and plugin inspection are labelled experimental (their fresh validations failed); skill text is never executed. Accepted as clearly experimental … |
| G11 | **PASS** | 9663ac3 | futures/rehearsal and impact are labelled static/heuristic with uncertainty lines; no certainty is marketed. Calibration of risk prediction is not measured (stated). |
| G12 | **PASS** | 9663ac3 | Clean macOS venv; clean python:3.12-slim container (no sandbox); privileged container with bwrap; upgrade from the published dev4 wheel to repo-ai-cli 0.9.0 keeps state; uninstall keeps user CLAUDE.md edits and restores… |
| G13 | **PASS** | 9663ac3 | Site tutorial snippets are not executed in CI (release_smoke.sh covers the first-run path). |
| G14 | **PASS** | 91780ad | Local build and Playwright/axe QA only: 20 pages x light/dark x 390/1440 px, 0 axe violations, 0 broken of 1,103 internal links/anchors, no overflow at 390/768/1440, 0 third-party requests, landing 19 KB gzipped. Lighth… |
| G15 | **NOT_RUN** | – |  |
| G16 | **NOT_RUN** | – |  |
| G17 | **NOT_RUN** | – |  |
| G18 | **BLOCKED_EXTERNAL** | 2d64217 | Audit of all 166 origin refs, 5566 blobs, issues/PRs/releases: no real credentials, no IBM-internal material. High: F01 corporate author email on 8 commits (4 reachable from main and tags); F02 sealed-v2/held-out labels… |
| G19 | **INCONCLUSIVE** | 509e54f | Prospective study designed and preregistered with immutable manifests, sealed grader, negative controls and exact power calculation; calibration run only (n=4 synthetic, single author). Calibration falsified the strong … |
| G20 | **PASS** | 9663ac3 | Real executables/auth/sandbox exercised for Codex 0.165.0 and agy 1.4.9 (macOS); Claude 2.1.312 re-observed as BLOCKED_AUTH in the isolated HOME and labelled so; Bob not re-run; Gemini not tried. n=1 workflows. |
| G21 | **NOT_RUN** | – |  |
| G22 | **NOT_RUN** | – |  |
<!-- gate-table:end -->

## What changed in this cycle (all with failing-first tests unless noted)

- First-run `verify` works on plain pytest-style projects (`c4b0956`).
- bwrap sandbox that cannot start is reported as "nothing was verified", never as test results; probe mirrors real
  mounts; toolchains under `/tmp` stay visible (`4146f6b`).
- Handoff continuation honours user `--allow-write` (`c505f74`); `shortlist` reports AST-identical candidates
  (`5e8dccf`); auth failures are not "transient retry" (`fb831bc`); `coverage` text identity and
  `NOT_DISCRIMINATING` explanations corrected (`8bb4fe4`, `b14b4aa`); dirty-checkout block names the paths.
- #56 end-to-end regression test (`5db8e33`); CLI reference generated from the parser and checked in CI.
- Release workflow (Trusted Publishing, SBOM, checksums, provenance, 3-OS smoke), Pages workflow, community files,
  launch README, Astro + Starlight site, version 0.9.0.
- abc-v5 preregistered false-green study with sealed grader and calibration run; thesis narrowed (L-007).

## Evidence

- Live provider journeys (installed wheel, macOS): [evidence/LIVE-JOURNEYS-2026-10-29.md](evidence/LIVE-JOURNEYS-2026-10-29.md).
- Clean Linux container journeys (fresh install, upgrade from published dev4, uninstall preserving user edits,
  bwrap negative and positive): ignored `dist/launch/onboard-4d77f86/`, `dist/launch/bwrapfix*/`.
- Publication audit: [PUBLICATION_AUDIT.md](PUBLICATION_AUDIT.md).
- Evaluation and spend: [EVALUATION.md](EVALUATION.md).
- Freeze qualification: [evidence/FREEZE-9663ac3.md](evidence/FREEZE-9663ac3.md) (2274 collected, 2266 passed, 8 xfailed, 0 failed).

## Platform and provider matrix

| | macOS | Linux | Windows |
|---|---|---|---|
| Install, index, context, impact, plans | verified (host, clean venv) | verified (clean `python:3.12-slim` container) | CI unit tests only (not run this cycle; billable) |
| `verify --run` | seatbelt, verified | bubblewrap, verified in a privileged container; refuses honestly where bwrap cannot start | container backend only |
| Missions | verified live (Codex, agy, Bob earlier) | bwrap suites pass; no live mission this cycle | not supported |

Providers through `repo-ai do`: Codex and agy live-verified this cycle (n=1 workflows each); Bob earlier; Claude Code
blocked as an isolated execution provider (re-observed: "Not logged in" in the scratch HOME; supported as a host);
Gemini rejected earlier, not retried.

## Security and privacy

Local only, no telemetry, explicit network commands, sandboxed test execution in disposable copies, symlink and
traversal protection, secrets quarantined, repository text treated as data. This cycle: the bwrap launcher fix (a
fail-closed improvement), the #56 regression test, and an independent adversarial review of the cycle's source
changes (no path to a false PASS; 2 medium and 5 low findings, all fixed with failing-first tests before the freeze). Threat model: `docs/SECURITY.md`, `docs/VERIFY-THREAT-MODEL.md`.

## Budget

Known model spend ≈ $34.3 of the ≈ $150 envelope (all from earlier cycles); this cycle's Codex (4) and agy (3) calls
are subscription-billed, cost UNKNOWN; one Claude probe failed authentication before any model call. No GitHub
Actions run was triggered this cycle (every commit carries `[skip ci]`).

## Blocked items and the exact owner actions

Everything below needs the owner. Nothing here has been done; no URL in this section exists yet.

**Decision 1 — how the source becomes public (G18).** The audit ([PUBLICATION_AUDIT.md](PUBLICATION_AUDIT.md))
found no credentials, but the private history carries a corporate author address on 8 commits and the sealed-v2 /
held-out evaluation sets, which only a history rewrite could remove (and `refs/pull/*` cannot be rewritten by the
owner). Options:

- **(a) Recommended: publish the curated export as `hxxtsxxh/repo-ai`.** One commit (noreply author), built and
  audited by `scripts/public_export.py` from the freeze commit; the full test suite passes on it (see Evidence). Steps
  the integrator runs after approval: rename the private repository to `hxxtsxxh/repo-ai-dev`
  (`gh repo rename repo-ai-dev`); repoint this checkout's and every worktree's `origin` to `repo-ai-dev` **before**
  anything else, so private branches can never be pushed to the public repository; create the public
  `hxxtsxxh/repo-ai` from the export and push only `main`; enable private vulnerability reporting, a `pypi`
  environment and branch protection on `main`. Historical releases `v0.5.1…v0.9.0-dev4` stay on the private
  repository unchanged.
- (b) Flip the existing repository to public, accepting the corporate address and the sealed sets in history.
- (c) Stay private: G18 cannot pass; the package and site can still ship, but their source links would not resolve.

**Decision 2a — the PyPI distribution name (G16).** `repo-ai` **cannot be registered on PyPI**: Warehouse rejects a
new name whose "ultranormalized" form (lowercase, `.`/`_`/`-` removed, `o`→`0`, `i`/`l`→`1`) equals an existing
project's, and the unrelated project `repoai` (0.0.4) normalizes to the same `rep0a1`
(`warehouse/packaging/services.py`, `ProjectNameUnavailableSimilarError`; checked 2026-10-29). Recommended: publish the
distribution as **`repo-ai-cli`** (`pipx install repo-ai-cli`) while the command, import package and brand stay
`repo-ai`; `repo-ai-cli` and its separator-free form are unclaimed. The rename touches `pyproject.toml`, the release
workflow's PyPI URL, the site config and install docs, and the pending-publisher entry below.

**Decision 2b — PyPI Trusted Publisher (G16), owner-only account action, about 2 minutes.** On
<https://pypi.org/manage/account/publishing/> → "Add a new pending publisher" → GitHub: PyPI project name `repo-ai-cli` (or the chosen name),
owner `hxxtsxxh`, repository `repo-ai`, workflow `release.yml`, environment `pypi`. (A pending publisher reserves nothing until the first upload, so do this shortly before the tag.) No token is created or shared.

**Decision 3 — publish (G15, G16, G21).** After 1 and 2: enable GitHub Pages (source: GitHub Actions) on the public
repository; run `pages.yml`; push tag `v0.9.0` on the public `main`, which runs `release.yml` (build, sdist→wheel
identity, SBOM, checksums, 3-OS smoke, provenance, PyPI, GitHub release). On a public repository these Actions runs
are free; on the private one they are billed (≈ $1–2.5 per full CI run; Pages ≈ $0.01–0.02).

**Then the integrator verifies externally (G21):** anonymous `git clone https://github.com/hxxtsxxh/repo-ai`;
`sh scripts/release_smoke.sh 'repo-ai-cli==0.9.0' 0.9.0` in a fresh container; re-download the release assets and PyPI
files and compare against `SHA256SUMS` and the freeze hashes; `gh attestation verify`; fetch
`https://hxxtsxxh.github.io/repo-ai/` and `/docs/` (status, TLS, sitemap, 404, metadata); then set
`site/src/config.ts` `pypiPublished`/`repoPublic` to true and redeploy.

**Not blocked on the owner but not done:** the abc-v5 confirmatory phase (needs blinded task authors: humans, or an
approved ≈ $15–40 for separate AI authoring sessions, and later an approved cap for model candidates); Windows was
not run this cycle (CI is billable while private; it becomes free once public).
