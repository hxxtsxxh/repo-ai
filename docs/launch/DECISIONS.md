# Launch decisions (ADRs, concise)

Each entry: decision, why (observable), consequence. Rejected options are kept.

## L-001 Product thesis: verification and continuity first, orchestration second (2026-10-29)

- **Primary daily-driver value:** before you trust an AI- or human-written change, repo-ai tells you what it touched, which tests can show a break, and what running them in a sandbox *actually* showed against the base — with no agent required.
- **Defensible, measurable advantage:** honest evidence semantics. The held-out-7 frozen evaluation measured 0 false assurances in 127 failing states (5 projects, pytest/`node --test`). `coverage` makes a missing requirement→test link visible (real `node-slug` decoy/reference reproduction). This is a *safety* metric, not raw solve-rate lift.
- **Distribution channel:** `pip`/`pipx install repo-ai` + a CI recipe + agent hooks (Claude Code first, because it is the host most users already run).
- **Falsifier:** if a prospective study shows `verify`/`coverage` do not catch planted false greens more often than "tests passed" alone, or produce excessive noise on correct changes, the thesis fails. Orchestration lift over a single agent stays `NOT_YET_DEMONSTRATED` (four studies at the arm-A ceiling) and is not marketed.
- **Rejected:** "more models beat one" as the headline; "proof of correctness" wording.

## L-002 Stable version is `0.9.0`, not `1.0.0` (2026-10-29)

- The CLI surface is large and several commands are experimental (ProofLab, discovery, learning, skills lab). A 1.0 would promise interface stability we do not have evidence for.
- `0.9.0` sorts after every `0.9.0.devN` pre-release (PEP 440), is a final (non-pre) release, and keeps the pre-1.0 compatibility caveat explicit.
- Consequence: the public package is `repo-ai==0.9.0`; stable/experimental status per command is in `docs/STATUS.md` and the site.

## L-003 Site: Astro + Starlight under `site/`, GitHub Pages project site (2026-10-29)

- Static, no server, no secrets, free on the existing Pro plan; Starlight ships navigation + Pagefind search.
- Base URL `https://hxxtsxxh.github.io/repo-ai/` (provider subdomain; no custom domain is claimed).
- Install commands and repository links are behind `site/src/config.ts` flags so the site never shows `pip install repo-ai` before PyPI publication succeeds or a repo link while the repo is private.
- Rejected: Vercel/Netlify/Cloudflare (no authenticated CLI on this host; adds accounts), Docusaurus (heavier JS).

## L-004 PyPI via Trusted Publishing (OIDC), never a long-lived token (2026-10-29)

- `.github/workflows/release.yml` builds once, verifies, attests provenance, and publishes with `pypa/gh-action-pypi-publish` from a protected `pypi` environment.
- First publication of a new project needs a **pending publisher** registered by the owner on pypi.org (account action; cannot be automated from here).

## L-005 CI spend policy while private (2026-10-29)

- Measured: Actions on this private repo is billed (October: Windows 6722 min, macOS 642 min). Mission PRs carry `[skip ci]`; equivalent local checks (macOS host suite, Linux podman container) are run and labelled *local*, not CI.
- Once public, standard GitHub-hosted runners are free, and full CI (including macOS) is re-enabled on PRs.

## L-006 Package metadata is provider-neutral (2026-10-29)

- `pyproject` description/keywords and the GitHub description said "for Claude Code and IBM Bob"; the product now routes across Bob, Codex, agy and works with no agent. Updated to neutral wording; provider support stays in the matrix with its evidence.

## L-007 Thesis narrowed after the abc-v5 calibration (2026-10-29)

- **Observed (calibration only, 4 synthetic tasks, 29 candidates, one author for every role, $0):** repo-ai's
  decision rule B accepted 5/9 requirement-violating decoys vs 9/9 for "tests pass", and 0/10 test-gaming controls
  vs 10/10 (2/10 for a careful developer who re-checks a clean checkout). But task-level discrimination was **0 on
  all 4 tasks**: every semantic "catch" was an abstention that B also gave the correct reference, because a
  requirement had no discriminating test. B cannot tell two candidates apart when both pass the same tests.
- **Decision:** the public claim is narrowed from "catches false greens" to what was observed: repo-ai **names the
  requirements your tests do not pin, and resists test gaming** (edited/skipped tests, exit-code tricks, stale
  evidence). It does not judge semantic correctness. The site and README already say PASS is not correctness; no
  "catches false greens" claim is made anywhere.
- **Next test of the thesis (preregistered, not run):** abc-v5 H2 — B+ (tests written for the requirements B flags)
  vs A+ (the same number of tests aimed at random requirements), on 24 upstream tasks with blinded authors. It needs
  owner approval for any model-authored task material (≈ $15–40) or human authors.
- The calibration also produced a coverage fix: a `NOT_DISCRIMINATING` explanation claimed the mapped tests "could not
  have detected" the change when one of them had; it now names which tests moved and which could not.

## L-008 PyPI distribution name `repo-ai-cli` (owner decision, 2026-10-29)

- PyPI's Warehouse rejects a new project whose ultranormalized name (lowercase; `.`, `_`, `-` removed; `o`→`0`,
  `i`/`l`→`1`) equals an existing one; `repo-ai` and the unrelated `repoai` both become `rep0a1`
  (`ProjectNameUnavailableSimilarError`). The owner chose `repo-ai-cli`. Command `repo-ai` and package `repo_ai` are
  unchanged. Pre-release wheels were the distribution `repo-ai`; both own the same files, so the migration is
  uninstall-then-install (verified in a clean container from the published dev4 wheel).

## L-009 Public source is a curated export, not a visibility flip (owner decision, 2026-10-29)

- The private history carries a corporate author address and the sealed/held-out sets; neither is removable without a
  rewrite, and `refs/pull/*` cannot be rewritten. The private repository becomes `hxxtsxxh/repo-ai-dev` (history,
  releases v0.5.1…v0.9.0-dev4, issues and PRs preserved there, private); the public `hxxtsxxh/repo-ai` starts from one
  audited commit built by `scripts/public_export.py`. Local `origin` remotes are repointed to `repo-ai-dev` first so no
  private branch can reach the public repository.
