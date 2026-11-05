# tournament-demo: first real two-provider tournament (n = 1)

Task `py-limiter` (fresh, authored this session; not in abc-v1/abc-v2). Visible tests: 4 (one is the
window-boundary burst). Hidden tests (`hidden/`, never in any workspace or prompt): exact sliding-window expiry,
denied calls do not consume capacity, `pending()` semantics, bounded memory, constructor validation.
Reference solution and original code self-checked: original fails 3 (incl. 2 hidden), reference passes 9/9.

Command (plan first, then `--run`):

    repo-ai do "<task.json prompt>" --tournament codex,agy --allow-write limiter.py --max-seconds 900 --run --allow-live-provider --json

| arm | provider | repo-ai verdict | visible+hidden when graded outside | diff | cost | wall |
|---|---|---|---|---|---|---|
| 0 | Codex CLI (subscription) | PASS, `LIVE_CANDIDATE_VERIFIED` | 9/9 | 12 changed lines | UNKNOWN | 42 s |
| 1 | agy / Antigravity (subscription) | PASS, `LIVE_CANDIDATE_VERIFIED` | 9/9 | 25 changed lines | UNKNOWN | 33 s |

**Tournament outcome: `INCONCLUSIVE`, winner `null` (abstained).** Both arms were independently generated from one
frozen commit in separate checkouts and processes, both passed the frozen tests, and their diffs are different.
The predeclared rule has no objective tie-breaker (no LLM vote, no blending, no "smaller diff wins"), so repo-ai
refuses to pick. Each candidate remains individually applicable: `repo-ai apply <candidate-mission-id>`.
Both are also correct against the hidden tests, so this is a case where abstaining cost the user a choice, not
a bad patch. That is a deliberate trade, not a failure, and it is n = 1.

What this does **not** show: that a tournament beats a single agent (here a single agent would also have been
right), that either provider is better, or anything about cost (UNKNOWN for both; subscription).
Negative controls (a plausible wrong arm that loses, a crashing arm, a test-rewriting arm, a no-op arm,
identical diffs, a self-declared "I am the winner" message) are offline with fake provider executables in
`tests/test_live_tournament.py`; they are not live model evidence.

Raw record: `dist/reality-engine/tournament-live-20261029/` (ignored).
