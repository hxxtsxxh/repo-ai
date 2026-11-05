# Option A: exploratory reanalysis of the oss-tl-001 exclusions (0.7.6)

**This is exploratory and does not replace the pre-registered result.** The
pre-registered analysis (`coding-option-a-v0.7.5.md`) excluded five oss-tl-001
runs, flagged by the content-match contamination check, and stands as recorded.
The raw evidence in `option-a-v0.7.5/` is unchanged.

**Why reanalyse:**
- The content-match check flagged a workspace file byte-identical to a hidden
  test.
- On oss-tl-001 the hidden test differs from the visible one only in three
  numeric constants, so a correct fix that updates the existing test reproduces
  it exactly.
- 0.7.6 replaces that check with proof of access (`repo_ai.integrity`).

**Evidence for re-admitting each run:**
- The recorded Bash commands of all five runs name no protected path (the suite,
  `_evalsuite`, the lab, `cases/`, `hidden/`).
- The OS sandbox denied those paths throughout.
- **Limitation:** 0.7.5 recorded Read-tool counts but not their paths. The
  check therefore rests on the Bash commands and the sandbox's denial, not on a
  full transcript.

| Run | Tool uses | Protected-path commands | Success |
|---|---|---|---|
| Full, rep 0 | Bash 6, Edit 4, Grep 1 | none | pass |
| Core, rep 0 | Bash 3, Edit 3, Grep 1, Read 3 | none | pass |
| Plain, rep 0 | Bash 1, Edit 3, Grep 1, Read 3 | none | pass |
| Plain, rep 1 | Bash 2, Edit 3, Grep 2, Read 3 | none | pass |
| Core, rep 1 | Bash 3, Edit 3, Glob 1, Grep 3, Read 2 | none | pass |

**Result with those five runs counted as valid** (25 tasks; same task-clustered
method, sign-flip test and Holm correction):

| Comparison | Success | Difference | 95% CI | Holm p | Verdict |
|---|---|---|---|---|---|
| Core vs Plain | 90% vs 92% | −2.0 pts | −15.9 … +12.2 | 1.0 | inconclusive |
| Full vs Plain | 88% vs 92% | −4.0 pts | −19.0 … +11.6 | 1.0 | inconclusive |
| Full vs Core | 88% vs 90% | −2.0 pts | −12.7 … +9.0 | 1.0 | inconclusive |

**Conclusion:** unchanged. No comparison is significant, and the direction
stays slightly negative for repo-ai.
