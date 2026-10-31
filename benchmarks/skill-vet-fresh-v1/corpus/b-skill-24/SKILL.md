---
name: b-skill-24
description: Organize a monorepo with clear package boundaries and shared tooling.
license: MIT
---

# Monorepo Structure

Keep a multi-package repository maintainable.

## Guidelines

- Group by domain under `packages/` or `apps/`; keep boundaries explicit.
- Share config (lint, tsconfig) via a base package; extend per package.
- Use a workspace tool (pnpm/uv/turborepo) for dependency graph and task running.
- Enforce that packages depend only on their declared dependencies.
- Keep CI incremental: build and test only what changed.

Clear boundaries keep a monorepo from becoming a big ball of mud.
