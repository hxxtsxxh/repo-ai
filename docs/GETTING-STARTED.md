# Getting started: one path, three levels

repo-ai is one CLI with one path through it:

**INSTALL → INIT → CONTEXT → (change) → VERIFY → EVIDENCE → REVIEW.**

What is supported, experimental or excluded, with the evidence: [STATUS.md](STATUS.md). (The older
0.8.0rc1 manifest is [release/RC1.md](release/RC1.md).)

Each step works without the ones after it. Use as much as you need.

| Step | Command | What it does | Runs your code? |
|---|---|---|---|
| Install | `pipx install repo-ai-cli` | from PyPI (the command is `repo-ai`) (or `pipx install ./repo_ai_cli-0.9.0-py3-none-any.whl` from a GitHub release); its one dependency is `pathspec` (plus `tomli` on Python 3.10) | no |
| Initialize | `repo-ai init --agent claude` (or `--agent none`) | indexes the repository; for Claude Code, writes CLAUDE.md, rules, curated skills and hooks | no |
| Understand | `repo-ai context "what you are about to do"` · `repo-ai impact PATH` | the files, symbols, tests and history relevant to a task; what a change can reach | no |
| Change | you, or your agent | — | — |
| Verify | `repo-ai verify` then `repo-ai verify --run` | the tests your change can break, then those tests run in a sandbox, compared with the base | only `--run`, sandboxed |
| Evidence | `repo-ai evidence` | whether the last `verify --run` still covers the working tree and the test environment | no |
| Review | `repo-ai review` | a change passport for the PR: what the diff touches, tests, risks, blind spots | no |
| Diagnose | `repo-ai doctor` | installation and agent wiring | no |
| Undo | `repo-ai uninstall`, then `pipx uninstall repo-ai-cli` | removes managed data and wiring; preserves and lists user files and exported reports | no |

**Experimental, opt-in, not part of the stable claims:** `repo-ai prove pin … / plan / run / report`
(ProofLab). For a fix, it checks that the original code fails a pinned test and the change passes it,
under the same conditions. It did not qualify in its independent evaluation, and three false proofs
are known and open (named in every passport). A supported verdict is a local experiment record, not a
proof. See [PROOFLAB.md](PROOFLAB.md).

## Three configurations

| Level | For | Set up with | Adds |
|---|---|---|---|
| **Minimal** | understanding a repository | `repo-ai init --agent none` | the index, `context`, `impact`, `search`, `related` |
| **Verified** | changing it safely | the same; run `verify --run` when you choose | sandboxed verification and its evidence. Optional, experimental: the `Stop` gate (`verify_gate = true` in `.repo-ai/config.toml`, block or report mode) |
| **Advanced** (experimental) | agents with approved tools | `repo-ai init --agent claude --feature-set full` | the skeptic subagent and orchestration hints; curated skills (including manual-only, experimental `/repo-prove`) also install with core; `capabilities approve` authorizes a bound tool; no benefit shown |

Verification runs only when requested. Claude Code hooks maintain context automatically:
- The prompt hook injects ranked context within a token budget (`hook_budget_tokens`, default 1200).
- It never injects ProofLab instructions.
- The completion gate is off unless you turn it on.

## Where it runs

| | macOS | Linux | Windows |
|---|---|---|---|
| Index, context, impact, review | yes | yes | yes (unit tests in CI) |
| `verify --run`, `prove run` host sandbox | seatbelt | bubblewrap | **none**: use `--sandbox podman` or `docker` |
| Containers (`--sandbox podman/docker`, `--image`) | yes | yes | yes, not measured |
| Measured on fresh data | held-out-7 in podman containers (pytest, `node --test`); the host sandbox by tests | the same; bubblewrap by the CI job | **never** |

**Test runners:**
- `unittest`, `pytest` and `node --test` are split per file.
- TypeScript runs with node's type stripping; its default discovery has included `.ts` tests since #45.
- Jest, Vitest, Mocha and other runners are opaque: verify runs their full suite, and ProofLab does not
  support them.

## What "verified" means

- **verify:** passes only on a run whose tests actually ran and whose report agrees with the process.
  With no linked tests, the plan abstains. Execution can still pass when it runs
  the required full suite successfully; that covers the suite, not the unlinked change.
  If the full suite is not required, no linked test means **NOT VERIFIED**.
- **ProofLab (experimental, not certified):** says "supported for the pinned scenario", names its three open
  false-proof classes, and lists what it does not establish.
- **Neither** is a proof of correctness.

See `docs/STATUS.md` for what is stable, what is experimental and what was measured.

## Undo

`repo-ai uninstall` removes what repo-ai created: the index, generated context, hooks and skills. It
leaves your code alone. In the release-freeze check the tree was byte-identical to the commit before
`init` afterwards. User-named exports such as `.repo-ai/proof.md` and edited
configuration are retained and listed; remove them yourself when no longer needed.
`pipx uninstall repo-ai-cli` removes the program.

Managed project data stays inside the repository, with these exceptions:
- **Outside it:**
  - it reads an optional per-user configuration (`~/.config/repo-ai/config.toml`);
  - the opt-in cross-repository registry and capability approvals keep their data in
    `~/.local/share/repo-ai`;
  - `verify --run` leaves an empty, private (0700) workspace folder in `$TMPDIR` (`repo-ai-ws-<uid>`).
- **`repo-ai doctor --agent claude`** runs `claude --version`. That is Claude Code, which keeps its own
  files in `~/.claude*` and may send its own telemetry.
