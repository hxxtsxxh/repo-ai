# Verified Development Engine: what this release builds, and what it defers (2026-10-25)

The final product mission lists thirteen phases. Session A's fresh evaluation of main showed that
verify could report passing where it should not (D1–D10). So this release is **correctness first**:
it closes those paths and hardens ProofLab. Each larger subsystem is deferred until it can be built
on that base **and** measured. A phase deferred here is not done, and nothing in the product claims it
is.

| Phase | In this release | Deferred, and what would justify it |
|---|---|---|
| 1. Correctness | #40–#43, #45 merged; **abstention**: `nothing-selected` never passes a behavioural change | a fresh evaluation of the integrated tree (Session A) |
| 2. ProofLab | `pin \| plan \| run \| status \| report`; Session A's F1–F5 and 16 earlier false proofs closed or documented; evidence contract 1.1 | the out-of-scope items stay out (hostile in-process tampering, local forgery); see `PROOFLAB.md` "Limits" |
| 3. Repository intelligence and retrieval | unchanged. Retrieval is already hybrid without vectors: exact path and symbol lookup, SQLite FTS5 BM25, the import graph, routes and intent signals, plus a token-budgeted context pack (`RETRIEVAL.md`) | **vectors:** a local embedding adapter is worth building only if it beats the current pipeline on a *fresh, independently labelled* task set. That set does not exist yet: the capability-discovery corpora are spent, and Corpus C failed. Building one is a Session A task (two labellers and a judge) |
| 4. Capability broker | unchanged: the registry with `prepare / approve / revoke / run` (a human binds an exact executable; refused from agent shells), and `candidates / select` (experimental). Keyword recommendation stays experimental, after its failed evaluation | structured capability contracts with DISCOVER → EVALUATE → AUTHORIZE, once an adapter needs them. The adapter fields are specified in `PROOFLAB.md` "External tools" |
| 5. Experiment design | none | a planner that *proposes* property, boundary or mutation experiments, labelled as proposals. It is not built, because no measurement says which proposals help |
| 6. Replay | none | HTTP or browser replay needs a project to demonstrate it on, and a dependency (Playwright) whose browser download this release does not take on |
| 7. Mission control | unchanged: `orchestrate plan` and `workflow plan` (plan-only) | a durable mission store (SQLite) with resume, budgets and approval gates: after a single-agent workflow shows a measured benefit |
| 8. Learning | unchanged: `learn`, opt-in, with evidence-gated suggestions | — |
| 9. One experience | `docs/GETTING-STARTED.md`: one path, three configurations, where it runs | `repo-ai mission` (Phase 7) |
| 10. Passport | contract 1.1 records; Markdown, JSON and unsigned in-toto output; **`prove report --publish-pr N`**, opt-in, fresh passports only, refuses public repositories without `--public-ok` | signed attestations need a signing identity and a verification path |
| 11. Demonstrations | 2 real upstream fixes (Python unittest and `node --test`), 10 controls each, 6+ runs | a full-stack/API demonstration with an external adapter: deferred with Phase 6 |
| 12. Production engineering | reproducible wheel and sdist, `uninstall`, offline operation, schema versioning, a migration note for abstention | Windows host sandbox; a fix for T7 (detached processes on macOS) |
| 13. Integration | batches in `RELEASE-INTEGRATION-2026-10-25.md`, one CI run on the exact tree, the spending ledger | — |

**Why not build more of it now:** each deferred item is a new surface for exactly the kind of false
assurance this release removes. None of them has a measurement saying it helps.
