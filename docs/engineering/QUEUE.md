# Work queue (living; top = next)

Updated 2026-10-30T10:00Z after the 0.10.0 release (public main `8eeb8ef`, PyPI `repo-ai-cli` 0.10.0, site deployed).

| # | Item | Gate | State |
|---|---|---|---|
| 1 | Requirement-erasure detection (PR #7) and `--expect-fix` (PR #9): reviews, merge; ship in 0.11.0 | C11, C21, C22 | in review |
| 2 | Missions on real suites, part 2 (PR #9): python-slugify replay verifies as PASS_WITH_PRE_EXISTING_FAILURES | C21 | in review |
| 3 | Second real project journey (offline + live) | C21 | todo |
| 4 | Skill value: blinded paired trial with a predeclared outcome (6 live calls left in the 2026-10-30 budget) | C10 | todo |
| 5 | ACP client adapter to reach PLANNED agents with one permission policy | C04, C05 | todo |
| 6 | Linux live provider run (podman + bwrap) | C17 | todo |
| 7 | `verify` names tests a change fixed (needs a whole-file base run; design first) | C11 | todo |
| 8 | Verify speed profiling | C16 | todo |
| 9 | Codex: the token copied into its sandbox stays readable by its model (0.10.0 hid the rest of HOME and prefers a dedicated login); explore a token broker or document as permanent | C18 | todo |
| 10 | Claude token-mode live check (needs the owner to create a `claude setup-token`) | C03 | blocked (owner) |
