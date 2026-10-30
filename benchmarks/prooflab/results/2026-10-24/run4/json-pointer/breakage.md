## ProofLab passport: `claim`

**❌ CLAIM NOT ESTABLISHED: the candidate fails the pinned scenario**

> **Claim:** Resolving a JSON pointer token against a string raises JsonPointerException instead of indexing into the string \(/foo/0 on {'foo': 'abc'} must not return 'a').

Freshness when exported: **fresh**

| | Before (base) | After (candidate) |
|---|---|---|
| Revision | `332ea8439995` (`HEAD`) | working tree `8392076c4496`, 2 changed file(s) |
| Scenario | `tests.py`, same bytes | `tests.py`, same bytes |
| Observed | 28 of 29 passed, 1 failed | 27 of 29 passed, 2 failed |
| Runs | 2, consistent | 2, consistent |

**Failing before:**
- `tests.WrongInputTests.test_string_not_indexable`: `AssertionError: JsonPointerException not raised by resolve_pointer`

**Failing after:**
- `tests.AltTypesTests.test_alttypes`: `jsonpointer.JsonPointerException: Cannot apply token 'left' to non-container type <class 'tests.AltTypesTests.Node'>`
- `tests.AltTypesTests.test_mock_dict_sanity`: `AssertionError: None != {'2': '3'}`

**Regressions:** not-checked
**Edited tests:** the base's own version of 1 edited test file(s) run against the candidate: detected
- `tests.py`: `tests.AltTypesTests.test_alttypes`, `tests.AltTypesTests.test_mock_dict_sanity`
**Integrity:** source tree unchanged; 0 oracle input(s) identical at both revisions; runner `python -m unittest tests`

### Why
- candidate: 2 test\(s) of the scenario fail at the candidate: tests.AltTypesTests.test\_alttypes \(jsonpointer.JsonPointerException: Cannot apply token 'left' to non-container type &lt;class 'tests.AltTypesTests.Node'&gt;)
- regressions: the scenario stage already shows the claim is not established \(--keep-going runs the regression check anyway)
- edited tests: the base's own tests.py fails at the candidate: tests.AltTypesTests.test\_alttypes, tests.AltTypesTests.test\_mock\_dict\_sanity

### What this does not establish
- A passing scenario shows the claim only for what this scenario checks; it is not a proof that the change is correct for other inputs, states or callers.
- ProofLab checks for mistakes, not for a hostile candidate: code under test runs in the scenario's own process and could defeat any check made there. This passport is also a local record that anyone who can write .repo-ai/state could forge, so a reviewer should run 'repo-ai prove run' again.
- The scenario is blob 19bd621d75b8 of tests.py at commit 16c4c8e33a30; whoever wrote that commit wrote the oracle \(check it with 'git cat-file -p 19bd621d75b8').
- The change edits files the scenario reaches by imports \(jsonpointer.py). ProofLab treats them as the code under test; if one of them holds the expected values, the scenario does not check the claim. Review them, or move expected values into the scenario.
- Each side ran 2 time\(s); a flaky outcome that shows up less often is not ruled out.
- The assertion canary only shows that assertions still fail in the scenario's process; code under test that recognises the scenario and behaves differently for it is not detected.

### Not tested
- Behaviour outside the scenario's 29 test\(s).
- Other platforms and environments: only Darwin, 3.12.14 in the seatbelt sandbox was used.
- The claim's wording itself: no tool checks that the scenario tests what the claim says.

### Reproduce
```sh
repo-ai prove run claim --base 332ea8439995
# by hand: check out 332ea8439995 in a separate worktree, then git show 16c4c8e33a30:tests.py > tests.py
# check the bytes: sha256 of tests.py must be 0f865c62352ce0fde46f1904810d29ec0e9906db0cdf87ff4953d7ee9980c7bf
# at the base, in a sandbox: python -m unittest tests -> expect a failure in tests.WrongInputTests.test_string_not_indexable
# at the candidate: python -m unittest tests -> expect every test to pass
repo-ai verify --run --base 332ea8439995 # the regression check
```

<sub>scenario sha256 `0f865c62352ce0fde46f1904810d29ec0e9906db0cdf87ff4953d7ee9980c7bf` from blob `19bd621d75b8` at commit `16c4c8e33a30`, pinned from a terminal · backend seatbelt, os Darwin, python 3.12.14 · repo-ai 0.7.7 · repo-ai.proof-passport/1 · passport `5b635979a743992c` · recorded 2026-10-24T08:31:37-07:00</sub>
