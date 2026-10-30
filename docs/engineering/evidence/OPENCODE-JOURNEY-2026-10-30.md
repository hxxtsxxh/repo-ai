# OpenCode with a local model through repo-ai: live journeys, 2026-10-30

Build: wheel of `provider/opencode` (`5196384`, with the 256 KB capture), installed non-editable in a clean venv.
Host: macOS Darwin 25.5 arm64 (36 GB RAM), seatbelt. OpenCode 2.2.1, Ollama 0.40.12 serving `qwen3:8b` on
loopback; `REPO_AI_OPENCODE_MODEL=qwen3:8b`. Cost $0 (local model; no account, no network beyond loopback).
Synthetic tasks, single author, hidden oracles kept outside the repositories. Every attempt is listed.

| # | Task | Result | Notes |
|---|---|---|---|
| 1 | `parse_duration` (seconds, unknown units, empty, leftover characters) on build `e0cfa0a` | **INCONCLUSIVE — BLOCKED [LIVE_FAILED]**, 678 s | stream exceeded the then 64 KB capture (`output_limit`); fixed in `5196384` |
| 1-raw | same task, OpenCode alone (no repo-ai), for diagnosis | 765 s; 25 of 28 `edit` calls failed (`oldString` mismatch); final patch passes the 3 visible tests but the **hidden oracle 12/17** (accepts `abc`, `1.5h`, leftover characters) | exactly the false assurance `coverage` names: "leftover characters" has no test |
| 2 | `parse_duration` again on `5196384` | **INCONCLUSIVE — mission deadline reached** (900 s) | the 8B model is too slow for this task inside the default budget |
| 3 | `clamp` ("Implement clamp as its docstring says") | **INCONCLUSIVE [LIVE_FAILED]**, 71 s | the model spliced a new function into the old signature (syntax error); repo-ai refused. Its recovery hint said "environment", which is wrong (queued) |
| 4 | `clamp` ("Implement the body … Keep the signature.") | **PASS `LIVE_CANDIDATE_VERIFIED`**, 161 s, mission `fd041944…` | hidden oracle **9/9** (incl. `lo > hi` → ValueError); apply then undo restored the file byte-for-byte |

No `opencode` process remained after any run (`pgrep -x opencode`).

## What this shows

- The account-free path works end to end: a small local model produced a real, independently verified change
  inside repo-ai's loopback-only sandbox.
- A small local model is weak at this: 1 pass in 4 attempts. In every failure repo-ai refused to report success,
  and the one patch that passed only the visible tests (attempt 1-raw, outside repo-ai) fails 5 of 17 hidden cases.
  This is a demonstration of the verifier's honesty, not of the model's quality.
