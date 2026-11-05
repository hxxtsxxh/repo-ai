---
name: impact
description: "Estimate the blast radius of changing a file or symbol: importers, tests, CI, co-change history, uncertainty. Use before refactors or risky edits."
argument-hint: "<path | SymbolName | --changed>"
---

# Change impact

1. Run `repo-ai impact "$ARGUMENTS"` (a path, a symbol name, or `--changed`
   for the current working-tree diff).
2. Summarise for the user:
   - direct and transitive importers (blast radius),
   - tests to run, from the "tests" section,
   - CI or build files that reference the area,
   - files that historically change together with it,
   - the uncertainty notes — static analysis misses dynamic imports, reflection,
     dependency injection and string-based routing; never claim full coverage.
3. Do not edit anything as part of this skill.
