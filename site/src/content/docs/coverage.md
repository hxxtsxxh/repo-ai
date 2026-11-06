---
title: Requirement coverage
description: Check a developer-declared requirement-to-test map against the per-test outcomes a mission actually observed, with repo-ai coverage.
---

A mission PASS says the frozen tests observed a pass. It cannot tell you whether those tests state the requirement you
care about. In one of repo-ai's own studies a candidate passed every visible test and still failed a requirement the
tests never checked (see [Evaluation](/repo-ai/docs/evaluation/)).

`repo-ai coverage` makes that gap visible. **You** declare which existing test pins each requirement; repo-ai checks
the declaration against the baseline and candidate outcomes recorded in the mission. It does not guess, run anything,
or change the mission's verdict.

```sh
repo-ai coverage MISSION_ID --requirements reqs.json
repo-ai coverage MISSION_ID --requirements reqs.json --json
```

`MISSION_ID` is a single candidate mission with recorded baseline and candidate runs, from `repo-ai do ... --run`
(see [Missions](/repo-ai/docs/missions/)).

Since 0.11.9 you can declare the requirements **before** the run: `repo-ai do ... --run --requirements reqs.json`
freezes the declaration with the mission record. `repo-ai coverage MISSION_ID` (no `--requirements`) then assesses
that frozen declaration and reports `declaration: FROZEN_WITH_MISSION`: it was written before this mission ran. If an
earlier mission still in the store, on the same source with the same proposal or candidate diff, had already
recorded outcomes, it says `FROZEN_AFTER_PRIOR_RUN`
instead; and it cannot know about tests you ran yourself. A file supplied later is `SUPPLIED_AT_ASSESSMENT`. The record's
digest is unkeyed: it catches accidental edits, not someone who rewrites the local mission store. `--requirements`
needs `--run` and is refused with `--resume`, `--from-handoff`, `--tournament`, and for a mission already recorded
without it. For a tournament, pass a candidate's mission ID from
[`shortlist`](/repo-ai/docs/tournaments/), not the comparison ID.

## The requirements file

```json
{
  "schema": "repo-ai.requirements/1",
  "requirements": [
    {
      "text": "Suffixes are unique across the whole list, not just among neighbours",
      "kind": "change",
      "tests": ["test/slug.test.js::unique suffixes across the list"]
    },
    {
      "text": "Existing single-word slugs are unchanged",
      "kind": "preserve",
      "tests": ["test/slug.test.js::single word"]
    },
    { "text": "Handles non-Latin input", "tests": [] }
  ]
}
```

- `kind` is `change` (the default: the behaviour should be new) or `preserve` (it should stay as it was).
- `tests` are test IDs as the runner records them. An ID that matches exactly one recorded test by its last
  `::` segment is accepted; an ambiguous or absent one is reported, never guessed.
- The file is strictly validated: an object with exactly that schema, 1–50 requirements, each with only `text`
  (up to 300 characters), `kind` and `tests` (up to 20). Anything unexpected is refused.

The test IDs above are illustrative; use the IDs from your own mission (`repo-ai why-test-failed MISSION_ID` lists
recorded test identities).

## Per-requirement status

| Status | Meaning |
|---|---|
| `VERIFIED_FAIL_TO_PASS` | `change`: every mapped test failed at baseline and passes on the candidate |
| `VERIFIED_PRESERVED` | `preserve`: every mapped test passed at baseline and still passes |
| `NOT_DISCRIMINATING` | `change`, but a mapped test already passed at baseline, so it could not have caught the missing behaviour |
| `FAILING` | a mapped test does not pass on the candidate |
| `MISSING_TEST` | a declared test ID was not collected in the recorded runs (absent or ambiguous) |
| `UNMAPPED` | no test declared: nothing observed supports this requirement |
| `NOT_OBSERVED` | a mapped test was skipped on the candidate, so it observed nothing |
| `UNVERIFIED_STALE`, `UNVERIFIED_INCONCLUSIVE` | (0.11.9 and later) the mission is stale or not a comparable fresh PASS, so what the mapped tests showed is not verification; `observed_status` keeps it |

Since 0.11.9, a declared test that matched only by its trailing name, not as `file::test`, is flagged in the row
("matched by name, check it is the intended test"), and one test mapped to several requirements is listed under `shared_tests`.

## Which changed lines each requirement's tests ran

For a mission run with a frozen declaration (`do --requirements FILE`), the change-exercise run also records which
changed executable lines ran while each test ran: per test for pytest (from 0.12.2), per test **file** for
`node --test` (from 0.12.5: each test file runs alone under V8 coverage, and every line it ran is credited to every
test in it, so the output says `per test file`), on a host sandbox or, from 0.12.8, in a podman or docker container
(in the image the verified run used). `coverage` lists, per
requirement, the changed lines that ran during its own mapped tests (`changed_lines_run`), and under
`changed_lines_by_requirement` the changed lines that ran only during tests no requirement names and those that ran
outside any test (at import or collection: a module constant, a default argument, a decorator argument).

This is **information, never a status**: it changes no row, obligation, headline or exit code. Attribution is by
time window, so a line that runs at import, in a shared fixture's teardown, in a child process or in another test's
thread is not credited to the test it serves; each run of a shared (session-, package-, module- or class-scoped)
fixture's setup is credited to the tests whose call ran with it active (the definitions they actually used;
parametrized and per-class runs separately; a skipped test gets nothing), and a run no test's call claimed counts as
outside any test. A record is marked incomplete
when a test started a child process (subprocess, multiprocessing, fork), the run stopped early (`-x`, `--maxfail`),
or more tests ran changed lines than are kept. When there is no record, `coverage` says `not measured` and why: no
declaration was frozen with the mission, the verdict was not PASS (the change exercise runs only after a PASS), the
measurement itself was UNMEASURED (with its reason), or no executable line changed.

Each declared test is also compared with what the traced run itself saw (after 0.12.8): `traced, ran no changed line`
when it ran there and credited nothing (for pytest only when the per-test record is complete; otherwise `no changed
line seen`, since child processes are not traced), `not traced` when it did not, and `DIVERGED (traced run: X, verified run: Y)`
when its outcome there differs from the verified run (for node, when any test of its file did). The lines of a
diverged test stay listed, labelled as informational only; the requirement's status always comes from the verified
run. The per-test record comes from a second, slower run in the time left after the usual measurement,
so it never costs the change-exercise result; if it cannot finish, it is left out.

## Headline and exit code

| Headline | When |
|---|---|
| `ACCEPTANCE_MAPPED_ALL` | every declared requirement is verified by a discriminating test, and nothing else is outstanding |
| `ACCEPTANCE_PARTIAL` | some are verified, some are not, or (0.11.9 and later) something no requirement covers is outstanding |
| `ACCEPTANCE_UNMAPPED` | none are verified |
| `STALE` | the mission's evidence no longer matches the source |
| `INCONCLUSIVE` | the mission is not a fresh PASS |

A container mission's image cannot be re-checked by this read-only command. When that is the only open point and the
mission passed, `coverage` assesses the outcomes observed in that image (from 0.12.9; the rule `apply` uses), says so
on an `Image:` line and in `image_check` (`checked: false` with the image digest), and the requirements can reach
their observed status. Anything else that is not fresh still makes the headline `STALE` or `INCONCLUSIVE`.

The command exits 0 only for `ACCEPTANCE_MAPPED_ALL`, so it can gate a script. The JSON also lists
`follow_up_test_needed`: the requirements that still need a test. Since 0.11.9 it also lists `other_obligations`:
changed executable lines that no frozen test ran (from the mission's change-exercise measurement; a mission without
that measurement says so), and failures a scoped mission accepted as pre-existing. Either one keeps the headline at most
`ACCEPTANCE_PARTIAL`. A map supplied with `--requirements` when you run `coverage` (not frozen with the mission) can be written after
the outcomes are known; it is labelled `SUPPLIED_AT_ASSESSMENT`.

:::caution[Never a correctness claim]
`task_correct` is always `CLAIM_UNVERIFIED`. The map is your statement; repo-ai only checked that the named tests
exist and what they observed. A verified requirement means a declared test observed it, not that the test is strong
enough. Behaviour you did not write down is not assessed.
:::

## A real case

On the `node-slug` task from the abc-v1 study, a decoy fix and the reference fix look identical to the visible tests:
both PASS. Once the "unique across the whole list" requirement is mapped to a test that states it, the decoy fails
that requirement and the reference verifies. That is the intended workflow: write the requirement as a test first
if it matters, then map it.
