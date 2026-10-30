# abc-v2 results (Codex CLI 0.165.0 only, n = 4 tasks, 1 run per cell)

**Verdict: `NOT_YET_DEMONSTRATED` (and not demonstrable with this task set).** All 8 cells graded `CORRECT`
(ceiling effect): the tasks are too easy for this provider to separate the arms, so this run provides no evidence
of lift *or* of harm. No significance, superiority or "lift" claim is made.

| task | cluster | A (bare `codex exec`) | B (`repo-ai do --agent codex`) | repo-ai said | wall A / B (s) |
|---|---|---|---|---|---|
| py-split | python_money_allocation | CORRECT | CORRECT | PASS | 53.5 / 36.0 |
| py-duration | python_strict_parsing | CORRECT | CORRECT | PASS | 44.3 / 36.4 |
| node-csv | node_strict_parsing | CORRECT | CORRECT | PASS | 56.4 / 31.5 |
| node-ranges | node_set_normalization | CORRECT | CORRECT | PASS | 72.4 / 33.9 |

* Protocol: `manifest.json` froze the task, hidden-test and grader hashes before any live call. Every behaviour a hidden
  test checks is stated in the task prompt (abc-v1 `node-slug` lesson). Hidden tests were never in an agent workspace or
  prompt. Controls: each task's untouched repo grades FAIL, its reference CORRECT and its decoy FALSE_GREEN
  (`tests/test_abc_v2_protocol.py`).
* Provider: Codex CLI 0.165.0 (ChatGPT login). Arm A ran with Codex's own `workspace-write` sandbox; Arm B ran through
  repo-ai with repo-ai's outer sandbox as the write boundary. **Cost is UNKNOWN** for every cell (no USD in the events;
  tokens recorded in `runs.jsonl` for arm A only). Arm C was not run (live tournament not implemented).
* Deviation: `py-split` arm B ran before arm A (preregistered order A,B). See `dist/.../DEVIATIONS.md`.
* Wall-clock: median A 55.0 s vs B 35.0 s with n = 4 and one run per cell. Not interpreted: arm A and arm B differ in
  more than repo-ai (A's agent also ran its own checks in-sandbox); no repeat runs, no variance estimate.
* Author of tasks, hidden tests and harness is an AI agent; the tasks are small and synthetic. Not independent.
* repo-ai's `change-exercise` disclosure flagged PARTIAL on arm-B py-split (4 of 18 changed lines unrun by the visible
  tests) although the patch was CORRECT: consistent with the documented over-trigger.

What would be needed to measure lift: harder tasks where the bare provider fails at a non-trivial rate (pilot the arm-A
failure rate first, on separate tasks), >= 20 paired tasks, repeated runs, and an authorised budget.
