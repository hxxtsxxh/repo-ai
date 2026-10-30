# Work queue (living; top = next)

Updated 2026-10-30T06:40Z. PRs: #3 provider stack (Claude, OpenCode, Gemini no-copy, sweep, probe; two reviews
fixed), #4 skills autopilot (review fixed; stacked on #3), #5 site (stacked on #4; merge after PyPI 0.10.0).

| # | Item | Gate | State |
|---|---|---|---|
| 1 | Merge #3, #4 after CI; release prep + catalog; full-suite freeze on the final tip | C20 | in progress |
| 2 | Tag v0.10.0 (owner-approved), verify PyPI/GitHub artifacts, clean install smoke | C01, C20 | next |
| 3 | `site_facts.py --record-pypi` for 0.10.0, merge #5, verify deployed pages | C19 | after 2 |
| 4 | Real-project journeys: one offline on a real OSS repo, one live provider + skill discovery | C21 | todo |
| 5 | Codex: dedicated CODEX_HOME login to shrink token exposure | C18 | todo |
| 6 | Verify speed profiling (C16); Linux live provider run in podman | C16, C17 | todo |
| 7 | ACP client adapter to reach PLANNED agents with one permission policy | C04, C05 | todo |
| 8 | Skill value: blinded paired trial with a predeclared outcome (budget: 12 calls left) | C10 | todo |
| 9 | Claude token refresh inside the sandbox: re-observe after the access token expires | C03 | waiting |
