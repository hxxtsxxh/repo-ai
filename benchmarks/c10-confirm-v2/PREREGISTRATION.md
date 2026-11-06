# c10-confirm-v2: does the c10-confirm-v1 result hold on a second project and a second model? (preregistered, not run)

Acceptance gate C10 (skill value evidence), next action "repeat on a second project and model". c10-confirm-v1
(`benchmarks/c10-confirm-v1/`) was SUPPORTED: the skill arm scored higher on 8 of 8 tasks (sign test p = 0.0039),
with `sonnet`, on one fixture project (`stockroom`, a Python in-memory ledger library), using one project-conventions
skill. Its stated limits: one project, one model, model-session authors rather than people, and a control with no
conventions text. This protocol is committed on 2026-11-06, **before any material of the trial exists and before any
live call**. Designed only: no run is approved by this file. Spend: at most **$3.60** notional (hard cap, see
Budget), from the owner's $10 budget of 2026-11-05 (about $9.90 left), and only after the owner approves the batch
(`docs/engineering/LIVE-SPEND-2026-11.md`, rule of 2026-11-02).

## Questions

1. **Primary (replication).** On a second, different fixture project and with a second model (`claude-haiku-5-5`),
   on tasks written by someone other than the skill's author, does a project-conventions skill installed by
   `repo-ai skills install` raise the share of the project's conventions that Claude Code's changes satisfy, compared
   with the same project without the skill?
2. **Secondary (v1's "no conventions text in the control" limit).** Does the skill do better than the **same text**
   given as the project's `CLAUDE.md`?
3. **Tertiary (sanity).** Does the same text in `CLAUDE.md` do better than no text?

## What changes from v1, and why (decided now)

| | v1 | v2 | reason |
|---|---|---|---|
| fixture | `stockroom`: Python library, in-memory ledger, dataclasses, money/time rules | a **Python command-line application**: argparse subcommands, `main(argv) -> int`, exit codes, stdout/stderr, file input and output, environment variables; a domain unrelated to inventory or money | a different kind of project and a different language feature set; still Python, so the grading (pytest in the macOS sandbox) is unchanged |
| conventions | 14 rules (money, SKUs, rounding, periods, IDs, ...) | 10–14 new rules, at least 8 not inferable from the code, at most 2 on v1's topics | so v2 does not re-test v1's rules |
| model | `sonnet` (claude-sonnet-5-5) | **`claude-haiku-5-5`** (full name, not the alias), and the init event must report exactly that model | a second, smaller model; the full name removes alias ambiguity |
| arms | skill, control | skill, **claudemd**, control | v1's limit: the control had no conventions text |
| per-session cap | $0.30 | **$0.05** | Haiku 5.5 is priced at 1/20 of Sonnet 5.5 ($0.10/$0.50 vs $2/$10 per million tokens); $0.05 is about 10x the expected cost of one run |
| sessions | 48 | **72** (8 tasks x 3 arms x 3 repeats), hard cap | the third arm |
| crashed runs | "a harness crash is fixed and the affected runs repeated" | a session that reached the model is **never repeated** (scored as it is, or INVALID without an init event); only a start that ended before any model turn ($0) may be retried, at most 3 times | the session count must be a hard cap |
| work directory | under a scratch path with a component `-Users-...` | under `$HOME`, no path component starting with `-` (the harness refuses otherwise) | 3 of 24 v1 control runs read a mangled form of that path and never edited (v1 RESULTS.md, Disclosed) |
| leaky requests | noted only | an assertion named in a reviewer **LEAK** finding is deleted before any run, like an ambiguous one | v1's t5 leak was noted but kept |
| oracle inputs | some reused the skill's own worked examples | oracle inputs must not reuse the SKILL.md's example values | v1 RESULTS.md, Reading |
| author hand-off | instructions not to read other material | each author works in its own directory that holds only its inputs | blindness by construction, not by instruction |
| built-in set | probe for Claude Code 2.1.316 | a new $0 probe for the version that runs (2.1.319 installed on 2026-11-06), committed before the run; it also records whether a project `CLAUDE.md` shows in the init event | v1 Amendment 1 method |

Everything else is v1's: the two original arms and their setup, 3 repeats, tools, flags, isolation, scripted
grading in run-id order, the reading rule and its threshold.

## Materials (written after this file is committed, by three separate model sessions)

The designer of this protocol writes **no** material: no fixture, skill, task, oracle or review. The briefs are in
`AUTHOR-BRIEFS.md`, one section per author; each author gets **only its own section and this Materials section**,
in a fresh session (no earlier context), working in its own new directory outside any repository that holds only
its inputs. A coordinator (the owner, or a session acting for the owner) prepares those directories, copies each
author's output into `benchmarks/c10-confirm-v2/` and commits it as that author's commit; the coordinator changes no
material except the mechanical deletions in step 4.

1. **Author A** writes a small, realistic **Python command-line application** (`fixture/`: one package with
   `cli.py` exposing `main(argv=None) -> int` and a `__main__.py`, standard library only, Python 3.11+, at least 3
   subcommands, 7–12 modules, at least 20 visible tests that pass with `python3 -m pytest -q`), and a skill
   `skill/<package>-conventions/` (`SKILL.md` with `name` and `description` frontmatter, plus an MIT `LICENSE`) that
   states **10–14 numbered project conventions** a contributor must follow, each with exactly one correct behaviour.
   At least 8 must not be inferable from the code; at most 2 may be on c10-confirm-v1's topics (integer-cent money,
   SKU formats, rounding of money or percentages, half-open time periods, generated sequential identifiers,
   all-or-nothing multi-line operations, tuple return types, warning logs for stock removals). The SKILL.md body
   must read correctly on its own, because the claudemd arm uses it verbatim as `CLAUDE.md`. A says in `A_NOTES.md`
   which rules are inferable and why. A never sees the tasks.
2. **Author B** sees only `fixture/` and the SKILL.md text (not A's notes, not the LICENSE, not this protocol's
   other sections). B writes **8 tasks** (`tasks.json`, v1's schema: a one-paragraph request each, naming no
   convention, no skill and no `CLAUDE.md`, and revealing no detail that a convention assertion checks unless the
   request must supply it) and, per task, a hidden oracle (`oracle/test_<id>.py`). Every convention assertion is
   its own test function, cites the single SKILL.md rule it checks, follows from that rule's text alone with one
   correct answer, and does not reuse the SKILL.md's example values as inputs. Each task has exactly one `baseline`
   assertion that checks the requested behaviour with no convention involved, and 1–4 convention assertions (18–28
   in total). At least 2 tasks are exercised through `main(argv)` and at least 2 through the package's functions.
   Every oracle passes on B's own reference implementation (discarded, never committed) and fails on the untouched
   fixture.
3. **Reviewer C** sees `fixture/`, the SKILL.md text, `tasks.json` and `oracle/`, and marks (a) every assertion
   whose expected value does not follow unambiguously from the cited rule, or (for a baseline assertion) that
   depends on a convention: **DELETE**; and (b) every assertion whose request reveals a detail it checks without
   having to: **LEAK**. Output `REVIEW.md` in the format the brief gives.
4. **Freeze (coordinator, mechanical).** Every DELETE and LEAK assertion is removed from its oracle file and from
   `tasks.json`; a task left with no convention assertion is dropped (reported; at least 6 tasks must remain, else
   B writes replacements and C reviews them). `python run.py check --strict` must then pass: visible tests pass,
   rule numbering, tasks and oracle names agree, the review is applied, and **no oracle assertion passes on the
   untouched fixture**. A failure goes back to the responsible author session with the check output only; any
   change by B is re-reviewed by C. The coordinator writes `MATERIALS.md` (sessions, counts, deletions) and commits;
   the materials are then frozen.

None of A, B, C reads `src/repo_ai/`, any `benchmarks/` directory (v1 included), the 2026-10-30 pilot, any result,
or `AUTHOR-BRIEFS.md` sections other than its own. The authors are model sessions (the owner's choice of model,
recorded in `MATERIALS.md`), not people.

## Runs

- Arms, same fixture commit in all three, each project prepared from scratch (`git init`, `repo-ai init --agent
  none`, which must not write `CLAUDE.md`, `AGENTS.md` or `.claude/`; the harness asserts this):
  - **skill**: `repo-ai skills discover --from-path skill/<name>` and `skills install <name> --approve <hash>
    --host claude-code`;
  - **claudemd**: the SKILL.md body after its frontmatter, verbatim (leading blank lines dropped), written as the
    project's `CLAUDE.md`; no skill installed;
  - **control**: nothing more.
  The arm setup is committed so each candidate diff is taken against it.
- 8 tasks x 3 arms x **3 repeats** = **72 runs**, in an order shuffled once with a recorded seed.
- Each run: `claude -p <task>` in the project, `--model claude-haiku-5-5`, `--tools Read,Write,Edit,Glob,Grep,Skill`
  (the `Skill` tool in every arm, as in v1), `--setting-sources project`, `--strict-mcp-config`, `--permission-mode
  acceptEdits`, `--no-session-persistence`, `--max-budget-usd 0.05`, stream-json output kept. Authentication
  `token_env`: the token is read from `--token-file` (see Authentication) and given to Claude Code as
  `CLAUDE_CODE_OAUTH_TOKEN`; every inherited `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_*` variable is removed. A **new,
  empty `CLAUDE_CONFIG_DIR` per run**, so no user-level skill, plugin, hook, setting or memory loads in any arm.
- repo-ai: the latest release on PyPI when `prepare` runs (0.12.8 or later), installed in a fresh virtual
  environment; Claude Code: the version the probe was taken with. Both versions are recorded in `mapping.json`.
- **Validity:** a run is `INVALID` (reported, not rerun) when its init event lists a skill outside the probe's
  built-in set (control, claudemd) or outside the built-in set plus the installed skill (skill), a plugin whose
  source is not `@builtin`, any MCP server, a tool beyond the list, or a model other than `claude-haiku-5-5`; and,
  if the probe shows an init field that reflects a project `CLAUDE.md`, when that field does not match the run's
  arm. The first run whose model differs aborts the stage (at most one session spent on a wrong model). A run that
  ends without editing, or at its budget cap, is scored as it is.

## Grading (scripted, in run-id order before arms are looked up)

As v1: the oracle file is copied into the finished project and run with pytest inside a network-denied macOS
sandbox that can write only the project and a temporary directory. Per run:

- **convention score** = passed convention assertions / convention assertions of that task;
- **baseline score** = passed baseline assertions / baseline assertions (none if C deleted the task's baseline).

## Analysis and reading rule (decided now)

For two arms X and Y, per task: the mean convention score over X's 3 runs minus the mean over Y's 3 runs (INVALID
runs excluded). Across the tasks: the number with a positive difference (X higher) and a negative one (Y higher);
ties dropped; one-sided exact sign test over the non-tied tasks.

- **Primary, skill vs control (v1's rule, unchanged).** **SUPPORTED**: skill higher on more tasks than control and
  p < 0.05 (8 non-tied tasks: at least 7; 7: 7; 6: 6). **NEGATIVE**: control higher on at least as many tasks as the
  skill. **INCONCLUSIVE**: otherwise.
- **Secondary, skill vs claudemd.** **SKILL_FORMAT_HIGHER**: skill higher on more tasks and p < 0.05.
  **CLAUDEMD_HIGHER**: claudemd higher on more tasks and the reverse one-sided p < 0.05. **NO_DIFFERENCE_SHOWN**:
  otherwise. Ties are expected when both arms deliver the text and are reported as a count; NO_DIFFERENCE_SHOWN is
  not evidence that the two are equivalent.
- **Tertiary, claudemd vs control**: the primary rule with claudemd in place of skill (TEXT_HIGHER / NEGATIVE /
  INCONCLUSIVE). Reported, gates nothing.

Reported as well (not gates): baseline score per arm; how often the skill arm called the `Skill` tool unprompted
(and with what argument); runs per arm that ended other than `success` (including budget caps); cost and turns per
arm; every run's per-assertion results; INVALID runs.

**What each outcome does to C10 (decided now).** v1 stands as recorded whatever v2 shows.

| primary | C10 |
|---|---|
| SUPPORTED | stays PASS_WITH_LIMITS; "one fixture project, one model" becomes "two fixture projects (a Python library, a Python CLI) and two models (Sonnet 5.5, Haiku 5.5); Python only" |
| INCONCLUSIVE | stays PASS_WITH_LIMITS with the added limit "did not replicate on a second project and model (c10-confirm-v2 INCONCLUSIVE)" |
| NEGATIVE | becomes INCONCLUSIVE (v1 and v2 disagree) |

The secondary result replaces the limit "the control had no conventions text" with what it found
(SKILL_FORMAT_HIGHER: "the installed skill beat the same text in CLAUDE.md on project 2 with Haiku";
NO_DIFFERENCE_SHOWN or CLAUDEMD_HIGHER: "on project 2 with Haiku, the installed skill did no better than the same
text in CLAUDE.md", so the claim is about conventions text being present, not the skill format). It does not change
the status.

**Limits stated in advance.** The project and the model change together: a SUPPORTED result covers both, but a
failure cannot be attributed to either (a follow-up, Haiku on v1's `stockroom` with v1's frozen materials, 48 runs,
is priced below and not part of this study). Still one conventions skill per project, whose value is by
construction the rules the code does not show; model-written authors and reviewer, not people; Python only; host
mode only; says nothing about third-party skills or repo-ai's discovery.

## Budget (decided now)

| item | sessions | cap | upper bound |
|---|---|---|---|
| authoring (A, B, C; plus any return to an author after a failed check) | 3 model sessions, owner's interactive Claude Code | not metered against this batch (as in v1) | n/a |
| built-in probe (`run.py probe`) | 2 Claude Code starts, no token, model name that does not exist | no model can be invoked | $0.00 |
| trial runs | **72 billed sessions**, hard cap in the harness | `--max-budget-usd 0.05` each | **$3.60** |
| starts that end before any model turn (e.g. `authentication_failed`) | at most 3, each stops the stage | $0.00 observed | $0.00 |

- **Hard ceiling $3.60**, enforced by the harness: a session is not started when the observed spend plus $0.05
  could exceed $3.60, and no more than 72 sessions are ever started past the model. A session that started but
  reported no cost (crash, kill) is counted at its full $0.05. Claude Code checks `--max-budget-usd` between turns,
  so only the last turn of the last session can go past the ceiling; at Haiku 5.5 prices one turn costs well under
  a cent, so **the upper bound is $3.65**. Under the owner's $4 limit for this study; at least $6.25 of the $9.90 is
  left in the worst case.
- **Realistic estimate: about $0.30–0.45 for the 72 runs; plan for at most $1.00.** Basis: v1's 48 Sonnet runs cost
  $3.2509 (mean $0.0677 per run; skill $0.0756, control $0.0599; maximum $0.1091; `benchmarks/c10-confirm-v1/
  results/results.json`). Haiku 5.5's per-token prices are 1/20 of Sonnet 5.5's, which gives $0.0034 per run; the
  2026-10-30 pilot measured Haiku directly in the same host-mode setup at $0.0255 for 6 runs, $0.0043 per run
  (skill $0.0048, control $0.0037; `docs/engineering/evidence/SKILL-VALUE-PILOT-2026-10-30.md`). The claudemd arm
  adds the conventions text (about 1,500–2,500 tokens) to every turn, mostly as cache reads: well under $0.001 per
  run at Haiku prices. $0.004–0.006 per run x 72 = $0.29–0.43; three times as many turns as Sonnet would still be
  about $1.00.
- **Ceiling risk.** If Haiku runs cost far more than expected, the $0.05 cap ends them early (scored as they are,
  counted and disclosed). The ceiling is not raised after the first live call (v1's Amendment 2 is not repeated);
  if the ceiling stops the trial early, the analysis uses the completed runs, and tasks without all three arms are
  reported as missing.
- Accounting: Claude Code's reported `total_cost_usd`; with the subscription token the money is notional and
  metered against the plan; an unreported cost is UNKNOWN, never $0. The batch is predeclared in
  `LIVE-SPEND-2026-11.md` with this session count, cap and upper bound, and runs only after the owner approves it.
- Not included, priced for a later decision: Haiku on v1's frozen `stockroom` materials, skill vs control, 48 runs:
  expected about $0.25, cap bound 48 x $0.05 = $2.40.

## Authentication

`token_env` from a token file, as in the C13 harness (`benchmarks/c13-live-handoff/run_l2l.py`, `--token-file`):
`python run.py run --work ~/c10v2-work --token-file ~/.config/repo-ai/claude-token`. The harness refuses a file that
group or others can read (it must be mode 600) or that does not hold exactly one token on one line; it passes the
token only to the `claude` processes of the run stage (never to `repo-ai`, git, the grader or the probe), never
prints it, and replaces it with `<token>` in the stream and stderr it keeps. The token is never written to
`mapping.json`, results, traces or any committed file. Full streams stay local (session metadata); `results/trace.json`
keeps only what validity needs, as in v1.

## Rules

1. One run of the 72 after the materials are frozen, the probe is committed and the owner has approved the batch.
2. Nothing in the materials, analysis, rule or budget changes after the first live call. A harness defect found
   before the first live call is fixed and recorded as an amendment; after it, only grading-side defects may be
   fixed (and disclosed), and no session is repeated.
3. Results: `results/` (mapping, per-run results, summary, trace, candidate diffs; `run.py grade --export`) and
   `RESULTS.md` with commits, versions, times, spend, and every deviation.

## Procedure

1. Dispatch Author A, then B, then C (`AUTHOR-BRIEFS.md`); freeze (Materials, step 4); commit.
2. `python run.py probe --work ~/c10v2-work` ($0); commit `probe/builtin-init-<version>.json`. If the built-in set
   or the CLAUDE.md finding needs a change to the validity rule, record it as an amendment before any live call.
3. Owner approval of the batch (72 sessions, $0.05 each, $3.60 ceiling, upper bound $3.65), recorded in
   `LIVE-SPEND-2026-11.md`.
4. `python run.py prepare --work ~/c10v2-work --repo-ai <venv>/bin/repo-ai`; `python run.py run --work ~/c10v2-work
   --token-file ~/.config/repo-ai/claude-token` (resumable; never restarts a started session); `python run.py grade
   --work ~/c10v2-work --export`; `RESULTS.md`; C10 observation and QUEUE row.

`python run.py check [--strict] [--selftest]` is offline and makes no model call. At design time (2026-11-06) only
`check` and `check --selftest` were run: the materials are reported PENDING, and the self-test prepared all three
arms from v1's frozen materials (stand-in), found 0 of their oracle assertions passing on untouched projects, and
re-graded two v1 full-score candidate diffs at 4/4 each.

## Amendment 1 (2026-11-06, after the run, before any score was read)

The 72 sessions ran (cost $0.7798, OBSERVED) and grading marked **all 72 invalid**, so no comparison had any data and
the computed "NEGATIVE / NO_DIFFERENCE_SHOWN" verdicts are artifacts of empty comparisons, not results. Both causes are
defects of the validity rules, identical across the three arms and independent of any outcome:

1. **`skills outside the allowed set: ['schedule']` (72 of 72).** Claude Code 2.1.319 lists its built-in `schedule`
   skill only for authenticated sessions; the predeclared probe ran without a token (to stay at $0), so its built-in
   list lacked it. `schedule` is added to the allowed built-ins (`AUTH_ONLY_BUILTIN_SKILLS`). The arm's own skill
   check (only the skill arm may have `logsift-conventions`) is unchanged.
2. **Project-memory checks (48 of 72: skill and control arms).** The probe recorded the init fields that differed
   between a project with and without CLAUDE.md: `memory_paths`, `messaging_socket_path`, `original_cwd`. They are
   path-dependent (each run's project directory differs), not a CLAUDE.md signal: both probe runs list only the
   per-path auto-memory folder. The init event therefore cannot show whether a project CLAUDE.md was loaded; the check
   is dropped and this becomes a limit (the claudemd arm's CLAUDE.md is placed by `prepare` and is in the project, but
   its loading is not observed in the init event).

The grading is re-run once under these rules on the kept streams ($0). Every other rule, the decision rule and the
oracles are unchanged; the original all-invalid grade is kept in the results. A reader should weigh that these rules
were changed after the run (before any score was read, and symmetrically across arms).

