# handoff-demo-2: Codex -> agy partial-work handoff (n = 1, constructed)

Scenario authored this session (`repo/`, see README.md). Both providers LIVE via repo-ai's mission path; cost UNKNOWN
(subscription) for both. Commands: `repo-ai do PROMPT --agent codex --allow-write textutil.py --run --allow-live-provider`,
`repo-ai handoff A --to agy`, `repo-ai do --from-handoff capsule.json --agent agy --run --allow-live-provider`.

| step | result |
|---|---|
| A (Codex, 27 s) | INCONCLUSIVE / FAIL: baseline 6 failing -> 3 failing (the 3 `wrap_words` tests fixed, 3 `render_table` tests still failing), no regressions |
| handoff | `recovery_category: partial_progress`, target agy; capsule carries the validated diff (sha256 `c25137c5...`) and the 3 still-failing tests |
| B (agy, 26 s) | INCONCLUSIVE / FAIL; `partial_patch_transferred: true`, `continuation_kind: partial_diff_reverified_from_same_frozen_source` |

Honest reading:
- Validated partial work **did** cross providers and was re-verified in a fresh checkout (the seed's fixed/still-failing sets match).
- agy **kept** the seed unchanged: its final diff is byte-identical to Codex's. It did not improve on it.
- The mission did **not** complete, and this is correct: the request and write scope (`textutil.py`) never covered the
  `render_table` tests, so no provider was permitted to fix them. The scenario was designed to leave work outstanding; it
  does not show that the second provider can finish what the first could not.
- A control (Codex alone, `--allow-write` for both files, no handoff) still edited only `textutil.py`, because the prompt names only `wrap_words`; also INCONCLUSIVE. It
  shows nothing about handoff benefit and is kept only for completeness (`control-A.json`).

Not shown: that a handoff completes tasks faster or cheaper than a restart (no restart arm, n = 1, cost UNKNOWN).
Raw JSON: `dist/reality-engine/handoff-live-2/` (ignored).
