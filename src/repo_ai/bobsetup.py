"""IBM Bob content: the text of every file the Bob adapter writes.

Paths and filenames follow IBM's published Bob documentation:

  * `AGENTS.md` in the workspace root is loaded automatically into the **Rules**
    category of Bob's context window, on every prompt in every task. It is
    therefore kept deliberately tiny — a router, not an encyclopedia.
  * `.bob/skills/<name>/SKILL.md` (YAML front matter: `name`, `description`)
    loads **once per conversation**, only when Bob decides the description
    matches the request.
  * `.bob/settings.json` holds `hooks`. `SessionStart` and `UserPromptSubmit`
    have their **stdout injected into the model's context**; `PostToolUse`
    matches on a tool-name regex (Bob's tool names: write_file, apply_diff, …).
  * `.bob/commands/<name>.md` become slash commands, with `$1` substitution.
  * `.bob/agents/<name>.md` are subagent personas.
  * `.bobignore` uses `.gitignore` syntax and blocks Bob's file tools.

Caveats this module works around:

  * An explicit `@/path` mention **bypasses `.bobignore`**, so repo-ai never
    emits a mention for a quarantined path.
  * IBM's docs disagree about the Agent-mode rules directory name, so repo-ai
    writes to `.bob/rules/`, documented as "general rules for all modes".

All context paths are parameters: nothing here assumes `.bob/context`.
"""

from __future__ import annotations

from .models import RepoFacts

BEGIN = "<!-- BEGIN repo-ai -->"
END = "<!-- END repo-ai -->"


# --------------------------------------------------------------------------
# AGENTS.md
# --------------------------------------------------------------------------
def build_agents_block(facts: RepoFacts, context_dir_rel: str, shared_with_claude: bool = False) -> str:
    """The always-loaded block. Target: under ~450 tokens.

    `shared_with_claude=True` means Claude Code also loads this block (its
    CLAUDE.md imports AGENTS.md), so it carries one line for Claude and the
    Claude adapter writes no separate block.
    """
    langs = ", ".join(list(facts.languages)[:3]) or "unknown"
    comps = ", ".join(f"{c.name} (`{c.root}`)" for c in facts.components[:5])
    from .testing import verification_plan, verify_line
    vplan = verification_plan(facts.commands, facts.test_suites)
    test_cmd = vplan.test_command or "(unknown)"
    build_cmd = (facts.commands.get("build") or facts.commands.get("install") or ["(unknown)"])[0]
    run_cmd = (facts.commands.get("run") or ["(unknown)"])[0]

    lines = [
        BEGIN,
        "## Project context (maintained by repo-ai)",
        "",
        f"**{facts.name}** — {langs}. "
        f"{facts.indexed_files:,} indexed files, {facts.total_loc:,} LOC.",
    ]
    if comps:
        lines.append(f"**Components:** {comps}")
    if facts.frameworks:
        lines.append(f"**Stack:** {', '.join(facts.frameworks[:8])}")
    lines.extend([
        "",
        "**Commands** — build: `%s` · test: `%s` · run: `%s`" % (build_cmd, test_cmd, run_cmd),
        "",
        verify_line(vplan),
        "",
        "### Before exploring, load context instead of guessing",
        "",
        f"Detailed, generated knowledge lives in `{context_dir_rel}/`. "
        "Read the one file that matches the task; do not read them all:",
        "",
        f"- orientation → `{context_dir_rel}/PROJECT_OVERVIEW.md`",
        f"- components, routes, infra → `{context_dir_rel}/ARCHITECTURE.md`",
        f"- where things live → `{context_dir_rel}/REPOSITORY_MAP.md`",
        f"- libraries and versions → `{context_dir_rel}/DEPENDENCIES.md`",
        f"- how to test → `{context_dir_rel}/TESTING.md`",
        f"- style and do-not-edit paths → `{context_dir_rel}/CONVENTIONS.md`",
        f"- human-written gotchas → `{context_dir_rel}/NOTES.md`",
        "",
        "### Finding code",
        "",
        "Run `repo-ai context \"<the task>\"` to get a ranked shortlist of files "
        "with line ranges. It is far cheaper than reading directories. "
        "`repo-ai search <term>`, `repo-ai symbol <Name>`, "
        "`repo-ai related <path>` and `repo-ai impact <path>` answer narrower questions.",
        "",
        "Prefer `GetSymbolsOverview` / `FindSymbol` over reading whole files (Bob).",
    ])
    if shared_with_claude:
        lines.append("Claude Code: the `/repo-locate`, `/repo-impact` and `/repo-verify` "
                     "skills wrap the same CLI.")
    lines.extend([
        "",
        "### Rules",
        "",
        "- Do not edit anything listed as generated in `CONVENTIONS.md`; change the generator.",
        f"- Do not edit files under `{context_dir_rel}/` — `repo-ai update` overwrites them. "
        "Durable notes go in `NOTES.md`.",
        "- Never read or mention files listed in `SECURITY_NOTES.md`.",
        "- Verify with the test command above before reporting a task complete.",
        END,
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Skill
# --------------------------------------------------------------------------
SKILL_NAME = "repository-context"


def build_skill(facts: RepoFacts, context_dir_rel: str) -> str:
    return f"""---
name: {SKILL_NAME}
description: >-
  Load deep, pre-computed knowledge about the {facts.name} repository: its
  architecture, components, routes, dependencies, test strategy, coding
  conventions, and change hotspots. Activate this whenever a request needs
  understanding of how this codebase is organised, where a feature lives, how
  components interact, how to run or test the project, or which files a change
  should touch. Also activate before any non-trivial edit, refactor, debugging
  session, or code review in this repository.
---

# Repository context for {facts.name}

Generated by `repo-ai` from commit `{facts.git_head or "n/a"}`.

## Use the retrieval CLI first

Before reading directories or grepping broadly, run:

```bash
repo-ai context "<restate the user's task in one line>"
```

It returns a ranked shortlist of files with line ranges and the reason each was
selected, using the import graph, symbol index, git history, and task intent.
Reading 8 targeted files beats skimming 80.

Other subcommands:

| Command | Returns |
|---|---|
| `repo-ai search "<terms>"` | BM25 ranked files matching identifiers or doc text |
| `repo-ai symbol <Name>` | Definitions of a symbol, with file and line |
| `repo-ai related <path>` | Importers, imports, co-changed files, and tests |
| `repo-ai impact <path or symbol>` | Downstream importers, tests, CI, and risk |
| `repo-ai architecture` | The architecture document on stdout |
| `repo-ai deps [name]` | Dependency facts |
| `repo-ai status` | Whether this context is stale |

If `repo-ai` is not on PATH, fall back to reading the files below directly.

## Knowledge files

Read the one that matches the task. Each is self-contained.

| File | Read when |
|---|---|
| `{context_dir_rel}/PROJECT_OVERVIEW.md` | You need orientation: purpose, stack, commands |
| `{context_dir_rel}/ARCHITECTURE.md` | Tracing a request, adding a service, changing an API |
| `{context_dir_rel}/REPOSITORY_MAP.md` | Locating where a concern lives |
| `{context_dir_rel}/DEPENDENCIES.md` | Checking a library, version, or what is really imported |
| `{context_dir_rel}/TESTING.md` | Writing tests, or working out how to verify a change |
| `{context_dir_rel}/CONVENTIONS.md` | Matching style, or checking what must not be edited |
| `{context_dir_rel}/HOTSPOTS.md` | Judging blast radius before a risky change |
| `{context_dir_rel}/SECURITY_NOTES.md` | Understanding what was quarantined and why |
| `{context_dir_rel}/NOTES.md` | Human-written knowledge that analysis cannot infer |

## Working rules for this repository

1. **Retrieve, then read.** Use `repo-ai context` to shortlist, then
   `GetSymbolsOverview` / `FindSymbol` on the shortlisted files. Load whole
   files only when a symbol-level read is genuinely insufficient.
2. **Respect the generated boundary.** Files listed as generated in
   `CONVENTIONS.md` are machine-owned; change the generator instead.
3. **Never open a quarantined path.** `SECURITY_NOTES.md` lists files the
   secret scanner excluded. `.bobignore` blocks tool reads, but an explicit
   `@` mention bypasses it — so do not mention them either.
4. **Verify.** Run the test command from `TESTING.md` before reporting done.
5. **Context may be stale.** If the working tree has moved on, trust the code
   and say so; suggest `repo-ai update`.
"""


# --------------------------------------------------------------------------
# Hooks (POSIX sh; Bob runs them from the workspace root)
# --------------------------------------------------------------------------
def hook_scripts(state_rel: str) -> dict[str, str]:
    index = f"{state_rel}/index.db"
    dirty = f"{state_rel}/.dirty"
    return {
        "session-start.sh": f"""#!/bin/sh
# repo-ai :: SessionStart
# stdout from this hook is injected into the model's context once per session.
# Keep it to a few lines: it is paid for on every prompt in the session.
command -v repo-ai >/dev/null 2>&1 || exit 0
[ -f {index} ] || exit 0
repo-ai status --brief 2>/dev/null || true
exit 0
""",
        "user-prompt.sh": f"""#!/bin/sh
# repo-ai :: UserPromptSubmit
# Reads {{"event","session_id","prompt"}} on stdin; stdout is injected into the
# model's context alongside the prompt. This is the task-aware retrieval step.
#
# Exit 0 always: a retrieval failure must never block the user's prompt.
set -u
command -v repo-ai >/dev/null 2>&1 || exit 0
[ -f {index} ] || exit 0

PROMPT=$(cat 2>/dev/null | repo-ai _extract-prompt 2>/dev/null) || exit 0
[ -n "$PROMPT" ] || exit 0

# Skip trivial turns: retrieval on "yes"/"continue"/"thanks" is pure token waste.
LEN=$(printf '%s' "$PROMPT" | wc -c | tr -d ' ')
[ "$LEN" -ge 25 ] || exit 0
case "$PROMPT" in
  /*|@*) exit 0 ;;
esac

repo-ai context "$PROMPT" --format hook --quiet 2>/dev/null || true
exit 0
""",
        "post-tool.sh": f"""#!/bin/sh
# repo-ai :: PostToolUse (write_file|apply_diff|insert_content|search_and_replace)
# Marks the index dirty. Re-indexing here would stall the agent mid-task, so
# the actual update runs from the Stop hook.
set -u
[ -d {state_rel} ] || exit 0
date -u +%Y-%m-%dT%H:%M:%SZ > {dirty} 2>/dev/null || true
exit 0
""",
        "stop.sh": f"""#!/bin/sh
# repo-ai :: Stop
# Fires when the agent finishes a turn. A debounced, lock-protected
# background refresh: concurrent or rapid-fire Stops do not stack up.
set -u
command -v repo-ai >/dev/null 2>&1 || exit 0
[ -f {dirty} ] || exit 0
REPO_AI_IN_HOOK=1 repo-ai refresh --background --quiet >/dev/null 2>&1 || true
exit 0
""",
    }


def hooks_config() -> dict:
    return {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": "sh .bob/hooks/session-start.sh",
                        "timeout": 10}]}
        ],
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "sh .bob/hooks/user-prompt.sh",
                        "timeout": 15}]}
        ],
        "PostToolUse": [
            {"matcher": "^(write_file|apply_diff|insert_content|search_and_replace)$",
             "hooks": [{"type": "command", "command": "sh .bob/hooks/post-tool.sh",
                        "timeout": 5}]}
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": "sh .bob/hooks/stop.sh",
                        "timeout": 10}]}
        ],
    }


def is_repo_ai_bob_hook(entry: dict) -> bool:
    return any(".bob/hooks/" in str(h.get("command", "")) or "repo-ai" in str(h.get("command", ""))
               for h in entry.get("hooks", []) if isinstance(h, dict))


# --------------------------------------------------------------------------
# Slash commands and persona
# --------------------------------------------------------------------------
def commands(context_dir_rel: str) -> dict[str, str]:
    return {
        "repo-context.md": """---
description: Retrieve the most relevant files for a task using repo-ai
argument-hint: <describe the task>
---
Run this command and use its output as your starting file set:

```bash
repo-ai context "$1"
```

Then read only the listed files, using `FindSymbol` for the named symbols and
the given line ranges rather than loading whole files. State which files you
opened and why before making any change.
""",
        "repo-orient.md": f"""---
description: Load the generated repository knowledge and summarise the project
---
Read `{context_dir_rel}/PROJECT_OVERVIEW.md` and `{context_dir_rel}/ARCHITECTURE.md`.

Then give me a short briefing:
1. What this project does, in two sentences.
2. Its components and how they communicate.
3. The build, run, and test commands.
4. The three files you would read first to make a change, and why.

Do not read any other files for this task.
""",
        "repo-refresh.md": """---
description: Re-analyse the repository and refresh the generated context
---
Run the incremental update and report what changed:

```bash
repo-ai update && repo-ai status
```

If the update reports that many files changed, tell me whether the architecture
summary is likely to need regeneration with `repo-ai rebuild`.
""",
        "repo-impact.md": """---
description: Assess the blast radius of changing a file
argument-hint: <path/to/file or SymbolName>
---
Run:

```bash
repo-ai impact "$1"
```

Then summarise: which modules depend on this file, which tests cover it, which
files historically change alongside it, and what could break. Respect the
uncertainty notes in the output. Do not make the change yet.
""",
    }


COMMAND_NAMES = ("repo-context.md", "repo-orient.md", "repo-refresh.md", "repo-impact.md")


def explorer_persona(context_dir_rel: str) -> str:
    return f"""---
name: repo-explorer
description: >-
  Explores this repository to answer a specific structural question and returns
  a compact summary. Read-only. Use for questions like "where is X handled",
  "what calls Y", or "how does subsystem Z fit together".
tools:
  - read
---

You are a codebase navigator working in a repository that has a pre-computed
context layer in `{context_dir_rel}/`.

Method, in order:

1. Run `repo-ai context "<the question>"` if the `execute` tool is available to
   you. Otherwise read `{context_dir_rel}/REPOSITORY_MAP.md`.
2. Open only the files it lists. Use `GetSymbolsOverview` and `FindSymbol`
   before `read_file`.
3. Follow at most two hops of imports from the shortlist.

Return **only** this, under 400 words:

**Answer** — a direct answer to the question.
**Key files** — a table of path, one-line role, and the specific line ranges
that matter.
**Uncertainties** — anything you could not confirm from the code.

Do not paste file contents. Do not propose changes. Do not read files that the
shortlist did not surface unless nothing else answers the question, and say so
if you do.
"""


def rules_pointer(context_dir_rel: str) -> str:
    """A tiny always-on rule that survives even if AGENTS.md is replaced."""
    return (
        "# Repository context\n\n"
        f"This repository has a generated context layer in `{context_dir_rel}/` "
        f"and a `{SKILL_NAME}` skill.\n\n"
        "- For any question about where code lives or how this project is "
        "structured, run `repo-ai context \"<task>\"` before exploring manually.\n"
        f"- Read `{context_dir_rel}/CONTEXT_INDEX.md` to see what knowledge is available.\n"
        f"- Never edit files in `{context_dir_rel}/` except `NOTES.md`.\n"
    )


# --------------------------------------------------------------------------
# .bobignore
# --------------------------------------------------------------------------
BOBIGNORE_HEADER = "# --- begin repo-ai managed block ---"
BOBIGNORE_FOOTER = "# --- end repo-ai managed block ---"

BASE_BOBIGNORE = [
    "# Secrets and credentials",
    ".env", ".env.*", "!.env.example", "!.env.sample", "!.env.template",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "id_rsa", "id_ed25519", "credentials", "credentials.json",
    "service-account*.json", ".npmrc", ".pypirc", ".netrc",
    "kubeconfig", "*.tfstate", "*.tfstate.backup", "terraform.tfvars",
    "",
    "# Dependencies and build output (Bob should read source, not artefacts)",
    "node_modules/", "vendor/", ".venv/", "venv/", "__pycache__/",
    "dist/", "build/", "target/", "out/", ".next/", ".nuxt/", ".turbo/",
    "coverage/", "htmlcov/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    "*.min.js", "*.min.css", "*.map",
    "",
    "# Lockfiles: huge, low information density",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Gemfile.lock", "composer.lock", "Cargo.lock", "go.sum", "uv.lock",
]


def bobignore_block(quarantined: list[str], internal_entries: list[str]) -> str:
    block = [BOBIGNORE_HEADER, *BASE_BOBIGNORE, "",
             "# repo-ai internals (the .md files stay readable)", *internal_entries]
    if quarantined:
        block.extend(["", "# Quarantined by the repo-ai secret scanner"])
        block.extend(sorted(quarantined))
    block.append(BOBIGNORE_FOOTER)
    return "\n".join(block)


def on_path(binary: str = "repo-ai") -> bool:
    from shutil import which
    return which(binary) is not None
