# repo-ai documentation

Start with the [project README](../README.md), then [STATUS.md](STATUS.md)
for what is stable, experimental or unsupported. This page only lists the
documents; nothing has moved.

## User guides

| Document | What it covers |
|---|---|
| [STATUS.md](STATUS.md) | what is stable, experimental, disabled or unsupported, with evidence links |
| [RELEASE-READINESS-2026-10.md](RELEASE-READINESS-2026-10.md) | the release gates, their status, and why this is not yet a release candidate |
| [VDE-SCOPE-2026-10.md](VDE-SCOPE-2026-10.md) | what this release builds of the Verified Development Engine, and what it defers, with what would justify each |
| [GETTING-STARTED.md](GETTING-STARTED.md) | the one path (install → initialize → understand → change → verify → prove → review), three configurations, where it runs |
| [PROOFLAB.md](PROOFLAB.md) | `repo-ai prove` (experimental): a pinned claim and scenario, before and after, a verification passport for the PR |
| [PROOFLAB-AB-PROTOCOL.md](PROOFLAB-AB-PROTOCOL.md) | the protocol (not run) for measuring whether ProofLab helps coding agents |
| [VERIFY.md](VERIFY.md) | `repo-ai verify`: the plan, sandboxed runs, evidence, limitations |
| [CLAUDE_CODE.md](CLAUDE_CODE.md) | what `init --agent claude` writes, the hooks, skills and subagents |
| [CONFIGURATION.md](CONFIGURATION.md) | every configuration key, with defaults and precedence |
| [CAPABILITIES.md](CAPABILITIES.md) | the capability registry, the ruff security adapter, discovery (experimental) |
| [SKILLS.md](SKILLS.md) | the skill lifecycle, workflows and orchestration |
| [SKILL_NETWORK.md](SKILL_NETWORK.md) | third-party skills: `inventory`, `vet`, the firewall, install, trials |
| [LEARNING.md](LEARNING.md) | learned rules, generated skills and learning signals |
| [RETRIEVAL.md](RETRIEVAL.md) | how `repo-ai context` ranks files, and its measured quality |
| [CROSSREPO.md](CROSSREPO.md) | opt-in cross-repository features, by zone |
| [OPTIMIZATION.md](OPTIMIZATION.md) | optimisation proposals, the governor, Stack Packs |
| [CODING_LAB.md](CODING_LAB.md) | the coding performance lab and grading sandbox (billable when run) |
| [SECURITY.md](SECURITY.md) | security and privacy |
| [COMPATIBILITY.md](COMPATIBILITY.md) | compatibility and migrating from repo-ai 0.4 |

## Contracts and design

| Document | What it covers |
|---|---|
| [VERIFY-AGENT-CONTRACT.md](VERIFY-AGENT-CONTRACT.md) | `verify` for agent integrations: decisions and the contract, including the gate |
| [CAPABILITY-AGENT-CONTRACT.md](CAPABILITY-AGENT-CONTRACT.md) | how an agent selects a capability (`candidates`, `select`) |
| [VERIFY-THREAT-MODEL.md](VERIFY-THREAT-MODEL.md) | the threat model for `verify` |
| [VERIFY-WATCHDOG.md](VERIFY-WATCHDOG.md) | the per-test watchdog: design and acceptance criteria (not implemented) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | the architecture |
| [ARCHITECTURE-DECISION-0.8.md](ARCHITECTURE-DECISION-0.8.md) | the decision to make repo-ai a change-verification engine |
| [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | the 0.6.0 product spec |

## Research, evaluations and reviews

These record what was measured, including the negative results. They are not
usage guides.

| Document | What it covers |
|---|---|
| [EVALUATION.md](EVALUATION.md) | the offline task suite and the live evaluation design |
| [VERIFY-RELEASE-REVIEW-2026-10.md](VERIFY-RELEASE-REVIEW-2026-10.md) | release readiness of the verify engine: merged as experimental, not ready to release |
| [VERIFY-INTEGRATION-REVIEW-2026-10.md](VERIFY-INTEGRATION-REVIEW-2026-10.md) | the corrections after the merge, and the release blockers |
| [VERIFY-AUDIT-2026-10.md](VERIFY-AUDIT-2026-10.md) | the pre-release audit of verify |
| [VERIFY-DEMOS.md](VERIFY-DEMOS.md) | recorded verify demonstrations |
| [PRODUCT_REVIEW-v0.8.md](PRODUCT_REVIEW-v0.8.md) | the 0.8 product review and direction |
| [RESEARCH-2026-10.md](RESEARCH-2026-10.md) | competitive research: code intelligence, test selection, agent integration |
| [EXPLORATORY-v2-pairs.md](EXPLORATORY-v2-pairs.md) | the exploratory Core vs plain Claude run on sealed-v2 |
| [SEALED_V2.md](SEALED_V2.md) | the sealed-v2 benchmark |
| [STATISTICS_COVERAGE.md](STATISTICS_COVERAGE.md) | coverage of the task-clustered success interval |

The evaluations behind the skills and capabilities claims, in this repository (preregistered, with their data):
- [../benchmarks/skill-vet-fresh-v1/RESULTS.md](../benchmarks/skill-vet-fresh-v1/RESULTS.md): skill vetting on 80 fresh cases, **failed** its main gate: opt-in `SAFE_AUTO` would have installed 8 of 30 harmful skills without asking. Hardened on `main` afterwards (not yet released); a re-run on the same corpus is not a confirmation, and the fresh confirmation (skill-vet-fresh-v2) is blocked;
- [../benchmarks/capability-fresh-v1/RESULTS.md](../benchmarks/capability-fresh-v1/RESULTS.md): capability discovery on 60 fresh tasks, **failed** recall and constraints.

Earlier evaluations whose files stay in the private development history (their figures are in
[STATUS.md](STATUS.md) and [CAPABILITIES.md](CAPABILITIES.md)): the fresh plugin-vetting run (**failed**), capability
discovery Corpus C (**failed**), `skills vet` and `inventory` on real skills, and the offline capability registry
evaluation (both held-out corpora failed recall).

## Preregistrations and experiment plans

Written before the experiments they describe. Results live in the documents
above and under `benchmarks/`.

| Document | What it covers |
|---|---|
| [PREREGISTRATION.md](PREREGISTRATION.md) | Option A: plain Claude Code vs repo-ai Core vs Full |
| [PREREGISTRATION-v2.md](PREREGISTRATION-v2.md) | repo-ai 0.7.6 on sealed-v2 |
| [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) | proposed live experiments |
| [../benchmarks/skill-vet-fresh-v1/PREREGISTRATION.md](../benchmarks/skill-vet-fresh-v1/PREREGISTRATION.md) | fresh skill-vetting corpus (run; failed) |
| [../benchmarks/skill-vet-fresh-v2/PREREGISTRATION.md](../benchmarks/skill-vet-fresh-v2/PREREGISTRATION.md) | the confirmation corpus for the skill-scanner fix (blocked: needs a human-written or published corpus) |
| [../benchmarks/capability-fresh-v1/PREREGISTRATION.md](../benchmarks/capability-fresh-v1/PREREGISTRATION.md) | fresh capability-discovery corpus (run; failed) |
