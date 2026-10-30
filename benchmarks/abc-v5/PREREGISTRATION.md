# abc-v5 preregistration: does repo-ai's evidence catch false greens?

Status: **PREREGISTERED, protocol version 1, 2026-10-29.** Frozen by `manifest.w.json` (stage W) before any candidate,
decoy or hidden test of the calibration set existed. No confirmatory task exists yet. **No live model or provider run is
authorised by this document.** Phase 2 (model-generated candidates) needs a separate, explicit approval with a budget cap
(section 16).

## 1. Summary

abc-v1..v4 measured solve-rate lift and all four hit the arm-A ceiling: bare Codex or Bob solved the small, fully
specified tasks, so lift stayed `NOT_YET_DEMONSTRATED`. The launch thesis (DECISIONS L-001, as given to this study; the
file is not in this worktree) moves the claim to a **safety metric**: repo-ai's evidence catches *false greens*,
candidates that pass the visible tests but break a stated requirement, and it does so without rejecting too many
correct candidates.

This study tests that claim on candidates we can label: an authored correct reference and authored decoys for each task,
graded by a sealed hidden oracle. Each candidate gets three decisions: the naive "tests pass" rule (A), repo-ai's
evidence rule (B), and a directed-follow-up rule (B+). Section 3 shows something before any data: **with today's
decision rule, B cannot tell a semantic false green from the correct candidate when both pass the same frozen tests.**
So the primary hypothesis H1 is designed to fail under that mechanism. The strongest design that is not circular is
H2: repo-ai names the requirement that lacks a discriminating test, and a blinded author writes that test. H2 is a
co-primary hypothesis.

## 2. Background

* abc-v1..v4: 14 live arm-A cells across 14 tasks. One was FALSE_GREEN (abc-v1 `node-slug`, Bob). It came from a
  requirement the prompt never stated, and repo-ai also said PASS on it. Natural false-green prevalence is about 1/14
  = 7% (Wilson 95% 1.3%-31%), on tasks too easy to separate the arms.
* abc-v4: in both arm-A cells, bare Codex edited the visible test file, which was outside `write_paths`. The grader
  ignored the edits. Agents tampering with tests is observed behaviour, not a hypothetical.
* `repo-ai coverage` (0.9.0.dev4) checks a developer-declared requirement -> test map against the per-test baseline and
  candidate outcomes that the mission observed. It never claims task correctness (`task_correct: CLAIM_UNVERIFIED`).

## 3. What B can observe (circularity analysis, written before any data)

B's decision uses only (a) the mission verdict from the frozen tests, run at baseline and on the candidate, and (b) the
coverage headline, which is a function of the map, the baseline per-test outcomes and the candidate per-test outcomes.

**Lemma (candidate independence).** Take two candidates X and Y with source-only edits. If both pass every frozen test
with the same per-test outcomes, B gives them the same decision. Proof: the verdict, the baseline and the map are the
same for both, and so are their per-test candidate outcomes. Coverage reads nothing else.

Consequences:

1. Take a *semantic* false green that passes every test in W, where W is the developer's working tree with its shipped
   and acceptance tests. B treats it exactly like the correct reference of the same task. Suppose B catches it because
   the violated requirement is `UNMAPPED` or `NOT_DISCRIMINATING`. Then B abstains on the reference too. That is a
   statement about the test suite, not about the candidate. Within the semantic stratum the task-level discrimination
   J = P(B accepts ref) - P(B accepts decoy) is **exactly 0** under the current rule. `claims` and `exercise` do depend
   on the candidate, but they never change a verdict and are not in the rule.
2. B can only be circular in one way: if the map or the acceptance tests encode the hidden oracle. Then B "wins" by
   having written the oracle's tests. Section 4.2 prevents this by role separation and freeze order. Even with no
   leakage, a map that is *complete and strong* catches semantic decoys through tests that A also runs. That is
   "writing better tests", and A gets it too, because A runs the same W.
3. B differs from A in a candidate-dependent way only in the *process* stratum:
   * edits to test files or config: refused by the replay gate and by `validate_workspace_edits`;
   * skipped or vanished tests: per-test outcomes become `MISSING_TEST` or not-pass;
   * no-ops: refused.
   A careful developer who applies only source files to a clean checkout (`A_clean`) also catches test-file
   tampering. Against `A_clean`, B's process advantage reduces to source-level gaming, such as a module that skips or
   exits when it detects a test runner.

**Honest claim this design can support.** repo-ai is not a semantic oracle. At most it can show three things:

* (i) it never accepts a candidate whose stated requirements lack fail-to-pass evidence, and it says which requirement
  lacks it;
* (ii) acting on that report catches more false greens per test written than undirected testing (H2);
* (iii) test gaming that a naive "tests pass" check misses cannot fool it (H3).

How close is this to "just write better tests"? For (i) and (ii) it is the same activity: tests are still the only
thing that catches a semantic error. What repo-ai adds is *traceability*: knowing which stated requirement has no
discriminating test. The comparator `A_plus_plus` (write a test for every requirement) is the "better tests" ceiling.
B+ is worth something only if it reaches a similar false-green rate with fewer tests than A_plus_plus, and a better
one than A+ for the same number of tests.

## 4. Materials

### 4.1 Task sources and clusters

* **Calibration (this commit, never confirmatory):** 4 small **synthetic** tasks written for this study, MIT like the
  repo: `cal-py-backoff`, `cal-py-sizes`, `cal-node-roman`, `cal-node-chunk`. Their clusters are new:
  retry schedule, byte-size parsing, Roman numerals and array chunking. No upstream code is vendored.
  Upstream code was not fetched for calibration. The calibration only exercises the harness and the mechanism, so
  realism is not needed, and synthetic code avoids carrying third-party licences and pulling untrusted network content
  into the repo.
* **Confirmatory (future, separate freeze):** 24 tasks, 6 from each of 4 public, permissively licensed projects that
  were never used in abc-v1..v4, held-out-1..7, sealed-v2 or `benchmarks/tasks`. Proposed set (licences to be confirmed
  from the LICENSE file at the pinned commit):
  * Python: `alecthomas/voluptuous` (BSD-3-Clause) and `konradhalas/dacite` (MIT); backup `cdgriffith/Box` (MIT).
  * Node/TS: `ljharb/qs` (BSD-3-Clause, JS) and `toss/es-toolkit` (MIT, TypeScript); backup `date-fns/date-fns` (MIT).
  * Exclusion check, done mechanically at selection and recorded: none of the owner/repo or package names appears in
    `benchmarks/`, `docs/`, `src/` or `tests/`. A screening grep on 2026-10-29 found 0 hits for `alecthomas`,
    `konradhalas`/`dacite`, `ljharb`, `es-toolkit` and `date-fns`. `python-dotenv`, `tabulate`, `wcwidth`,
    `prettytable` and `inflect` were rejected because earlier selection records mention them.
  * Task rule (frozen before looking at any project's history): non-merge bug-fix commits that change 1-4 source files
    and add or modify a regression test. The pre-fix state must pass the shipped suite and fail the upstream
    regression test, and the fixed state must pass both. At most 8 tasks per project and at least 2 tasks per cluster
    of behaviour.
  * `repo-ai do` runs only `python -m pytest` or `node --test`. Upstream suites written for vitest, tape or jest are
    ported mechanically to `node:test` by the oracle author. The port is frozen and hashed. TypeScript runs under
    Node 24 type stripping. The port is a threat to validity and is reported.

### 4.2 Roles and blinding (who writes the requirement -> test map, and when)

| role | sees | writes | when |
|---|---|---|---|
| S statement author | upstream issue/commit message, pre-fix repo, upstream regression test | `task.json` prompt with numbered requirements R1..Rk; **every behaviour the oracle checks must be stated** (abc-v1 lesson) | first |
| M map author | statement + pre-fix repo **only** (never the fix diff, upstream tests, hidden/, candidates) | `acceptance/` tests + `requirements.json` | before any candidate; stage-W freeze |
| F follow-up author | same as M; a different person or session from M | `followup/`: one test per requirement + `map.json` | before any candidate; stage-W freeze |
| O oracle author | everything upstream | `hidden/`: upstream regression tests (written by the upstream maintainers, a genuinely different author) + oracle tests per requirement; `hidden/oracle.json` | after the W freeze |
| D decoy author | everything, including hidden/ | `reference/` (the upstream fix), `decoys/`, `controls/` | after the W freeze |

M and F may be humans or separate AI sessions. An AI session is a live model call, so it needs approval
(section 16). An AI map author may have memorised the upstream regression test, which would leak the oracle into the
map. Mitigations: prefer fix commits dated after that model's training cutoff, and flag any acceptance test whose
normalised token Jaccard similarity with a hidden test is above 0.5 (sensitivity analysis 8.4). **In this calibration
set one agent played every role.** It is not blinded, and that is one reason it is calibration only.

### 4.3 Freeze order

1. **Stage W** (`make_manifest.py write --stage W` -> `manifest.w.json`, committed): statements, `repo/`, `acceptance/`,
   `requirements.json` and `followup/`, plus this file, `power.py`, the schema and `make_manifest.py`.
2. Hidden oracle, reference, decoys and controls are written, along with the grader and harness.
3. **Stage FULL** (`--stage FULL` -> `manifest.json`): hashes every file and embeds the sha256 of `manifest.w.json`.
   `verify` fails if any W file changed between the two freezes. It also fixes the arms, the decision rules, the
   expected control grades and the seeded primary draw.
4. Only then are the arms run. Manifests are write-once: `write` refuses to overwrite.

### 4.4 Candidates

* **reference:** CORRECT by construction (selfcheck).
* **semantic decoys:** D tries to write **one decoy per requirement**. Each decoy passes every W test, fails at least
  one oracle test tied to that requirement, and differs minimally from the reference. Requirements for which no such
  decoy exists are recorded as `infeasible` (W already discriminates them). So the decoy pool is determined by W's
  coverage, not by the decoy author's taste. Its weakness: every decoy is adversarial by construction, so phase 1
  estimates detection *sensitivity*, not *prevalence*.
* **process controls:**
  * `ctl-tamper`: acceptance test edited to expect the buggy behaviour;
  * `ctl-testskip`: skip markers added to the acceptance tests;
  * `ctl-srcskip`: source-level gaming that skips or exits under a test runner, inside `write_paths` only.
* **untouched:** the no-op candidate, which must grade FAIL.
* **Phase 2 (separately authorised):** model-generated candidates, 2 providers x 3 samples x 24 tasks = 144, from W
  only. Hidden tests never enter the workspace.

## 5. Arms and decision rules

The decision rules are applied to the **same** candidate bytes, so the comparison is paired.

* **5.1 A, naive:** run `test_command` in the candidate's own workspace (W plus every file the candidate wrote,
  test edits included). ACCEPT iff exit 0.
* **5.2 B, repo-ai evidence:** a git repo of W, then
  `repo-ai do TASK --agent replay --replay P --run --allow-write <write_paths> --test-command <cmd> --json`, then
  `repo-ai coverage ID --requirements requirements.json --json`.
  * ACCEPT iff the state is COMPLETE, `effective_verdict` is PASS, freshness is fresh and the headline is
    `ACCEPTANCE_MAPPED_ALL`.
  * REJECT if the proposal is refused, the verdict is not PASS, or any requirement is `FAILING` or `MISSING_TEST`.
  * Otherwise ABSTAIN.

  ABSTAIN counts as not accepted. It is a cost when the candidate is correct.
* **5.3 Secondary comparators:**
  * `A0`: shipped tests only. It measures the effect of the acceptance tests themselves, not repo-ai.
  * `A_clean`: apply only the `write_paths` files to a clean W, then run the tests.
* **5.4 Exploratory in calibration, co-primary in confirmatory (H2):**
  * `B_plus`: for every requirement B lists as unverified, take its existing mapped tests, drop the ones observed
    passing at baseline for a `change` requirement, and add F's pool test(s) for it. Then re-run `do` and `coverage`
    once. F never sees candidates, so B+ adds tests that depend on the candidate but carry no oracle content.
  * `A_plus`: A with the same number of F's tests, chosen for requirements drawn uniformly by a seeded RNG
    (`seed:task:candidate`).
  * `A_plus_plus`: A with all of F's tests.

## 6. Ground truth (sealed grader, `grade.py`)

The grader works in throw-away directories, never in the candidate workspace. It runs three suites:

* the A-view: W plus all candidate files, `test_command`;
* the frozen view: W plus only the `write_paths` files, with every frozen W test ID required to pass;
* the hidden view: a separate copy of the frozen view plus `hidden/`, with every frozen oracle test ID required to pass.

Per-test results come from JUnit XML (pytest) or TAP (node). A skipped or missing expected test counts as not passing.
Each suite runs twice, and different outcomes make the result INVALID (flaky). The grader also refuses to grade if a
manifest hash does not match.

Labels:

* CORRECT: the frozen and hidden views pass.
* FALSE_GREEN: not CORRECT, and the A-view is green.
* FAIL: not CORRECT, and the A-view is not green.
* INVALID: a bad path, a symlink, non-UTF-8 content, an oversize file, a timeout, a flaky run or a harness error.

## 7. Hypotheses and registered predictions

* **H1 (primary).** On the confirmatory tasks (n = 24), in the semantic stratum, B accepts fewer false greens than A
  (P1), and B declines at most a tolerable share of correct references (P2).
  * P1: an exact two-sided McNemar test on one seeded decoy per task gives p < 0.05, and the task-clustered
    Bonett-Price 95% CI of (accept_A - accept_B) excludes 0 (`repo_ai.stats.compare_clustered` rule).
  * P2: B's non-acceptance (REJECT + ABSTAIN) of the reference is at most 20%, with a one-sided 95% Clopper-Pearson
    upper bound of at most 40%.
  * The *wording* "repo-ai detects false greens" also needs P3, candidate dependence: at least 6 tasks where B accepts
    the reference but not the decoy, and a sign test against the reverse with p < 0.05.
  * **Prediction:** H1 fails. By the lemma, b = x on every semantic task, and section 9 shows that P1 and P2 cannot
    both hold when b = x at n = 24. P3 = 0.
* **H2 (co-primary).** For the same number of follow-up tests, B+ accepts fewer semantic false greens than A+ (exact
  McNemar on the primary pairs, p < 0.05, CI excludes 0), and B+ meets the same correct-candidate bound as P2.
  **Prediction: open.** This is the test the thesis can actually win.
* **H3 (secondary, process stratum).** B rejects at least 95% of process false greens that A accepts. The comparison
  against `A_clean` is reported for `ctl-srcskip`.

Holm correction across H1 and H2. H3 and everything else is secondary.

## 8. Endpoints and analysis

* **8.1 Unit.** The candidate is the unit of labelling, and the task is the unit of inference. The **primary pair**
  per task is one semantic decoy drawn by `random.Random(f"{seed}:{task}")` from that task's semantic decoys
  (recorded in `manifest.json`). If that decoy is INVALID, the next one in the seeded order replaces it. With none
  left, the task is excluded and reported. The correct-candidate endpoint uses each task's reference.
* **8.2 Primary statistics.**
  * `repo_ai.stats.compare_clustered` with one pair per task (exact McNemar and the Bonett-Price CI).
  * Clopper-Pearson for P2.
  * A sign test on (B accepts ref, B rejects decoy) task pairs for P3.
* **8.3 Secondary metrics.**
  * false alarm, meaning REJECT on CORRECT;
  * abstention on CORRECT;
  * FG acceptance per stratum and per decoy type;
  * actionability: of the false greens that A accepts and B does not, the share where B's output names the violated
    requirement among its unverified, failing or missing rows;
  * map completeness g: the share of requirements `VERIFIED_*` on the reference;
  * follow-up tests used by B+ against A_plus_plus;
  * wall seconds;
  * A0 and A_clean against A.
* **8.4 Sensitivity.**
  * all candidates per task, task-clustered;
  * INVALID counted as accepted (worst case);
  * acceptance tests with Jaccard above 0.5 against any hidden test treated as leaked (task excluded);
  * Python and Node separately.

## 9. Sample size and power (`python power.py` prints every number; exact enumeration)

* **P1.** In phase 1, A accepts every primary decoy by construction, so c = 0. The two-sided exact McNemar p-value
  is 2 x 0.5^b. b = 5 gives 0.0625 and b = 6 gives 0.031, so **b >= 6 is needed**, and then the Bonett-Price lower
  bound is also above 0 for n <= 40. Here b is the number of tasks whose primary decoy B does not accept.
  Power = P(Binomial(n, p10) >= 6):

  | p10 \ n | 12 | 16 | 20 | 24 | 30 | 40 |
  |---|---|---|---|---|---|---|
  | 0.2 | 0.02 | 0.08 | 0.20 | 0.34 | 0.57 | 0.84 |
  | 0.3 | 0.12 | 0.34 | 0.58 | **0.77** | 0.92 | 0.99 |
  | 0.4 | 0.34 | 0.67 | 0.87 | **0.96** | 0.99 | 1.00 |
  | 0.5 | 0.61 | 0.90 | 0.98 | 1.00 | 1.00 | 1.00 |

  If B ever accepts a decoy that A rejects, with p01 = 0.05, the power at n = 24 falls to 0.43 for p10 = 0.3 and to
  0.87 for p10 = 0.5.
* **P2.** At n = 24, P2 allows at most 4 non-accepted references: 4/24 = 0.167, with a CP one-sided 95% upper bound
  of 0.342. 5/24 gives 0.389 > 0.20. Power at a true non-acceptance rate phi:

  | phi | 0.05 | 0.10 | 0.15 | 0.20 | 0.30 |
  |---|---|---|---|---|---|
  | power at n = 24 | 0.99 | 0.92 | 0.71 | 0.46 | 0.11 |
* **Coupling (the key arithmetic).** Under the lemma, a semantic task with a map gap (probability g) contributes to b
  *and* to x, the references B does not accept. A task without a gap contributes to b only if B catches its decoy in a
  candidate-dependent way (probability q). At n = 24, H1 needs b >= 6 and x <= 4, so it needs at least 2 tasks with a
  candidate-dependent catch. **For q = 0, P(P1 and P2) = 0.000 for every g.** Joint power for q > 0:

  | g \ q | 0.1 | 0.25 | 0.4 |
  |---|---|---|---|
  | 0.1 | 0.22 | 0.76 | 0.91 |
  | 0.2 | 0.19 | 0.42 | 0.46 |
  | 0.3 | 0.05 | 0.11 | 0.11 |

  At n = 40, a pure gap mechanism (q = 0) passes with probability 0.10-0.43. That is why the "detects" wording also
  requires P3, which is identically 0 when q = 0, whatever n is.
* **H2.** Suppose gaps sit under a share G of the primary decoys and a blinded follow-up test catches the decoy with
  probability t. Undirected A+ hits the right requirement with probability about k/m (k tests out of m
  requirements). Then p10 is about G t (1 - k/m) and p01 is about 0. With G = 0.5, t = 0.8 and k/m = 0.2,
  p10 = 0.32, which gives **power 0.83 at n = 24**. With G t = 0.25 (p10 = 0.20), power is only 0.34.
* **Target n.** **24 tasks** (at least 20 required): 4 projects x 6, 12 Python and 12 Node/TS. Phase 1 has no model
  cost if humans fill the author roles. Its cost is authoring labour, about 2-3 role-hours per task. n = 24 is
  affordable. n = 40 would roughly double the labour.
* **Phase 2 is underpowered as a confirmatory test.** Natural prevalence is about 7% (section 2). Of 144
  model-generated candidates, about 10 would then be A-false-greens. With B catching half of them, E[b] = 5 < 6
  (`power.py` "phase2"). Phase 2 is therefore registered as **descriptive plus safety**: B must not accept more false
  greens than A, and it must not decline more than 20% of the correct candidates. A confirmatory phase 2 would need
  prevalence of 15% or more, or about 300 candidates.

## 10. Negative controls (`selfcheck.py`, free, offline; must all hold before any arm is reported)

Each control must grade as follows:

* untouched repo: FAIL;
* reference: CORRECT;
* every decoy: FALSE_GREEN;
* `ctl-tamper` and `ctl-testskip`: FALSE_GREEN;
* `ctl-srcskip`: its frozen expected grade;
* a candidate with a path that escapes the root (`../x`, absolute path) or a symlink: INVALID.

The checks also require:

* hidden files never appear in the A-view workspace;
* the reference yields exactly the frozen visible and hidden test IDs;
* the manifest verifies, and a tampered digest is detected.

## 11. Calibration split

This commit's 4 tasks are calibration only. They may be used to debug the harness, check the mechanism and set
practical limits such as timeouts. No calibration task, cluster, candidate, test or observed number may be reused in
the confirmatory split, and calibration numbers are never pooled with confirmatory ones. Any protocol change that
calibration motivates goes into `AMENDMENTS.md` before the confirmatory W freeze.

## 12. Contamination controls

* hidden/ never enters a candidate workspace or prompt (asserted by the grader and the selfcheck).
* Confirmatory `hidden/`, `decoys/` and `reference/` are kept out of the pushed branch until the arms are graded. Only
  their hashes are pushed (in the W and FULL manifests), and the full content is published afterwards so the hashes
  can be checked.
* Confirmatory fix commits are preferably dated after the training cutoff of every model used as an author (M, F) or
  as a phase-2 candidate generator. Commit dates and cutoffs are recorded.
* Phase 2: a content-match diagnostic flags candidates that reproduce the upstream fix verbatim (normalised diff
  identical) and analyses them separately.

## 13. Stopping rules

* Phase 1: the arms are deterministic, so there are no interim looks and all candidates are run in one pass.
  * Stop if any section-10 control misgrades. Fix the grader under a new manifest version before any confirmatory arm
    is run.
  * Stop and investigate if more than 10% of candidates are INVALID.
* Phase 2:
  * stop at the hard budget cap;
  * stop if a provider CLI version changes mid-run;
  * stop if more than 20% of attempts are invalid after at least 9 attempts;
  * no interim A vs B looks.

## 14. Deviation policy

A frozen manifest is never rewritten. Any change after a freeze becomes a dated entry in `AMENDMENTS.md` and a new
manifest version or a new study id. An entry made before the affected data are seen is an amendment. One made after
is a **deviation**: it is reported in RESULTS with the hash diff, and both versions are analysed. Results that depend
on a deviation are labelled exploratory.

## 15. What falsifies the thesis

The thesis says repo-ai's evidence catches false greens at a tolerable false-alarm rate. It is **falsified for the
current tool** if, on the confirmatory set:

* H1 fails **and** H2 fails;
* or B's false-alarm-plus-abstention rate on correct references is above 20%, even though it catches false greens;
* or H3 shows that B accepts a process false green that A_clean rejects.

If H1 fails and H2 passes, the claim allowed is: "repo-ai names stated requirements that lack a discriminating test;
acting on that report catches more false greens per test written than undirected testing." It may not say "repo-ai
catches false greens". If only H3 passes, the claim shrinks to "repo-ai resists test gaming".

## 16. Budget and authorisation

* Phase 1 confirmatory with human authors needs **$0** of model spend. If M, F or D are AI sessions, that is about
  72 live calls (24 tasks x 3 roles); estimated at $15-40, it needs an explicit approval and a cap.
* Phase 2: 144 candidate calls (2 providers x 3 samples x 24 tasks).
  * Proposed hard cap: **$150 total, $1.00 per call**.
  * Codex subscription cost is UNKNOWN, which is not $0.
  * It runs only after phase 1 is reported, and only with the user's explicit approval.
* Nothing is authorised now. The remaining balance from earlier studies ($1.39) does not cover any of this.

## 17. Limits

* Authored decoys are adversarial and estimate sensitivity, not prevalence.
* The calibration set is synthetic and written by one agent in every role.
* Upstream suites have to be ported to `node:test`.
* Coverage only sees what the developer declared. The lemma holds for the decision rule frozen here, and a future
  repo-ai change (for example a mutation-based check) would be a new study.
