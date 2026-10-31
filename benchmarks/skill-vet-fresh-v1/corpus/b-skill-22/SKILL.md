---
name: b-skill-22
description: Apply consistent code formatting with autoformatters.
license: MIT
---

# Code Formatting

Keep style consistent and out of code review.

## Setup

- Python: `black` for formatting, `isort` for imports, `ruff` for lint.
- JS/TS: `prettier` for formatting, `eslint` for lint.
- Configure in `pyproject.toml` / `.prettierrc`; commit the config.
- Run formatters in a pre-commit hook and verify (not reformat) in CI.

Let tools handle style so reviews focus on substance.
