# routing-journey-v1: adaptive routing end to end, with controlled failure injection (preregistered)

C06 (adaptive routing). The 2026-11-01 matrix (`tests/test_provider_routing_matrix.py`, 34,944 decisions) checked the
routing *function* against its specification. This journey checks the **whole path** through the real CLI: discovery
on PATH, `agents route`, `do --agent auto` missions that start a provider process, the cooldown and observation
records a run writes, and the next run's decision. Spend: $0. No model is called.

## Method

`run.py` creates a fresh fixture repository per scenario (one bug, one test, a project virtualenv with pytest) and
runs repo-ai as a subprocess with:

- **PATH** = a scenario directory of stand-in executables + `/usr/bin:/bin` (the host's real agents are invisible);
- **stand-ins** (shell scripts) for Claude Code (help listing repo-ai's required flags; an isolation probe answered
  with a clean init event; then a run that fixes the bug, hits a rejected rate limit, prints "Not logged in", or
  crashes) and for Codex (fixes the bug, emits a completed turn, reports no cost);
- **no real credential:** `CLAUDE_CODE_OAUTH_TOKEN` is a dummy where a scenario needs Claude configured and absent
  otherwise; the Claude dedicated-login directory is a fresh one (missing or empty); Codex gets a dummy dedicated login
  (`REPO_AI_CODEX_HOME`), so its personal login is never read or copied;
- **controlled injections**, where a real observation cannot be produced on demand: an observation's or cooldown's
  expiry time moved into the past in the project's `providers.json`; the stand-in binary changed; the platform name
  seen by the adapters module set to `win32` (in process, discovery and routing otherwise real).

Stand-ins are not the real CLIs: repo-ai cannot tell them apart, so its labels (`LIVE_CANDIDATE_VERIFIED`, `READY`)
describe what repo-ai observed of a stand-in, not of a vendor's agent. Real-provider behaviour (exhausted quotas,
expired logins) is not provoked: the owner's paid quota is never exhausted to create a rate-limit event.

## Scenarios and expected decisions (checked by `run.py`'s `EXPECT` table)

| scenario | condition | expected |
|---|---|---|
| Z1 | zero providers | route `NO_AGENT`; `do --agent auto` refused, no provider started |
| U1 | Claude installed, no login (directory missing) | Claude `SETUP_REQUIRED`; `NO_AGENT`; mission refused |
| U2 | Claude configured (empty login directory), not logged in | routed (`INSTALLED_UNPROBED`: configured, unverified); mission BLOCKED, `provider_unavailable`; then `AUTHORIZED_BUT_UNREADY`, `NO_AGENT` |
| O1 | one usable provider | Claude selected; mission PASS with an observed cost; then `READY` |
| E1 | readiness expires; binary changes | after expiry `INSTALLED_UNPROBED`; after a new success `READY`; after a binary change `INSTALLED_UNPROBED` |
| M1 | two providers | default order Claude; under `--max-cost-usd` Codex ineligible (cost `UNKNOWN`); after `agents authorize codex --prefer` Codex selected |
| Q1 | quota exhausted (rejected rate limit) | mission BLOCKED, `rate_limited`, `provider_unavailable`; next route: Claude `USAGE_LIMITED`, Codex selected |
| Q2 | quota exhausted, under a USD ceiling | `NO_AGENT` (the uncapped provider is no fallback); mission refused |
| F1 | fallback | the next `do --agent auto` runs Codex: PASS, cost `UNKNOWN` (never counted as $0) |
| A1 | explicit `--agent claude` while it cools down | refused before the provider starts |
| C1 | cooldown passed | Claude eligible and selected again |
| X1 | provider crash | BLOCKED, not rate-limited, recovery not `budget_limit`; no cooldown recorded |
| P1 | unsupported platform | `NO_AGENT`; every installed provider `ISOLATION_BLOCKED` |

## Gates (decided now)

| id | measure | gate |
|---|---|---|
| G1 | expected decisions met | **all** |
| G2 | missions that ran a provider other than the one their contract names (a silent fallback inside a run) | **0** |
| G3 | runs of a provider without an enforceable ceiling that report an observed cost | **0** |

## Pilot (disclosed)

Three pilot runs of the harness on 2026-11-02, before this preregistration, found two repo-ai defects, now fixed in
the same change (`tests/test_routing_journey_fixes.py`, failing first):

1. An explicit `--agent claude` during a recorded rate-limit cooldown started the provider again (it would hit the
   same quota). Now refused before it starts; automatic routing already skipped it.
2. A crashed provider under a USD ceiling was classified `budget_limit` ("replan with an explicit time/attempt
   budget"), because its unknown cost matched the budget rule. The crash is now the cause (`contract_failure`).

The pilots also corrected the harness (a USD ceiling where a capped provider runs; distinct task texts, since the same
task on the same commit returns the stored mission unrun; a missing versus an empty login directory; an in-process
platform injection limited to the adapters module). The counted run is the first run of the committed harness on the
fixed build. One run on macOS (seatbelt); results in `RESULTS.md` and `results/`.

## Amendment after run 1 (2026-11-02, independent review of the change)

Run 1 was recorded with the checks above (27 of 27). The review found the refusal checks too loose: any non-zero exit
without a verdict passed, and the Z1, U1 and Q2 refusals printed a misleading reason ("live provider execution
requires --allow-live-provider" although it was given); X1 was checked only as "not `budget_limit`". It also found
three defects in the pilot's fixes (a continuation refused for a cooldown used up its capsule; a cost overrun with a
non-zero exit was no longer `budget_limit`; a malformed cooldown time crashed the refusal) and a unit test that could
start a real `claude` (its run_provider was not stubbed). All are fixed. The checks now require exit 1, the stated
reason ("no provider can run this mission (NO_AGENT)", "is cooling down until"), no traceback, and X1 recovery
`contract_failure`. Run 1 is kept and re-evaluated under these checks; run 2 is the first run of the amended harness
on the fixed build. Both are reported.

## Amendment 2 after run 2 (2026-11-02, review of the integration record)

Run 2 was at `bf49f2a`, before #105. Its Q1 mission started the Claude stand-in with no `--max-cost-usd`, which is the
"started uncapped, refused afterwards" path #105 later closed; A1 also had no ceiling but was refused for the cooldown
before starting. The journey did not detect it. On main
those missions are now refused for the missing ceiling, so run 2's result does not describe main. The harness now
gives Claude a ceiling in Q1 and A1 (F1 stays without one, so Codex remains the fallback) and adds **G4: missions
that started a ceiling-enforcing provider without a usable ceiling = 0**. Run 2 is re-evaluated with G4 and kept;
run 3 is the first run of this harness on main. All three runs are reported.

## Amendment 3 before run 4 (2026-11-03 UTC, queue row 28)

Runs 1 to 3 describe 0.12.0, where `--agent auto` at the default `--max-cost-usd 0` could select Claude and the
mission was then refused for the missing ceiling (the 0.12.0 known limitation). Routing now treats a provider whose CLI
enforces a USD ceiling as ineligible when no usable ceiling (at least $0.0001) is given, says why, and names
`--max-cost-usd`. Written before run 4, with no run of the changed code through this harness:

- The route steps that check Claude's readiness or selection (U2 both, O1 `route` and `route-after-success`, E1 all
  three, C1, X1) now pass `--max-cost-usd 0.5`, as their missions already did. Their expectations are unchanged.
- M1 `route` (at $0, Claude and Codex installed): expected **Codex** selected, Claude not eligible with a reason naming
  `--max-cost-usd`, both `INSTALLED_UNPROBED`. The default order (Claude first) stays checked by
  `route-with-usd-ceiling`.
- New O1 steps at $0, before the ceilinged route: `route-at-zero` expects `NO_AGENT`, Claude `INSTALLED_UNPROBED` and
  not eligible, and a `why` naming `--max-cost-usd`; `mission-at-zero` expects the refusal "no provider can run this
  mission (NO_AGENT)" naming `--max-cost-usd`, with no provider started.
- The route record now includes `why`. G1 counts 29 expected decisions (27 + 2); G2, G3 and G4 are unchanged.

Runs 1 to 3 are kept as the record of 0.12.0. Run 4 is the first run of this harness on the changed code.
