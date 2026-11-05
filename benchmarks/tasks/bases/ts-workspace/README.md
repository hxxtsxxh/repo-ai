# jobrunner workspace

A small job scheduler split into three workspace packages. Everything is
plain TypeScript executed directly by Node's built-in type stripping, so
there is **no build step and no dependencies**.

| Package | Purpose |
| --- | --- |
| `packages/core` | Shared primitives: durations, schedules, retry/backoff, semver ranges, config resolution, an event bus, a token-bucket rate limiter and the job lifecycle |
| `packages/api` | An HTTP-shaped API (`createApi().handle(request)`) over an in-memory job store, with API-key scopes, cursor pagination and rate limiting |
| `packages/cli` | The `jobs` command-line client; talks to the API in-process |

Requirements: Node.js >= 22.18 (type stripping enabled by default).

## Conventions

* Cross-package imports are relative and include the `.ts` extension,
  e.g. `import { parseDuration } from "../../core/src/duration.ts";`.
* Only erasable TypeScript syntax is allowed (no `enum`, `namespace`,
  parameter properties or decorators). Type-only imports use `import type`.
* Durations accept `ms`, `s`, `m`, `h` and `d` units and may be combined
  (`1h30m`). A bare number is seconds.
* Configuration precedence: built-in defaults < config file < environment
  (`RUNNER_*`) < explicit overrides such as CLI flags.

## Tests

```
npm test            # all packages
npm run test:core   # one package
cd packages/api && npm test
```

Tests use `node:test` and `node:assert/strict`.

## CLI

```
node packages/cli/src/main.ts list --status failed
node packages/cli/src/main.ts create nightly-report --command "report.sh" --schedule "daily at 02:00" --timeout 10m
```
