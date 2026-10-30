# Omniprovider mission — report

Status: **in progress** (draft written 2026-10-30 before the 0.10.0 tag; release facts are filled in after
publication and re-verified from the public hosts). Controlling order: the owner's omniprovider mission (kept
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
| OpenCode + qwen3:8b | 2.2.1 | yes | n/a (local) | yes (macOS) | yes | 1 of 4 (9/9 on the pass) | $0 |
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

## Release

_To be filled after the v0.10.0 tag: public `main` SHA, PR list, CI runs, PyPI files and sha256, re-download check,
clean-install transcript, Pages deployment and served-page checks._
