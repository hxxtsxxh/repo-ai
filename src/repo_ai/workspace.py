"""Orchestration: analysis -> docs -> learning -> skills -> agent wiring.

`init`, `update`, `rebuild`, `refresh` and the hooks all funnel through
`generate()`, so there is exactly one path that writes into a repository.
Everything except the SQLite index is written through a `Plan`, which makes
`--dry-run` / `--diff` exact and gives every write a backup.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .adapters import ADAPTERS, SetupContext, ordered
from .adapters.base import plan_gitignore, plan_remove_gitignore
from .analyze import run_analysis
from .config import Config
from .fsutil import Originals, Plan, managed_state, read_text, stamp_managed
from .index import open_index
from .logging_setup import get_logger
from .models import RepoFacts
from .paths import Layout, make_dir

log = get_logger()

CONTEXT_FILES = {
    "PROJECT_OVERVIEW.md": "overview",
    "ARCHITECTURE.md": "architecture",
    "REPOSITORY_MAP.md": "repo map",
    "DEPENDENCIES.md": "dependencies",
    "TESTING.md": "testing",
    "CONVENTIONS.md": "conventions",
    "HOTSPOTS.md": "hotspots",
    "SECURITY_NOTES.md": "security",
    "CONTEXT_INDEX.md": "index",
}

_VOLATILE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
VALID_AGENTS = ("claude", "bob")


@dataclass(slots=True)
class Outcome:
    facts: RepoFacts
    plan: Plan
    layout: Layout
    agents: tuple[str, ...]
    notes: list[str] = field(default_factory=list)
    rules_active: int = 0
    rules_proposed: int = 0
    rule_changes: list[tuple[str, str, str]] = field(default_factory=list)
    skills_active: list[str] = field(default_factory=list)
    skills_candidates: list[tuple[str, str]] = field(default_factory=list)
    event_id: str = ""
    elapsed: float = 0.0
    applied: bool = False


# --------------------------------------------------------------------------
# agents bookkeeping
# --------------------------------------------------------------------------
def recorded_agents(root: Path, cfg: Config, layout: Layout) -> tuple[str, ...] | None:
    """Agents chosen at init: config first, then index metadata. None = unknown."""
    if cfg.agents:
        return tuple(a for a in VALID_AGENTS if a in cfg.agents)
    if not layout.index_path.is_file():
        return None
    try:
        index = open_index(layout.state_dir)
    except Exception:
        return None
    try:
        raw = index.get_meta("agents")
        if raw:
            try:
                return tuple(a for a in VALID_AGENTS if a in json.loads(raw))
            except ValueError:
                pass
        legacy = index.get_meta("wire_bob")
        if legacy:
            return ("bob",) if legacy != "0" else ()
        return ("bob",)  # v0.4 index without metadata: Bob was wired by default
    finally:
        index.close()


CONFIG_TEMPLATE = """# repo-ai project settings — created by `repo-ai init`; edit freely.
# repo-ai never rewrites this file except the `agents` line, and only when
# you run `repo-ai init --agent ...` with a new agent. Docs: docs/CONFIGURATION.md
{out_dir_line}
agents = [{agents}]

# What repo-ai may change on its own (docs/LEARNING.md):
#   off | suggest | safe-auto | manual-only-for-risky
learning_policy = "{policy}"
# Minimal local workflow signals: off | known-commands | outcomes (never prompts or output)
learning_signals = "{signals}"
# Generated skills: off | curated | auto
skills_mode = "{skills}"
# Capability set: core (verification guidance, context, hooks, curated skills)
#   | full (adds subagents, the skeptic reviewer and orchestration hints)
feature_set = "{feature_set}"

# commit_context = true       # false: keep generated docs out of git
# local_only = false          # true: personal setup (settings.local.json, all ignored)
# hook_budget_tokens = 1200   # hard cap on per-prompt injected context
# hook_max_files = 8
# verify_gate = false         # true: the Stop hook asks agents to run `repo-ai verify --run`
#                             #   once per change that has no passing evidence
# verify_gate_mode = "block"  # "report": never block; show the user one line of evidence status
# verify_gate_max_blocks = 3  # at most this many blocks per agent session
# verify_test_command = ""    # e.g. "PYTHONPATH=src python -m pytest tests": the command
#                             #   `repo-ai verify` runs (sandboxed, only with --run/--record)
#                             #   when it cannot establish one from the project's files
"""


def _agents_toml(agents: tuple[str, ...]) -> str:
    return ", ".join(f'"{a}"' for a in agents)


def plan_config(plan: Plan, layout: Layout, cfg: Config, agents: tuple[str, ...]) -> list[str]:
    """Create .repo-ai/config.toml once; afterwards only the agents line changes."""
    notes: list[str] = []
    path = layout.config_path
    current = plan.current(path)
    if current is None:
        out_dir = (f'out_dir = "{layout.context_rel}"   # keeps the existing layout'
                   if layout.kind in {"legacy", "custom"} else "")
        body = CONFIG_TEMPLATE.format(out_dir_line=out_dir, agents=_agents_toml(agents),
                                      policy=cfg.learning_policy, signals=cfg.learning_signals,
                                      skills=cfg.skills_mode, feature_set=cfg.feature_set or "core")
        plan.write(path, stamp_managed(body, "config", comment="hash"))
        return notes
    line = f"agents = [{_agents_toml(agents)}]"
    if re.search(r"(?m)^agents\s*=.*$", current):
        updated = re.sub(r"(?m)^agents\s*=.*$", line, current, count=1)
    else:
        updated = current.rstrip("\n") + "\n" + line + "\n"
    if cfg.extra.get("_feature_set_flag"):  # `init --feature-set`: record the choice
        fs = f'feature_set = "{cfg.feature_set}"'
        if re.search(r"(?m)^feature_set\s*=.*$", updated):
            updated = re.sub(r"(?m)^feature_set\s*=.*$", fs, updated, count=1)
        else:
            updated = updated.rstrip("\n") + "\n" + fs + "\n"
    if updated != current:
        plan.write(path, updated)
    return notes


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------
def generate(
    root: Path,
    cfg: Config,
    layout: Layout,
    agents: tuple[str, ...],
    *,
    incremental: bool,
    dry_run: bool = False,
    smart: bool = False,
    write_config: bool = False,
    learn_apply: tuple[str, ...] = (),
    learn_apply_safe: bool = False,
    learn_reject: tuple[str, ...] = (),
    skills_generate: tuple[str, ...] = (),
    skills_generate_safe: bool = False,
) -> Outcome:
    from . import learning, llm, render, skills
    import time

    started = time.monotonic()
    tmp_dir: Path | None = None
    if dry_run:
        tmp_dir = Path(tempfile.mkdtemp(prefix="repo-ai-dry-"))
        state_dir = tmp_dir
        if layout.index_path.is_file() and incremental:
            shutil.copy2(layout.index_path, tmp_dir / "index.db")
    else:
        state_dir = layout.state_dir
        make_dir(layout.root, state_dir)

    prune = tuple(sorted({layout.rel(d) for d in layout.owned_dirs() if layout.root in d.parents}))
    try:
        result = run_analysis(root, cfg, layout.context_dir, incremental=incremental,
                              state_dir=state_dir, prune=prune)
        facts = result.facts
        plan = Plan(root)

        narrative = ""
        if cfg.summarize and not dry_run:
            narrative = llm.summarize(facts, root, cfg.bob_binary, cfg.summarize_max_cost)

        index = open_index(state_dir)
        try:
            external = [(r["pkg"], r["n"]) for r in index.conn.execute(
                "SELECT external_package AS pkg, COUNT(DISTINCT src_path) AS n "
                "FROM imports WHERE external_package != '' "
                "GROUP BY external_package ORDER BY n DESC, pkg LIMIT 80")]
            overview = render.render_overview(facts)
            if narrative:
                overview += "\n" + llm.render_summary_section(narrative)
            outputs = {
                "PROJECT_OVERVIEW.md": overview,
                "ARCHITECTURE.md": render.render_architecture(facts),
                "REPOSITORY_MAP.md": render.render_repo_map(
                    facts, render.directory_stats(result.scan.files), cfg.max_repo_map_entries),
                "DEPENDENCIES.md": render.render_dependencies(facts, external),
                "TESTING.md": render.render_testing(facts),
                "CONVENTIONS.md": render.render_conventions(facts),
                "HOTSPOTS.md": render.render_hotspots(facts),
                "SECURITY_NOTES.md": render.render_security_notes(facts, result.scan.quarantined),
                "CONTEXT_INDEX.md": render.render_context_index(facts, list(CONTEXT_FILES)),
            }
            for name, body in outputs.items():
                plan.write_if_changed(layout.context_dir / name, body, _VOLATILE)
            notes_path = layout.context_dir / "NOTES.md"
            if not notes_path.exists():
                plan.write(notes_path, render.render_notes_stub(facts))
            plan.write_if_changed(layout.context_dir / "facts.json", facts.to_json(), _VOLATILE)

            # -- learning + skills ------------------------------------------------
            signals_on = cfg.learning_signals in ("known-commands", "outcomes")
            cycle = learning.run_cycle(root, layout, facts, index, cfg.learning_policy,
                                       signals=signals_on, apply_ids=learn_apply,
                                       apply_safe=learn_apply_safe, reject_ids=learn_reject)
            factory = skills.FactoryResult()
            if "claude" in agents and cfg.write_claude_skills:
                factory = skills.run_factory(
                    root, layout, facts, index, mode=cfg.skills_mode, policy=cfg.learning_policy,
                    signals=signals_on, generate=skills_generate,
                    generate_safe=skills_generate_safe, persist=not dry_run,
                    max_active=cfg.max_generated_skills)
            if not dry_run:
                index.set_meta("agents", json.dumps(list(agents)))
                index.set_meta("wire_bob", "1" if "bob" in agents else "0")
                index.set_meta("tool_version", __version__)
        finally:
            index.close()

        ctx = SetupContext(root=root, cfg=cfg, layout=layout, agents=agents, plan=plan,
                           facts=facts, quarantined=result.scan.quarantined, smart=smart,
                           rules=cycle.ledger.active(), skills=factory.active)
        for name in ordered(agents):
            ADAPTERS[name].plan_install(ctx)

        ignore = layout.runtime_ignore_entries()
        if not cfg.commit_context or cfg.local_only:
            ignore += [f"{layout.context_rel}/", f"{layout.learning_rel}/"]
            if layout.kind == "standard":
                ignore.append(".repo-ai/config.toml")
        if cfg.local_only:
            for name in ordered(agents):
                ignore += ADAPTERS[name].local_only_ignores(ctx)
        # a custom layout too: its index, lock and evidence would otherwise count as part of the change being verified
        if agents or layout.kind in {"standard", "custom"} or cfg.local_only or not cfg.commit_context:
            plan_gitignore(plan, root, ignore)
        if write_config or layout.config_path.is_file():
            ctx.notes += plan_config(plan, layout, cfg, agents)

        outcome = Outcome(facts=facts, plan=plan, layout=layout, agents=agents, notes=ctx.notes,
                          rules_active=len(cycle.ledger.active()),
                          rules_proposed=sum(1 for r in cycle.ledger.rules.values()
                                             if r.status == "proposed"),
                          rule_changes=cycle.changes,
                          skills_active=[s.name for s in factory.active],
                          skills_candidates=[(s.name, st) for s, st, _ in factory.candidates])
        if dry_run:
            return outcome

        applied = plan.apply(layout.backup_dir, originals=Originals(layout.originals_path))
        outcome.applied = True
        if cycle.changed:
            cycle.ledger.save()
        agent_changes = [(plan.rel(c.path), c.before, c.after) for c in applied
                         if layout.context_dir not in c.path.parents
                         and layout.learning_dir not in c.path.parents]
        if (cycle.changed or factory.changed) and (agent_changes or cycle.changes):
            outcome.event_id = learning.record_event(
                layout, "update", cycle.changes, agent_changes)
        outcome.elapsed = time.monotonic() - started
        return outcome
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# uninstall
# --------------------------------------------------------------------------
def plan_uninstall(root: Path, cfg: Config, layout: Layout, remove: tuple[str, ...],
                   configured: tuple[str, ...]) -> tuple[Plan, tuple[str, ...]]:
    from . import render

    plan = Plan(root)
    ctx = SetupContext(root=root, cfg=cfg, layout=layout, agents=configured, plan=plan)
    for name in ordered(remove):
        ADAPTERS[name].plan_uninstall(ctx)
    remaining = tuple(a for a in configured if a not in remove)
    if remaining:
        if layout.config_path.is_file():
            plan_config(plan, layout, cfg, remaining)
        plan.restore_originals(Originals(layout.originals_path))
        return plan, remaining

    # Nothing left: remove repo-ai's own data too.
    plan_remove_gitignore(plan, root)
    for name in [*CONTEXT_FILES, "facts.json"]:
        if (layout.context_dir / name).exists():
            plan.delete(layout.context_dir / name)
    notes = layout.context_dir / "NOTES.md"
    if notes.is_file():
        stub = render.render_notes_stub(RepoFacts(name=root.name))
        if notes.read_text("utf-8", errors="replace") == stub:
            plan.delete(notes)
        else:
            plan.skip(notes, "contains your notes; kept")
    for tree in (layout.learning_dir, layout.backup_dir):
        plan.delete_tree(tree)
    # every store repo-ai writes in its state directory: the index, markers, verify's and ProofLab's records
    # (claims, pinned scenarios, passports); anything else there is not repo-ai's and is kept
    names = ["index.db", "index.db-wal", "index.db-shm", ".dirty", "update.lock",
             "last-refresh", "signals.jsonl", ".dirty.processing", "originals.json",
             "flight.jsonl", "ranking.json", "episodes", "testmap.json", "gate.json", "evidence",
             "runs.jsonl", "sarif", "prove", "missions"]
    if layout.state_dir.is_dir():
        names += sorted(p.name for p in layout.state_dir.glob("verify-*.json"))
    for name in dict.fromkeys(names):
        path = layout.state_dir / name
        if path.exists():
            _schedule_binary_delete(plan, path)
    if layout.config_path.is_file():
        if managed_state(read_text(layout.config_path)) == "pristine":
            plan.delete(layout.config_path)
        else:
            plan.skip(layout.config_path, "edited by hand; kept")
    for directory in (layout.state_dir, layout.context_dir, layout.learning_dir, root / ".repo-ai"):
        plan.remove_dir_if_empty(directory)
    plan.restore_originals(Originals(layout.originals_path))
    # User-selected report destinations have no ownership ledger. Preserve
    # them, but disclose every retained file in both the preview and execution.
    pending = [root / ".repo-ai"]
    known = {p for p, _ in plan.skipped}
    while pending:
        directory = pending.pop()
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            children = sorted(directory.iterdir())
        except OSError:
            plan.skip(directory, "unreadable user directory; kept")
            continue
        for path in children:
            if path in plan.removed_trees or path in known:
                continue
            change = plan.changes.get(path)
            if change is not None and change.after is None:
                continue
            if path.is_dir() and not path.is_symlink():
                pending.append(path)
            else:
                plan.skip(path, "user file or exported report; kept")
    return plan, remaining


def _schedule_binary_delete(plan: Plan, path: Path) -> None:
    # Binary state (the SQLite index) cannot be diffed as text; Plan.apply
    # unlinks files and removes directories listed here.
    if path not in plan.removed_trees:
        plan.removed_trees.append(path)
