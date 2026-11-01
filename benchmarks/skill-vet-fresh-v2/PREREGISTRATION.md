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
