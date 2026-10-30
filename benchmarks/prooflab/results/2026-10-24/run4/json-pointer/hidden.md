## ProofLab passport: `claim`

**❌ CLAIM NOT ESTABLISHED: the candidate breaks existing behaviour**

> **Claim:** Resolving a JSON pointer token against a string raises JsonPointerException instead of indexing into the string \(/foo/0 on {'foo': 'abc'} must not return 'a').

Freshness when exported: **fresh**

| | Before (base) | After (candidate) |
|---|---|---|
| Revision | `989f3ae53f87` (`HEAD`) | working tree `8f7c1a6000f7`, 2 changed file(s) |
| Scenario | `tests_accept.py`, same bytes | `tests_accept.py`, same bytes |
| Observed | 0 of 1 passed, 1 failed | 1 of 1 passed |
| Runs | 2, consistent | 2, consistent |

**Failing before:**
- `tests_accept.StringNotIndexable.test_string_not_indexable`: `AssertionError: JsonPointerException not raised by resolve_pointer`

**Regressions:** none-detected (verify: `selected-passed (full suite not run)`; 1 test file(s) passed of 1 selected, 1 in the project; confidence medium)
**Edited tests:** the base's own version of 1 edited test file(s) run against the candidate: detected
- `tests.py`: `tests.AltTypesTests.test_alttypes`, `tests.AltTypesTests.test_mock_dict_sanity`
**Integrity:** source tree unchanged; 0 oracle input(s) identical at both revisions; runner `python -m unittest tests_accept`

### Why
- edited tests: the base's own tests.py fails at the candidate: tests.AltTypesTests.test\_alttypes, tests.AltTypesTests.test\_mock\_dict\_sanity

### What this does not establish
- A passing scenario shows the claim only for what this scenario checks; it is not a proof that the change is correct for other inputs, states or callers.
- ProofLab checks for mistakes, not for a hostile candidate: code under test runs in the scenario's own process and could defeat any check made there. This passport is also a local record that anyone who can write .repo-ai/state could forge, so a reviewer should run 'repo-ai prove run' again.
- The scenario was pinned from a terminal; who wrote it is not recorded.
- The change edits files the scenario reaches by imports \(jsonpointer.py). ProofLab treats them as the code under test; if one of them holds the expected values, the scenario does not check the claim. Review them, or move expected values into the scenario.
- The scenario is not in the candidate's tree \(it was injected for the experiment): the change does not ship this test.
- Each side ran 2 time\(s); a flaky outcome that shows up less often is not ruled out.
- The assertion canary only shows that assertions still fail in the scenario's process; code under test that recognises the scenario and behaves differently for it is not detected.
- The regression check's test selection has medium confidence \(see 'repo-ai verify').

### Not tested
- Behaviour outside the scenario's 1 test\(s).
- Other platforms and environments: only Darwin, 3.12.14 in the seatbelt sandbox was used.
- The claim's wording itself: no tool checks that the scenario tests what the claim says.

### Reproduce
```sh
repo-ai prove run claim --base 989f3ae53f87
# by hand: check out 989f3ae53f87 in a separate worktree, then copy the pinned bytes from .repo-ai/state/prove/blobs/1085a8afc44a9aca943d93352c762bb4121b0f09f821e6ebc39440d5924842e2 to tests_accept.py
# check the bytes: sha256 of tests_accept.py must be 1085a8afc44a9aca943d93352c762bb4121b0f09f821e6ebc39440d5924842e2
# at the base, in a sandbox: python -m unittest tests_accept -> expect a failure in tests_accept.StringNotIndexable.test_string_not_indexable
# at the candidate: python -m unittest tests_accept -> expect every test to pass
repo-ai verify --run --base 989f3ae53f87 # the regression check
```

<sub>scenario sha256 `1085a8afc44a9aca943d93352c762bb4121b0f09f821e6ebc39440d5924842e2` from a file outside the repository, pinned from a terminal · backend seatbelt, os Darwin, python 3.12.14 · repo-ai 0.7.7 · repo-ai.proof-passport/1 · passport `f0b2d334c1508155` · recorded 2026-10-24T08:32:38-07:00</sub>
