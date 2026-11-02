# Omniprovider mission — report

Status: **0.11.9 publicly shipped and verified (2026-11-02)**; the mission continues (see [QUEUE.md](QUEUE.md)).
Release facts below were re-read from the public hosts after publication. Controlling order: the owner's omniprovider
mission (kept outside the repository). Ledger: [ACCEPTANCE.json](ACCEPTANCE.json), [QUEUE.md](QUEUE.md),
[DECISIONS.md](DECISIONS.md), [EXPERIMENTS.md](EXPERIMENTS.md), [INTEGRATIONS.md](INTEGRATIONS.md),
[SKILLS_NETWORK.md](SKILLS_NETWORK.md), [LIVE-SPEND-2026-11.md](LIVE-SPEND-2026-11.md), [evidence/](evidence/).

## Current state (2026-11-02)

### Release 0.11.9 (verified after publication)

| What | Value |
|---|---|
| Tag | `v0.11.9` (annotated) at `26f3988e763b2b9721180322007fa4a180dd9862`, merge of #97; pushed by the agent with the owner's authorization for this release |
| Contents | the code changes merged after 0.11.8: #87 workspace git without host configuration and no persisted checkout tokens, #89 a missing test runner is NOT VERIFIED, #90 probe hidden directories by real path, #91 handoff snapshot, #94 coverage review fixes, #96 `do --requirements`; plus the findings of its own release-level review, fixed in #97 (two rounds) |
| Qualification | #97 green, incl. the dispatched full CI with the macOS suite at `d4c94ac` (run 41444670896) |
| Release workflow | run 41487187744: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | <https://pypi.org/project/repo-ai-cli/0.11.9/>: wheel `ca3bc35fa442db4d1ab971be37012ac5df65c2b4d18ab28f943c0549db0cec4d`, sdist `2dddc5255e424ff314506bed8f54554389ec8564f78c8b8666ea8d5ae34e488c`; identical to the GitHub release assets and to a local clean build; the wheel rebuilt from the sdist is identical; `SHA256SUMS` OK; SLSA provenance verified for both (release.yml at `refs/tags/v0.11.9`, `26f3988`) |
| Clean install | macOS, fresh virtualenv from the default index (no `direct_url.json`; the index wheel's hash matches): `repo-ai 0.11.9`, `init`; with pytest absent from the interpreter, `verify --run` reported NOT VERIFIED: the test runner could not start (the 0.11.8 smoke finding) |
| Website | updated by the Pages deploy that follows this record |

### Release 0.11.8 (verified after publication)

| What | Value |
|---|---|
| Tag | `v0.11.8` (annotated) at `5662506e589bb93bbf43f20c6db212d2dc5dee12`, merge of #85; pushed by the agent with the owner's authorization for this release |
| Contents | #78–#86: the C18 security review of 0.11.3–0.11.7 (probe sandbox hides Linux host socket directories; macOS probe denies preference writes, launchd jobs and every Mach lookup but user and group lookups; licence-file vetting scope; coding-lab host git reads a pre-run copy of `.git`; TOML and pattern guards; workflow tokens), consumed handoff capsules (#82), and the medium finding of the release-level review (#86) |
| Qualification | #85 green incl. the dispatched full CI with the macOS suite at `30afeac`; an independent release-level review (nothing blocking; its medium finding fixed in #86 before the tag) |
| Release workflow | run 41396702501: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | <https://pypi.org/project/repo-ai-cli/0.11.8/>: wheel `967e659016454f9da1b8d37ddbd2f5d8fa59b592a910892d22f7bfe40a57ba8c`, sdist `d46d99aac42a2d87d2cffea27bacee414ea076884f94904dea21beb21e212b21`; identical to the GitHub release assets and to a local clean build; the wheel rebuilt from the sdist is identical; `SHA256SUMS` OK; SLSA provenance verified for both (release.yml at `refs/tags/v0.11.8`, `5662506`) |
| Website | <https://hxxtsxxh.github.io/repo-ai/>, Pages run for main `9f3904d` (2026-11-02T07:40Z); checked 2026-11-02T10:00Z: all 20 sitemap URLs 200 over HTTPS, a real 404 for a missing page, the served pages name 0.11.8 and the site changelog has a 0.11.8 section |
| Clean install | macOS, fresh virtualenv from the default index: `repo-ai 0.11.8`, `init`, a comment-only change gave NOTHING TO RUN. The same run found that a missing test runner was headlined "NO NEW FAILURES" (exit 1); fixed in 0.11.9 (#89) |

### Releases since 0.11.2

| Release | Date | Tag at | Wheel | Notes |
|---|---|---|---|---|
| 0.11.3 | 2026-10-31 | `7750279` | `b11ff58f…` | Codex credential broker, ACP agents, honest mission evidence |
| 0.11.4 | — | (`991d9c6`, never tagged) | — | qualified, tag push refused by the session's permissions; folded into 0.11.5 |
| 0.11.5 | 2026-11-01 | `abc81dc` | `1203e843…` | `agents doctor` sandbox fix, ACP conformance kit, real-project journeys |
| 0.11.6 | 2026-11-01 | `9edf537` | `c56e61e5…` | faster hooks and commands, a pytest collection note |
| 0.11.7 | 2026-11-01 | `34cb2e9` | `6a70b4b7…` | faster verify on Linux, Claude live on Linux, conventions-skill trial, Gemini removed |
| 0.11.8 | 2026-11-02 | `5662506` | `967e6590…` | security review fixes (above) |
| 0.11.9 | 2026-11-02 | `26f3988` | `ca3bc35f…` | a missing test runner is NOT VERIFIED; `do --requirements`; coverage review fixes; workspace git without host configuration; probe hidden directories by real path |

0.11.5–0.11.9 were each checked after publication the same way (PyPI = GitHub release = local build, `SHA256SUMS`,
attestation, clean install); 0.11.3: PyPI = GitHub release = local build, attestation, smoke (`SHA256SUMS` not
recorded). Details per release in ACCEPTANCE.json C20.

**0.11.9** shipped the code changes merged after 0.11.8 (details in the table above).

### Providers (changes since 0.10.0)

- Claude Code ran live on **Linux** (bubblewrap, `token_env`, Claude Code 2.1.316): a toy journey PASS,
  `LIVE_CANDIDATE_VERIFIED` (n = 1, a toy task; the `/proc` refusal rests on the model's report;
  [evidence](evidence/LINUX-CLAUDE-2026-11-01.md)). The exported token was later removed by the owner, so no live
  Claude run under repo-ai's isolation is possible until a credential is provided (C13).
- **Gemini CLI removed** (0.11.7): superseded by Antigravity (`agy`). Its `~/.gemini` state paths stay protected.
- OpenCode also runs through its ACP mode (`opencode-acp`); any ACP agent can be checked with `agents conformance`
  (handshake only, sandboxed).
- Codex: an opt-in credential broker on macOS (`REPO_AI_CODEX_BROKER=1`) keeps the token out of the model's reach;
  without it (and off macOS) the token stays readable by the model (disclosed).

### Security (0.11.3–0.11.8)

Two independent reviews of the release diffs (0.11.3–0.11.7, then 0.11.8) found 2 + 1 medium and 5 + 8 low issues.
Every medium is fixed.
- **Fixed in 0.11.8:** both mediums of the first review (probe sandbox), the five first-review lows (licence-file
  vetting, a quadratic dup2 check, a TOML crash, an unbounded pytestcfg pattern, checkout tokens in three workflows),
  coding-lab host git over a pre-run copy of `.git`, and the second review's medium (integrity `git show` on the
  agent-writable `.git`) and L1 (#86).
- **Fixed in 0.11.9:** L3 (#90), L5 (#91), L7 and part of L6 (#87: no host-global git configuration,
  `persist-credentials: false` everywhere).
- **Still open and disclosed:** L2 (a resolve-to-bind race in the Linux probe), L4, the rest of L6 (QUEUE row 19);
  probe reads are not restricted; Linux unix sockets outside the hidden directories; macOS signals and IOKit; the
  OpenCode adapter's loopback rule admits a wildcard listen and the host's own LAN address (QUEUE row 13).

### Evaluation (no forced positives)

| Question | Result |
|---|---|
| Does `verify` give false assurance? | held-out-7: **0 in 127 failing states**, 0 false alarms, tree unchanged 234/234 (five projects, containers, build `903984a`) |
| Is `verify --run` faster than the native suite? | **NEGATIVE**: speed-v1 1.84× (preregistered), then 2.23×, 2.00×, 1.96×; exit codes agree with the native suite on 24 of 30 in runs 4–5 (16 and 23 earlier; the rest are pyjwt, which needs the network the sandbox denies) |
| Does repo-ai improve a coding agent? | **NOT_YET_DEMONSTRATED** (Option A: 92% plain, 90% / 88% repo-ai; abc studies at ceiling) |
| Does an installed skill help? | one conventions skill on one fixture project: **SUPPORTED with design limits** (8 of 8 tasks, p = 0.0039; c10-confirm-v1) |
| Does the deterministic skill recommender find the right capability? | **NEGATIVE** (recall 0.385 and 0.69 on two fresh corpora, constraint gate failed on both; tuning stopped) |
| Does skill vetting block harmful skills on unseen data? | **FAILED** (skill-vet-fresh-v1: SAFE_AUTO would have auto-installed 8 of 30 harmful prose-only skills, and 6 of 10 harmful script skills were rated eligible; fixed, not confirmed on fresh data) |
| Does verify mislead on real commits? | journey-offline-v2: no false assurance on 7 real fixes (5 flagged as a regression, 2 refused; a small sample, upper bound about 35%); the fix confirmed on 3 of 6; journey-offline-v1 INCONCLUSIVE |
| Claude context effect | not re-run (the only public split was tuned on; decision recorded, C15) |

### Spend

Live spend this cycle: **$3.2921 of the owner's $20** ([LIVE-SPEND-2026-11.md](LIVE-SPEND-2026-11.md)); Claude
cost is notional on a subscription token. CI on the public repository is free.

### Gates

PASS: C01, C02, C03, C20. PASS_WITH_LIMITS: C04, C09, C10, C17, C19. PASS_AT_0.9.0: C23. EXPERIMENTAL: C05, C06, C07,
C08, C11, C12, C13, C18, C21, C22. NEGATIVE_RESULT: C16. NEGATIVE_RESULT_HISTORICAL: C15. NOT_YET_DEMONSTRATED: C14.
IN_PROGRESS: C24.

### Not proven, and what would prove it

- **Agent benefit (C14, C15):** blinded human authors and new held-out tasks.
- **Skill-vetting on an unseen corpus (C08):** a person-written v2 corpus; an agent-authored one was stopped by a
  safety classifier and is not retried.
- **Claude as a handoff target (C13):** a Claude credential for isolated runs.
- **Live third-party projects (C21):** the live provider journey within the remaining live budget; third-party code
  needs the owner's explicit approval or runs on CI (EXPERIMENTS.md). The Claude token used so far was removed.
- **Tournament on behaviourally different candidates (C12), routing over real host states (C06):** live calls.
- **Requirement coverage (C11):** an independent review found it partly met; its fixes (#94) and a declaration frozen
  with the mission (#96) shipped in 0.11.9. Next: requirement-by-requirement links to the changed code.
- **Speed (C16):** the fixed cost on small suites; steadier strategy inputs.

## The 0.10.0 cycle (2026-10-30)

### What changed for a developer

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

### Provider matrix (macOS, 2026-10-30)

| Provider | Version | Discovered | Authenticated | Isolated execution | Live candidate | Verified (hidden oracle) | Cost |
|---|---|---|---|---|---|---|---|
| Claude Code | 2.1.314 | yes | yes (dedicated login) | yes | yes | yes (17/17) | notional $; hard cap |
| Codex CLI | 0.165.0 | yes | yes | yes | yes | yes (17/17) | UNKNOWN (subscription) |
| Antigravity agy | 1.4.9 | yes | yes | yes (macOS) | yes | yes (17/17) | UNKNOWN (subscription) |
| OpenCode + qwen3:8b | 2.2.1 | yes | n/a (local) | yes (macOS) | yes | dev builds: 1 of 4 (9/9 on the pass); 0.10.0: a PASS that failed 1 of 9 hidden cases | $0 |
| IBM Bob | 2.0.9 | yes | not re-checked | yes | earlier pre-release | earlier | provider-reported |
| Gemini CLI | 0.65.0 | yes | **no** (exit 41) | — | — | — | BLOCKED |

### Security findings this cycle (all fixed unless stated)

Credential copying (Claude files, whole `~/.gemini` incl. another agent's history); read rules able to expose all
of HOME; a config-dir override able to write `~/.zshrc`; reachable unix sockets and DNS; setsid'd survivors and
`open`-launched apps escaping the sweep; account-synced connectors (shell, mail) reaching a Claude session (now
probed per run); a committed lockfile able to make uninstall delete a user file; a >2 MB tracked file hiding a
provider change from the scope check. **Disclosed, not fixed:** Codex's token is readable by a model with shell
access (dedicated login recommended); reads outside HOME (`/tmp`) stay open.

### Evaluation (no forced positives)

- Comparative lift over a standalone agent: **NOT_YET_DEMONSTRATED** (abc-v1..v4 at ceiling; Option A 92/90/88%).
- Skill benefit: **NOT_YET_DEMONSTRATED** (a paired run shows an installed skill's instruction is followed; no
  blinded outcome trial).
- Real project (python-slugify): `verify --run` caught a deliberate regression; Claude produced the exact fix; the
  mission abstained because of the suite's skips and unrelated failures (design in
  [designs/MISSION-REAL-SUITES.md](designs/MISSION-REAL-SUITES.md); part 1 implemented on a branch under review).
- Speed: on a tiny suite `verify --run` ≈ 0.5 s fixed + 2× native; held-out overhead unchanged (1.44–2.31×).

### Spend

Live calls under the owner's 2026-10-30 authorization (25 calls / $5): see [EXPERIMENTS.md](EXPERIMENTS.md).
Claude stream cost is notional on a Max subscription; Codex/agy/Gemini UNKNOWN; OpenCode $0. CI on the public
repository is free.

## Release 0.11.2 (verified after publication, 2026-10-30)

| What | Value |
|---|---|
| Public `main` at the tag | `c22c9fe52deafb6a0e530a96907ad937e1f19468` = tag `v0.11.2` (annotated), merge of #20; tree identical to the qualified `2ec12f0` |
| Contents | #16 init's `.gitignore` block, #17 the project's interpreter (incl. editable installs) and tracked-but-ignored files, #18 verify quotes pytest's counts, #14 project-skill relevance (advice). All found on python-humanize. Each PR was reviewed adversarially until no confirmed issue remained. |
| Qualification | required CI green on #20; macOS full suite on `2ec12f0` in the real clone (22:42–23:41Z, checkout untouched throughout): 2,616 passed, 4 skipped, 11 xfailed, 0 failed |
| Release workflow | run 41146089668: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | wheel `e5ad6dd9e9cf92bd5d0568f8db4c4c02ffe10b20a407f70d4d59b52856eb2b15`, sdist `81bb0626ea2d9f0fcf3a42173525b4e27dbf12873be2663615067f0d4e324102`; identical to the GitHub assets; `SHA256SUMS` OK; attestation verified (wheel and sdist); `release_smoke.sh` SMOKE PASS |
| Real-world check | python-humanize, fresh first run on the published wheel: live Claude `PASS [LIVE_CANDIDATE_VERIFIED]` (call #36), apply/undo exact |

## Release 0.11.1 (verified after publication, 2026-10-30)

| What | Value |
|---|---|
| Public `main` at the tag | `a0bbe3677c50d99feeca24de520c579e661f2188` = tag `v0.11.1` (annotated), merge of #13 (head `029e6fa`) |
| Contents | init-then-do fix (#11): repo-ai's own state never makes a checkout dirty, never counts as mission source, never materializes into a candidate |
| Qualification | required CI green on #13; macOS full suite on `029e6fa` (18:10–19:10Z): 2,567 passed, 4 skipped, 11 xfailed, 0 failed. The checkout was switched to `main` for 9 s during the run (19:05:22–19:05:31Z; six version-string files differed); the 15 test files that read those files and the plugin check were re-run on `029e6fa` afterwards: 457 passed, 2 xfailed |
| Review | independent reviewer: no confirmed issue (one changelog nit, folded into the 0.11.1 entry afterwards) |
| Release workflow | run 41114278657: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | wheel `92cc761432439b583658c5aa5369541070802367a397466d92fc7a824008025c`, sdist `cedd5f33b254c9463c42c61e2bd252bb493a3e66a81cdf04129472e2c29b29f7`; identical to the GitHub assets; `SHA256SUMS` OK; attestation verified (wheel and sdist); `release_smoke.sh` SMOKE PASS |

## Release 0.11.0 (verified after publication, 2026-10-30)

| What | Value |
|---|---|
| Public `main` at the tag | `218461a352d3d6cee72610e4ecb861d13f0b4baa` = tag `v0.11.0` (tree identical to the frozen `0ebe88a`) |
| Contents | requirement erasure (#7), `--expect-fix` for real suites (#9), each independently reviewed with findings fixed |
| Qualification | required CI green (#10); macOS full suite run locally on `0ebe88a` (2026-10-30T12:05–13:04Z, tree identical to the tag): 2,551 passed, 4 skipped, 11 xfailed, 0 failed |
| Release workflow | run 41092530934: build, smoke on ubuntu/windows/macos, Trusted Publishing, GitHub release |
| PyPI | wheel `5a28fd1787a18b7098635cefd86c079ef83e49f538d3961b0c8b8e293657874e`, sdist `95316697ad2e160260c2367d55a67ae55b230fb2198c8f551cca5718d56adaa9`; identical to the GitHub assets; `SHA256SUMS` OK; attestation verified; clean-install smoke PASS |
| Found after release | an init-then-do first-run bug (fixed in 0.11.1; live-verified on a development build against a real repository) |

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
