# repo-ai

**Know what a change actually did before you trust it.**

repo-ai is a local-first CLI for AI-assisted (and ordinary) software work. It indexes your
repository offline, tells you what a change touches and which tests can show a break, runs
those tests sandboxed in a disposable copy against the base commit, and reports exactly what
was observed — never more. Coding agents are optional: when you opt in, repo-ai can drive
them under isolation, frozen acceptance tests and explicit apply/undo.

- **Context, offline.** Task-aware file shortlists, change impact, test links and "why"
  explanations from a local index. No agent, model, daemon or network needed.
- **Evidence, not vibes.** `verify --run` separates new failures from ones already at the
  base, flags stale evidence, and says when a verdict rests only on static links.
  `coverage` checks a requirement→test map you declare against the tests that actually
  ran. A PASS means *the selected tests passed* — never *the task is correct*.
- **Agents, if and when you want them.** `repo-ai do` runs a provider (Bob, Codex,
  Antigravity) in an isolated worktree with an explicit cost ceiling. Tournaments abstain
  instead of crowning an arbitrary winner; handoff capsules are integrity-checked; nothing
  is applied without your command, and `undo` restores the bytes.

> **Status: 0.9 is a beta.** The verification core is the most tested part (below). Many
> commands are experimental and say so; the full matrix with evidence is in
> [docs/STATUS.md](docs/STATUS.md). **Not yet demonstrated:** that repo-ai makes a coding
> agent succeed more often than the same agent alone.

## Install

Python 3.10–3.14 on macOS, Linux or Windows. Runtime dependencies: `pathspec` (+ `tomli` on 3.10). The PyPI
distribution is `repo-ai-cli` (`repo-ai` was taken by a similar name); the command and the Python package are
`repo-ai` / `repo_ai`. If you installed a 0.9.0.devN pre-release wheel, remove it first: `pipx uninstall repo-ai`.

```sh
pipx install repo-ai-cli        # or: python -m pip install repo-ai-cli
repo-ai --version               # the command is repo-ai
```

Stable [GitHub releases](https://github.com/hxxtsxxh/repo-ai/releases) also carry the wheel,
sdist, `SHA256SUMS`, a CycloneDX SBOM and build-provenance attestations.

## Two-minute first run (no agent)

```sh
cd your-git-project
repo-ai quickstart                 # where you are and what to run next
repo-ai init --agent none          # build the local index under .repo-ai/ (+ a .gitignore block)
# ...edit some code...
repo-ai verify                     # read-only: changed units, linked tests, confidence, the command
repo-ai verify --run               # run them sandboxed in a disposable copy of the working tree
repo-ai evidence                   # does the last result still cover the working tree?
```

Real output (trimmed) of `verify --run` on a two-file project (`calc.py`, `test_calc.py`) after editing `mean()`:

```
verifying 1 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…
  command: pytest  [inferred from the test files]
  pass    test_calc.py (0.3s)
selected 1 of 1 test files; confidence MEDIUM: some of the change rests on static evidence only (imports or file names), not on runtime evidence

PASSED: every selected test passed (the full suite was not run)
  1 passed
  source tree unchanged
evidence saved; `repo-ai evidence` shows whether it still covers the working tree.
This covers only the tests that ran; it is not proof the change is correct.
```

`repo-ai uninstall --agent all` removes everything repo-ai created (`--dry-run` shows it first).

## With Claude Code

```sh
repo-ai init --agent claude        # CLAUDE.md block, skills, confidence-gated context hooks
claude                             # context arrives with each prompt when repo-ai has evidence
```

repo-ai never adds permission allow-rules or `bypassPermissions`. Details: [docs/CLAUDE_CODE.md](docs/CLAUDE_CODE.md).

## Missions with coding agents (opt-in)

```sh
repo-ai agents list                # offline: what is installed; no model call
repo-ai agents route               # which provider would be chosen and why; no model call
repo-ai do "make mean() return 0 for an empty list" --dry-run     # plan only (the default)
repo-ai do "make mean() return 0 for an empty list" --agent codex \
    --allow-write calc.py --run --allow-live-provider              # live, isolated, consented
repo-ai apply <mission-id>         # explicit; re-verifies after applying
repo-ai undo <mission-id>          # restores the original bytes
```

Execution needs a clean committed checkout, explicit write paths, pytest or `node --test`,
and a sandbox backend (macOS or Linux; missions are not supported on Windows). `--tournament codex,agy` runs independent candidates against the
same frozen tests and abstains unless exactly one distinct candidate passes; `shortlist`
explains an abstention. Recipes: [docs/roadmap/REALITY-ENGINE-USAGE.md](docs/roadmap/REALITY-ENGINE-USAGE.md).

| Provider | Through `repo-ai do` (isolated) | Notes |
|---|---|---|
| IBM Bob | live, verified changes on small tasks | hard USD cap supported |
| OpenAI Codex CLI | live, verified changes on small tasks | runs under repo-ai's outer sandbox; cost UNKNOWN under subscription |
| Antigravity `agy` | live on macOS only | cost UNKNOWN under subscription |
| Claude Code | **blocked** as an execution provider (login is not usable in the isolated scratch HOME) | fully supported as the *host* for context and hooks |
| Gemini CLI | rejected for the tested account | |

"Live" means a model-generated change was independently re-verified through repo-ai on this
project's development machine, with small n. Your account, quota and platform decide what works for you;
`agents route` reports it without spending anything.

## Platforms

| | macOS | Linux | Windows |
|---|---|---|---|
| Index, context, impact, plans | yes | yes | yes |
| Sandboxed test runs (`verify --run`, missions) | seatbelt | bubblewrap | podman/docker container only (no host sandbox) |

## What has and hasn't been measured

- **Verify (held-out-7, frozen, independently labelled):** 0 false assurances in 127 failing
  states across 5 pytest/`node --test` projects in containers; the working tree was unchanged
  in 234/234 runs. Slower than the native suite on 3 of 5 small suites. Not qualified:
  unittest, TypeScript, Jest/Vitest/Mocha.
- **Agent benefit:** four small preregistered studies: abc-v1 (Bob, 4 tasks) was A 2/4 vs
  B 3/4 — inconclusive at that n, with one repo-ai false green; abc-v2..v4 hit the ceiling (the
  bare provider solved every task). An earlier 150-run Claude study found no difference (92%
  plain vs 90%/88%). Comparative lift is **NOT_YET_DEMONSTRATED**.
- **Retrieval:** strong on symbol names, weak on prose (recall@5 0.32 on natural-language
  queries). See [docs/RETRIEVAL.md](docs/RETRIEVAL.md).

## Safety and privacy

Local only, no telemetry. Network use happens only on explicit commands (live missions,
`--online` skill vetting, `sandbox pull`). Secrets are quarantined or shown as rule +
`path:line`, never the value. Repository text is data, never instructions. Writes never
leave the repository or follow symlinks. `repo-ai privacy audit` lists every store and
whether it is committed. Threat model: [docs/SECURITY.md](docs/SECURITY.md),
[docs/VERIFY-THREAT-MODEL.md](docs/VERIFY-THREAT-MODEL.md).

## Documentation

- [Getting started](docs/GETTING-STARTED.md) · [CLI reference](docs/CLI-REFERENCE.md) · [Full guide](docs/GUIDE.md)
- [Verify](docs/VERIFY.md) · [Status matrix](docs/STATUS.md) · [Architecture](docs/ARCHITECTURE.md) · [Changelog](CHANGELOG.md)

## Contributing, security, licence

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) (report vulnerabilities
privately) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) · [SUPPORT.md](SUPPORT.md) ·
MIT licence ([LICENSE](LICENSE)); bundled third-party evaluation tasks keep their own
licences ([notices](docs/release/THIRD-PARTY-NOTICES.md)).
