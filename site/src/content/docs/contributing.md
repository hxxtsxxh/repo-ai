---
title: Contributing
description: Set up a development environment for repo-ai, run its tests and benchmarks, and work on this documentation site.
---

## Development setup

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                      # unit, CLI integration, hooks and security tests
python benchmarks/run.py              # retrieval quality and latency vs. benchmarks/results/
python scripts/build_plugin.py        # regenerate the Claude Code plugin bundle
repo-ai eval                          # repo-ai's own bundled task suite, offline and free
```

`repo-ai eval` measures repo-ai itself on its bundled suite. It does not evaluate the repository you run it in.

Some tests need a sandbox: seatbelt on macOS, bubblewrap on Linux (and unprivileged user namespaces), or Docker.
Tests that need a missing backend are skipped.

:::caution[Billable commands]
`repo-ai eval coding`, `eval --live`, `skills benchmark`, `skills tournament` and `skills draft` run Claude Code and
can cost money. A real run needs an explicit, positive `--max-cost-usd`; use `--dry-run` to see what would happen.
:::

## Ground rules

- **Claims follow evidence.** A new capability starts as experimental. "Stable" needs held-out or CI evidence for its
  main claim. Results that go against repo-ai are reported, not dropped.
- **No network on default paths.** New network use must be opt-in behind an explicit flag, and listed on
  [Security & privacy](/repo-ai/docs/security/).
- **Repository text is data.** Nothing read from a repository may be executed or treated as an instruction.
- **Every security fix gets a regression test** that fails on the code before the fix.

## The documentation site

The site lives in `site/` (Astro and Starlight). Pages are Markdown under `site/src/content/docs/`.

```sh
cd site
npm ci
npm run dev        # local preview with live reload
npm run qa         # build, internal link check, accessibility check
```

Release facts the site renders (version, whether the package is on PyPI, whether the repository is public) live in
one file, `site/src/config.ts`. The [CLI reference](/repo-ai/docs/reference/cli/) is generated from `repo-ai --help`.

## Reporting security issues

Report vulnerabilities privately to the repository owner, not in a public issue.
