# repo-ai product review and v0.8.0 direction (2026-10-21)

**Scope:** an evidence-based review of repo-ai 0.7.7 as a developer product.
- No implementation code was changed, nothing was released, and no model was
  called.
- No third-party skill was downloaded, approved, installed or run.
- The existing research reports are unchanged.

**Sources:**
- the 212 archived live runs (calibration, Option A, sealed-v2);
- a fresh offline tool audit on 15 public repositories
  (`benchmarks/audit-v0.7.7/`, scripts and raw results included);
- two read-only code and documentation audits;
- direct inspection of what `init` generates.

## Bottom line

repo-ai does not make Claude Code write more correct code, and its
always-loaded guidance has measurable failure modes. Its one capability that
is clearly better than simple tools is **change-impact test selection**:
- across 123 detected mutations, its recommended tests contained every
  failing test file in 86–89% of cases;
- the best grep heuristic managed 50%.

v0.8.0 should become a **local change-impact and verification tool** that
developers and agents call on demand. Always-on context injection, learned
rules, subagents and the skill network should become opt-in or experimental.

## 1. What the live runs show the model actually used

| Across the archived live runs | Count |
|---|---|
| Skill invocations (any skill, including repo-ai's) | **0** of 212 runs |
| Subagent calls | **0** of 212 runs |
| Bash calls of the `repo-ai` CLI by the agent | **0** of 200 runs (Option A and sealed-v2) |
| Bash commands reading `.repo-ai/context/*` or CLAUDE.md | **0** of 200 runs. Read-tool paths were not recorded, so Read use is unknown |

**What the model did receive:** the CLAUDE.md block, about 130 words always
loaded, and the prompt hook's shortlist, about 270 tokens per prompt (268 in
Option A, 273 in sealed-v2).

**Everything else** went unused in every recorded run:
- the 15 installed skills (6 model-visible);
- the generated docs (about 2,800 words in 10 files per repository);
- the subagents, skeptic and orchestration hint (Full).

## 2. Capability inventory

### 2.1 Proven to work correctly offline (tested, and measured here or before)

- **Indexing:**
  - deterministic;
  - incremental equals rebuild;
  - 1.3–3.6 s for `init` on repositories up to 147k lines of Python (sqlglot);
  - no network on default paths.
- **Symbol lookup:** recall 1.00 against Python AST ground truth on all 15
  repositories. The few precision losses are mostly `.pyi` stubs, which are
  arguably correct hits.
- **Import graph and impact:** see §3.2.
- **Hooks:** fail open; about 74 ms p50; never store prompt text; never block
  the agent.
- **Uninstall:** byte-exact removal of what repo-ai owns; user-authored files
  are preserved (acceptance demo 81/81).
- **Privacy defaults:**
  - no telemetry;
  - secret quarantine;
  - the `privacy` audit;
  - zone isolation for the opt-in registry.
- **Experiment infrastructure:**
  - the sandboxed grader;
  - the budget gate;
  - blinding;
  - proof-of-access integrity checks;
  - task-clustered statistics.
  
  This is solid research tooling, not a user feature.

### 2.2 Usefulness demonstrated independently of unit tests

- **Impact-based test selection** (§3.2): far higher recall than grep
  heuristics on 10 real projects.
- **The `review` change passport:** fast (0.16 s), and it combines what the
  diff touches, the reverse dependencies, recommended tests, a secret scan of
  added lines, and the blind spots. Its value rests on the same impact engine.
- **Localization on the `final` set:** recall@5 0.853 vs grep's 0.580.
  - This **did not replicate** on held-out or fresh tasks (§3.1), so it is
    not robust evidence.

### 2.3 Implemented but never exercised meaningfully

| Feature | Status | Exercised live? |
|---|---|---|
| Subagents, skeptic, orchestration (Full) | — | never invoked in 150 Option A runs |
| repo-ai's own skills (`/repo-locate`, `/repo-impact`, `/repo-verify`, …) | — | 0 invocations in 212 runs |
| Third-party skill network (discover → install → trial → promote) | offline with fakes only; GitHub install path untested | never |
| Skill trials and tournaments, canary Fisher test, promotion stages | — | never run live |
| Outcome learning, the "Self-Improvement Governor", `optimize`, `performance`, `friction` | proxies and simulated sessions only | no real data |
| Stack Packs, cross-repo registry | offline tests only | never |
| Tier-2 skill drafting (calls Claude) | fake client only | never |
| IBM Bob integration | unit tests only | never against Bob |

### 2.4 Overhead without demonstrated value

- **Prompt hook shortlist:** about 270 tokens per prompt.
  - On fresh tasks its ranking equals grep's, and it contained all gold files
    on only 40% of sealed-v2 tasks.
  - Claude greps on its own (54–100 Grep calls per 25–50 runs).
- **Generated context docs:** 10 files, about 2,800 words. They are never
  read by Bash in live runs, and some labels are wrong: `ARCHITECTURE.md`
  classifies the `markdown` library package as a "service".
- **Fifteen installed skills** (9 manual-only). Their descriptions cost 141
  words of always-loaded context, with 0 invocations.
- **Learned rules:** low-value items such as "functions use snake_case
  (87%)", plus the incorrect rules in §3.4.
- **Full:** about 10% higher cost than Core in Option A, with no feature ever
  used.

### 2.5 Descriptions that overstate the evidence

Most misleading, with file references; a full table is available from the
audit:

1. **`docs/LEARNING.md:3,15`:** "guidance it can **prove**"; "safe rules are
   applied".
   - An auto-applied, "evidence-backed" lint rule caused Option A's one
     measured harm.
   - §3.4 shows two more incorrect auto-applied rules.
2. **README:** the Before/After framing ("spends tokens and turns exploring").
   Core and Plain cost the same in both controlled experiments.
3. **README:** "repo-ai itself makes no model calls" and "the one exception is
   `--summarize`". `skills draft`, `eval coding` and skill trials also call
   Claude, and `skills updates` always uses the network.
4. **`docs/PRODUCT_SPEC.md:72-75` and `docs/EVALUATION.md:174-176`:** "live
   evaluation has not been run". Three were run, and none showed a benefit.
5. **SKILL_NETWORK.md and README:** "measure whether the skill helps",
   "measured benefit", "vetted".
   - No trial has ever run.
   - Vetting is regex-based static analysis.
6. **SKILL_NETWORK.md:178:** promotion "only after a live trial… not worse".
   A 6-task pilot with difference ≥ 0 suffices.
7. **"Self-Improvement Governor":** it adjusts two retrieval limits from a
   proxy and has never been shown to improve anything.
8. **README:** subagents listed as what Claude gets. Core, the default, does
   not install them.
9. **"About 185 tokens" per prompt:** a fixture figure. Real repositories
   average about 270.
10. **CLAUDE_CODE.md:** the Verify line's benefit is "unverified until a new
    controlled evaluation".
    - sealed-v2 was that evaluation.
    - Core ran tests three times as often, with no correctness gain.

## 3. Offline tool audit (no model calls)

### 3.1 Task-specific context retrieval (localization)

| Set | n | repo-ai recall@5 / all-gold@5 / MRR | naive grep | MRR better / worse | Paired p |
|---|---|---|---|---|---|
| `final` (real repos; examined in 0.7.2) | 25 | 0.853 / 0.800 / 0.606 | 0.580 / 0.560 / 0.420 | 11 / 8 | 0.09 |
| holdout (synthetic) | 35 | 0.703 / 0.629 / 0.572 | 0.735 / 0.714 / 0.520 | 12 / 14 | 0.63 |
| **sealed-v2 (fresh for localization)** | 25 | **0.503 / 0.360 / 0.542** | **0.550 / 0.360 / 0.546** | 10 / 9 | 0.88 |

- **On the only fresh, never-examined real-repository set, repo-ai's ranking
  is indistinguishable from naive grep.**
- The `final` advantage did not generalize. sealed-v2 is no longer unexamined
  for retrieval.
- **Redundant with Claude Code:** the agent already searches with Grep, Glob
  and Read.

### 3.2 Change-impact test selection

**Method:**
- In each of 10 projects, one function body at a time was replaced with
  `raise` (16 seeded mutations per project), and the project's real test
  suite was run in the network-less sandbox.
- 123 of 160 mutations broke at least one test.
- For each, the question is whether a method's selected test files include
  every failing file ("no miss").

| Method | No miss | Mean recall | Share of test files selected |
|---|---|---|---|
| `repo-ai impact <symbol>` | **109/123 (89%)** | 0.927 | 83% |
| `repo-ai impact <file>` | **106/123 (86%)** | 0.909 | 80% |
| grep: tests that import the module, or mention the function | 62/123 (50%) | 0.611 | 43% |
| grep: tests that mention the function | 35/123 (28%) | 0.343 | 15% |
| test file name matches the module | 25/123 (20%) | 0.250 | 9% |
| run every test | 123/123 | 1.000 | 100% |

**Interpretation:**
- **This is repo-ai's clearest advantage over simple tools.** Transitive
  import analysis finds the tests that actually fail far more reliably than
  grep or naming conventions.
- **The savings over running everything are modest:** about 80% of test files
  are still selected.
- **Its value is in ordering and focus,** not in replacing the full suite.
  "Targeted first, then the full suite" is the right guidance.

**Failure mode: confident and wrong.**
- On Python-Markdown, extensions are loaded by string name, and impact missed
  failing tests in **12 of 13** mutations.
- It still reported `risk: low` and `import_resolution_rate: 1.0`.
- The "dynamic imports not visible" caveat is printed for every repository,
  so it carries no signal.

**Output defects:**
- It suggests running non-tests as tests, for example
  `python -m unittest tests/__init__.py`, or `harness.py` in pyflakes.
- It prints one command per file instead of a single runnable command.

### 3.3 Search and symbol lookup

| | repo-ai `symbol` | ripgrep `^\s*(def\|class) NAME\b` |
|---|---|---|
| Recall (AST ground truth, 600 lookups) | 1.00 | 1.00 |
| Precision | 0.78–1.00 (stubs counted as extra) | 0.98–1.00 |
| Latency p50 | about 165 ms | about 23 ms |

**Verdict:** correct, but not better than ripgrep for Python, and 7× slower.
The structured fields (kind, signature, docstring, parent) are its only
advantage. Claude Code's Grep tool covers this.

### 3.4 Generated guidance: correctness problems found

The setup Core installs was regenerated on public repositories, including the
8 sealed-v2 bases (the Core arm's actual content).

1. **asn1crypto:** one file with a generated-code banner
   (`tests/unittest_data.py`) produced an auto-applied rule (confidence 0.9)
   declaring the whole of **`tests/` "generated output: do not hand-edit it."**
   - It is loaded whenever the agent touches `tests/**`.
   - The Core arm carried it on 4 sealed-v2 tasks.
2. **py-shop:**
   - The rule file says "Tests here use unittest… run the suite with
     `pytest`", inferred from a `[tool.pytest.ini_options]` section.
   - The CLAUDE.md Verify line says `make test`, which runs unittest.
   - Two instructions contradict each other.
3. **Earlier:** Option A's lint-only rule, fixed in 0.7.6.
4. **Honest uncertainty works:** for more-itertools and typing_extensions,
   the Verify line said it "could not establish a test command" instead of
   inventing one.

So "evidence-backed, auto-applied" rules have now produced three incorrect
instructions on fewer than 25 repositories. Auto-application is not safe
enough to be a default.

### 3.5 Other tools

- **Repository map and docs** (`map`, `architecture`, `overview`, `hotspots`,
  `conventions`, `deps`): correct inventories, mostly derivable from the file
  tree, the manifests and `git log`.
  - Some classifications are wrong (library labelled "service").
  - They are not read by the agent in recorded runs.
  - They overlap Claude Code's `/init`.
- **Co-change and hotspots:** derivatives of `git log`. They are useful in
  `review`, but not a differentiator.
- **`init` default:** with no `--agent`, it still targets IBM Bob, as in
  v0.4. It writes `.bob/context/` even with `--no-bob`, which is confusing for
  Claude Code users.
- **Explainability:** `explain` gives a per-file score breakdown. It is real
  and useful when debugging the ranking.

### 3.6 Skills intelligence: stage by stage

| Stage | Status today |
|---|---|
| Capability gap profile | Works offline. Heuristic, with 6 gap types. 4 keyword groups are dead: no profile ever produces those gaps |
| Online discovery | Partial. GitHub and allowlisted hosts work; skills.sh needs a token. The successful parsing path has no test; one manual live run, no saved output |
| Relevance ranking | A heuristic score that has never been evaluated (no labelled set). **Bug:** trial evidence is stored by skill name but looked up by candidate id, so the empirical term never applies |
| Security screening | Static only: pinned commit, hash check, regex rules, hidden-Unicode and injection phrases, front-matter allowlist. **Nothing is executed** (good). It misses semantic injection, indirect execution, multi-line exfiltration, and prose destructive commands (downgraded). "Review" findings and shipped scripts can each be overridden with one flag |
| Approval and installation | Works for local `--from-path`; the GitHub path is never tested. **Bug (verified):** every file is decoded as UTF-8 text on install, so binary assets are corrupted. What is trialled (raw bytes) differs from what is installed |
| Activation | An installed file in `.claude/skills/`. No third-party skill has ever been active in a live run, and repo-ai's own skills had 0 invocations in 212 runs |
| Measured usefulness | Never measured. Trials run on repo-ai's own suite, not the user's repository. The default 6-task trial is below the minimum for a verdict. "Harmful" is unreachable at that size; "promote" accepts a difference ≥ 0 |
| Network discipline | **`skills updates` always uses the network.** Its `--check` flag is ignored, and neither `updates` nor a GitHub `install` consults the zone's discovery policy, contrary to "nothing reaches the network unless you pass `--online`" |
| Trust in committed data | `promote` and Stack Packs trust trial evidence stored in the committed lockfile. A cloned repository can claim "evaluated, diff > 0" |

**Is online skill discovery useful today? No.**
- Discovery runs.
- Ranking is unevaluated, and screening is static.
- The install path has defects.
- No skill has ever been shown to help.
- The model did not invoke the skills it already had.

The safety design is careful and executes nothing, which is good. The
workflow is not a working product.

## 4. What is redundant with Claude Code

| repo-ai | Claude Code already has |
|---|---|
| `search`, `symbol`, prompt-hook shortlist | Grep, Glob and Read; the agent searches on its own and does so as well as the shortlist does (§3.1) |
| Generated CLAUDE.md block and context docs | `/init`, memory, and reading the repository |
| Subagents and orchestration | the built-in Explore and general-purpose agents |
| `security-review` gap coverage | the built-in `/security-review` |
| Skill management | the plugin and skill marketplaces, and native skill loading |

**Not redundant:**
- transitive impact and test selection with reasons;
- the pre-PR change passport;
- explainable ranking;
- local privacy auditing;
- the evaluation lab.

## 5. Should Core remain the default?

**Not in its current form.** Core has no measured benefit in either experiment
and no measured efficiency cost. Its always-loaded parts, however, have
produced incorrect instructions three times. When something brings no benefit
and carries a demonstrated risk of wrong guidance, it should not be on by
default.

**Recommended install modes:**

| Mode | What it installs | For |
|---|---|---|
| **advisory** (new default) | Index, CLI, and on-demand `/repo-impact` and `/repo-verify` skills. No prompt hook injection, no auto-applied rules, and at most a 2-line CLAUDE.md pointer | everyone |
| **core** (opt-in) | Today's Core: hooks, shortlist injection, Verify line, rules as *proposals* only unless approved | users who want ambient context |
| **full** (opt-in) | Today's Full | experimentation |

**Compatibility:**
- Existing installs keep their mode and settings: no silent change to anyone's
  Claude Code setup, including yours.
- `repo-ai init --feature-set core` restores today's behaviour.
- Uninstall stays byte-exact.

This is a recommendation; nothing has been changed.

## 6. Primary value proposition

> **repo-ai tells you, and your coding agent, exactly what a change touches
> and which tests prove it still works, locally, with evidence and honest
> uncertainty.**

**Supporting it:** the index, impact graph, `review` passport, `explain` and
the privacy guarantees.

**Not the value proposition:**
- "makes Claude smarter";
- self-improvement;
- skill discovery;
- multi-agent orchestration.

None of these has supporting evidence today.

## 7. The next three changes

### 7.1 Calibrated impact and verification: `repo-ai verify` / `impact --changed`

**Problem solved:** "I changed X. What must I run, in what order, and how sure
is that?" This applies to a developer before a commit and to an agent before
it says "done".

**Current evidence:**
- 86–89% no-miss vs 50% for the best grep heuristic (123 mutations).
- Confidently wrong on plugin and registry codebases: Markdown 1 of 13 with
  `risk: low`.
- It suggests non-test files as tests.

**Change:**
1. **Output:** one runnable targeted command (the selected tests in a single
   invocation), then the full-suite command.
2. **Non-tests:** drop helper and `__init__` files from the "tests" list.
3. **Confidence that means something:** detect string-based loading
   (`importlib`, `__import__`, entry points, `load_extension`-style
   registries, `getattr` dispatch on module names) and downgrade to "low
   confidence: run the full suite".
4. **One verified-run check:** a `--run` mode that executes the commands
   (opt-in; the user's own tests, on the host as they would run them).

**Expected benefit:** faster, ordered verification with an honest stop sign
where static analysis is blind. It directly serves the "avoid regressions"
goal.

**Complexity:** small to medium, about 300–500 lines, mostly in
`impact.py`, `testing.py` and `review.py`.

**Risk:** low. It is read-only by default, and `--run` executes only the
project's own test commands, as the user would.

**Validation without models:**
- the mutation benchmark in `benchmarks/audit-v0.7.7` (extend it to 15–20
  projects, including JS and TS);
- targets: no-miss ≥ 90% overall, 0 "low risk" labels on any repository where
  no-miss is below 50%, selected share reported;
- every suggested command must run in the sandbox.

### 7.2 Correct-by-construction guidance: no auto-applied rules by default, plus a consistency check

**Problem solved:** the always-loaded or path-loaded instructions that told
agents things that are false: "`tests/` is generated", "run pytest" in a
unittest/make project, and lint-only verification.

**Current evidence:** three incorrect instructions across fewer than 25
repositories. No measured benefit from rules.

**Change:**
1. **Rules become proposals** (`learn review`) unless approved.
2. **Generated-path rules:** require that most files under the directory be
   generated, not one banner.
3. **One source of truth for commands:** the verification plan. A rule may
   never name a runner that disagrees with it.
4. **Drop trivial style rules** (naming-percentage rules).
5. **A `doctor` check** that flags contradictions between CLAUDE.md, the rules
   and the manifests.

**Expected benefit:** removes the one class of harm repo-ai has actually
caused. Less always-loaded text.

**Complexity:** small, about 200–300 lines in `learning.py`, `testing.py` and
`claude.py`, plus tests.

**Risk:** low. For compatibility, rules already active in existing installs
stay active until re-derived. They are flagged, not deleted.

**Validation without models:**
- **Corpus test:** run `init` on 20+ public repositories. Check every
  generated instruction against ground truth: the runner the CI config uses
  must match, and the "generated" claim must cover at least 80% of a
  directory's files.
- Target: 0 contradictions and 0 false generated-directory rules.

### 7.3 Advisory-by-default install, honest claims, and the skill network gated as experimental

**Problem solved:** users get always-on machinery with no demonstrated benefit
and documentation that implies benefits. The one feature with external reach
(skills) has unverified safety paths.

**Change:**
1. **Install:** the `advisory` mode of §5 becomes the default for new
   installs. Existing installs are untouched.
2. **Documentation:**
   - rewrite the claims in §2.5;
   - update the stale "live evaluation not run" lines;
   - report the fresh localization result.
3. **Skills commands** move under `repo-ai skills … --experimental`.
4. **Disable GitHub installs** until the binary-corruption bug is fixed and
   the path has a test.
5. **Network policy:** make `skills updates` honour `--online` and the zone
   policy.
6. **Committed evidence:** stop trusting trial evidence from the committed
   lockfile. Re-verify it against the local experiment store.

**Expected benefit:** less overhead and lower risk of misleading users, with
no loss of any measured value.

**Complexity:** medium for the docs and install mode (about 300 lines, with
migration tests); small for the skill fixes.

**Risks:**
- Compatibility: users relying on the hook shortlist must opt in again, which
  is mitigated by keeping existing configurations as they are.
- Security improves.

**Validation without models:**
- the acceptance demo for each mode;
- byte-exact uninstall tests;
- a test that no network call happens without `--online`;
- a binary round-trip test for install.

**Not recommended now:**
- any new agents or skills;
- a retrieval rewrite (it would need a fresh sealed set first);
- an architectural rewrite. Nothing indicates one is needed: the core engine
  is fast and correct, and the problems are defaults and wrong instructions.

## 8. Roadmap (priority order)

1. **Correctness and reliability:** §7.2 rule correctness; §7.1 impact
   confidence and output fixes; the skill install bugs.
2. **Observable usefulness:** the `verify`/`review` workflow as the headline
   feature, measured with the mutation benchmark and command-execution checks.
3. **Minimal overhead:** advisory default; trimmed CLAUDE.md pointer; no
   shortlist injection unless opted in; fewer installed skills (only
   `/repo-impact` and `/repo-verify` by default).
4. **Privacy and security:** network only behind `--online`; untrusted
   lockfile evidence; doc correction on model calls.
5. **Clear user control:** explicit modes; `doctor` reports what is active and
   why.
6. **Measurable improvement:** every release reports the offline numbers
   (impact no-miss, guidance-correctness corpus, retrieval vs grep on a fresh
   split), not only unit tests.

## 9. Evidence that would justify another paid coding experiment

Spend again only when **all** of these hold:

1. **A task set that discriminates:** plain Claude succeeds on 30–70% of it,
   measured on a small calibration (not 92% as in both sets so far). Mined by
   a fixed rule, never examined.
2. **A specific mechanism with offline proof:** for example, the plain arm's
   failures in calibration are mostly regressions that repo-ai's impact
   selection would have caught. That can be checked offline from the
   calibration runs' grading output.
3. **Correct guidance:** the guidance-correctness corpus is clean (§7.2).
4. **Enough power for a plausible effect:**
   - With one run per arm, roughly 60–100 tasks for a 15–20 point effect.
   - At the measured $0.15–0.16 per run, that is about $20–35 for both arms
     (more if the harder tasks cost more).
   - The design should be pre-registered, with a ceiling check before the
     main run.

Without points 1 and 2, another experiment would most likely repeat the
inconclusive results at the ceiling.

## 10. Recommended direction for v0.8.0

**"repo-ai 0.8: change impact and verification, on demand."**

- **Ship §7.1–7.3 only:**
  - calibrated impact and `verify`;
  - correct, non-auto-applied guidance;
  - the advisory default with honest documentation;
  - the skill network gated as experimental, with its defects fixed or the
    paths disabled.
- **Keep:**
  - all existing users' configurations;
  - byte-exact uninstall;
  - the evaluation lab (as research tooling).
- **Measure with the offline audit suites** (mutation test selection,
  guidance correctness, retrieval on a fresh split), not unit tests alone and
  not model experiments.
- **Make no claim that repo-ai improves Claude Code's coding performance**
  until a discriminating, pre-registered experiment shows it.

## Limitations of this review

- The audit corpus is mostly Python. JS and TS impact quality is not
  measured.
- Mutations are function-body raises scored at test-file level. Real
  regressions can be subtler.
- Read-tool paths were not recorded in the live runs, so whether the agent
  opened the generated docs with Read is unknown. Bash never did.
- Several skill-network findings come from a code trace. The following were
  re-verified directly:
  - binary decoding on install;
  - the name vs id trial key;
  - `updates` ignoring `--check`;
  - lockfile-trusted promotion.
