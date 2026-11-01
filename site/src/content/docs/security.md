---
title: Security & privacy
description: How repo-ai isolates test runs per operating system, what it stores and where, what can leave your machine, and the residual risks.
---

repo-ai is designed for repositories that may be hostile: cloned from the internet, or containing text written to
manipulate an AI agent. Repository text is data, never instructions.

## Local-first by default

- No daemon, no hosted service, no telemetry.
- No network calls on any default path (tested by patching sockets).
- Network is used only when you ask:
  - mission execution with `--allow-live-provider` (the provider's own traffic);
  - `repo-ai skills discover --online`, `skills vet --online`, `skills install --online`, `skills updates --online`
    (GitHub);
  - `repo-ai prove report --publish-pr` (posts through `gh`);
  - `repo-ai sandbox pull` (container images);
  - `repo-ai init --summarize`, which runs `bob run` and sends facts, never code.
- `repo-ai doctor --agent claude` runs `claude --version`; Claude Code keeps its own files and may send its own
  telemetry.

## Sandboxes, by operating system

| OS | Host sandbox for `verify --run`, `--record` and missions | Notes |
|---|---|---|
| macOS | seatbelt, deny-by-default profile | shares the kernel; no Mach services, so no LaunchServices `open`, Apple Events or pasteboard |
| Linux | bubblewrap | tested in a dedicated CI job |
| Windows | **none**; use `--sandbox podman` or `--sandbox docker` | missions are not supported; a killed `repo-ai` can leave a container running |
| any | podman / Docker | the strongest isolation; `--image` must already exist locally and is never pulled |

Every backend blocks network, inherited environment, writes outside the workspace and symlink escapes. Tests run in a
**disposable copy** of the working tree; the original is not even readable from inside, and it is snapshotted before
and after each run. There is no unsandboxed fallback. `repo-ai sandbox status` shows which backend will be used.

## What is stored, and where

`repo-ai privacy audit` lists every store, its size, what it holds and whether it is committed. An excerpt from a
freshly initialised repository after one `verify --run`:

```text
  [facts] index: .repo-ai/state/index.db — 164.0 KB; committed: no (gitignored)
      holds: code-derived facts: paths, symbols, imports, routes, search text of indexed files (quarantined secret files excluded); query cache of ranked results keyed by prompt hash; retention: rebuilt on update
  [facts] generated docs: .repo-ai/context — 32.9 KB, 11 entries; committed: yes
      holds: Markdown summaries and facts.json; retention: rewritten on update
  …
  [support] verification evidence: .repo-ai/state/evidence — 6.4 KB, 2 entries; committed: no (gitignored)
      holds: per verify run: changed paths, selected tests, commands and results, and the last lines of failing test output (secret-shaped values scrubbed); static-security capability evidence; retention: last 50 runs
  [support] missions (experimental): .repo-ai/state/missions — absent; committed: n/a
  …
```

- `.repo-ai/state/` is never committed (a managed `.gitignore` block). Generated docs under `.repo-ai/context/` are
  committed unless you choose `--no-commit-context`.
- **Prompt text is never persisted.** The query cache is keyed by a hash; episodes and signals store hashes, lengths
  and paths.
- Outside the repository: an optional user config (`~/.config/repo-ai/config.toml`), opt-in cross-repository and
  capability-approval data (`~/.local/share/repo-ai`), and an empty 0700 workspace folder in `$TMPDIR`.

## Secrets

- Credential files (`.env*`, keys, `credentials.json`, kubeconfig, tfstate, …) are quarantined before they are read.
- Embedded private keys and AWS secret keys quarantine the file that contains them.
- Other findings are shown as a rule plus `path:line`, never the value; credentials in git remote URLs are redacted.
- Untracked credential-looking files are withheld from verify's disposable copy and listed.

## What repo-ai never does

- It never adds permission allow rules, never sets `bypassPermissions`, and never declares `allowed-tools` in skills.
- Hooks fail open: zero bytes and exit 0 on any error. They cannot block a prompt.
- A repository's own config cannot choose programs for repo-ai to run (`claude_cmd`, `bob_binary`, `summarize` and
  similar keys are honoured only from your user config, the environment or flags), and it can tighten but never relax
  `.gitignore` handling or secret scanning.
- No write or delete leaves the repository or goes through a symlink.
- Everything repo-ai writes carries an ownership marker or sits inside a marked block; `uninstall` removes only that.

## Live provider runs

`repo-ai do --run --allow-live-provider` starts a third-party coding CLI as a child process. The write boundary is
repo-ai's outer sandbox: writes go to a disposable candidate checkout and a scratch directory, and your checkout is
untouched until `repo-ai apply`. The residual risks, stated plainly:

- **Network is allowed** for the provider process, so it can send what it can read, including the candidate checkout,
  to its provider and, in principle, elsewhere.
- **Codex:** its own inner sandbox is bypassed, only after repo-ai confirms the outer one is active. A flaw in the
  outer sandbox is not backstopped.
- **agy (macOS):** can read the encrypted login keychain database files it needs to authenticate.
- **OpenCode on macOS, "loopback only":** measured on a CI runner (`benchmarks/seatbelt-loopback/`), the rule
  denies every other host (another machine on the local network, the internet; IPv4 measured, IPv6 not). But seatbelt can name hosts only as
  `*` or `localhost`, and `localhost` also matches your machine's own network addresses, so the agent can reach
  services bound to them; and the rule's inbound part lets it listen on every interface, not only 127.0.0.1. Whether
  such a listener is reachable from your network (the macOS firewall may intervene) was not measured. Any service on
  loopback that forwards traffic (a local proxy, a container engine's TCP port, a model server routing to a cloud
  model) is reachable too and can relay data; keep such services off while running an agent.
- **Credentials inside the run.** Codex's login token is copied into its scratch `CODEX_HOME` unless the opt-in
  credential broker is on (`REPO_AI_CODEX_BROKER=1`, macOS); Bob's `~/.bob/settings` directory is copied into the
  scratch HOME; and a provider credential set in your environment is passed to that provider's process
  (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (not with the broker), `GEMINI_API_KEY`,
  `GOOGLE_API_KEY`, `BOB_API_KEY`). A model that can run shell commands can read them, and network is allowed. Claude
  Code's model gets file tools only, so on macOS it cannot read its environment; whether its file tools can reach
  `/proc` or its config directory's credentials file under the Linux sandbox is not yet checked. Use a separate,
  revocable login or key for repo-ai.
- **Cost is not enforced for subscription CLIs.** Codex and agy cost is recorded as `UNKNOWN`, never `0`.
- **A passing test is not a proof of correctness**, and handoff capsules are integrity-checked, not authenticated.

## Threat model, in brief

repo-ai has to stay safe when a repository commits files designed to make it execute code, write outside the
repository or leak data (config, symlinks, filenames, an index database, skills); when repository text or model output
contains instructions; when personal and work repositories share a machine; and when hooks fire concurrently or
receive malformed payloads. Each invariant is enforced by a named test. Known open items include a race between the
containment check and a write (exploitable only by a concurrent local writer), seatbelt sharing the kernel, and the
static skill firewall missing destructive instructions written as plain prose.

The full tables are `docs/SECURITY.md` and `docs/VERIFY-THREAT-MODEL.md` in the source tree.

## Reporting a vulnerability

Report security issues privately to the repository owner. Please do not open a public issue.
