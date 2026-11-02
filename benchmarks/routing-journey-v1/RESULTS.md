# routing-journey-v1: results

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md), committed with the harness and the pilot's fixes at `66ecb5f`
before this run. Runs on 2026-11-02, macOS Darwin 25.5 arm64 (seatbelt): run 1 with repo-ai at that commit, run 2 at `bf49f2a`. Spend: $0; no
model was called; every provider process was a stand-in script. Raw: [results/run-1.jsonl](results/run-1.jsonl),
evaluation: [results/run-1-evaluation.json](results/run-1-evaluation.json) (host paths replaced).

**Run 1 (preregistered checks): G1 27 of 27; G2 0 silent fallbacks inside a run; G3 0 uncapped runs reporting an
observed cost.** An independent review then found those refusal checks too loose (amendment in the
preregistration): re-evaluated under the stricter checks, run 1 meets **24 of 27**. Z1, U1 and Q2 were refused for
the right cause but with a misleading message ("live provider execution requires --allow-live-provider", although it
was given). **Run 2** (the amended harness on the fixed build, `bf49f2a`, results in `results/run-2*.json*`): **G1 27 of
27, G2 0, G3 0**, with the refusals now saying "no provider can run this mission (NO_AGENT): …" and "cooling down
until …".

| scenario | what happened |
|---|---|
| Z1 zero providers | `NO_AGENT`; `do --agent auto` exited 1 with no provider started |
| U1 no login | Claude `SETUP_REQUIRED`, `NO_AGENT`; mission refused |
| U2 configured, not logged in | routed as `INSTALLED_UNPROBED` (an empty login directory looks configured; repo-ai reads no credential to check); the stand-in's "Not logged in" made the mission BLOCKED (`provider_unavailable`) and the next route `AUTHORIZED_BUT_UNREADY`, `NO_AGENT` |
| O1 one provider | Claude selected; PASS, cost `OBSERVED` ($0.01 reported by the stand-in); next route `READY` |
| E1 expiry | the `READY` observation, expired by injection, gave `INSTALLED_UNPROBED`; a new success gave `READY`; a changed binary gave `INSTALLED_UNPROBED` again |
| M1 two providers | default order: Claude; with `--max-cost-usd 0.5` Codex ineligible (cost `UNKNOWN`); `agents authorize codex --prefer` selected Codex (and, as documented, made the allowlist exclusive: Claude `AVAILABLE_BUT_UNAUTHORIZED`) |
| Q1 quota | the stand-in's rejected rate limit: mission BLOCKED, `rate_limited`, `provider_unavailable`; next route Claude `USAGE_LIMITED`, Codex selected |
| Q2 quota under a ceiling | `NO_AGENT`; mission refused (an uncapped provider is no fallback under a USD ceiling) |
| F1 fallback | the next `do --agent auto` ran Codex: PASS, cost `UNKNOWN` |
| A1 explicit while cooling | refused before start: "claude hit a quota or rate limit recently and is cooling down until … UTC; another call would hit it again" |
| C1 cooldown passed | Claude eligible and selected again |
| X1 crash | BLOCKED, not rate-limited, cost `UNKNOWN`, recovery `contract_failure` (both runs); no cooldown recorded |
| P1 unsupported platform | `NO_AGENT`, both providers `ISOLATION_BLOCKED` |

**Fixed by this study.** Pilot (before run 1): an explicitly chosen provider in a rate-limit cooldown was started
again; a crashed provider under a USD ceiling was classified `budget_limit`. Review (before run 2): a continuation
refused for a cooldown used up its capsule (now refused before the capsule is claimed); a cost overrun with a non-zero
exit was no longer `budget_limit` (a reported overrun now always is); a malformed cooldown time crashed the refusal;
the `NO_AGENT` refusal gave a misleading reason. All have tests (`tests/test_routing_journey_fixes.py`). One of the
pilot's own tests did not stub the provider runner, so on this Mac it could start the installed `claude` with the
test fixture's fake token in a scratch HOME (no credential of the owner's was in that environment, so it could not
authenticate or bill); it now stubs the runner and asserts it was reached.

**What this shows:** on one host, through the real CLI and records, routing chooses, refuses, cools down, falls back,
recovers and expires as specified across zero, one and two installed providers, missing and unverified logins,
exhausted quota (with and without a USD ceiling), unknown cost, provider failure and an unsupported platform name.

**What it does not show:** real providers' behaviour. The quota, login and crash events came from stand-ins, the
expiries and the platform name were injected, and the providers' own authentication was never exercised (repo-ai
reads no credential, so a configured but logged-out login is only discovered by a run). Linux was not run (the routing
logic is platform-independent except for containability, which P1 and the 2026-11-01 matrix cover). Real host
observations without injection, on this Mac on 2026-11-02 (`agents route --allow-live-provider`): bob first in the
default order and eligible; Claude `SETUP_REQUIRED` (no dedicated
login), Codex and agy `ISOLATED_READY` but refused under a USD ceiling (cost not capped by their CLIs), OpenCode
`SETUP_REQUIRED` (no local model configured).
