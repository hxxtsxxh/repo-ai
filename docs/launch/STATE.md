# Launch state (living checkpoint)

Controlling order: `docs/launch/CLAUDE_ULTIMATE_PRODUCT_LAUNCH_MISSION.md` (user-supplied, untracked; preserved as-is).
Gate registry: [ACCEPTANCE.json](ACCEPTANCE.json). Queue: [WORK_QUEUE.md](WORK_QUEUE.md). Decisions: [DECISIONS.md](DECISIONS.md).
Evaluation: [EVALUATION.md](EVALUATION.md). Final report: [LAUNCH_REPORT.md](LAUNCH_REPORT.md).

**Launch status: `NOT_LAUNCHED`.** Nothing below is a public launch until G15/G16/G18/G21 pass.

## Baseline (verified 2026-10-29, by command, not from the mission text)

| Fact | Verified value | How |
|---|---|---|
| Checkout | local checkout, branch `main` = `origin/main` = `2d64217db66676d8f72cf45e06b81c6fb0718d96` | `git rev-parse HEAD origin/main` after `git fetch` |
| Working tree | clean except untracked user/agent dirs `.claude/` (worktrees), `.serena/`, `docs/launch/` (mission file) | `git status --short` |
| Visibility | **PRIVATE**, MIT licence file, description still "for Claude Code and IBM Bob" | `gh repo view` |
| Default branch protection | **none** (`Branch not protected`) | `gh api …/branches/main/protection` |
| GitHub Pages | not configured (404) | `gh api …/pages` |
| GitHub plan | Pro (Pages available for private repos; Actions minutes billed past quota) | `gh api user` |
| Releases | `v0.9.0-dev0..dev4` pre-releases (dev4 published 2026-10-29T20:22Z); `v0.8.0rc1` draft; `v0.7.7` is the GitHub "Latest" | `gh release list` |
| PyPI | project name `repo-ai` **unregistered** (`/pypi/repo-ai/json` → 404); no `~/.pypirc`; no PyPI credential in this session | `curl` |
| Version in tree | `0.9.0.dev4` (`src/repo_ai/__init__.py`) | file |
| Open PRs | #52 (draft, evidence graph), #57 (draft, BM25 prototype) — historical, untouched | `gh pr list` |
| Open issues | #47 (Session A ledger), #55, #56, #59 (ProofLab false proofs / host-exec finding) | `gh issue list` |
| CI | `ci.yml`: lint, ubuntu py3.10–3.14, windows py3.10/3.13, macOS on push/tag only, docker sandbox, bwrap sandbox. Last 5 runs green (main `2d64217` run 40952185072) | `gh run list` |
| CI cost | **Billable**: Oct 2026 usage on this repo shows Windows 6722 min ($57.73 net) and macOS 642 min ($37.40 net). Each full CI run ≈ $1–2.5. Public repos get standard runners free | `gh api /users/hxxtsxxh/settings/billing/usage` |
| Tooling | Claude Code 2.1.312; gh (github.com account `hxxtsxxh`, scopes repo/workflow/user/gist/read:org; a second, enterprise GitHub login exists on this host and is never used for this project); Python 3.12.14 / 3.13; Node 24.19.0; uv; pipx; podman | `--version` |
| Providers on PATH | codex-cli 0.165.0, agy 1.4.9, bob 2.0.9, gemini, claude 2.1.312. `repo-ai agents list` (offline): all `PLANNING_ONLY`, auth UNKNOWN, no model invoked | `repo-ai agents list` |
| Worktrees | ~60 pre-existing worktrees (scratchpad of earlier sessions, `dist/reality-engine/*`, sibling `repo-ai-*` dirs, agent-lab). **All preserved; none created by earlier sessions may be deleted by this mission.** | `git worktree list` |

## Supplied facts vs verification

| Supplied claim (mission §1) | Status |
|---|---|
| dev4 is a GitHub prerelease, not PyPI | **verified** |
| main at `2d64217`, PRs #67/#68 merged | **verified** |
| Repo is private | **verified** |
| dev4 qualification 2246/2238/8 xfail at `9822624` | recorded in `docs/roadmap/FINALIZATION-ACCEPTANCE.md`; artifacts in ignored `dist/reality-engine/qual-dev4-9822624/` — not re-run (no source change yet) |
| Installed Cachetools/Marked journeys were replays | **verified** from the acceptance row (`live:false`) |
| Comparative lift `NOT_YET_DEMONSTRATED` | **verified** from `benchmarks/abc-v4/RESULTS.md` and STATUS |
| Live Claude inside repo-ai blocked | per records; not re-tested yet |
| Prior observed spend ≈ $2.56 | **incomplete**: memory of earlier sessions records $33.78 of Claude-eval spend (Oct 20–21) plus ≈ $8.61 of approved CI spend, plus untracked CI since. Live-model spend ledger to be reconstructed in EVALUATION.md; subscription costs stay UNKNOWN |

## Known defects / limits carried in (from STATUS and issues)

- ProofLab: open false proofs (#55, #59), uncertified; experimental and excluded.
- #56: `prove status/report` may execute an untracked repo `.venv/bin/python` on the host without `--run` consent (security finding, open).
- verify: speed target missed on short suites; Jest/Vitest/Mocha unsupported; Windows has no host sandbox.
- Capability discovery and plugin vet failed their fresh validations (experimental).
- `shortlist` exercised only with fake providers; live Claude execution blocked; Gemini rejected.
- README/pyproject still market "Claude Code and IBM Bob" although the product is provider-neutral.

## Ranked launch-critical gaps (initial)

1. **G18 publication audit** of all origin refs, history, issues/PRs and release assets (running: read-only auditor). Visibility flip needs owner approval.
2. **G16 stable package**: version decision, metadata, Trusted Publishing workflow; PyPI pending-publisher needs a one-time owner action on pypi.org.
3. **G14/G15 site**: no site exists. Building `site/` (Astro + Starlight); hosting on GitHub Pages needs a Pages enablement and a (cheap, billable while private) Actions run.
4. **G17 GitHub readiness**: no CONTRIBUTING / CODE_OF_CONDUCT / root SECURITY / templates / release workflow / branch protection.
5. **G13 docs**: no CLI reference generated from `--help`; README is long and partly historical.
6. **G05/G07/G08/G20 live journeys**: live shortlist with real candidates never run; live journeys from the installed wheel.
7. **G12 clean-environment onboarding** on Linux container + macOS clean venv.
8. **G19** prospective study: previous four studies at ceiling; needs a new preregistered design focused on an outcome repo-ai can plausibly move.
9. **#56** host execution without consent: fix before a public launch.

## Constraints in force

- No purchases, billing changes, credential exposure, or visibility change without a publication audit and explicit approval.
- CI on the private repo is billable: PRs from this mission carry `[skip ci]` until the owner approves a CI budget or the repo is public; local free equivalents (macOS host suite, Linux podman) are used instead and labelled as such.
- Live provider calls: bounded, recorded, subscription cost UNKNOWN (never 0); cumulative envelope ≈ $150 per the mission.

## Next command

See the top unblocked item in [WORK_QUEUE.md](WORK_QUEUE.md).
