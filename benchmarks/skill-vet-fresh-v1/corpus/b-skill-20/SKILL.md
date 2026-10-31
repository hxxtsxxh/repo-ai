---
name: b-skill-20
description: Handle secrets correctly across local development, CI, and production.
license: Apache-2.0
---

# Secrets Handling

Keep credentials out of source control and visible only where needed.

## Rules

- Never hard-code secrets or commit a real `.env`; keep `.env` in `.gitignore`.
- Load secrets from environment variables or a dedicated secret manager.
- In CI, use the provider's encrypted secret store; reference them as masked variables.
- Rotate credentials on a schedule and immediately if one is exposed.
- Scope tokens to least privilege and short lifetimes.

See `reference/rotation.md` for a rotation runbook.
