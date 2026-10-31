---
name: b-skill-02
description: Review and author React components following modern hooks conventions.
license: MIT
---

# React Component Style

Guidance for writing consistent, accessible React components.

## Conventions

- Function components with hooks; no class components in new code.
- Keep components small; extract logic into custom hooks (`useXxx`).
- Co-locate styles and tests with the component.
- Derive state rather than duplicating it; avoid unnecessary `useEffect`.
- Always provide accessible labels for interactive elements.

## Checklist

1. Props typed with TypeScript interfaces.
2. No inline anonymous functions in hot render paths where avoidable.
3. Memoize expensive children with `React.memo` only when profiling shows a need.

Prefer clarity over cleverness.
