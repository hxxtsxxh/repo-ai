---
name: b-skill-13
description: Migrate a TypeScript codebase to strict mode incrementally.
license: MIT
---

# TypeScript Strict Migration

Turn on strictness without a big-bang rewrite.

## Steps

1. Enable `strict` in `tsconfig.json`, then allow per-file opt-out while migrating.
2. Fix `noImplicitAny` first; add explicit types at module boundaries.
3. Address `strictNullChecks` with proper guards, not `!` assertions.
4. Remove `any` as you go; prefer `unknown` plus narrowing.
5. Keep the build green at each step; migrate file by file.

Small, reviewable commits make this painless.
