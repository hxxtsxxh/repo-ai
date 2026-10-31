---
name: b-skill-27
description: Write clear conventional commit messages.
license: MIT
---

# Commit Messages

Write commits that explain intent, not just the diff.

## Format

- Use Conventional Commits: `type(scope): summary` (feat, fix, docs, refactor, test, chore).
- Keep the summary under ~72 chars, imperative mood.
- Add a body explaining why when the change is non-obvious.
- Reference issues in a footer: `Closes #123`.

## Example

```
fix(auth): reject expired tokens before refresh

Previously an expired token could be refreshed once more, extending a
session past its intended lifetime.

Closes #482
```
