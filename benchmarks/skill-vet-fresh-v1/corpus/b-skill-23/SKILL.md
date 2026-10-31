---
name: b-skill-23
description: Write and run safe, reversible database migrations.
license: MIT
---

# Database Migrations

Evolve the schema without downtime or data loss.

## Practices

- One logical change per migration; make them reversible where possible.
- Separate schema changes from data backfills; backfill in batches.
- For destructive changes, use expand-then-contract: add new, migrate, then remove old in a
  later release.
- Test the migration on a copy of production-like data before applying.
- Keep migrations in version control and run them in CI against a fresh database.

Never edit an already-applied migration; add a new one.
