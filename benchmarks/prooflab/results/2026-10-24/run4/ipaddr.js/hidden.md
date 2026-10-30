## ProofLab passport: `claim`

**❌ CLAIM NOT ESTABLISHED: the candidate breaks existing behaviour**

> **Claim:** IPv4/IPv6 match\() and subnetMatch\() reject invalid CIDR prefix lengths \(negative, fractional, NaN, infinite or longer than the address).

Freshness when exported: **fresh**

| | Before (base) | After (candidate) |
|---|---|---|
| Revision | `b20e8ad598ce` (`HEAD`) | working tree `812d10da4b39`, 2 changed file(s) |
| Scenario | `test/accept-cidr.test.js`, same bytes | `test/accept-cidr.test.js`, same bytes |
| Observed | 0 of 3 passed, 3 failed | 3 of 3 passed |
| Runs | 2, consistent | 2, consistent |

**Failing before:**
- `ipaddr > rejects invalid IPv4 CIDR prefix lengths in match`: `AssertionError: Missing expected exception.`
- `ipaddr > rejects invalid IPv6 CIDR prefix lengths in match`: `AssertionError: Missing expected exception.`
- `ipaddr > subnetMatch rejects invalid CIDR prefix lengths`: `AssertionError: Missing expected exception.`

**Regressions:** none-detected (verify: `selected-passed (full suite not run)`; 1 test file(s) passed of 1 selected, 1 in the project; confidence medium)
**Edited tests:** the base's own version of 1 edited test file(s) run against the candidate: detected
- `test/ipaddr.test.js`: `ipaddr > converts between IPv4-mapped IPv6 addresses and IPv4 addresses`, `ipaddr > correctly processes IPv4-mapped addresses`, `ipaddr > detects reserved IPv4 networks`
**Integrity:** source tree unchanged; 1 oracle input(s) identical at both revisions; runner `node --test test/accept-cidr.test.js`

### Why
- edited tests: the base's own test/ipaddr.test.js fails at the candidate: ipaddr &gt; converts between IPv4-mapped IPv6 addresses and IPv4 addresses, ipaddr &gt; correctly processes IPv4-mapped addresses, ipaddr &gt; detects reserved IPv4 networks

### What this does not establish
- A passing scenario shows the claim only for what this scenario checks; it is not a proof that the change is correct for other inputs, states or callers.
- ProofLab checks for mistakes, not for a hostile candidate: code under test runs in the scenario's own process and could defeat any check made there. This passport is also a local record that anyone who can write .repo-ai/state could forge, so a reviewer should run 'repo-ai prove run' again.
- The scenario was pinned from a terminal; who wrote it is not recorded.
- The change edits files the scenario reaches by imports \(lib/ipaddr.js). ProofLab treats them as the code under test; if one of them holds the expected values, the scenario does not check the claim. Review them, or move expected values into the scenario.
- The scenario is not in the candidate's tree \(it was injected for the experiment): the change does not ship this test.
- Each side ran 2 time\(s); a flaky outcome that shows up less often is not ruled out.
- The assertion canary only shows that assertions still fail in the scenario's process; code under test that recognises the scenario and behaves differently for it is not detected.
- The regression check's test selection has medium confidence \(see 'repo-ai verify').

### Not tested
- Behaviour outside the scenario's 3 test\(s).
- Other platforms and environments: only Darwin, v24.19.0 in the seatbelt sandbox was used.
- The claim's wording itself: no tool checks that the scenario tests what the claim says.

### Reproduce
```sh
repo-ai prove run claim --base b20e8ad598ce
# by hand: check out b20e8ad598ce in a separate worktree, then copy the pinned bytes from .repo-ai/state/prove/blobs/e26813d62815ba0b144a8b4fbf6f07498d3c589c226a93e81222de5932f6eacc to test/accept-cidr.test.js
# check the bytes: sha256 of test/accept-cidr.test.js must be e26813d62815ba0b144a8b4fbf6f07498d3c589c226a93e81222de5932f6eacc
# at the base, in a sandbox: node --test test/accept-cidr.test.js -> expect a failure in ipaddr > rejects invalid IPv4 CIDR prefix lengths in match, ipaddr > rejects invalid IPv6 CIDR prefix lengths in match, ipaddr > subnetMatch rejects invalid CIDR prefix lengths
# at the candidate: node --test test/accept-cidr.test.js -> expect every test to pass
repo-ai verify --run --base b20e8ad598ce # the regression check
```

<sub>scenario sha256 `e26813d62815ba0b144a8b4fbf6f07498d3c589c226a93e81222de5932f6eacc` from a file outside the repository, pinned from a terminal · backend seatbelt, os Darwin, node v24.19.0 · repo-ai 0.7.7 · repo-ai.proof-passport/1 · passport `b4702abebfdbd700` · recorded 2026-10-24T08:33:56-07:00</sub>
