# Security and privacy

## Threat model

repo-ai runs on a developer's machine, inside repositories that may be
hostile: cloned from the internet, or containing text written to manipulate
an AI agent. It has to stay safe when:

- a repository commits files designed to make repo-ai execute code, write
  outside the repository, or leak data. That includes config, symlinks,
  filenames, an index database, the learning ledger and skills;
- repository text (READMEs, comments, tests) or model output contains
  instructions aimed at Claude or at repo-ai;
- the user works in both personal and work (enterprise) repositories on
  the same machine;
- hooks fire concurrently, get interrupted, or receive malformed payloads.

## Invariants (each is enforced by tests)

| Invariant | Where | Tests |
|---|---|---|
| A repository's files cannot make repo-ai run a program or send data: `claude_cmd`, `bob_binary`, `summarize`, `skills_llm` and `follow_symlinks` are honoured only from the user's config, the environment or CLI flags | `config.py` (`TRUSTED_ONLY_KEYS`) | `test_repository_config_cannot_choose_programs_to_run` |
| A user's own `learning_signals` / `flight_recorder` setting beats the repository's | `config.py` (`USER_WINS_KEYS`) | `test_user_config_off_beats_repository_signals` |
| No write or delete leaves the repository or goes through a symlink, including `.claude -> ~/.claude` | `fsutil.ensure_inside`, `paths._no_symlinks` | `test_symlinked_claude_dir_is_never_written_through`, `test_symlinked_state_dir_is_refused` |
| Prompt text is never persisted: the query cache is keyed by a hash and stores no prompt-derived text; episodes, flight and signals store hashes, lengths and paths | `retrieval.to_cache`, `episodes.py`, `flight.py` | `test_prompt_text_never_lands_in_the_index`, `test_outcomes_drive_…`, `test_flight_recorder_…` |
| Git refs from index metadata cannot become git options | `gitinfo.safe_ref`, `--end-of-options` | `test_poisoned_index_metadata_cannot_inject_git_options` |
| Suggested shell commands quote repository paths | `impact._focused_for`, `manifests.py` | `test_hostile_test_filename_is_quoted_in_suggested_commands` |
| Skill and workflow text is never executed; static tests read inline code and fenced blocks | `skillcheck.command_text`, `skills_lab.test_skill`, `workflows.verify` | `test_fenced_dangerous_commands_fail_static_tests`, `test_skill_test_flags_unknown_commands_and_never_runs_them` |
| A pinned skill body (a draft, an older version, or a tampered `skills.json`) is validated again before writing | `skills.run_factory` | `test_tampered_pinned_body_is_not_written` |
| Model output cannot set front matter or the risk class, and cannot activate itself | `skills_lab.run_draft`, `cli` `promote --draft` | `test_tier2_draft_is_untrusted` |
| Zones never share; one repository cannot be in two zones under two spellings; peer indexes open read-only, with the path escaped | `registry.py` | `test_zones_never_share`, `test_case_variant_…`, `test_registry_audit_catches_tampering` |
| repo-ai never adds allow rules, `bypassPermissions` or `allowed-tools` | adapters | `test_claude_setup.py`, `tests/test_roundtrip.py` |
| Hooks always exit 0 and print nothing on error; timeouts cannot be swallowed | `hooks.py` (`_Timeout(BaseException)`) | `test_hooks.py` |
| Corrupt state files are moved aside (`*.corrupt`), and features keep working | `episodes.py`, `flight.py` | `test_corrupt_state_files_are_quarantined_not_fatal`, `test_malformed_flight_lines_do_not_crash_commands` |
| No symlink inside repo-ai's own directories is ever followed | `paths._no_symlinks`, `O_NOFOLLOW`, `index.open_index` | `test_committed_symlink_inside_state_dir_is_refused` |
| A repository may tighten `respect_gitignore`/`detect_secrets` but never relax them | `config.py` (`STRICTER_ONLY_KEYS`) | `test_repository_cannot_relax_gitignore_or_secret_scanning` |
| No network: the optional grammar pack is never asked to download | `parser._get_ts_parser` | `test_optional_grammar_pack_never_downloads` |
| Secrets are shown as rule plus `path:line`, never the value; bearer tokens and `*TOKEN*=` style assignments are redacted | `security.py` | `test_security.py` |

## v0.7.0: execution sandbox, Skill Intelligence Network, optimiser

| Invariant | Where | Tests |
|---|---|---|
| Untrusted code (benchmark tasks, model-written workspaces) runs only in a sandbox backend; there is no unsandboxed fallback | `sandbox.get_backend` | `test_no_backend_means_no_execution` |
| Each backend blocks reads outside the workspace and home, writes outside, the network, inherited environment, symlink escapes, signals to outside processes, and runaway process trees | `sandbox.py` | `tests/test_sandbox.py` (every available backend; Docker in CI) |
| The macOS backend is deny-by-default: no Mach services, so no LaunchServices `open`, Apple Events or pasteboard | `SeatbeltBackend.profile` | `test_seatbelt_cannot_reach_launchservices` |
| Lab agents see only their own workspace; hidden tests are installed only into a fresh grading copy after the agent exits; leftover processes are killed; kept workspaces move under the denied lab home | `coding_lab.run_one` | `test_each_run_may_write_only_its_own_workspace` |
| Lab agents inherit no host credentials (an allowlisted environment) | `evals.agent_env` | `test_agent_environment_carries_no_host_credentials` |
| "Fake" mode can never run the real client (it would skip the budget, the config audit and the preflight) | `coding_lab.run_experiment` | `test_fake_mode_refuses_the_real_client` |
| Radar queries contain only fixed technology vocabulary | `radar.sanitize_query` | `test_19_…` |
| Network: allowlisted hosts, pinned commits, redirects re-checked, credentials sent as unredirected headers, owner/repo names validated | `radar.Client`, `check_slug` | `test_github_token_is_never_forwarded_on_redirect`, `test_radar_refuses_injected_owner_or_repo` |
| Quarantine: blob SHA verified, `0600`, `O_EXCL|O_NOFOLLOW`, no symlinks, FIFOs or devices, size caps enforced while reading | `firewall.py` | `test_special_files_are_never_read`, fixtures 1–20 |
| A blocked skill is never installable; installation needs the reviewed content hash; front matter is reduced to an allowlist (no `allowed-tools`, `hooks` or other escalation in any spelling) | `portfolio.install`, `firewall.sanitize_front_matter` | `test_quoted_allowed_tools_and_hooks_are_flagged_and_removed` |
| A committed lockfile is untrusted: invalid names, paths or hashes are ignored (and preserved, never deleted); object-store content is re-hashed before every restore | `portfolio.entry_problem`, `verified_object` | `test_a_committed_lockfile_cannot_aim_outside_its_skill` |
| State that steers repo-ai (tuning, optimisation journal, radar results) lives outside the repository | `registry.machine_dir` | `test_apply_journal_and_revert` |
| The governor changes only two bounded retrieval knobs, never an explicit setting | `optimize.govern` | `test_governor_rules`, `test_explicit_repository_config_beats_tuning` |
| Radar publishers and marketplaces come only from the user's config | `config.TRUSTED_ONLY_KEYS` | `test_repository_config_cannot_choose_skill_publishers` |
| Stack Packs and zone patterns never carry paths or local skill sources, and never cross zones; a repository in two zones is denied everything | `registry.py`, `stackpacks.py` | `tests/test_stackpacks.py`, `test_zone_conflict_denies_discovery` |

### Independent review (0.7.0 development build)

A separate read-only reviewer audited the v0.7 diff and reproduced each
finding in throwaway directories. Every finding was fixed before release,
and each fix has a regression test:

| Severity | Finding | Fix |
|---|---|---|
| High | The seatbelt profile was allow-by-default: code being graded could reach LaunchServices (`open x.command` runs outside the sandbox) and signal outside processes; `/Users/Shared` and `/Volumes` were readable | deny-by-default profile (system and toolchain reads, workspace writes, same-sandbox signals only) |
| High | A quoted `'allowed-tools':` key evaded the firewall and survived install-time stripping | allowlisted front matter at install; normalised keys in the firewall |
| High | Firewall evasions: prose downgrades, any earlier "never" on the line, a fake `/*` in shell, payloads in `.png` assets, Unicode tag characters, `\` continuations | no downgrade for remote-exec/exfiltration/credentials; negation only directly before the match; block comments only for C-like languages; asset signatures checked; tag characters detected; continuations joined |
| Medium | A committed lockfile could direct deletes and restores outside the skill directory, or point the lab at an unapproved quarantine copy | entry validation; re-hashed objects |
| Medium | `--trial-fake` alone ran the real `claude` without a budget, audit or preflight | fake mode requires a fake client |
| Medium | Lab agents could read and write the whole lab root, including the settings file and other arms' kept workspaces; leftover processes could alter hidden tests | per-run scope; grading on a fresh copy; process-group kill; kept workspaces under the denied lab home |
| Medium | Lab agents inherited host credentials (`GITHUB_TOKEN`, AWS keys, `SSH_AUTH_SOCK`) | allowlisted environment |
| Low | Steering state (tuning, journal, radar results) lived in the committable `.repo-ai/state/`; `skills audit` trusted quarantine paths; repository config could choose radar publishers | machine-local state; quarantine paths checked; trusted-only keys |
| Low | skills.sh token was forwarded on redirects; owner/repo names from APIs and config were not validated | unredirected headers; `check_slug` |
| Low | A repository in two zones fell back to the permissive policy | deny everything on a conflict |
| Low | Quarantining a FIFO hung; size could change between stat and read | regular files only; capped reads |

A second pass by the same reviewer re-ran every reproduction:
- **Fixed:** all 11 original findings.
- **New issues, all fixed with regression tests before release:**

| Severity | Finding | Fix |
|---|---|---|
| High | More remote-execution forms reached "eligible": `bash -c "$(curl …)"`, `sh <(curl …)`, `\|& sh`, download-then-run, `xargs sh -c`, `sh -c "$(tail … assets/logo.png)"`, a script behind a valid PNG header | rules for command and process substitution, download-then-run, xargs and executing an asset; printable text inside assets is scanned for shebangs and instruction rules |
| Medium | A negation word plus a comma still softened credential and exfiltration instructions | for those categories only "never/do not <action verb>" directly governing the match counts, with no second action verb in between |
| Medium | A lock entry without `name`, or a symlinked skill directory, made the kill switch and uninstall fail for every skill | the key is the identity; symlinked directories are left untouched; one plan per skill |
| Medium | Delimiter tricks (`----: x`, `--- `, a BOM) could hide `allowed-tools` from the sanitizer | exact `---` lines only; any delimiter-like line makes the skill uninstallable; sanitized output is re-verified before writing |
| Low/Medium | A process left by one arm could stage data for a later arm; hidden tests sat in a readable grading copy | grading copies live under the denied lab home and are re-checked; every earlier run's workspace is denied to later runs |
| Low | A disguised real client in fake mode could still bill | fake mode uses an empty Claude config directory (no login) |
| Low | seatbelt still allowed Homebrew `etc/`/`var/`, the whole pyenv tree, and stat() everywhere | only code directories under Homebrew and `/usr/local`; the interpreter's real prefix; metadata only on ancestors of readable paths |

A third pass confirmed all 7 fixed and reported three low notes, now also
fixed:
- fake mode never passes an API key;
- uninstall skips a failing entry instead of aborting;
- `tempfile` inside the sandbox is now covered by a test.

Two probes from that pass were not repeated: symlinks in the empty-directory
cleanup, and further YAML edge cases against the front-matter allowlist.
By code reading both only remove (empty directories, disallowed keys).

Re-auditing the real Anthropic and Vercel skill corpus (29 skills) after
these changes gives 15 eligible, 14 review and 0 blocked. Most of the
review verdicts are about licences. The rest are an API skill that uploads
files to its own API, an incomplete font bundle and an embedded archive.

## v0.7.2: closing the remaining probes

| Issue | Status | Test |
|---|---|---|
| Empty-directory cleanup followed a symlinked parent: with `.claude/skills -> ../../outside`, uninstall removed empty directories outside the repository (reproduced) | fixed: every component from the root is checked before each `rmdir` | `test_empty_dir_cleanup_never_follows_a_symlinked_parent` |
| YAML edge cases in third-party front matter (anchors, aliases, tags, merge keys, flow collections, complex keys, tab indentation, duplicate keys, `: ` inside plain values) | sanitized front matter must also pass a strict YAML subset that every parser reads the same way, or the skill is not installable; the real corpus is unaffected (15 eligible, 14 review, 0 blocked) | `test_yaml_edge_cases_are_not_installable` |
| Legacy `eval --live` graded model-written code on the host | removed: `--live` is the sandboxed lab; experiments refuse to start without a grading sandbox | `test_live_is_the_sandboxed_lab_and_its_dry_run_spends_nothing` |
| Third-party benchmark code (the open-source bases) | runs only in the sandbox, including offline oracle validation | `validate_task` (third-party bases) |

## Independent review (0.6.0 development build)

A separate read-only reviewer audited `src/repo_ai/` against the claims
above, reproducing each finding in throwaway repositories. Every confirmed
finding was fixed before release:

| Severity | Finding | Fix |
|---|---|---|
| High | Repository config could set `bob_binary`/`summarize` (and `claude_cmd`), and repo-ai ran the binary, even from a background refresh | trusted-only keys |
| High | A committed `.claude` (or `.repo-ai`) symlink made repo-ai write into the target, for example a global `~/.claude` | containment check on every write and delete; symlinked state directories refused |
| High | The query cache stored prompt text, and the privacy audit did not inspect it | the cache stores no prompt-derived text; old entries are never served and are cleared on update; the audit checks the cache |
| Medium | `git_head` from the index could inject `--output=…` into `git diff` | ref validation plus `--end-of-options` |
| Medium | A repository could join two zones under two path spellings (Python API) | device+inode repository identity; audit recomputes identities |
| Medium | Static skill tests ignored fenced code blocks and missed `curl … \| sh`, `rm -fr`, `git reset --hard` and similar; pinned bodies were not re-validated | fenced blocks scanned, risky patterns widened, pinned bodies re-validated |
| Medium | Repository filenames went unquoted into suggested commands | `shlex.quote` |
| Low | Live-eval spend could exceed the cap (clamped charges, negative caps accepted) | charge the reported cost; caps must be positive |
| Low | Hidden tests reachable during live eval | narrower Bash allow-list; symlink-safe hidden-test install; contamination detection (see residual risks) |
| Low | Unescaped read-only SQLite URI | `Path.as_uri()` |
| Low | Corrupt state disabled features | quarantine |
| Low | Exponential glob matching | segment DP matcher |
| Low | Redaction missed bearer tokens and `NAME=secret` | added |
| Low | The hook timeout could be swallowed | `BaseException` |
| Info | The optional grammar pack (1.x) downloads at runtime | only on-disk grammars are used; extra pinned `<1.0` |
| High (re-check) | Committed symlinks *inside* `.repo-ai/state/` (`update.lock`, `.dirty`, `signals.jsonl`, `flight.jsonl`, `index.db`, `last-refresh`) were opened directly and followed | the layout refuses any symlink inside repo-ai's directories; state files open with `O_NOFOLLOW`; a symlinked index is refused |
| Medium (re-check) | Static tests missed `~~~` fences, indented blocks, `<code>`, lookalike backticks and prose | wider `command_text`; high-precision destructive patterns checked over the whole body |
| Low (re-check) | A repository could relax `respect_gitignore`/`detect_secrets`; malformed flight lines crashed `budget`/`debug`/`privacy audit`; some secret forms went unredacted | stricter-only keys; non-object lines ignored; `-u user:pass`, `X-…-Key:`, `mysql -p…` and Basic auth redacted |
| Info (re-check) | `init --diff` could print a symlinked `CLAUDE.md` target | refused paths are never shown in diffs |

| Low (third pass) | Mistyped flight-log fields crashed `debug`/`budget`; `Authorization: token` went unredacted; `include_overrides` could re-admit gitignored files | field coercion; redaction added; overrides apply only after the gitignore, dockerignore and .bobignore checks |

A second read-only pass by the same reviewer re-ran every reproduction:
- **Fixed:** 10 of 13. The rest are listed as re-check rows above.
- **Third pass:** confirmed the state-directory fix, including symlinks
  planted between runs; its three small findings are fixed.
- **Still open:** a race between the containment check and the write. Only
  a concurrent *local* writer could exploit it (for example a `git checkout`
  that swaps in a symlink during a background refresh).
- **Inherent limit:** destructive instructions written as plain prose with
  no command keywords cannot be caught by static checks. That is one more
  reason skills that act are manual-only.

## Live provider runs: what the model process can and cannot do (0.9.0.dev1+)

`repo-ai do --run --allow-live-provider` launches a third-party coding CLI as a child process of repo-ai. The write
boundary is repo-ai's **outer** sandbox (macOS seatbelt, or bubblewrap on Linux): writes are limited to a disposable
candidate checkout and a scratch directory, and the original checkout is never written until `repo-ai apply`.
Two exceptions are deliberate and are the main residual risks of live runs:

- **Codex: its own inner sandbox is bypassed.** repo-ai passes `--dangerously-bypass-approvals-and-sandbox` to Codex
  **only after** it has confirmed that the outer sandbox is active for that run (nested sandboxes are not supported on
  macOS, so Codex's own would otherwise fail). If the outer sandbox is unavailable the run is refused, not downgraded.
  So for Codex the outer sandbox is the *only* boundary; a flaw in it is not backstopped by Codex's own. Network is
  allowed for live runs (the model API needs it), which means the child can send what it can read, including the
  candidate checkout, to its provider and, in principle, elsewhere. Credentials are not copied into the workspace; Codex
  runs with a scratch `HOME` seeded only with its own auth file.
- **agy (Antigravity, macOS only): reads the real `HOME` and the login keychain database file.** agy has no scratch-HOME
  login, so it runs with the real `HOME`, but the seatbelt profile denies all reads under `HOME` except its own state
  directory (minus per-user history), `~/.gemini/config`, `~/.local` and the two `login.keychain-db` /
  `metadata.keychain-db` files it needs to authenticate. Those files are encrypted, but the child process can read them,
  and has network access. repo-ai never prints, copies or stores keychain contents, and never uses
  `--dangerously-skip-permissions` for agy (shell actions are denied in headless mode and reported as `denied_actions`).
  If this exposure is unacceptable for you, do not use `--agent agy`; it is refused on non-macOS hosts.
- **Cost is not enforced for subscription CLIs.** Codex and agy report no USD; repo-ai records cost as `UNKNOWN`
  (never `0`), bounds wall-clock with `--max-seconds`, and refuses a USD ceiling that the provider cannot enforce.
- **Provider readiness is a cached observation, not a probe.** `agents list`, `doctor`, `route` and `--dry-run` never
  start a model. Observations (`READY`, `USAGE_LIMITED`, ...) come only from a real run, are bound to the provider
  binary's identity hash, and expire.
- **A passing test is not a proof of correctness.** The mission `claims` block separates "the frozen tests observed a pass"
  from "the task is correct" and lists requirement words the tests do not echo; it is a heuristic and can miss gaps.
- **Handoff capsules are integrity-checked, not authenticated.** A capsule carries an unkeyed checksum plus a receipt in
  the local store; it cannot import authority into another store, repository, zone or source revision (tested), but anyone
  who controls both the capsule and the local store can forge one.

## Residual risks (stated plainly)

- **The seatbelt backend shares the kernel.** Prefer podman or
  Docker; `repo-ai sandbox status` shows which backend grading will use.
- **The skill firewall is static.** "Eligible" means no known problem, not
  proven safe. Destructive instructions written as plain prose with no
  command keywords can still pass, which is one reason installation always
  needs a human approval of the exact content hash.
- **Headless agent runs** (`eval coding`, and `eval --live`, which uses it
  since 0.7.2):
  - The agent itself runs as your user, under Claude Code's own Bash sandbox
    and permission rules, with the suite, your home directory and earlier
    workspaces denied.
  - Grading runs in repo-ai's sandbox, and experiments refuse to start
    without one.
  - For a stronger boundary around the agent itself, run experiments in a
    disposable VM.
- **Hooks call `repo-ai` from `PATH`.** Whoever controls your `PATH` controls
  what runs. This is the same trust Claude Code gives any hook command.
- **Repository-committed `.claude/` content** (skills, agents, settings) is
  Claude Code's own trust surface. repo-ai never weakens it, but it does not
  vet a repository's own hand-written skills unless you run
  `repo-ai skills test`.
- **Token counts are estimates.** Live costs are Claude Code's client-side
  estimates, not billing.

Report security issues privately to the repository owner.
