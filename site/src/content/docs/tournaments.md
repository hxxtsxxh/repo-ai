---
title: Tournaments & shortlist
description: Run independent candidates from two or three providers against one frozen commit; repo-ai picks a winner only when exactly one distinct candidate passes, and abstains otherwise.
---

:::caution[Experimental · needs provider logins and explicit consent]
A live tournament starts two or three provider CLIs, each with network access, and roughly multiplies provider time
by the number of arms. It is plan-only unless you pass `--run --allow-live-provider`.
:::

```sh
repo-ai do "..." --tournament codex,agy --allow-write limiter.py          # plan only
repo-ai do "..." --tournament codex,agy --allow-write limiter.py \
  --max-seconds 900 --run --allow-live-provider                           # live
```

Each arm gets its own isolated checkout and process, from **one frozen commit**, and is checked against **identical
frozen tests**. The arms must be independent agents: two transports of one executable (`opencode` and
`opencode-acp` both run OpenCode with its one configured model) are refused as a pair. Then a fixed rule decides:

| Outcome | Result |
|---|---|
| Exactly one distinct candidate passes | it is the winner |
| Several candidates pass with byte-identical diffs | equivalent; treated as one |
| Several **distinct** candidates pass | **abstain** (no winner) |
| A crash, a no-op, or a baseline mismatch | abstain |

A provider whose CLI enforces a USD ceiling (Claude Code, Bob) needs one in a tournament too. With a provider that
cannot enforce one (Codex, agy), add `--allow-unknown-cost`: `--max-cost-usd` then caps only the enforcing arms and the
others run with cost UNKNOWN (from 0.12.0), for example `--tournament codex,claude --max-cost-usd 1.50
--allow-unknown-cost`.

When several distinct candidates pass, the live comparison (`do --tournament`; not the replay `--candidate` one) says
**how** they differ, without running them. It rebuilds each candidate's files from the frozen commit, as `shortlist`
does, and reports `IDENTICAL` (same bytes), `COSMETIC` (the same Python syntax tree: comments and formatting only, so
nothing they compute differs, except code that reads its own source or line numbers), `SUBSTANTIVE` with the
definitions that differ (`charge.py:charge`, `m.py:C.m`, `<module level>`; a docstring counts; a non-Python file is
substantive whenever it differs), or `UNKNOWN` when a candidate's files cannot be rebuilt exactly (no claim). The rule
above is unchanged: they still abstain. The comparison ends with a **next step** taken from the decision: review and
`repo-ai apply` the winner; when one candidate passed but the comparison was not controlled, `repo-ai why`; for the
same code, pick either via `shortlist`; for a substantive difference, write a test that pins the intended behaviour at
the named definitions and run again, or review and apply the one you choose.

There is no LLM vote, no blending of patches, and no "smaller diff wins" by default. Nothing is ever applied
automatically: even a winner needs `repo-ai apply`.

`--candidate FILE` (repeat 2–3 times) runs the same comparison on **simulated replay proposals** only, offline. It
never calls a model.

```sh
repo-ai compare COMPARISON_ID      # the stored comparison: arms, verdicts, reasons for rejection
```

## After an abstention: `shortlist`

```sh
repo-ai shortlist COMPARISON_ID                         # strict (default): an evidence table only
repo-ai shortlist COMPARISON_ID --policy smallest-diff  # adds a labelled POLICY_PREFERENCE
```

The table shows, per passing candidate: files touched, lines added and removed, cost status, the claim headline, and
files only that candidate touches. For Python changes it also rebuilds each candidate's files from the base commit
and compares their syntax trees: candidates that differ only in comments, formatting or layout are reported as
**the same code**, so you know the choice does not change behaviour (docstrings and other literals still count as
differences). From 0.12.1 this is decided file by file: a non-Python file, or a Python file with a coding cookie or
that does not parse, must be byte-identical; `repo-ai compare` uses the same rule. With `--policy smallest-diff` it marks one candidate as `POLICY_PREFERENCE`. That
is a **tie rule you chose, not a correctness judgement**; a tie yields no preference. `shortlist` declines when the
comparison is uncontrolled or stale, and it applies nothing. A stale comparison (`repo-ai compare ID`, after HEAD
moved or its evidence changed) no longer repeats its recorded next step: it says to run the tournament again and
keeps the old step as `recorded_next_step`. A tournament run in a container reads `not checked` instead (a read-only
command cannot check the image): its recorded step is shown with that caveat, and `repo-ai apply CANDIDATE_ID`
re-runs the tests in the same image before keeping the change.

### Ask a question the tests did not: `--probe` (unreleased)

```sh
repo-ai shortlist COMPARISON_ID --probe edge_cases.py   # run your script against each distinct passing candidate
```

When the frozen tests cannot tell two candidates apart, write a short Python script that prints what matters, for
example the function's result on edge-case inputs, and pass it as `--probe`. repo-ai runs it, as `python
edge_cases.py` from where your tests run, against the base (twice) and against each distinct passing candidate, each
in its own disposable checkout, in the mission's own test sandbox (the same image, network denied). Then it compares
what they printed and their exit status:

| Probe result | Meaning |
|---|---|
| `SAME` | every candidate printed the same thing on these inputs; not proof that they are equivalent |
| `DIFFER` | they behave differently; the first differing line is shown, and you decide which is right |
| `INCONCLUSIVE` | the probe failed to run, timed out, or printed different output on two runs of the same base (time, randomness or addresses in its output) |

The script's sha256 is recorded, so the question asked is the one you declared. No model runs, the script is never
shown to a provider (the candidates already exist), nothing is applied, and the comparison's verdict is unchanged.
`--probe-timeout` sets the limit per run (default 60 seconds).

Each candidate stays individually applicable:

```sh
repo-ai apply CANDIDATE_MISSION_ID
```

Before choosing, map your requirements with [`repo-ai coverage`](/repo-ai/docs/coverage/) on each candidate's mission
ID.

## What has been observed

- **First live tournament** (Codex + agy, one task, n = 1): both candidates passed the frozen tests with different
  diffs, so repo-ai abstained. Graded separately against hidden tests, both were correct. Abstaining cost the user a
  choice, not a bad patch.
- **Live tournament, 2026-10-29** (Codex + agy on a synthetic money-splitting task, n = 1): both passed with distinct
  diffs, so repo-ai abstained; `shortlist` showed +2/−2 vs +4/−2, and `--policy smallest-diff` labelled Codex's as the
  policy preference. The two diffs were the same `divmod` fix, agy's with an added comment, which is what led to the
  same-code report above. Evidence: `docs/launch/evidence/LIVE-JOURNEYS-2026-10-29.md` in the source tree.
- **abc-v3 arm C** (Codex + agy, 4 small tasks): both providers produced passing, different candidates on every valid
  cell, so repo-ai abstained 4 of 4. On tasks this easy, a tournament roughly doubles provider time and returns no
  patch. Whether both were correct was not captured for that arm.
- Cost was `UNKNOWN` for every arm (subscription CLIs).

None of this shows that a tournament beats a single agent. See [Evaluation](/repo-ai/docs/evaluation/).
