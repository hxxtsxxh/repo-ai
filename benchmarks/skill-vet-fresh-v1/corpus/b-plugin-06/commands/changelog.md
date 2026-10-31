---
description: Draft a changelog entry from commits since the last tag
allowed-tools: Bash
---

Collect commits since the last git tag with `git log $(git describe --tags --abbrev=0)..HEAD --oneline`,
then group them into Added / Changed / Fixed and draft a `CHANGELOG.md` section. Show the draft
for the user to review before writing it.
