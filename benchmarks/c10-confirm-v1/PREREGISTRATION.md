# c10-confirm-v1: does a repo-ai-installed project-conventions skill improve Claude's results? (preregistered)

Acceptance gate C10 (skill value evidence). The 2026-10-30 pilot was INCONCLUSIVE and limited by a single author of
fixture, skill, tasks and oracle, one model, n = 3 pairs and an ambiguous oracle rule
(`docs/engineering/evidence/SKILL-VALUE-PILOT-2026-10-30.md`). This protocol is committed before any material of the
trial exists. Spend: at most **$4.00** notional, from the owner's $20 live budget (`docs/engineering/LIVE-SPEND-2026-11.md`).

## Question

On tasks written by someone other than the skill's author, does a project-conventions skill installed by
`repo-ai skills install` raise the share of the project's conventions that Claude Code's changes satisfy, compared
with the same project without the skill?

## Materials (written after this file is committed, by three separate agents)

1. **Author A** writes a small, realistic Python project (`fixture/`, with visible tests that pass) and a skill
   (`skill/<name>/SKILL.md`) that states 10–14 project conventions a contributor must follow. At least 8 of them must
   not be inferable from the code (the point of a conventions skill); A says which. A never sees the tasks.
2. **Author B** sees only `fixture/` and the SKILL.md text (not A's notes). B writes **8 tasks** (`tasks.json`: a
   one-paragraph request each, naming no convention and no skill) and, per task, a hidden oracle (`oracle/test_<id>.py`).
   Every oracle assertion cites the single SKILL.md rule it checks, and must follow from that rule's text alone, with
   one correct answer. B also writes one assertion per task that checks the requested behaviour itself, with no
   convention involved (`baseline` assertions).
3. **Reviewer C** sees `fixture/`, SKILL.md, `tasks.json` and `oracle/`, and marks every assertion whose expected value
   does not follow unambiguously from the cited rule (the pilot's t1 defect). Marked assertions are **deleted before
   any run**; the list is kept in `REVIEW.md`. A task left with no convention assertion is dropped (reported).

All three are briefed with this file's Materials section only. None reads `src/repo_ai/`, the pilot's materials or
any result. The materials and `REVIEW.md` are committed, then frozen.

## Runs

- Arms: **skill** (`repo-ai init --agent none`, then `repo-ai skills discover --from-path skill/<name>` and
  `skills install <name> --approve <hash> --host claude-code`) and **control** (`repo-ai init --agent none` only).
  Same fixture commit in both.
- 8 tasks × 2 arms × **3 repeats** = 48 runs, in an order shuffled once with a recorded seed.
- Each run: `claude -p <task>` in the project, model `sonnet`, tools `Read,Write,Edit,Glob,Grep,Skill`,
  `--setting-sources project`, `--strict-mcp-config`, `--permission-mode acceptEdits`, `--no-session-persistence`,
  `--max-budget-usd 0.30`, stream-json output kept. Authentication `token_env` (`CLAUDE_CODE_OAUTH_TOKEN`) with a
  **new, empty `CLAUDE_CONFIG_DIR` per run**, so no user-level skill, plugin, hook or setting can load in either arm.
- **Validity:** a run whose init event lists any skill other than the installed one (skill arm) or any skill at all
  (control), any plugin or MCP server, or any tool beyond the list above is `INVALID` (reported, not rerun).
  A run that ends without editing is scored as it is.

## Grading (scripted, in run-id order before arms are looked up)

The oracle file is copied into the finished project and run with pytest inside a network-denied macOS sandbox that
can write only the project and a temporary directory. Per run:

- **convention score** = passed convention assertions / convention assertions of that task;
- **baseline score** = passed baseline assertions / baseline assertions.

## Analysis and reading rule (decided now)

Per task, the mean convention score over its 3 skill runs minus the mean over its 3 control runs. Across the tasks:
the number with a positive difference (skill higher) and a negative one (control higher); ties dropped.

- **SUPPORTED**: skill higher on more tasks than control **and** a one-sided exact sign test over non-tied tasks
  gives p < 0.05 (for 8 non-tied tasks: skill higher on at least 7).
- **NEGATIVE**: control higher on at least as many tasks as the skill.
- **INCONCLUSIVE**: otherwise.

Reported as well (not gates): the baseline scores per arm (the skill must not cost task correctness); how often the
skill was invoked unprompted; cost and turns per arm; every run's per-assertion results.

C10 can move from NOT_YET_DEMONSTRATED only on SUPPORTED, and then only as "on this project and these tasks". Limits
stated in advance: one fixture project, one model, a conventions skill (its value is by construction the rules that
the code does not show), model-written authors (not people), host mode only.

## Rules

One run of the 48 after the materials are frozen. A harness crash is fixed and the affected runs repeated; nothing in
the materials, analysis or rule changes after the first live call. Results: `results/`, `RESULTS.md` with commit,
versions and times.
