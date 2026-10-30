## ProofLab passport: `claim`

**✅ CLAIM SUPPORTED for the pinned scenario: the candidate passes it and the original code failed it, with no regression detected. The scenario is not independent of the change, so this is not a controlled comparison (evidence level behavior_observed)**

> **Claim:** Resolving a JSON pointer token against a string raises JsonPointerException instead of indexing into the string \(/foo/0 on {'foo': 'abc'} must not return 'a').

Freshness when exported: **fresh**

| | Before (base) | After (candidate) |
|---|---|---|
| Revision | `cb845b0e4ac3` (`HEAD`) | working tree `fbeb6d76c7ce`, 2 changed file(s) |
| Scenario | `tests.py`, same bytes | `tests.py`, same bytes |
| Observed | 28 of 29 passed, 1 failed | 29 of 29 passed |
| Runs | 2, consistent | 2, consistent |

**Failing before:**
- `tests.WrongInputTests.test_string_not_indexable`: `AssertionError: JsonPointerException not raised by resolve_pointer`

**Regressions:** none-detected (verify: `selected-passed (full suite not run)`; 1 test file(s) passed of 1 selected, 1 in the project; confidence medium)
**Edited tests:** the base's own version of 1 edited test file(s) run against the candidate: none-detected
**Integrity:** source tree unchanged; 0 oracle input(s) identical at both revisions; runner `python -m unittest tests`

### What this does not establish
- A passing scenario shows the claim only for what this scenario checks; it is not a proof that the change is correct for other inputs, states or callers.
- ProofLab checks for mistakes, not for a hostile candidate: code under test runs in the scenario's own process and could defeat any check made there. This passport is also a local record that anyone who can write .repo-ai/state could forge, so a reviewer should run 'repo-ai prove run' again.
- The scenario is blob 19bd621d75b8 of tests.py at commit 16c4c8e33a30; whoever wrote that commit wrote the oracle \(check it with 'git cat-file -p 19bd621d75b8').
- The change edits files the scenario reaches by imports \(jsonpointer.py). ProofLab treats them as the code under test; if one of them holds the expected values, the scenario does not check the claim. Review them, or move expected values into the scenario.
- Each side ran 2 time\(s); a flaky outcome that shows up less often is not ruled out.
- The assertion canary only shows that assertions still fail in the scenario's process; code under test that recognises the scenario and behaves differently for it is not detected.
- The regression check's test selection has medium confidence \(see 'repo-ai verify').

### Not tested
- Behaviour outside the scenario's 29 test\(s).
- Other platforms and environments: only Darwin, 3.12.14 in the seatbelt sandbox was used.
- The claim's wording itself: no tool checks that the scenario tests what the claim says.

### Reproduce
```sh
repo-ai prove run claim --base cb845b0e4ac3
# by hand: check out cb845b0e4ac3 in a separate worktree, then git show 16c4c8e33a30:tests.py > tests.py
# check the bytes: sha256 of tests.py must be 0f865c62352ce0fde46f1904810d29ec0e9906db0cdf87ff4953d7ee9980c7bf
# at the base, in a sandbox: python -m unittest tests -> expect a failure in tests.WrongInputTests.test_string_not_indexable
# at the candidate: python -m unittest tests -> expect every test to pass
repo-ai verify --run --base cb845b0e4ac3 # the regression check
```

<sub>scenario sha256 `0f865c62352ce0fde46f1904810d29ec0e9906db0cdf87ff4953d7ee9980c7bf` from blob `19bd621d75b8` at commit `16c4c8e33a30`, pinned from a terminal · backend seatbelt, os Darwin, python 3.12.14 · repo-ai 0.7.7 · repo-ai.proof-passport/1 · passport `3642aa589079d398` · recorded 2026-10-24T08:31:19-07:00</sub>
