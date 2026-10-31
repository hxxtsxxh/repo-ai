---
name: b-skill-28
description: Apply consistent, robust error-handling patterns.
license: MIT
---

# Error Handling

Fail clearly and recover deliberately.

## Patterns

- Catch narrow exceptions, not bare `except`; handle what you can, re-raise what you cannot.
- Add context when re-raising (`raise X from err`) so the trace stays useful.
- Validate inputs at boundaries; keep the core assuming valid data.
- Return typed results or raise; do not signal errors with sentinel values silently.
- Log at the point you handle an error, not at every layer it passes through.

A good error message says what failed, why, and what to try next.
