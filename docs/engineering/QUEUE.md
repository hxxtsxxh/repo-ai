# Work queue (living; top = next)

Updated 2026-10-30 after the 0.11.2 release.

| # | Item | Gate | State |
|---|---|---|---|
| 1 | Release 0.11.2 (#16, #17, #18) | C20, C21 | done: published 2026-10-30, verified (PyPI = GitHub, attestation, smoke) |
| 1a | Re-run the scoped missions on the published 0.11.2: python-humanize done (#36 PASS); python-slugify todo | C21 | in progress |
| 1b | Mission workspaces drop tracked files marked `export-ignore` (git archive honours it): every provider mission blocks on such repos | C21 | todo |
| 1c | `--expect-fix`: unrelated tests that error at setup identically at base and candidate make the observation incomplete (design: trust model) | C21 | todo |
| 2 | Skill value: pilot run 2026-10-30, INCONCLUSIVE (`evidence/SKILL-VALUE-PILOT-2026-10-30.md`); next a confirmatory trial with independently written tasks and oracles (5 calls left in the second budget) | C10 | todo |
| 2a | Skill radar recommended against project-convention skills | C07 | done (#14) |
| 3 | python-slugify post-apply 0 vs sandbox 20 failures | C21 | explained: `apply` printed a hard-coded "0 failed"; the post-apply observation had 20 (same interpreter); fixed in #21. An earlier note blamed the interpreter bug: wrong |
| 4 | ACP client adapter to reach PLANNED agents with one permission policy | C04, C05 | todo |
| 5 | Linux live provider run (podman + bwrap) | C17 | todo |
| 6 | `verify` names tests a change fixed (needs a whole-file base run; design first) | C11 | todo |
| 7 | Verify speed profiling | C16 | todo |
| 8 | Codex: the token copied into its sandbox stays readable by its model; explore a token broker or document as permanent | C18 | todo |
| 9 | Claude provider live on the re-logged dedicated login | C03 | done (#33, #34 provider runs) |
| 10 | Claude token-mode live check (needs the owner to create a `claude setup-token`) | C03 | blocked (owner) |
