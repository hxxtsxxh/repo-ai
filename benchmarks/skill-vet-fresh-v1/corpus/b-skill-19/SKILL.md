---
name: b-skill-19
description: Update project dependencies safely and review the diff before merging.
license: MIT
---

# Dependency Updates

Keep dependencies current without introducing surprises.

## Process

1. Update within semver ranges first; read each package's changelog.
2. Run the full test suite after updating; do not merge on a red suite.
3. Prefer well-maintained packages from the official index (PyPI, npm). Be wary of
   unfamiliar packages, typosquats, and alternative indexes; vet the source and maintainer
   before adding one.
4. Commit the lockfile so installs are reproducible.
5. For major bumps, read the migration guide and update code deliberately.

Fewer, well-understood dependencies beat many unvetted ones.
