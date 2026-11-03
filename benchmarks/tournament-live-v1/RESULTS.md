# tournament-live-v1: results (2026-11-03 UTC)

**Protocol.** [PREREGISTRATION.md](PREREGISTRATION.md). Raw records (paths redacted): [results/run-2026-11-03.jsonl](results/run-2026-11-03.jsonl).

**Setup.**
- A clone of main at `a2099be` (0.12.1 plus #118/#119/#121), under HOME.
- Codex CLI 0.165.0 on the owner's personal Codex login; cost UNKNOWN.
- Claude Code 2.1.317 on the dedicated login `claude-provider`, capped at $1.50 per arm.
- macOS seatbelt for the providers and repo-ai's own verification.
- abc-v5's sealed hidden oracle, graded in a podman container without network.

**Preflight.** It passed with no provider started:
- the cap split was `{"claude": 1.5, "codex": 0.0}`;
- both providers were eligible;
- the difference classification was present;
- the grader graded every reference CORRECT and every first semantic decoy FALSE_GREEN.

| Task | Codex arm | Claude arm | Hidden oracle (Codex / Claude) | Difference | Decision | Next step |
|---|---|---|---|---|---|---|
| cal-py-backoff | PASS (25 s) | PASS (23 s, $0.0508) | CORRECT / CORRECT | SUBSTANTIVE: `backoff.py:delays` | abstained | pin the behaviour in `delays` with a test, or `repo-ai shortlist` and choose |
| cal-py-sizes | PASS (35 s) | PASS (25 s, $0.0682) | CORRECT / CORRECT | SUBSTANTIVE: `sizes.py:<module level>`, `parse_size` | abstained | same |
| cal-node-roman | PASS (22 s) | PASS (20 s, $0.0469) | CORRECT / CORRECT | SUBSTANTIVE: `roman.js` | abstained | same |
| cal-node-chunk | PASS (26 s) | PASS (14 s, $0.0369) | CORRECT / CORRECT | SUBSTANTIVE: `chunk.js` | abstained | same |

No candidate was byte-identical to the authored reference (`equals_reference: false` for all eight).

## Gates

| id | Measure | Result |
|---|---|---|
| T1 | arbitrary winners | **0** (no winners) |
| T2 | next steps that do not match the decision | **0** |
| T3 | IDENTICAL or COSMETIC pairs whose oracle grades differ | **0** (no such pairs) |
| T4 | winners graded FALSE_GREEN or FAIL | none (no winners) |
| R1 | SUBSTANTIVE pairs whose oracle grades differ | 0 of 4. Every SUBSTANTIVE pair was CORRECT on both sides: the code differed, but the hidden oracle observed no difference in behaviour |
| R2 | cost | Claude **$0.2028** observed (4 arms); Codex UNKNOWN (4 arms) |

## Reading

All 8 live arms produced candidates that the hidden oracle graded CORRECT. repo-ai never self-certified a winner. In
each case it named where two passing candidates differ in code and pointed the human to the choice or to a pinning
test. On these four tasks the abstentions were costly: every candidate was in fact correct, so a reviewer had to
choose between two correct fixes. That is the documented tie rule (two distinct passing candidates abstain), not an
error. It also shows that "SUBSTANTIVE" means different code, not proven different behaviour; R1 makes that visible.

Four synthetic calibration tasks give no rate. These tasks are calibration-only in abc-v5, and this run does not change
that.
