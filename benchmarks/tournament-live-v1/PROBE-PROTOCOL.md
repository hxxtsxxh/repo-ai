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

## Amendment 1 (before any probe output; after the refusal)

**Observed:** `shortlist` refused both comparisons: "candidate evidence is stale: mission kernel changed since the
recorded experiment; baseline environment: repo-ai version changed (0.12.1 -> 0.12.3)". That is repo-ai's freshness
rule working as designed, and it is a finding in itself: a probe cannot be run on a tournament recorded by an older
repo-ai version.

**Added step, labelled separately (not a re-grading of the live run):** for each of the two tasks, the two recorded
candidate diffs (read from the mission records; byte-for-byte the diffs Codex and Claude produced) are applied to a
fresh clone of the task's frozen repository to obtain each candidate's file contents, then submitted as two explicit
replay proposals (`repo-ai do TASK --agent replay --candidate A --candidate B --run`) under repo-ai 0.12.3: no model
call, $0. If that comparison abstains with both PASS, the same committed probes (unchanged; sha256 `48f17ca910d7…`,
`1bdb02d886ac…`) run through `shortlist --probe`. Every other rule above is unchanged.

## Results (2026-11-04, repo-ai 0.12.3 from PyPI, no model call, $0)

Raw records: `results/probe-2026-11-04.jsonl` (every probe output in full).

1. **On the recorded comparisons: refused.** `shortlist` declined both as stale (repo-ai 0.12.1 → 0.12.3), so no
   probe ran. Correct under the freshness rule, and a real limit: a probe only runs on a tournament recorded by the
   same repo-ai version (the tournaments page now says so).
2. **After the replay re-submission (amendment 1):** both comparisons reproduced the live outcome (two PASS arms,
   abstained). The committed probes ran unchanged:

| Task | Probe | Differing line(s) | Codex | Claude | Classification |
|---|---|---|---|---|---|
| cal-py-backoff | DIFFER (1 of 24 lines) | `delays(2, base=3, cap=3)` | `[3.0, 3]` | `[3, 3]` | outside the spec: equal values (3.0 == 3); only the number type differs, and the prompt asks for "a list of numbers" (Codex's follows the literal `min(base * factor ** i, cap)`, which keeps the float) |
| cal-py-sizes | DIFFER (1 of 45 lines) | `parse_size('١٠')` (Arabic-Indic digits) | `10` | `ValueError` | outside the spec: the prompt says "digits" and only requires the separating space to be ASCII; accepting non-ASCII decimal digits is a real behavioural difference in an input parser, invisible to the frozen tests and to the hidden oracle |

**What this shows.** On two real abstentions between two correct candidates (by the hidden oracle), a short
predeclared probe written from the prompt found, in each, the one place where they behave differently, and named it
on its first line, with no model call. Neither difference contradicts the oracle (both are outside the prompt). The
probe does not choose: whether a size parser should accept non-ASCII digits is the developer's call. Small sample
(two tasks, one pair of providers, probes by the same person who built the feature); the Node abstentions were out
of scope.
