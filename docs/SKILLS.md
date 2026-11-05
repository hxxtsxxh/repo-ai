# Skills, workflows and orchestration

## Skill lifecycle

```
discover → propose → (draft) → test → promote → monitor → canary → retire / rollback
```

```sh
repo-ai skills discover               # candidates with evidence, risk and validity
repo-ai skills propose repo-tests     # the exact SKILL.md, nothing written
repo-ai skills test [name]            # static sandbox test (see below)
repo-ai skills diff repo-tests        # disk vs what repo-ai would write
repo-ai skills promote repo-tests     # activate (risky skills are written manual-only)
repo-ai skills disable repo-tests     # remove; not regenerated unless re-promoted
repo-ai skills rollback repo-tests --previous
repo-ai skills canary repo-tests      # compare the two latest versions
repo-ai skills doctor                 # validate every project skill
```

The older names `candidates`, `generate` and `audit` still work.

### Tier 1: deterministic (default)

Skills are generated from evidence repo-ai has:
- routes and their registration (`repo-add-endpoint`);
- test suites with focused commands (`repo-tests`);
- component layout (`repo-add-component`);
- migration tooling (`repo-db-migration`, manual-only);
- release commands (`repo-release`, manual-only);
- repeated verified command sequences (`repo-precheck`).

No model is involved. At most `max_generated_skills` (8) are active at once.

### Tier 2: Claude-assisted drafting (opt-in, billable)

```sh
repo-ai skills draft repo-tests --dry-run              # print exactly what would be sent
repo-ai skills draft repo-tests --max-cost-usd 0.05    # run it
repo-ai skills promote repo-tests --draft              # activate a reviewed draft
```

**Requirements** (all of them):
- `skills_llm = "on"`;
- the repository is registered in a zone whose policy allows model drafting.
  Only `personal` does by default; `work` and unregistered repositories are
  denied;
- an explicit `--max-cost-usd`.

**What is sent:** minimized and redacted. The skill's purpose and current
body, the repository's declared commands, evidence *paths* and languages.
No file contents. `--dry-run` prints it verbatim.

**How Claude Code is run:** `--tools ""` (no tools), `--safe-mode` (no
hooks, plugins or memory), `--max-turns 1` and `--max-budget-usd`.

**How the reply is treated:** as untrusted. Its front matter is discarded,
and the name, description and risk class come from repo-ai. It must pass the
same static tests, and it is stored as a `draft`. Only
`skills promote --draft` activates it, and only if it passes.

### Static sandbox test (`skills test`)

The test runs against a disposable copy of the tracked files. It checks:
- front matter and the risk class (a skill that runs risky commands must be
  manual-only);
- that every referenced path exists;
- that every backticked command is one of the repository's declared
  commands, or a focused-test template for a detected suite;
- token cost;
- description overlap with other skills (≥ 0.6 → merge instead of
  duplicating);
- Claude Code's own `claude plugin validate`, when the CLI is installed.

**Nothing in the skill is executed.** Skill text and repository text are
untrusted, and an unknown command is flagged for a human, never run.

### Canary lab (`skills canary`)

The canary compares the two most recent versions of a generated skill:
- **Static checks:** if one version fails, it is retired.
- **Outcomes:** sessions record which skill version they used. This needs
  ≥ 5 recorded sessions per version and a two-sided Fisher exact test at
  p < 0.1 on the verified-session rate.
- **Otherwise:** both versions are kept. `--apply` acts on the decision.
- Sessions are not randomised, so this is association, not causation, and
  the report says so.

## Workflow Compiler (`repo-ai workflow`)

```sh
repo-ai workflow list
repo-ai workflow plan wf-billing      # read-only preview + static verification
```

A playbook is typed data:
- prerequisites;
- ordered `locate` / `edit` / `verify` steps;
- affected paths;
- a tool policy;
- failure branches;
- a rollback recipe;
- its evidence.

There are two sources:
- **Episodes:** at least 3 *verified* sessions that edited the same areas and
  then ran the same declared commands.
- **Facts:** for example, adding an endpoint when routes and route tests
  exist.

Verification is static: paths must exist and commands must be declared.
repo-ai never executes a playbook. Claude follows one only when the user
asks, under normal permissions.

## Orchestration (`repo-ai orchestrate plan "<task>"`)

The planner is advice only and spawns nothing. From the task packet it
recommends **zero to three** read-only specialists, each with its trigger
and an estimated token cost:

| Specialist | Triggered by |
|---|---|
| `repo-explorer` | low retrieval confidence |
| `repo-impact-analyst` | a wide blast radius: ≥ 8 transitive importers, ≥ 2 components, or many routes on API work |
| `repo-security-reviewer` | auth, payments, deletion or schema changes |
| `repo-skeptic` | the same risky changes, when `skeptic_reviewer = true` |
| `repo-verifier` | wide or risky changes that have linked tests |

Trivial edits (typos, comments, formatting) get no delegation.

The plan is a DAG with one writer, the main session, which is also the merge
point. Subagents are read-only, so parallel edits to the same path cannot
happen. Fan-out is capped at three, and subagents do not recurse.
Orchestration has no benchmark win yet, so it is off by default and nothing
calls it automatically.
