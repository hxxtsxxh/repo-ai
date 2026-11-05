# Proof-of-change evidence contract: `repo-ai.proof-evidence/1`

**Status:**
- **Version 1.1:** draft, normative for producers and consumers. 1.1 adds: the control is a side (§7), `scenario.pinned_from` (§3), the D10 cap and the `nothing-selected` rule (§6).
- **Owner:** Session A, verification reliability.
- **Consumers:** ProofLab (`repo-ai prove`, Session B) and any report built on `verify`.
- **Machine-readable schema:** [`schemas/proof-evidence-1.schema.json`](schemas/proof-evidence-1.schema.json).

**What this contract is for:** it defines what one piece of evidence about a change records, and
which claim that evidence may support.

**What it never is:** a proof that a change is correct. Evidence says what was observed for
particular tests or scenarios, in one environment, on one exact working-tree state, and nothing
beyond that.

## 1. Versioning

- **The `schema` field** is `"repo-ai.proof-evidence/1"`. Within version 1, fields are only added.
  A consumer ignores fields it does not know.
- **Renaming or removing a field, or changing a field's meaning,** changes the schema id to `/2`.
- **`contract_version`** (`"1.0"`, `"1.1"`, …) increases when rules are added. A producer writes
  the version it implements.
- **The ProofLab passport (`repo-ai.proof-passport/1`)** embeds one or more evidence records, each
  under its own `schema`. It never copies their fields into its own namespace.

## 2. The five claim levels

Each record states exactly one `claim.level`. A level holds only when every condition in its row
holds. Otherwise the record falls back to the strongest level whose conditions do hold, down to
`not_established`.

| Level | It means | Required |
|---|---|---|
| `not_established` | nothing is claimed | the default. Every incomplete, stale, infrastructure-failed or contradictory observation ends here |
| `test_passed` | the named tests ran to completion and passed on the candidate state | the candidate observation is `pass` and conclusive (§4); the run's integrity is unchanged (§5); fresh (§6) |
| `behavior_observed` | a scenario run on the candidate produced the stated observable result | as `test_passed`, for the scenario. The oracle (the condition checked) is recorded with its hash |
| `regression_reproduced` | the same scenario bytes pass at the base and fail on the candidate | both observations conclusive (`pass` at the base, `fail` on the candidate). Same scenario sha256, same runner identity, same environment key on both sides. Repeats agree (§7). Fresh |
| `supported_by_controlled_comparison` | the change, and nothing else measured, turns observation A into observation B for this scenario | everything `regression_reproduced` needs, with A ≠ B in either direction. The scenario's provenance is independent of the change (§3). A **negative control** ran and behaved as predicted: the same scenario on an unchanged copy of the base reproduces A. The oracle is unchanged between the sides |

**`claim.not_established[]` is always written.** It lists what the record does not show. At a
minimum:
- `"other inputs and scenarios"`;
- `"other environments"`;
- `"the full test suite"`, unless a full-suite observation is included and conclusive;
- `"correctness of the change"`.

A producer adds anything specific: `"flaky: repeats disagreed"`, `"submodule content not
fingerprinted"`, and so on.

**Words that must not appear in a claim's text:** "proves", "safe" and "correct". The claim text is
for display only. Consumers decide on `claim.level`.

## 3. Provenance

| Field | Meaning |
|---|---|
| `base.commit` | the full commit id compared against (`git rev-parse <base>^{commit}`) |
| `base.tree` | that commit's tree id |
| `candidate.fingerprint` | verify's exact fingerprint of the working tree against `base.commit` (`changes.fingerprint`) |
| `candidate.semantic_fingerprint` | for display only; it never upgrades freshness or a claim |
| `candidate.head` | the commit `HEAD` resolved to when the run started |
| `scenario.sha256` | sha256 of the exact scenario bytes run on both sides |
| `scenario.source` | `worktree:<path>`, `blob:<rev>:<path>`, `external:<sha256>` or `generated:<generator id>@<version>` |
| `scenario.pinned_from` | (1.1, optional) how an `external:` scenario was pinned: `terminal`, `agent`, … A consumer can then see why it counts as independent |
| `scenario.independent_of_change` | true only if the scenario's bytes did not come from the candidate's diff (`blob` at the base, `external`, or `generated` from inputs that exclude the diff). A scenario written in the same change cannot reach `supported_by_controlled_comparison` |
| `command.runner` | verify's runner identity (`cache.runner_identity`): kind, argv, cwd, environment allowlist |
| `command.argv` | the exact argv of each process, as `report.display` prints it |
| `oracle` | `{kind: exit-status|test-ids|output-match|custom, spec, sha256}`. It is the same on both sides, or the level is at most `behavior_observed` |

## 4. Observations and their states

Each side (`base`, `candidate`, `control`) holds `observations[]`, one per repeat:

| Field | Values |
|---|---|
| `state` | `pass` · `fail` · `timeout` · `infrastructure_error` · `incomplete` · `skipped` · `not_run` |
| `conclusive` | true only for `pass` or `fail` meeting every rule below |
| `exit_code`, `timed_out`, `duration_s`, `processes` | from the sandbox result |
| `tests` | `{ran, passed, failed, skipped, expected_failures}`, counting **tests only** |
| `failing_tests[]`, `hung_tests[]` | test ids |
| `report` | `{present, complete, trusted, reason}` from verify's per-test report |
| `stdout_sha256`, `stderr_sha256` | hashes of the full output; excerpts are untrusted text |

**Rules.** Each rule closes a defect found on `083b6f1` (`docs/VERIFY-PHASE2-FINDINGS-2026-10.md`).

1. **The report outranks the exit status.** `pass` needs exit 0, no time-out, and, when a per-test
   report exists:
   - it is complete (its `done` event is present);
   - it shows no failing and no unfinished test.

   Otherwise the state is `fail` if the report shows a failure. If the report ended early or
   contradicts the exit status, the state is `incomplete`. (D1)
2. **Only tests count.** node's per-file wrapper, suites and collection entries are not tests. A
   file or scenario where `ran == 0` is `skipped`, never `pass`. (D2)
3. **An expected failure is not a pass.** An `xfail`, `@expectedFailure` or skip verifies nothing.
   It counts under `skipped` / `expected_failures`. If every selected test is in those counts, the
   state is `skipped`. (D3)
4. **A time-out says nothing about what a test would have done.** A base observation cut by a time
   limit is `timeout`, never `fail`. A comparison with it is not conclusive. (D4)
5. **An infrastructure failure is not a test result.** If the sandbox is unavailable, the image is
   missing, dependencies fail to import at both sides in the same way, or the harness crashes, the
   state is `infrastructure_error`. Pre-existing failures caused by the environment are labelled as
   environment, not as the base.
6. **Untrusted text stays untrusted.** Messages, test names and output excerpts are written by the
   code under test. They are bounded, scrubbed, and never parsed for decisions.

## 5. Integrity

`integrity` holds:
- `source_tree_unchanged`: verify's snapshot before and after each run, as in the agent contract's
  source-tree check;
- `workspace_disposable: true`;
- `sandbox`: `{backend, network: false}`.

**Any run whose source tree changed makes the record `not_established`.** This covers verify's
`invalid: the source tree changed during the run`. It never falls back to an earlier record of
another state.

## 6. Freshness

`freshness` holds:
- `state`: `fresh`, `stale` or `unknown`;
- `checked_at`;
- `environment_key`: verify's `cache.environment_key`.

**A record is `fresh` only if both of these hold now:**
- `changes.fingerprint(root, base.commit)` equals `candidate.fingerprint`;
- the environment key equals the recorded one.

**Consumers rules:**
- A consumer must recompute freshness before it displays a claim above `not_established`, and show
  the record as stale otherwise.
- A semantic-fingerprint match may be shown as "same behaviour expected". It never makes a record
  fresh.

**Coverage the fingerprint must have.** The producer guarantees that the fingerprint changes
whenever any byte the execution copy reads changes:
- exact bytes, CRLF included (D7);
- tracked files flagged `--skip-worktree` / `--assume-unchanged` (D6);
- files inside checked-out submodules (D5);
- a rename or move, by path (D9);
- the interpreter and its environment, the venv's own site-packages included (D8). These are in the
  environment key.

**Until a producer's engine includes the fixes for D5–D9,** it must flag the corresponding
conditions in `claim.not_established` and cap the level at `test_passed`:
- a submodule is present;
- any flagged index entry exists;
- a rename is in the change;
- a CRLF file is in the change;
- a host-sandbox Python run uses a virtualenv;
- the change touches TypeScript tests that only node's default discovery lists (D10).

**`nothing-selected` never supports a claim above `not_established`.** For a behavioural code
change it is the outcome of every selection blind spot found so far (D9, D10).

## 7. Repeats and flakiness

- `regression_reproduced` and above need at least 2 conclusive observations on each side, all
  agreeing.
- **The control is a side** (1.1). `supported_by_controlled_comparison` needs at least 2 conclusive,
  agreeing control observations: the control is what rules out environment drift and flakiness.
- Disagreement on either side makes the record `not_established`, with
  `"flaky: repeats disagreed"`. The disagreeing observations are kept.
- Repeats run sequentially, each in a fresh disposable workspace.

## 8. Reproduction

`reproduction` holds:
- `engine`: `{version, wheel_sha256 | commit}`;
- `environment`: `{image, image_digest, python | node version, platform}`;
- `commands[]`: the `repo-ai` invocations that recreate each side;
- `seed`, when one applies.

**A reproduction that does not match is a new record**, never an edit of this one.

## 9. Consumer decision table

| The consumer wants to say | It needs |
|---|---|
| "the tests passed" | `test_passed` or above, fresh, and the test names shown |
| "this change broke X" | `regression_reproduced`, fresh |
| "this change caused B" | `supported_by_controlled_comparison`, fresh, with the negative control shown |
| anything about correctness, safety or completeness | never supported; show `not_established` |

## 10. Example (abridged)

```json
{
  "schema": "repo-ai.proof-evidence/1", "contract_version": "1.1",
  "base": {"commit": "083b6f14…", "tree": "0e1e1f4a…"},
  "candidate": {"fingerprint": "7c1d46…", "semantic_fingerprint": "…", "head": "083b6f14…"},
  "scenario": {"sha256": "…", "source": "blob:083b6f1:tests/test_core.py", "independent_of_change": true},
  "command": {"runner": {"kind": "unittest", "command": "python -m unittest discover -s tests -t ."},
              "argv": ["python -m unittest tests.test_core"]},
  "oracle": {"kind": "exit-status", "spec": "0 = holds", "sha256": "…"},
  "sides": {
    "base": {"observations": [{"state": "pass", "conclusive": true, "tests": {"ran": 4, "passed": 4, "failed": 0,
             "skipped": 0, "expected_failures": 0}, "report": {"present": true, "complete": true, "trusted": true}}]},
    "candidate": {"observations": [{"state": "fail", "conclusive": true, "failing_tests": ["tests.test_core.T.test_add"]}]},
    "control": {"observations": [{"state": "pass", "conclusive": true}]}
  },
  "integrity": {"source_tree_unchanged": true, "workspace_disposable": true,
                "sandbox": {"backend": "podman", "network": false}},
  "freshness": {"state": "fresh", "checked_at": "2026-10-24T15:00:00-07:00", "environment_key": "…"},
  "claim": {"level": "regression_reproduced", "text": "tests.test_core fails with this change and passes at the base",
            "not_established": ["other inputs and scenarios", "other environments", "the full test suite",
                                "correctness of the change"]},
  "reproduction": {"engine": {"version": "0.7.7", "commit": "083b6f1"},
                   "environment": {"image": "localhost/proj:1", "image_digest": "sha256:…"},
                   "commands": ["repo-ai verify --run --json --rerun --sandbox podman --image localhost/proj:1"]}
}
```

## 11. Caveats measured so far

- **Ten defects on `083b6f1` violate rules in §4 and §6** (D1–D10). Fixes are in #41, #42, #43 and #45;
  until they are merged, the §6 cap applies. D9 (a staged rename gives `nothing-selected`) reproduced on 5 of
  5 fresh held-out-6 projects.
- **The held-out-6 evaluation** (`benchmarks/verify-eval/PROTOCOL.md` Amendment 5) measures the
  false-assurance invariant on fresh repositories. Its results decide which runners and
  environments may carry levels above `not_established` in a release.
- **Windows has never been measured.** A producer on Windows writes
  `"Windows: not validated"` in `not_established`.
- **Gate-related semantic equivalence** (formatter-only rewrites) is a display convenience, not
  evidence. See §6.
