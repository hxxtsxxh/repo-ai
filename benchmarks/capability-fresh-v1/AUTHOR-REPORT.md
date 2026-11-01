# Author report (as returned by the corpus author agent, 2026-11-01; not independently verifiable)

**Files read (only these three):** `PREREGISTRATION.md`, `catalog-for-authors.json`, `stacks-for-authors.json` in this
directory. Did not open or grep `src/`, `tests/`, `docs/`, `scripts/` or `score.py`; did not run repo-ai. The corpus
was produced by a generator script the author wrote that reads only the catalog and stacks files.

**Counts:** 60 tasks; 20 with empty `gold`; 13 with a non-empty `forbidden` (t03, t12, t16, t21, t22, t28, t31, t34,
t41, t44, t47, t56, t60); 6 tasks per stack (ts-react-frontend 7, java-spring 5); every capability is gold 2–6 times.

**Judgement calls (the author's words, condensed):** for network constraints only `adapter.dependency-audit` was
forbidden, as the one the catalog plainly marks as needing the network; `adapter.semgrep`, `ext.browser-evidence` and
`repo-ai.skills-vet` were not forbidden on network grounds, except t34, where "no new installs" plus "no network at
all" rule out Semgrep. "Don't execute anything" tasks forbid the tools that execute something (Semgrep, the dependency
audit, mutation testing, the browser) as each task's wording requires. Traps: t41 (an offline Cargo.lock advisory check:
`gold` empty, dependency audit forbidden) and t53 (vetting a local plugin folder offline: `repo-ai.skills-vet` gold).
