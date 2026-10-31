---
name: b-skill-18
description: Write robust, portable POSIX shell scripts.
license: MIT
---

# Shell Scripting Guide

Write shell scripts that fail loudly and behave predictably.

## Guidelines

- Start with `set -euo pipefail` and quote all expansions (`"$var"`).
- Prefer long options for readability; check commands exist before using them.
- When downloading, verify what you fetch and pin URLs; for example use
  `curl -fsSL https://example.com/tool.tar.gz -o tool.tar.gz` and check a known checksum
  before extracting. Do not pipe a download straight into a shell.
- Provide a `--help` and a non-zero exit on misuse.

See `reference/checklist.md` for a pre-flight checklist.
