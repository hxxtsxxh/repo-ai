# repo-ai launch report

**Status: `PUBLIC_LAUNCH_COMPLETE` for 0.9.0 (beta)** — public source, PyPI package and website are live and were
verified externally on 2026-10-29/30. Comparative lift over a standalone coding agent remains **`NOT_YET_DEMONSTRATED`**;
the abc-v5 confirmatory study is open (see [Follow-ups](#follow-ups)).

## Published

| What | Where | Identity |
|---|---|---|
| Public source | <https://github.com/hxxtsxxh/repo-ai> (anonymous clone verified) | `main` = tag `v0.9.0` = `7ca4c51449a2decb3034c011980207449e1198ea` (curated single-commit export of private `2ea271c`; `src/`, `tests/` byte-identical to freeze `9663ac3`) |
| PyPI | <https://pypi.org/project/repo-ai-cli/0.9.0/> — `pipx install repo-ai-cli` (command `repo-ai`) | wheel `b351d80e737764d749c52ed0f9af8d96c5e3ec313ed25f68ca743ab2238db17f`, sdist `b328ca0feb1d4648946e2e7d23d50ca389f257a1be10f6773f6844756898552d` |
| GitHub release | <https://github.com/hxxtsxxh/repo-ai/releases/tag/v0.9.0> | same two files + `SHA256SUMS` + CycloneDX SBOM; provenance attestations (`gh attestation verify … -R hxxtsxxh/repo-ai`: ok) |
| Release workflow | <https://github.com/hxxtsxxh/repo-ai/actions/runs/40985177161> | build, sdist→wheel identity, 3-OS smoke, attest, Trusted Publishing, release |
| Public CI on `main` | <https://github.com/hxxtsxxh/repo-ai/actions/runs/40982021533> | 13/13 jobs green (Linux py3.10–3.14, Windows py3.10/3.13, macOS, docker and bwrap sandboxes, offline eval, benchmark, lint) |
| Landing site | <https://hxxtsxxh.github.io/repo-ai/> | Pages run 40982105858; all 19 sitemap URLs 200, real 404, TLS ok |
| Documentation | <https://hxxtsxxh.github.io/repo-ai/docs/> | Starlight with search; CLI reference generated from the parser |
| Private development history | `hxxtsxxh/repo-ai-dev` (private; renamed from `repo-ai`) | history, releases v0.5.1…v0.9.0-dev4, issues and PRs preserved; all local `origin` remotes repointed |

**Installation transcript (summary).** In a fresh `python:3.12-slim` container with only `git` added,
`sh scripts/release_smoke.sh 'repo-ai-cli==0.9.0' 0.9.0` installed from the default PyPI index and passed: version
0.9.0 from site-packages, `pip check`, `quickstart`, `agents list`, `do --dry-run`, `init --agent claude`, `verify`
(test linked, pytest inferred), `verify --run` refused honestly (no sandbox), `privacy audit`, `uninstall` (user
`CLAUDE.md` lines kept, clean `git status`). The same script passed with bubblewrap (sandboxed `verify --run`
PASSED) and on macOS (seatbelt).

## Product

repo-ai is a local-first CLI that tells you what a change touched, which tests can show a break, and what running
them in a sandbox against the base actually showed — never more — with optional, consented, isolated coding agents.
Its measured value is honest evidence: it **names the requirements your tests do not pin and resists test gaming**;
it does not judge semantic correctness, and comparative lift over a standalone agent is `NOT_YET_DEMONSTRATED`.

## Release identifiers (freeze)

| Item | Value |
|---|---|
| Version | `0.9.0` (final, beta; pre-1.0 CLI — see DECISIONS L-002); PyPI distribution `repo-ai-cli` (L-008) |
| Freeze commit (private development history) | `9663ac3ad0145c1100f7a1a3204d7225e408c5d8` (tree `d83320bb`); later commits change only docs, site content and launch tooling |
| Wheel / sdist sha256 (local freeze build) | `b351d80e737764d749c52ed0f9af8d96c5e3ec313ed25f68ca743ab2238db17f` / `0f1802e407003f67bc9e75868f00b5e060d8999e94dd3fa0b54dbb3fad306b96`; wheel rebuilt from sdist byte-identical |
| Public export | single commit (noreply author) built by `scripts/public_export.py`; its SHA is recorded in the published section below |

## Gate matrix

See [ACCEPTANCE.json](ACCEPTANCE.json) for evidence paths, SHAs and limitations. Summary at the freeze:

<!-- gate-table:begin -->
Launch status in the registry: `PUBLIC_LAUNCH_COMPLETE`. Counts: PASS 22.

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
| G15 | **PASS** | 7ca4c51 | Fetched over the public internet from the development host (not a second network). Rollback: re-run pages.yml on an earlier commit (workflow_dispatch) or disable Pages in settings. robots.txt under a project path is not… |
| G16 | **PASS** | 7ca4c51 | Published by Trusted Publishing (OIDC; no token). Wheel sha256 b351d80e… is byte-identical to the local freeze build and to a wheel rebuilt from the sdist; sdist b328ca0f… (built from the public tree; differs from the l… |
| G17 | **PASS** | 6c3b40c | test-macos is skipped on pull requests by its own condition and runs on main pushes and tags (green on 7ca4c51). No force-push or bypass; historical tags/releases untouched (they live on the private repo-ai-dev). |
| G18 | **PASS** | 7ca4c51 | Owner chose the curated export (L-009). Public history is one commit by the noreply address; the export audit (corporate address, local paths, enterprise host, private-only text) and gitleaks (42 verified false positive… |
| G19 | **PASS** | 509e54f | Mission §9 fallback taken and declared: harness built and validated (sealed grader, negative controls, immutable manifests, exact power), bounded calibration run (n=4 synthetic, single author, $0), primary result NOT_YE… |
| G20 | **PASS** | 9663ac3 | Real executables/auth/sandbox exercised for Codex 0.165.0 and agy 1.4.9 (macOS); Claude 2.1.312 re-observed as BLOCKED_AUTH in the isolated HOME and labelled so; Bob not re-run; Gemini not tried. n=1 workflows. |
| G21 | **PASS** | 7ca4c51 | Re-downloaded PyPI and GitHub assets: identical bytes, SHA256SUMS OK, attestations verified; wheel == freeze build. pip install repo-ai-cli==0.9.0 from the default index: scripts/release_smoke.sh PASS on a clean Linux c… |
| G22 | **PASS** | 6c3b40c | The report states what was not shown: comparative lift NOT_YET_DEMONSTRATED; abc-v5 confirmatory phase not run; Windows missions unsupported; Claude isolated execution blocked. |
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

## Follow-ups

Nothing blocks the launch. Open items, in priority order:

1. **abc-v5 confirmatory study** (G19 limitation): 24 upstream tasks with blinded authors (humans, or separate AI
   sessions after the owner approves ≈ $15–40), then an approved cap for model-generated candidates. Until then the
   primary result stays `NOT_YET_DEMONSTRATED`.
2. **PyPI publisher environment**: the pending publisher was created with environment "(Any)"; pin it to `pypi` on
   the project's publishing settings for defence in depth (GitHub already restricts the `pypi` environment to `v*` tags).
3. **Development flow**: the public repository is now canonical. New work should branch from public `main` and merge
   by pull request (branch protection requires the 12 PR checks, admins included). The private `repo-ai-dev` keeps
   history only.
4. Windows has no host sandbox (container backend only) and missions are unsupported there; Claude Code as an
   isolated execution provider stays blocked; Gemini was not re-tried.
