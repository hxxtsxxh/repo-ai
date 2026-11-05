# ProofLab demonstrations, 2026-10-24

Produced by `benchmarks/prooflab/demo.py`:
- **Host:** macOS, seatbelt sandbox.
- **Toolchain:** Python 3.12.14, node v24.19.0.
- **CLI:** repo-ai 0.7.7, the development source of `prove/prooflab-mvp`.
- **Cases:** two real upstream fixes, cloned at pinned commits:
  - python-json-pointer `f15abac` → `16c4c8e` (BSD-3-Clause);
  - ipaddr.js `40708ee` → `74ee4c5` (MIT).

The script fixes every control's expected verdict before anything runs.

**These are demonstrations, not a held-out evaluation.** A scout picked the cases, after checking that
each upstream test fails at the parent and passes at the fix. Neither project appears in a
`benchmarks/verify-eval` corpus.

| Run | ProofLab code | Controls as expected | False proofs | Note |
|---|---|---|---|---|
| 1 (`summary-run1.json`) | before the security review | 16 of 18 | 0 | **The `hidden` control is not valid evidence.** Its list of broken tests came from a regression check that had been skipped, so it skipped nothing, and verify found the regression on its own. |
| 2 (`summary-run2.json`) | + `separate-breakage`, declared after run 1; `hidden` takes its list from it | 18 of 20 | 0 | In `hidden`, `verify --run` alone passes (exit 0); ProofLab names the broken tests |
| 3 (`summary-run3.json`) | + security fixes, the evidence contract, expected levels declared before the run | 18 of 20 | 0 | levels as declared |
| 4 (`summary-run4.json`, `run4/`) | final (`6f32e62`): false-proof review fixes | 18 of 20 | 0 | identical verdicts and levels to run 3 |
| 5 (`summary-run5-installed-wheel.json`) | the same code, **built as a wheel and installed in a fresh virtualenv**; the demo drives that `repo-ai` | 18 of 20 | 0 | identical to run 4. The wheel was built twice from `git archive`, with byte-identical results |
| 6 (`summary-run6-integrated.json`) | the integrated tree (`00d124f`): ProofLab plus #39–#43, Session A's verify fixes for D1–D9 included | 18 of 20 | 0 | identical verdicts and levels |
| 7 (`summary-run7-contract-1-1.json`) | contract 1.1 (2026-10-25): the control is a side (2 runs), repeats sequential per side, Session A's F1-F5 fixed | 18 of 20 | 0 | identical verdicts and levels; a hang now costs two sequential time-outs (about 42 s) |
| 8 (`summary-run8-subject.json`) | the candidate side runs on the base plus only the code under test; the `separate-*` pins declare it with `--subject` (the upstream fix's source files), as a reviewer would | 18 of 20 | 0 | identical verdicts and levels |
| 9 (`summary-run9-subject-suite.json`) | the subject-only check (the full suite on the base and on the base plus the code under test) replaces the edited-tests mapping | 18 of 20 | 0 | identical verdicts and levels |
| 10 (`summary-run10-final-wheel.json`) | the final integrated tree (ProofLab plus #39-#51), **built as a wheel** (two byte-identical builds, sha256 `5db829b3…`) and installed in a fresh virtualenv | 18 of 20 | 0 | identical verdicts and levels |

**The two mismatches in every run** are `breakage` on both projects. It was expected to be
`regressions-detected` and was observed as `candidate-failed`.
- **Why:** upstream keeps the related tests in the same file as the new test. The pinned scenario is that
  whole file, so the breakage fails the scenario itself.
- **Effect:** the claim is still not established, by another route.

`run4/<case>/<control>.md` and `.json` are the exported passports. The `fix` controls have the evidence
level `behavior_observed`: their scenario is the fix commit's own test, so it is part of the change.
The `separate-fix` controls have `supported_by_controlled_comparison`: the same test, kept outside the
repository and pinned with `--file`.
