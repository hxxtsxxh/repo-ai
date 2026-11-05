# abc-v4 pilot results (Codex CLI arm A only; n = 2 tasks, 1 run each)

**Verdict: `NOT_YET_DEMONSTRATED`.** The pilot's question was whether the bare provider fails tasks with longer, more exact
specifications. It did not: arm A (`codex exec`, no repo-ai) graded `CORRECT` on both tasks, so per the preregistered
PILOT RULE arms B and C are `NOT_RUN` (a ceiling cell cannot show lift). No claim of lift or harm.

| task | split | A (bare codex) | B | C | wall A (s) |
|---|---|---|---|---|---|
| py-semver | calibration | CORRECT | NOT_RUN (ceiling) | NOT_RUN (ceiling) | 50 |
| node-duration | holdout | CORRECT | NOT_RUN (ceiling) | NOT_RUN (ceiling) | 77 |

Protocol: `manifest.json` froze tasks/hidden/grader hashes and the pilot rule before the first live call; `make_manifest.py verify`
still passes. Controls (`tests/test_abc_v4_protocol.py`): untouched repo FAIL, reference CORRECT, decoy FALSE_GREEN. While drafting,
the controls and a review of my own reference caught two defects, both fixed before the freeze: a first Python task reused an
abc-v2 cluster (replaced by `py-semver`), and the reference regex accepted a trailing newline (`$` vs `\Z`).

Limits: n = 2, one run each, no variance. Cost UNKNOWN (Codex subscription; not $0). Tasks, tests and grader were written by an AI
agent; the tasks are small and synthetic. Four studies (abc-v1..v4) now show the same thing for a strong provider on small,
fully-specified tasks: arm A is already at the ceiling, so these designs cannot measure lift. What would: tasks where the bare
provider fails at a non-trivial rate (for example real, larger-repository issues with an under-specified prompt), >= 20 paired tasks,
repeats, and an authorised budget. That is a new study id, not a change to this one.

Observation: in both arm A cells the bare agent also edited the visible test file (outside `write_paths`). The grader ignores such
edits and graded only `semver.py` / `duration.js` against the original visible tests plus the hidden tests, so the CORRECT grades
do not depend on them. Run record: ignored `dist/reality-engine/abc-v4-live/runs.jsonl`.

Deviation (post-run, disclosed): after the arm A runs, a lint gate (`ruff B905`) flagged `zip()` without `strict=` in
`tasks/py-semver/reference/semver.py`. That file is a free control: it is not shown to any agent and was not used in any live run
(arm A sees only `repo/`, the grader uses only `hidden/`). I changed it to `zip(..., strict=False)` (identical behaviour) and
re-wrote `manifest.json`, which changes the manifest hash of that one file. Nothing else under `tasks/` or `grade.py` changed; the
`repo/` and `hidden/` hashes that the live cells depended on are unchanged (`git diff 6c8b362 -- benchmarks/abc-v4/tasks/*/{repo,hidden}` is empty).
