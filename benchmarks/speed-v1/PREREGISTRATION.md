# speed-v1: how long `verify --run` takes on real upstream commits, against the native suite (preregistered)

Acceptance gate C16 (performance) and the site's "not shown" speed item. This protocol, the harness (`run.py`)
and the workflow (`.github/workflows/speed.yml`) are committed before any measurement. Spend: $0 (GitHub-hosted
runners on a public repository). Third-party code runs only on those disposable runners.

## Question

When a developer changes a real project the way its maintainers did, how long does `repo-ai verify --run` take,
compared with running the project's own full test suite? The earlier measurement (held-out-7, before 0.9) found
verify slower on 3 of 5 projects (1.44–2.31×) and faster only on the larger ones.

## Projects (pinned before any run)

| project | ref | install |
|---|---|---|
| jpadilla/pyjwt | 2.10.1 | `.[crypto]` pytest |
| python-humanize/humanize | 4.12.3 | `.` pytest freezegun |
| more-itertools/more-itertools | v10.7.0 | `.` pytest |
| pallets/itsdangerous | 2.2.0 | `.` pytest freezegun |
| marshmallow-code/marshmallow | 4.0.0 | `.` pytest simplejson |

A project whose suite does not pass at its pinned ref on the runner (native exit code not 0) is reported as
`INVALID_BASELINE` and excluded, with the reason. Nothing else is excluded.

## Changes (selected by `run.py`, mechanically)

Walking back from the pinned ref (`git log --no-merges --first-parent`), the first **6** commits that change at
least one `.py` file outside test directories, change no dependency or configuration file (`pyproject.toml`,
`setup.py`, `setup.cfg`, `requirements*`, `tox.ini`, `noxfile.py`, `conftest.py`), and change at most 300 lines.
Each change is replayed as the maintainers made it: the parent is checked out and the commit's diff is applied to
the working tree.

## Measurements, per change (one fresh clone per project, `--workers 4`, the runner's bwrap sandbox)

- **native:** the project's full suite, `python -m pytest -q -p no:cacheprovider`, in the changed tree,
  unsandboxed (the runner is disposable), median of 3 wall-clock runs, with its exit code.
- **verify (cold):** `repo-ai verify --run --json`, the first verification of that state.
- **verify (reuse):** the same command again (evidence may be reused).
- **verify (rerun):** `repo-ai verify --run --rerun --json` (fresh run, warm caches).
- recorded: wall-clock seconds, verify's verdict and selected test files, exit codes, runner CPU count and model.

repo-ai is installed from the commit under test into its own virtual environment; each project gets its own
`.venv` inside its clone, which verify uses as the project interpreter. repo-ai's state directory is excluded
through `.git/info/exclude`, so the working tree holds only the replayed change.

## Analysis (decided now)

- Per change: ratio = verify (cold) / native median. Also reuse and rerun ratios.
- Reported: per-project median ratio, the geometric mean over all valid changes, the number of changes where
  verify (cold) is slower than the native suite, and verify's verdict next to the native exit code.
- **Reading rule.** "verify is faster than the native suite on these projects" may be stated only if the
  geometric mean of the cold ratio is below 1.0 **and** verify is slower on fewer than half the valid changes.
  Otherwise the result is stated as measured (for example "slower on 9 of 28 changes"), with the overhead.
- Either way the claim is limited to these five pure-Python projects, this runner type and selective runs; it is
  not a general speed claim.

## Rules

One run of the workflow on the commit that adds this file. A harness crash is fixed and the run repeated; the
selection, projects and analysis are not changed after a run. Results: the run's artifact, then `RESULTS.md`
with the run URL.

## Amendment 1 (2026-10-31, after run 1; harness defect, analysis unchanged)

Run 1 (GitHub Actions run 41239830514, commit 8b8d7e5) is **invalid** and kept only as a record. The harness
installed each project non-editable (`pip install .`) at its pinned ref and then replayed older commits. In
src-layout projects (itsdangerous, marshmallow) pytest imported the installed release, not the working tree, so
the native suite tested different code from the change (for example `No module named 'itsdangerous.jws'`, from
tests older than the installed package). The fix installs every project editable (`pip install -e`), so both
sides import the working tree, and records verify's failing-test detail and a longer native tail, so that a
disagreement between verify and the native suite can be explained. Projects, selection, measurements and the
reading rule are unchanged. Run 2 is the measurement.

## Amendment 2 (2026-10-31, after run 2; disclosed, run 2 stands)

An independent review found that the harness reset tracked files between changes (`git checkout -- .`) without
removing untracked ones, so files a commit adds leaked into the older changes replayed after it (humanize: 2 of
30 measurements). Run 2 stands as recorded, with the two measurements disclosed in RESULTS.md. The harness now also
runs `git clean -fdq` (which keeps ignored paths: the project's `.venv` and repo-ai's state) before each change, for
any future run.

## Amendment 3 (2026-11-01, before run 3; a replication, analysis unchanged)

Run 2 remains the speed-v1 result. **Run 3** repeats it, unchanged in projects, pinned refs, selection,
measurements and reading rule, on a later repo-ai commit (main at c462f0e, after 0.11.5 and PR #60), with the Amendment 2
harness. Two questions, both stated before the run:

1. **Overhead.** Does verify's fixed cost per change differ from run 2's (median +0.63 s, cold ratio 1.84×)?
   PR #60 removed about 80 ms of argument-parser imports from every command; its git change applies only on
   macOS, so little difference is expected on this Linux runner.
2. **Agreement.** Run 2's disagreements with the native suite were attributed to causes fixed in 0.11.4 and
   0.11.5 (more-itertools: a lint-only `make check` taken for the suite and a unittest marker; humanize: a
   git-ignored version file missing from verify's copy). Are they gone? pyjwt's network-denied tests are expected
   to stay `pre-existing` (verify's sandbox denies the network) and to be named as sandbox-network suspects.

Run 3 is reported next to run 2 in RESULTS.md, whatever it shows. The reading rule is applied to run 3 alone;
the two runs are not pooled. Spend: $0 (GitHub-hosted runner).
