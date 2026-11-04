# tournament-live-v1: `shortlist --probe` on the recorded abstentions (C12, mission 5B)

Declared before any probe was run and before any candidate diff was read (this file and `probes/` are committed
first; the run follows in a later commit).

**What.** The two Python abstentions of the 2026-11-03 run (`cal-py-backoff`, comparison `54a590ab…`;
`cal-py-sizes`, comparison `074f52eb…`): each had two distinct candidates (Codex, Claude) that passed the frozen
tests and were graded CORRECT by the hidden oracle. The two Node abstentions are out of scope (a probe runs Python).

**How.** repo-ai 0.12.3 from PyPI, `repo-ai shortlist ID --probe probes/<task>.py --json` in each task's recorded
work repository (`~/.cache/repo-ai-studies/tournament-live-v1-work/<task>/repo`). No model call, $0. Each probe was
written from the task prompt alone: spec edge cases plus inputs just outside the spec, printing the result's repr or
the exception class.

**What is reported.** The probe verdict (SAME / DIFFER / INCONCLUSIVE), and for DIFFER every differing line, each
classified by hand afterwards as *inside the spec* (the prompt determines the answer: one candidate would then be
wrong, contradicting the oracle) or *outside the spec* (the prompt does not determine it). No result changes the
original tournament verdicts or grades. A refusal by `shortlist` (for example stale evidence after the 0.12.1 to
0.12.3 upgrade) is reported as such, not worked around.
