---
name: orient
description: "Orient in this repository: purpose, components, commands, hotspots and freshness of repo-ai's map. Use at the start of unfamiliar work."
---

# Orient in this repository

1. Run `repo-ai status` to see whether the map is current (exit code 2 means stale;
   run `repo-ai update` first if many files changed).
2. Read the output of `repo-ai overview`, then skim the output of `repo-ai architecture`.
3. Run `repo-ai hotspots | head -30` for the files under active change.

Report in at most 12 lines: what the project does, its components and how they
connect, the build/test/run commands, and the three files to read first for the
user's goal. Do not read other files for this step.
