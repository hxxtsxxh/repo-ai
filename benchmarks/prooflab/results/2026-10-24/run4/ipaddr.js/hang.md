## ProofLab passport: `claim`

**❌ CLAIM NOT ESTABLISHED: the experiment is incomplete**

> **Claim:** IPv4/IPv6 match\() and subnetMatch\() reject invalid CIDR prefix lengths \(negative, fractional, NaN, infinite or longer than the address).

Freshness when exported: **fresh**

| | Before (base) | After (candidate) |
|---|---|---|
| Revision | `014ef5e31b08` (`HEAD`) | working tree `262dad77a147`, 2 changed file(s) |
| Scenario | `test/ipaddr.test.js`, same bytes | `test/ipaddr.test.js`, same bytes |
| Observed | 67 of 70 passed, 3 failed | incomplete: did not finish within 20s (--timeout): the process timed out |
| Runs | 2, consistent | 2, consistent |

**Failing before:**
- `ipaddr > rejects invalid IPv4 CIDR prefix lengths in match`: `AssertionError: Missing expected exception.`
- `ipaddr > rejects invalid IPv6 CIDR prefix lengths in match`: `AssertionError: Missing expected exception.`
- `ipaddr > subnetMatch rejects invalid CIDR prefix lengths`: `AssertionError: Missing expected exception.`

**Regressions:** not-checked
**Edited tests:** the base's own version of 1 edited test file(s) run against the candidate: none-detected
**Integrity:** source tree unchanged; 1 oracle input(s) identical at both revisions; runner `node --test test/ipaddr.test.js`

### Why
- candidate: the scenario's run at the candidate is incomplete: did not finish within 20s \(--timeout): the process timed out
- regressions: the scenario stage already shows the claim is not established \(--keep-going runs the regression check anyway)

### What this does not establish
- A passing scenario shows the claim only for what this scenario checks; it is not a proof that the change is correct for other inputs, states or callers.
- ProofLab checks for mistakes, not for a hostile candidate: code under test runs in the scenario's own process and could defeat any check made there. This passport is also a local record that anyone who can write .repo-ai/state could forge, so a reviewer should run 'repo-ai prove run' again.
- The scenario is blob 092ccb1acb47 of test/ipaddr.test.js at commit 74ee4c5751af; whoever wrote that commit wrote the oracle \(check it with 'git cat-file -p 092ccb1acb47').
- The change edits files the scenario reaches by imports \(lib/ipaddr.js). ProofLab treats them as the code under test; if one of them holds the expected values, the scenario does not check the claim. Review them, or move expected values into the scenario.
- Each side ran 2 time\(s); a flaky outcome that shows up less often is not ruled out.
- The assertion canary only shows that assertions still fail in the scenario's process; code under test that recognises the scenario and behaves differently for it is not detected.

### Not tested
- Other platforms and environments: only Darwin, v24.19.0 in the seatbelt sandbox was used.
- The claim's wording itself: no tool checks that the scenario tests what the claim says.

### Reproduce
```sh
repo-ai prove run claim --base 014ef5e31b08
# by hand: check out 014ef5e31b08 in a separate worktree, then git show 74ee4c5751af:test/ipaddr.test.js > test/ipaddr.test.js
# check the bytes: sha256 of test/ipaddr.test.js must be ba469775028dece0b2c1de7023a1ee92d9de7bc7c68e3f50927fc9c10b444057
# at the base, in a sandbox: node --test test/ipaddr.test.js -> expect a failure in ipaddr > rejects invalid IPv4 CIDR prefix lengths in match, ipaddr > rejects invalid IPv6 CIDR prefix lengths in match, ipaddr > subnetMatch rejects invalid CIDR prefix lengths
# at the candidate: node --test test/ipaddr.test.js -> expect every test to pass
repo-ai verify --run --base 014ef5e31b08 # the regression check
```

<sub>scenario sha256 `ba469775028dece0b2c1de7023a1ee92d9de7bc7c68e3f50927fc9c10b444057` from blob `092ccb1acb47` at commit `74ee4c5751af`, pinned from a terminal · backend seatbelt, os Darwin, node v24.19.0 · repo-ai 0.7.7 · repo-ai.proof-passport/1 · passport `8c12a842c853faa1` · recorded 2026-10-24T08:33:09-07:00</sub>
