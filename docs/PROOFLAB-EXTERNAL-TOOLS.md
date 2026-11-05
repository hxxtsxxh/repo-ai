<!-- Researched by a subagent with web search on 2026-10-24; nothing was installed or run. Facts it could not confirm are listed at the end. -->

# ProofLab: research on external tools

Date: 2026-10-24. Scope: which external technologies would help `repo-ai prove` show that the
**same pinned oracle fails at the base revision and passes at the candidate**, and what a later
opt-in adapter contract has to describe. I installed, cloned and ran nothing. Versions and licences
come from public pages fetched today; a version marked "unverified" means the sources disagreed.

## 0. Summary

- **MVP: no external integrations.** The core proof is "pytest runs the pinned test bytes in the
  existing sandbox at two revisions". repo-ai already does every part of that. None of the tools
  below is needed to demonstrate it, and each one adds execution risk, network use or size.
- **Treat Hypothesis as part of the oracle, not as an integration.** If a pinned test uses it,
  ProofLab only has to make its randomness deterministic (seed, no example database carried between
  runs). That is a small fix to how the scenario runs, not an adapter.
- **GitHub: produce output files only.** The check-runs write API is open only to GitHub Apps, so
  `gh` with a user token cannot create check runs. The passport Markdown is written so it can be
  pasted as-is, or posted by the user with `gh pr comment --body-file`. It also fits within the
  Actions job-summary limit.
- **The passport should be expressible as an unsigned in-toto Statement v1** with a custom
  `predicateType`. Signing it (cosign/Sigstore) and SLSA claims are left for later and are
  explicitly *not* claimed now.

## 1. What a tool has to contribute

"Baseline fails / candidate passes" counts as evidence only if:

1. **Oracle identity.** The same scenario bytes run at both revisions. At base, the pinned test file
   is laid over the base copy. Its sha256 is in the passport.
2. **Right-reason failure.** At base, the failure is an *assertion failure inside the pinned test
   ids*. A collection error, ImportError, timeout or sandbox denial does not count, or at most counts
   as "weak". An ImportError for a symbol that did not exist yet is a legitimate but weaker failure
   and should be labelled that way.
3. **Stability.** Each side is repeated k times (k=2 or 3 is cheap) to rule out flakiness. Seeds and
   randomness are pinned.
4. **No regressions.** This is the existing base-vs-candidate failure comparison.
5. **Environment record.** Interpreter, platform, sandbox backend, dependency lockfile digests,
   environment allowlist and network policy.

A tool is "useful" below only if it strengthens one of points 1 to 5.

## 2. Evaluation of each technology

Columns: **Use** = how much it helps the base-fails/candidate-passes proof. **Exec risk** = whether
it executes repo code, needs network, browsers or daemons. **Port.** = L/M/W (Linux/macOS/Windows).
**Local?** = whether it is typically already on a developer machine.

### 2.1 Primary candidates

| Tech | Use | Exec risk | Maintenance | Port. | Licence (2026) | Local? | Cost |
|---|---|---|---|---|---|---|---|
| **Hypothesis** 6.170.9 (2026-10-23) | **High when the repo already uses it.** A property is a strong oracle. The base counterexample can be replayed at the candidate. | It runs inside the repo's own test run: same risk as pytest, no network. The `.hypothesis/` DB writes state. | Low if treated as "part of pytest". ProofLab only pins `derandomize`/seed and isolates the DB. | L/M/W | MPL-2.0 | Only if it is a project dependency | Free |
| **Playwright** (Python ~1.62, Jul 2026) | High for web UI claims, none for library/CLI claims. | Executes the app plus a browser. Needs browser binaries (hundreds of MB, downloaded), a running app server and loopback networking. Browser sandboxes conflict with bwrap/seatbelt. | High: browser versions, server lifecycle, traces, flakiness. | L/M/W (OS deps on Linux) | Apache-2.0 | Rarely | Free; disk and CPU |
| **ast-grep** 0.44.x (unverified; 0.42.1 confirmed Apr 2026) | Low to medium. Static checks on the *oracle*: pinned test has no `skip`/`xfail`, contains assertions, refers to changed symbols. | Does not execute repo code. No network. Single Rust binary. | Low, but every rule is code we own. For Python, stdlib `ast` does the same with no dependency. | L/M/W | MIT | Rarely | Free |
| **pyright / basedpyright** 1.40.2 (2026-10-04) | Low. "Does the test reach the changed symbol" through cross-file references. Type errors are not behavioural proof. | Static. pyright needs Node (npm or bundled). LSP server process. | Medium to high: LSP session management, config inference, version drift. | L/M/W | MIT | Sometimes (editors) | Free |
| **tsserver** (TypeScript) | Same as above, for JS/TS. | Static. Node required. | High: tsserver protocol is not standard LSP without a wrapper. | L/M/W | Apache-2.0 | When TS is present | Free |
| **jedi** | Low. Lightweight Python reference lookup. | Static (it may import stubs). Pure Python. | Low to medium; heuristic, misses dynamic dispatch. | L/M/W | MIT | Often (IPython dependency) | Free |
| **Containers** (podman 6.0, Jul 2026; Docker) | Medium. Hermetic environment; image digest gives environment provenance. **repo-ai already has backends.** | Executes repo code (that is the point). Needs a daemon or VM (podman machine on macOS/Windows); pulling images needs network. | Already paid for. Main cost is image pinning. | L native; M/W through a VM | Podman Apache-2.0; Docker Engine Apache-2.0; Docker Desktop has paid tiers for larger orgs | Often | Free (Docker Desktop terms vary) |
| **mutmut** 3.8.0 (2026-09-12) | Medium, but answers a *different* question (oracle strength in general). Base failure already shows the oracle tells these two revisions apart. | Executes repo tests N times (once per mutant). Writes `mutants/`. | Medium. Long runtimes. | L/M; **Windows only through WSL** (needs fork) | BSD-3-Clause | Rarely | CPU time (N × suite) |
| **cosmic-ray** 8.7.0 (2026-08-09) | Same as mutmut. | Same. Session DB, optional distributed workers. | Medium to high (config, distributors). | L/M/W ("OS Independent") | MIT | Rarely | CPU time |
| **StrykerJS** 9.6.1 (10.0 reported Aug 2026, unverified) | Same, for JS/TS. | Executes JS tests N times. Node. | Medium. | L/M/W | Apache-2.0 | Rarely | CPU time |
| **GitHub PR integration** (gh CLI) | Distribution only. Adds no proof strength. | Network plus credentials. Writes to a shared system. | Low (comment/summary) to high (check runs need a GitHub App). | L/M/W | gh: MIT | Often | Actions minutes if run in CI |
| **in-toto Statement v1 / SLSA / Sigstore** | Medium for *portability* of the passport, not for the proof itself. | Unsigned statement: none. Keyless signing: network (Fulcio/Rekor) plus OIDC identity. | Low (unsigned JSON) to medium (signing, verification policy). | L/M/W | Spec Apache-2.0; cosign Apache-2.0 | cosign: rarely | Free (public-good Sigstore) |

### 2.2 Secondary candidates (brief)

| Tech | Use | Exec risk | Port. | Licence | Notes |
|---|---|---|---|---|---|
| **schemathesis** 4.32.4 (2026-10-22) | Medium for API claims (an OpenAPI property as the oracle). | Sends real requests to a running server and can create or delete data. Needs a server, plus network if not loopback. | L/M/W | MIT | Built on Hypothesis; would inherit the seed rules. |
| **Pact** (Rust core, FFI) | Low to medium. Consumer-contract claims across services. | Mock server process; a broker means network. | L/M/W | MIT | Two-party workflow; does not fit one repo with two revisions. |
| **semgrep** CE / **opengrep** | Low. Static security delta (new findings at the candidate). Not behavioural. | Static. Registry rules are fetched over the network. | L/M (Windows partial) | Engine LGPL-2.1; **community rules under the restrictive Semgrep Rules License**; opengrep LGPL-2.1 | Watch the rule licence if rules are redistributed. |
| **bandit** 1.9.4 (Feb 2026) | Low. Python security lint delta; SARIF output. | Static AST. No network. | L/M/W | Apache-2.0 | Cheap; could be a "regression lint" adapter later. |
| **testcontainers** (Python) | Medium for database-backed claims. | Needs the Docker API (podman socket works with configuration). Pulls images over the network. Starts sidecars. | L; M/W through a VM | Apache-2.0 (I could not fetch the PyPI page; verify) | Conflicts with `--network=none` sandboxes. |
| **toxiproxy** 2.12.0 | Low to medium for resilience claims ("retries on timeout"). | Proxy daemon; TCP on loopback. | L/M/W | MIT | Little release activity in 2026. |
| **coverage.py** 7.17.0 (2026-10-22) | **Medium.** Shows the pinned test *executes the changed lines* at the candidate (relevance evidence). | Runs inside the test process; same risk as pytest. | L/M/W | Apache-2.0 | `sysmon` core is the default on Python 3.14+ (fast). Best first post-MVP adapter. |
| **sys.monitoring** (PEP 669, Python 3.12+) | Same as coverage, stdlib. | Needs a hook injected into the test process, which changes the oracle's environment. | L/M/W | PSF | Prefer coverage.py over writing our own tracer. |
| **OpenTelemetry** | Low. Traces of distributed behaviour. | SDK in-process; an exporter or collector means a daemon or network. | L/M/W | Apache-2.0 | Too heavy for a local proof. |

### 2.3 Notes on each technology

**Hypothesis.** Two pitfalls matter for ProofLab.
1. A base failure can be *random*: on some seeds the search may not find the counterexample. Run
   with `derandomize=True` (or a fixed `--hypothesis-seed`) and set `database=None`. Otherwise the
   `.hypothesis/examples` DB replays failures across runs and silently changes the oracle.
2. A deliberate improvement: shrinking at base produces a minimal falsifying example. It can be
   recorded in the passport and, optionally, pinned as `@example(...)` so the candidate run replays
   exactly that input. In the MVP, record the falsifying-example text that Hypothesis prints. Do not
   rewrite the test.

**Playwright.** Its traces would make web proofs much stronger. The cost is browser downloads (the
2026 releases made browser install opt-in to keep images small), a server lifecycle, and browser
sandboxes that must run inside bwrap or seatbelt. Defer until there is a concrete web demo.

**ast-grep / stdlib `ast`.** The useful static checks are about the *oracle*, not the code. Does
the pinned test contain `assert` or `pytest.raises`? Is it free of `skip`/`xfail`/`importorskip`?
Do the test ids exist in the pinned bytes? Python's `ast` covers all of this with no dependency.
ast-grep becomes worth adopting only when JS/TS scenarios arrive.

**Compiler/LSP.** These answer "the test refers to the changed symbol", but dynamic dispatch makes
the answer approximate. Coverage gives *observed* reach and is strictly better evidence for a
behavioural claim. Not recommended.

**Containers.** Already integrated. For the passport, add `image@sha256:` digests and
`--network=none`. On macOS and Windows a VM sits in between (podman machine: applehv/libkrun
providers), so wall-clock numbers are not comparable across hosts.

**Mutation testing.** It is the classic "is the oracle strong" measure, but it costs one suite run
per mutant. It is a natural future "oracle-strength" adapter that runs only the pinned test against
mutants of the *changed hunks*. That cuts the cost from N × suite to M × one test.

**GitHub.**
- The check-runs write API is "only available to GitHub Apps". "OAuth apps and authenticated users
  are not able to create them". Up to 50 annotations per request; `output.summary` is at most 65,535
  characters; conclusions include `success`/`failure`/`neutral`/`skipped`.
- `GITHUB_STEP_SUMMARY` allows 1 MiB per step and shows 20 step summaries per job. The `::error
  file=,line=` workflow commands give annotations without an App.
- MVP: emit `passport.md`, sized to stay well under 65 KB, and print the `gh pr comment <n>
  --body-file passport.md` command for the user to run. ProofLab itself does not touch the network.

**Provenance.**
- SLSA Provenance (`https://slsa.dev/provenance/v1`; spec v1.2 is current) describes *builds*. Its
  `buildDefinition`/`runDetails` shape is a good model for recording the environment, but claiming
  SLSA levels from a local, self-run tool would be misleading.
- SLSA VSA (`https://slsa.dev/verification_summary/v1`) has `verificationResult: PASSED|FAILED`
  plus a `policy` descriptor. It is conceptually close, but it is bound to SLSA levels.
- in-toto `test-result/v0.1` (`result`, `configuration`, `passedTests`, `failedTests`) describes
  *one* run, not a base/candidate pair. Reuse its field names inside our predicate.
- cosign 2.6.0+ can sign a pre-built Statement (`attest-blob`). Verification had predicate-type
  check bugs that were fixed in 3.0.6 and 2.6.3, so pin a minimum version if signing is ever added.
  Keyless signing needs network plus OIDC, so it is opt-in and post-MVP.

## 3. Recommendation (a): MVP integration

**Zero substantial external integrations.** The concrete demonstration can be shown end to end
with what repo-ai already has: a pinned pytest file and ids, run in a bwrap/seatbelt disposable
copy at base and at candidate, k repeats each, plus the existing regression engine.

Small internal steps that need no new dependency:
- Hypothesis handling: when the pinned file imports `hypothesis`, pass the pytest plugin's
  `--hypothesis-seed=<fixed>` and record the seed. Also leave the repo's `.hypothesis/` example DB
  out of every disposable copy (a fresh copy for each repeat). That stops a saved failure from
  replaying and quietly changing the oracle. A project-defined `--hypothesis-profile` may also set
  `database=None`, but do not rely on the project having one.
- Stdlib-`ast` checks of the oracle: has assertions, no skip/xfail, ids present.
- Failure classification: assertion vs import/collection vs timeout vs sandbox denial.
- `passport.json` written as an in-toto Statement, plus `passport.md`.

**If one integration is ever needed** (for example a demo has to show the test *exercises* the
change), pick **coverage.py**, run only when it is already installed in the project environment. It
is Apache-2.0, cross-platform and has no network. The one condition is that coverage runs in a
*separate* candidate pass, so the oracle runs themselves stay unmodified.

## 4. Recommendation (b): minimal adapter contract

Each adapter declares a static manifest before it runs. Its result is checked against the declared
schema. Field names are the ones I suggest using.

| Field | Meaning | Type / values |
|---|---|---|
| `id`, `version` | Adapter identity and the tool version it pins | `"coverage-py"`, `"7.17.0"` |
| `tool_digest` | Digest of the executable or wheel or image actually used | DigestSet (`sha256`, or `image` digest) |
| `executes_repo_code` | Whether repository code runs | `none` / `tests-only` / `app-server` / `arbitrary` |
| `permissions.fs` | Filesystem scope | `read-copy` / `write-copy` / `write-outside` (refused) |
| `permissions.processes` | Long-lived processes or daemons | `none` / `subprocess` / `daemon` / `vm` |
| `network` | Network need | `none` / `loopback` / `egress:<hosts>` / `fetch-at-setup` |
| `credentials` | Secrets needed | `none` / list of env names (never values) |
| `execution` | How often it runs and where | `{runs: once\|per_side\|per_mutant, sides: [base,candidate], deterministic: bool, seed_param}` |
| `resources` | Limits it promises to respect | `{timeout_s, max_rss_mb, disk_mb, est_runtime_factor}` |
| `cost` | Money and quota | `{paid: bool, metered_by: null\|"actions-minutes"\|"api"}`; paid ⇒ needs explicit approval |
| `output_schema` | Versioned schema of `result` | URI + version (e.g. `repo-ai/adapter/coverage/v1`) |
| `completeness` | What a clean result means | `exhaustive` / `sampled` / `heuristic` / `best-effort`, plus `skipped[]` with reasons |
| `status` | Outcome classification | `ok` / `inconclusive` / `tool-error` / `denied` / `timeout` |
| `provenance` | What was observed | `{argv, env_allowlist, started, finished, stdout_sha256, artifacts[{name,digest}]}` |
| `platforms` | Supported OS list | `[linux, macos, windows]` |

How each technology would fill the contract:

| Tech | executes_repo_code | network | processes | execution.runs | completeness | cost |
|---|---|---|---|---|---|---|
| Hypothesis (inside the oracle) | tests-only | none | subprocess | per_side (k×) | `sampled` (seeded) | free |
| coverage.py | tests-only | none | subprocess | once (candidate) | `exhaustive` for executed lines | free |
| ast-grep / stdlib ast | none | none | none / subprocess | once | `heuristic` | free |
| pyright / jedi | none | none (pyright: Node) | daemon (LSP) | once | `heuristic` | free |
| Playwright | app-server | loopback (+ fetch-at-setup for browsers) | daemon | per_side | `sampled` | free; heavy |
| podman/docker | arbitrary (in a container) | none or fetch-at-setup (pull) | vm/daemon | per_side | n/a (environment) | free |
| mutmut / cosmic-ray / Stryker | tests-only | none | subprocess | per_mutant | `sampled` (mutant set) | CPU |
| schemathesis | app-server | loopback | daemon | per_side | `sampled` | free |
| testcontainers / toxiproxy | arbitrary + sidecars | fetch-at-setup + loopback | daemon | per_side | n/a | free |
| semgrep / bandit | none | semgrep: egress (registry) / bandit: none | subprocess | per_side (finding delta) | `heuristic` | free (semgrep paid tiers) |
| gh PR comment / check run | none | egress:api.github.com | subprocess | once | n/a | Actions minutes if in CI |
| cosign signing | none | egress (Fulcio/Rekor) | subprocess | once | n/a | free |

Rules that follow from the contract:
- An adapter whose `network` is anything other than `none` cannot be enabled by default.
- An adapter with `cost.paid=true` needs explicit per-run approval. This matches the repo's existing
  "ask before any paid run" policy.
- `completeness != exhaustive` must appear in the passport. It cannot be turned into a pass.

## 5. Recommendation (c): passport as an in-toto Statement v1

**Yes.** Emit `passport.json` as an **unsigned** in-toto Statement v1. The cost is close to zero.
It makes the passport signable later with no format change (DSSE envelope with payloadType
`application/vnd.in-toto+json`; cosign `attest-blob` on a pre-built statement). The spec says
consumers MUST ignore unknown fields. The passport must still state plainly that it is
**self-attested and unsigned**.

Statement v1 layout. `_type` is fixed. `subject[]` is required and each element MUST have `digest`.
`predicateType` is a required TypeURI. `predicate` is optional; if absent it is treated as empty.

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [
    { "name": "candidate", "digest": { "gitCommit": "<40|64 hex>", "gitTree": "<hex>" } },
    { "name": "change.patch", "digest": { "sha256": "<sha256 of canonical diff = change fingerprint input>" } }
  ],
  "predicateType": "https://repo-ai.invalid/prooflab/passport/v0.1",
  "predicate": {
    "claim": { "text": "...", "sha256": "..." },
    "scenario": {
      "files": [ { "name": "tests/test_x.py", "digest": { "sha256": "..." } } ],
      "testIds": ["tests/test_x.py::test_claim"],
      "runner": { "name": "pytest", "version": "..." },
      "seeds": { "hypothesis": "...", "PYTHONHASHSEED": "0" }
    },
    "base":      { "revision": { "digest": { "gitCommit": "..." } }, "repeats": 3,
                   "result": "FAILED", "failureKind": "assertion", "failedTests": ["..."] },
    "candidate": { "revision": { "digest": { "gitCommit": "..." } }, "repeats": 3,
                   "result": "PASSED", "passedTests": ["..."] },
    "regressions": { "engine": "repo-ai verify", "newFailures": [], "completeness": "exhaustive|partial" },
    "environment": { "sandbox": "bwrap|seatbelt|podman", "network": "none",
                     "python": "3.12.x", "platform": "...", "image": { "digest": { "sha256": "..." } },
                     "lockfiles": [ { "name": "uv.lock", "digest": { "sha256": "..." } } ] },
    "adapters": [],
    "verdict": "PROVEN|WEAK|NOT_PROVEN|INCONCLUSIVE",
    "signed": false,
    "producer": { "id": "repo-ai", "version": "...", "fingerprint": "<repo-ai change fingerprint>" },
    "timeStarted": "...", "timeFinished": "..."
  }
}
```

Layout choices:
- **Subject = what the claim is about**: the candidate revision (`gitCommit`/`gitTree` are standard
  DigestSet keys) and the change bytes (`sha256`).
  - For uncommitted work, omit `gitCommit` and keep only `change.patch`.
  - The base revision and the scenario are *inputs*, so they go in the predicate as
    ResourceDescriptor-shaped `{name, digest}` entries.
  - A custom digest key such as `repoAiFingerprint` is allowed, but its encoding must be
    documented and consumers ignore unknown keys. Put the fingerprint in the predicate and use
    `sha256` in the subject.
- **predicateType**: a URI under a namespace the project controls, with the major version in the
  path (in-toto rule: the TypeURI carries the major version, minor versions are monotonic, and 0.x
  counts as major). Do not use a domain the project does not own. `.invalid` above is a
  placeholder.
- Reuse the in-toto `test-result/v0.1` vocabulary (`result: PASSED|FAILED`, `passedTests`,
  `failedTests`) per side, so tooling that already knows that predicate can read it.
- Leave out volatile data (timestamps, absolute paths) of any *digest you compute over the
  predicate*, but keep the timestamps in the predicate.
- Do not use `https://slsa.dev/provenance/v1` or claim SLSA levels. The SLSA VSA shape
  (`verificationResult`, `policy`) is a reference, not the type.

## 6. Sources

- in-toto Statement v1: https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md ; https://in-toto.io/Statement/v1
- in-toto parsing/versioning rules: https://github.com/in-toto/attestation/blob/main/spec/v1/README.md
- in-toto predicate guidance: https://github.com/in-toto/attestation/blob/main/spec/v1/predicate.md
- in-toto envelope (DSSE, payloadType): https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md
- in-toto DigestSet keys: https://github.com/in-toto/attestation/blob/main/spec/v1/digest_set.md
- in-toto test-result predicate: https://github.com/in-toto/attestation/blob/main/spec/predicates/test-result.md
- SLSA provenance v1.1 (v1.2 current): https://slsa.dev/spec/v1.1/provenance
- SLSA VSA: https://slsa.dev/spec/v1.2/verification_summary
- cosign attest-blob on pre-built statements and verification fixes: https://github.com/sigstore/cosign/blob/main/specs/BUNDLE_SPEC.md ; https://codegraph.jelmer.uk/cosign/3.1.1-1/CHANGELOG.md
- Hypothesis changelog: https://hypothesis.readthedocs.io/en/latest/changelog.html ; licence https://security.snyk.io/package/pip/hypothesis
- Playwright versions: https://www.piwheels.org/project/playwright/ ; https://testdino.com/blog/playwright-2026-new-features/ ; https://releases.sh/release/rel_vlVgKmDHiYfCjbGnYPaAx
- ast-grep: https://freshports.org/textproc/ast-grep/ ; https://simple-repository.app.cern.ch/project/ast-grep-py
- basedpyright: https://pypi.org/project/basedpyright/
- Podman 6: https://releasebot.io/updates/podman ; https://blog.podman.io/tag/podman-machine
- mutmut: https://pypi.org/project/mutmut/
- cosmic-ray: https://pypi.org/project/cosmic-ray/
- StrykerJS: https://www.jsdelivr.com/package/npm/@stryker-mutator/core ; https://nevercodealone.de/de/frontend-development/strykerjs-mutation-testing-javascript-typescript-2026
- GitHub check runs: https://docs.github.com/en/rest/checks/runs
- GitHub workflow commands / job summaries: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands
- schemathesis: https://pypi.org/project/schemathesis/
- Pact: https://docs.pact.io/implementation_guides/rust/
- semgrep / opengrep licensing: https://docs.semgrep.dev/faq/comparisons/opengrep.md ; https://thenewstack.io/opengrep-launches-as-free-fork-after-semgrep-license-shift/
- bandit: https://simple-repository.app.cern.ch/project/bandit
- toxiproxy: https://freshports.org/net/toxiproxy-cli ; https://licenses.dev/go/github.com%2FShopify%2Ftoxiproxy%2Fv2/v2.9.0
- coverage.py (sysmon default on 3.14+): https://coverage.readthedocs.io/en/latest/changes.html

Not verified today (stated from general knowledge; check before relying on them): the
testcontainers-python licence and podman-socket details (PyPI page failed to load), the gh CLI
licence (MIT), the OpenTelemetry licence (Apache-2.0), and the Docker Desktop subscription
thresholds.
