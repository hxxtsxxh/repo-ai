# Changelog

## Unreleased

- Security: the probe sandbox of `agents doctor`, `agents conformance` and the Claude preflight let a probed
  program reach the host's unix sockets on Linux (D-Bus and the systemd user manager, X11, docker, ssh-agent;
  `--unshare-net` does not cover path-based sockets) and, on macOS, write preferences outside its scratch directory
  through cfprefsd and use the pasteboard (found by an independent security review of 0.11.3–0.11.7). Linux now hides
  `/tmp`, `/run`, `/var/tmp`, a real `/var/run`, WSLg's `/mnt/wslg`, LXD's and Incus's directories and
  `~/.ssh`, `~/.gnupg`, `~/.1password` and `~/.docker` (for `$HOME` and the account's home), and unshares IPC and
  UTS. The probed program's own file and directory (and its node runtime's) are bound back read-only, never a
  directory holding a socket, with hidden directories inside them hidden again: a single-file agent under `/tmp`, or
  one whose files all sit in its own directory, still runs; one that needs other files there (an npm package's
  `node_modules`, a virtualenv) is not run (NO_HANDSHAKE). macOS
  denies preference writes, the pasteboard and, as defence in depth, launchd job creation (launchd already refused
  `launchctl submit` from a sandboxed caller on Darwin 25.5). Still open and disclosed: reads are not restricted;
  unix sockets elsewhere on Linux (other files in your home directory, other `/var/lib` services) stay reachable.
  Live provider sandboxes are unchanged.
- Security: the macOS probe sandbox now denies Mach lookups by default (the pasteboard, the keychain through
  securityd, cfprefsd, the window server, login items, notifications, DNS), allowing only user and group lookups
  through opendirectoryd, and denies registering a Mach name. With every lookup denied, the `--version` and `--help`
  output of codex, claude, bob, agy, opencode and opencode-acp was byte-identical to the unrestricted profile's, and
  again with this profile (Darwin 25.5, measured locally). Still allowed and disclosed: signals to the user's other
  processes and IOKit reads.
- Security review of v0.11.3...v0.11.7 (C18), low findings:
  - The skill vetter read a `LICENSE`, `COPYING` or `NOTICE` file in any directory (`scripts/notice`) as
    documentation, which skipped the code rules. Now only a root one without a `#!` line is read that way, and the
    code rules (whole-program checks and the per-line code rules) apply to it as well, since a skill can run any of its
    files. The instruction and injection checks apply to every licence-named file. The plugin vetter never reads a file
    that a hook, command or installer runs as documentation. A licence file below the root is now checked as code,
    which is stricter for plugins too. The code checks read a licence file's long lines in overlapping windows
    instead of cutting them at 2,000 characters, so an unwrapped paragraph is neither cut nor flagged as an overlong
    line.
  - The check for a socket duplicated onto stdio makes one pass over the file instead of one search per socket name,
    which was quadratic on large files.
  - `verify` no longer crashes when `pyproject.toml` gives `tool`, `tool.setuptools_scm` or a `tool.hatch` table a
    non-table value (valid TOML) or nests deeply enough to stop the parser; no version file is declared then.
  - The `norecursedirs` note is skipped for a pattern over 256 characters, and a memory or overflow error while
    reading the configuration gives no note instead of an error.
  - The coding lab's `git diff` and `git ls-files` over an agent's workspace use a copy of its `.git` taken before
    the run (with no fsmonitor and no hooks). The agent could have written the workspace's own `.git/config`, and a
    clean filter defined there would have run on the host during `git diff`.
  - The diagnose, journey and speed workflows no longer keep the checkout token in `.git/config`.

## 0.11.7 — faster verify on Linux, Claude live on Linux, conventions-skill trial, Gemini removed

- A mission record now says how a live Claude run authenticated: `provider.auth_mode` (`token_env` or
  `dedicated_config`) and `provider.auth_env_vars` (the variable names found, such as `CLAUDE_CODE_OAUTH_TOKEN`;
  never a value).
- Removed: the `gemini` provider and the `gemini-cli` skill-export host. Gemini CLI was superseded by Antigravity,
  which repo-ai supports as `agy` (its `~/.gemini` state paths stay protected). `--agent gemini` and
  `--host gemini-cli` are no longer accepted, and a saved `gemini` authorization or preference is ignored (routing
  picks the next authorized provider, or none). A skill an earlier version exported to `.gemini/skills` can still be
  disabled or uninstalled byte-exactly; if that was its only host, enabling, rolling back or re-installing it
  without `--host` is refused with the command that moves it (`repo-ai skills install <name> --host <host>`) instead
  of moving it to `.claude/skills` silently; with another host as well, it keeps that host.
- Faster `verify --run` (measured on GitHub's ubuntu and macOS runners with `scripts/profile_verify.py`, a
  40-test project with its own virtualenv; medians of 7, one run per platform, runners not identical; Windows
  not measured): the two source-tree snapshots that check a run left the working tree alone built a `pathlib`
  path for every entry, virtualenv included (under the profiler, most of a comment-only run). The walk now carries
  each directory's relative prefix; what is recorded and compared is unchanged. On the ubuntu runner: comment-only
  change 0.34 → 0.23 s and behaviour change 0.55 → 0.49 s, although that run's native suite was 32% slower. The
  ratios to the native suite (comment-only 2.16× → 1.12×, behaviour 3.54× → 2.38×; macOS 2.86× → 1.71× and
  4.17× → 3.04×) shrank partly because the native time grew, so the absolute times are the fairer measure.
  Re-verifying an unchanged state did not get faster. verify is still slower than the project's own suite;
  speed-v1 has not been re-run, so its negative result stands.
  The profiling script and its workflow (`.github/workflows/profile.yml`) are included.
- Fixed: repo-ai's mission and eval-lab git commands could let git start its background maintenance after a
  commit, which then wrote `.git/objects/maintenance.lock` in a repository or workspace repo-ai was copying (a macOS
  CI failure). They now run with `maintenance.auto=false` and `gc.auto=0` (the eval lab also with
  `core.fsmonitor=false`, whose daemon socket in `.git` would break the copy too).
- Evaluation: c10-confirm-v1 (`benchmarks/c10-confirm-v1/`, preregistered; fixture and skill, tasks and hidden
  oracles, and an ambiguity review written by three separate model sessions; 48 host-mode runs with Claude Code and
  sonnet, a new empty Claude config per run): with a project-conventions skill installed by `repo-ai skills install`,
  Claude's changes passed every convention assertion; without it, about a third (0.319). Skill arm higher on 8 of 8
  tasks (one-sided exact sign test p = 0.0039), with no cost to the requested behaviour. Limits: one fixture project,
  one model, one conventions skill whose value is by construction the rules the code does not show (9 of its 14),
  and some oracle inputs reuse the skill's own worked examples, so much of the gap is built into the design; the
  control had no conventions text, so this is not a comparison with the same text in CLAUDE.md; it says nothing about
  third-party skills in general. C10 moves to PASS_WITH_LIMITS.
- Evaluation: the Claude provider ran live on Linux for the first time (a disposable Ubuntu container with
  bubblewrap, repo-ai 0.11.6 and Claude Code 2.1.316 with a `CLAUDE_CODE_OAUTH_TOKEN`): a toy journey PASS,
  `LIVE_CANDIDATE_VERIFIED`; a probe found that a Read outside the workspace was refused (recorded), and the model
  reported that its Read tool also refused `/proc/self/environ` (not recorded). n = 1;
  `docs/engineering/evidence/LINUX-CLAUDE-2026-11-01.md`.

## 0.11.6 — faster hooks and commands, a pytest collection note, speed-v1 replicated

- verify names the test files that the project's pytest `norecursedirs` keeps out of a full run when it matches
  tests by name: a targeted run passes them to pytest, which runs them anyway, while a full run does not reach them,
  so the two can disagree on one change (speed-v1: marshmallow's `tests/mypy_test_cases`). Read from the file pytest
  would use; no note when the command picks its own configuration or the file cannot be read. A note in the plan
  only: nothing is removed on this reading, and `repo-ai verify --record` still learns pytest's own collection.
- Docs: the shipped capability catalog cited three research files that are not in the public repository (as
  evidence and review references in `capabilities show --json`, and in the catalog's note); each now says it is
  in the private development history. User-facing strings (two catalog entries, ProofLab's node-scenario reason)
  no longer name an internal development session.
- Faster (measured on an Apple Silicon Mac, medians of 7 to 9 runs on a small pytest project; not a re-run of
  speed-v1): every repo-ai command parsed its arguments by importing the mission runtime and every provider
  adapter, about 80 ms before doing anything. They now load only in the commands that use them. Agent hooks
  take about half as long there (Claude `prompt`, `post-edit` and `stop` 147–150 ms → 67–81 ms; `session-start`
  324 → 205 ms, partly the macOS git change below) and `repo-ai --version` 145 → 49 ms. Not measured on Linux or
  Windows, where only the import saving applies.
- Faster on macOS: `/usr/bin/git` is Apple's launcher stub, which asks xcrun for the developer directory on every
  call (35 ms per git command here, against 17 ms for the program it runs). repo-ai now runs the selected
  developer directory's git directly: `DEVELOPER_DIR`, else the `xcode-select` link, else what `xcode-select -p`
  prints (asked once per process). Another git first on PATH (Homebrew's), or anything unusual, runs as before.
  `verify --run` on that project: comment-only change 965 → 636 ms, a behaviour change with the full suite
  1,370 → 992 ms, re-verifying an unchanged state 544 → 330 ms. Linux and Windows run git as before.
- Evaluation: speed-v1 run 3 (`benchmarks/speed-v1/`, a replication stated before the run as Amendment 3, GitHub
  runner, on a commit that already includes the startup change above): verify is still **not** faster than the
  native suite (2.23× geometric mean, slower on 30 of 30; run 2: 1.84×, 24 of 30). Its more-itertools changes were
  measured differently (a targeted run of 2 files where run 2's full-suite attempt ended early); without them the
  two runs agree (run 3 2.61×, run 2 2.64×). Absolute overheads are not compared (the runner CPU changed), and the
  ~80 ms startup saving cannot be seen in these data. Exit codes agreed with the native suite on 23 of 30 changes
  (run 2: 16): the more-itertools (full suite seen passing once) and humanize disagreements are gone, consistent
  with fixes in 0.11.4/0.11.5 but not isolated by the runs; pyjwt's failing tests (consistent with the sandbox
  denying the network) and one name-matched marshmallow change still disagree. Run 2 stays the result.
  marshmallow 2fc8207d's two verdicts (targeted exit 1, full exit 0) are inferred to come from files pytest's
  `norecursedirs` skips, which only a targeted run names (see the first item); why the strategy differed between
  the two runs is not recorded.
- Site: a weekly probe of the deployed site from a GitHub runner (every sitemap URL over HTTPS, no third-party
  URLs in its HTML or stylesheets, the published version the site renders) and Lighthouse on six pages; the first runs scored 100 on accessibility,
  best practices and SEO everywhere, and 95–100 on performance.

## 0.11.5 — agents doctor sandbox fix, ACP conformance kit, real-project journeys

Includes everything listed under 0.11.4 (see CHANGELOG.md), which was qualified but never published to PyPI.

- Fixed (found by journey-offline-v2 on more-itertools): `from unittest import TestCase` (or
  `IsolatedAsyncioTestCase`) now marks a unittest suite, so verify runs it by discovery. `from unittest import mock`
  alone does not: pytest projects stay under pytest.
- Evaluation: journey-offline-v2 (`benchmarks/journey-offline-v2/`, preregistered, CI runner): on 7 real upstream
  fixes whose tests fail without them, verify never reported a pass for the broken state (0 of 7). It confirmed the
  fix in 3 of 6 (selected tests passed; full suite not run). The rest: tests that also failed at the base (likely
  network) and more-itertools, whose unittest suite repo-ai did not recognise (fixed above). Uninstall left no tracked
  or untracked difference in 7 of 7 (ignored files and state outside the repository not checked). journey-offline-v1
  was inconclusive and is kept, with its cause.
- Evaluation: capability-fresh-v1 (`benchmarks/capability-fresh-v1/`, preregistered, 60 tasks by one independent model
  author): the capability recommender **failed** again: top-3 recall 0.69 (gate 0.80) and 2 recommendations a stated
  constraint ruled out. Together with Corpus C this makes the deterministic matcher a negative result (the Skill Radar
  gate, C07, stays experimental: online discovery, caching and pinning are unvalidated, not shown false); `--deny`
  remains the enforced way to rule capabilities out.
- Tests: provider routing is checked over every provider, alone, under macOS and Linux platform names (34,944
  decisions), including the UNKNOWN and RUNTIME_UNSUPPORTED labels and argument-over-policy preference; a 1-in-256
  flake in a large-binary test is gone.
- Docs: 24 links pointed at research files that are not in the public repository; they now say where the files are,
  and a test keeps relative links in the docs resolvable.
- Security (disclosed, measured): on macOS the OpenCode providers' "loopback only" network reaches no other host, but
  seatbelt's `localhost` rule also admits the machine's own network addresses, and its inbound rule lets the agent
  listen on every interface. Seatbelt cannot name 127.0.0.1 alone. The security and providers pages say so;
  `benchmarks/seatbelt-loopback/` holds the probe and results. Earlier "loopback-only" wording (0.10.0, 0.11.3) is
  qualified by this.
- Added: `repo-ai agents conformance --acp-executable PATH [--acp-arg ARG]`, a conformance kit for Agent Client
  Protocol agents repo-ai has no adapter for. It runs only the `initialize` handshake (no session, no model call) in
  the network-denied probe sandbox, refuses repository-owned executables, sweeps every process the agent started, and
  reports the protocol version, the agent's name and version and what it advertises (terminal escapes stripped) or,
  when it fails, what it printed. A conformant agent is still `PLANNED` for execution. Gemini CLI 0.65.0 conforms;
  OpenCode 2.2.1 needs network to start its ACP mode and does not.
- Security: the probe sandbox of `agents doctor` (and the kit) did not deny LaunchServices `open` or Apple events on
  macOS, so a probed program could start an application outside the sandbox, with network access (found by an
  independent review of the kit, with a harmless probe). It now does; on Linux the probe also gets its own process
  namespace, so nothing it starts outlives it.

## 0.11.4 — SAFE_AUTO hardened after a failed unseen-corpus test; verify fixes from real projects

Not published to PyPI (no tag was pushed); these changes ship in 0.11.5.

- Added: when tests fail at the base and the change alike and their output shows a network denial (name
  resolution, unreachable network, failed connection), verify says some failures in those files look like its
  sandbox's missing network, which the project's own run may not have (pyjwt's JWKS client tests). JSON:
  `summary.sandbox_network_suspected`. No verdict changes.
- Evaluation: speed-v1 (`benchmarks/speed-v1/`, preregistered, run on a CI runner): on 30 real upstream commits in 5
  pure-Python projects, `verify --run` took 1.84× the native suite and was slower on 24 of 30. A negative result,
  recorded as such on the site; on small, fast suites verify's value is its classification, not time.
- Fixed (found by speed-v1 on real projects): in a project that writes its version file at build time
  (setuptools-scm `version_file`/`write_to`, hatch-vcs `version-file`), that git-ignored file was missing from
  verify's disposable copy, so every test failed with `No module named '<pkg>._version'` at base and change alike
  (python-humanize). The declared version file is now copied in; nothing else ignored is, and the declaration
  must name a small `.py` file called like a version file inside the repository.
- Fixed (found by speed-v1): verify ran more-itertools' `make check` (black, flake8, stubtest: no tests) as the test
  suite and reported a passing suite `full-suite-failed`. `python -m unittest -v` (options only) is discovery, a
  trailing lowercase make parameter that the Makefile leaves undefined (`${tests}`) is empty as make treats it, and
  a make target whose every step is a lint tool is never the suite. Also: `${v}` make variables are expanded,
  `python -m unittest -v discover …` is opaque (unittest discovers only when `discover` comes first), a `-k` value
  is never taken for a module or start directory, and the workspace summary lists `generated_version_files`.
- Security (opt-in `SAFE_AUTO`): a preregistered evaluation with an unseen corpus (`benchmarks/skill-vet-fresh-v1`,
  80 defanged cases) **failed** its main gate. `SAFE_AUTO` would have installed 8 of 30 harmful skills without
  asking. All 8 were prose-only SKILL.md files: overriding the agent's instructions, hiding results from the user,
  bypassing approvals, weakening tests or CI, writing into agent configuration, destructive requests and taking
  over commit identity. The firewall now reads each prose paragraph for these seven classes. A match is a `high`
  finding (`instruction-risk/…`), so the verdict is `review` and the skill is no longer inert: `SAFE_AUTO` asks.
  No negation clears a match, so a prohibition about these subjects asks too: an independent review showed "never
  mind the old notes, delete everything …" passing otherwise. Text is normalised (full-width letters, HTML
  entities), licence and notice files are read too, and any non-ASCII letter keeps a skill from being inert
  (homoglyphs). Not yet confirmed: the confirming corpus (v2) could not be produced here, so this is a hardening,
  not a validated detector; phrase checks can be paraphrased around.
- Security: the firewall rated 6 of 10 harmful script-bearing skills `eligible` in the same evaluation, including a
  reverse shell with no finding at all. Code (scripts and fenced blocks) is now read for a socket handed to a shell,
  credential stores named by path pieces, `rm -rf` with other flags first or a quoted `"$HOME"/*`, and, across a
  whole program, a secret read plus a network send or a download made executable; also a bind shell's accepted
  socket. `rm … --no-preserve-root` in code is `critical` (blocked), and a code line over 2,000 characters is a
  `high` finding (`review`) because only its first 2,000 are read for behaviour. They were never auto-installed
  (scripts already need approval); a reviewer now sees `review` or `blocked` instead of `eligible`.
- Tests: tests that write attack-like fixtures (reverse and bind shells, recursive deletes, credential uploads) or
  make deliberately denied escape attempts are now an explicit class (`tests/conftest.py`
  `SECURITY_FIXTURE_MODULES`). Every CI job runs them; on a developer machine they are skipped unless
  `REPO_AI_SECURITY_FIXTURES=1`, because endpoint protection cannot tell a fixture from a payload. Nothing in the
  suite executes a fixture. See CONTRIBUTING.md.
- Plugins in the same evaluation: harmful 6 `blocked` and 4 `review` (never `eligible`); benign 10 `review` and 0
  `blocked` (the earlier fresh validation blocked 12 of 42 benign cases).

## 0.11.3 — a Codex credential broker, ACP agents, honest mission evidence

- Security (opt-in, macOS): a credential broker for Codex (`REPO_AI_CODEX_BROKER=1`). Without it, the Codex login's
  token is copied into the run's scratch `CODEX_HOME`, where the model (which has a shell and the network) can read it
  (disclosed). With it, nothing secret is copied in:
  - Codex gets a per-run dummy key and a model provider whose `base_url` is a loopback proxy in repo-ai. The proxy
    checks the key, swaps in the login's credential and forwards `POST /v1/responses` upstream.
  - Codex's sandbox can reach only that port (and unix sockets in the run's scratch directory) and cannot read the
    login's directory.
  - Each request is vetted, so that the upstream cannot be made to reach another host for the model: only local tool
    types, hosted web search removed, no remote image or file URLs, no stored prompt, conversation or response and no
    background run, no duplicate keys,
    and the model pinned to the first request's.
  - It went through three independent security-review rounds. Two live runs with a ChatGPT login (Codex 0.165, on a
    development build) went through it; the second recorded 3 requests, all HTTP 200, none refused, and no
    credential in the record (the first predates the recorded broker summary). An API-key login is not yet
    live-verified.
- Added: `repo-ai do --agent opencode-acp` (below) keeps the ACP agent's stderr for diagnostics. The first 64 KiB are
  kept, every byte is counted and hashed, and a flood can neither block the agent nor grow memory. The result carries
  `stderr_bytes`, `stderr_sha256` and a redacted `diagnostic_summary`, like every other provider. A rate-limit
  message there is a failure reason, and a failed handshake says what the agent printed.
- Fixed: a repository that tracks a FILE named `.repo-ai` failed `init`, missions and sandboxed runs with a bare
  `[Errno 20] Not a directory`. repo-ai now names the file. `out_dir` in `repo-ai.toml` moves the index and context,
  but sandboxed runs and missions still need a `.repo-ai/` directory and stay unavailable in such a repository.
- Fixed: with a custom `out_dir` and `init --agent none`, no ignore entries were written. repo-ai's own index, lock
  and evidence counted as part of the change, and the first `verify --run` always failed with "the working tree
  changed while the run was being prepared".
- Changed: a live tournament refuses two providers that run the same executable (`opencode` and `opencode-acp` both
  run OpenCode with its one configured model). They are not independent candidates.
- Added: `repo-ai do --agent opencode-acp` runs OpenCode over the Agent Client Protocol (`opencode acp`) instead of
  `opencode run`, under exactly the `opencode` isolation: same OS sandbox with loopback-only network, scratch HOME,
  deny-by-default inline config and local model. The ACP client stays outside the sandbox; any protocol problem,
  refused request, timeout or stop reason other than `end_turn` fails the run, and the edit OpenCode makes itself is
  still checked in the workspace and by the tests. It appears in `agents list/doctor/route/catalog` and `agents setup
  opencode-acp`, which also runs an `initialize`-only ACP handshake (no model call). A live $0 run with a local
  `qwen3:8b` reached PASS on a scratch fixture.
- Added: an Agent Client Protocol (ACP 1) client (`repo_ai.providers.acp`). It applies one permission policy to every
  ACP agent: reads only inside the workspace, writes only to allowed paths, no terminals, permission requests allowed
  once only for read/search/edit/think tool calls, never allow-always. A handshake-only probe gives accurate capability
  detection without a model call; OpenCode 2.2.1 and Gemini CLI 0.65.0 both answer ACP 1. A live $0 run of OpenCode
  with a local model completed over ACP. `opencode-acp` (above) is the first ACP provider for `repo-ai do`.
- Added: `repo-ai verify --run --show-fixed` names the tests a change fixed. A fix is a claim about one test, so
  each candidate is confirmed in isolation: it must fail alone at the base and pass alone at the change, existing,
  running and not skipped there. Candidates are the base full suite's failures in selected files that pass now; that
  suite runs once and is cached. A deleted, newly skipped or order-dependent test is never named, nor is any test when
  the change edits dependency files. Up to 20 candidates are checked, at two processes each. On python-humanize it
  names `tests/test_number.py::test_intword_rounding_rollover`, the upstream regression test.
- Faster: on macOS (APFS), a parallel test process's disposable workspace is one copy-on-write clone of the whole
  tree, pruned to exactly the listed files, instead of one clone per file. On repo-ai's own 2,742-file tree that is
  about 0.07 s against 0.310 s per process. Content, links, modes and the ownership marker are unchanged, nothing unlisted
  is carried over (not even an empty directory), and other filesystems still copy file by file.
- Security: a hostile repository could put a file at a repo-ai state path in a mission workspace on a case-insensitive
  filesystem (macOS). A tracked link `A -> .claude` and a file `a/settings.local.json` wrote
  `.claude/settings.local.json`, because the archive filter compared names as text. It stayed inside the workspace.
  Whatever exists at a state path after a workspace is built is now removed, however it got there.
- Changed: in a scoped mission (`--expect-fix`), a test that errors at **setup** (its body never runs) in the same way
  at the base and on the candidate may stand, like a failure that was already there. An error in teardown or the body
  still makes the observation incomplete, because it hides the test's own result. It is listed with them, and the standing is
  `PASS_WITH_PRE_EXISTING_FAILURES`. Found on python-humanize, where a pytest-benchmark plugin broken under pytest 9
  errored 15 unrelated benchmark tests and the mission could not verify at all. A new error on the candidate is a
  regression; a declared test must fail at the base by an assertion, not an error; and an unscoped mission still
  refuses any setup error.
- Fixed: mission workspaces left out tracked files marked `export-ignore` in `.gitattributes` (often a whole `tests/`)
  and rewrote `$Format:…$` in files marked `export-subst`, because they are built with `git archive`. On such a
  repository every provider mission was blocked, or verified the wrong tests. Those files are now written from their
  committed blobs, with the line endings a checkout gives them and their executable bit.
- Fixed: `repo-ai apply` always printed "0 failed" after post-apply verification; the count was hard-coded. A scoped
  mission (`--expect-fix`) legitimately keeps failures that were already there at the base and are not declared. It now
  prints the real count and says when every remaining failure is one of those ("131 tests ran, 20 failed (all 20
  already failing at the base and not declared)"). JSON: `post_apply_failed` is real; `post_apply_pre_existing` is
  new.

## 0.11.2 — missions on real repositories: the project's interpreter, init's .gitignore, honest counts

- Fixed (found on python-humanize): `repo-ai verify --run --full` printed "0 passed" when no test file was selected,
  although the full suite ran 738 passing tests. The summary now says "N selected test file(s) passed" and, for
  pytest, quotes pytest's own final line ("full suite, as pytest printed it: 1 failed, 738 passed, 112 skipped"), only when it agrees with repo-ai's per-test report (test code could print a look-alike); counts
  are never derived, so other runners show none. The JSON `passed` field keeps its meaning (selected files);
  `full_suite_counts` is new.
- Changed: `repo-ai skills recommend` / `explain` count a local skill (`discover --from-path`) as relevant when its
  description names one of this repository's own Python packages (common names such as `app` or `data` excluded).
  Before, a skill written for the repository's own conventions was advised against ("matches no evidence-backed
  capability gap"); found in the C10 skill-value pilot (`docs/engineering/evidence/SKILL-VALUE-PILOT-2026-10-30.md`).
  This is advice only: a network skill that names the package gets no credit, and `skills autopilot` never
  auto-installs a skill on this ground; it does so only for a skill that fills a gap or that you name.
- Fixed (found on a real repository, python-humanize, with 0.11.1): `repo-ai init` adds its managed block to
  `.gitignore` (or creates the file), and `repo-ai do` then refused the "dirty checkout". A `.gitignore` whose only
  change is repo-ai's managed block no longer makes the checkout dirty, and a provider's candidate is compared with the
  committed file, so the block is not read as a provider edit. Any other change to the file still blocks the mission.
- Fixed (found on a real repository, python-humanize): mission tests ran with the first `python3` on PATH instead of
  the project's virtualenv. The interpreter was resolved from the disposable workspace, which never holds `.venv`.
  Missions now resolve the interpreter from the checkout, like
  `repo-ai verify`. A project installed in editable mode imports the candidate's copy, not the checkout's.
  (Corrected: as released, this entry also said the fix explained a python-slugify discrepancy, 20 failures in the
  sandbox and 0 after apply. It did not: that "0" was a hard-coded count in `repo-ai apply`, fixed after 0.11.2.)
- Fixed (same repository): a tracked file that a `.gitignore` pattern also matches (python-humanize's `_version.py`
  stub) was dropped from mission workspaces, so every test failed to import the package.

## 0.11.1 — `init` then `do` works on the first try

- Fixed (found on a real repository): `repo-ai init` followed by `repo-ai do` failed either way. Uncommitted
  `.repo-ai/` files made the checkout "dirty", and once committed (as the message advised) a live provider's candidate
  was refused because repo-ai's own `.repo-ai/config.toml` was compared as if the provider had deleted it. repo-ai's
  own directory is no longer mission source, never makes a checkout dirty, and is never materialized into a candidate
  workspace (not even as an empty directory). The same applies to the other local-state paths repo-ai already kept out
  of candidate workspaces (`.bob/`, `.claude/settings.local.json`): tracked copies no longer count as mission source.

## 0.11.0 — missions on real suites; requirement erasure

- Added: `repo-ai do --expect-fix TEST` (repeatable) for real suites with failures the task does not touch. The
  declared tests must fail at the base and pass on the candidate, and no test that passed at the base may fail; tests
  that already failed at the base and are not declared may keep failing. The result is `PASS_WITH_PRE_EXISTING_FAILURES`
  (claim `ASSURANCE_PARTIAL`, remaining failures listed), never a plain whole-suite PASS; `apply` re-verifies with the
  same scope. Without the flag nothing changes. Observed on `un33k/python-slugify`: the same candidate that an unscoped
  mission had to refuse (20 unrelated failures in this environment) verifies with three declared tests.
- Added: **requirement erasure** — when a candidate deletes documentation that states a requirement (a docstring or
  comment line with words such as "raise", "must", "never", "reject"), the mission names it and a clean PASS drops to
  `ASSURANCE_PARTIAL`. Observed live on 0.10.0: a local model removed "Raise ValueError if lo > hi" together with the
  behaviour, and the visible tests passed (`docs/engineering/evidence/JOURNEYS-0.10.0-PYPI.md`). Python lines are placed
  with the parser on the base file; JS/TS use a diff heuristic. It never changes a verdict.

## 0.10.0 — Claude Code and OpenCode as isolated providers; safe skill autopilot

- **Claude Code runs as an isolated `repo-ai do` provider** (it was blocked in 0.9.0). It authenticates with its own
  supported login and nothing is copied: `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` (scratch HOME, no keychain),
  or a dedicated repo-ai login (`CLAUDE_CONFIG_DIR=<dir> claude auth login`; HOME read-restricted). The model gets
  file tools only (`--restricted --safe-mode --strict-mcp-config`), and every live run first starts the exact
  invocation with a model name Claude Code rejects locally to confirm, at no cost, that no other tool, MCP server,
  plugin or skill would load (an account syncs those into every login). `repo-ai agents setup claude` explains the
  one-time setup; a missing login is `SETUP_REQUIRED` in `agents route`.
- **OpenCode with a local model** (new provider, account-free): loopback-only endpoints, deny-by-default tool policy,
  `--standalone`, network restricted to loopback; cloud-routed models are refused. `repo-ai agents setup opencode`.
- **Security:** no provider credential is copied into the sandbox any more (0.9.0 copied Claude credential files and
  the whole `~/.gemini`, which held OAuth tokens and another agent's history). Every process a seatbelt provider run
  starts is killed before verification, including ones that call `setsid`; `open`/Apple events are denied. An
  independent adversarial review found and this release fixes: read rules that could expose all of HOME, a
  config-dir override that made HOME writable, reachable unix sockets (container engine, ssh-agent) and DNS.
  (Corrected: as released, this entry said no provider credential is copied any more. That holds for Claude and
  Gemini. Codex's `auth.json` was still copied into its scratch `CODEX_HOME`, readable by its model (disclosed; the
  opt-in broker of 0.11.3 removes it), Bob's `~/.bob/settings` directory is copied, and a provider credential set in
  the environment (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `GOOGLE_API_KEY`, `BOB_API_KEY`) is passed into that provider's run.)
- **Skills — safe autopilot:** autonomy levels (`skills policy`; default PROPOSE, stored machine-locally), five
  capability kinds kept apart (only skills are installable), a strict inert check, `CapabilityBundle` installs
  with ownership markers, conflict refusal and byte-exact uninstall/rollback; OpenCode is an install target
  (`.agents/skills`). A repo-ai-installed skill was observed loading on Claude Code and OpenCode. An independent
  review's 10 findings are fixed (e.g. a committed lockfile could make uninstall delete a user file).
- Missions accept a test skipped identically at base and candidate (real suites have platform and
  optional-dependency skips); a candidate that makes a test skip, or un-skips one, never passes; a module skipped at
  collection is now reported instead of silently vanishing; `futures --rehearse` no longer counts a new skip as a pass.
- Codex live runs are HOME read-restricted like Claude and OpenCode (a model with a shell could read
  `~/.codex/auth.json` and other HOME files) and reach only DNS/scratch unix sockets.
- Gemini live runs need `GEMINI_API_KEY`/`GOOGLE_API_KEY`; exit 41 is reported as an authentication failure.
- Added: `repo-ai agents catalog` — 24 coding agents with what repo-ai can honestly do with each (EXECUTION, BLOCKED,
  PLANNED from vendor docs, UNSUPPORTED); detection is a PATH lookup that never runs anything.
- Codex: prefers a dedicated repo-ai login (`CODEX_HOME=<dir> codex login`; `repo-ai agents setup codex` explains
  why) and receives only model-selection keys of the user's config (no MCP servers, `notify` or trust lists).
- Fixed (found on a real repository): a tracked file over 2 MB made every mission fail with an opaque error, and
  the same limit let a provider's change to such a file pass the scope check unseen. Files up to 25 MB are read and
  compared; an unreadable side never compares equal.
- Fixed: the tree-sitter install hint named `repo-ai[ast]`; it is `repo-ai-cli[ast]`. `why-test-failed` shows
  pytest identities once. A dirty-checkout refusal names the paths.
- Evidence: `docs/engineering/` (mission ledger, INTEGRATIONS.md, evidence/). Comparative lift over a standalone
  agent remains `NOT_YET_DEMONSTRATED`; skill benefit is not demonstrated.

## 0.9.0 — first stable (beta) release

The first release intended for public installation (`pip install repo-ai`). "Stable" here means a final,
non-pre-release version with a documented support matrix; the CLI is still pre-1.0 and many commands are
experimental, as `docs/STATUS.md` states. Comparative lift over a standalone coding agent remains
`NOT_YET_DEMONSTRATED`.

- **Distribution name:** the PyPI distribution is `repo-ai-cli`. PyPI refuses `repo-ai` because it normalizes to
  the same name as the unrelated project `repoai`. The command (`repo-ai`) and the import package (`repo_ai`) are
  unchanged. **Migration:** pre-release wheels were the distribution `repo-ai`; uninstall it (`pipx uninstall repo-ai`)
  before installing `repo-ai-cli`, since both own the same files. Repository data under `.repo-ai/` is unaffected.
- Fixed: first-run `verify` on a project whose tests are plain top-level `def test_*()` functions with no
  `import pytest` and no config: the framework was `unknown`, so no runner, "0 linked test files" and
  `verify --run` exit 1. Such files are now pytest style (a weak vote; an explicit framework import or a declared
  dependency still decides). Found by a clean-container first-run journey.
- Fixed: a handoff continuation silently ignored `--allow-write`. Paths passed on the continuation command now
  widen the inherited scope by the user's authority (never the capsule's), pass the same plan checks (frozen
  tests stay refused) and are recorded as `continued_from.write_paths_added_by_user`. Found by the first live
  Codex -> agy handoff.
- Added: `shortlist` reports candidates whose Python code is identical (same syntax trees in every changed file,
  ignoring comments and formatting) as `same_code`, so a tie between them is known not to matter. Found by the
  first live Codex + agy tournament, whose two passing diffs differed only by a comment.
- Fixed: `coverage` text output printed pytest identities twice (`f.py::f.py::test_x`); JSON is unchanged.
- Changed: a plan blocked by a dirty checkout names the changed paths and says to commit or stash them.
- Added: `docs/CLI-REFERENCE.md` generated from the parser (`scripts/gen_cli_reference.py`, checked in CI);
  help text for `-v`, `-q`, `--json` and other previously blank arguments.
- Added: release workflow (`.github/workflows/release.yml`): stable tags only, sdist->wheel byte identity, SBOM,
  `SHA256SUMS`, three-OS clean-venv smoke, build-provenance attestation, PyPI Trusted Publishing.
- Added: the documentation and landing site under `site/` (Astro + Starlight), CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, SUPPORT, issue and PR templates; the README was rewritten (the previous one is `docs/GUIDE.md`).
- Changed: package metadata is provider-neutral (description, keywords, classifiers incl. Python 3.14, project URLs).
- Security: end-to-end regression test for #56 (read-only `prove` commands never execute a repository
  interpreter on the host; fixed earlier by the static interpreter resolution).
- Evidence (n=1 each, synthetic tasks, installed wheel): live Codex mission with coverage/apply/undo; live
  Codex + agy tournament that abstained, then `shortlist`; live Codex -> agy handoff that carried verified partial
  work and passed an author-written hidden oracle (`docs/launch/evidence/LIVE-JOURNEYS-2026-10-29.md`).

## 0.9.0.dev4 — pre-release candidate (after 0.9.0.dev3)

- Added: `repo-ai coverage MISSION_ID --requirements FILE [--json]`: checks a developer-declared requirement->test map (strict `repo-ai.requirements/1` schema) against the mission's observed per-test baseline/candidate outcomes. Per-requirement statuses `VERIFIED_FAIL_TO_PASS`, `VERIFIED_PRESERVED`, `NOT_DISCRIMINATING`, `FAILING`, `MISSING_TEST`, `UNMAPPED`; headlines `ACCEPTANCE_MAPPED_ALL`, `ACCEPTANCE_PARTIAL`, `ACCEPTANCE_UNMAPPED`, `STALE`, `INCONCLUSIVE`. `task_correct` is always `CLAIM_UNVERIFIED`. Exit 0 only for `ACCEPTANCE_MAPPED_ALL`. Real `node-slug` reproduction: decoy and reference look identical until the cross-list-uniqueness requirement is mapped to a test, then the decoy fails and the reference verifies.
- Added: `benchmarks/abc-v4`, a preregistered pilot (`py-semver`, `node-duration`) with free controls (untouched FAIL, reference CORRECT, decoy FALSE_GREEN) and a pilot rule (arms B/C are NOT_RUN on any task where the bare provider is already CORRECT). Live result: Codex arm A CORRECT on both tasks, so B/C NOT_RUN; a fourth study at the ceiling. Comparative lift remains `NOT_YET_DEMONSTRATED`.
- Fixed: `privacy audit` no longer crashes with `FileNotFoundError` when another process deletes a file between its directory walk and the size read (found when the installed journeys ran beside the test suite, whose lab tests create and remove canary directories); vanished files are simply not counted.
- Changed: `shortlist` output points to `coverage` and restates that PASS is not task correctness.
- Not claimed: any lift over a plain provider (`NOT_YET_DEMONSTRATED`).

## 0.9.0.dev3 — pre-release candidate (after 0.9.0.dev2)

- Added: `repo-ai shortlist COMPARISON_ID [--policy strict|smallest-diff] [--json]` for tournaments that abstain because several distinct candidates passed. Prints an evidence table (files, +/- lines, cost status, claim headline, files only one candidate touches). `strict` (default) preserves abstention; `smallest-diff` adds an opt-in, clearly labelled `POLICY_PREFERENCE` (a tie rule, not correctness). It never applies anything, declines when the comparison is uncontrolled or stale, and ties yield no preference.
- Added: claims now name scope/quantifier words a requirement uses but the tests never do (`unechoed_qualifiers`, e.g. `whole` for the `node-slug` false green). Heuristic prompt only: it trips on many ordinary tasks, cannot upgrade a verdict and does not discriminate on its own.
- Added: `status_class` (`NOT_INSTALLED`, `NOT_AUTHORIZED`, `BLOCKED_AUTH`, `BLOCKED_QUOTA`, `BLOCKED_SANDBOX`, `UNSUPPORTED`, `ISOLATED_READY`) and `observation_stale` / `auth_observed` in `agents route`; `readiness` is unchanged. There is no `HOST_READY`: repo-ai has no un-isolated execution path.
- Fixed: README no longer calls the tournament replay-only (`--candidate` is; `--tournament` is live). Tournament text output shows each candidate's claim headline and states that PASS is not task correctness.
- Not claimed: any lift over a plain provider (`NOT_YET_DEMONSTRATED`).

## 0.9.0.dev2 — GitHub pre-release `v0.9.0-dev2` (not on PyPI)

- Added: claim taxonomy in mission `status`/`explain`/`why` (`claims`): separates "frozen tests observed a pass" from "task correct"; additive, never changes a verdict.
- Added: live multi-provider tournament `repo-ai do TASK --tournament A,B[,C] --allow-write PATH [--run --allow-live-provider]` (plan-only by default). One distinct passing candidate wins; byte-identical passes are equivalent; several distinct passes, a crash, a no-op or a baseline mismatch abstain.
- Added: provider readiness states (`NOT_INSTALLED`, `INSTALLED_UNPROBED`, `USAGE_LIMITED`, `ISOLATION_BLOCKED`, `READY`, ...) in `agents route`; observations come only from real runs, are bound to the binary hash and expire. No billable probe in `--dry-run`, `agents list`, `doctor` or `route`.
- Added: handoff attack tests (cross-store, source drift, corrupted, symlinked, traversal capsules).
- Added: `benchmarks/abc-v3` preregistration (4 new tasks, calibration/holdout, arms A/B/C), `benchmarks/tournament-demo`, `benchmarks/handoff-demo-2` (Codex -> agy, n=1).
- Docs: README/STATUS/ARCHITECTURE refreshed; `docs/SECURITY.md` documents the Codex inner-sandbox bypass and agy keychain-file read.
- Not claimed: any lift over a plain provider (`NOT_YET_DEMONSTRATED`).

## 0.9.0.dev1 — GitHub pre-release `v0.9.0-dev1` (not on PyPI)

- Added: Antigravity `agy` adapter (macOS seatbelt only; live runs refused elsewhere).
- Added: capability-based provider routing `repo-ai agents route|authorize|revoke`; `--agent auto` yields `NO_AGENT` / `NOT_AUTHORIZED` instead of defaulting to Bob; quota observations put a provider on a one-hour cooldown.
- Added: change-exercise disclosure (never alters a verdict); Codex runs under repo-ai's outer sandbox.
- Fixed: continuation after an UNKNOWN-cost provider is allowed when no USD ceiling exists.
- Evaluation: abc-v2 Codex A/B (8 cells, all CORRECT = ceiling effect). Verdict remains `NOT_YET_DEMONSTRATED`.
- Not done: live multi-candidate tournament, abc-v3, any claim of lift.

## 0.9.0.dev0 — GitHub pre-release `v0.9.0-dev0`, missions (experimental core)

- Added: `repo-ai do` offline plans; isolated candidate execution with baseline/regression observations; local delivery passports; `why`, `why-test-failed`, `compare`, `apply`/`undo` (transactional), `handoff` and `--from-handoff` partial-work continuation.
- Added: live provider execution behind `--allow-live-provider --run` with a sandboxed scratch HOME, bounded/redacted event capture and hard USD cap where the provider supports one. Works for IBM Bob; Codex, Claude and Gemini are BLOCKED/unsupported as described in the README matrix.
- Fixed: Codex JSONL stdout/stderr separation; inherited-unittest test identity; TypeScript identifiers such as `tokenizer` no longer quarantined as secrets; stricter local-store-bound handoff integrity; **candidate diffs were stripped of their final newline and could fail to re-apply when a hunk ended in a blank context line** (found by the abc-v1 study).
- Privacy: provider executable and workspace are persisted as basenames; the absolute binary locator is a 0600 sidecar; provider text is secret- and path-scrubbed. Hash-bound environment fingerprints stay local and may hold interpreter paths. **Migration:** missions recorded by earlier dev builds can contain absolute paths; delete `.repo-ai/missions/` to drop them.
- Evaluation: `benchmarks/abc-v1` (preregistered manifest, hidden grader, decoys). Verdict remains `NOT_YET_DEMONSTRATED`.
- Not claimed: cross-provider continuity, live tournaments, independent review, or any product-performance improvement.

## 0.8.0rc1 — release candidate (not released)

Release notes, supported scope and known issues: [docs/release/0.8.0rc1.md](docs/release/0.8.0rc1.md); evidence
manifest: [docs/release/RC1.md](docs/release/RC1.md). Core `verify` qualified CONDITIONAL_WITH_EXPLICIT_LIMITATIONS on `903984a`
(pytest, `node --test`); ProofLab NOT QUALIFIED (experimental, excluded).

### Release-freeze corrections

- macOS system Python resolves statically to the selected Xcode or Command Line
  Tools runtime, avoiding the Apple launcher startup failure inside the sandbox.
  Freshness remains nonexecuting and sandbox permissions remain unchanged.
- Evidence, verification status and the Stop gate reject another repo-ai version,
  missing environment identity, or a changed Python/Node interpreter selection.
  Selection is checked without executing an interpreter.
- Uninstall lists retained user exports (including `.repo-ai/proof.md`) in its
  preview and execution, while preserving their bytes.
- Corrected first-run prerequisites, full-suite pass semantics, the support
  matrix, bundled-source attribution and the release artifact manifest.

### `repo-ai prove`, ProofLab (experimental)

#### Added
- **`repo-ai prove pin | plan | run | status | report`** (`docs/PROOFLAB.md`):
  - pins a claim and its acceptance scenario by exact bytes;
  - runs those bytes at the base and at the change (twice each, plus a control copy of the base), sandboxed;
  - runs the whole suite on the base and on the base plus only the code under test (the subject-only check);
  - runs `verify --run` for regressions;
  - writes a passport (JSON, Markdown, unsigned in-toto) that embeds a `repo-ai.proof-evidence/1` record.
- **`/repo-prove`**, a manual-only Claude Code skill.
- **`benchmarks/prooflab/demo.py`**: two real upstream fixes, each with negative controls.

#### Security
- verify never executes or chooses an interpreter from a virtualenv the repository commits (#40).
### `repo-ai verify`, a change-verification engine (experimental)

#### Added
- **`repo-ai verify`** (`docs/VERIFY.md`) reports:
  - which code units a change touched (Python: function, method, class
    body, module code; comment-only edits recognised);
  - which test files can show a regression, each with the evidence linking
    it (runtime, static import chain, literal load, string reference);
  - a confidence class with explicit full-suite triggers.

  Planning is read-only.
- **`verify --record`** records which code units each test file executes,
  once per file, in the sandbox.
  - Python uses a standard-library tracer (`sys.monitoring` on 3.12+); Node
    uses V8 coverage.
  - Evidence is keyed to file content and ignored once stale.
  - When fresh, it is authoritative for tests with complete traces.
- **`verify --run [--full]`** runs the selection (and the full suite when
  required) in an OS-enforced sandbox. Failures are re-run on the base
  revision and classified as new or pre-existing.
- **`repo-ai evidence`** shows the last result and whether it still covers
  the working tree.
- **`verify --gate`** is a `Stop`-hook completion gate: silent unless the
  current change is unverified, and it blocks at most once per change and at
  most `verify_gate_max_blocks` (default 3) times per agent session.
  Passing evidence still covers a later formatting-only rewrite (same Python
  syntax tree, or the same conservative JavaScript/TypeScript tokens), so
  a formatter hook that runs after verification does not cause another block.
- **Dynamic-loading detection:** computed-name imports, entry points, plugin
  scans, `require(variable)`. It lowers confidence instead of reporting
  "low risk".
- **`benchmarks/verify-eval/`:** a frozen protocol, a held-out corpus, and a
  harness with podman ground truth.
- **Docs:** `docs/RESEARCH-2026-10.md` and
  `docs/ARCHITECTURE-DECISION-0.8.md`.

#### Fixed
- **Python imports in `src/` layouts resolve.** `import pkg.mod` reaches
  `src/pkg/mod.py`; it used to be treated as an external package.
- **Python imports resolve only to Python modules.** `import markdown` had
  resolved to `docs/reference/markdown.md`, cutting every test off from the
  package in the static graph and in `impact`.
- **Host sandboxes accept extra read-only directories** (a project's
  virtualenv), never the home directory or `/`.
- **`/repo-verify` uses `repo-ai verify`.**
- **Python files that start with a UTF-8 BOM are parsed.** They used to yield
  no symbols or imports.
- **Found by the held-out evaluation and the demos.** All were fixed after
  the frozen results were recorded, and are reported as such in
  `benchmarks/verify-eval/RESULTS.md`:
  - a test that reads `.py` sources as data (a version or header check) is
    linked to source changes;
  - modules under a computed-name loader prefix
    (`import_module("pkg.providers." + name)`) are reachable, and changes
    reached only that way are reported at low confidence;
  - failures are compared per test with the base, so new failures inside a
    file that already failed are reported;
  - sandboxed runs leave no files in the working tree.

#### Pre-release audit (2026-10-23; `docs/VERIFY-AUDIT-2026-10.md`)

Four independent reviews: correctness and caching, process isolation,
benchmark methodology, and performance. Every reproduced defect below has a
regression test that fails on the commit before the fix.

**Wrong attribution:** a real regression was reported as pre-existing or as
passing in each of these cases, now fixed.
- a doctest or a `load_tests`/`FunctionTestCase` test: its "by id" base
  re-run called the function;
- a test class imported into another file (checked in the wrong module);
- a test that fails at the base, but differently: new verdict
  `failing (tests that fail at the base now fail differently)`;
- a new hang or load failure in a file with a known failing test;
- tests reordered across files: after a timeout, an unfinished file counted
  as finished;
- a change that makes every test of a file skip: new verdict
  `not verified: …`, unless the tests skip at the base too;
- a dependency upgrade: the base ran with the upgraded dependencies, so the
  result is now "not comparable";
- an aggregator test file that configures the tests it imports was skipped.

**Stale reuse, now fixed:** evidence was reused after a symbolic link was
retargeted, after an edit beyond the first 4 MB of a file, and at a different
explicit `--timeout`.

**Legacy layout:** a `--run` with state in `.bob/context` always reported
"source tree changed".

**Cancellation and host reads:**
- a signal while a main-thread process was starting left it running;
- a process holding the test's output stalled the run, and its cancellation;
- a cancelled container run left its container running;
- a test could replace its report with a FIFO, a device or a link;
- a pid could be signalled after reuse.

**Added:**
- `verify_gate_max_blocks` (a per-session cap on gate blocks);
- the gate accepts evidence after formatting-only rewrites;
- `verify --paths` (a read-only plan for part of a change);
- `same_behaviour` in `repo-ai evidence --json`;
- the integration contract (`docs/VERIFY-AGENT-CONTRACT.md`).

#### Production hardening (2026-10-22)

**Safety:**
- **Tests never run in the working tree.**
  - Every `--run`, `--record` and base re-check uses a disposable copy:
    tracked and untracked, non-ignored files as they are, never `.git` or
    ignored files.
  - Untracked credential-like files are withheld.
  - Dependency directories are read-only, and editable installs are
    redirected to the copy.
  - Before/after integrity snapshots of the whole tree make a changed tree
    fail loudly and invalidate the evidence.
  - Before this, the sandbox's writable workspace *was* the repository.
- **Every test process gets its own pristine copy.** Parallel runs used to
  share one, so tests with a fixed working-directory file (peewee's SQLite
  database) collided. They were reported as **new failures** and recorded as
  already failing.
- **Cancellation:** SIGINT, SIGTERM and SIGHUP stop every test process and
  container, delete the copies, and record nothing. Seatbelt runs also reap
  processes that detached.
- **Read-scope bug:** with no `node` on PATH, the sandbox was granted read
  access to the parent of the current directory. Now nothing runs. A command
  the sandbox cannot start is reported as an environment error, not as test
  failures.
- **Planning is read-only, git included:** verify no longer lets `git diff`
  refresh `.git/index`.
- Host interpreter probes use `-I -S`.
- Threat model: `docs/VERIFY-THREAT-MODEL.md`.

**Adoption:**
- **The test command is established without configuration** where the
  project's files make it unambiguous:
  - package-manager scripts;
  - `&&` chains whose other steps are lint or type checks;
  - coverage wrappers and thresholds;
  - Makefile recipes;
  - src layouts;
  - unittest discovery.

  The command is shown with its origin and every rule applied. On the 22
  known projects, 11 were correct before and 20 after; this is post-hoc and
  needs validation on fresh projects.
- **Per-file runs keep the suite's runner options.** Option values are no
  longer mistaken for test paths.
- `verify_test_command` in `.repo-ai/config.toml`, and `--image` for a local
  container image with the project's dependencies.
- `repo-ai init`'s own `.gitignore` block no longer makes every first plan
  require the full suite.
- The plan says whether the last evidence is current or stale.

**Cost:**
- Batched execution: selected unittest and pytest files run in at most
  `--workers` processes. A failing batch is re-run file by file.
- Dynamic-loading scans are cached per file. Toolchain discovery no longer
  starts pyenv shims or `xcode-select`.
- Wall-clock costs are measured in `benchmarks/verify-eval/E2E.md`.

**Found by the evaluation and the integrated CI, fixed afterwards:**
- **Post-hoc (after the held-out-3 result):** a changed file that no
  recorded test executed, loaded or opened is "unobserved". It keeps its
  static links and is reported at medium confidence. This was held-out-3's
  one high-confidence miss: a JS file a server reads as text.
- **A sweep race:** a new copy's cleanup could delete copies other threads
  were still creating.
- **Batch timeouts:** a batch is bounded by 3× its recorded time, never n ×
  the per-file limit.
- **macOS:** the interpreter's own (symlinked) prefix is readable in seatbelt.
  This affected GitHub's macOS toolcache Python.
- **Untracked credential-like files** are not part of the verified change, so
  they no longer force the full suite.
- **sdist root files are anchored.** `README.md` matched
  `benchmarks/audit-v0.7.7/README.md`.

**Research artifacts:** `results/raw/` (37.6 MB) is now a verified 0.99 MB
archive with per-file checksums. The originals stay in git history. Release
artifacts carry no research data, and CI checks this.

#### Adaptive execution (2026-10-22)

How `verify --run` runs a plan, not which tests it selects. Measured in
`benchmarks/verify-eval/WALLCLOCK.md`.

- **Run shape from measured times.** The project's full suite as one
  process when it is not expected to be slower than the selection (and only
  it when the change requires the full suite: nothing runs twice). Otherwise
  the selected files in balanced batches; `node --test` gets one invocation.
  `--record` times the full suite once. The shape and its reason are printed
  and stored.
- **Per-test outcome reports from inside the sandbox** (`rai_result.py` for
  unittest and pytest, `rai_reporter.mjs` for `node --test`):
  - a failing batch is attributed per file instead of re-run file by file;
  - a time-out names the hung test, keeps the files that finished and runs
    only those not started;
  - the report is untrusted data, used only when it agrees with the process.
- **One grouped base comparison, in the same shape.**
  - Full-suite failures are compared with the full suite at the base.
  - Other failures are compared test by test at the base, in a few processes.
  - Failures from multi-file processes are re-run alone at the change, so an
    order-dependent failure is not called a regression.
  - A pre-existing failure whose message changed is flagged.
- **Local caches with asymmetric trust:**
  - base outcomes per base tree and test environment: a pass after one
    observation, a failure after two that agree, flaky tests never;
  - measured times and a calibration ratio;
  - reuse of the evidence for an identical change and environment, under a
    day old (`--rerun` forces a run).
- **The report leads with the conclusion.** It reports one error shared by
  many files once and says why each failing test was selected. `--json`
  adds a `summary` object.
- **Further changes:**
  - `no-tests` status: helper modules are neither passes nor failures, and a
    run where nothing executed is never reported as passing;
  - aggregator test files (a package `__init__` that imports every test
    module) are skipped in selection runs when their record shows they add
    nothing;
  - time limits follow measured times unless `--timeout` is given;
  - `verify_gate_mode = "report"` shows the evidence status and never blocks;
  - container CLI probes are cached per command.

### Containment of known defects (from the 0.8 product review)

#### Fixed
- **Skill installs are byte-exact or refused.** Binary (non-UTF-8) files
  were decoded with replacement characters, which corrupted them. Such
  skills are now refused, and text files keep their exact bytes (CRLF, BOM).
- **No network use without `--online`:** `skills install` of a remote
  candidate and `skills updates` used to reach GitHub without it.
- **Committed trial evidence is not trusted.** `promote` and the registry
  export count a lockfile's trial claim only when the cited experiment exists
  in this machine's lab store. A pilot never promotes.
- **Recommendations read trial evidence by skill name.** It had been looked
  up by candidate id, so it never applied.
- **Learned rules:**
  - A directory is "generated, do not hand-edit" only when at least 80% of
    its files are generated. One bannered helper had marked asn1crypto's
    whole `tests/`.
  - The testing rule names the Verify line's command. A pytest config
    section had made it say `pytest` where the Verify line said `make test`.
  - A human-documented test command suppresses the rule.

### `repo-ai verify`: core-correctness fixes (#29, after the held-out-5 freeze)

Details and measurements: `docs/VERIFY-INTEGRATION-REVIEW-2026-10.md`.
- **Index crash safety.** A `repo-ai update` killed at the wrong moment could
  leave search entries missing for good (6 of 9 kill points). A killed update
  now forces one full re-analysis, and `status` reports the index as stale
  until then.
- **pytest's own collection is followed** (`testpaths`, `norecursedirs`,
  `python_files`, …) once `--record` has stored it. Without a recording, a
  note says the configuration may exclude files. Not revalidated on a
  held-out set.
- **Wrong verdicts:** an unresolvable `--base` is an error (it used to plan an
  empty change and record a pass), and staged files count in a repository
  with no base commit.
- **Sandbox and time-outs:** bounded output buffer, process groups killed
  until gone, a pid-reuse check in the guardian, containers stopped at the
  limit + 5 s.
- **Measured on development fixtures only:** one hanging-file case went from
  61.0 s to 31.2 s; the fixed per-run overhead is unchanged within noise.

### `repo-ai verify`: overhead, parallel sessions, first-run output (#28, #33, #34)
- **Lower fixed overhead (#28):** `--run` is 10–11% faster on the development
  corpus (20 interleaved rounds), with identical verdicts. Held-out-5 was not
  re-run.
- **Two sessions in one repository (#33):** rebuilds run under a lock, an
  interrupted update leaves a marker, evidence writes are atomic and
  Windows-safe, and the gate and `evidence` use the newest valid record of
  *this* change when another session wrote `latest.json`.
- **First-run output (#34):** a dirty `--record` baseline is reported
  (`uncommitted[]`, `failures_are_base`), and the MEDIUM wording, the runner
  source, the process count and the closing caveat never say more than the
  evidence.

### `repo-ai verify`: a failing node file is never reported passing after a time-out
- node writes a file's test events only when its turn comes, after every
  earlier file's, but reports the file's completion at once. When a node batch
  or full suite hit its time limit while an earlier file hung, a later file that
  had already failed counted as finished, with no failures in the report, and
  was reported as **passing**. A hang already present at the base could then
  hide the regression completely. Such a file now runs again. Found by an
  adversarial review of the watchdog; reproduced on main by a regression test.

### `repo-ai verify`: per-test progress watchdog (#35)
- A run of the change ends early once no test has started or finished for
  max(5 s, 3 × the file's measured own-process time + 2 s). The result is a
  time-out, never a pass, and the open test is named. It covers unittest and
  pytest. It is off with `--timeout`, for unmeasured files, for node and
  opaque runners, and for base and confirmation runs.
- Rechecked on two previously used held-out-5 projects in podman (not a fresh
  set): h11 `mut-04` 36.8 → 7.1 s. koa `mut-07` (node) is unchanged and misses
  its 15 s target. Verdicts were unchanged on all 28 changes.

### `repo-ai evidence`: timestamps
- Evidence `created` is ISO 8601 local time with its UTC offset. It used to be
  naive local time while record names are UTC. Display only; records are
  ordered by write time.
- `docs/VERIFY-AGENT-CONTRACT.md` named the Stop hook `repo-ai hook stop`;
  the command is `repo-ai hook claude stop`.

### `repo-ai review`: added-line attribution (#31)
- The secret scanner and the other added-line facts no longer miss or shift
  lines when a line starts with `++`, `.gitattributes` marks files `-diff`,
  colour, inter-hunk context, an external diff or textconv is configured, a
  path is unusual (tab, quote, newline, non-ASCII, `{}`, ` => `) or looks like
  a pathspec, or a line contains a Unicode line separator. A staged pure
  rename adds nothing. 31 regression tests.

### Skills: `skills inventory` and `skills vet` (#24)
- **`repo-ai skills inventory`:** an offline, read-only audit of every skill,
  command, agent, plugin component, hook and MCP server Claude Code loads in
  this repository. `--check` exits 1 on a high-severity issue.
- **`repo-ai skills vet <github-url> --online`** (or a local directory,
  offline): pins a commit, quarantines the files and inspects them as text.
  It installs and runs nothing; `install` later re-fetches the same commit and
  refuses any change.
- **Hardening from an independent security audit:**
  - `vet` counts every `SKILL.md` and vets up to `--vet-limit` (200). A skipped
    skill, a request-cap failure, a truncated tree, a renamed repository or a
    SHA off the default branch makes the result incomplete (exit 3), and
    `install` refuses;
  - licences are parsed as whole SPDX expressions; restricted and
    unrecognised licences block install and recommendation;
  - untrusted text is printed inert (control characters, ANSI escapes, bidi,
    zero-width characters, newlines);
  - `inventory` also reads plugins' default `hooks/hooks.json` and `.mcp.json`,
    walks manifest paths (escapes refused), applies the firewall to agents
    and commands, and lists front-matter hooks;
  - the quarantine root and caches are owner-only;
  - a skill vetted from a local directory inherits a regular top-level
    `LICENSE` / `COPYING`, as the online path inherits GitHub's licence field.
- **Release artifacts:** the sdist leaves out `docs/research/` (the research
  ledger, protocols, corpora and results), and CI fails if any path from it
  appears in the sdist or wheel.

### Plugin inspection (experimental, #26)
- `skills vet` and `skills inventory` inspect plugin components (hooks, hooks
  modules, MCP and LSP servers, monitors, `bin/`, settings, marketplace and
  lifecycle scripts) without running them.
- **Its fresh, preregistered validation failed:** 12 of 42 benign cases were
  blocked, and executable-resolution coverage was 0.25 (0.43 after a post-hoc
  corrective pass, still a fail). Attack detection was not freshly validated
  (`docs/research/plugin-vet-fresh-2026-10/RESULTS.md`).
- **Contained:** a plugin is never reported eligible (`review` at best), and
  evidence is counted by kind. No rule was loosened. The text output shows the
  plugin section for any detected plugin, so `review` is explained even when
  each skill is eligible on its own.

### Capabilities registry (#27, with #30's adapter fixes)
- **`repo-ai capabilities list | show | prepare | approve | run | revoke`:** a
  curated registry of 15 records with six separate lifecycle fields. repo-ai
  installs nothing and writes no Claude Code settings, hooks or MCP
  configuration (`docs/CAPABILITIES.md`).
- **`adapter.ruff-security`:** your installed ruff with 51 flake8-bandit rules
  on the changed Python files; it reports only findings on added lines. Only a
  human in a terminal can approve it. The approval binds the binary's path,
  sha256, size and version, and each run executes a private, re-hashed copy.
  Hardened after adversarial reviews, each finding pinned by a regression
  test.
- **`repo-ai capabilities evidence`:** the last ruff result, only while its
  fingerprint still matches the change. Informational, never a verdict.

### Capability discovery (experimental, #30)
- **`capabilities recommend`, and `candidates` / `select`** for agents: a
  gated menu with a digest; `select` executes nothing. `/repo-capabilities`
  now uses `candidates`, then `select`.
- **Its fresh, preregistered evaluation failed** (Corpus C): top-3 recall
  0.385 against a gate of 0.80, shortlist recall@6 0.736, top-3 precision
  0.712, and 5 constraint-forbidden recommendations in the top 3. Tuning of
  the deterministic matcher has stopped
  (`docs/research/capability-discovery-C-2026-10/RESULTS.md`).
- **`--deny` constraints** (`no-network`, `no-exec`, `static-only`,
  `no-install`, `no-third-party`) are always enforced on `recommend`,
  `candidates` and `select`, and only tighten. An unknown class is an error.
  Outputs separate `explicit` constraints from `inferred` ones (best-effort:
  9 of 18 detected on Corpus C). Added after that evaluation; covered by
  tests, not by a fresh evaluation.

### Fixed
- **`repo-ai review` added-line attribution (#31).** An added line starting
  with `++` was read as a diff header, and `.gitattributes` (`-diff`) or colour
  config could empty the hunks, so facts about added lines (such as secrets
  on added lines) could miss them. Hunks are now counted exactly; git runs with
  `--text`, literal pathspecs and NUL-separated listings, and every setting
  that could hide lines is overridden. User and system config are kept, so
  `core.autocrlf` still applies on Windows.

## 0.7.7 — a budget-limited exploratory design (no model calls)

Evaluation runner and analysis only. Everything repo-ai installs for an agent
is unchanged from 0.7.6, apart from its version string.

### Added
- **`eval coding --task-order interleave`.** Tasks run round-robin across
  their bases, in a seeded order. A budget stop still leaves a paired
  comparison spread over every project reached. The order is recorded, and a
  resume with another order is refused.
- **Outcomes beside `success`.** Per-arm rates and paired comparisons for
  `correct_no_regression` (hidden tests and the visible suite pass; success
  as `SEALED_V2.md` defines it) and `regression_free`. They are computed from
  recorded fields, so the grader is unchanged.
- **The content-match sensitivity analysis** promised in PREREGISTRATION-v2
  §8.
- **Tasks with a valid run in only one arm** are listed as "not compared".
- **`docs/EXPLORATORY-v2-pairs.md`.** A registered, not authorized,
  exploratory experiment: Core vs Plain on sealed-v2, 50 runs, $20 budget.
  Schedule SHA-256 `bb90d60e…4184`.

### Fixed
- **A live run with a missing host toolchain is refused.** It used to skip
  that task silently, leaving the schedule.
- **The dry run's example settings now show the authoring-notes denial**
  that runs apply. Runs, the preflight and the dry run share one deny list.
- **PREREGISTRATION-v2 Amendment 1** records that the runner's `success`
  covers the hidden tests only. The documented definition (with the visible
  suite) is the new derived outcome.

## 0.7.6 — fix the measured harms (no model calls)

Option A (v0.7.5) found no correctness benefit from repo-ai and one concrete
harm. This release removes the harms; it claims no performance gain.

### Fixed
- **Lint-only verification guidance** (Option A, oss-ct-002).
  - The CLAUDE.md block listed `ruff check .` and a learned "run ruff before
    finishing" rule, but no test command. The inferred unittest command never
    reached it, and TESTING.md wrongly called the package untested.
  - A verification plan now classifies commands by role (tests, static, type
    check, format, build) and records where each came from.
  - The block carries one concise **Verify** line: targeted tests, then the
    full suite; static checks complement the tests; disclose when tests
    cannot run.
  - It defers to human-written testing instructions, and reports uncertainty
    instead of inventing commands.
  - Only plain runner invocations reach agent instructions.
- **Learned lint rules are complementary.** They say they never replace the
  tests, are named only while active, and formatters never become rules.
- **"Untested" claims need evidence.** A directory counts as tested when any
  test imports or names it, not only when tests sit beside it.
- **Root-level test commands lead.** A nested fixture's `cd sub && mvn test`
  was repo-ai's own "full suite".
- **Contamination needs proof of access.**
  - Content similarity invalidated five legitimate oss-tl-001 runs in Option A.
  - Runs are now invalid only on a per-run canary or a tool call or result
    that reads or reveals protected material without a denial.
  - Denied attempts and content matches are recorded as diagnostics.
  - The pre-registered exclusions stand. An exploratory reanalysis is in
    `benchmarks/results/option-a-v0.7.5-exploratory-reanalysis.md`; its
    conclusions are unchanged.

### Changed
- **`feature_set = core | full`.**
  - New installs are `core`: no subagents, skeptic or orchestration hint.
  - `init --feature-set full` opts in, and explicit keys win.
  - Installs from before 0.7.6 keep their behaviour.
  - Switching agents off retires only unedited repo-ai agents.
  - Orchestration plans keep every step in the main session when subagents
    are off.
- **The Option A `final` split is labelled analysed.** Selecting it warns that
  it is not fresh confirmatory evidence.

### Added
- `benchmarks/sealed-v2/`, a new, harder sealed benchmark (see
  docs/SEALED_V2.md):
  - selected by a fixed rule;
  - oracles validated in the sandbox;
  - not shipped in the wheel;
  - authoring notes kept separately.
- `docs/PREREGISTRATION-v2.md`, a costed comparison on it. **Not run.**
- Regression fixtures for the v0.7.5 findings: `tests/test_verification.py`,
  plus the integrity tests in `tests/test_coding_lab.py`.

## 0.7.5 — calibration recorded; measurement and grading integrity (no model calls)

### Fixed (found in the v0.7.4 calibration)
- **Bytecode counted as edits.**
  - Running Python in a workspace leaves untracked `__pycache__/*.pyc`. The
    "unnecessary edits" metric counted these, so it penalised arms whose
    agents ran the tests (Core and Full on two calibration tasks).
  - Untracked interpreter and test-tool caches are now `execution_artifacts`.
  - Tracked files, module-level `.pyc` files and anything else still count
    as edits.
- **Grading could import planted bytecode.** Bytecode whose header matches a
  source file's mtime and size was loaded instead of the source. Hidden tests
  now run on a copy without `__pycache__`, so success always comes from the
  agent's source.
- **Resume did not pin the repo-ai build.** Experiments now record
  `repo_ai_version`, and a resume under a different build is refused.

### Added
- Per-run `bash_commands` (first 100, each up to 300 characters) and
  `test_commands`, plus a "test runs by the agent" report row.
- Fake-client modifiers `+runtests` and `+stray`, used by regression tests in
  all three arms.
- Calibration record: `benchmarks/results/coding-calibration-v0.7.4.md` and
  the raw rows, with SHA256SUMS.
- PREREGISTRATION.md Amendment 2:
  - limits from the calibration rule: C $0.75, R $0.9375, T 30, timeout
    1,800 s;
  - a proposed budget of $40, against a guaranteed-completion budget of
    $140.63;
  - the corrections above.
  - The sealed tasks, schedule hash, arms, seed, model, effort, success
    criterion and decision rules are unchanged.

## 0.7.4 — budget and interval corrections (no model calls)

### Fixed (would have affected the Option A experiment)
- **Budget formula.**
  - The pre-registration called 150 × the per-run cap a guaranteed-completion
    budget, but the gate reserves 1.25 × cap for every pending arm. Runs
    costing exactly the cap would have stopped before the last task.
  - The reservation is now one function, `coding_lab.reservation`
    (`--reserve-per-run` sets a larger one).
  - The completion budget (runs × R) and the recommended budget are derived
    from it and rounded up to the cent.
  - The dry run prints the completion budget.
- **Over-budget protection.** A run whose reported cost exceeds its
  reservation stops the experiment. A run with no reported cost, or a crash,
  is charged its full reservation.
- **Success interval for repeated tasks.**
  - Simulation (docs/STATISTICS_COVERAGE.md) showed Newcombe on fractional
    task-level counts undercovered with one run per task (85% at 10 tasks)
    and was over-conservative with repetitions (about 99%).
  - `stats.clustered_diff_ci`, a task-clustered Bonett–Price adjusted Wald
    interval, held nominal 95% and 90% coverage in all 936 simulated
    conditions.
  - `compare_clustered` uses it for every design.
  - At 25 tasks × 2 repetitions it is about 14% narrower.

### Added
- Per-run `api_calls` and `max_call_cost_usd_est`, the largest single API
  call, estimated from the stream. The reservation margin must cover it.
- `coding_lab.preregistered_limits`: the pre-registered calibration rules
  (cap, margin, turns, timeout, guaranteed and recommended budgets) as code.
  Calibration reports print them.
- The report shows turns max, timeouts, the longest run and the largest
  call per arm.
- Regression tests:
  - near-cap budgets: runs at 0, the cap, 0.99 R and R;
  - missing costs and overshoot;
  - a randomized property check that charges never exceed the budget;
  - the four interval cases: all-success, all-failure, all-discordant and
    mixed repetitions;
  - a seeded coverage check.
- The simulation scripts and results: `benchmarks/statistics/`.
- PREREGISTRATION.md Amendment 1. The sealed tasks, schedule hash, arms and
  decision rules are unchanged.

## 0.7.3 — experiment preflight (no model calls)

### Fixed (would have affected the Option A experiment)
- **Repetitions treated as independent tasks.** The analysis is now
  task-clustered: repetitions are averaged per task, with a Newcombe
  interval on task-level counts, a sign-flip permutation test and Holm
  correction across comparisons.
- **Resume.** It refuses a different protocol. Arm orders are a pure
  function of the protocol, where before a resumed run reshuffled them.
- **A crashed or killed attempt's cost was lost.** Each attempt now writes a
  reservation first; an unfinished attempt is charged its full cap and runs
  again.
- **Unequal caps.** A later arm of a task could get a smaller cap after an
  earlier arm overshot. Every arm now gets the same cap, and the budget gate
  reserves 1.25 × cap per remaining arm.
- **Undercounted tokens.** Counts now come from `modelUsage` (all models,
  subagents included) when reported. Fresh input, cache reads and cache
  creation are kept separate.
- **Version drift.** Claude Code's auto-update is disabled for agent runs. A
  version change or a model mismatch invalidates the run, and a version
  change stops the experiment.

### Added
- A balanced, seeded arm-order schedule, published in the dry run's
  `schedule`.
- `--blind`: no pass/fail is shown while running.
- An invalid-rate stopping rule: more than 20% invalid after 9 attempts.
- An outcome table that accounts for every attempt (cost-cap, max-turn and
  timeout stops are valid failures).
- Pre-registered sensitivity analyses.
- Cost distribution per arm: p50, p90, max, cap hits, turns p90, max-turn
  hits.
- A `calibration` split: 4 real-repository tasks outside the sealed set,
  selected by a fixed rule. Like `final`, it is excluded from `--split all`.
- docs/PREREGISTRATION.md and benchmarks/preregistration/option-a-schedule.json.

## 0.7.2 — validation, statistics and a real-repository benchmark

### Security
- Empty-directory cleanup no longer follows a symlinked parent. A committed
  `.claude/skills -> ../../outside` let uninstall remove empty directories
  outside the repository.
- Third-party SKILL.md front matter must also pass a strict YAML subset
  after sanitizing, or the skill is not installable. That rules out anchors,
  aliases, tags, merge keys, flow collections, complex keys, tab indentation,
  duplicate keys, and `: ` inside plain values.
- `repo-ai eval --live` now runs in the coding lab: sandboxed grading,
  settings preflight, isolation checks and budget gating. The old host-side
  runner, which executed model-written tests unsandboxed, is removed.
- Coding experiments refuse to start, before any model call, when a task's
  toolchain has no grading sandbox.

### Statistics
- New `repo_ai.stats` module:
  - Wilson intervals per arm;
  - Newcombe paired intervals for the success difference (six agreeing
    pairs give −39…+39 points, no longer a collapsed 0…0);
  - exact McNemar;
  - equivalence only by TOST within ±10 points;
  - ceiling and floor flags;
  - paired Wilcoxon and bootstrap intervals for tokens, cache reads, cost,
    tool calls and runtime;
  - sample-size and detectable-effect planning.
- Observed equality is never reported as equivalence.

### Benchmark
- New sealed `final` split: 25 re-injected upstream bugs from
  Python-Markdown, pyflakes, cachetools, simplejson, bottle and tomli.
  - Licences are kept, and sources pinned.
  - Tasks were selected by one fixed rule over 3,760 commits; every outcome
    is in `benchmarks/tasks/oss-manifest.json`.
  - Oracles are validated inside the sandbox.
  - The split is excluded from `--split all`.
- Third-party bases run only in the sandbox, offline validation included.
- Task fields:
  - `split`;
  - `visible_after_hidden`: the regression check runs the whole suite with
    the updated upstream tests in place, ignoring methods defined in the
    hidden modules;
  - `delete` edits.

### Feature attribution
- Named ablation arms: `full-packets`, `full-rules`, `full-skills`,
  `full-thirdparty`, `full-outcomes` and `full-subagents`. `--compare
  ablations` runs Full plus all six.
- Cache reads, cache creation and uncached input tokens are recorded per run.

### Retrieval: investigated, not shipped
- Recall changes tuned on the dev split: all query terms, IDF-weighted
  filename matches, same-package expansion, a minimum candidate list.
  - They did not improve held-out results: holdout p = 0.29; sealed
    real-repo tasks −0.04 MRR, p = 0.56.
  - The v0.7.1 ranker is kept. Data in docs/RETRIEVAL.md.

### Fixed
- Float configuration values set by environment or file are converted to
  numbers. They were left as strings.

### Measured, and not
- No new live-model runs.
- The v0.7.0 pilot, re-analysed: inconclusive on success (ceiling); no
  efficiency difference is significant at n = 6.
- Proposed experiments, with costs and detectable effects:
  docs/EXPERIMENT_PLAN.md.

## 0.7.1

### Fixed
- `repo-ai eval coding` refused to run from a wheel install (pip or pipx).
  - **Cause:** the bundled task suite sits inside repo-ai's own
    environment, which the agent must be able to read so it can run
    `repo-ai`. The settings builder therefore refused, rather than risk
    re-opening the hidden tests.
  - **Fix:** the environment is now allowed piece by piece around the
    suite. The suite and its ancestors are never allowed.
  - Found by the v0.7.0 clean-install acceptance run. The v0.7.0 pilot ran
    from a source checkout and was not affected.
- Lab arms get only a `repo-ai` link first on PATH, not repo-ai's whole
  `bin` directory, so the agent's `python3` is no longer repo-ai's
  interpreter.

## 0.7.0 — coding performance lab, Skill Intelligence Network, governed optimisation

### Added
- **Coding Performance Research Lab** (`repo-ai eval coding`).
  - Three arms built from feature flags: `baseline` (plain Claude Code),
    `core` and `full`.
  - `ablate --feature X`, `--pilot`, `--resume`, and `report`, `compare`,
    `regressions` (the Regression Investigator) and `list`.
  - Fairness: one shared settings file, a dedicated audited
    `CLAUDE_CONFIG_DIR`, per-run isolation checks against Claude's `init`
    event, a `claude doctor` settings preflight, randomised arm order, and
    hidden tests graded on a fresh copy inside the sandbox.
  - Statistics: paired McNemar, bootstrap CI and Cohen's h. A pilot is never
    called significant.
  - Live runs need `--max-cost-usd`. See docs/CODING_LAB.md.
- **Execution sandbox** (`repo-ai sandbox status|pull`):
  - backends: podman, docker (as your uid), bwrap, and a deny-by-default
    macOS seatbelt;
  - no unsandboxed fallback;
  - escape tests for every backend, plus a Docker CI job.
- **Skill Intelligence Network** (docs/SKILL_NETWORK.md):
  - capability profiler;
  - Skill Radar (`skills discover --online`): Anthropic, Vercel, GitHub,
    marketplaces, publishers and skills.sh, with vocabulary-only queries;
  - quarantine and an 8-layer Skill Firewall;
  - recommendations that keep "allowed?" separate from "worth it?";
  - a hash-approved, pinned portfolio (`.repo-ai/skills.lock.json`) with
    kill switch, rollback and updates;
  - controlled trials (`skills benchmark`) and tournaments;
  - canary, promoted and harmful stages;
  - 20 adversarial fixtures.
- **Continuous optimisation** (docs/OPTIMIZATION.md):
  - `repo-ai capabilities` (coverage map), `repo-ai performance` (measured
    vs not recorded) and `repo-ai friction`;
  - `repo-ai optimize`: the Zero-Value Detector, a context-budget governor,
    research proposals and skill-evolution proposals;
  - the Self-Improvement Governor (`optimize --apply|--revert`): two
    bounded retrieval knobs, explicit settings always win, rate-limited,
    journaled and machine-local.
- **Stack Packs** (`repo-ai pack list|show|plan`): built from same-zone,
  per-repository sanitized patterns. An item needs 2+ repositories or a
  measured benefit, and a plan changes nothing.
- **Seven manual-only native skills**, which cost no always-loaded context:
  `/repo-discover-skills`, `/repo-skill-audit`, `/repo-skill-recommend`,
  `/repo-skill-evaluate`, `/repo-capabilities`, `/repo-performance` and
  `/repo-optimize`. They are also in the plugin bundle.
- **Task suite: 59 tasks** (+18): security, auth, database, frontend,
  performance, migration and architecture. All oracles are valid.

### Changed
- Capability coverage is judged from skill descriptions, not bodies.
- Zone patterns keep per-repository entries and pinned public third-party
  skills. `registry audit` checks them.
- A repository registered in two zones is denied everything until fixed.
- `skill_publishers` and `skill_marketplaces` come only from the user's
  config.

### Fixed
- Frameworks in `facts.json` are names. The profiler and zone patterns
  previously read them as objects and always saw none.
- `eval coding --dry-run` no longer records an experiment.

### Security
- An independent review of the v0.7 diff found 3 high, 4 medium and 4 low
  issues. All are fixed, with regression tests (docs/SECURITY.md).

### Measured, and not
- Retrieval benchmark unchanged: recall@5 1.0, MRR 0.942, false injection 0.
- On the 41 tasks shared with v0.6, localization did not regress.
- On the 18 new tasks, repo-ai trails grep slightly (MRR 0.793 vs 0.830).
- Live pilot (6 held-out tasks × 3 arms, Sonnet, 18/18 valid runs, $3.08
  spent in total):
  - all arms solved every task, a ceiling effect;
  - median tool calls 8 → 5.5 (core) and 4 (full);
  - tokens fell on 5 of 6 tasks per arm; cost about the same.
  - Directional only: **task-completion improvement is unverified.** See
    benchmarks/results/coding-pilot-v0.7.0.md.

## 0.6.1

### Fixed
- `repo-ai eval` workspaces no longer include `__pycache__`/`*.pyc` files.
  - **Cause:** pip byte-compiles the bundled suite on install, and every
    workspace built from an installed package copied those files.
  - **Effect:** the naive-grep baseline was skewed (installed-package MRR
    0.336 vs 0.397 from source), and live runs would have shown compiled
    copies of the base code.
  - repo-ai's own localization numbers were unaffected.

## 0.6.0 — measured, outcome-aware, hardened

### Added
- **`repo-ai eval`.**
  - A frozen suite of 41 synthetic, held-out coding tasks in Python,
    TypeScript and Java, shipped in the wheel.
  - Offline mode (default): oracle validation, localization against a naive
    grep baseline, a deterministic dev/holdout split, and a `--check`
    regression gate (a new CI job).
  - Live mode (opt-in): paired, budget-capped headless Claude Code A/B runs
    with least-privilege permissions, a seeded arm order, McNemar and
    bootstrap statistics, and per-task regressions. Live mode has not been
    run. See docs/EVALUATION.md.
- **Evidence graph** (`repo-ai graph <file|symbol:|route:|component:>`). Every
  edge carries its provenance: parser, resolver, manifest or git (proven), or
  naming, pattern or heuristic (inferred). Index schema v6 adds symbol-use
  evidence and API-path literals, which link frontend calls to backend
  routes. v5 indexes migrate in place.
- **`repo-ai packet "<task>"`.** A source-linked task briefing under a token
  cap: a query plan (exact path → stack frames → symbols → routes → changed
  files → ranked retrieval), locations, linked tests and focused commands,
  learned constraints, blast radius, uncertainty and freshness. The
  `/repo-locate` skill now uses it.
- **Context Flight Recorder** (`flight_recorder = true` or
  `REPO_AI_FLIGHT_RECORDER=1`; `repo-ai debug last|purge`). Opt-in and
  local. It records what the prompt hook injected or omitted and why. It
  never stores the prompt, only a hash and length.

- **Outcome-aware memory** (`learning_signals = "outcomes"`, which `--smart`
  now sets).
  - Per-session episodes: candidate, injected and edited paths, known-command
    results and a status (verified, failed, unverified or no-change). Never
    prompts or output. Retention is 30 days or 400 sessions.
  - An outcome prior: leave-one-session-out shadow evaluation, promoted only
    on a measured gain, at most ±30 %, and reversible
    (`learn shadow|approve ranking|rollback ranking`).
  - Counterevidence: a command rule that keeps failing in recorded sessions is
    never auto-applied, and is demoted from active to proposed.
  - Friction radar (`learn friction`).
  - The `learn status|review|explain|approve|reject|rollback|history|forget|export`
    lifecycle; the v0.5 flags still work.
- **`repo-ai privacy audit`**: every store, its size, retention and git
  state, plus allow-list checks for outcome stores. It exits 1 on a
  violation.
- **Skill lifecycle**:
  - `skills discover|propose|test|diff|promote|disable|canary|draft|doctor`;
  - a static sandbox test that never executes skill commands;
  - a canary lab with a Fisher test and no causal claims;
  - opt-in Tier-2 drafting, gated by `skills_llm`, zone policy and an
    explicit budget. Its output is an untrusted draft, activated only by
    `promote --draft`;
  - skill-version usage is recorded in outcomes;
  - a `max_generated_skills` cap.
- **Workflow Compiler** (`workflow list|plan`): typed playbooks from verified
  sessions or structural facts. Previews are read-only and verified
  statically; repo-ai never executes them.
- **`orchestrate plan`**: advice for zero to three read-only specialists,
  with one writer and merge point and capped fan-out. It spawns nothing.
  Optional advisory `repo-skeptic` subagent.
- **Registry and zones** (`registry …`, `crossrepo context|impact`): opt-in;
  zones never share; `work` and unregistered repositories deny model
  drafting; the pattern library is sanitized and audited.
- **UX:**
  - `review --changed|--branch` (change passport);
  - `budget` (Budget Governor; estimates are labelled);
  - `quickstart`;
  - `completion bash|zsh|fish`;
  - `status` shows active capabilities;
  - curated manual-only `/repo-pr` skill.
- Docs: PRODUCT_SPEC.md, SKILLS.md, CROSSREPO.md; LEARNING.md rewritten
  around the four stores.

### Changed
- **Retrieval, driven by the new suite** and tuned on its dev split only.
  Held-out MRR went from 0.403 to 0.534; recall@5 went from 0.496 to 0.629,
  still below grep's 0.683.
  - lexical ranking is relative to the best match;
  - new filename-term signal;
  - prose is discounted unless the request is about documentation;
  - "documented" no longer triggers the docs intent;
  - quoted plain words are not treated as identifiers;
  - priors count half on files without evidence.
- The retrieval gold set's MRR rose from 0.875 to 0.942, with false injection
  still 0 %.

- The filename-term signal is cached and prefix-filtered. The prompt hook on
  a 4,002-file repository is 0.121 s p50 (0.5.1: about 0.13 s).

### Security
An independent review found the issues below; all are fixed and covered by
regression tests (docs/SECURITY.md).
- **High:**
  - repository config could choose a program for repo-ai to run
    (`bob_binary`/`summarize`, `claude_cmd`); such keys are now accepted
    only from the user's config, the environment or CLI flags;
  - a committed `.claude`/`.repo-ai` symlink could redirect writes, for
    example into `~/.claude`; every write and delete is now checked for
    containment;
  - the query cache stored prompt text; it now stores none, old entries are
    purged, and `privacy audit` checks the cache.
- **Medium:**
  - git option injection through index metadata;
  - one repository registered in two zones under two path spellings;
  - static skill tests missed fenced code blocks and several dangerous
    commands, and pinned bodies were not re-validated;
  - unquoted repository paths in suggested commands.
- **Low:**
  - the live-eval budget could be overshot;
  - contamination detection and a narrower tool allow-list for live eval;
  - an unescaped read-only database URI;
  - corrupt state files are quarantined;
  - exponential glob matching;
  - redaction of bearer tokens and secret-named assignments;
  - the hook timeout could be swallowed;
  - the optional grammar pack is never asked to download, and the extra is
    pinned below 1.0.
- A user's own `learning_signals`/`flight_recorder` setting now beats the
  repository's; `doctor` reports ignored keys and config files that fail to
  parse.

### Fixed
- Migrating a v0.4 `.gitignore` section into the managed block no longer
  shows up as drift in `status`. CRLF files were affected too (found on
  Windows CI).
- `skills promote` can re-activate a skill the user had disabled.

## 0.5.1 — reliability

### Fixed
- **Exact round trips for human-owned files.** `init` then `uninstall` now
  restores `CLAUDE.md`, `AGENTS.md`, `.gitignore`, `.bobignore` and
  `.claude/settings.json` byte for byte. The pre-install bytes go into a
  machine-local ownership ledger (`state/originals.json`). They are written
  back only when what's left after removing repo-ai's material is equivalent
  to the recording, so human edits made while installed are never reverted.
- **Line endings.** CRLF files stay CRLF: managed blocks use the file's own
  line ending, and reads no longer translate newlines. A CRLF checkout of
  repo-ai's own files (git `autocrlf` on Windows) is still recognised as
  pristine, so it isn't rewritten or orphaned.
- **JSON formatting.** Rewriting `settings.json` keeps the file's indent
  (spaces, tabs or single-line), separators, line ending, trailing newline and
  literal Unicode.
- **Windows console output.** `--diff`, hooks and other output no longer
  crash on a non-UTF-8 pipe. Pipes get UTF-8, and consoles replace characters
  they can't show.
- Manifest-derived commands (`make -C dir`, `cd dir && npm run …`) always use
  POSIX separators.
- Found by the new lint/type gates: a closure in secret redaction that
  captured its loop variable, a shadowed variable in the git co-change scan,
  and an unchecked `None` in `learn --rollback`.

### Changed
- **The version is single-sourced** from `repo_ai.__version__`. Every release
  bumps it, so `pipx upgrade repo-ai` works for Git installs (a
  same-version reinstall still needs `pipx reinstall repo-ai`).
- **CI:**
  - Windows (Python 3.10 and 3.13) is a required gate, no longer best effort;
  - Python 3.14 added;
  - new lint job: ruff with a correctness-focused rule set, mypy, and a
    plugin-freshness check;
  - macOS runs on `main` and tags only, to save private-repository minutes.
- `tests/test_roundtrip.py`: 18 regression tests covering eight settings
  layouts, CRLF, missing final newlines, edits made while installed,
  per-agent uninstall, CRLF checkouts, and non-UTF-8 consoles. 13 of them fail
  on 0.5.0.

## 0.5.0 — Claude Code native

### Added
- **Claude Code adapter.** `repo-ai init --agent claude [--smart]` writes:
  - a managed CLAUDE.md block;
  - path-scoped `.claude/rules`;
  - 7 curated skills;
  - 4 subagents;
  - hooks merged into `.claude/settings.json` (SessionStart, UserPromptSubmit,
    PostToolUse, Stop; `PostToolUseFailure` only with signals).

  Verified against Claude Code 2.1.303, including `claude plugin validate`.
- `--agent claude|bob|both|auto|none`, `--smart`, `--dry-run`, `--diff` and
  `--local-only`. Agents accumulate on re-init; `uninstall --agent X` removes one.
- **Adapter layer** (`adapters/`). One engine, with per-agent formats.
  AGENTS.md and CLAUDE.md are deduplicated according to Claude Code's
  AGENTS.md loading rules.
- **Ownership-aware writes** (`fsutil.Plan`): managed blocks, checksum markers,
  atomic writes, backups, exact dry-run diffs. Hand-edited files are never
  overwritten or deleted.
- **Learning engine** (`repo-ai learn`): rules derived from evidence, with
  provenance, confidence and placement. Four policies; dedupe against human
  instructions; retirement when the evidence disappears; history and rollback.
- **Skill Factory** (`repo-ai skills`): validated, repo-specific skills
  (`repo-add-endpoint`, `repo-tests`, `repo-add-component`, `repo-precheck`,
  and the manual-only `repo-db-migration` and `repo-release`), with
  collision checks, versions and rollback.
- **Impact analysis** (`repo-ai impact <path|symbol|--changed|--branch>`):
  transitive importers, linked tests, routes, CI and build references,
  co-change partners, focused test commands, and explicit uncertainty.
- `repo-ai explain`, `context --scope diff|branch|component:|lang:|path:|tests`,
  and `context --agent claude`.
- `repo-ai refresh`: a debounced, lock-protected background update for hooks.
- `status --json`, `doctor --agent claude --json` (hook round-trip latency,
  Claude's own validator), `learn --json`, `skills --json`.
- An optional **Claude Code plugin** (`integrations/claude-plugin/`) and a
  marketplace manifest, both generated from the same source as the project files.
- A standard layout `.repo-ai/{config.toml,context,state,learning}`. The v0.4
  `.bob/context` layout is detected and kept.
- Local opt-in signals: hashed sessions, known commands only, never prompts.
- Benchmarks (`benchmarks/run.py`, gold set, v0.4.0 and v0.5.0 results), five
  fixture repositories, CI workflow, the docs set, and an MIT LICENSE.

### Changed
- **Retrieval:**
  - IDF-weighted term coverage, so relevance is absolute rather than relative
    to the other results;
  - confidence gating: irrelevant prompts return nothing (false injection went
    from 100 % to 0 % on the gold set);
  - stack-trace frame parsing;
  - Porter stemming with identifier subwords;
  - route tokens indexed;
  - test links and test promotion;
  - adaptive hook budget;
  - a query cache invalidated by a content fingerprint;
  - per-signal score breakdown in the JSON output.
- **Index schema v5**: `test_links`, `query_cache`, Porter FTS. v4 indexes are
  migrated in place with a one-time re-analysis instead of being wiped. Newer
  indexes are refused with a message.
- `repo-ai init` on an initialised repository refreshes it and returns 0
  (v0.4 returned 1).
- `status` exits 2 when stale; `--brief` still always exits 0.
- Hooks for both agents fail open and never block; the Bob Stop hook uses
  `repo-ai refresh`.

### Fixed (v0.4 defects, each with a regression test)
- Makefiles were never parsed. `requirements/*.txt` and `requirements-*.txt`
  were skipped. `*.csproj` had no parser. Maven always claimed `./mvnw`.
- CONVENTIONS.md "Do not edit" was always empty. HOTSPOTS.md "Recently changed"
  was empty.
- Python 3.10 crashed without `tomli`, which is now declared.
- `.bob/context` was hard-coded in hooks, ignores and commands, so a custom
  `out_dir` broke them. `out_dir` is now also validated to stay inside the repo.
- `uninstall` left `.gitignore` entries behind. Legacy entries are now migrated
  into a managed block and removed cleanly.
- Quarantine rule names referred to rules that did not exist. Anthropic keys
  were reported twice. The security docstring contradicted the behaviour. The
  generic-rule severity branch was dead code.
- Incremental drift:
  - conventions were inferred only from changed files;
  - stale import edges remained after deletions;
  - new files never received their importers;
  - imports were resolved twice;
  - test frameworks were re-voted without test files, so pytest flipped to Vitest;
  - route order differed between full and incremental runs.
- Python `from pkg import module` didn't link to the module file. Empty
  `__init__.py` packages were reported as external.
- AGENTS.md could be classified as "generated" because of repo-ai's own block.
  Managed blocks are now stripped before indexing, and repo-ai's own edits are
  not counted as drift.
- Symlinked files could pull content from outside the repository.
  Control-character filenames are now skipped. New files are written with the
  normal umask rather than 0600.
- `embeddings` was advertised but not implemented; the option is removed, and
  old config keys are reported as retired.

### Verification for this release
- `pytest`: **162 passed** on Python 3.12.14, 3.13 and 3.14.7 (macOS arm64).
- Python 3.10/3.11: not run locally (no interpreter available). The minimum-version
  analysis (`vermin`) reports nothing above 3.10 except the `tomllib` import,
  which falls back to `tomli` on older versions. CI covers 3.10–3.13 on Linux.
- Wheel and sdist built. A pipx install of the wheel passed
  `scripts/acceptance_demo.sh` end to end.

## 0.4.0
- IBM Bob context layer: index, generated docs, AGENTS.md block, skill, hooks.

## Unreleased — local 0.9.0.dev0 finalization

- Separate provider JSONL from bounded stderr diagnostics; preserve unknown cost,
  extract Codex agent messages and reject inconsistent live terminal protocols.
- Replace handoff imports with local-store-bound /2 integrity receipts; enforce
  freshness, remaining budget, execution authority and single continuation attempts.
- Validate patches before source writes; journal existing-file apply and provide
  conflict-aware undo. Separate tested candidate assurance from applied assurance.
- Grade the actual selected evaluation patch; correct intentional-edit accounting.
- Disclose provider transmission/host-read surfaces and retained exports; add local
  mission listing and elapsed/provider/observed-cost display.
- Add exact-source validation and upstream replay journey scripts. No comparative
  benefit, production qualification, portable partial handoff or model-team claim.
