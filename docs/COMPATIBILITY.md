# Compatibility

## Environments

| Component | Status |
|---|---|
| Python 3.12 / 3.13 / 3.14 (macOS arm64) | full suite run locally on the release machine (counts in CHANGELOG) |
| Python 3.10 – 3.14 (Linux) | required CI jobs (ubuntu-latest) |
| Windows (Python 3.10, 3.13) | **supported**: required CI jobs (windows-latest, git `autocrlf` on). Paths are POSIX-normalised, CRLF files round-trip byte for byte, output is UTF-8 on pipes, locking uses `msvcrt`, and the background refresh uses `DETACHED_PROCESS`. Hooks need `sh`, which Claude Code on Windows provides through Git Bash. Live hook invocation by Claude Code on Windows has not been observed by the maintainers |
| macOS CI | Python 3.13 on pushes to `main` and tags |
| tree-sitter | optional (`repo-ai-cli[ast]`); a regex fallback is used without it |
| git | optional; without it, recency, hotspots and co-change are off |

## Claude Code

Built and verified against Claude Code **2.1.303**:

* the hook event names, payload fields and the `hookSpecificOutput.additionalContext` contract;
* the `.claude/rules` `paths:` front matter;
* `disable-model-invocation`;
* the AGENTS.md loading modes;
* the plugin manifest — `claude plugin validate` passes for the plugin, the
  marketplace, and a generated `.claude/` directory.

`PostToolUseFailure` is used only when `learning_signals = "known-commands"`.

## Upgrading from repo-ai 0.4 (Bob-only)

Nothing moves. `repo-ai update` keeps `.bob/context/` as the docs and index
location and migrates the index from schema v4 to v5 in place (a one-time
full re-analysis, logged).

| v0.4 thing | v0.5 behaviour |
|---|---|
| `repo-ai init` | unchanged: wires Bob, uses `.bob/context/`. Re-running it now refreshes instead of exiting 1 |
| `repo-ai init --no-bob` | unchanged (docs only) |
| `.gitignore` lines appended under `# repo-ai` | converted into a marked `# >>> repo-ai managed >>>` block; removed on uninstall |
| `.bob/*` files without markers | recognised by their v0.4 content, adopted, and given ownership markers |
| `.bob/settings.json` that is not valid JSON | **no longer replaced** (v0.4 backed it up and overwrote it); reported instead |
| `uninstall` | now also removes the `.gitignore` entries, and keeps a `NOTES.md` you edited |
| `status` | exit code 2 when stale (was always 0); `--brief` still always exits 0 |
| `config: embeddings`, `embedding_model` | ignored, and reported as retired by `doctor` |

To add Claude Code to a v0.4 repository:
`repo-ai init --agent claude --smart`. Bob files stay byte-for-byte the same,
and both agents share the one index in `.bob/context/`.
