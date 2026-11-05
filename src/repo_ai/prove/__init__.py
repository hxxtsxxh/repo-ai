"""ProofLab: evidence that a change does what it claims, not only that it
breaks nothing.

`repo-ai verify` answers "what can this change break, and did it?". ProofLab
answers a different question about the same change: **does the original code
show the targeted failure, does the candidate fix it, under the same oracle,
and what remains unproven?**

* ``claim``      - a pinned behavioural claim and its acceptance scenario: the
  scenario's exact bytes, where they came from, and who pinned them;
* ``conditions`` - what decides how the scenario runs besides its own bytes
  (conftest.py, pytest configuration, test helpers and data next to it, the
  runner command), compared between the base and the candidate;
* ``experiment`` - the same scenario bytes in a disposable copy of the base and
  of the candidate, sandboxed (``verify.execute``), the base's own versions of
  edited tests run against the candidate, and the regression check
  (``verify.engine.run_plan``);
* ``passport``   - the machine-readable record of one experiment, its verdict
  and its freshness;
* ``render``     - the terminal and the Markdown (pull-request) report.

Nothing here runs repository code except ``experiment.run``, which only runs
inside verify's sandboxes and disposable copies. There is no unsandboxed
fallback.
"""
