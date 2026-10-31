# Work queue (living; top = next)

Updated 2026-10-31: 0.11.3 published (#21–#36).

| # | Item | Gate | State |
|---|---|---|---|
| 1 | Release 0.11.2 (#16, #17, #18) | C20, C21 | done: published 2026-10-30, verified (PyPI = GitHub, attestation, smoke) |
| 1a | Re-run the scoped missions on the published 0.11.2 | C21 | done: python-humanize live PASS (#36); python-slugify replay PASS_WITH_PRE_EXISTING_FAILURES, fresh first run |
| 1b | Mission workspaces dropped `export-ignore` files and rewrote `export-subst` | C21 | done (#22, four review rounds) |
| 1d | Release 0.11.3 (#21–#36: apply count, export attributes, state paths, scoped setup errors, show-fixed, clones, ACP client, opencode-acp, tournament families, `.repo-ai` file, ACP stderr, Codex broker) | C20 | done: owner approved 2026-10-31; tag v0.11.3 at 7750279 (tree = qualified 2c5eeba; macOS full suite 2,762 passed, 0 failed at 14c953d, docs-only delta after); published 2026-10-31, verified: PyPI = GitHub release = local clean build (wheel `b11ff58f…`, sdist `644248fa…`), SLSA attestation from release.yml at the tag, smoke from PyPI PASS |
| 1e | Nothing reaches a state path by any route (macOS case collisions; `.claude -> conf` links) | C18 | done (#24) |
| 1f | A repository that tracks a FILE named `.repo-ai` breaks the sandboxed run directory `.repo-ai/run` (every verify/mission run) | C21 | done (#34): `init`, missions and the run directory name the file instead of ENOTDIR. `out_dir` moves the index and context only: sandboxed runs stay unavailable in such a repository (the run directory is fixed) |
| 1g | A custom `out_dir` with `init --agent none` wrote no ignore entries: the index, lock and evidence counted as part of the change and the first `verify --run` always failed ("the working tree changed while the run was being prepared") | C21 | done (#34) |
| 1c | `--expect-fix`: a setup error already at the base may stand (teardown/body errors still refused) | C21 | done (#25, three review rounds) |
| 2 | Skill value: pilot run 2026-10-30, INCONCLUSIVE (`evidence/SKILL-VALUE-PILOT-2026-10-30.md`); next a confirmatory trial with independently written tasks and oracles (5 calls left in the second budget) | C10 | todo |
| 2a | Skill radar recommended against project-convention skills | C07 | done (#14) |
| 3 | python-slugify post-apply 0 vs sandbox 20 failures | C21 | explained: `apply` printed a hard-coded "0 failed"; the post-apply observation had 20 (same interpreter); fixed in #21. An earlier note blamed the interpreter bug: wrong |
| 4 | ACP: client with one permission policy (#30) and `opencode-acp` provider under the opencode sandbox (#31, live $0 PASS) | C04, C05 | in progress: next a Gemini ACP provider (needs the owner's Gemini login) and other ACP agents as they are installed |
| 4a | Tournaments count `opencode` and `opencode-acp` as distinct providers although they share a binary and model | C12 | done (#33): providers sharing an executable are refused as a pair |
| 5 | Linux live provider run (podman + bwrap) | C17 | todo |
| 6 | `verify --show-fixed` names tests a change fixed, each confirmed alone at base and change | C11 | done (#26, redesigned after review found four false claims) |
| 7 | Verify speed profiling: host time is test execution; per-process workspace clone was the visible overhead | C16 | done for clones (#28: 0.07 s vs 0.31 s per process on 2,742 files). Background deletion was measured locally (2026-10-31) and not pursued: cleanup is 0.12 s per 2,750-file workspace, about 5 s on a 20-check `--show-fixed` run, against directories outliving the process |
| 8 | Codex: the token copied into its sandbox stays readable by its model; explore a token broker or document as permanent | C18 | done (#36): opt-in broker (`REPO_AI_CODEX_BROKER=1`, macOS) after three security-review rounds; live-verified with a ChatGPT login (calls #37 and #38 in EXPERIMENTS.md). Next: verify an API-key login; consider making it the default for Codex on macOS |
| 9 | Claude provider live on the re-logged dedicated login | C03 | done (#33, #34 provider runs) |
| 10 | Claude token-mode live check (needs the owner to create a `claude setup-token`) | C03 | blocked (owner) |
| 11 | Linux Claude runs: bwrap mounts `/proc` and, in dedicated-config mode, the config dir read-write; check whether Claude Code's file tools (Read/Glob/Grep under `--restricted --safe-mode`) can read `/proc/self/environ` or the credentials file, and deny both if so. On macOS the file-only model cannot read its environment | C03, C18 | todo (needs a Linux host) |
| 12 | Credentials inside a run were mis-stated in 0.10.0 (Codex `auth.json`, Bob settings, env keys) | C18 | done (#39): corrected changelog; disclosed on the security and providers pages. Next: consider a broker or file-only mode for Bob and env keys |

Decided 2026-10-31:
- **ACP cost label.** An ACP run keeps `cost_status: OBSERVED` at $0, with `cost_basis` naming the confinement. Any
  other status counts as unknown spend in the mission runtime (`runtime.py` spend accounting and retry decisions),
  which would wrongly mark loopback-only runs, so the label stays.
- **ACP stderr** is kept and reported (#35).
- **Rejected ACP permission requests** stay `denied_actions`, not failure reasons: they are the policy working, and the
  tests decide the outcome.
