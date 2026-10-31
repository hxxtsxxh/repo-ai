# repo-ai Claude Code plugin (v0.11.4)

Optional alternative to per-project wiring. The plugin provides the repo-ai
skills (`/repo-ai:locate`, `/repo-ai:impact`, `/repo-ai:verify`, `/repo-ai:debug`,
`/repo-ai:review-diff`, `/repo-ai:orient`, `/repo-ai:learn`), four read-only-leaning
subagents, and the context hooks for every repository you open.

It does **not** replace the CLI: install `repo-ai` first, then run
`repo-ai init --agent claude` (or `--agent none` to skip project wiring) in each
repository so there is an index to read. In repositories without an index the
hooks do nothing.

Install from a clone of the repo-ai repository (or its git URL):

```sh
claude plugin marketplace add /path/to/repo-ai      # the directory holding .claude-plugin/
claude plugin install repo-ai@repo-ai
```

If you use the plugin, `repo-ai init --agent claude` notices it is enabled and
skips writing project hooks, so nothing runs twice. Project-generated skills
(`repo-add-endpoint`, `repo-tests`, ...) are still written per repository.

Generated from `src/repo_ai/plugin.py`; do not edit by hand.
