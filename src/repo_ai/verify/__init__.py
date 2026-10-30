"""Change verification: what a change touches, which tests can show whether it
broke something, and what running them actually showed.

The engine is deliberately evidence-first:

* ``changes``  - the diff against a base revision, mapped to the code objects
  (functions, class bodies, module code) whose lines changed;
* ``dynamic``  - where static imports cannot see consumers (loaders that take
  a computed name, entry points, string references);
* ``testmap``  - runtime evidence: which code objects each test file actually
  executed, recorded by running the suite once under a tracer;
* ``select``   - the union of static and runtime evidence, with explicit
  full-suite triggers and a confidence that is never "safe";
* ``isolate``  - disposable copies of the change, so tests never run in (or
  write to) the developer's tree, and before/after integrity snapshots;
* ``execute``  - authorized, sandboxed runs with a baseline check that tells
  new failures from pre-existing ones;
* ``evidence`` - machine-readable records of what was verified, for which
  exact working tree.

Nothing in this package runs repository code unless a caller passes an
explicit run/record request; planning is read-only.
"""

import os as _os

# Read-only toward the repository, git's own housekeeping included: without
# this, `git diff` rewrites .git/index to refresh its stat cache.
_os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")
