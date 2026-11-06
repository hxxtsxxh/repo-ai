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

## Amendment 2 (2026-11-04, before any Node probe was run or any Node candidate diff was read)

The two Node abstentions (`cal-node-roman`, comparison `62fd53c2…`; `cal-node-chunk`, comparison `2dabef0b…`) are
added now that `--probe` takes JavaScript (#137). Same method as amendment 1: the recorded Codex and Claude diffs are
re-submitted as replay proposals in a fresh clone of each frozen task repository (`--test-command "node --test"`),
then the probes `probes/cal-node-roman.js` and `probes/cal-node-chunk.js`, committed with this amendment and written
from the prompts alone, run through `shortlist --probe` with repo-ai built from the #137 branch (or the release that
contains it). Same reporting and classification rules.

## Results of amendment 2 (2026-11-04, repo-ai from the #137 branch, no model call, $0)

Raw records: `results/probe-node-2026-11-04.jsonl`. Both replay re-submissions reproduced the live outcome (two PASS
arms, abstained).

| Task | Probe | Lines | Lines where the candidates differ from the base | Codex vs Claude |
|---|---|---|---|---|
| cal-node-roman | SAME | 60 (including a 1..3999 round trip: 3999 ok) | 37 | identical output and exit status |
| cal-node-chunk | SAME | 30 (including input-unchanged and new-array checks) | 18 | identical output and exit status |

**What this shows.** The live comparison classified both Node pairs as SUBSTANTIVE (their code differs), and the
probes found no behavioural difference on the spec's edge cases and the inputs just outside it, while both candidates
clearly differ from the buggy base. SAME is not equivalence: other inputs could still separate them.

**All four abstentions together:** the probes separated the two Python pairs, each on exactly one input outside the
prompt (non-ASCII digits; int vs float), and found the two Node pairs behaving identically on everything they asked.
In every case the probe's answer agreed with the hidden oracle's CORRECT for all eight candidates. Same caveats:
four tasks, one provider pair, probes written by the feature's author.

## Amendment 3 (2026-11-06, before any run of these probes): independent probe authors

C12's next action is "independent probe authors". The probes above were written by the person who built the feature
and ran the study. Four new probes, `probes-independent/`, were written by a separate agent instance that saw only
each task's statement (`task.json`) and starting repository (`repo/`), copied into a scratch folder; it was given no
candidate, no earlier probe and no result, and reported opening nothing outside that folder. It is not a human author
(the study does not claim one). sha256:

```
e17b475488f0e6afb17cc99c5e94889f6f8bd9293ee18c93d1a819ae10481d9c  cal-node-chunk.js
c4c0bb85ec5cde6b2f000b12975487e7bfdcf223ebffe128571747e9989a5bb6  cal-node-roman.js
5c3f3c67eadc1f88fc9fec5bdd2b7225f8bec719f1df92505b0405fa47c32dbd  cal-py-backoff.py
fe21ae5d0358a3e0da4bb66ecb876081f7469a1a74f7c3fcbf2170f689402d78  cal-py-sizes.py
```

**Run:** the same replay re-submission as amendments 1 and 2 (each task's two recorded candidate diffs applied to a fresh
clone of its frozen repository and submitted as explicit replay proposals, no model call), now under repo-ai 0.12.8
from PyPI, then `shortlist --probe probes-independent/<task>.<py|js>`. The original probes are also re-run in the same
comparisons so both sets are compared on identical candidates. Reported per task: each probe set's verdict and every
differing line, classified as inside or outside the spec as before, and whether the independent probe finds the same
difference, a different one, or none. A refusal or an INCONCLUSIVE is reported as such. $0.


## Results of amendment 3 (2026-11-06, repo-ai 0.12.8 from PyPI, no model call, $0)

Raw records: `results/probe-independent-2026-11-06.jsonl` (each replay comparison's and each `shortlist --probe`
run's full output, home paths shortened to `~`). Work directory: `~/.cache/repo-ai-studies/c12-amendment3/`.

**Replay.** For each task, the Codex and Claude diffs from the live mission records were applied to a fresh clone
of the frozen repository (`frozen base` commit) and submitted as two replay proposals:
`repo-ai do PROMPT --agent replay --candidate codex.json --candidate claude.json --allow-write FILE --run
--max-cost-usd 0 --test-command TEST_COMMAND --json`. All four comparisons reproduced the live outcome: two PASS
arms, abstained (verdict INCONCLUSIVE, no winner). The replayed diffs have the same sha256 as the live diffs.
Comparisons: cal-py-backoff `85367c81…`, cal-py-sizes `3c9d770d…`, cal-node-roman `671b1ce1…`, cal-node-chunk
`f8183dd7…`.

**Probes.** Before each run, each probe's sha256 was checked against this file: amendment 3 for the independent
set, and the amendment 1 prefixes and the 2026-11-04 records for the original set. Both sets ran unchanged. Every
run exited 0, no stderr, no `shortlist` refusal, no INCONCLUSIVE. The original probes reproduced the 2026-11-04
outputs byte for byte (all eight candidate stdouts and all four base stdouts). One recording limit: in the
independent cal-py-backoff run, repo-ai capped the recorded stdout of the base and of Claude's candidate at 4,000
characters (`stdout_truncated: true`). Every difference listed below falls inside the recorded text (Claude's line
55 is cut after `type=list len=400`, which already shows a list where Codex raised).

### cal-py-backoff

| Probe set | Verdict | Lines | Line | Input | Codex | Claude | Spec | Independent vs original |
|---|---|---|---|---|---|---|---|---|
| original | DIFFER | 24 | 23 | `delays(2, base=3, cap=3)` | `[3.0, 3]` | `[3, 3]` | outside (see a) | n/a |
| independent | DIFFER | 55 | 12 | `delays(3, 0.5, 2, 1)` | `[0.5, 1.0, 1]` | `[0.5, 1, 1]` | outside (see a) | **same** difference, on another input |
| | | | 54 | `delays(1100)` (defaults) | `OverflowError` | a list of 1100, ending `60.0` | **inside, by my reading** (see b) | **different**: the original probe does not find it |
| | | | 55 | `delays(400, 1.0, 10.0, 1e9)` | `OverflowError` | a list of 400 | **inside, by my reading** (see b) | **different** |

(a) The values are equal; only the number type differs, at the point where a delay equals the cap. Codex's
`min(base * factor ** i, cap)` returns the first argument, the float. Claude's loop stores `cap` itself. The prompt
asks for "a list of numbers".
(b) R1 defines every delay as the value `min(base * factor ** i, cap)`, which is the cap here. R2, R3 and R5 name
the only errors, and the result is a list. Codex's candidate raises `OverflowError`: the float power
`base * factor ** i` overflows once it exceeds about 1e308 (i ≥ 1024 with the defaults). Claude's stops computing
powers once the cap is reached. Read this way, Codex's candidate is wrong on an input the prompt covers, and that
contradicts the hidden oracle's CORRECT; the oracle never tests that many attempts. Caveat: Codex's code is R1's
expression verbatim, and Python's float arithmetic overflows on that expression itself. If R1 is read as Python
code rather than as arithmetic, the difference falls outside the spec.

### cal-py-sizes

| Probe set | Verdict | Lines | Line | Input | Codex | Claude | Spec | Independent vs original |
|---|---|---|---|---|---|---|---|---|
| original | DIFFER | 45 | 32 | `parse_size('١٠')` (Arabic-Indic digits) | `10` | `ValueError` | outside (see c) | n/a |
| independent | DIFFER | 103 | 87 | `'١٠KB'` (Arabic-Indic) | `10000` | `ValueError` | outside (see c) | **same** difference |
| | | | 88 | `'１０KB'` (fullwidth digits) | `10000` | `ValueError` | outside (see c) | **same** difference, another script |
| | | | 90 | `'١.٥KiB'` (Arabic-Indic, fractional) | `1536` | `ValueError` | outside (see c) | **same** difference, fractional form |

(c) The prompt says "digits" and requires only the separating space to be ASCII. Codex's pattern uses `\d`
(any Unicode decimal digit) and Claude's uses `[0-9]`. Both reject `'²KB'` (superscript), `'1ＫB'` (fullwidth unit) and
`'10İB'`.

### cal-node-roman

| Probe set | Verdict | Lines | Lines where the candidates differ from the base | Differing lines | Independent vs original |
|---|---|---|---|---|---|
| original | SAME | 60 | 37 | none | n/a |
| independent | SAME | 99 | 68 | none | **none** found by either |

### cal-node-chunk

| Probe set | Verdict | Lines | Lines where the candidates differ from the base | Differing lines | Independent vs original |
|---|---|---|---|---|---|
| original | SAME | 30 | 18 | none | n/a |
| independent | SAME | 49 | 39 | none | **none** found by either |

**What this shows.** The independent author, who saw only the prompt and the starting repository, reached the
same verdict as the original probes on all four tasks: DIFFER, DIFFER, SAME, SAME. On both Python tasks it found
the difference the original probe had found (int vs float at the cap; non-ASCII digits), each time on inputs of its
own. On cal-py-backoff it also found a second difference that the original probe missed. Codex's candidate raises
`OverflowError` for a long schedule (`delays(1100)`), while Claude's returns the list. By my reading of the prompt
this input is inside the spec, so it is the first probe result that disagrees with the hidden oracle's CORRECT for
one of the eight candidates (with the caveat in (b)). It changes no tournament verdict or grade. On the Node tasks,
two probes from two authors (98 and 79 lines in all) found no behavioural difference. That is still not proof of
equivalence. Caveats: four synthetic calibration tasks and one provider pair. The independent author is a separate
agent instance, not a human. The inside/outside classification is a judgement made from the prompt by the agent
instance that ran this step (not the independent author); (b) is the one to check.
