# Capability selection by an agent: the contract

repo-ai finds candidate capabilities and enforces trust. A coding agent (Claude Code or another) may
choose among the candidates. The CLI works without any model, so this is a supported integration mode,
not a dependency. Nothing here claims that an agent which chooses does better work. That would need a
controlled experiment, and none has been run.

## The loop

1. **Write the task** to a file with your own file-writing tool. Never pass it through a shell command line.
2. **List the candidates:** `repo-ai capabilities candidates --json --task-file <file> [--deny …]`.
   Pass every constraint the user stated, using `no-network`, `no-exec`, `static-only`, `no-install` or
   `no-third-party`.
   - The menu is at most 6 entries and 1,800 bytes, about 450 tokens.
   - A `digest` binds it to the task, the changed paths, the base commit, the trust state and the
     registry.
3. **Choose** one candidate id or `none`. `none` means "my own tools suffice" and is always valid.
4. **Select:** `repo-ai capabilities select <id|none> --digest <digest> --json --task-file <file>`.
5. **Act on the decision.**

| decision | exit | what the agent does |
|---|---|---|
| `ready` | 0 | Run `argv` exactly, and only if the user's request covers it. If `append` is `task-on-stdin`, pass the same task file on stdin; if it is `url-or-dir`, add what the user named. |
| `none` | 0 | Continue with its own tools. |
| `human` | 3 | Tell the user `text`, a fixed sentence. Do not attempt it. |
| `stale` | 6 | Call `candidates` again, once. |
| `refused`, `not-offered`, `unknown` | 7 | Continue with its own tools. |
| usage error | 2 | Fix the call. |

## Guarantees (each has a test)

**What `select` checks**
- **It re-evaluates every gate** at selection time. A stale or forged digest never produces `ready`.
- **Gates cannot be loosened.** Ranking orders the list but never changes a gate, and `--deny` only
  tightens. Nothing can lift a gate: not the task text, the registry's free text, a repository file
  (a committed approvals file or index), an environment variable, or `--all`.
- **`ready` needs every gate to pass:**
  - reviewed, pinned and implemented;
  - approved, and bound to the same binary;
  - available;
  - the command is on a read-only allowlist.
- **It never returns** `verify --run`, `skills vet --online`, `approve`, `prepare`, `revoke` or any
  install command.

**What the output contains**
- **No untrusted text.** Every string is a manifest constant, a closed code, a hex digest or a fixed
  argv token. The task text, file paths, repository framework and dependency names, and tool output
  are never echoed.
- **A constraint passed with `--deny` is always enforced.** It rules capabilities out, and those
  entries are shown as `blocked`.
  - The menu lists `constraints.explicit` (from `--deny`) separately from `constraints.inferred`
    (from the task text).
  - An unknown class is a usage error (exit 2), never ignored.
- **A constraint that is only written in the task is not reliably detected.** The corpus-C run caught
  only 9 of 18. The agent must therefore pass the user's stated constraints with `--deny`; the skill
  says so.

**What it does and records**
- **`select` runs and installs nothing.** A selection is logged outside the repository, without the
  task text, and never counts as `invoked`. `invoked` and `validated` change only through
  `capabilities run`.
- **The output is deterministic:** byte-identical across hash seeds, locales and the presence of agent
  environment variables.

## What is not a boundary

- **The digest** is a freshness check, not a secret. The gates are the check.
- **Refusing `approve`** inside agent shells, in CI or without a terminal is defence in depth. Your
  host's permission prompt is the boundary, and anything that can write your approvals file can
  approve.

## Context cost

- **Nothing is always loaded.** No hook, no MCP server and no CLAUDE.md text are added.
- **The `/repo-capabilities` skill is manual-only.** It costs nothing until you type it.

A hook that injects the menu into every prompt is not justified: its benefit is unmeasured, and the
cost is paid on every prompt. It belongs only in a preregistered experiment, and none is authorised.

## Not claimed

- That agents call this unprompted. The earlier record: 0 CLI calls in 200 runs and 0 skill
  invocations in 212.
- That agent selection beats the deterministic top 3. It was not measured; that would be a model trial.
- That discovery is reliable. On a fresh preregistered corpus, top-3 recall was 0.385 and shortlist
  recall 0.736, both FAIL (`docs/research/capability-discovery-C-2026-10/RESULTS.md`, private development history).
- That any capability improves a task outcome. `measured_effect` is `null` everywhere.
