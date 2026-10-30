# `repo-ai verify`: threat model

**Scope:**
- `repo-ai verify` (planning);
- `verify --record` and `verify --run [--full]` (execution);
- `repo-ai evidence`;
- the opt-in `Stop`-hook gate.

**Reviewed:** 2026-10-22, against the code in PR #23. Re-reviewed for the
adaptive engine (per-test reports, run shapes, caches, evidence reuse): T16–T21.
Each control names the test that checks it.

## What is protected

| Asset | Why it matters |
|---|---|
| The developer's working tree, including uncommitted work | losing or silently changing it is the worst outcome a verification tool can have |
| `.git` (objects, refs, index, hooks, config) | corrupting history or planting a hook persists beyond the run |
| Ignored and untracked secrets beside the code (`.env`, keys, `credentials.json`) | tests must not read what the developer never committed |
| The home directory and the rest of the host filesystem (`~/.ssh`, `~/.aws`, other repositories) | the classic exfiltration targets |
| The network | exfiltration and supply-chain fetches |
| The integrity of verification evidence | the gate and `repo-ai evidence` report it as fact |
| Agent permissions | repo-ai must never widen what Claude Code or another agent may do |

## Who runs what

- **Planning** (`repo-ai verify`, `--json`, `--gate`) executes **no repository
  code**.
  - It reads files and runs `git` plumbing (`rev-parse`, `diff --no-ext-diff`,
    `ls-files`, `cat-file`, `archive`).
  - Verify sets `GIT_OPTIONAL_LOCKS=0`, so even git's opportunistic index
    refresh does not write `.git/index`.
- **Execution** (`--run`, `--record`) runs the project's tests, which is
  repository code.
  - It happens only when the user passes one of those flags.
  - The command is printed first, with its origin: `--test-command`,
    `.repo-ai/config.toml`, declared in the project's files, or inferred from
    the tests.

## Threats and controls

| # | Threat | Control | Checked by |
|---|---|---|---|
| T1 | A test (buggy or hostile) writes, deletes or chmods files in the working tree | Tests never run in the working tree: every run uses a **disposable copy** in a private (0700) per-user directory. The sandbox's only writable location is that copy. The original is not even readable (seatbelt: no read rule for it; bwrap and containers: not mounted). | `test_hostile_tests_cannot_touch_the_source_tree_git_or_secrets` |
| T2 | A test reaches `.git` (rewrites config, plants a hook, edits refs) | `.git` is never copied, and the original is unreachable (T1) | same test (`write_git`, `read_git`, `git_in_copy`) |
| T3 | A test reads ignored or untracked secrets | Ignored files are never copied. Untracked, non-ignored files that look like credentials (`.env`, `*.pem`, `id_rsa`, …; the same globs the indexer quarantines) are **withheld** and listed in the evidence. The original tree is unreachable. | `test_the_copy_is_the_working_tree_without_git_ignored_files_or_credentials`, hostile test (`read_ignored_secret`, `read_untracked_credential`, `secret_in_copy`) |
| T4 | A test reads the home directory or the rest of the host | **seatbelt:** deny-by-default reads (system and toolchain directories, the copy, the interpreter's prefix; never `$HOME` or `/`). **bwrap:** only system directories are bound. **containers:** only the copy is mounted. `HOME` and `TMPDIR` point inside the copy. | hostile test (`list_home`), `test_sandbox_extra_reads_never_open_home_or_root` |
| T5 | Network exfiltration | No network in any backend (seatbelt rule omitted, bwrap `--unshare-all`, containers `--network=none`). Unchanged from 0.7. | `tests/test_sandbox.py` escape tests |
| T6 | The working tree changes anyway (a backend bug, a concurrent editor) | **Integrity snapshot before and after** every run and recording: the stat of every entry, `.git` and ignored files included, plus the content hash of every working-tree file. Any difference marks the evidence **invalid**, makes the command fail loudly, and stops a recording from being saved. The copy must also match the planned change's fingerprint before anything runs. | `test_snapshots_detect_changes_to_source_git_and_ignored_files`, `test_failing_runs_and_timeouts_leave_the_tree_unchanged` |
| T7 | Tests outlive the run (servers, daemons, sleepers) | Every test process runs in its own process group, killed on exit, timeout or cancellation. **seatbelt** (no PID namespace): each run's profile carries a unique rule that grants nothing, `(allow user-preference-read (preference-domain "com.repo-ai.run.<random>"))`. It is inherited by every descendant and cannot be dropped (a sandboxed process cannot apply another profile: `sandbox_apply` fails with EPERM). When the run ends (pass, failure, time-out, cancellation; the guardian if repo-ai is killed), every process on the machine is checked with `sandbox_check(pid, …)`. A process is the run's only when it is sandboxed, allows that domain and denies a control domain with the same prefix: an unsandboxed process allows every domain and another sandbox denies a random one. Those processes are SIGKILLed, pass after pass, until a pass finds none or the 3 s budget runs out; only a pass that finds none confirms the cleanup. An empty pass proves something only if the check works: so once per repo-ai process, a probe run (`/bin/sleep` under a run profile with its own domain, about 30 ms) must be recognised as that run's and as no other's, or every cleanup is reported unconfirmed. A process's start time is read before it is classified, after, and again before the kill, so a reused pid is never taken for the run's or signalled. `setsid`, a double fork (adopted by launchd), a cleared environment, `chdir /` and Apple binaries (whose environment `ps -E` hides) no longer escape it. When the cleanup cannot be confirmed (the process table or the sandbox cannot be asked, or a process cannot be killed), the result notes say so, and so does `verify` (stderr warning; `sandbox_cleanup_unconfirmed` in `--json`). The run then stays registered for cancellation and the guardian. The environment marker scan remains only as the fallback for that case. bwrap uses a PID namespace that dies with the run. Containers are removed. | hostile test (`_stragglers() == []`, including a `setsid` child); `tests/test_sandbox_descendants.py` (detached `/bin/sleep`, double-fork daemon, time-out, SIGINT/SIGTERM, parent SIGKILLed, `verify --run` end to end, processes outside the run untouched, pid reuse on a fake process table) |
| T8 | The developer cancels (Ctrl-C, SIGTERM, SIGHUP) and processes or copies are left behind | Every live process group and container is killed, new starts are refused, the copy is deleted, nothing is recorded, and the command exits with 130. Copies left by a killed repo-ai are swept on the next run (owner PID gone). | `test_cancellation_kills_tests_deletes_the_copy_and_leaves_the_tree_unchanged[SIGINT,SIGTERM]`, `test_workspaces_live_in_a_private_directory_and_stale_ones_are_swept` |
| T9 | Resource exhaustion (fork bombs, memory, disk, endless output) | CPU-time, file-size and core rlimits (host); pids, memory, CPU and tmpfs limits (containers); per-file timeout (default 600 s). Output is read through a bounded buffer: the last 64 KiB per stream is kept and the rest is counted and dropped, so endless output costs bounded host memory (before 2026-10-23 it was all buffered: 600 MB of output took the host process past 2 GB). **Not limited:** the number of processes a host-sandboxed test may start (no `RLIMIT_NPROC`; containers have `--pids-limit`). A fork bomb on a host backend can exhaust the user's process slots until the run's time limit. | `tests/test_sandbox.py`, `test_endless_output_costs_bounded_host_memory` |
| T10 | Symlinks used to reach outside the copy | A symlink escaping the repository is not copied (listed as skipped). The sandbox refuses a workspace with an escaping symlink, except the declared read-only dependency links. `git archive` extraction drops escaping links and non-regular members. | `test_modes_and_symlinks` |
| T11 | Repository configuration steers execution (a hostile `package.json` script, Makefile, `verify_test_command`) | Commands are **parsed, never passed to a shell**. Only `unittest`, `pytest` and `node --test` invocations, with an allowlisted, repository-relative `PYTHONPATH` and similar, are executed. Scripts are resolved by reading files. Any `\|\|`, `;`, pipe or redirection, any build step before the tests, or an unknown tool makes the command opaque, and opaque commands are never run. The tests themselves are repository code and run sandboxed (T1–T9). | `tests/test_verify_commands.py` (`test_shell_operators_other_than_and_stay_opaque`, `test_lint_and_type_steps_…_build_steps_keep_it_opaque`) |
| T12 | Host-side probing runs repository code (a `.pth` file in the project's virtualenv) | Interpreter probes use `python -I -S` (no `site`, no `.pth`, no `PYTHON*` variables), and only for an interpreter outside the repository; one inside it is never probed (T24). Editable-install detection reads `.pth` and `__editable__` finder files as **text**. | `test_editable_installs_are_redirected_to_the_copy` |
| T13 | The test command or output leaks secrets into evidence | Evidence stores paths, statuses and short failure excerpts, with credential-looking assignments masked. It never stores the environment. The sandbox environment is rebuilt from an allowlist (no tokens, SSH agent or cloud credentials). Evidence lives in `.repo-ai/state/`, which is git-ignored. | `test_record_run_and_evidence_end_to_end`, `evidence.scrub` |
| T14 | Agent permissions | `verify` never edits agent settings. The gate is opt-in (`verify_gate`), honours `stop_hook_active`, blocks at most once per change and at most `verify_gate_max_blocks` (3) times per session (or, with `verify_gate_mode = "report"`, never blocks), and fails open. Passing evidence also covers a later rewrite with the same Python syntax tree or the same conservative JS/TS token stream; a false "same" there could only silence the gate, never alter a run, which always uses exact content. Nothing grants an agent new tools or permissions. | `test_the_stop_hook_gate_is_opt_in`, `test_gate_is_silent_until_…_blocks_once`, `tests/test_verify_gate.py` |
| T15 | Time-of-check versus time-of-use between planning and running | The copy is made *after* the plan. Its change fingerprint must equal the plan's, or nothing runs. The integrity snapshot covers the whole window. | `engine._prepare` (fingerprint check), `test_the_quick_fingerprint_matches_the_full_change_detection` |
| T16 | A test forges its per-test report to turn a failure into a pass | The report (`.repo-ai/run/*.jsonl` in the disposable copy) is written by the process under test, so it is read as **untrusted data**: size-capped (32 MB, 400k events), every field type-checked, and **trusted only when it agrees with the process**. The process must finish without a timeout, the report must be complete, its failures must agree with the exit code, and every failure must map to a file the process was asked to run. An untrusted report changes nothing: the files are run one by one as before. A process that fails can never be reported as passing as a whole. Residual: inside a *failing* multi-file process, the report decides which of its files failed, so a test written to rewrite the report could move failures between the files that ran with it. That is the trust evidence already places in tests (residual risk 6); runs of single files are unaffected. | `test_reports_that_disagree_with_the_process_are_not_trusted`, `test_a_forged_passing_report_cannot_turn_a_failure_into_a_pass`, `test_an_oversized_report_is_not_read` |
| T17 | The reporters change what the tests do | They are copied into the disposable copy (never imported on the host) and run with the project's own interpreter or Node, like the 0.8 tracer. They record ids, outcomes, the first line of each failure and durations; never values or the environment. Two documented behaviour changes, both towards running each file as it would run alone: in a batch, a unittest module that raises a non-`ImportError` at import fails as one test instead of aborting the batch, and a pytest batch continues past a collection error. The project's own full-suite command runs as is (`native`). | `test_a_unittest_batch_is_attributed_per_file_exactly_like_separate_runs`, `test_a_pytest_batch_is_attributed_per_file_and_continues_past_collection_errors` |
| T18 | A cached base outcome hides a new failure | Base outcomes are cached per environment (`cache.environment_key`: repo-ai version, backend, image digest, interpreter or Node binary, installed distributions, dependency directories, the test command) and per base **tree**. A cached **pass** can only make a failure look new, so one observation suffices. A cached **failure** could hide a regression, so it is used only after two independent base runs agreed. A test seen both passing and failing is marked flaky and is always re-run. The cache lives in `.repo-ai/state/`, outside every copy, so tests cannot write it. | `test_base_outcomes_are_trusted_asymmetrically` |
| T19 | Reused evidence vouches for a different state | Evidence is reused only for the same change fingerprint, base commit, environment key, selection and full-suite requirement, recorded less than a day ago, with the source tree unchanged. `--rerun` always runs. The reused record is marked `reused`. A record forged in `.repo-ai/state/evidence/` with a matching key would be reused: the same local trust as the gate (residual risk 5). | `test_reusable_evidence_must_match_exactly_and_be_recent`, `test_a_failing_batch_is_attributed_…` (reuse step) |
| T20 | The run shape weakens a guarantee (a faster shape that checks less) | Every shape runs in the same sandbox, in disposable copies, with the same integrity checks. The full suite is chosen only when it is not expected to be slower, and it runs every selected test and more. A test file skipped as a duplicate (an aggregator) is skipped only when its own record shows it re-runs other selected files' tests and adds no changed code of its own. A file in which no test ran is `no-tests`, never a pass, and a run where nothing executed is never reported as passing. A file whose tests all skip (or that defines none) is run at the base; if its tests ran there, the verdict is `not verified`. An aggregator is skipped only when its top level is imports alone. | `test_the_full_suite_is_chosen_only_when_…`, `test_aggregators_that_add_no_evidence_are_skipped`, `test_helper_modules_matched_by_the_pattern_are_not_failures`, `test_verdicts_never_call_unverified_runs_passing` |
| T22 | A test replaces a file the host reads afterwards (its report, trace or coverage) with a FIFO, a device or a link to a host file | `isolate.read_inside` opens each path component under the workspace without following links (`openat` with `O_NOFOLLOW`), opens the file non-blocking, reads only a regular file, and bounds the size. Anything else is "no report": the files run one by one. | `test_a_report_replaced_by_something_other_than_a_file_is_not_read` (FIFO, `/dev/zero`, host file, linked directory) |
| T23 | Cancellation leaves a test process or container running | (1) In the main thread, SIGINT, SIGTERM and SIGHUP are blocked from before the fork until the process is registered; the child unblocks them before exec; the guardian is started before that mask. (2) When the test process ends but its output stays open, its group is killed and the marker scan runs; the output pipes are then waited for at most 5 s, and a process that left the group and still holds them is abandoned with a note (the run never waits for it, and never reports it as killed). (3) The group is killed repeatedly until it is gone (bounded): one `killpg` raced a member that was forking (reproduced 3 of 3 times). (4) A cancelled container run removes its container before forgetting it; a time-out removes it at the limit + 5 s with `rm -f -t 0`. (5) **POSIX only:** if `repo-ai` itself is killed outright, a guardian process (repo-ai's own code, `python -I`) sees its pipe close and kills each registered test group whose leader is the same process (start time recorded at registration) or whose leader has exited while the group still exists (a pid is not reused while its process group exists); it kills every process of the seatbelt runs still registered (found by their sandbox, T7) and what carries the run markers, and removes registered containers. It needs to `fork` `ps`: at the user's process limit it falls back to killing registered groups that still exist. Windows has no guardian: a killed `repo-ai` there can leave a container running until it ends. No absolute guarantee: residual risk 2 applies. | `tests/test_sandbox_cancellation.py`, `test_cancellation_kills_tests_deletes_the_copy_and_leaves_the_tree_unchanged` |
| T21 | A tighter time limit hides a failure | Limits follow measured times (5x + 10 s, at least 30 s, at most the configured limit) unless `--timeout` is given. A time-out is a failure, never a pass. A batch time-out names the test that was running, keeps the results of files that had finished (every test the file was about to run ended, from the reporters' `collected` lists, so reordered tests cannot make an unfinished file look finished), and runs the rest again. | `test_a_hanging_file_in_a_batch_is_reported_and_the_rest_still_run`, `test_process_limits_follow_measured_time_unless_given` |
| T24 | The repository ships its own interpreter (a committed `.venv/bin/python` script), which verify would execute on the host to ask its prefixes and site-packages, before any sandbox exists | An interpreter in a virtualenv that git tracks or has staged is the repository's code: it is never executed and never chosen (`execute._committed`). The match is case-insensitive (macOS: `.VENV` is `.venv`) and follows symlinks. This also applies to an active `VIRTUAL_ENV` inside the repository. The next candidate is used instead: an untracked local `.venv`, then `python3` on `PATH`. When git cannot answer, the interpreter is not used. Since 2026-10-25 (F2b), **no interpreter inside the repository is executed on the host at all**, tracked or not: a `.venv/bin/python` planted in the working tree (an applied patch, an extracted archive, `git reset` of a hostile commit) cannot be told apart from the developer's own ignored `.venv`, so it may still be chosen, but its prefixes and site-packages are read from `pyvenv.cfg` as text (`home`, `version`/`version_info`, `include-system-site-packages`) and the directory layout (`isolate.static_venv`). "Inside" is decided for the path as given, through its directory's links and fully resolved, by directory identity (another spelling of the root still counts). A virtualenv whose metadata is missing, not a regular file, or disagrees with the layout (no base `python3.X` in `home`, no standard library beside it, no `lib/python3.X/site-packages`) is refused, and the next candidate is used. The base prefix granted to the sandbox is where the standard library is, never merely `home`'s parent, so a hostile `home` cannot open up a wider directory than an interpreter installation. Interpreters outside the repository keep the `-I -S` probes. A version-manager shim (pyenv, asdf) is never run on the host, neither to find the interpreter nor the directories the sandbox reads: the version file it obeys is the repository's (`.python-version`, `.tool-versions`) and can name a program inside it. The interpreter is read from pyenv's files, or the candidate is skipped. The directories the repository's `pyvenv.cfg` (`home`) or `bin/python` link point to are readable in the sandbox only when they are, or lie inside, the virtualenv or the validated base installation (the F2b security and defensive reviews, 2026-10-25). **Residual:** the metadata is the repository's: it chooses which existing installation runs the tests (inside the sandbox) and which installation directories the sandbox may read; with `include-system-site-packages = true`, system site-packages are found by the usual layouts only (`lib/python3.X/site-packages`, Debian's `dist-packages`), so a distribution-specific location (Homebrew's `/opt/homebrew/lib/python3.X`) is left out of the environment identity. Found by the ProofLab security review (2026-10-24). | `tests/test_verify_committed_interpreter.py`, `tests/test_verify_static_interpreter.py` |
| T25 | `repo-ai evidence` or the completion gate calls a pass current after the test environment changed (`pip install -U`, a recreated virtualenv, an edit inside site-packages or `node_modules`): the fingerprint covers the change, not the environment (X13b) | A run records `environment_static` (the interpreter and `pyvenv.cfg` by `stat`; the site-packages and read-only dependency directories by every entry's metadata, `cache._tree_id`), taken before its tests start. Both readers recompute its digest from recorded paths (`stat`, `scandir`, `readlink`), compare the repo-ai version and resolve the current interpreter selection statically. Virtualenv and version-manager metadata may be read, but the gate never executes the interpreter or repository code. A mismatch, a vanished path, or a malformed or unknown identity is stale: `current: false`, `stale_reason: "environment"`, and the gate shows the change once more as unverified. **Residual:** records missing version or environment identity now read as stale. A container image, the standard library and code outside the recorded directories are not compared; the record is a local file an agent could forge (residual 5). The defensive review of the corrective integration (2026-10-25) named three such gaps, which `cache.environment_key` shares, so none is a regression: an edit inside a `__pycache__` directory of site-packages (`_tree_id` skips `__pycache__` everywhere, and Python can run a cached `.pyc`); a package that site-packages reaches through a symbolic link (links are recorded by target, not followed); the source of an editable install outside the repository (a `.pth` path line). Not fixed yet. | `tests/test_verify_environment_freshness.py` |

## Residual risks (not fixed; stated)

1. **macOS seatbelt is a shared-kernel, same-user sandbox.** It is weaker than
   a container: kernel or `sandbox-exec` bugs are out of scope, and Apple marks
   `sandbox-exec` deprecated. Use `--sandbox podman` for untrusted code.
2. **On macOS, a seatbelt run's cleanup is a sweep, not a kernel guarantee.**
   Since 2026-10-25 a process that left the run's process group is found by
   its sandbox (T7), wherever it went. Before that, a detached Apple binary
   survived every run. What remains:
   - A run ends with a sweep of the process table, not a PID namespace. A fork
     loop faster than the sweep (3 s budget), or a process the user cannot
     kill (a setuid program the test ran), is **reported** as an unconfirmed
     cleanup, never assumed clean.
   - Between the start-time check and `kill` a pid could in principle be
     reused. That needs the pid space to wrap within microseconds (macOS has no
     pidfd). The identity is checked first, so an unrelated process is never
     selected.
   - The sweep relies on the private `sandbox_check` interface and the
     `user-preference-read` operation (checked on Darwin 25.5, arm64). If they
     stop answering, or answer otherwise (the probe run is not recognised as
     its own), the cleanup is reported as unconfirmed and only the
     environment-marker scan runs. Other macOS versions are not evaluated.
   - A surviving process stays confined by the profile: no network, and it can
     write only inside the deleted copy; it cannot signal processes outside
     the sandbox.
   - bwrap (PID namespace, `--die-with-parent`) and containers do not have
     this gap.
   - Host backends set no process-count limit (T9).
3. **Read-only dependency directories are readable.** `node_modules` and the
   project's virtualenv are what the tests need. A secret kept *inside* them
   would be readable, but never writable.
4. **Tracked secrets are copied.** A key committed to the repository is part
   of the project (test fixtures often are) and is already in git history.
5. **Evidence is a local file, not a signature.** An agent with write access
   to `.repo-ai/state/evidence/` could forge a passing record and satisfy the
   gate. The gate is an advisory nudge, not an enforcement boundary.
6. **The tests decide what they test.** A test suite that passes vacuously
   gives vacuous evidence. `verify` never reports a change as safe, and the
   full-suite command is always shown.
7. **Order-dependence is detected, not explained.** A failure that happens
   only next to other files in one process (and passes alone at the change
   and at the base) is reported as such, not as a regression. The first
   process's shape (which files ran together) is what produced it.
8. **A failure already present at the base can hide the change's effect on
   that test.**
   - When the same test fails at the base and with the change in the same
     way, `verify` cannot tell whether the change also affected it.
   - When the failure message differs, the run is not called pre-existing.
     Its verdict is `failing (tests that fail at the base now fail
     differently)`.
   - When the change edits a dependency-declaring file, a failure that also
     fails at the base is "not comparable". The base runs with the
     dependencies installed now, so both runs can share the regression's
     cause.
9. **The environment key sees installed files by their metadata, not their bytes.**
   It covers the interpreter or Node binary, and every entry in the
   site-packages directories and the read-only `node_modules`: path, type,
   size, modification and change time (since 2026-10-25; before, only the
   top-level names, so a file edited by hand in place kept the key: X13).
   What remains:
   - the change time can only be set by the kernel, so an in-place edit
     always changes the key, even with the modification time restored; but
     code reached *outside* those directories (an editable install's source
     tree, a `.pth` line pointing elsewhere, the interpreter's standard
     library) is not covered;
   - `__pycache__` anywhere and `.cache` / `.vite` at the top of a dependency
     directory are left out (the runs write them);
   - a directory of more than 400,000 entries is not identified: its key never
     matches, so nothing is reused (a cost, not a wrong result), and a pass
     recorded with it is always stale for `repo-ai evidence` and the gate (T25).
   `--rerun` runs again regardless. The same identity, recorded with each run
   (`environment_static`), is what `repo-ai evidence` and the gate compare
   since 2026-10-25 (X13b, T25); before, they compared only the fingerprint.
   The RC1 correction also compares the repo-ai version and current interpreter
   selection (PATH, active virtualenv and project virtualenv), without running
   that interpreter. Missing version or environment identity is stale. Container
   image identity remains unchecked by these read-only freshness commands.
10. **Windows has no host sandbox.** `--run` needs Docker or Podman there.
   Without them nothing runs (`SandboxUnavailable`).
