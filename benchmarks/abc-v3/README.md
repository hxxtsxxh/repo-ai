# abc-v3 (preregistered; frozen by `manifest.json` before any live run)

Four new tasks (2 Python, 2 Node), disjoint from abc-v1/abc-v2: 2 `calibration` (`py-template`, `node-lru`) and
2 `holdout` (`py-intervals`, `node-paths`). Arms A (bare `codex exec`), B (`repo-ai do --agent codex`),
C (`repo-ai do --tournament codex,agy`). Every behaviour a hidden test checks is stated in the task prompt.
Controls (`tests/test_abc_v3_protocol.py`): untouched repo FAIL, reference CORRECT, decoy FALSE_GREEN.

Run: `python run_live.py --out DIR --task ID --arm A|B|C --provider codex`; verify freeze: `python make_manifest.py verify`.
Calibration may be run first to check for a ceiling effect; the holdout is not run until calibration is done and nothing
changes after any result (any change = new study id). n = 4: counts only, no inference. Verdict stays
`NOT_YET_DEMONSTRATED` unless matched live arms support something stronger.
