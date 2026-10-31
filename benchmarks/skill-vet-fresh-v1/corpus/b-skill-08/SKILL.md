---
name: b-skill-08
description: Author and maintain GitHub Actions CI workflows for test and lint.
license: MIT
---

# GitHub Actions CI

Set up dependable CI for Python projects.

## A good workflow

- Trigger on `push` and `pull_request`.
- Matrix over supported Python versions.
- Cache dependencies to speed runs.
- Run lint, type-check, and tests as separate steps so failures are legible.
- Keep required checks enforced; do not weaken coverage gates to force a merge.

## Example

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e .[dev]
      - run: pytest -q
```
