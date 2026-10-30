# Omniprovider mission — report

Status: **0.10.0 publicly shipped and verified (2026-10-30)**; the mission continues (see [QUEUE.md](QUEUE.md)). Release
facts below were re-read from the public hosts after publication. Controlling order: the owner's omniprovider mission (kept
outside the repository). Ledger: [ACCEPTANCE.json](ACCEPTANCE.json), [QUEUE.md](QUEUE.md),
[DECISIONS.md](DECISIONS.md), [EXPERIMENTS.md](EXPERIMENTS.md), [INTEGRATIONS.md](INTEGRATIONS.md),
[SKILLS_NETWORK.md](SKILLS_NETWORK.md), [evidence/](evidence/).

## What changed for a developer

- **Claude Code is a real repo-ai provider** (was blocked): `repo-ai agents setup claude`, then
  `repo-ai do … --agent claude --run --allow-live-provider`. Its own login, nothing copied; file tools only; every run
  first proves, for free, that the session loads nothing else.
- **A free, account-less provider**: OpenCode with a local model (`repo-ai agents setup opencode`). Weak models fail
  often; repo-ai refuses those runs instead of reporting success.
- **Honest provider map**: `repo-ai agents catalog` lists 24 coding agents with what repo-ai can actually do with each
  (5 EXECUTION, 1 BLOCKED, 16 PLANNED from vendor docs, 2 UNSUPPORTED).
- **Safer skills**: autonomy levels, a strict inert check, byte-exact install/uninstall across hosts; a
  repo-ai-installed skill was observed loading on Claude Code and OpenCode.
- **Fewer ways to be hurt**: no provider credential is copied into a sandbox; every process a provider run starts is
  killed before verification; `open`/Apple events and stray unix sockets are denied.

## Provider matrix (macOS, 2026-10-30)

| Provider | Version | Discovered | Authenticated | Isolated execution | Live candidate | Verified (hidden oracle) | Cost |
|---|---|---|---|---|---|---|---|
| Claude Code | 2.1.314 | yes | yes (dedicated login) | yes | yes | yes (17/17) | notional $; hard cap |
| Codex CLI | 0.165.0 | yes | yes | yes | yes | yes (17/17) | UNKNOWN (subscription) |
| Antigravity agy | 1.4.9 | yes | yes | yes (macOS) | yes | yes (17/17) | UNKNOWN (subscription) |
| OpenCode + qwen3:8b | 2.2.1 | yes | n/a (local) | yes (macOS) | yes | dev builds: 1 of 4 (9/9 on the pass); 0.10.0: a PASS that failed 1 of 9 hidden cases | $0 |
| IBM Bob | 2.0.9 | yes | not re-checked | yes | earlier pre-release | earlier | provider-reported |
| Gemini CLI | 0.65.0 | yes | **no** (exit 41) | — | — | — | BLOCKED |

## Security findings this cycle (all fixed unless stated)

Credential copying (Claude files, whole `~/.gemini` incl. another agent's history); read rules able to expose all
of HOME; a config-dir override able to write `~/.zshrc`; reachable unix sockets and DNS; setsid'd survivors and
`open`-launched apps escaping the sweep; account-synced connectors (shell, mail) reaching a Claude session (now
probed per run); a committed lockfile able to make uninstall delete a user file; a >2 MB tracked file hiding a
provider change from the scope check. **Disclosed, not fixed:** Codex's token is readable by a model with shell
access (dedicated login recommended); reads outside HOME (`/tmp`) stay open.

## Evaluation (no forced positives)

- Comparative lift over a standalone agent: **NOT_YET_DEMONSTRATED** (abc-v1..v4 at ceiling; Option A 92/90/88%).
- Skill benefit: **NOT_YET_DEMONSTRATED** (a paired run shows an installed skill's instruction is followed; no
  blinded outcome trial).
- Real project (python-slugify): `verify --run` caught a deliberate regression; Claude produced the exact fix; the
  mission abstained because of the suite's skips and unrelated failures (design in
  [designs/MISSION-REAL-SUITES.md](designs/MISSION-REAL-SUITES.md); part 1 implemented on a branch under review).
- Speed: on a tiny suite `verify --run` ≈ 0.5 s fixed + 2× native; held-out overhead unchanged (1.44–2.31×).

## Spend

Live calls under the owner's 2026-10-30 authorization (25 calls / $5): see [EXPERIMENTS.md](EXPERIMENTS.md).
Claude stream cost is notional on a Max subscription; Codex/agy/Gemini UNKNOWN; OpenCode $0. CI on the public
repository is free.

## Release 0.11.0 (verified after publication, 2026-10-30)

| What | Value |
|---|---|
| Public `main` at the tag | `218461a352d3d6cee72610e4ecb861d13f0b4baa` = tag `v0.11.0` (tree identical to the frozen `0ebe88a`) |
| Contents | requirement erasure (#7), `--expect-fix` for real suites (#9), each independently reviewed with findings fixed |
| Qualification | required CI green (#10); macOS full suite 2,551 passed, 4 skipped, 11 xfailed, 0 failed |
| Release workflow | run 41092530934: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | wheel `5a28fd1787a18b7098635cefd86c079ef83e49f538d3961b0c8b8e293657874e`, sdist `95316697ad2e160260c2367d55a67ae55b230fb2198c8f551cca5718d56adaa9`; identical to the GitHub assets; `SHA256SUMS` OK; attestation verified; clean-install smoke PASS |
| Found after release | an init-then-do first-run bug (fixed in PR #11, live-verified on a real repository) |

## Release 0.10.0 (verified after publication)

| What | Value |
|---|---|
| Public `main` at the tag | `f53d027416e1983bd04dfa7f4e437ff969f42cad` = tag `v0.10.0` (annotated, `18d2f0c2…`) |
| Merged PRs | #3 providers (`90a3b94`), #4 skills (`f33e9fb`), #6 release (`f53d027`), #5 site + docs (`8eeb8ef`) |
| CI | every required check green on each PR (Linux py3.10–3.14, Windows py3.10/3.13, docker and bwrap sandboxes, lint, offline eval, benchmark) |
| macOS full suite (freeze, `434a659`, `src/` identical to the tag) | 2,467 passed, 4 skipped, 9 xfailed, 1 failed (stale plugin bundle, fixed in `9c5f52f`, re-run green) |
| Release workflow | <https://github.com/hxxtsxxh/repo-ai/actions/runs/41030084295>: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | <https://pypi.org/project/repo-ai-cli/0.10.0/>: wheel `aa8278061511a26ea0d947b80af825711d073462ea6d74fcb6d63ff963eb51cf`, sdist `4cdcb886067eb59bbdeb54434af46b454a510297aa57f6d35dde6365a3c6bec3` |
| Re-download check | PyPI and GitHub release files byte-identical; `SHA256SUMS` OK (wheel, sdist, SBOM); `gh attestation verify` exit 0 |
| Website | Pages run 41036040819 (2026-10-30T09:48Z): all 20 sitemap URLs 200 over HTTPS, real 404, served HTML shows `repo-ai-cli 0.10.0` (verified PyPI read) |
| Live journeys on the published wheel | Claude, Codex, agy PASS (hidden oracle 17/17, undo byte-exact); Claude hostile repository PASS; OpenCode (local qwen3:8b, 3 attempts): one refused, one returned the recorded mission, the third PASSed the visible tests but failed 1 of 9 hidden cases (kept on display) — [evidence](evidence/JOURNEYS-0.10.0-PYPI.md) |
| Clean install | `sh scripts/release_smoke.sh 'repo-ai-cli==0.10.0' 0.10.0` from the default index on macOS: **SMOKE PASS** (offline first run, sandboxed verify, privacy audit, uninstall keeping user edits) |
