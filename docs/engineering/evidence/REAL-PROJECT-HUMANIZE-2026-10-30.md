# Second real project: python-humanize, a real upstream defect, 2026-10-30

Owner approval (2026-10-30 ≈19:30Z): run python-humanize's tests through repo-ai's sandbox (`verify --run`, missions),
plus live provider fixes from the second live budget.

## Task

- Repository: `python-humanize/humanize` (MIT), cloned. The defect is real and fixed upstream in `ca892b3`, "Fix
  `intword()` rounding carry for very large numbers (#346)": `intword(10**24 - 1)` rendered `1000.0 sextillion`
  instead of `1.0 septillion`.
- Task commit `41ec804` = the fix's parent plus three things, all disclosed here:
  - upstream's regression test from `ca892b3` (`tests/test_number.py::test_intword_rounding_rollover`);
  - `pythonpath = ["src"]` in `[tool.pytest]`, so the uninstalled src layout imports;
  - a tracked stub `src/humanize/_version.py`. hatch-vcs generates that file at build time, and the project's
    `.gitignore` matches it.
- Test environment: an untracked `.venv` with pytest 9.2.0, freezegun 1.5.5 and pytest-codspeed 5.0.3, from the
  `tests` extra. `test_benchmarks.py` names pytest-codspeed; the extra also lists pytest-benchmark and pytest-cov,
  which were left out. humanize itself was not installed.
  - With pytest-benchmark instead of pytest-codspeed, 15 benchmark tests error at setup (`'Function' object has no
    attribute '_nodeid'`, a plugin incompatible with pytest 9.2). See finding 5.
- Prompt to each provider: a one-sentence bug report naming the function, the wrong and the right output, and
  `src/humanize/number.py`. The fix was not described.

## Offline baseline (no model)

`repo-ai verify --run --full` (0.11.1, seatbelt, network denied) ran the full suite in 2.6–4 s. Result: 738 passed,
1 failed, 112 skipped.
- The 1 failure is exactly the declared test: `'1000.0 sextillion' == '1.0 septillion'`.
- The 112 skips are translation tests that need compiled `.mo` catalogues, which the project generates with a script.
- The CLI summary printed "0 passed" for this run. That is a reporting bug (finding 4).

## Live runs (second budget; calls #33–#35)

| # | Build | Provider | Result | Cost |
|---|---|---|---|---|
| — | published 0.11.1 | claude | refused before any model call: "dirty checkout (.gitignore)", because `init`'s managed block dirties the tracked `.gitignore` (finding 1) | $0, no invocation |
| 33 | dev `43293d0` (finding 1 fixed) | claude | `INCONCLUSIVE [LIVE_FAILED]`: the baseline and candidate tests ran with `~/.pyenv/…/python3` instead of the project's `.venv` (finding 2) and without `_version.py` (finding 3), so every observation was untrusted. The candidate itself was correct (oracle below). | $0.076408 |
| — | dev `86c9e19` (findings 1–3 fixed) | replay of #33's candidate | `PASS [SIMULATED]`, claim `ASSURANCE_PARTIAL` | $0 |
| 34 | dev `86c9e19` | claude | **`PASS [LIVE_CANDIDATE_VERIFIED]`**. Baseline: 739 ran, 1 failed. Candidate: 739 ran, 0 failed. Both used the project's `.venv`. `apply`: post-apply 739 ran, 0 failed; `undo` restored `number.py` byte-exactly. The user's `.gitignore` was never touched. | $0.070512 |
| 35 | dev `86c9e19` | codex | **`PASS [LIVE_CANDIDATE_VERIFIED]`**, claim `ASSURANCE_PARTIAL` | UNKNOWN (subscription) |

- `init` then `do` worked on the first try with findings 1–3 fixed: no extra commit and no manual step.
- **On the published 0.11.2** (2026-10-30T23:46Z, call #36), from a fresh first run with `init` uncommitted, Claude
  scored **`PASS [LIVE_CANDIDATE_VERIFIED]`** at $0.066148.
  - The tests used the project's `.venv`. Baseline: 739 ran, 1 failed. Candidate: 739 ran, 0 failed.
  - `apply`: post-apply 739 ran, 0 failed. `undo` was byte-exact.
  - The candidate is `>=` on the integer ratio, the same logic as #33 and #34, so the upstream equivalence holds.
  - Before that, a $0 replay of #33's candidate also passed on the published build.
- All verdicts are plain PASS, not `PASS_WITH_PRE_EXISTING_FAILURES`, because the only failure at the base was the
  declared test.

## Oracle: equivalence to the upstream fix

A differential test compared each candidate's `intword()` with `ca892b3`'s. It ran inside repo-ai's sandbox over
3,000+ values, their negatives and six format strings: powers of ten minus 2, minus 1, plus 0 and plus 1, runs of nines, and 30 random values per
magnitude up to 10^102.
- The oracle is live: on the original buggy code it fails for all six formats.
- **Claude (#33 and #34, the same code apart from a comment): identical to upstream on every value.** It uses `>=`
  where upstream uses `==`, on the same integer ratio.
- **Codex (#35): not identical.** It uses float division (`/`). It differs from upstream only just below a googol:
  Codex renders "1.0 googol" (or "1.0e+00 googol"), upstream a 67-digit "… decillion" count (or "1.0e+67 decillion"). A dense follow-up sample
  was run in the sandbox: 244 values from 10^100 − 9·10^99 up to 10^100 − 1. It measured how far below a googol the
  divergence reaches:
  - up to about 9×10^83 for `%.1f`, `%.0f`, `%.2f`, `%.3f` and `%d`;
  - up to 5×10^97 for `%.1e`;
  - below 10^99 the sample has no values. There the scaled value stays under 1e66, so no carry can happen (by
    reasoning, not sampling).

  An independent fact-check found the `%.1e` range first. The original oracle sampled only 10^100 − 1 and 10^100 − 2
  near a googol, so it under-reported the scope. The power table jumps from 10^33 to 10^100, so Codex's output is
  arguably the better rounding. It is still a behaviour change that upstream's tests do not catch, which is what
  `ASSURANCE_PARTIAL` warns about.

## Product findings (fixed or queued)

1. **`init` dirtied a tracked `.gitignore`** (or created an untracked one), and `do` refused. It reproduces on the
   published 0.11.1 and is not covered by #11's tests. Fixed in PR #16 (merged), after four adversarial review rounds. The rounds found
   and closed: markers in source files, a block ignoring more than repo-ai state, an empty file, CRLF/autocrlf, a
   provider rewriting the file's line endings, and malformed markers.
2. **Missions ran tests with the wrong interpreter.** The interpreter was resolved from the disposable workspace,
   which never holds `.venv`. Post-apply verification runs in the checkout and used the project's venv. **This
   explains the open python-slugify discrepancy (20 failures in the sandbox, 0 after apply).** Fixed in PR #17, which also
   handles editable installs (found in its review). The verified runs used an earlier development build of #16
   and #17 (`86c9e19`), from before their review rounds.
3. **A tracked file that `.gitignore` also matches was dropped from mission workspaces**, because the workspace was
   re-committed with `git add -A`. Fixed in PR #17 (`commit_snapshot`, literal pathspecs).
4. `verify --run --full` printed "0 passed" when no file was selected but the full suite ran (738 passed here). Fixed
   in PR #18: it now quotes pytest's own counts, and only when they agree with the per-test report.
5. Under `--expect-fix`, unrelated tests that error at setup identically at the base and on the candidate still make
   the observation incomplete, unlike pre-existing failures. Queued: changing that changes the trust model and needs
   a design.
6. Found in #16's review and predating it: tracked files marked `export-ignore` are missing from mission
   workspaces, so every provider mission blocks on such repositories. Queued.

## Limits

- One repository, one defect.
- The task needed three disclosed scaffolding edits to run from source.
- #34 and #35 used development builds. #36 repeated the Claude run on the published 0.11.2.
- Grading is equivalence to upstream on a sampled domain, not a proof.
