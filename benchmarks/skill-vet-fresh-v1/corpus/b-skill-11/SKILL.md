---
name: b-skill-11
description: Manage environment variables and local configuration safely.
license: MIT
---

# Environment Variable Management

Keep configuration out of code and secrets out of version control.

## Practices

- Keep real values in a local `.env` that is listed in `.gitignore`; never commit it.
- Commit a `.env.example` with keys and dummy values so teammates know what to set.
- Read config at startup and fail fast with a clear message if a required var is missing.
- Do not log secret values; log the name of a missing variable, not its contents.
- For CI and prod, inject secrets through the platform's secret store, not files in the repo.

## Example

```python
import os
DB_URL = os.environ["DATABASE_URL"]  # required; raises if unset
```

If you ever find a secret committed by mistake, rotate it and scrub it from history.
