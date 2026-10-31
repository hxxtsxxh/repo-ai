---
description: Run the test suite for the current project
allowed-tools: Bash
---

Detect the project type and run its tests:

- If `pyproject.toml` or `pytest.ini` exists, run `pytest -q`.
- If `package.json` exists, run `npm test`.

Summarize pass/fail counts and show the first failing test's output.
