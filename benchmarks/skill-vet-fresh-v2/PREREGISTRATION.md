# skill-vet-fresh-v2: confirmation after the v1 failure (preregistered)

skill-vet-fresh-v1 failed gate G1: 8 of 30 harmful skills, all prose-only, would have been installed by `SAFE_AUTO`
without asking ([../skill-vet-fresh-v1/RESULTS.md](../skill-vet-fresh-v1/RESULTS.md)). A fix was written with that
corpus in view (`firewall.instruction_risks`). This protocol confirms it on a corpus written afterwards, by a
different author, and was committed before any v2 case existed. Spend: $0.

**Identical to v1** ([../skill-vet-fresh-v1/PREREGISTRATION.md](../skill-vet-fresh-v1/PREREGISTRATION.md)) in
questions, strata and counts, defanging, labels, gates G1–G4, reports R1–R3 and rules, except:

- **System under test:** the commit that adds this file, which contains the fix. Unchanged until the run.
- **Harness:** v1's `run.py`, copied unchanged.
- **Author:** a new agent briefed with v1's corpus section and layouts only. It must not read `src/`, `tests/`, the
  vetting documentation, anything under `benchmarks/skill-vet-fresh-v1/` (corpus, labels, results) or the fix.
- **Extra report R4:** harmful H-text cases caught *only* by an `instruction-risk` finding, and benign cases
  carrying one (the fix's own false alarms).

C08 can leave EXPERIMENTAL only if G1–G4 all pass here. If G1 fails again, the result is recorded and `SAFE_AUTO`
is narrowed further (for example, to skills from an allow-listed publisher only) before any release that ships it.

## Status (2026-10-31): blocked, no corpus

The author agent was stopped by a safety classifier while starting the harmful strata and wrote no case. It was not
retried or reworded, and the content was not given to another agent. The unblock is a corpus written by a person
(or taken from an external, legitimately published benchmark), following the corpus section above, then
`python benchmarks/skill-vet-fresh-v2/run.py` once.

## Status (2026-11-01): still blocked

The owner asked the agent to build the corpus. The agent's briefing of an author was stopped by a safety classifier
(the second stop on this task); following the rule above it was not retried, reworded or handed to another agent,
and the partly launched author wrote nothing. The unblock is unchanged: a person-written corpus, or an external,
legitimately published benchmark, run once on CI (attack-like fixtures are never written on the development host).

## Status (2026-11-02): ready for an independent person (deviations declared before any v2 case exists)

- **Author:** a person, not an agent ([AUTHOR-BRIEF.md](AUTHOR-BRIEF.md)). Eligibility: no prior exposure to repo-ai's
  vetting code, tests, security or skills documentation, changelog, earlier corpora or results; the maintainer is not
  eligible. While writing, the author reads only the brief and public Claude Code documentation. The brief carries
  v1's corpus section (strata, counts, harm kinds, defanging) and the layouts, nothing about v1's outcome or the fix.
- **Delivery:** the layout `run.py` loads (`labels.json` with `{"cases": [...]}`, `corpus/<id>/`), neutral ids,
  `AUTHOR.md` (provenance and prior exposure) and a `MANIFEST.sha256` over all of them, whose own hash the author
  publishes outside the maintainer's control. [validate_corpus.py](validate_corpus.py) checks a delivery on CI
  (`skill-vet-v2` workflow, `validate` job): structure, counts, labels, manifest, defanged hosts in harmful cases
  (`example.com` or `.invalid`, as v1). It never runs the vetter.
- **System under test:** the preregistration said "the commit that adds this file" (`111d519`); the vetter has changed
  since (later security fixes). It is frozen now instead, as the git blobs in [SUT.json](SUT.json) of the vetting
  sources and the harness, recorded at this commit; the run job refuses if any differs (`sut.py --check`).
- **Run:** once, by hand (`skill-vet-v2` workflow, `run` job, `workflow_dispatch`), refused when
  `results/run-1.json` exists. Gates G1–G4 and reports R1–R4 unchanged.

Nothing in this directory was written as a case, and no case will be written by the maintainer's agent.
