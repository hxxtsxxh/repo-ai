# abc-v5 amendments

Protocol version 1 is frozen in `manifest.w.json` and `manifest.json`. These entries are **proposed** for the
confirmatory W freeze. They were motivated by the calibration run of 2026-10-29 and have not yet been applied to any
confirmatory material, because none exists.

1. **(proposed) F writes one follow-up file per requirement**, named `followup/R<k>.*`. In calibration, `run_offline.py`
   had to split a shared file into per-test blocks to select one requirement's tests. Per-requirement files make that
   selection trivial and remove the risk that undirected tests leak into B+.
2. **(proposed) Report a second actionability measure.** "B named the violated requirement" (2 of 4 semantic catches
   in calibration) is reported next to the current measure. The current denominator counts process controls that were
   refused without naming any requirement, which understates actionability. Process refusals carry their own reason
   string, which is reported instead.
3. **(proposed) Make B+ laundering a named secondary endpoint.** It is the share of decoys that B did not accept but
   B+ accepted. Calibration had 2. This is the cost of turning an accidental task-level abstention into an acceptance.
4. **(proposed) Pre-register the case where no decision rule is affected.** A follow-up test that passes at baseline
   for a `change` requirement stays `NOT_DISCRIMINATING` under B+. This is reported as such, not treated as a harness
   failure.
