"""Claude Code plugin bundle (optional distribution channel).

The plugin carries the same skills, subagents and hooks as `repo-ai init
--agent claude`, rendered from the same source (`adapters/claude_content.py`)
so the two channels cannot drift. Differences, by design:

  * plugin skills are namespaced by Claude Code (`/repo-ai:locate`), so they
    drop the `repo-` prefix;
  * they reach generated docs through the CLI (`repo-ai overview`, ...)
    because the context directory differs between repositories;
  * plugin hooks are global but inert: the hook runtime does nothing in a
    repository without a repo-ai index.

`python scripts/build_plugin.py` regenerates `integrations/claude-plugin/`;
a test fails if the committed copy is stale.
"""

from __future__ import annotations

import json

from . import __version__
from .adapters import claude_content as content

PLUGIN_NAME = "repo-ai"
CONTEXT_PLACEHOLDER = "<context dir: see `repo-ai status`>"

HOOK_SCRIPT = content.HOOK_SCRIPT.replace(
    "# Claude Code hook dispatcher for repo-ai.",
    "# Claude Code hook dispatcher for repo-ai (plugin copy).\n"
    "# Inert in repositories without a repo-ai index.")


def _plugin_skill_body(body: str) -> str:
    """Point at CLI commands instead of a repo-specific context directory."""
    ph = CONTEXT_PLACEHOLDER
    for doc, command in (("PROJECT_OVERVIEW.md", "repo-ai overview"),
                         ("ARCHITECTURE.md", "repo-ai architecture"),
                         ("CONVENTIONS.md", "repo-ai conventions"),
                         ("REPOSITORY_MAP.md", "repo-ai map"),
                         ("TESTING.md", "repo-ai tests")):
        body = body.replace(f"`{ph}/{doc}`", f"the output of `{command}`")
    body = body.replace(f"`{ph}/SECURITY_NOTES.md`", "SECURITY_NOTES.md (`repo-ai status` shows "
                                                     "where the context directory is)")
    assert ph not in body, "unmapped context path in plugin content"
    return body


def render_plugin() -> dict[str, str]:
    files: dict[str, str] = {}
    files[".claude-plugin/plugin.json"] = json.dumps({
        "name": PLUGIN_NAME,
        "version": __version__,
        "description": "Repository intelligence for Claude Code: task-ranked file shortlists on "
                       "each prompt, change impact, verification and review workflows. Requires "
                       "the `repo-ai` CLI and `repo-ai init` in each repository.",
        "author": {"name": "repo-ai contributors"},
        "license": "MIT",
        "keywords": ["context", "retrieval", "code-intelligence", "impact-analysis"],
    }, indent=2) + "\n"
    for skill in [*content.curated_skills(CONTEXT_PLACEHOLDER, ""), *content.management_skills()]:
        # Namespaced as /repo-ai:<name>; still avoid built-in command names.
        short = {"repo-review": "review-diff"}.get(skill.name, skill.name.removeprefix("repo-"))
        doc = content.SkillDoc(short, skill.description, _plugin_skill_body(skill.body),
                               skill.argument_hint, skill.manual_only)
        files[f"skills/{short}/SKILL.md"] = doc.render()
    for agent in content.subagents(CONTEXT_PLACEHOLDER):
        agent_doc = content.AgentDoc(agent.name, agent.description, agent.tools,
                                     _plugin_skill_body(agent.body))
        files[f"agents/{agent.name}.md"] = agent_doc.render()

    def cmd(event: str, timeout: int) -> dict:
        return {"type": "command",
                "command": f'sh "${{CLAUDE_PLUGIN_ROOT}}/hooks/repo-ai.sh" {event}',
                "timeout": timeout}
    files["hooks/hooks.json"] = json.dumps({"hooks": {
        "SessionStart": [{"hooks": [cmd("session-start", 10)]}],
        "UserPromptSubmit": [{"hooks": [cmd("prompt", 10)]}],
        "PostToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit",
                         "hooks": [cmd("post-edit", 5)]}],
        "Stop": [{"hooks": [cmd("stop", 10)]}],
    }}, indent=2) + "\n"
    files["hooks/repo-ai.sh"] = HOOK_SCRIPT
    files["README.md"] = PLUGIN_README.format(version=__version__)
    return files


def render_marketplace(plugin_path: str = "./integrations/claude-plugin") -> str:
    return json.dumps({
        "name": "repo-ai",
        "owner": {"name": "repo-ai contributors"},
        "description": "repo-ai: local repository intelligence for Claude Code",
        "plugins": [{
            "name": PLUGIN_NAME,
            "source": plugin_path,
            "description": "Task-ranked context, change impact, verify/review workflows "
                           "(needs the repo-ai CLI).",
            "version": __version__,
        }],
    }, indent=2) + "\n"


PLUGIN_README = """# repo-ai Claude Code plugin (v{version})

Optional alternative to per-project wiring. The plugin provides the repo-ai
skills (`/repo-ai:locate`, `/repo-ai:impact`, `/repo-ai:verify`, `/repo-ai:debug`,
`/repo-ai:review-diff`, `/repo-ai:orient`, `/repo-ai:learn`), four read-only-leaning
subagents, and the context hooks for every repository you open.

It does **not** replace the CLI: install `repo-ai` first, then run
`repo-ai init --agent claude` (or `--agent none` to skip project wiring) in each
repository so there is an index to read. In repositories without an index the
hooks do nothing.

Install from a clone of the repo-ai repository (or its git URL):

```sh
claude plugin marketplace add /path/to/repo-ai      # the directory holding .claude-plugin/
claude plugin install repo-ai@repo-ai
```

If you use the plugin, `repo-ai init --agent claude` notices it is enabled and
skips writing project hooks, so nothing runs twice. Project-generated skills
(`repo-add-endpoint`, `repo-tests`, ...) are still written per repository.

Generated from `src/repo_ai/plugin.py`; do not edit by hand.
"""
