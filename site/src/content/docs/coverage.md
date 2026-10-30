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
(see [Missions](/repo-ai/docs/missions/)). For a tournament, pass a candidate's mission ID from
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

## Headline and exit code

| Headline | When |
|---|---|
| `ACCEPTANCE_MAPPED_ALL` | every declared requirement is verified by a discriminating test |
| `ACCEPTANCE_PARTIAL` | some are verified, some are not |
| `ACCEPTANCE_UNMAPPED` | none are verified |
| `STALE` | the mission's evidence no longer matches the source |
| `INCONCLUSIVE` | the mission is not a fresh PASS |

The command exits 0 only for `ACCEPTANCE_MAPPED_ALL`, so it can gate a script. The JSON also lists
`follow_up_test_needed`: the requirements that still need a test.

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
