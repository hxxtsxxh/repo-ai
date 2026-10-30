# Work queue (living; top = next)

Updated 2026-10-30 after the python-humanize journey (PRs #14, #16, #17, #18).

| # | Item | Gate | State |
|---|---|---|---|
| 1 | Release 0.11.2 (#16 init `.gitignore`, #17 interpreter + tracked-ignored files, #18 verify counts): qualify on main (CI + macOS full suite), then tag | C20, C21 | blocked (owner approval) |
| 1a | Re-run the python-humanize and python-slugify scoped missions on the published 0.11.2 | C21 | todo (after 1) |
| 1b | Mission workspaces drop tracked files marked `export-ignore` (git archive honours it): every provider mission blocks on such repos | C21 | todo |
| 1c | `--expect-fix`: unrelated tests that error at setup identically at base and candidate make the observation incomplete (design: trust model) | C21 | todo |
| 2 | Skill value: pilot run 2026-10-30, INCONCLUSIVE (`evidence/SKILL-VALUE-PILOT-2026-10-30.md`); next a confirmatory trial with independently written tasks and oracles (9 calls left in the second budget) | C10 | todo |
| 2a | Skill radar recommended against project-convention skills | C07 | done (#14) |
| 3 | python-slugify post-apply 0 vs sandbox 20 failures | C21 | explained: missions used the PATH python3, post-apply the project venv; fixed in #17 |
| 4 | ACP client adapter to reach PLANNED agents with one permission policy | C04, C05 | todo |
| 5 | Linux live provider run (podman + bwrap) | C17 | todo |
| 6 | `verify` names tests a change fixed (needs a whole-file base run; design first) | C11 | todo |
| 7 | Verify speed profiling | C16 | todo |
| 8 | Codex: the token copied into its sandbox stays readable by its model; explore a token broker or document as permanent | C18 | todo |
| 9 | Claude provider live on the re-logged dedicated login | C03 | done (#33, #34 provider runs) |
| 10 | Claude token-mode live check (needs the owner to create a `claude setup-token`) | C03 | blocked (owner) |
