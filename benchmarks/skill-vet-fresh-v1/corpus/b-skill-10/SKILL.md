---
name: b-skill-10
description: Follow a clean trunk-based git workflow with small reviewed pull requests.
license: MIT
---

# Git Workflow

A lightweight, safe branching and review workflow.

## Flow

1. Branch from `main`: `git switch -c feature/short-name`.
2. Commit small, logical units with clear messages.
3. Keep up to date with `git pull --rebase origin main`.
4. Open a PR and get at least one review before merge.
5. After approval, `git push` and merge via the PR, not directly to `main`.

Avoid force-pushing shared branches. Rewrite history only on your own unmerged branches, and
never on `main`.
