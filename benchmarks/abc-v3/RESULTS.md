# abc-v3 results (Codex CLI for arms A/B; Codex + agy for arm C; n = 4 tasks, 1 run per cell)

**Verdict: `NOT_YET_DEMONSTRATED`.** Again a ceiling effect: arms A (bare `codex exec`) and B (`repo-ai do --agent codex`)
graded `CORRECT` on all 4 tasks, so nothing separates them. No claim of lift or harm.

| task | split | A | B | C (tournament codex+agy) | wall A / B / C (s) |
|---|---|---|---|---|---|
| node-lru | calibration | CORRECT | CORRECT | ABSTAIN | 118 / 64 / 97 |
| py-template | calibration | CORRECT | CORRECT | ABSTAIN | 79 / 54 / 87 |
| node-paths | **holdout** | CORRECT | CORRECT | ABSTAIN | 91 / 41 / 78 |
| py-intervals | **holdout** | CORRECT | CORRECT | ABSTAIN | 54 / 44 / 78 |

Arm C finding (the only new information here): on every valid cell **both** providers produced a passing candidate with a
*different* diff, and the predeclared rule has no objective tie-breaker, so repo-ai abstained 4/4. Both candidates were
plausibly correct (their repo-ai verdicts were PASS), but the per-arm hidden-test grade was not captured (see deviation 3),
so "both were correct" is **not** shown for C. Consequence: with two strong providers on tasks this easy, a tournament costs
roughly double the provider time and returns no patch. It is opt-in and plan-only by default and stays that way. A useful
tie-breaker (for example a differential test between the two candidates) would be a *new* study with a new id, not a change to
this one.

Protocol: `manifest.json` froze task/hidden/grader hashes and the arm order before any live call (`make_manifest.py verify`
still passes). Calibration ran before holdout; nothing about tasks, prompts, hidden tests or grader changed after any result.
Controls (untouched repo FAIL, reference CORRECT, decoy FALSE_GREEN) are in `tests/test_abc_v3_protocol.py`. While drafting,
those controls caught two of my own defects (a decoy that was actually correct, a reference that failed its hidden tests); both
were fixed before the freeze.

Deviations (full text in the ignored `dist/reality-engine/abc-v3-live/DEVIATIONS.md`): (1) the first `node-lru` arm C attempt is
INVALID (runner omitted `--test-command`, so a Node task ran under pytest); fixed and re-run once, invalid record retained and
flagged; (2) the runner was extended after calibration, before the holdout, to also grade each tournament arm; (3) that extra
grading errored on the holdout cells (symlinked temp path) and was fixed afterwards without re-running.

Limits: n = 4, one run each, no variance, no significance test. Cost UNKNOWN for every cell (Codex and agy subscriptions).
Tasks, hidden tests, harness and this write-up were all authored by an AI agent; the tasks are small and synthetic. Run order was
counterbalanced per the manifest seed, but arm A and B differ in more than repo-ai (A's agent can run its own checks).
To measure lift you would need tasks the bare provider fails at a non-trivial rate (pilot arm A first), >= 20 paired tasks,
repeats and an authorised budget.
