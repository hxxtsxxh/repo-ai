"""Claude Code adapter.

Verified against Claude Code 2.1.x behaviour:

* CLAUDE.md is loaded every session. With the default `agents_md` mode
  (`claude-md-or-agents-md`) AGENTS.md is loaded **only when no CLAUDE.md
  exists**. So when repo-ai has to create a CLAUDE.md in a repo that already
  has an AGENTS.md, the new file imports it with `@AGENTS.md` — otherwise the
  user's AGENTS.md would silently stop loading.
* `.claude/rules/*.md` load alongside CLAUDE.md; `paths:` front matter makes a
  rule load only when Claude works with matching files.
* `.claude/skills/<name>/SKILL.md`: descriptions load up front, bodies on use;
  `disable-model-invocation: true` makes a skill slash-command-only.
* `.claude/agents/<name>.md`: subagents with a `tools` allow-list.
* `.claude/settings.json` `hooks`: SessionStart / UserPromptSubmit stdout (or
  `hookSpecificOutput.additionalContext`, max 10k chars) is added to context;
  exit code 2 blocks, so the dispatcher always exits 0.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..fsutil import managed_state, marker_attrs, read_text
from ..learning import human_instruction_text
from ..testing import human_verification, instructable, verification_plan, verify_line
from . import claude_content as content
from .base import (
    Adapter, Check, SettingsError, SetupContext, dump_settings, imports_agents_md,
    load_settings, merge_hook_entries, plan_block, plan_managed_file,
    plan_remove_block, plan_remove_managed_file, remove_hook_entries,
)

BEGIN = "<!-- BEGIN repo-ai:claude -->"
END = "<!-- END repo-ai:claude -->"
CREATED_HEADER = ("<!-- repo-ai created this file and imports AGENTS.md so Claude Code keeps "
                  "loading it. -->\n@AGENTS.md\n")
HOOK_SCRIPT_REL = ".claude/hooks/repo-ai.sh"
FILE_TOOLS = "Write|Edit|MultiEdit|NotebookEdit"


def skill_description_tokens(description_chars: int) -> int:
    """Always-loaded cost of one model-invocable skill, estimated as `repo-ai
    budget` does: ceil(chars / 4) for the description, plus 4 for its name.
    `doctor` and `skills audit` use it too, so the three agree."""
    return -(-description_chars // 4) + 4


def claude_reads_agents_md(ctx: SetupContext) -> bool:
    """Will Claude load AGENTS.md (via an import) once setup is applied?

    Single source of truth used by both adapters so `--agent both` produces
    one copy of shared guidance, not two, on the first run and every run after.
    """
    if "claude" not in ctx.agents:
        return False
    target = _instructions_path(ctx)
    text = read_text(target)
    if text is not None:
        return imports_agents_md(text)
    if ctx.cfg.local_only:
        return False
    return (ctx.root / "AGENTS.md").is_file() or "bob" in ctx.agents


def _instructions_path(ctx: SetupContext) -> Path:
    return ctx.root / ("CLAUDE.local.md" if ctx.cfg.local_only else "CLAUDE.md")


def _settings_path(ctx: SetupContext) -> Path:
    name = "settings.local.json" if ctx.cfg.local_only else "settings.json"
    return ctx.root / ".claude" / name


def is_repo_ai_claude_hook(entry: dict) -> bool:
    return any(isinstance(h, dict) and ("repo-ai.sh" in str(h.get("command", ""))
                                        or "repo-ai hook claude" in str(h.get("command", "")))
               for h in entry.get("hooks", []))


def hook_entries(signals: bool, outcomes: bool = False) -> dict[str, list[dict]]:
    def cmd(event: str, timeout: int) -> dict:
        return {"type": "command",
                "command": f'sh "$CLAUDE_PROJECT_DIR/{HOOK_SCRIPT_REL}" {event}',
                "timeout": timeout}
    entries: dict[str, list[dict]] = {
        "SessionStart": [{"hooks": [cmd("session-start", 10)]}],
        "UserPromptSubmit": [{"hooks": [cmd("prompt", 10)]}],
        "PostToolUse": [{"matcher": FILE_TOOLS, "hooks": [cmd("post-edit", 5)]}],
        "Stop": [{"hooks": [cmd("stop", 10)]}],
    }
    if signals:
        # Only with `learning_signals = "known-commands"`: records which of the
        # repository's own known commands ran and whether they failed. Never
        # stores command output, prompts, or unknown command text.
        entries["PostToolUse"].append({"matcher": "Bash", "hooks": [cmd("post-bash", 5)]})
        entries["PostToolUseFailure"] = [{"matcher": "Bash", "hooks": [cmd("post-bash-failure", 5)]}]
    if outcomes:
        # Only with `learning_signals = "outcomes"`: which skill (name and
        # version) a session used, so skill versions can be compared on
        # outcomes. Arguments are never recorded.
        entries["PostToolUse"].append({"matcher": "Skill", "hooks": [cmd("post-skill", 5)]})
    return entries


def plugin_enabled(root: Path) -> bool:
    """Is the repo-ai Claude plugin enabled? Then its hooks already run."""
    candidates = [Path.home() / ".claude" / "settings.json",
                  root / ".claude" / "settings.json", root / ".claude" / "settings.local.json"]
    for path in candidates:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        enabled = data.get("enabledPlugins") if isinstance(data, dict) else None
        if isinstance(enabled, dict) and any(str(k).startswith("repo-ai@") and v
                                             for k, v in enabled.items()):
            return True
    return False


# --------------------------------------------------------------------------
# CLAUDE.md block
# --------------------------------------------------------------------------
def build_claude_block(ctx: SetupContext, slim: bool) -> str:
    facts = ctx.facts
    assert facts is not None
    rel = ctx.layout.context_rel
    lines = [BEGIN, "## Repository context (managed by repo-ai; edits inside this block are overwritten)", ""]
    if not slim:
        langs = ", ".join(list(facts.languages)[:3]) or "unknown"
        comps = ", ".join(f"`{c.root}`" for c in facts.components[:6] if c.root != ".")
        lines.append(f"**{facts.name}** — {langs}" + (f"; components {comps}." if comps else "."))
    plan = verification_plan(facts.commands, facts.test_suites)
    # static checks are named only while an active learned rule backs them:
    # a rule demoted by counterevidence stops being presented
    active_lint = {getattr(r, "subject", "") for r in ctx.rules if getattr(r, "kind", "") == "lint"}
    stated = [c.command for c in plan.static if c.command in active_lint]
    lines.append(verify_line(plan, human_verification(human_instruction_text(ctx.root), plan), stated))
    if not slim:
        cmd_parts = [f"{kind} `{(facts.commands.get(kind) or [''])[0]}`" for kind in ("build", "run")
                     if (facts.commands.get(kind) or [""])[0] and instructable(facts.commands[kind][0])]
        if cmd_parts:
            lines.append("Other commands (declared in manifests/docs): " + " · ".join(cmd_parts))
    # lint rules are already part of the Verify line, as complements to the tests
    rule_lines = [r.text for r in ctx.rules if getattr(r, "placement", "") == "claude-md"
                  and not (getattr(r, "kind", "") == "lint" and getattr(r, "subject", "") in stated[:2])]
    if rule_lines:
        lines.append("Project rules (evidence-backed; `repo-ai learn --explain` shows sources):")
        lines.extend(f"- {text}" for text in rule_lines[:8])
    lines.append(
        "Context: a hook adds a ranked file shortlist to relevant prompts. For more, use "
        "`/repo-locate <task>`, `/repo-impact <path>`, `/repo-verify`, or "
        "`repo-ai context \"<task>\"`. Maps: "
        f"`{rel}/ARCHITECTURE.md`, `{rel}/REPOSITORY_MAP.md`, `{rel}/TESTING.md`.")
    if not slim:
        generated = list((facts.conventions.get("generated_paths") or [])[:4])
        boundary = [f"`{rel}/` is regenerated (human notes go in `{rel}/NOTES.md`)"]
        if generated:
            boundary.insert(0, "generated, do not hand-edit: " + ", ".join(f"`{g}`" for g in generated))
        if ctx.quarantined:
            boundary.append(f"never open files listed in `{rel}/SECURITY_NOTES.md`")
        lines.append("Boundaries: " + "; ".join(boundary) + ".")
    lines.append(END)
    return "\n".join(lines)


class ClaudeAdapter(Adapter):
    name = "claude"

    # -- install ----------------------------------------------------------------
    def plan_install(self, ctx: SetupContext) -> None:
        facts = ctx.facts
        assert facts is not None
        cfg = ctx.cfg
        plan = ctx.plan
        claude_dir = ctx.root / ".claude"
        rel = ctx.layout.context_rel

        if cfg.write_claude_md:
            target = _instructions_path(ctx)
            existing = plan.current(target)
            reads_agents = claude_reads_agents_md(ctx)
            # Shared guidance already reaches Claude through AGENTS.md's block.
            slim = reads_agents and "bob" in ctx.agents
            create_with = ""
            if existing is None:
                create_with = (CREATED_HEADER + "\n") if reads_agents else ""
            plan_block(plan, target, BEGIN, END, build_claude_block(ctx, slim),
                       create_with=create_with)

        if cfg.write_claude_skills and cfg.skills_mode != "off":
            test_cmd = verification_plan(facts.commands, facts.test_suites).test_command
            for skill in content.curated_skills(rel, test_cmd):
                plan_managed_file(plan, claude_dir / "skills" / skill.name / "SKILL.md",
                                  skill.render(), "claude-skill", attrs={"origin": "curated"})
            if cfg.management_skills:
                for skill in content.management_skills():
                    plan_managed_file(plan, claude_dir / "skills" / skill.name / "SKILL.md",
                                      skill.render(), "claude-skill", attrs={"origin": "curated"})
        wanted_generated = {s.name for s in ctx.skills}
        for spec in ctx.skills:
            plan_managed_file(plan, claude_dir / "skills" / spec.name / "SKILL.md",
                              spec.render(), "claude-skill",
                              attrs={"origin": "generated", "version": str(spec.version)})
        self._retire_generated_skills(ctx, wanted_generated)

        if cfg.write_claude_agents:
            for agent in content.subagents(rel):
                plan_managed_file(plan, claude_dir / "agents" / f"{agent.name}.md",
                                  agent.render(), "claude-agent")
            skeptic = claude_dir / "agents" / f"{content.SKEPTIC.name}.md"
            if cfg.skeptic_reviewer:
                plan_managed_file(plan, skeptic, content.SKEPTIC.render(), "claude-agent")
            elif skeptic.exists():
                plan_remove_managed_file(plan, skeptic)
        else:
            # switched off (e.g. feature_set = "core"): retire the agents repo-ai
            # installed; hand-edited or user-written agents are kept
            for agent in [*content.subagents(rel), content.SKEPTIC]:
                path = claude_dir / "agents" / f"{agent.name}.md"
                if path.exists():
                    plan_remove_managed_file(plan, path)

        if cfg.write_claude_rules:
            self._plan_rules(ctx)

        if cfg.write_claude_hooks:
            if plugin_enabled(ctx.root):
                ctx.notes.append("the repo-ai Claude plugin is enabled, so project hooks were "
                                 "not written (they would run twice)")
                self._remove_hooks(ctx)
            else:
                plan_managed_file(plan, ctx.root / HOOK_SCRIPT_REL, content.HOOK_SCRIPT,
                                  "claude-hook", executable=True, comment="hash")
                settings_path = _settings_path(ctx)
                try:
                    data = load_settings(plan.current(settings_path))
                    merged = merge_hook_entries(
                        data, hook_entries(cfg.learning_signals in ("known-commands", "outcomes"),
                                           cfg.learning_signals == "outcomes"),
                        is_repo_ai_claude_hook)
                    plan.write_shared(settings_path, dump_settings(merged, plan.current(settings_path)))
                except SettingsError as exc:
                    plan.skip(settings_path, f"{exc}; fix it and re-run — not overwritten")
                    ctx.notes.append(f"{settings_path.name} is not valid JSON; hooks not installed")

    def _plan_rules(self, ctx: SetupContext) -> None:
        rules_dir = ctx.root / ".claude" / "rules"
        by_topic: dict[str, list] = {}
        for rule in ctx.rules:
            if getattr(rule, "placement", "") == "rules":
                by_topic.setdefault(rule.topic, []).append(rule)
        wanted: set[Path] = set()
        for topic, rules in sorted(by_topic.items()):
            paths = sorted({p for r in rules for p in r.paths})
            body = []
            if paths:
                body += ["---", "paths:"] + [f'  - "{p}"' for p in paths] + ["---"]
            body += [f"# {topic.replace('-', ' ').capitalize()} (managed by repo-ai)", ""]
            body += [f"- {r.text}" for r in rules]
            body += ["", "Evidence and history: `repo-ai learn --explain`."]
            path = rules_dir / f"repo-ai-{topic}.md"
            wanted.add(path)
            plan_managed_file(ctx.plan, path, "\n".join(body) + "\n", "claude-rule")
        # Retire rule files whose evidence disappeared.
        if rules_dir.is_dir():
            for path in sorted(rules_dir.glob("repo-ai-*.md")):
                if path not in wanted and managed_state(read_text(path)) == "pristine":
                    ctx.plan.delete(path, note="rule retired: evidence no longer present")

    def _retire_generated_skills(self, ctx: SetupContext, wanted: set[str]) -> None:
        skills_dir = ctx.root / ".claude" / "skills"
        if not skills_dir.is_dir():
            return
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            text = read_text(skill_md) or ""
            attrs = marker_attrs(text)
            if attrs.get("origin") != "generated" or skill_md.parent.name in wanted:
                continue
            if managed_state(text) == "pristine":
                ctx.plan.delete(skill_md, note="generated skill retired")
                ctx.plan.remove_dir_if_empty(skill_md.parent)

    def _remove_hooks(self, ctx: SetupContext) -> None:
        for name in ("settings.json", "settings.local.json"):
            path = ctx.root / ".claude" / name
            current = ctx.plan.current(path)
            if current is None:
                continue
            try:
                data = load_settings(current)
            except SettingsError as exc:
                ctx.plan.skip(path, f"{exc}; repo-ai hooks not removed")
                continue
            cleaned = remove_hook_entries(data, is_repo_ai_claude_hook)
            if cleaned == data:
                continue
            if cleaned:
                ctx.plan.write_shared(path, dump_settings(cleaned, current))
            else:
                ctx.plan.delete(path, shared=True)
        plan_remove_managed_file(ctx.plan, ctx.root / HOOK_SCRIPT_REL)

    # -- uninstall ----------------------------------------------------------------
    def plan_uninstall(self, ctx: SetupContext) -> None:
        plan = ctx.plan
        claude_dir = ctx.root / ".claude"
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            plan_remove_block(plan, ctx.root / name, BEGIN, END,
                              delete_if=lambda rest: rest.strip() in {"", CREATED_HEADER.strip()})
        for skill_md in sorted(claude_dir.glob("skills/*/SKILL.md")):
            if marker_attrs(read_text(skill_md) or "").get("kind") == "claude-skill":
                plan_remove_managed_file(plan, skill_md)
        for agent in (*content.SUBAGENT_NAMES, *content.OPTIONAL_SUBAGENT_NAMES):
            plan_remove_managed_file(plan, claude_dir / "agents" / f"{agent}.md")
        from ..portfolio import remove_all_plan
        remove_all_plan(ctx.root, plan)  # approved third-party skills (unedited files only)
        for rule in sorted(claude_dir.glob("rules/repo-ai-*.md")):
            plan_remove_managed_file(plan, rule)
        self._remove_hooks(ctx)
        plan.remove_dir_if_empty(claude_dir / "skills")
        plan.remove_dir_if_empty(claude_dir / "hooks")

    def local_only_ignores(self, ctx: SetupContext) -> list[str]:
        out = [".claude/hooks/repo-ai.sh", ".claude/rules/repo-ai-*.md"]
        out += [f".claude/skills/{n}/" for n in content.CURATED_SKILL_NAMES]
        out += [f".claude/skills/{n}/" for n in content.NATIVE_MANAGEMENT_SKILLS]
        out += [f".claude/skills/{s.name}/" for s in ctx.skills]
        out += [f".claude/agents/{n}.md" for n in content.SUBAGENT_NAMES]
        out.append("CLAUDE.local.md")
        return out

    # -- doctor -------------------------------------------------------------------
    def doctor(self, ctx: SetupContext) -> list[Check]:
        checks: list[Check] = []
        binary = shutil.which("claude")
        if binary:
            version = _claude_version(binary)
            checks.append(Check("claude CLI", "ok", version or binary))
        else:
            checks.append(Check("claude CLI", "warn", "not found on PATH",
                                "install Claude Code; indexing works without it"))

        target = _instructions_path(ctx)
        text = read_text(target)
        has_block = bool(text and BEGIN in text)
        checks.append(Check(f"{target.name} managed block", "ok" if has_block else "fail",
                            "" if has_block else "missing", "repo-ai update"))
        if text:
            block = text[text.find(BEGIN):text.find(END) + len(END)] if has_block else ""
            tokens = len(text) // 4
            checks.append(Check(f"{target.name} size",
                                "ok" if tokens < 2500 else "warn",
                                f"~{tokens} tokens total, repo-ai block ~{len(block) // 4}"))
        agents_md = ctx.root / "AGENTS.md"
        if agents_md.is_file() and text is not None and not imports_agents_md(text):
            checks.append(Check("AGENTS.md visibility", "info",
                                "Claude Code (default agents_md mode) does not load AGENTS.md "
                                "when CLAUDE.md exists",
                                "add a line `@AGENTS.md` to CLAUDE.md if Claude should read it"))

        script = ctx.root / HOOK_SCRIPT_REL
        settings_path = _settings_path(ctx)
        if plugin_enabled(ctx.root):
            checks.append(Check("hooks", "ok", "provided by the enabled repo-ai plugin"))
        else:
            state = managed_state(read_text(script))
            checks.append(Check("hook dispatcher", "ok" if state == "pristine" else "fail",
                                f"{HOOK_SCRIPT_REL} ({state})", "repo-ai update"))
            if script.is_file() and not os.access(script, os.X_OK):
                checks.append(Check("hook dispatcher executable", "warn", "not executable",
                                    f"chmod +x {HOOK_SCRIPT_REL} (hooks invoke it via `sh`, so this is cosmetic)"))
            try:
                data = load_settings(read_text(settings_path))
                hooks = data.get("hooks") or {}
                for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
                    commands = [h.get("command", "") for e in hooks.get(event, [])
                                if isinstance(e, dict) and is_repo_ai_claude_hook(e)
                                for h in e.get("hooks", []) if isinstance(h, dict)]
                    dupes = len(commands) - len(set(commands))
                    status = "fail" if not commands else ("warn" if dupes else "ok")
                    checks.append(Check(f"{event} hook", status,
                                        f"{settings_path.relative_to(ctx.root)}"
                                        + (f" ({dupes} duplicate entr{'y' if dupes == 1 else 'ies'})"
                                           if dupes else ""),
                                        "repo-ai update"))
            except SettingsError as exc:
                checks.append(Check(settings_path.name, "fail", str(exc), "fix the JSON by hand"))

        from ..skillcheck import validate_skill_file
        skills_dir = ctx.root / ".claude" / "skills"
        names = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []
        ours = [n for n in names
                if marker_attrs(read_text(skills_dir / n / "SKILL.md") or "").get("kind") == "claude-skill"]
        problems = []
        desc_tokens = manual = 0
        for name in ours:
            report = validate_skill_file(skills_dir / name / "SKILL.md")
            if report.manual_only:
                manual += 1  # its description is never offered to the model
            else:
                desc_tokens += skill_description_tokens(report.description_chars)
            problems += [f"{name}: {p}" for p in report.errors]
        checks.append(Check("skills", "ok" if ours and not problems else ("fail" if problems else "warn"),
                            f"{len(ours)} repo-ai skill(s), descriptions ~{desc_tokens} tokens"
                            + (f" ({manual} manual-only, not counted)" if manual else "")
                            + (f"; {'; '.join(problems[:3])}" if problems else ""),
                            "repo-ai update"))
        if binary and (ctx.root / ".claude").is_dir():
            try:
                proc = subprocess.run([binary, "plugin", "validate", str(ctx.root / ".claude")],
                                      capture_output=True, text=True, timeout=60, check=False)
                passed = proc.returncode == 0 and "Validation passed" in proc.stdout
                checks.append(Check("Claude Code validation of .claude/", "ok" if passed else "fail",
                                    "claude plugin validate .claude" + ("" if passed else
                                                                       f": {proc.stdout[-300:]}")))
            except (OSError, subprocess.SubprocessError) as exc:
                checks.append(Check("Claude Code validation of .claude/", "warn", str(exc)))
        if not ctx.cfg.write_claude_agents:
            # none are installed by design; `repo-ai update` would not add them
            why = (f"feature_set = {ctx.cfg.feature_set}" if ctx.cfg.feature_set == "core"
                   else "write_claude_agents = false")
            checks.append(Check("subagents", "info", f"off ({why})"))
            return checks
        missing_agents = [a for a in content.SUBAGENT_NAMES
                          if not (ctx.root / ".claude" / "agents" / f"{a}.md").is_file()]
        checks.append(Check("subagents", "ok" if not missing_agents else "warn",
                            "all present" if not missing_agents else f"missing {', '.join(missing_agents)}",
                            "repo-ai update"))
        return checks


def _claude_version(binary: str) -> str:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10,
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or "").strip().splitlines()[0] if out.stdout else ""
