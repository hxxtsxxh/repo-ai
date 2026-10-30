# Engine integration review (2026-10-23, after PR #25 merged)

## State

- **PR #25 is merged** into `main` as `bc72d50`. Main's tree is exactly the
  PR head `ee554c8` (the validated engine `2f6ea31` plus docs only). Main's
  CI passed.
- **PR #28** (lower fixed overhead):
  - **Branch:** retargeted to `main`, with `main` merged in (`0ec1d65`); no
    history rewritten. Its post-copy fingerprint check was given more
    adversarial cases: an untracked file added, a tracked file deleted, and a
    symlink retargeted during the copy (`0beefbf`).
  - **Tests:** the full suite passed, 660 tests, on a quiet machine. An earlier
    run with 2 failures had overlapped with the reviewers' fork and
    process-limit experiments; both tests pass alone, 3/3.
  - **CI:** passed on `0ec1d65`.
- **This branch, `fix/core-correctness`:** the corrections below, with every
  reproduced defect pinned by a test that fails on `main`.

Four read-only specialist reviews ran: correctness, runtime security,
performance, and integration. Then a fifth, adversarial review of this
branch. Their reports and experiments are in the session scratchpad
(`agents2/`, `agents3/`).

## Root causes

### The intermittent `test_killed_update_leaves_a_recoverable_index` (Windows and Ubuntu CI)

- **Not a flaky test: a real index-corruption bug.**
  - Every `Index` write method commits on its own, and a file's stored hash is
    what tells the next incremental update the file is current.
  - A kill after `upsert_files` committed the new hashes while that file's
    symbols, imports and search rows were deleted and not yet rewritten. The
    next update then saw "unchanged" and never re-parsed the file.
  - The test's 0.8 s SIGKILL lands in that window only sometimes.
- **Deterministic reproduction** (`tests/test_index_crash_safety.py`): the
  update exits hard right after each of 9 write steps, then a normal update
  runs.
  - On `main`, 3 of 9 kill points recover; 6 leave search entries missing for
    good.
  - With the fix, 9 of 9 recover.
- **Fix:** `needs_reanalysis` is committed before the first destructive write
  and cleared last. A run killed anywhere forces one full re-analysis, and
  `status` and session start report the index as stale until then.

### marshmallow's pytest `norecursedirs`

- **Cause:** for pytest, verify treated every `test_*.py` / `*_test.py` under
  the command's paths as a test file. It read no pytest configuration at all.
- **Scale:** the correctness review reproduced the mismatch for `testpaths`,
  `norecursedirs` (any depth), `python_files`, `--ignore`, `collect_ignore`,
  `--doctest-modules`, pytest 9's `[tool.pytest]` and `pytest.toml`.
- **Per-file runs** name files explicitly, which bypasses pytest's own
  exclusions. So the fix cannot be handed to pytest's command line.
- **A static reading would be unsafe.** In the dangerous direction it would
  exclude files pytest *does* run:
  - an empty `pytest.ini` wins over `pyproject.toml`;
  - slash patterns are matched against absolute paths;
  - `testpaths` is ignored when paths are given;
  - `[tool.pytest]` applies only on pytest 9 or later;
  - `collect_ignore` is computed by repository code.
- **Fix:** the universe follows pytest's own collection.
  - The pytest reporter names every file pytest collects.
  - `--record`'s sandboxed full-suite run, which is already authorized to run
    repository code, stores that list with a fingerprint of every collection
    input: config files, `conftest.py` at any depth, files named by `-c`, the
    command and its environment.
  - **Adding:** while the inputs are unchanged, files pytest collects that the
    patterns miss (doctest modules, `python_files`) join the universe. A
    changed doctest module still selects its importers' tests.
  - **Removing:** pattern-matched files it never collects leave the universe,
    except for test files added since the recording.
  - **Never used** when the report was incomplete (any file with test events
    but no collect report: the xdist shape), or when the recording would
    remove more than half the files.
  - **Without a recording,** a note says the configuration may exclude files.
- **Residual:** the environment is not part of the fingerprint. An installed
  plugin, or a pytest upgrade that changes collection, takes effect at the
  next `--record`.

## Other corrections on this branch

**Wrong verdicts:**
- **An unresolvable `--base` passed (P0, integration review).** `--base main`
  on a `master` repository planned an empty change, and `--run` recorded a
  pass. It is now an error.
- **Staged files were invisible without a base commit (adversarial review).**
  In a new repository or on an orphan branch, `git add`-ed files are now the
  change.

**Sandbox:**
- **Unbounded output:** 600 MB of output took the host process past 2 GB. It
  is now read through a bounded buffer.
- **Forking group members** survived a single `killpg` (3 of 3). The group is
  now killed until it is gone.
- **The guardian:**
  - a registered group whose leader had exited survived; it is now killed;
  - the orphan check could kill an unrelated process that reused a pid; the
    leader's start time is now recorded at registration and compared;
  - on bwrap, the guardian inherited the blocked signals; it is now started
    before masking.

**Time-outs:**
- **Containers:** they now end at the limit + 5 s with `rm -f -t 0`. They used
  to take limit + 15 s + podman's 10 s stop timeout.
- **Hung files** are attributed after a full-suite time-out, not run again.
- **Speed choice:** a time-out never disables the full suite for speed.
- **Explicit `--timeout`** is honoured for full-suite runs. It used to become
  1800 s there.

**Contract** (`docs/VERIFY-AGENT-CONTRACT.md`):
- one definition of a passing verdict, used by the exit code and the gate;
- `evidence --json` has the same keys in every state;
- `Cancelled` exits 130;
- corrected entries: the hook entry point, schema id, verdict list and
  `confidence: none`.

## Measured (pinned builds, development fixtures; not a held-out set)

| What | `main` `bc72d50` | this branch | How |
|---|---|---|---|
| A change that makes one test file hang, after `--record` (host sandbox) | **61.0 s**, 4 processes | **31.2 s**, 2 processes | same verdict (`regression`) and the same hung file; `scratchpad/meas/hang.py` |
| Fixed overhead per `verify --run`, cachetools / tomli / markdown | 1.172 / 1.931 / 1.795 s | 1.219 / 1.932 / 1.829 s | 10 interleaved rounds (`overhead.py`); verdicts identical |

**Honest negative result:**
- The first version of this branch added +47 ms per run on cachetools (95%
  interval +2 to +104 ms). tomli and markdown were within noise.
- The cause was the new wait loop polling `Popen.wait`. It now wakes on
  end-of-file (commit `0c95284`).
- **Re-measured on the final build** (10 interleaved rounds), B − A:

  | project | B − A | 95% interval |
  |---|---|---|
  | cachetools | +0.009 s | [−0.06, +0.07] |
  | tomli | +0.038 s | [−0.06, +0.25] |
  | markdown | −0.024 s | [−0.23, +0.29] |

  - Every interval includes 0, and verdicts were identical in every round.
  - Another session's test suite ran at the same time, so absolute times are
    noisier than in the first measurement.
- The hang case on the final build is still **31.2 s** (unchanged).
- Held-out-5 was **not** re-run: the frozen evidence stays as it was. The
  estimate for its two hang rows (111 s → about 31 s, 91 s → about 61 s) is
  from the code path, not measured.

## Merge readiness

- **PR #25:** merged; its own verdict was READY TO MERGE AS EXPERIMENTAL.
- **This branch:** ready to merge as a corrective PR once CI is green on its
  head. Every claim in it is pinned by a test that fails on `main`, and it
  went through one corrective pass after the adversarial review.
- **PR #28:** compatible with `main` and green. Merge it after this branch,
  and re-check it once `main` contains both.
  - Its measurement covers 3 Python projects on the host only, and its "p95"
    with n = 10 is the maximum (performance review).
  - Its savings (−0.14 to −0.20 s per run) are real for the host sandbox; on
    podman they are unmeasured.

## Release blockers (not ready to release)

1. **The speed targets on sub-second suites** (held-out-5: 4 of 7 slower than
   native). PR #28 helps but does not reach the target.
2. **Hang cost** remains up to one time limit per hanging file. The per-test
   watchdog (`docs/VERIFY-WATCHDOG.md`) is the next milestone, with its
   acceptance criteria written.
3. **TypeScript** has not been re-validated since held-out-4.
4. **Windows:** there is no host sandbox and no guardian, and a killed
   `repo-ai` can leave a container running.
5. **CI can pass with zero sandboxed tests** (integration review): the bwrap
   and macOS jobs skip instead of failing when the sandbox is missing.
   `REPO_AI_REQUIRE_SANDBOX` is proposed.
6. **The diagnostics interface** for optional tools is specified, not
   implemented.

## Next recommended milestone

The per-test watchdog, Phase 1, against its written acceptance criteria.
Any held-out re-run needs the owner's approval.
