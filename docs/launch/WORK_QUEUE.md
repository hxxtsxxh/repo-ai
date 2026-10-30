# Launch work queue (ranked)

Status: `todo` / `doing` / `done` / `blocked(ext)`. Owner: I = integrator (lead session), SEC = read-only security auditor, WEB = site worker, EVAL = evaluation design, QA = release QA.

| # | Task | Gate(s) | Owner | Depends | Files | Status | Verification cost |
|---|---|---|---|---|---|---|---|
| 1 | Publication / secret-history audit of every origin ref, release asset, issue, PR and comment | G18 | SEC | – | scratch `pubaudit/REPORT.md` | done | free |
| 2 | Site: Astro+Starlight landing + docs, QA (axe, links, screenshots), Pages workflow | G14, G15 | WEB | – | `site/`, `.github/workflows/pages.yml` | done | free (local) |
| 3 | Community files: CONTRIBUTING, CODE_OF_CONDUCT, root SECURITY, SUPPORT, issue/PR templates | G17 | I | – | `.github/`, root | done | free |
| 4 | Stable packaging: version 0.9.0, neutral metadata, project URLs, classifiers; release workflow with Trusted Publishing + provenance attestation + SBOM + checksums | G16, G17 | I | – | `pyproject.toml`, `.github/workflows/release.yml` | done | free |
| 5 | CLI reference generated from `--help` + drift test | G13 | I | 2 | `scripts/gen_cli_reference.py`, `tests/test_cli_reference.py`, `site/src/content/docs/reference/cli.md` | done | free |
| 6 | Fix #56 (host interpreter execution without `--run` consent) — failing-first test | G04 | I | – | `src/repo_ai/prove*` | done | free |
| 7 | Clean-environment onboarding: Linux podman container + macOS clean venv, wheel install, offline journey, upgrade from dev4, uninstall preserves user data | G02, G12 | QA | 4 | evidence under `dist/launch/` (ignored) | done | free |
| 8 | Live single-provider journey from the installed wheel (Codex): do → verify → apply → post-apply → undo | G05, G20 | I | 7 | evidence under `dist/launch/` | done | subscription, cost UNKNOWN |
| 9 | Live 2-provider tournament + `shortlist` on real candidates (Codex + agy) | G07 | I | 8 | same | done | subscription, UNKNOWN |
| 10 | Live cross-provider handoff with fresh verification | G08 | I | 8 | same | done | subscription, UNKNOWN |
| 11 | Prospective study design (false-green detection / safety metric), preregistration, harness, bounded calibration pilot | G19 | EVAL | – | `benchmarks/abc-v5/`, `docs/launch/EVALUATION.md` | done (calibration); confirmatory blocked(ext) | free design; pilot bounded |
| 12 | README rewrite to launch quality (short, accurate, links to site/docs; history moved to docs) | G01, G13, G17 | I | 2, 4 | `README.md` | done | free |
| 13 | Final freeze: 3-shard full suite, ruff/mypy/plugin/compileall/secret scan, wheel/sdist reproduction | all | QA | 3–12 | `scripts/finalization_validate.py` | todo | free (local) |
| 14 | Owner approvals: (a) visibility → public after audit, (b) PyPI pending publisher, (c) enable Pages, (d) branch protection | G15–G18 | owner | 1, 2, 4, 13 | – | todo | – |
| 15 | Publish: tag `v0.9.0`, GitHub release, PyPI, Pages deploy; external smoke (anonymous clone, `pip install repo-ai==0.9.0`, HTTPS fetch) | G15, G16, G21 | I | 14 | `docs/launch/LAUNCH_REPORT.md` | blocked(ext) | CI free once public |

## Added during execution

| # | Task | Gate(s) | Status | Evidence |
|---|---|---|---|---|
| 16 | First-run verify on plain pytest-style tests | G02, G12 | done | `c4b0956` |
| 17 | bwrap: probe mirrors real mounts; launcher failures never reported as results; /tmp toolchains | G04, G06, G12 | done | `4146f6b`; podman unprivileged/privileged runs; Linux isolation suites 99 passed |
| 18 | Continuation honours user `--allow-write` | G08 | done | `c505f74`; live Codex -> agy |
| 19 | shortlist AST-identical candidates | G07 | done | `5e8dccf` |
| 20 | Auth failure not a transient retry | G03, G20 | done | `fb831bc`; live Claude probe |
| 21 | Public source export (alternative to flipping the private history) | G18 | done | `scripts/public_export.py`; audit clean; full suite on the export: see LAUNCH_REPORT |
| 22 | Independent adversarial review of this cycle's src changes | G04 | doing | read-only reviewer |
| 23 | Final freeze (3 shards, static, wheel/sdist reproduction, clean installs) | all | todo | |
