# skill-vet-fresh-v2: confirmation after the v1 failure (preregistered)

skill-vet-fresh-v1 failed gate G1: 8 of 30 harmful skills, all prose-only, would have been installed by `SAFE_AUTO`
without asking ([../skill-vet-fresh-v1/RESULTS.md](../skill-vet-fresh-v1/RESULTS.md)). A fix was written with that
corpus in view (`firewall.instruction_risks`). This protocol confirms it on a corpus written afterwards, by a
different author, and was committed before any v2 case existed. Spend: $0.

**Identical to v1** ([../skill-vet-fresh-v1/PREREGISTRATION.md](../skill-vet-fresh-v1/PREREGISTRATION.md)) in
questions, strata and counts, defanging, labels, gates G1–G4, reports R1–R3 and rules, except:

- **System under test:** the preregistration said "the commit that adds this file" (`111d519`); the vetter has changed
  since (later security fixes). It is frozen now instead: [SUT.json](SUT.json) records the git tree of `src/repo_ai`
  (the vetter, `skills vet` and every helper they import), `pyproject.toml`, the harness, the validator and
  [constraints.txt](constraints.txt) (the one runtime dependency pinned). The **freeze commit** is the commit that adds
  `SUT.json`: `1e2041fdd8f68e3ddea7659e3d1b4262c592e5d7`. The maintainer creates `skill-vet-v2/delivery` from it; the
  author's pull request targets that branch. The run is dispatched on a branch cut from the freeze commit with only the delivery added; the run job
  (`sut.py --check FREEZE`) refuses if any frozen object differs or anything but the delivery changed since then.
- **Run:** once, by hand (`skill-vet-v2` workflow, `run` job, `workflow_dispatch` with the freeze commit), refused when
  `results/run-1.json` exists and serialised by a concurrency group; every dispatched run is reported, whatever its
  outcome (the Actions history lists them). A delivery pull request may change only the delivery's paths (checked).
  Gates G1–G4 and reports R1–R4 unchanged.

Nothing in this directory was written as a case, and no case will be written by the maintainer's agent.
