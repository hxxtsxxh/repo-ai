# abc-v4 (PILOT; preregistered; frozen by `manifest.json` before any live run)

Two new tasks, disjoint from abc-v1/v2/v3 by id, cluster and reference bytes: `py-semver` (calibration, Python, semver
precedence) and `node-duration` (holdout, Node, strict duration parsing). abc-v3 hit a ceiling (arms A and B both
CORRECT on 4/4), so this is a pilot with one question: **does the bare provider (arm A) fail tasks with longer, more
exact specifications at all?** If arm A is CORRECT on a task there is nothing for repo-ai to improve there, and arms B/C
are NOT_RUN on it (see `PILOT RULE` in the manifest). Every behaviour a hidden test checks is stated in the prompt.

Free offline controls (`tests/test_abc_v4_protocol.py`): untouched repo FAIL, reference CORRECT, decoy FALSE_GREEN,
candidate cannot win by editing tests, hidden tests never in the agent workspace or prompt, manifest hashes match.

Status: **no live run has been made.** Spend and subscription use are not authorised by this document. Run with
`python run_live.py --out DIR --task ID --arm A|B|C --provider codex`; verify the freeze with `python make_manifest.py verify`.
n = 2: descriptive counts only. Verdict stays `NOT_YET_DEMONSTRATED`. The tasks, hidden tests and grader were written by
an AI agent; the decoys are plausible-wrong by construction, not sampled from real model failures.
