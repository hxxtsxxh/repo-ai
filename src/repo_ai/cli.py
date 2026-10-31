"""The `repo-ai` command line.

Setup and maintenance
  init        analyse the repo, generate context, wire agents (`--agent claude --smart`)
  update      incremental re-analysis + refresh of everything repo-ai owns
  rebuild     full re-analysis from scratch
  refresh     debounced, lock-protected update (what hooks call)
  status      freshness (exit 0 current, 2 stale, 1 not initialised)
  doctor      diagnose installation, agent wiring, hooks, skills, freshness
  uninstall   remove what repo-ai owns (per agent, with --dry-run)

Context
  context     task-aware retrieval — the core of the workflow
  explain     the same, with the per-signal score breakdown
  impact      change impact for a path, symbol, or the working-tree diff
  search / symbol / related / deps
  architecture / overview / map / tests / conventions / hotspots

Learning
  learn       evidence-backed project rules: list, explain, apply, history, rollback
  skills      generated skills: list, candidates, generate, audit, rollback

Imports are deliberately lazy: `repo-ai hook claude prompt` runs on every
prompt and must not pay for the analysis pipeline it does not use.
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import time
import os
import sys
from pathlib import Path

from . import __version__

AGENT_CHOICES = ("claude", "bob", "both", "auto", "none")


def _log():
    from .logging_setup import get_logger
    return get_logger()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def resolve_root(explicit: str | None) -> Path:
    from .gitinfo import find_repo_root, is_git_repo
    start = Path(explicit).expanduser().resolve() if explicit else Path.cwd()
    if not start.exists():
        raise SystemExit(f"error: path does not exist: {start}")
    if not start.is_dir():
        raise SystemExit(f"error: not a directory: {start}")
    if is_git_repo(start):
        return find_repo_root(start)
    return start


def overrides_from_args(args: argparse.Namespace) -> dict:
    keys = ("verbose", "quiet", "workers", "max_file_bytes", "git_history_days",
            "summarize", "max_context_files", "context_budget_tokens",
            "parse_symbols", "commit_context", "detect_secrets")
    return {k: getattr(args, k) for k in keys if getattr(args, k, None) is not None}


def _repo_config_keys(root: Path) -> set[str]:
    """Keys a human set explicitly in a repo config file (never overridden by --smart)."""
    from .config import _read_toml
    keys: set[str] = set()
    for rel in (".repo-ai/config.toml", ".repo-ai.toml", "repo-ai.toml"):
        path = root / rel
        if path.is_file():
            keys.update(k.replace("-", "_") for k in _read_toml(path))
    return keys


SMART_SETTINGS = {"learning_policy": "safe-auto", "learning_signals": "outcomes",
                  "skills_mode": "auto"}


def open_workspace(args: argparse.Namespace, prefer: str | None = None, extra: dict | None = None):
    from .config import load_config
    from .logging_setup import setup_logging
    from .paths import LayoutError, detect_kind, resolve_layout

    root = resolve_root(getattr(args, "path", None))
    overrides = overrides_from_args(args)
    overrides.update(extra or {})
    cfg = load_config(root, overrides)
    setup_logging(cfg.verbose, cfg.quiet)
    try:
        layout = resolve_layout(root, cfg, prefer=prefer or detect_kind(root) or "standard")
    except LayoutError as exc:
        raise SystemExit(f"error: {exc}") from exc
    from .optimize import apply_tuning
    return root, apply_tuning(cfg, layout), layout


INIT_HINT = "run `repo-ai init --agent claude` (or `--agent none` for verify only)"
BOB_DEFAULT_NOTICE = ("no --agent given: wiring IBM Bob (the v0.4 default); "
                      "for Claude Code use --agent claude")


def require_index(layout):
    from .index import IndexTooNew, open_index
    if not layout.index_path.is_file():
        raise SystemExit(
            f"error: no index at {layout.index_path}\n"
            f"       {INIT_HINT} in {layout.root} first.")
    try:
        return open_index(layout.state_dir)
    except IndexTooNew as exc:
        raise SystemExit(f"error: {exc}") from exc


def load_facts(layout) -> dict:
    path = layout.context_dir / "facts.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _facts_obj(layout):
    from .models import (Component, Dependency, GitFileStat, RepoFacts, Route, SecretHit,
                         TestSuite)
    data = load_facts(layout)
    if not data:
        return None
    facts = RepoFacts()
    for key, value in data.items():
        if hasattr(facts, key):
            setattr(facts, key, value)
    facts.components = [Component(**c) for c in data.get("components", [])]
    facts.dependencies = [Dependency(**d) for d in data.get("dependencies", [])]
    facts.routes = [Route(**r) for r in data.get("routes", [])]
    facts.test_suites = [TestSuite(**t) for t in data.get("test_suites", [])]
    facts.hotspots = [GitFileStat(**h) for h in data.get("hotspots", [])]
    facts.secret_hits = [SecretHit(**h) for h in data.get("secret_hits", [])]
    return facts


def _lock(layout, timeout: float = 120.0):
    from .locks import file_lock
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    return file_lock(layout.lock_path, timeout=timeout)


def _resolve_agents(arg: str | None, root: Path, existing: tuple[str, ...] | None,
                    no_bob: bool) -> tuple[tuple[str, ...], str]:
    """(agents, preferred layout). Agents only ever accumulate on re-init;
    removal is explicit (`repo-ai uninstall --agent X`)."""
    from shutil import which
    current = set(existing or ())
    if arg is None:
        if no_bob:
            return tuple(sorted(current - {"bob"})), "legacy"
        if existing is None:
            return ("bob",), "legacy"  # v0.4 behaviour: plain `repo-ai init` wires Bob
        return tuple(sorted(current)), "legacy"
    if arg == "none":
        return (), "standard"
    if arg == "both":
        return ("bob", "claude"), "standard"
    if arg == "auto":
        wanted = set()
        if (root / ".claude").is_dir() or (root / "CLAUDE.md").is_file() or which("claude"):
            wanted.add("claude")
        if (root / ".bob").is_dir() or which("bob"):
            wanted.add("bob")
        wanted = wanted or {"claude"}
        return tuple(sorted(current | wanted)), "standard"
    return tuple(sorted(current | {arg})), ("legacy" if arg == "bob" and not current else "standard")


# --------------------------------------------------------------------------
# init / update / rebuild / refresh
# --------------------------------------------------------------------------
def _print_plan(outcome, diff: bool, dry: bool) -> None:
    plan = outcome.plan
    label = "would change" if dry else "changed"
    effective = plan.effective()
    print(f"  {label} {len(effective)} file(s)" + (f", skipped {len(plan.skipped)}" if plan.skipped else ""))
    context_prefix = outcome.layout.context_rel + "/"
    context_changes = [c for c in effective if plan.rel(c.path).startswith(context_prefix)]
    for line in plan.summary_lines():
        rel = line.split()[-1] if line.strip() else ""
        if any(plan.rel(c.path) == rel for c in context_changes) and len(context_changes) > 3:
            continue
        print("  " + line)
    if len(context_changes) > 3:
        print(f"    (+ {len(context_changes)} generated docs under {context_prefix})")
    if diff:
        text = plan.diff(exclude=(context_prefix,))
        if text:
            print()
            sys.stdout.write(text)


def _onboarding_summary(outcome, cfg, reinit: bool) -> None:
    from .bobsetup import on_path
    facts = outcome.facts
    print()
    print(f"  repo-ai {__version__} — {facts.name}: {facts.indexed_files:,} files, "
          f"{facts.total_loc:,} LOC, {len(facts.components)} component(s)"
          + (f" [{', '.join(list(facts.languages)[:3])}]" if facts.languages else ""))
    agents = ", ".join(outcome.agents) or "none (docs only)"
    print(f"  agents: {agents}   learning: {cfg.learning_policy}   skills: {cfg.skills_mode}   "
          f"layout: {outcome.layout.context_rel}/")
    _print_plan(outcome, diff=False, dry=False)
    if outcome.rules_active or outcome.rules_proposed:
        print(f"  rules: {outcome.rules_active} active, {outcome.rules_proposed} proposed "
              "(`repo-ai learn` to review)")
    if outcome.skills_active:
        print(f"  generated skills: {', '.join(outcome.skills_active)}")
    if facts.secret_hits:
        high = sum(1 for h in facts.secret_hits if h.severity == "high")
        print(f"  ! secret scan: {len(facts.secret_hits)} finding(s), {high} high — "
              f"see {outcome.layout.context_rel}/SECURITY_NOTES.md")
    for note in outcome.notes:
        print(f"  ! {note}")
    for warning in facts.warnings:
        print(f"  ! {warning}")
    if outcome.agents and not on_path():
        print("  ! `repo-ai` is not on PATH, so agent hooks will silently do nothing.")
        print("    Install it as a tool (pipx/uv) or add its bin/ directory to PATH.")
    print()
    if "claude" in outcome.agents:
        print("  next: start `claude` here (restart open sessions to load hooks and skills).")
        print("        try /repo-orient, or just ask a task. check: repo-ai doctor --agent claude")
    elif "bob" in outcome.agents:
        print("  next: open this folder in Bob and ask a question. Try /repo-orient")
    print()


def cmd_init(args: argparse.Namespace) -> int:
    from .paths import detect_kind
    from .workspace import generate, recorded_agents

    probe_root = resolve_root(args.path)
    from .config import load_config
    probe_cfg = load_config(probe_root)
    from .paths import resolve_layout
    probe_layout = resolve_layout(probe_root, probe_cfg, prefer=detect_kind(probe_root) or "standard")
    existing = recorded_agents(probe_root, probe_cfg, probe_layout)
    no_bob = getattr(args, "no_bob", False)  # absent when reached from `skills` (no indexing flags)
    agents, prefer = _resolve_agents(args.agent, probe_root, existing, no_bob)
    if args.agent is None and existing is None and not no_bob:
        print(BOB_DEFAULT_NOTICE, file=sys.stderr)

    extra: dict = {}
    notes: list[str] = []
    if args.smart:
        explicit = _repo_config_keys(probe_root)
        for key, value in SMART_SETTINGS.items():
            if key in explicit:
                notes.append(f"--smart: kept {key} from your config file")
            else:
                extra[key] = value
    if args.local_only:
        extra.update({"local_only": True, "commit_context": False})
    if getattr(args, "feature_set", None):
        extra["feature_set"] = args.feature_set
        extra["_feature_set_flag"] = True
    root, cfg, layout = open_workspace(args, prefer=prefer, extra=extra)

    reinit = layout.index_path.is_file()
    incremental = reinit and not args.force
    write_config = bool(args.smart or "claude" in agents or layout.config_path.is_file()
                        or args.local_only or (args.agent is not None and layout.kind == "standard"))
    if args.dry_run or args.diff:
        outcome = generate(root, cfg, layout, agents, incremental=incremental, dry_run=True,
                           smart=args.smart, write_config=write_config)
        print(f"  dry run — nothing was written. agents: {', '.join(agents) or 'none'}; "
              f"layout: {layout.context_rel}/")
        _print_plan(outcome, diff=args.diff, dry=True)
        return 0

    _log().info("repo-ai %s — %s %s", __version__, "refreshing" if reinit else "initialising", root)
    with _lock(layout) as held:
        if not held:
            raise SystemExit("error: another repo-ai update holds the lock; try again shortly")
        outcome = generate(root, cfg, layout, agents, incremental=incremental, smart=args.smart,
                           write_config=write_config)
    outcome.notes = notes + outcome.notes
    if reinit and not args.force:
        _log().info("already initialised: refreshed incrementally (use --force to rebuild)")
    if not cfg.quiet:
        _onboarding_summary(outcome, cfg, reinit)
    return 0


def _current_agents(root, cfg, layout, args) -> tuple[str, ...]:
    from .workspace import recorded_agents
    agents = recorded_agents(root, cfg, layout)
    agents = ("bob",) if agents is None else agents
    if getattr(args, "no_bob", False):
        agents = tuple(a for a in agents if a != "bob")
    return agents


def _run_update(args: argparse.Namespace, *, incremental: bool, **kwargs) -> int:
    from .workspace import generate
    root, cfg, layout = open_workspace(args)
    if not layout.index_path.is_file():
        _log().warning("no existing index; running a full init instead")
        args.agent, args.smart, args.force = None, False, False
        args.local_only = getattr(args, "local_only", False)
        args.dry_run = getattr(args, "dry_run", False)
        args.diff = getattr(args, "diff", False)
        return cmd_init(args)
    agents = _current_agents(root, cfg, layout, args)
    if getattr(args, "dry_run", False) or getattr(args, "diff", False):
        outcome = generate(root, cfg, layout, agents, incremental=incremental, dry_run=True, **kwargs)
        print("  dry run — nothing was written.")
        _print_plan(outcome, diff=getattr(args, "diff", False), dry=True)
        return 0
    with _lock(layout) as held:
        if not held:
            raise SystemExit("error: another repo-ai update holds the lock; try again shortly")
        if not incremental:
            # under the lock only: deleting the database while another update holds the lock made
            # that update write into an unlinked file and leave an empty index behind (it then
            # read as current); a rebuild killed while waiting must change nothing
            for name in ("index.db", "index.db-wal", "index.db-shm"):
                (layout.state_dir / name).unlink(missing_ok=True)
        outcome = generate(root, cfg, layout, agents, incremental=incremental, **kwargs)
        _touch(layout.stamp_path)
    if not cfg.quiet:
        verb = "updated" if incremental else "rebuilt"
        changed = len(outcome.plan.effective())
        print(f"  {verb}: {outcome.facts.indexed_files:,} files indexed at "
              f"{outcome.facts.git_head or 'working tree'}; {changed} file(s) written")
        for rid, before, after in outcome.rule_changes[:12]:
            print(f"    rule {rid}: {before} -> {after}")
        for note in outcome.notes:
            print(f"  ! {note}")
    return 0


def _touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        pass


def cmd_update(args: argparse.Namespace) -> int:
    return _run_update(args, incremental=True)


def cmd_rebuild(args: argparse.Namespace) -> int:
    return _run_update(args, incremental=False)


def cmd_refresh(args: argparse.Namespace) -> int:
    """Hook-safe update: never waits on a lock, never raises, debounced."""
    import time
    from .hooks import spawn_refresh
    from .workspace import generate
    try:
        root, cfg, layout = open_workspace(args, extra={"quiet": True})
    except SystemExit:
        return 0
    if not layout.index_path.is_file():
        return 0
    if args.background:
        spawn_refresh(root, force=args.force)
        return 0
    if not args.force:
        try:
            if time.time() - layout.stamp_path.stat().st_mtime < cfg.refresh_debounce_seconds \
                    and not layout.dirty_path.exists() \
                    and not (layout.state_dir / ".dirty.processing").exists():  # a killed refresh's claim
                return 0
        except OSError:
            pass
    with _lock(layout, timeout=0) as held:
        if not held:
            return 0
        processing = layout.state_dir / ".dirty.processing"
        try:
            if layout.dirty_path.exists():
                os.replace(layout.dirty_path, processing)
        except OSError:
            pass
        try:
            generate(root, cfg, layout, _current_agents(root, cfg, layout, args), incremental=True)
            _touch(layout.stamp_path)
        except Exception as exc:  # leave the marker so the next Stop retries
            _log().debug("refresh failed: %s", exc)
            try:
                if processing.exists() and not layout.dirty_path.exists():
                    os.replace(processing, layout.dirty_path)
            except OSError:
                pass
            return 0
        try:
            processing.unlink()
        except OSError:
            pass
    return 0


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    from .gitinfo import changed_since, is_git_repo
    from .index import open_index
    from .logging_setup import setup_logging
    from .workspace import recorded_agents

    root, cfg, layout = open_workspace(args)
    setup_logging(cfg.verbose, quiet=args.brief or cfg.quiet or args.json)
    db = layout.index_path
    if not db.is_file():
        if args.brief:
            return 0
        if args.json:
            print(json.dumps({"initialised": False, "root": str(root)}))
        else:
            print(f"no repo-ai context in this repository. {INIT_HINT}.")
        return 1

    from .scanner import real_drift
    index = open_index(layout.state_dir)
    stats = index.stats()
    generated_at = index.get_meta("generated_at")
    indexed_head = index.get_meta("git_head")
    version = index.get_meta("tool_version")
    drift: list[str] = []
    if indexed_head and is_git_repo(root):
        prefixes = (layout.context_rel + "/", layout.state_rel + "/", ".repo-ai/", ".claude/", ".bob/")
        drift = real_drift(root, index, [p for p in changed_since(root, indexed_head)
                                         if not p.startswith(prefixes)])
    incomplete = index.get_meta("needs_reanalysis") == "1"  # an update was interrupted before it finished
    index.close()
    dirty = layout.dirty_path.exists() or incomplete
    stale = bool(drift) or dirty

    if args.brief:
        # Consumed by the Bob SessionStart hook: one line.
        parts = [f"repo-ai context: {stats['files']} files indexed at {generated_at}."]
        if drift:
            parts.append(
                f"{len(drift)} file(s) changed since then"
                + (f", including {', '.join(drift[:3])}" if drift[:3] else "")
                + ". Run `repo-ai update` for current context.")
        elif incomplete:
            from .locks import is_locked
            parts.append("An update is running; context may be incomplete until it finishes."
                         if is_locked(layout.lock_path) else
                         "The last update was interrupted before it finished. Run `repo-ai update`.")
        else:
            parts.append("Context is current.")
        parts.append("Use `repo-ai context \"<task>\"` to shortlist relevant files.")
        print(" ".join(parts))
        return 0

    agents = recorded_agents(root, cfg, layout) or ()
    capabilities = _capabilities(root, cfg, layout)
    if args.json:
        print(json.dumps({
            "capabilities": capabilities,
            "initialised": True, "root": str(root), "layout": layout.kind,
            "context_dir": layout.context_rel, "state_dir": layout.state_rel,
            "generated_at": generated_at, "tool_version": version, "indexed_head": indexed_head,
            "stats": stats, "drift": drift, "dirty": dirty, "stale": stale,
            "agents": list(agents), "learning_policy": cfg.learning_policy,
        }, indent=2))
        return 2 if stale else 0

    print(f"  repo:        {root}")
    print(f"  layout:      {layout.kind} — context {layout.context_rel}/, state {layout.state_rel}/")
    print(f"  agents:      {', '.join(agents) or 'none'}   learning: {cfg.learning_policy}")
    print(f"  generated:   {generated_at}  (repo-ai {version})")
    print(f"  indexed at:  {indexed_head or 'n/a'}")
    print(f"  contents:    {stats['files']:,} files · {stats['symbols']:,} symbols · "
          f"{stats['imports']:,} imports · {stats['routes']:,} routes · "
          f"{stats['dependencies']:,} deps · {stats['test_links']:,} test links")
    print(f"  index size:  {db.stat().st_size / 1_048_576:.1f} MB")
    print("  active:      " + ", ".join(f"{k}={v}" for k, v in capabilities.items()))
    if drift:
        print(f"  drift:       {len(drift)} file(s) changed since indexing")
        for path in drift[:10]:
            print(f"               {path}")
        if len(drift) > 10:
            print(f"               … and {len(drift) - 10} more")
        print("  -> run `repo-ai update`")
    elif dirty:
        print("  drift:       edits recorded by hooks; refresh pending (`repo-ai update`)")
    else:
        print("  drift:       none — context is current")
    return 2 if stale else 0


def _capabilities(root: Path, cfg, layout) -> dict[str, object]:
    from .episodes import load_prior
    from .registry import zone_of
    from .fsutil import marker_attrs, read_text
    skills_dir = root / ".claude" / "skills"
    generated = sum(1 for p in (skills_dir.glob("*/SKILL.md") if skills_dir.is_dir() else [])
                    if marker_attrs(read_text(p) or "").get("origin") == "generated")
    zone = zone_of(root)
    return {"signals": cfg.learning_signals, "outcome_prior": "active" if load_prior(layout) else "off",
            "flight_recorder": "on" if cfg.flight_recorder else "off",
            "skills": generated, "llm_drafting": cfg.skills_llm,
            "zone": zone or "none", "orchestration": cfg.orchestration}


# --------------------------------------------------------------------------
# context / explain
# --------------------------------------------------------------------------
def _scope_changed(root: Path, scope: str) -> list[str]:
    from .gitinfo import _run, changed_since, is_git_repo
    if not is_git_repo(root):
        return []
    if scope == "diff":
        return changed_since(root, "HEAD")
    if scope.startswith("branch"):
        base = scope.partition(":")[2] or _default_base(root)
        from .gitinfo import safe_ref
        if not safe_ref(base):
            raise SystemExit(f"error: not a valid git revision: {base!r}")
        merge_base = _run(root, ["merge-base", "--end-of-options", base, "HEAD"], timeout=20).strip()
        return changed_since(root, merge_base or base)
    return []


def _default_base(root: Path) -> str:
    from .gitinfo import _run
    ref = _run(root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], timeout=10).strip()
    if ref:
        return ref
    for candidate in ("main", "master"):
        if _run(root, ["rev-parse", "--verify", "--quiet", candidate], timeout=10).strip():
            return candidate
    return "HEAD~1"


def _retrieve(args, root, cfg, layout, index):
    from .retrieval import cached_search, scope_files
    prompt = " ".join(args.task).strip()
    if not prompt:
        raise SystemExit('error: describe the task, e.g. repo-ai context "fix the login bug"')
    scope = getattr(args, "scope", "") or ""
    try:
        scope_paths = scope_files(index, scope, _scope_changed(root, scope)) if scope else None
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc
    from .episodes import load_prior
    return cached_search(index, prompt, max_files=cfg.max_context_files,
                         include_tests=not getattr(args, "no_tests", False), scope=scope,
                         scope_paths=scope_paths, use_cache=cfg.query_cache and not args.no_cache,
                         prior=load_prior(layout))


def cmd_context(args: argparse.Namespace) -> int:
    from .logging_setup import setup_logging
    from .retrieval import render_claude, render_context, render_explain, render_json

    root, cfg, layout = open_workspace(args)
    setup_logging(cfg.verbose, quiet=True)  # stdout must stay clean
    index = require_index(layout)
    try:
        result = _retrieve(args, root, cfg, layout, index)
    finally:
        index.close()
    facts = load_facts(layout)
    quarantined = frozenset(facts.get("quarantined", []))
    hits = [h for h in result.hits if h.path not in quarantined]
    result.hits = hits

    if getattr(args, "explain", False):
        print(render_explain(result))
        return 0
    if args.format == "json":
        print(json.dumps(render_json(result.query, hits, result.confidence, result.signals), indent=2))
        return 0
    if args.format == "paths":
        for hit in hits:
            print(hit.path)
        return 0
    if args.format == "mentions":
        print(" ".join(f"@/{h.path}:{h.lines[0][0]}-{h.lines[0][1]}" if h.lines else f"@/{h.path}"
                       for h in hits))
        return 0
    commands = facts.get("commands", {})
    from .testing import TestSuite as _Suite, verification_plan
    suites = [_Suite(**{k: s.get(k, "") for k in ("name", "root", "framework", "kind")},
                     file_count=int(s.get("file_count") or 0), command=s.get("command", ""))
              for s in facts.get("test_suites", []) if isinstance(s, dict)]
    test_cmd = verification_plan(commands, suites).test_command
    if args.format == "hook":
        # Injected into an agent's context: say nothing unless it is relevant.
        if result.confidence not in {"high", "medium"} or not hits:
            return 0
        summary = f"Verify with: `{test_cmd}`" if test_cmd else ""
        print(render_context(result.query, hits, summary, min(cfg.context_budget_tokens,
                                                              cfg.hook_budget_tokens * 2)))
        return 0
    if not hits:
        print("no matching files (no content evidence for this task). "
              "try different terms, a symbol name, or `repo-ai update`.")
        return 0
    if args.agent == "claude" or args.format == "claude":
        from .hooks import _focused_test
        index = require_index(layout)
        try:
            verify = _focused_test(index, layout, result) or test_cmd
        finally:
            index.close()
        print(render_claude(result, cfg.context_budget_tokens, verify, quarantined,
                            max_chars=60_000))
        return 0
    out = render_context(result.query, hits, f"Verify with: `{test_cmd}`" if test_cmd else "",
                         cfg.context_budget_tokens)
    print(out.replace("Task class:", f"Confidence: {result.confidence}. Task class:", 1))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    args.explain = True
    args.format = "markdown"
    args.agent = None
    return cmd_context(args)


# --------------------------------------------------------------------------
# impact
# --------------------------------------------------------------------------
def cmd_impact(args: argparse.Namespace) -> int:
    from .impact import analyze_impact, render_impact
    from .logging_setup import setup_logging

    root, cfg, layout = open_workspace(args)
    setup_logging(cfg.verbose, quiet=True)
    index = require_index(layout)
    try:
        targets = list(args.targets)
        if args.changed or args.branch is not None:
            scope = "diff" if args.changed else ("branch:" + args.branch if args.branch else "branch")
            changed = _scope_changed(root, scope)
            indexed = {r["path"] for r in index.all_files()}
            targets += [p for p in changed if p in indexed]
            if not targets:
                print("no changed, indexed files." if args.format == "text" else
                      json.dumps({"targets": [], "note": "no changed, indexed files"}))
                return 0
        if not targets:
            raise SystemExit("error: give a path or symbol, or --changed")
        result = analyze_impact(index, _facts_obj(layout), targets, max_depth=args.depth, root=root)
    finally:
        index.close()
    if args.format == "json":
        print(json.dumps(result.to_json(), indent=2))
    else:
        print(render_impact(result))
    return 0 if result.targets else 1


def _scoped_paths(root: Path, raw: list[str]) -> list[str]:
    """`--paths` as repository-relative POSIX paths. A relative path is
    relative to the repository root; an absolute one must be inside it."""
    out = []
    top = root.resolve()
    for item in raw:
        for part in item.split(","):
            part = part.strip()
            if not part:
                continue
            path = Path(part)
            full = path.resolve() if path.is_absolute() else (top / path).resolve()  # relative: to the root
            try:
                out.append(full.relative_to(top).as_posix())
            except ValueError:
                raise SystemExit(f"error: --paths {part}: outside the repository") from None
    return sorted(dict.fromkeys(out))


def cmd_verify(args: argparse.Namespace) -> int:
    from .logging_setup import setup_logging
    from .verify import engine, report
    from .verify.execute import get_executor

    root, cfg, layout = open_workspace(args, extra={"quiet": True})
    setup_logging(cfg.verbose, quiet=True)
    if args.gate:
        from .verify.gate import gate
        return gate(root, layout, sys.stdin.read() if not sys.stdin.isatty() else "", mode=cfg.verify_gate_mode,
                    max_blocks=cfg.verify_gate_max_blocks)
    if not layout.index_path.is_file():
        raise SystemExit(f"error: no index at {layout.index_path}; {INIT_HINT} first")
    log = (lambda *_: None) if args.json else (lambda line: print(line, file=sys.stderr))
    from .sandbox import Cancelled, SandboxUnavailable, SandboxViolation, cleanup_problems, terminate_all
    from .verify import evidence
    from .verify.changes import ChangeError
    from .verify.isolate import IsolationError
    restore = _cancel_on_signals() if (args.run or args.record) else None
    timeout = float(args.timeout) if args.timeout is not None else 600.0
    override = args.test_command or cfg.verify_test_command or None
    source = "--test-command" if args.test_command else ".repo-ai/config.toml (verify_test_command)"
    paths = _scoped_paths(root, args.paths) if args.paths else None
    if args.deadline is not None and (not args.run or args.record or not math.isfinite(args.deadline)
                                      or not args.deadline > 0):
        raise SystemExit("error: --deadline takes a positive, finite number of seconds, with --run (not --record)")
    if paths is not None and (args.run or args.record):
        raise SystemExit("error: --paths plans part of a change and is read-only; --run and --record always "
                         "cover the whole change")
    try:
        if args.record:
            p, _ = engine.build_plan(root, layout, base=args.base, command=override, use_runtime=False,
                                     command_source=source)
            executor = get_executor(root, args.sandbox, p.runner.language, timeout_s=timeout,
                                    image=args.image or "")
            log(f"recording runtime evidence for {p.universe} test file(s) in the {executor.backend.name} "
                "sandbox, in a disposable copy of the working tree (runs the test suite)…")
            log(f"  command: {p.runner.command}  [{p.runner.source}]")
            tmap = engine.record_evidence(root, layout, executor, command=override, command_source=source,
                                          workers=args.workers, timeout_s=timeout, log=log)
            failing = tmap.baseline_failures()
            summary = {"recorded_tests": len(tmap.tests), "baseline_failures": failing,
                       "backend": tmap.backend, "commit": tmap.commit, "uncommitted": tmap.uncommitted,
                       # with uncommitted changes in place the failures are those of that tree
                       "failures_are_base": not tmap.uncommitted}
            if tmap.uncommitted:  # the failures belong to these edits, not to the base
                state = (f"; {len(failing)} failing with uncommitted changes to "
                         + ", ".join(tmap.uncommitted[:3]) + (" …" if len(tmap.uncommitted) > 3 else "")
                         + " in place (not base failures: commit or stash them and record again to measure "
                         "the base): " + ", ".join(failing[:5])) if failing else ""
            else:
                state = f"; {len(failing)} already failing: " + ", ".join(failing[:5]) if failing else ""
            print(json.dumps(summary, indent=2) if args.json else
                  f"recorded runtime evidence for {len(tmap.tests)} test file(s)" + state)
            if not args.run:
                _warn_cleanup(cleanup_problems())
                return 0
        p, change = engine.build_plan(root, layout, base=args.base, command=override,
                                      use_runtime=not args.no_runtime, command_source=source, paths=paths)
        if paths is not None:  # evidence status refers to the whole change, never to a part
            if args.json:
                print(json.dumps({**p.to_json(), "scope": {"paths": paths, "partial": True}}, indent=2))
            else:
                print(report.render_plan(p), end="")
            return 0
        if not args.run:
            status = _evidence_status(root, layout, change)
            if args.json:
                print(json.dumps({**p.to_json(), "evidence_status": status}, indent=2))
            else:
                print(report.render_plan(p, evidence_status=status), end="")
            return 0
        if p.runner.kind == "opaque" and not p.runner.command:
            raise engine.VerifyError("no test command was established, so nothing can be run; pass "
                                     "--test-command \"...\" (it is shown before anything runs)")
        executor = get_executor(root, args.sandbox, p.runner.language, timeout_s=timeout,
                                image=args.image or "")
        log(f"verifying {len(p.selected)} selected test file(s) in the {executor.backend.name} sandbox, "
            "in a disposable copy of the working tree…")
        log(f"  command: {p.runner.command}  [{p.runner.source}]")
        rec = engine.run_plan(root, layout, p, change, executor, full=args.full, workers=args.workers,
                              timeout_s=timeout, timeout_explicit=args.timeout is not None,
                              reuse=not args.rerun, deadline_s=args.deadline, log=log,
                              show_fixed=getattr(args, "show_fixed", False))
    except KeyboardInterrupt:
        terminate_all()
        from .sandbox import stopped_total
        print(f"\ncancelled: stopped {stopped_total()} running test process(es); the disposable copies were "
              "deleted and nothing was recorded", file=sys.stderr)
        _warn_cleanup(cleanup_problems())
        return 130
    except Cancelled:  # a cancellation that reached a run before it started: same outcome as Ctrl-C
        terminate_all()
        print("\ncancelled: nothing was recorded", file=sys.stderr)
        _warn_cleanup(cleanup_problems())
        return 130
    except (engine.VerifyError, SandboxUnavailable, SandboxViolation, IsolationError, ChangeError) as exc:
        # say so; never run unsandboxed or in the developer's tree
        raise SystemExit(f"error: {exc}") from exc
    finally:
        if restore:
            restore()
    problems = cleanup_problems()
    if args.json:
        doc: dict[str, object] = {"summary": report.summarize(rec), "plan": p.to_json(), "evidence": rec}
        if problems:  # never assumed: a test process may have outlived the run
            doc["sandbox_cleanup_unconfirmed"] = problems
        print(json.dumps(doc, indent=2))
    else:
        print(report.render_run(p, rec), end="")
    _warn_cleanup(problems)
    return 0 if evidence.is_passing(rec["verdict"]) else 1


def _warn_cleanup(problems: list[str]) -> None:
    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)


def _evidence_status(root: Path, layout, change) -> dict:
    """Whether the last `verify --run` covers this exact change."""
    from .verify import evidence
    rec = evidence.latest(layout.state_dir)
    if rec is None:
        return {"state": "none"}
    current = rec.get("fingerprint") == change.fingerprint and rec.get("base") == change.base
    env = evidence.environment_check(rec, root)[0] if current else "not checked"
    return {"state": "current" if current and env != "changed" else "stale", "verdict": rec.get("verdict"),
            "created": rec.get("created"), "path": rec.get("path"),
            "stale_reason": None if current and env != "changed" else "environment" if current else "change"}


def _cancel_on_signals():
    """SIGTERM and SIGHUP cancel a run like Ctrl-C does, so sandboxed test
    processes are killed and the disposable copy is deleted."""
    import signal

    def raise_interrupt(_signum, _frame):
        raise KeyboardInterrupt
    saved = {}
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                saved[sig] = signal.signal(sig, raise_interrupt)
            except (ValueError, OSError):  # not the main thread
                pass

    def restore() -> None:
        for sig, handler in saved.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
    return restore


def cmd_evidence(args: argparse.Namespace) -> int:
    from .verify import changes, evidence, report

    root, cfg, layout = open_workspace(args, extra={"quiet": True})
    rec = evidence.latest(layout.state_dir)
    if rec is None:
        print(json.dumps({"current": False, "same_behaviour": False, "stale_reason": None, "environment_check": "not checked",
                          "environment_detail": "", "evidence": None}) if args.json else
              "no verification evidence yet: run `repo-ai verify --run`")
        return 1
    try:
        now = changes.detect(root, rec.get("base", "HEAD") or "HEAD").fingerprint
        if now != rec.get("fingerprint"):  # the latest may be another session's run of another state
            found = evidence.for_fingerprint(layout.state_dir, now)
            if found is None and (rec.get("base") or "HEAD") != "HEAD":  # and against another base:
                head = changes.detect(root, "HEAD").fingerprint     # what the completion gate checks
                found = evidence.for_fingerprint(layout.state_dir, head)
                now = head if found is not None else now
            rec = found or rec
        current = now == rec.get("fingerprint")
        # what the completion gate also accepts: a later rewrite with the same syntax tree / tokens
        same = current or (bool(rec.get("semantic_fingerprint")) and changes.semantic_fingerprint(
            root, rec.get("base", "HEAD") or "HEAD") == rec["semantic_fingerprint"])
    except changes.ChangeError:
        current = same = False
    # Check version, current interpreter selection and recorded dependency paths
    # without executing the interpreter. Incomplete old records require a rerun.
    env, env_detail = evidence.environment_check(rec, root) if same else ("not checked", "")
    stale = None if current else "change"
    if env == "changed":
        current = same = False
        stale = stale or "environment"
    if args.json:
        print(json.dumps({"current": current, "same_behaviour": same, "stale_reason": stale, "environment_check": env,
                          "environment_detail": env_detail, "evidence": rec}, indent=2))
    else:
        print(report.render_evidence(rec, current=current, environment=(env, env_detail)), end="")
    return 0 if current else 2


PROVE_CLAIM_MAX = 2000


def cmd_prove(args: argparse.Namespace) -> int:
    """ProofLab: pin a claim and its scenario, plan, run (sandboxed), check
    freshness, export. Only `run` executes repository code."""
    import subprocess

    from .gitinfo import safe_ref
    from .prove import claim as cl
    from .prove import experiment, passport, render
    from .verify import engine

    root, cfg, layout = open_workspace(args, extra={"quiet": True})
    if not safe_ref(args.base):
        raise SystemExit(f"error: not a valid git revision: {args.base!r}")
    if args.timeout is not None and not 0 < args.timeout <= 86400:
        raise SystemExit("error: --timeout is a number of seconds above 0")
    tracked = cl.tracked_state(root, layout.state_dir)
    if tracked:  # a repository that ships claims could hand every clone a pin, or a path, it never made
        raise SystemExit("error: git tracks ProofLab state (" + ", ".join(tracked) + "); a repository must never "
                         "ship claims or passports: remove them from git (`git rm -r --cached`) and pin again")
    override = args.test_command or cfg.verify_test_command or None
    source = "--test-command" if args.test_command else ".repo-ai/config.toml (verify_test_command)"

    def emit(obj, text: str, code: int = 0) -> int:
        print(json.dumps(obj, indent=2, default=str) if args.json else text)
        return code

    try:
        if args.action == "pin":
            text = args.claim or ""
            if args.claim_stdin:
                text = sys.stdin.read(PROVE_CLAIM_MAX + 1)
            if args.remove:
                if not args.claim_id:
                    raise cl.ClaimError("pin --remove needs the claim id: `repo-ai prove pin ID --remove`")
                cl.remove(layout.state_dir, args.claim_id)
                return emit({"removed": args.claim_id}, f"unpinned {args.claim_id} and forgot its passports")
            if not args.scenario:
                raise cl.ClaimError("pin needs --scenario PATH (the acceptance test file)")
            if not layout.index_path.is_file():
                raise cl.ClaimError(f"no index yet: {INIT_HINT}, commit, then pin")
            runner = engine.establish_runner(root, layout, override, override_source=source)
            if runner.kind not in experiment.SUPPORTED_RUNNERS:
                raise cl.ClaimError(f"no unittest, pytest or node --test command was established "
                                    f"({runner.command or 'none'}); pass --test-command \"...\" (it is pinned too)")
            rec = cl.pin(root, layout.state_dir, text=text, scenario=args.scenario, revision=args.scenario_from or "",
                         external=args.scenario_file or "", support=args.support, targets=args.target,
                         expect_failure=args.expect_failure or "", supersedes=args.supersedes,
                         claim_id=args.claim_id or "", redact=args.redact_claim, replace=args.replace,
                         runner=experiment.runner_record(runner), subject=args.subject)
            who = ("an agent shell (recorded: the passport will say the oracle may not be independent)"
                   if rec["pinned_by"]["agent_shell"] else "a terminal")
            return emit(rec, f"pinned claim {rec['id']}: scenario {rec['scenario']['path']} sha256 "
                             f"{rec['scenario']['sha256'][:16]} ({rec['scenario']['provenance']['kind']}), from {who}\n"
                             f"next: `repo-ai prove plan {rec['id']}` (read-only), then `repo-ai prove run {rec['id']}`")
        if args.action == "status" and not args.claim_id and len(cl.all_ids(layout.state_dir)) > 1:
            return _prove_list(args, root, layout, _prove_env_key(root, layout, override, source, args))
        record = cl.resolve(layout.state_dir, args.claim_id)
        cid = record["id"]
        pinned_runner = record.get("runner") or {}
        if not args.test_command and pinned_runner.get("source") == "--test-command" and pinned_runner.get("command"):
            # the pinned command is part of the claim: no need to repeat it on every call
            override, source = pinned_runner["command"], "--test-command"
        def env_now() -> str:
            """verify's environment key now ("" when it cannot be computed): part of freshness."""
            from .sandbox import SandboxUnavailable
            from .verify.execute import get_executor
            try:
                run = engine.establish_runner(root, layout, override, override_source=source)
                ex = get_executor(root, args.sandbox, run.language, image=args.image or "")
                return experiment.env_key_for(root, ex, run)
            except (SandboxUnavailable, OSError, ValueError):
                return ""
        if args.action == "status":
            st = passport.status(root, layout.state_dir, cid, env_now())
            pp = st["passport"]
            code = {"none": 1, "stale": 2, "unknown": 2}.get(st["state"], 0 if pp and pp["verdict"]["supported"] else 3)
            view = passport.export_view(pp, st) if pp else None
            summary = {"claim": cid, "state": st["state"], "reasons": st["reasons"],
                       "verdict": view["verdict"] if view else None,
                       "experimental": view["experimental"] if view else passport.EXPERIMENTAL,
                       "supported": bool(pp and pp["verdict"]["supported"] and st["state"] == "fresh"),
                       "passport": pp["path"] if pp else None, "digest": pp["digest"] if pp else None}
            text = (f"{cid}: no passport yet (`repo-ai prove run {cid}`)" if pp is None else
                    (f"{cid}: passport is fresh: {pp['verdict']['headline']}" if st["state"] == "fresh" else
                     f"{cid}: STALE: the newest passport no longer describes this claim and tree (it said: "
                     f"{pp['verdict']['state']}); run `repo-ai prove run {cid} --base {pp['baseline']['revision']}`")
                    + "".join(f"\n  - {experiment.clean(r, 300)}" for r in st["reasons"])
                    + "\n" + passport.experimental_notes()[0] + " Known open false proof(s): "
                    + ", ".join(k["id"] for k in passport.EXPERIMENTAL["known_false_proofs"]) + ".")
            return emit(summary, text, code)
        if args.action == "report":
            st = passport.status(root, layout.state_dir, cid, env_now())
            pp = st["passport"]
            if pp is None:
                raise cl.ClaimError(f"no passport for {cid} yet: `repo-ai prove run {cid}`")
            # every format shows the same view: its freshness, and no support unless fresh (without the record's
            # local path: a report is meant to leave this machine)
            view = passport.export_view(pp, st)
            if args.format == "json":
                body = json.dumps(view, indent=1, sort_keys=True) + "\n"
            elif args.format == "in-toto":
                body = json.dumps(render.in_toto(view), indent=1, sort_keys=True) + "\n"
            else:
                body = render.markdown(view, st)
            if args.publish_pr is not None:
                if args.format != "md":
                    raise cl.ClaimError("--publish-pr posts the Markdown passport only (drop --format)")
                return _publish_pr(root, args.publish_pr, body, args.public_ok, st["state"])
            if args.out:
                out_path = Path(args.out)
                _write_report(root, out_path, body)
                print(f"wrote {args.out} ({st['state']}; {view['verdict']['state']})", file=sys.stderr)
                try:
                    rel = out_path.resolve().relative_to(root.resolve()).as_posix()
                except ValueError:
                    rel = ""
                if rel and not rel.startswith((".repo-ai/", ".git/")) and subprocess.run(
                        ["git", "check-ignore", "-q", "--", rel], cwd=root, check=False,
                        stdin=subprocess.DEVNULL).returncode != 0:
                    print(f"note: {rel} is now part of the working tree, so the passport no longer describes it "
                          "(stale); write reports under .repo-ai/ or outside the repository", file=sys.stderr)
            else:
                sys.stdout.write(body)
            return 0 if st["state"] == "fresh" else 2
        runner = engine.establish_runner(root, layout, override, override_source=source)
        if args.action == "plan":
            return _prove_plan(args, root, layout, record, runner, override, source)
        return _prove_run(args, root, layout, record, runner, override, source)
    except cl.ClaimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except experiment.ProveError as exc:
        raise SystemExit(f"error: {exc}") from exc


def _publish_pr(root: Path, number: int, body: str, public_ok: bool, freshness: str) -> int:
    """Post the Markdown passport as a comment on a GitHub pull request, with
    the user's own `gh` (opt-in: only when asked). The passport carries no
    source code; failure messages in it are cleaned and bounded. A public
    repository needs --public-ok, and a passport that is not fresh is not
    posted."""
    import shutil
    import subprocess
    import tempfile
    gh = shutil.which("gh")
    if gh is None:
        raise SystemExit("error: --publish-pr needs the GitHub CLI (`gh`) on PATH; or write the report with --out "
                         "and post it yourself")
    if freshness != "fresh":
        raise SystemExit(f"error: the passport is {freshness}; run `repo-ai prove run` again before publishing it")
    vis = subprocess.run([gh, "repo", "view", "--json", "visibility", "--jq", ".visibility"], cwd=root,
                         capture_output=True, text=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    if vis.returncode != 0:
        raise SystemExit("error: `gh repo view` failed; nothing was posted: " + vis.stderr.strip()[:200])
    if vis.stdout.strip().upper() != "PRIVATE" and not public_ok:
        raise SystemExit(f"error: the repository is {vis.stdout.strip().lower() or 'not private'}: the passport "
                         "(test ids and failure messages) would be public; pass --public-ok to post it anyway")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        tmp = fh.name
    try:
        res = subprocess.run([gh, "pr", "comment", str(number), "--body-file", tmp], cwd=root, capture_output=True,
                             text=True, timeout=120, check=False, stdin=subprocess.DEVNULL)
    finally:
        os.unlink(tmp)
    if res.returncode != 0:
        raise SystemExit("error: `gh pr comment` failed: " + res.stderr.strip()[:300])
    print(f"posted the passport on pull request #{number}: {res.stdout.strip()[:200]}", file=sys.stderr)
    return 0


def _write_report(root: Path, out: Path, body: str) -> None:
    """Never through a link: a repository could commit `.repo-ai/proof.md` as
    a symlink to a file of the user's. A new file, then an atomic rename,
    which replaces a link rather than following it."""
    import tempfile
    folder = out.absolute().parent
    try:
        rel = folder.relative_to(root.resolve())
    except ValueError:
        try:
            rel = folder.relative_to(root.absolute())
        except ValueError:
            rel = None
    if rel is not None:
        cur = root.absolute()
        for part in rel.parts:
            cur = cur / part
            if cur.is_symlink():
                raise SystemExit(f"error: {out}: {cur} is a link; write the report somewhere else")
    if out.is_symlink() or (out.exists() and not out.is_file()):
        raise SystemExit(f"error: {out} is not a regular file; write the report somewhere else")
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".proof.", dir=str(folder))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, out)


def _prove_env_key(root, layout, override, source, args) -> str:
    """verify's environment key now ("" when it cannot be computed): part of freshness."""
    from .prove import experiment
    from .sandbox import SandboxUnavailable
    from .verify import engine
    from .verify.execute import get_executor
    try:
        run = engine.establish_runner(root, layout, override, override_source=source)
        ex = get_executor(root, args.sandbox, run.language, image=args.image or "")
        return experiment.env_key_for(root, ex, run)
    except (SandboxUnavailable, OSError, ValueError):
        return ""


def _prove_list(args, root, layout, env_key: str = "") -> int:
    """Every pinned claim and the state of its newest passport."""
    from .prove import claim as cl
    from .prove import passport
    rows = []
    for cid in cl.all_ids(layout.state_dir):
        try:
            st = passport.status(root, layout.state_dir, cid, env_key)
        except cl.ClaimError as exc:
            rows.append({"claim": cid, "state": "unreadable", "verdict": None, "why": str(exc)})
            continue
        pp = st["passport"]
        rows.append({"claim": cid, "state": st["state"],
                     "verdict": passport.export_view(pp, st)["verdict"]["state"] if pp else None,
                     "experimental": "not certified; open false proof(s): "
                                     + ", ".join(k["id"] for k in passport.EXPERIMENTAL["known_false_proofs"])})
    if args.json:
        print(json.dumps({"claims": rows, "experimental": passport.EXPERIMENTAL}, indent=2))
    else:
        print("\n".join(f"{r['claim']}: {r['state']}" + (f" ({r['verdict']})" if r.get("verdict") else "")
                        for r in rows))
        print("name one: `repo-ai prove status ID`; unpin: `repo-ai prove pin ID --remove`")
    return 0


def _prove_plan(args, root, layout, record, runner, override, source) -> int:
    """What `prove run` would do, and whether it can be a comparison at all.
    Reads files and git objects; runs nothing."""
    from .prove import experiment
    from .verify import engine

    pre = experiment.preflight(root, layout, record, args.base, runner)
    if not layout.index_path.is_file():
        pre["problems"].insert(0, {"state": "environment-unavailable", "why": f"no index yet: {INIT_HINT}"})
    p, _change = engine.build_plan(root, layout, base=args.base, command=override, command_source=source)
    pj = p.to_json()
    out = {"schema": "repo-ai.proof-plan/1", "claim": record["id"], "ready": not pre["problems"],
           "problems": pre["problems"], "base": pre["change"].base_commit, "scenario": pre["scenario"],
           "support": pre["support"], "runner": pre["runner"], "command": pre["command"], "oracle": pre["oracle"],
           "edited_tests": pre["edited_tests"], "subject": pre["subject"],
           "regression_plan": {"confidence": pj["confidence"], "full_suite_required": pj["full_suite_required"],
                               "selected": len(p.selected), "test_files_total": pj["test_files_total"]},
           "runs": ["the scenario at the base and at the candidate, --repeat times each (default 2)",
                    "the base's own version of each edited test file, at the base and at the candidate",
                    "verify --run on the change (unless --no-regressions)"]}
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["ready"] else 2
    from .prove.experiment import clean
    scen, oracle = pre["scenario"], pre["oracle"]
    lines = [f"proof plan for {record['id']}" + ("" if out["ready"] else ": NOT READY, nothing would run"),
             *[f"  ! {x['state']}: {clean(x['why'], 400)}" for x in pre["problems"]],
             f"  base         {pre['change'].base_commit[:12]} ({args.base})",
             f"  scenario     {clean(scen['path'])}  sha256 {scen['sha256'][:16]}  (in the candidate tree: "
             f"{scen['in_candidate_tree']}; at the base: {scen['in_base_tree']})",
             f"  command      {pre['command'] or '-'}  [{runner.source}]",
             f"  oracle       {oracle['checked']} input(s) "
             + ("identical at both revisions" if oracle["identical"] else
                "DIFFER: " + ", ".join(clean(d) for d in oracle["differing"][:5])),
             "  subject      " + (", ".join(clean(p) for p in pre["subject"]["files"][:5]) or "none")
             + (" (declared)" if pre["subject"]["declared"] else " (inferred: the changed files the scenario imports)")
             + ("; left out of the scenario: " + ", ".join(clean(p) for p in pre["subject"]["left_out"][:5])
                if pre["subject"]["left_out"] else ""),
             "  edited tests " + (", ".join(clean(e["path"]) for e in pre["edited_tests"][:5]) or "none"),
             f"  regressions  verify selects {len(p.selected)} of {pj['test_files_total']} test file(s), confidence "
             f"{p.confidence}" + ("; the full suite is required" if p.full_suite_required else ""),
             *[f"  note         {n}" for n in scen["notes"]],
             "nothing was run; `repo-ai prove run` runs these in the sandbox (executes repository code)"]
    print("\n".join(lines))
    return 0 if out["ready"] else 2


def _prove_run(args, root, layout, record, runner, override, source) -> int:
    from .prove import experiment, render
    from .sandbox import Cancelled, SandboxUnavailable, SandboxViolation, terminate_all
    from .verify import engine
    from .verify.changes import ChangeError
    from .verify.execute import get_executor
    from .verify.isolate import IsolationError

    if not 1 <= args.repeat <= 10:
        raise SystemExit("error: --repeat is 1 to 10")
    if not layout.index_path.is_file():
        raise SystemExit(f"error: no index at {layout.index_path}; {INIT_HINT} first")
    log = (lambda *_: None) if args.json else (lambda line: print(line, file=sys.stderr))
    timeout = float(args.timeout) if args.timeout is not None else 300.0
    restore = _cancel_on_signals()
    try:
        executor, why = None, ""
        try:
            executor = get_executor(root, args.sandbox, runner.language, timeout_s=timeout, image=args.image or "")
        except SandboxUnavailable as exc:
            why = str(exc)

        def regression_run() -> dict:
            p, change = engine.build_plan(root, layout, base=args.base, command=override, command_source=source)
            assert executor is not None
            return engine.run_plan(root, layout, p, change, executor, workers=args.workers,
                                   timeout_s=timeout if args.timeout is not None else 600.0,
                                   timeout_explicit=args.timeout is not None, reuse=not args.rerun, log=log)
        log(f"proving {record['id']}: the pinned scenario at the base and at the candidate, then the regression "
            "check (runs repository code in the sandbox, in disposable copies)…")
        pp = experiment.run(root, layout, record, base=args.base, runner=runner, executor=executor,
                            repeat=args.repeat, timeout_s=timeout, workers=args.workers,
                            regressions=not args.no_regressions, regression_run=regression_run,
                            sandbox_error=why, keep_going=args.keep_going,
                            suite_timeout_s=timeout if args.timeout is not None else 600.0, log=log)
    except KeyboardInterrupt:
        terminate_all()
        print("\ncancelled: the test processes were stopped, the disposable copies deleted, and no passport was "
              "recorded", file=sys.stderr)
        return 130
    except Cancelled:
        terminate_all()
        print("\ncancelled: no passport was recorded", file=sys.stderr)
        return 130
    except (engine.VerifyError, SandboxViolation, IsolationError, ChangeError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    finally:
        restore()
    if args.json:
        print(json.dumps(pp, indent=2, default=str))
    else:
        print(render.text(pp), end="")
    return 0 if pp["verdict"]["supported"] else 1


def cmd_privacy(args: argparse.Namespace) -> int:
    from .privacy import audit, render

    root, cfg, layout = open_workspace(args)
    stores = audit(root, cfg, layout)
    if args.json:
        print(json.dumps([s.to_json() for s in stores], indent=2))
    else:
        print(render(stores))
    return 1 if any(s.problems for s in stores) else 0


def cmd_packet(args: argparse.Namespace) -> int:
    from .episodes import load_prior
    from .learning import Ledger
    from .packet import build_packet, render_claude, render_markdown

    root, cfg, layout = open_workspace(args)
    index = require_index(layout)
    task = " ".join(args.task)
    try:
        rules = Ledger.load(layout).active()
    except Exception:  # noqa: BLE001 - rules are optional context
        rules = []
    try:
        changed = _scope_changed(root, "diff")
    except Exception:  # noqa: BLE001 - not a git repo
        changed = []
    try:
        packet = build_packet(root, index, load_facts(layout), task, facts_obj=_facts_obj(layout),
                              rules=rules, changed=changed, max_files=args.max_files,
                              budget_tokens=args.budget_tokens, prior=load_prior(layout))
    finally:
        index.close()
    if args.format == "json":
        print(json.dumps(packet.to_json(), indent=2))
    elif args.format == "claude":
        sys.stdout.write(render_claude(packet))
    else:
        sys.stdout.write(render_markdown(packet))
        print(f"(~{packet.tokens_est} tokens, estimate; cap {args.budget_tokens})")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from .review import build, render

    root, cfg, layout = open_workspace(args)
    index = require_index(layout)
    base = None
    if args.branch is not None:
        base = args.branch or _default_base(root)
        from .gitinfo import safe_ref
        if not safe_ref(base):
            raise SystemExit(f"error: not a valid git revision: {base!r}")
        base = (subprocess_out(root, ["git", "merge-base", "--end-of-options", "HEAD", base])
                or base).strip()
    try:
        passport = build(root, index, _facts_obj(layout), layout, base)
    finally:
        index.close()
    if args.format == "json":
        print(json.dumps(passport.to_json(), indent=2))
    else:
        sys.stdout.write(render(passport))
    return 0


def subprocess_out(root: Path, argv: list[str]) -> str:
    import subprocess
    try:
        return subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=30,
                              check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def cmd_budget(args: argparse.Namespace) -> int:
    from .budget import measure, render

    root, cfg, layout = open_workspace(args)
    data = measure(root, cfg, layout)
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 1 if data["problems"] and args.check else 0


def cmd_capabilities(args: argparse.Namespace) -> int:
    if getattr(args, "action", None):
        return _capability_registry(args)
    return _capability_coverage(args)


TASK_STDIN_MAX = 8000


def _capability_registry(args: argparse.Namespace) -> int:
    """The capability registry: show, recommend, prepare, approve, run, revoke.
    Only `approve` and `run` write, and only repo-ai's own files."""
    from . import capabilities as caps
    from .gitinfo import safe_ref

    root, cfg, layout = open_workspace(args)
    if not safe_ref(args.base):
        raise SystemExit(f"error: not a valid git revision: {args.base!r}")
    manifest = caps.load_manifest()
    records = caps.by_id(manifest)
    unknown = [i for i in args.ids if i not in records] if args.action != "select" else []
    if unknown:
        raise SystemExit(f"error: unknown capability {', '.join(unknown)} (see `repo-ai capabilities list`)")
    states = caps.all_states(root, manifest, indexed=caps.index_ready(root, layout.index_path),
                             state_dir=caps.runs_dir(root))

    def emit(obj, text: str, code: int = 0) -> int:
        print(json.dumps(obj, indent=2, default=str) if args.json else text)
        return code

    files = [f.strip() for f in args.files.split(",") if f.strip()] if args.files is not None else None
    if sum(bool(x) for x in (args.task, args.task_stdin, args.task_file)) > 1:
        print("error: use one of --task, --task-stdin, --task-file", file=sys.stderr)
        return 2
    raw = args.task.encode("utf-8", "surrogateescape") if args.task else b""
    if args.task_stdin:
        raw = sys.stdin.buffer.read(TASK_STDIN_MAX + 1)
    elif args.task_file:
        try:
            with open(args.task_file, "rb") as fh:
                raw = fh.read(TASK_STDIN_MAX + 1)
        except OSError as exc:
            print(f"error: cannot read --task-file: {exc.strerror}", file=sys.stderr)
            return 2
    if len(raw) > TASK_STDIN_MAX:
        print(f"error: the task is longer than {TASK_STDIN_MAX} bytes", file=sys.stderr)
        return 2
    try:
        args.task = raw.decode("utf-8")
    except UnicodeDecodeError:
        print("error: the task is not valid UTF-8", file=sys.stderr)
        return 2
    try:
        if args.action == "list":
            return emit({"schema": caps.SCHEMA_RECORD, "capabilities": [
                {**c, "lifecycle": states[c["id"]]} for c in manifest["capabilities"]]},
                caps.render_list(manifest, states))
        if args.action == "show":
            if not args.ids:
                raise SystemExit("error: repo-ai capabilities show <id>")
            out = [{"schema": caps.SCHEMA_RECORD, **records[i], "lifecycle": states[i]} for i in args.ids]
            return emit(out if len(out) > 1 else out[0], "\n\n".join(json.dumps(o, indent=2) for o in out))
        if args.action == "recommend":
            if not args.task.strip():
                raise SystemExit('error: repo-ai capabilities recommend --task "what you are working on"')
            changed = files if files is not None else ([] if args.no_changes else caps.changed_files(root, args.base))
            deny = [d.strip() for d in (args.deny or "").split(",") if d.strip()]
            try:
                rec = caps.recommend(args.task, caps.profile(root, load_facts(layout)), changed, manifest, states,
                                     deny=deny)
            except ValueError as exc:  # an explicit constraint that cannot be read is never ignored
                print(f"error: {exc}", file=sys.stderr)
                return 2
            return emit(rec, caps.render_recommendation(rec))
        if args.action == "prepare":
            if len(args.ids) != 1:
                raise SystemExit("error: repo-ai capabilities prepare <id>")
            prep = caps.prepare(root, args.ids[0], args.executable)
            return emit(prep, f"{prep['capability']}: {prep['path']}\n  sha256 {prep['sha256']}\n"
                              f"  runs: {' '.join(prep['argv'])}\n  {prep['note']}\n"
                              f"  to approve, run this yourself in a terminal:\n    {prep['approve']}")
        if args.action == "approve":
            if len(args.ids) != 1 or not args.sha256:
                raise SystemExit("error: repo-ai capabilities approve <id> --sha256 <prefix from prepare>")
            done = caps.approve(root, args.ids[0], args.sha256, args.executable, interactive=sys.stdin.isatty())
            a = done["approved"]
            return emit(done, f"approved {done['capability']}: {a['path']} ({a['version']}, sha256 "
                              f"{a['sha256'][:16]}). Undo: repo-ai capabilities revoke {done['capability']}")
        if args.action == "revoke":
            if not args.ids and not args.all:
                raise SystemExit("error: repo-ai capabilities revoke <id> | --all")
            gone = caps.revoke(root, None if args.all else args.ids)
            return emit({"revoked": gone}, "revoked: " + (", ".join(gone) or "nothing was approved"))
        if args.action in ("candidates", "select"):
            return _capability_menu(args, root, layout, caps, manifest, states, files)
        if args.action == "evidence":
            ev = caps.evidence(root, caps.runs_dir(root), *(args.ids[:1] or []), base=args.base, files=files)
            text = f"{ev['capability']}: {ev['status']}"
            if ev["status"] == "fresh":
                c = ev["result"].get("counts") or {}
                text += (f" ({c.get('new', 0)} finding(s) on added lines, {c.get('pre_existing', 0)} pre-existing; "
                         "informational, never a verdict)")
            else:
                text += f": {ev.get('reason', '')}"
            return emit(ev, text, 0 if ev["status"] == "fresh" else caps.EXIT_NOT_AVAILABLE)
        if args.action == "run":
            if len(args.ids) != 1:
                raise SystemExit("error: repo-ai capabilities run <id>")
            result = caps.run(root, caps.runs_dir(root), args.ids[0], base=args.base, task=args.task, files=files,
                              manifest=manifest)
            code = 0 if result["status"] in ("ran", "nothing-to-scan") else caps.EXIT_TOOL_ERROR
            return emit(result, _render_capability_result(result), code)
    except caps.CapabilityError as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": exc.code}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return exc.code
    return 2


def _capability_menu(args: argparse.Namespace, root: Path, layout, caps, manifest: dict, states: dict,
                     files: list[str] | None) -> int:
    """`candidates`: the trust-gated menu an agent may choose from. `select`: validate one choice
    against freshly recomputed gates. Neither runs, installs or approves anything."""
    import hashlib

    from . import __version__, capdiscovery, capselect
    from .gitinfo import _run as git

    if not args.task.strip():
        raise SystemExit(f"error: repo-ai capabilities {args.action} needs --task or --task-stdin")
    if args.action == "select" and (len(args.ids) != 1 or not args.digest):
        raise SystemExit("error: repo-ai capabilities select <id|none> --digest <from candidates> --task-stdin")
    task = " ".join(args.task.split())
    deny = [d.strip() for d in (args.deny or "").split(",") if d.strip()]
    commit = git(root, ["rev-parse", "--verify", "--quiet", args.base + "^{commit}"]).strip()
    if args.base != "HEAD" and not commit:
        print(f"error: {args.base!r} is not a commit here", file=sys.stderr)
        return 2
    changed = files if files is not None else ([] if args.no_changes else caps.changed_files(root, args.base))
    disc = capdiscovery.discover(task, caps.profile(root, load_facts(layout)), changed, manifest)
    inputs = {"task_sha256": hashlib.sha256(task.encode()).hexdigest()[:16], "base": args.base,
              "commit": commit,
              "changed": sorted(changed), "indexed": caps.index_ready(root, layout.index_path), "version": __version__}
    try:
        if args.action == "candidates":
            menu = capselect.candidates(disc, manifest, states, deny=deny, digest_inputs=inputs, all_=args.all)
            if args.json:
                print(capselect.encode(menu))
            else:
                print(capselect.render_text(menu))
            return 0
        out, code = capselect.select(args.ids[0], args.digest, disc, manifest, states, deny=deny,
                                     digest_inputs=inputs, all_=args.all, log_dir=caps.runs_dir(root))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(capselect.encode(out) if args.json else capselect.render_text(out))
    return code


def _render_capability_result(result: dict) -> str:
    head = f"{result['capability']}: {result['status']} in {result['duration_s']} s"
    if result["status"] == "error":
        return head + f"\n  {result.get('error', '')}\n  the scan failed; this is not a clean result"
    if result["status"] == "nothing-to-scan":
        return head + f"\n  {result['note']}"
    if "findings" not in result:
        return head + f" (`{' '.join(result.get('command', []))}`, output sha256 {result.get('output_sha256', '')[:16]})"
    c = result["counts"]
    lines = [head + f": {c['new']} finding(s) on added lines, {c['pre_existing']} pre-existing, "
             f"{len(result['files'])} file(s) scanned (SARIF {result.get('sarif', '')})"]
    for f in result["findings"][:15]:
        lines.append(f"  [{f['severity']}] {f['rule']} {f['path']}:{f['line']} {f['title']}")
    lines.append("  " + result.get("note", ""))
    return "\n".join(lines)


def _capability_coverage(args: argparse.Namespace) -> int:
    """Capability coverage map: gaps -> covering skills/agents -> outcomes."""
    from . import optimize, recommend
    from .episodes import load_all, skill_outcomes
    from .portfolio import load_lock

    root, cfg, layout = open_workspace(args)
    index = require_index(layout)
    try:
        profile = _profile(root, layout, index).to_json()
    finally:
        index.close()
    eps = load_all(layout)
    # what a skill claims to do is its description (what Claude matches on)
    texts = {n: optimize._front_matter(t).get("description", "").lower()
             for n, t in _skill_texts(root).items()}
    lock = load_lock(root)
    cov = recommend.coverage_map(profile, texts, lock, skill_outcomes(eps))
    agents_dir = root / ".claude" / "agents"
    stack = {k: profile.get(k) for k in ("languages", "frameworks", "test_frameworks", "ci", "databases")}
    data = {"stack": stack, "skills": optimize.installed_skills(root),
            "agents": sorted(p.stem for p in agents_dir.glob("*.md")) if agents_dir.is_dir() else [],
            "hooks": (root / ".claude" / "hooks" / "repo-ai.sh").is_file(), **cov}
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    by_origin: dict[str, list[str]] = {}
    for s in data["skills"]:
        by_origin.setdefault(s["origin"], []).append(s["name"])
    lines = [f"capabilities of {root.name}: " + "; ".join(
                 f"{k.replace('_', ' ')} {', '.join(v)}" for k, v in stack.items() if v),
             "  skills: " + "; ".join(f"{o} {len(n)}" for o, n in sorted(by_origin.items())) if by_origin
             else "  skills: none installed",
             f"  subagents: {', '.join(data['agents']) or 'none'}; repo-ai hooks: "
             f"{'on' if data['hooks'] else 'off'}", "  coverage:"]
    for row in data["capabilities"]:
        covered = ", ".join(["/" + s for s in row["skills"]] + row["covered_by_native"]) or "nothing"
        lines.append(f"    [{row['status']:7s}] {row['title']} (strength {row['strength']}): {covered}")
        lines.append(f"              evidence: {'; '.join(row['evidence'][:2])}")
    if not data["capabilities"]:
        lines.append("    no evidence-backed capability gaps: no additional skills are necessary")
    for name, status in sorted(data["third_party_evidence"].items()):
        lines.append(f"  third-party /{name}: benefit {status}")
    for a, b in data["redundant_pairs"]:
        lines.append(f"  possibly redundant: /{a} and /{b}")
    print("\n".join(lines))
    return 0


def cmd_performance(args: argparse.Namespace) -> int:
    from . import optimize
    from .episodes import load_all

    root, cfg, layout = open_workspace(args)
    data = optimize.performance(root, cfg, layout, load_all(layout))
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0
    hook, sl, ses = data["prompt_hook"], data["shortlist"], data["sessions"]
    lines = [f"repo-ai performance in {root.name} (local records only; estimates are marked)"]
    if hook["status"] == "measured":
        lines.append(f"  prompt hook: {hook['prompts']} prompts, injected on {hook['injection_rate']:.0%}, "
                     f"~{hook['tokens_mean']} tokens (estimate), latency p50 {hook['latency_ms_p50']} ms "
                     f"p95 {hook['latency_ms_p95']} ms")
    else:
        lines.append(f"  prompt hook: {hook['status']}")
    if sl["prompts_injected"]:
        lines.append(f"  shortlist: an injected file was edited after {sl['hit_rate']:.0%} of "
                     f"{sl['prompts_injected']} prompts; precision {sl['precision']}")
    else:
        lines.append("  shortlist: no injected prompts followed by edits recorded")
    lines.append(f"  sessions: {ses['status']}" if not ses.get("sessions") else
                 f"  sessions: {ses['sessions']} — " + ", ".join(f"{k} {v}" for k, v in ses["by_status"].items()))
    prior = data["outcome_prior"]
    lines.append(f"  outcome prior (shadow): {prior['prompts']} prompts, MRR {prior['mrr_recorded']} → "
                 f"{prior['mrr_with_prior']}" + ("" if prior["enough_evidence"] else " (insufficient evidence)"))
    if isinstance(data["experiments"], list):
        for e in data["experiments"]:
            arms = ", ".join(f"{a} {v['success_rate']} (n={v['n']})" for a, v in e["arms"].items())
            lines.append(f"  experiment {e['id']} [{e['kind']}]: {arms or 'no runs'}")
    else:
        lines.append("  experiments: none recorded")
    lines.append(f"  task success: {data['task_success']}")
    if data["tuning"]:
        lines.append(f"  governor tuning in effect: {data['tuning']}")
    print("\n".join(lines))
    return 0


def cmd_optimize(args: argparse.Namespace) -> int:
    from . import optimize
    from .episodes import load_all

    root, cfg, layout = open_workspace(args)
    if args.revert is not None:
        try:
            out = optimize.revert(layout, args.revert or None)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        print(json.dumps(out, indent=2) if args.json else
              "\n".join(f"reverted {e['id']}: {e['key']} back from {e['to']}" for e in out)
              or "nothing to revert")
        return 0
    plan = optimize.proposals(root, cfg, layout, load_all(layout))
    plan["proposals"] = [p.to_json() for p in plan["proposals"]]
    if args.apply:
        try:
            applied = optimize.apply(layout, cfg, plan, args.ids or None)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        print(json.dumps(applied, indent=2) if args.json else
              "\n".join(f"applied {e.get('id')}: " + (f"{e['key']} {e['from']} → {e['to']}" if "key" in e
                                                        else f"reverted {e['reverted']}") for e in applied)
              or "nothing the governor may apply (see `repo-ai optimize`)")
        return 0
    if args.json:
        print(json.dumps(plan, indent=2, default=str))
        return 0
    gov = plan["governor"]
    lines = [f"repo-ai optimize (plan only; nothing changed) — {len(plan['proposals'])} proposal(s)",
             f"  context-budget governor: {gov['status']}"]
    for p in plan["proposals"]:
        mark = "auto" if p["governor"]["auto_apply"] else "human"
        lines += [f"  [{mark}] {p['title']}",
                  f"      hypothesis: {p['hypothesis']}",
                  f"      evidence: {'; '.join(p['evidence'])}",
                  f"      confirm with: {p['experiment']}  (metric: {p['metric']})",
                  f"      risk: {p['risk']}; governor: {'; '.join(p['governor']['reasons'])}"]
    for j in plan["journal"]:
        if j.get("active"):
            obs = j.get("observed") or {}
            lines.append(f"  active change {j['id']}: {j['key']} {j['from']} → {j['to']} "
                         f"(hit rate before {obs.get('before')}, after {obs.get('after')}, "
                         f"n={obs.get('after_n')})")
    if any(p["governor"]["auto_apply"] for p in plan["proposals"]):
        lines.append("  apply the [auto] ones: repo-ai optimize --apply   (journaled; --revert undoes)")
    print("\n".join(lines))
    return 0


def cmd_friction(args: argparse.Namespace) -> int:
    _root, cfg, layout = open_workspace(args)
    return _print_friction(cfg, layout, args.json)


def _print_friction(cfg, layout, as_json: bool) -> int:
    from . import episodes
    items = episodes.friction(episodes.load_all(layout))
    if as_json:
        print(json.dumps([f.to_json() for f in items], indent=2))
        return 0
    if not items:
        print("friction radar: nothing repeated enough to report"
              + ("" if episodes.enabled(cfg) else
                 " (outcome recording is off: learning_signals = \"outcomes\" enables it)"))
        return 0
    print("friction radar (repeated, evidence-backed):")
    for f in items:
        print(f"  - [{f.kind}] {f.summary}\n      evidence: {f.evidence}\n      try: {f.suggestion}")
    return 0


def cmd_quickstart(args: argparse.Namespace) -> int:
    import shutil
    from .gitinfo import is_git_repo
    from .paths import detect_kind

    root = resolve_root(args.path)
    lines = [f"repo-ai {__version__} quickstart for {root}"]
    git = is_git_repo(root)
    initialized = bool(detect_kind(root))
    claude = shutil.which("claude")
    on_path = shutil.which("repo-ai")
    lines.append(f"  git repository: {'yes' if git else 'no (repo-ai works best in one)'}")
    lines.append(f"  repo-ai on PATH: {on_path or 'NO: hooks call `repo-ai` by name; install with pipx'}")
    lines.append(f"  claude CLI: {claude or 'not found (install Claude Code)'}")
    lines.append(f"  initialized here: {'yes' if initialized else 'no'}")
    lines.append("\n  next:")
    if not initialized:
        lines += ["    repo-ai init --agent claude --dry-run --diff   # see exactly what changes",
                  "    repo-ai init --agent claude --smart            # set up (re-runnable)"]
    lines += ["    claude                                         # restart running sessions",
              "    repo-ai doctor --agent claude                  # verify hooks, skills, freshness",
              '    repo-ai packet "<your task>"                   # task briefing',
              "    repo-ai impact --changed                       # blast radius of your diff",
              "    repo-ai verify                                 # which tests can show it broke (read-only)",
              "    repo-ai verify --run                           # run them, sandboxed (executes repo code)",
              "    repo-ai review --changed                       # pre-PR change passport",
              "    repo-ai learn status                           # what repo-ai learned and why",
              "    repo-ai privacy audit                          # what is stored where",
              "    repo-ai uninstall --agent claude --dry-run     # exact removal preview"]
    print("\n".join(lines))
    return 0


def cmd_completion(args: argparse.Namespace) -> int:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    commands = sorted(sub.choices)
    opts = {name: sorted({o for a in p._actions for o in a.option_strings if o.startswith("--")})
            for name, p in sub.choices.items()}
    if args.shell == "bash":
        cases = "\n".join(f'    {c}) opts="{" ".join(opts[c])}" ;;' for c in commands)
        print(f"""# repo-ai bash completion: eval "$(repo-ai completion bash)"
_repo_ai() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}" cmd="${{COMP_WORDS[1]}}" opts=""
  if [ "$COMP_CWORD" -eq 1 ]; then COMPREPLY=($(compgen -W "{' '.join(commands)}" -- "$cur")); return; fi
  case "$cmd" in
{cases}
  esac
  COMPREPLY=($(compgen -W "$opts" -- "$cur"))
}}
complete -F _repo_ai repo-ai""")
    elif args.shell == "zsh":
        print("# repo-ai zsh completion: eval \"$(repo-ai completion zsh)\"")
        print("autoload -Uz bashcompinit && bashcompinit")
        args.shell = "bash"
        return cmd_completion(args)
    else:
        print("# repo-ai fish completion: repo-ai completion fish | source")
        print(f"complete -c repo-ai -f -n '__fish_use_subcommand' -a '{' '.join(commands)}'")
        for c in commands:
            for o in opts[c]:
                print(f"complete -c repo-ai -f -n '__fish_seen_subcommand_from {c}' -l {o[2:]}")
    return 0


def cmd_orchestrate(args: argparse.Namespace) -> int:
    from .episodes import load_prior
    from .orchestrate import plan, render
    from .packet import build_packet

    root, cfg, layout = open_workspace(args)
    index = require_index(layout)
    try:
        packet = build_packet(root, index, load_facts(layout), " ".join(args.task),
                              facts_obj=_facts_obj(layout), prior=load_prior(layout))
    finally:
        index.close()
    result = plan(packet, skeptic_enabled=cfg.skeptic_reviewer, agents_enabled=cfg.write_claude_agents)
    print(json.dumps(result.to_json(), indent=2) if args.json else render(result))
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    from .graph import neighborhood, render

    root, cfg, layout = open_workspace(args)
    index = require_index(layout)
    try:
        node = args.node
        if not node.startswith(("symbol:", "route:", "component:")) and index.get_file(node) is None:
            hits = index.find_symbol(node, limit=1)
            if hits:
                node = f"symbol:{node}"
        edges = neighborhood(index, node, depth=args.depth, kinds=args.kind or ())
    finally:
        index.close()
    if args.format == "json":
        print(json.dumps({"node": node, "edges": [e.to_json() for e in edges]}, indent=2))
    else:
        print(render(edges, node))
    return 0 if edges else 1


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def cmd_search(args: argparse.Namespace) -> int:
    from .index import fts_escape
    _root, _cfg, layout = open_workspace(args, extra={"quiet": True})
    index = require_index(layout)
    rows = index.search(fts_escape(" ".join(args.terms)), limit=args.limit)
    if args.format == "json":
        print(json.dumps([{"path": r["path"], "kind": r["kind"],
                           "score": round(r["score"], 3)} for r in rows], indent=2))
    else:
        if not rows:
            print("no matches.")
        for row in rows:
            print(f"{row['path']}  [{row['kind']}]")
    index.close()
    return 0


def cmd_symbol(args: argparse.Namespace) -> int:
    _root, _cfg, layout = open_workspace(args, extra={"quiet": True})
    index = require_index(layout)
    rows = index.find_symbol(args.name, limit=args.limit)
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        if not rows:
            print(f"no symbol named '{args.name}'.")
        for row in rows:
            parent = f"{row['parent']}." if row["parent"] else ""
            print(f"{row['path']}:{row['line']}  {row['kind']:9s} {parent}{row['name']}")
            if row["signature"]:
                print(f"    {row['signature'][:150]}")
    index.close()
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    _root, _cfg, layout = open_workspace(args, extra={"quiet": True})
    index = require_index(layout)
    target = args.file.lstrip("./")
    row = index.get_file(target)
    if row is None:
        candidates = [f["path"] for f in index.all_files() if f["path"].endswith("/" + target)
                      or f["path"].endswith(target)]
        if len(candidates) == 1:
            target = candidates[0]
            row = index.get_file(target)
        elif candidates:
            print("ambiguous. did you mean:")
            for candidate in candidates[:12]:
                print(f"  {candidate}")
            index.close()
            return 1
        else:
            print(f"'{target}' is not in the index.")
            index.close()
            return 1

    importers = index.importers_of(target)
    imports = [r["resolved_path"] or r["external_package"] or r["raw_target"]
               for r in index.imports_of(target)]
    coupled = index.coupled_with(target, limit=8)
    tests = [r["test_path"] for r in index.tests_for(target)][:10]
    symbols = index.symbols_for(target)
    payload = {
        "path": target,
        "role": row["role"], "language": row["language"], "lines": row["lines"],
        "component": row["component"],
        "centrality": round(row["centrality"], 3),
        "recency": round(row["recency"], 3),
        "churn": row["churn"],
        "symbols": [{"name": s["name"], "kind": s["kind"], "line": s["line"]} for s in symbols[:40]],
        "imported_by": importers[:30],
        "imports": imports[:30],
        "co_changes_with": coupled,
        "likely_tests": tests,
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(f"{target}  [{row['role']}, {row['language']}, {row['lines']} lines]")
        print(f"  component:   {row['component']}")
        print(f"  centrality:  {row['centrality']:.3f}   churn: {row['churn']}")
        for label, items in (("imported by", importers), ("imports", imports),
                             ("co-changes with", coupled), ("likely tests", tests)):
            print(f"  {label} ({len(items)}):")
            for item in items[:10]:
                print(f"    {item}")
            if len(items) > 10:
                print(f"    … and {len(items) - 10} more")
        if symbols:
            print(f"  symbols ({len(symbols)}):")
            for s in symbols[:15]:
                print(f"    {s['line']:5d}  {s['kind']:9s} {s['name']}")
    index.close()
    return 0


def cmd_show(args: argparse.Namespace, filename: str) -> int:
    _root, _cfg, layout = open_workspace(args, extra={"quiet": True})
    path = layout.context_dir / filename
    if not path.is_file():
        raise SystemExit(f"error: {path} not found. {INIT_HINT}.")
    sys.stdout.write(path.read_text("utf-8"))
    return 0


def cmd_deps(args: argparse.Namespace) -> int:
    _root, _cfg, layout = open_workspace(args, extra={"quiet": True})
    index = require_index(layout)
    rows = index.dependencies()
    if args.name:
        needle = args.name.lower()
        rows = [r for r in rows if needle in r["name"].lower()]
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2))
    else:
        if not rows:
            print("no matching dependencies.")
        for row in rows:
            print(f"{row['manager']:9s} {row['scope']:8s} {row['name']:45s} "
                  f"{row['version']:15s} {row['manifest']}")
    index.close()
    return 0


# --------------------------------------------------------------------------
# learn / skills
# --------------------------------------------------------------------------
def cmd_learn(args: argparse.Namespace) -> int:
    from . import learning
    from .signals import forget

    root, cfg, layout = open_workspace(args)
    action, target = args.action, args.target
    if action:
        handled = _learn_action(args, root, cfg, layout, action, target)
        if handled is not None:
            return handled
    if args.forget_signals:
        print("local signals deleted." if forget(layout) else "no local signals stored.")
        return 0
    if args.history:
        events = learning.history(layout)
        if args.json:
            print(json.dumps(events, indent=2))
            return 0
        if not events:
            print("no learning history yet.")
        for event in events[-30:]:
            print(f"{event['id']}  {event['at']}  {event['kind']:8s} "
                  f"{len(event.get('changes', []))} rule change(s), {len(event.get('files', []))} file(s)")
            for rid, before, after in event.get("changes", [])[:8]:
                print(f"    {rid}: {before} -> {after}")
        return 0
    if args.rollback:
        return _learn_rollback(root, cfg, layout, args.rollback)
    if args.apply or args.apply_safe or args.reject:
        return _run_update(args, incremental=True, learn_apply=tuple(args.apply or ()),
                           learn_apply_safe=args.apply_safe, learn_reject=tuple(args.reject or ()))

    index = require_index(layout)
    try:
        facts = _facts_obj(layout)
        if facts is None:
            raise SystemExit("error: no facts.json; run `repo-ai update`")
        cycle = learning.run_cycle(root, layout, facts, index, "suggest",
                                   signals=cfg.learning_signals in ("known-commands", "outcomes"))
    finally:
        index.close()
    rules = sorted(cycle.ledger.rules.values(), key=lambda r: (r.status != "active", r.id))
    if args.explain is not None:
        wanted = [r for r in rules if not args.explain or r.id == args.explain
                  or r.id.startswith(args.explain)]
        if not wanted:
            raise SystemExit(f"error: no rule matching {args.explain!r}")
        if args.json:
            print(json.dumps([r.to_json() for r in wanted], indent=2))
            return 0
        for rule in wanted:
            print(f"{rule.id}  [{rule.status}, v{rule.version}, confidence {rule.confidence}, "
                  f"{rule.source}]")
            print(f"  text:      {rule.text}")
            where = rule.placement + (f" ({rule.topic}; paths {', '.join(rule.paths)})"
                                      if rule.placement == "rules" else "")
            print(f"  placement: {where} — {rule.reason}")
            print("  evidence:")
            for ev in rule.evidence:
                print(f"    {ev.pointer()}  {ev.detail}")
            if rule.note:
                print(f"  note:      {rule.note}")
        return 0
    if args.json:
        print(json.dumps({"policy": cfg.learning_policy,
                          "rules": [r.to_json() for r in rules]}, indent=2))
        return 0
    print(f"learning policy: {cfg.learning_policy}"
          + ("  (proposals are applied only with --apply / --apply-safe)"
             if cfg.learning_policy in {"suggest", "off"} else ""))
    if not rules:
        print("no candidate rules found yet.")
        return 0
    for rule in rules:
        if rule.status == "retired" and not args.all:
            continue
        mark = {"active": "*", "proposed": "?", "covered": "=", "rejected": "x",
                "retired": "-"}.get(rule.status, " ")
        print(f" {mark} {rule.id:38s} {rule.status:9s} {rule.confidence:.2f}  {rule.text[:90]}")
    print("\n  * active  ? proposed  = covered by your own instructions  x rejected  - retired")
    print("  explain: repo-ai learn --explain <id>    apply: repo-ai learn --apply <id> | --apply-safe")
    return 0


def _learn_action(args, root, cfg, layout, action: str, target: str | None) -> int | None:
    """The `repo-ai learn <action>` lifecycle. Returns None to fall through to
    the flag-based implementation shared with v0.5 (`--explain`, `--apply`...)."""
    from . import episodes, learning

    if action in {"approve", "reject", "rollback", "explain"} and not target:
        raise SystemExit(f"error: `repo-ai learn {action}` needs an id "
                         "(see `repo-ai learn review`)")
    if target == "ranking":
        if action == "approve":
            result = episodes.promote(layout, episodes.load_all(layout), force=args.force)
            ev = result["evaluation"]
            if not result["promoted"]:
                print(f"not promoted: shadow evaluation {ev['mrr_recorded']} -> "
                      f"{ev['mrr_with_prior']} over {ev['prompts']} prompts / {ev['sessions']} "
                      f"sessions does not meet: {ev['criteria']}. (--force overrides.)")
                return 1
            event = learning.record_event(layout, "ranking", [("outcome-prior", "shadow", "active")], [])
            print(f"outcome prior promoted ({result['files']} files; MRR {ev['mrr_recorded']} -> "
                  f"{ev['mrr_with_prior']} in shadow). Undo: repo-ai learn rollback ranking "
                  f"(event {event})")
            return 0
        if action in {"reject", "rollback"}:
            removed = episodes.demote(layout)
            if removed:
                learning.record_event(layout, "ranking", [("outcome-prior", "active", "off")], [])
            print("outcome prior removed; ranking is back to evidence only." if removed
                  else "no outcome prior is active.")
            return 0
    if action == "approve":
        args.apply = [target]
        return None
    if action == "reject":
        args.reject = [target]
        return None
    if action == "rollback":
        args.rollback = target
        return None
    if action == "explain":
        args.explain = target
        return None
    if action == "history":
        args.history = True
        return None
    if action == "review":
        args.explain = None
        return _learn_review(args, root, cfg, layout)
    if action == "status":
        return _learn_status(args, root, cfg, layout)
    if action == "shadow":
        ev = episodes.shadow_evaluate(episodes.load_all(layout))
        if args.json:
            print(json.dumps(ev, indent=2))
            return 0
        print(f"outcome prior, shadow evaluation (leave-one-session-out): {ev['prompts']} prompts "
              f"over {ev['sessions']} sessions")
        print(f"  MRR of the first edited file: recorded {ev['mrr_recorded']} -> with prior "
              f"{ev['mrr_with_prior']} ({ev['gain']:+}); {ev['wins']} better, {ev['losses']} worse")
        print(f"  promotable: {'yes' if ev['promotable'] else 'no'} ({ev['criteria']})")
        if ev["promotable"]:
            print("  promote: repo-ai learn approve ranking")
        return 0
    if action == "friction":
        return _print_friction(cfg, layout, args.json)
    if action == "forget":
        what = args.what or "all"
        forgotten = []
        if what in {"episodes", "all"}:
            n = episodes.forget(layout, args.older_than)
            forgotten.append(f"{n} episode file(s)")
        if what in {"signals", "all"} and args.older_than is None:
            from .signals import forget as forget_signals
            forgotten.append("signals" if forget_signals(layout) else "no signals")
        if what in {"flight", "all"} and args.older_than is None:
            from .flight import purge
            forgotten.append("flight log" if purge(layout) else "no flight log")
        if what in {"ranking", "all"} and args.older_than is None:
            forgotten.append("outcome prior" if episodes.demote(layout) else "no outcome prior")
        print("forgot: " + ", ".join(forgotten))
        return 0
    if action == "export":
        ledger = learning.Ledger.load(layout)
        eps = episodes.load_all(layout)
        rules = [r.to_json() for r in ledger.rules.values() if r.status == "active"]
        if args.portable:
            rules = [{"kind": r.get("kind"), "topic": r.get("topic"), "text": r.get("text"),
                      "confidence": r.get("confidence"), "evidence_count": len(r.get("evidence", []))}
                     for r in rules]
        out = {"repo_ai_export": 1, "portable": bool(args.portable), "rules": rules,
               "outcomes": episodes.stats(eps)}
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    return None


def _learn_status(args, root, cfg, layout) -> int:
    from . import episodes, learning

    ledger = learning.Ledger.load(layout)
    counts: dict[str, int] = {}
    for rule in ledger.rules.values():
        counts[rule.status] = counts.get(rule.status, 0) + 1
    eps = episodes.load_all(layout)
    st = episodes.stats(eps)
    ranking = episodes.load_prior(layout)
    shadow = episodes.shadow_evaluate(eps) if eps else None
    friction = episodes.friction(eps) if eps else []
    data = {"policy": cfg.learning_policy, "signals": cfg.learning_signals,
            "rules": counts, "outcomes": st, "outcome_prior": {
                "status": "active" if ranking else "off", "files": len(ranking),
                "shadow": shadow}, "friction": len(friction),
            "history_events": len(learning.history(layout))}
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print(f"learning policy: {cfg.learning_policy}   signals: {cfg.learning_signals}")
    print("rules: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "none yet"))
    if episodes.enabled(cfg) or eps:
        print(f"sessions recorded: {st['sessions']} "
              + (f"({', '.join(f'{n} {s}' for s, n in st['by_status'].items())})" if eps else ""))
        if shadow:
            print(f"outcome prior: {'active' if ranking else 'off'}; shadow MRR "
                  f"{shadow['mrr_recorded']} -> {shadow['mrr_with_prior']} "
                  f"({'promotable' if shadow['promotable'] else 'not yet promotable'})")
        if friction:
            print(f"friction radar: {len(friction)} item(s) — repo-ai learn friction")
    else:
        print("outcome recording is off (learning_signals = \"outcomes\" or --smart enables it)")
    print(f"history: {data['history_events']} event(s) — repo-ai learn history; undo with "
          "repo-ai learn rollback <event>")
    return 0


def _learn_review(args, root, cfg, layout) -> int:
    from . import episodes, learning

    ledger = learning.Ledger.load(layout)
    proposed = sorted((r for r in ledger.rules.values() if r.status == "proposed"),
                      key=lambda r: (-r.confidence, r.id))
    eps = episodes.load_all(layout)
    shadow = episodes.shadow_evaluate(eps) if eps else None
    if args.json:
        print(json.dumps({"proposed": [r.to_json() for r in proposed], "outcome_prior": shadow,
                          "friction": [f.to_json() for f in episodes.friction(eps)]}, indent=2))
        return 0
    if not proposed and not (shadow and shadow["promotable"]):
        print("nothing to review: no proposed rules and no promotable outcome prior.")
        return 0
    for rule in proposed:
        print(f"? {rule.id}  confidence {rule.confidence:.2f}  ({rule.kind})")
        print(f"    {rule.text}")
        for ev in rule.evidence[:3]:
            print(f"    evidence: {ev.pointer()}  {ev.detail}")
        print(f"    approve: repo-ai learn approve {rule.id}   reject: repo-ai learn reject {rule.id}")
    if shadow and shadow["promotable"]:
        print(f"? outcome prior  shadow MRR {shadow['mrr_recorded']} -> {shadow['mrr_with_prior']}"
              f" over {shadow['prompts']} prompts\n    approve: repo-ai learn approve ranking")
    return 0


def _learn_rollback(root, cfg, layout, event_id: str) -> int:
    from . import learning
    from .fsutil import Plan, find_block, read_text
    from .fsutil import KNOWN_BLOCKS
    snapshot = learning.load_snapshot(layout, event_id)
    if snapshot is None:
        raise SystemExit(f"error: no snapshot for event {event_id!r} (see `repo-ai learn --history`)")
    plan = Plan(root)
    restored, skipped = [], []
    for item in snapshot.get("files", []):
        rel, before, after = item["path"], item.get("before"), item.get("after")
        path = (root / rel).resolve()
        if root.resolve() not in path.parents:
            skipped.append((rel, "outside repository"))
            continue
        current = read_text(path)
        if current == after:
            if before is None:
                plan.delete(path)
            else:
                plan.write(path, before)
            restored.append(rel)
            continue
        # The file changed since: restore only repo-ai's managed block.
        done = False
        for begin, end in KNOWN_BLOCKS:
            span = find_block(current, begin, end) if current else None
            if current and before is not None and span:
                old = find_block(before, begin, end)
                new_block = before[old[0]:old[1]] if old else ""
                plan.write(path, current[:span[0]] + new_block + current[span[1]:])
                restored.append(rel + " (managed block)")
                done = True
                break
        if not done:
            skipped.append((rel, "changed since that event; left as is"))
    ledger = learning.Ledger.load(layout)
    events = {e["id"]: e for e in learning.history(layout)}
    reverted = []
    for rid, _before, after in events.get(event_id, {}).get("changes", []):
        rule = ledger.rules.get(rid)
        if rule and after == "active" and rule.status == "active":
            rule.status = "rejected"
            rule.note = f"rolled back ({event_id})"
            reverted.append(rid)
    applied = plan.apply(layout.backup_dir)
    ledger.save()
    learning.record_event(layout, "rollback", [(r, "active", "rejected") for r in reverted],
                          [(plan.rel(c.path), c.before, c.after) for c in applied])
    print(f"rolled back {event_id}: restored {len(restored)} file(s); "
          f"{len(reverted)} rule(s) marked rejected (they will not be re-applied unless "
          "their evidence changes)")
    for rel, why in skipped:
        print(f"  skipped {rel}: {why}")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from . import skills
    from .fsutil import managed_state, marker_attrs, read_text
    from .skillcheck import validate_skill_file

    root, cfg, layout = open_workspace(args, extra={"quiet": True} if args.json else None)
    skills_dir = root / ".claude" / "skills"
    network_actions = {"recommend", "explain", "install", "portfolio", "updates", "compare",
                       "benchmark", "tournament", "health", "enable", "vet", "autopilot"}
    if args.action == "policy":
        return _skills_policy(args, root)
    if args.action == "inventory":
        from . import inventory
        inv = inventory.build(root, firewall=not args.no_firewall)
        print(json.dumps(inv.to_json(), indent=2) if args.json else inventory.render(inv, verbose=args.all))
        return 1 if args.check and any(i.severity == "high" for i in inv.issues) else 0
    if args.action in network_actions or (args.action == "discover" and (args.online or args.from_path)) \
            or (args.action == "audit" and args.all) \
            or (args.action == "disable" and args.third_party) \
            or (args.action in {"rollback", "disable", "promote"} and args.names
                and all(_is_third_party(root, n) for n in args.names)):
        return _skills_network(args, root, cfg, layout)
    action = {"discover": "candidates", "promote": "generate", "doctor": "audit"}.get(
        args.action, args.action)
    if action in {"propose", "test", "diff", "disable", "canary", "draft"}:
        return _skills_lifecycle(args, root, cfg, layout, action)

    if action == "list":
        state = skills.SkillState.load(layout)
        rows = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []:
            text = read_text(skill_md) or ""
            attrs = marker_attrs(text)
            owner = {"pristine": "repo-ai", "modified": "user (edited)",
                     "foreign": "user"}.get(managed_state(text), "?")
            entry = state.entries.get(skill_md.parent.name, {})
            report = validate_skill_file(skill_md)
            rows.append({"name": skill_md.parent.name, "owner": owner,
                         "origin": attrs.get("origin", "user"), "status": entry.get("status", ""),
                         "manual_only": report.manual_only, "valid": report.ok})
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("no project skills in .claude/skills/.")
        for r in rows:
            flags = " manual-only" if r["manual_only"] else ""
            flags += "" if r["valid"] else " INVALID"
            print(f"  /{r['name']:24s} {r['origin']:9s} owner: {r['owner']:14s}{flags}")
        return 0

    if action == "rollback":
        if not args.names:
            raise SystemExit("error: name the skill to roll back")
        for name in args.names:
            print(skills.rollback(layout, name, previous=args.previous))
        return _run_update(args, incremental=True)

    if action == "generate" and args.draft:
        state = skills.SkillState.load(layout)
        for name in args.names:
            entry = state.entries.get(name, {})
            draft = entry.get("draft")
            if not draft:
                raise SystemExit(f"error: no stored draft for {name!r} (repo-ai skills draft {name})")
            if not draft.get("ok"):
                raise SystemExit(f"error: the draft for {name!r} fails static tests: "
                                 + "; ".join(draft.get("problems", [])))
            entry["pinned"] = {"version": int(entry.get("version", 1)) + 1, "body": draft["body"]}
            entry["status"] = "active"
            entry.pop("draft", None)
            entry["note"] = "promoted Tier-2 draft (reviewed by user)"
        state.save()
        return _run_update(args, incremental=True)

    if action == "generate":
        if not args.names and not args.safe:
            raise SystemExit("error: use --safe (all safe candidates) or name skills to generate")
        return _run_update(args, incremental=True, skills_generate=tuple(args.names),
                           skills_generate_safe=args.safe)

    if action == "audit":
        from .adapters.claude import skill_description_tokens
        problems = 0
        desc_tokens = 0
        out = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []:
            report = validate_skill_file(skill_md, root)
            if not report.manual_only:  # a manual-only description is never offered to the model
                desc_tokens += skill_description_tokens(report.description_chars)
            clash = (Path.home() / ".claude" / "skills" / skill_md.parent.name / "SKILL.md").is_file()
            out.append({"name": skill_md.parent.name, "errors": report.errors,
                        "warnings": report.warnings + (["a personal skill has the same name"] if clash else []),
                        "manual_only": report.manual_only})
            problems += len(report.errors)
        if args.json:
            print(json.dumps({"skills": out, "description_tokens": desc_tokens}, indent=2))
        else:
            for item in out:
                status = "ok" if not item["errors"] else "FAIL"
                print(f"  [{status:4s}] /{item['name']}" + (" (manual-only)" if item["manual_only"] else ""))
                for e in item["errors"]:
                    print(f"         error: {e}")
                for w in item["warnings"]:
                    print(f"         warn:  {w}")
            print(f"  always-loaded skill descriptions: ~{desc_tokens} tokens (manual-only skills excluded)")
        return 1 if problems else 0

    # candidates
    index = require_index(layout)
    try:
        facts = _facts_obj(layout)
        specs = skills.discover(root, layout, facts, index,
                                signals=cfg.learning_signals in ("known-commands", "outcomes")) if facts else []
    finally:
        index.close()
    state = skills.SkillState.load(layout)
    rows = []
    for spec in specs:
        report = skills.validate(spec, root)
        clash = skills.collision(root, spec.name)
        rows.append({"name": spec.name, "risk": spec.risk, "confidence": spec.confidence,
                     "status": state.entries.get(spec.name, {}).get("status", "candidate"),
                     "reason": spec.reason, "valid": report.ok, "errors": report.errors,
                     "collision": clash,
                     "evidence": [e.pointer() for e in spec.evidence[:5]]})
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no skill candidates: repo-ai found no repeatable, repo-specific workflow with enough evidence.")
        return 0
    for r in rows:
        risk = "manual-only" if r["risk"] == "risky" else "safe"
        print(f"  {r['name']:22s} {r['status']:9s} {risk:11s} conf {r['confidence']:.2f}  {r['reason']}")
        print(f"      evidence: {', '.join(r['evidence'])}")
        if r["collision"]:
            print(f"      blocked: {r['collision']}")
        for e in r["errors"]:
            print(f"      invalid: {e}")
    print("\n  generate: repo-ai skills generate --safe   (or name skills; risky ones are written manual-only)")
    return 0


def _is_third_party(root: Path, name: str) -> bool:
    from .portfolio import load_lock
    return name in load_lock(root)["skills"]


def _radar_state_path(layout) -> Path:
    from .registry import machine_dir
    return machine_dir(layout.root) / "radar.json"  # never a file a repository could commit


def _load_radar(layout) -> dict:
    try:
        return json.loads(_radar_state_path(layout).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _profile(root, layout, index):
    from . import radar
    from .episodes import load_all
    return radar.build_profile(root, load_facts(layout), index, load_all(layout))


def _skills_network(args, root, cfg, layout) -> int:
    """Skill Intelligence Network: radar, firewall, recommendations, portfolio."""

    from . import firewall, portfolio, radar, recommend
    from .fsutil import atomic_write
    from .registry import policy_for

    from . import autonomy
    action = args.action
    state = _load_radar(layout)
    existing = {n: t for n, t in _skill_texts(root).items()}
    level = autonomy.level(root)
    if not autonomy.network_allowed(level) and (
            (action == "discover" and args.online) or action == "updates"
            or (action == "vet" and args.names and str(args.names[0]).startswith(("https://", "http://")))):
        raise SystemExit(f"error: the skill policy is {level}: `skills {action}` needs the network "
                         "(repo-ai skills policy show)")
    if action in {"benchmark", "tournament"} and not (args.dry_run or args.trial_fake):
        if autonomy.trial_problem(level):
            raise SystemExit(f"error: {autonomy.trial_problem(level)}")

    def save_state(data: dict) -> None:
        atomic_write(_radar_state_path(layout), json.dumps(data, indent=1) + "\n")

    def emit(obj, text: str) -> int:
        print(json.dumps(obj, indent=2, default=str) if args.json else text)
        return 0

    if action == "discover":
        index = require_index(layout)
        try:
            profile = _profile(root, layout, index)
        finally:
            index.close()
        candidates: list[dict] = list(state.get("candidates", [])) if args.from_path else []
        reports: dict[str, dict] = dict(state.get("reports", {})) if args.from_path else {}
        notes: list[str] = []
        errors: list[str] = []
        queries: list[str] = []
        requests = 0
        if args.online:
            zone, policy = policy_for(root)
            if policy.get("discovery", "allow") == "deny":
                raise SystemExit(f"error: online discovery is denied for zone `{zone}` "
                                 "(repo-ai registry policy --zone ... --set discovery=allow)")
            client = radar.Client(_radar_cache_dir(), max_requests=args.max_requests)
            providers = [p.strip() for p in args.providers.split(",") if p.strip()]
            found = radar.discover(profile, list(cfg.extra.get("skill_publishers", []) or []),
                                   list(cfg.extra.get("skill_marketplaces", []) or []),
                                   client, providers)
            notes, errors, queries, requests = found["notes"], found["errors"], found["queries"], found["requests"]
            ranked = sorted(found["candidates"], key=lambda c: (not c.matched_gaps,
                                                                c.provider not in {"anthropic", "vercel"},
                                                                -c.stars, c.name))
            for cand in ranked[:args.audit_limit]:
                try:
                    dest, files, prior = firewall.quarantine_github(client, cand)
                except (radar.RadarError, firewall.QuarantineError) as exc:
                    errors.append(f"quarantine {cand.id}: {exc}")
                    unaudited = cand.to_json()
                    unaudited["quarantine"] = ""
                    candidates.append(unaudited)
                    continue
                report = firewall.inspect(dest, files, cand.to_json(), existing, prior)
                reports[cand.id] = report.to_json()
                cand_json = cand.to_json()
                cand_json["quarantine"] = str(dest)
                candidates.append(cand_json)
            for cand in ranked[args.audit_limit:]:
                cj = cand.to_json()
                cj["quarantine"] = ""
                candidates.append(cj)
            requests = client.requests
        if args.from_path:
            src = Path(args.from_path).resolve()
            name = src.name
            dest, files, prior = firewall.quarantine_local(src, name)
            cand = {"id": f"local/{name}@{firewall.content_hash(files)[:12]}", "name": name,
                    "provider": "local", "owner": "", "repo": "", "path": name, "commit": "",
                    "description": _desc_of(dest), "stars": 0, "quarantine": str(dest),
                    "source_path": str(src)}
            from .radar import Candidate, match_gaps
            cand["matched_gaps"] = match_gaps(Candidate(cand["id"], name, "local", "", "", name, "",
                                                        "", cand["description"]), profile)
            report = firewall.inspect(dest, files, cand, existing, prior)
            reports[cand["id"]] = report.to_json()
            candidates = [c for c in candidates if c["id"] != cand["id"]] + [cand]
        data = {"run_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "profile": profile.to_json(),
                "candidates": candidates, "reports": reports, "queries": queries,
                "errors": errors, "notes": notes, "requests": requests}
        save_state(data)
        lines = [f"skill radar: {len(candidates)} candidate(s), {len(reports)} audited, "
                 f"{requests} API request(s)" + (f"; queries: {', '.join(queries)}" if queries else "")]
        lines.append("  capability gaps (with evidence): " + (", ".join(
            f"{g['id']} ({g['strength']})" for g in profile.to_json()["gaps"]) or "none"))
        for c in candidates[:30]:
            rep = reports.get(c["id"], {})
            lines.append(f"  {c['name'][:30]:30s} {c['provider']:10s} {rep.get('verdict', 'not audited'):11s} "
                         f"licence {rep.get('license') or c.get('repo_license') or '?':12s} gaps "
                         f"{','.join(c.get('matched_gaps') or []) or '-'}  {c['id']}")
        for e in errors[:8]:
            lines.append(f"  error: {e}")
        for n in notes[:5]:
            lines.append(f"  note: {n}")
        lines.append("  next: repo-ai skills recommend   |   repo-ai skills explain <name>")
        return emit(data, "\n".join(lines))

    if action == "vet":
        return _skills_vet(args, root, state, existing, save_state, emit)

    if action == "autopilot":
        return _skills_autopilot(args, root, state, existing, emit)

    candidates = state.get("candidates", [])
    reports = state.get("reports", {})
    profile = state.get("profile", {})

    def find(key: str) -> dict:
        hits = [c for c in candidates if c["id"] == key or c["name"] == key or c["id"].startswith(key)]
        if not hits:
            raise SystemExit(f"error: no discovered candidate {key!r} (repo-ai skills discover --online)")
        approve = getattr(args, "approve", None) or ""
        hits.sort(key=lambda c: (not (approve and reports.get(c["id"], {}).get("content_hash", "")
                                      .startswith(approve)), c["id"] not in reports, c["id"]))
        return hits[0]

    if action == "recommend":
        result = recommend.recommend(candidates, reports, profile, existing,
                                     {k: v for k, v in state.get("trials", {}).items()})
        lines = [result["summary"]]
        for r in result["recommendations"][:15]:
            mark = "RECOMMENDED" if r["install_recommended"] else ("blocked" if r["verdict"] == "blocked"
                                                               else "not recommended")
            lines.append(f"  [{mark}] {r['name']} score {r['score']} ({r['verdict']}; benefit "
                         f"{r['evidence_status']}; ~{r['context_tokens_est']} tokens always loaded)")
            for reason in r["reasons"][:3]:
                lines.append(f"      - {reason}")
        if result["gaps_without_candidates"]:
            lines.append("  gaps with no candidate: " + ", ".join(result["gaps_without_candidates"]))
        lines.append("  benefit is unproven until `repo-ai skills benchmark <name>` runs a controlled trial")
        return emit(result, "\n".join(lines))

    if action == "explain":
        if not args.names:
            raise SystemExit("error: repo-ai skills explain <name|candidate-id>")
        name = args.names[0]
        lock = portfolio.load_lock(root)
        if name in lock["skills"]:
            return emit(lock["skills"][name], json.dumps(lock["skills"][name], indent=2))
        cand = find(name)
        rep = reports.get(cand["id"]) or {}
        rec = recommend.score(cand, rep or None, profile, existing).to_json()
        text = [f"{cand['name']} — {cand['description'][:200]}",
                f"  source: {cand.get('url') or cand['id']} (commit {cand.get('commit', '')[:12]}, "
                f"provider {cand['provider']}, {cand.get('stars', 0)} stars"
                + (", archived" if cand.get("archived") else "") + ")",
                f"  duplicates of this content elsewhere: {len(cand.get('duplicates', []))}"]
        if rep:
            text.append(firewall.render(firewall.Report(
                rep["candidate_id"], rep["content_hash"], rep["files"],
                [firewall.Finding(**f) for f in rep["findings"]], rep["license"], rep["verdict"],
                rep["complete"])))
        text.append(f"  recommendation: {'install' if rec['install_recommended'] else 'do not install'} "
                    f"(score {rec['score']}); " + "; ".join(rec["reasons"]))
        if rep:
            text.append(f"  to install after review: repo-ai skills install {cand['name']} "
                        f"--approve {rep['content_hash'][:16]}")
        return emit({"candidate": cand, "report": rep, "recommendation": rec}, "\n".join(text))

    if action == "install":
        if not args.names:
            raise SystemExit("error: repo-ai skills install <name|candidate-id> --approve <hash>")
        from . import capbundle
        cand = find(args.names[0])
        old = reports.get(cand["id"])
        if not old:
            raise SystemExit("error: this candidate was not audited; re-run discovery with a higher --audit-limit")
        policy_problem = autonomy.install_problem(level, remote=cand["provider"] != "local",
                                                  approve=args.approve or "")
        if policy_problem:
            raise SystemExit(f"error: {policy_problem}")
        try:
            hosts = capbundle.parse_hosts(args.host) if args.host else None
        except capbundle.BundleError as exc:
            raise SystemExit(f"error: {exc}") from exc
        if cand.get("source_problems"):
            from .textsafe import display
            raise SystemExit("error: refusing to install: vetting its source did not complete: "
                             + "; ".join(display(p, 300) for p in cand["source_problems"]))
        # Re-fetch at the pinned commit and re-inspect: refuse anything that changed.
        if cand["provider"] == "local":
            # re-read the ORIGINAL source: tampering after discovery is caught by the hash check
            src = Path(cand.get("source_path") or Path(cand["quarantine"]) / "files")
            dest, files, prior = firewall.quarantine_local(src, cand["name"] + "-recheck")
        else:
            if not args.online:  # re-fetching from GitHub is network use: explicit, never implied
                raise SystemExit("error: installing a remote skill re-fetches it from GitHub at the "
                                 "pinned commit; pass --online to allow that network access")
            client = radar.Client(_radar_cache_dir(), max_requests=args.max_requests)
            obj = radar.Candidate(**{k: v for k, v in cand.items() if k in radar.Candidate.__dataclass_fields__})
            dest, files, prior = firewall.quarantine_github(client, obj)
        radar.private_dir(firewall.quarantine_root())
        radar.harden_tree(dest)
        fresh = firewall.inspect(dest, files, cand, {k: v for k, v in existing.items()
                                                     if k != cand["name"]}, prior)
        if fresh.content_hash != old["content_hash"]:
            raise SystemExit(f"error: content changed since it was reviewed ({old['content_hash'][:16]} → "
                             f"{fresh.content_hash[:16]}); re-run discovery and review again")
        try:
            entry = portfolio.install(root, cand["name"], dest, fresh, cand, args.approve or "",
                                      accept_review=args.accept_review, allow_scripts=args.allow_scripts,
                                      dry_run=args.dry_run, hosts=hosts, pinned_hash=old["content_hash"])
        except portfolio.PortfolioError as exc:
            raise SystemExit(f"error: {exc}") from exc
        if args.dry_run:
            plan = entry["plan"]
            preview = "\n".join([f"dry run: {cand['name']} → " + ", ".join(
                f"{h['host']} ({h['skills_dir']}, {h['support']})" for h in plan["hosts"]),
                *[f"  CONFLICT {c}" for c in entry["conflicts"]], plan["diff"].rstrip("\n") or "  (no changes)"])
            emit(entry, preview)
            return 1 if entry["conflicts"] else 0
        export_only = [h for h in entry.get("hosts", []) if capbundle.HOSTS[h].support == capbundle.EXPORT_ONLY]
        return emit(entry, f"installed {cand['name']} (pinned {fresh.content_hash[:16]}, commit "
                    f"{cand.get('commit', '')[:12] or 'local'}); approved for limited use — its benefit "
                    "is unproven until a trial runs. Undo: repo-ai skills disable --third-party "
                    f"{cand['name']}" + (f"\n  exported for {', '.join(export_only)}: export only, loading by "
                                         "those hosts is not verified" if export_only else ""))

    if action == "portfolio":
        lock = portfolio.load_lock(root)
        rows = [{"name": n, "status": e["status"], "license": e.get("license"),
                 "source": f"{e['source'].get('owner')}/{e['source'].get('repo')}@"
                           f"{(e['source'].get('commit') or '')[:12]}",
                 "content": e["content_hash"][:16], "verdict": e.get("verdict"),
                 "evidence": e.get("evidence", {}).get("status"), "modified": e.get("modified"),
                 "approved_at": e.get("approved_at")} for n, e in sorted(lock["skills"].items())]
        bad = [f"  IGNORED invalid entry {n!r}: {why}" for n, why in sorted(lock.get("invalid", {}).items())]
        pf_text = "\n".join([f"skill portfolio ({portfolio.lock_path(root).relative_to(root)}): "
                             f"{len(rows)}", *bad]
                            + [f"  {r['name']:28s} {r['status']:8s} {r['source']}  {r['license']}  "
                               f"benefit: {r['evidence']}" for r in rows] or ["  (empty)"])
        return emit(rows, pf_text)

    if action == "disable":
        names = None if args.all or not args.names else args.names
        out = portfolio.disable(root, names)
        return emit(out, ("kill switch: " if names is None else "") +
                    (f"disabled {', '.join(out)}" if out else "nothing to disable"))

    if action == "enable":
        if not args.names:
            raise SystemExit("error: repo-ai skills enable <name> [--approve <hash>]")
        try:
            entry = portfolio.enable(root, args.names[0], approve=args.approve or "",
                                     allow_scripts=args.allow_scripts, level=level)
        except portfolio.PortfolioError as exc:
            raise SystemExit(f"error: {exc}") from exc
        return emit(entry, f"re-enabled {args.names[0]} ({entry['content_hash'][:16]}, verified)")

    if action == "rollback":
        try:
            entry = portfolio.rollback(root, args.names[0], approve=args.approve or "",
                                       allow_scripts=args.allow_scripts, level=level)
        except portfolio.PortfolioError as exc:
            raise SystemExit(f"error: {exc}") from exc
        return emit(entry, f"rolled back {args.names[0]} to {entry['content_hash'][:16]}")

    if action == "updates":
        if not (args.online or args.check):
            raise SystemExit("error: checking for updates queries GitHub; pass --online (or --check) "
                             "to allow that network access")
        client = radar.Client(_radar_cache_dir(), max_requests=args.max_requests)
        rows = portfolio.check_updates(root, client)
        return emit(rows, "\n".join(f"  {r['name']}: {r['status']}" for r in rows) or "portfolio is empty")

    if action == "health":
        from .episodes import load_all
        rows = portfolio.health(root, load_all(layout))
        lines = [f"skill health: {len(rows)} third-party skill(s)"]
        for r in rows:
            lines.append(f"  {r['name']}: {r['status']}, benefit {r['evidence']}, used in "
                         f"{r['sessions_used']} session(s)" + ("; " + "; ".join(r["issues"])
                                                               if r["issues"] else "; healthy"))
        return emit(rows, "\n".join(lines))

    if action == "compare":
        if len(args.names) != 2:
            raise SystemExit("error: repo-ai skills compare <a> <b>")
        from .skills_lab import overlap
        a, b = find(args.names[0]), find(args.names[1])
        ra, rb = (recommend.score(c, reports.get(c["id"]), profile, existing).to_json() for c in (a, b))
        cmp_out = {"a": ra, "b": rb, "description_overlap": overlap(a["description"], b["description"]),
                   "findings_a": reports.get(a["id"], {}).get("counts"),
                   "findings_b": reports.get(b["id"], {}).get("counts")}
        cmp_text = "\n".join([f"{a['name']} vs {b['name']} (description overlap "
                              f"{cmp_out['description_overlap']})",
                          *[f"  {r['name']}: score {r['score']}, {r['verdict']}, gaps {r['gaps']}, "
                            f"~{r['context_tokens_est']} tokens, benefit {r['evidence_status']}"
                            for r in (ra, rb)],
                          "  neither is shown to be better without a controlled trial (skills benchmark)"])
        return emit(cmp_out, cmp_text)

    if action in {"benchmark", "tournament"}:
        return _skill_benchmark(args, root, cfg, layout, state, find)

    if action == "promote":
        try:
            entries = [portfolio.promote(root, n) for n in args.names]
        except portfolio.PortfolioError as exc:
            raise SystemExit(f"error: {exc}") from exc
        return emit(entries, "\n".join(f"promoted {n} (trial {e['promoted_on']['experiment']}, "
                                       f"{e['promoted_on']['status']}, diff {e['promoted_on']['diff']})"
                                       for n, e in zip(args.names, entries, strict=True)))

    if action == "audit":
        rows = []
        for cand in candidates:
            q = cand.get("quarantine")
            if not q or not Path(q).is_dir() or \
                    not Path(q).resolve().is_relative_to(firewall.quarantine_root().resolve()):
                continue  # only repo-ai's own quarantine is ever read
            files = json.loads((Path(q) / "manifest.json").read_text("utf-8"))["files"]
            try:
                for f in files:
                    firewall.safe_rel(str(f.get("path", "")))
            except (firewall.QuarantineError, AttributeError):
                continue
            audited = firewall.inspect(Path(q), files, cand, {k: v for k, v in existing.items()
                                                              if k != cand["name"]})
            reports[cand["id"]] = audited.to_json()
            rows.append({"id": cand["id"], "verdict": audited.verdict, "counts": audited.counts()})
        state["reports"] = reports
        save_state(state)
        return emit(rows, "\n".join(f"  {r['verdict']:8s} {r['id']} {r['counts']}" for r in rows)
                    or "nothing quarantined to audit")
    return 2


POLICY_REFUSED = 5  # exit status: raising the skill policy needs a human in a terminal


def _skills_policy(args, root: Path) -> int:
    """`skills policy [show | set LEVEL | revoke]`: the autonomy level for this checkout."""
    from . import autonomy, capbundle, portfolio
    verb = args.names[0] if args.names else "show"
    try:
        if verb == "show" and len(args.names) <= 1:
            data = autonomy.load(root)
        elif verb == "set" and len(args.names) == 2:
            data = autonomy.set_level(root, args.names[1], interactive=sys.stdin.isatty())
        elif verb == "revoke" and len(args.names) == 1:
            data = autonomy.revoke(root)
            auto = portfolio.policy_installed(root)  # the machine-local record, never the lockfile
            data["disabled"] = portfolio.disable(root, auto) if auto else []
        else:
            raise autonomy.PolicyError("usage: repo-ai skills policy [show | set LEVEL | revoke]; levels: "
                                       + ", ".join(autonomy.LEVELS))
    except autonomy.PolicyError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return exc.code
    data["auto_installed"] = portfolio.policy_installed(root)
    data["levels"] = dict(autonomy.DESCRIPTIONS)
    data["kinds"] = dict(capbundle.KIND_RULES)
    data["hosts"] = [t.to_json() for t in capbundle.HOSTS.values()]
    data["always_needs_approval"] = ["scripts", "hooks", "MCP servers", "plugins", "binaries", "provider adapters",
                                     "static tools", "external accounts", "permission changes",
                                     "network execution"]
    lines = [f"skill policy: {data['level']}{' (default)' if data.get('default') else ''} — {data['description']}",
             f"  stored outside the repository: {data['path']}"]
    if data.get("note"):
        lines.append(f"  note: {data['note']}")
    if verb == "revoke":
        lines.append("  revoked: back to " + autonomy.DEFAULT
                     + (f"; disabled auto-installed: {', '.join(data['disabled'])}" if data.get("disabled") else ""))
    if data["auto_installed"]:
        lines.append(f"  installed by the policy (not by a per-hash approval): {', '.join(data['auto_installed'])}")
    lines.append("  every level still needs your approval for: " + ", ".join(data["always_needs_approval"]))
    lines.append("  levels: " + ", ".join(autonomy.LEVELS) + "   (repo-ai skills policy set LEVEL | revoke)")
    print(json.dumps(data, indent=2) if args.json else "\n".join(lines))
    return 0


AUTOPILOT_INTEGRITY = 4  # exit status: a candidate's content changed between vetting and install


def _skills_autopilot(args, root: Path, state: dict, existing: dict, emit) -> int:
    """Apply the skill policy to the vetted candidates of the last discovery.

    Under SAFE_AUTO an inert, pinned, SKILL.md-only skill that fills a gap (or that
    you name) is re-fetched, re-hashed against the vetted pin, re-assessed and
    installed into Claude Code project scope. A skill recommended only because it
    names this repository's package fills no gap: it is installed only when named.
    Everything else is only proposed."""
    from . import autonomy, capbundle, firewall, portfolio, recommend
    from .textsafe import shell_word
    level = autonomy.level(root)
    candidates = state.get("candidates", [])
    reports = state.get("reports", {})
    profile = state.get("profile", {})
    named = set(args.names)
    known = {c["name"] for c in candidates} | {c["id"] for c in candidates}
    if named - known:
        raise SystemExit(f"error: no discovered candidate {sorted(named - known)[0]!r} "
                         "(repo-ai skills discover --from-path DIR | --online)")
    lock = portfolio.load_lock(root)
    qroot = firewall.quarantine_root().resolve()
    rows: list[dict] = []
    integrity = 0
    for cand in candidates:
        rep = reports.get(cand["id"])
        nominated = cand["name"] in named or cand["id"] in named
        if not rep or (named and not nominated):
            continue
        row = {"id": cand["id"], "name": cand["name"], "content_hash": rep["content_hash"]}
        installed = lock["skills"].get(cand["name"])
        if installed and installed.get("content_hash") == rep["content_hash"] and installed.get("status") == "active":
            rows.append({**row, "action": "none", "reasons": ["already installed at this content hash"]})
            continue
        report = firewall.Report(rep["candidate_id"], rep["content_hash"], rep["files"],
                                 [firewall.Finding(**f) for f in rep["findings"]], rep["license"], rep["verdict"],
                                 rep["complete"])
        q = Path(cand.get("quarantine") or "")
        if cand.get("quarantine") and q.is_dir() and q.resolve().is_relative_to(qroot):
            try:
                assessment = capbundle.assess(q, report)
            except (OSError, firewall.QuarantineError) as exc:
                assessment = {"installable": False, "inert": False, "reasons": [f"quarantined copy unreadable: {exc}"]}
        else:
            assessment = {"installable": False, "inert": False, "reasons": ["no quarantined copy to assess"]}
        if cand.get("source_problems"):
            assessment = {**assessment, "installable": False,
                          "reasons": [*assessment.get("reasons", []), "vetting its source did not complete"]}
        rec = recommend.score(cand, rep, profile, existing).to_json()
        decision = autonomy.decide(level, assessment, nominated=nominated,
                                   recommended=recommend.autopilot_wants(rec))
        row.update(action=decision["action"], reasons=decision["reasons"], inert=bool(assessment.get("inert")),
                   surfaces=assessment.get("surfaces", []))
        if decision["action"] == "auto_install" and not args.dry_run:
            row["result"] = _autopilot_install(args, root, cand, rep, existing, level)
            if row["result"].startswith("refused: content changed"):
                integrity += 1
        elif decision["action"] == "propose_install":
            row["next"] = f"repo-ai skills install {shell_word(cand['name'])} --approve {rep['content_hash'][:16]}"
        elif decision["action"] == "propose_trial":
            row["next"] = ("install it with an approval, then: repo-ai skills benchmark <name> "
                           "--max-cost-usd <cap> --dry-run")
        rows.append(row)
    lines = [f"skill autopilot under policy {level}" + (" (dry run: nothing installed)" if args.dry_run else "")
             + f": {len(rows)} vetted candidate(s)"]
    for r in rows:
        lines.append(f"  {r['action']:15s} {r['name']}" + (f" → {r['result']}" if r.get("result") else "")
                     + (f"  ({r['reasons'][0]})" if r.get("reasons") else ""))
        if r.get("next"):
            lines.append(f"      next: {r['next']}")
    if not rows:
        lines.append("  nothing vetted: run repo-ai skills discover first")
    emit({"policy": level, "dry_run": bool(args.dry_run), "decisions": rows}, "\n".join(lines))
    return AUTOPILOT_INTEGRITY if integrity else 0


def _autopilot_install(args, root: Path, cand: dict, rep: dict, existing: dict, level: str) -> str:
    """Re-fetch, re-hash against the vetted pin, re-assess, then install without a per-hash approval."""
    from . import capbundle, firewall, portfolio, radar
    try:
        if cand["provider"] == "local":
            src = Path(cand.get("source_path") or Path(cand["quarantine"]) / "files")
            dest, files, prior = firewall.quarantine_local(src, cand["name"] + "-recheck")
        else:
            if not args.online:
                return "skipped: re-fetching from GitHub needs --online"
            client = radar.Client(_radar_cache_dir(), max_requests=args.max_requests)
            obj = radar.Candidate(**{k: v for k, v in cand.items() if k in radar.Candidate.__dataclass_fields__})
            dest, files, prior = firewall.quarantine_github(client, obj)
        radar.private_dir(firewall.quarantine_root())
        radar.harden_tree(dest)
    except (OSError, radar.RadarError, firewall.QuarantineError) as exc:
        return f"refused: could not re-fetch ({exc})"
    fresh = firewall.inspect(dest, files, cand, {k: v for k, v in existing.items() if k != cand["name"]}, prior)
    if fresh.content_hash != rep["content_hash"]:
        return (f"refused: content changed since it was vetted ({rep['content_hash'][:16]} → "
                f"{fresh.content_hash[:16]})")
    assessment = capbundle.assess(dest, fresh)
    if not assessment["inert"]:
        return "refused: no longer inert on re-inspection (" + ", ".join(assessment["surfaces"][:3]) + ")"
    try:
        portfolio.install(root, cand["name"], dest, fresh, cand, fresh.content_hash, hosts=("claude-code",),
                          pinned_hash=rep["content_hash"], approved_by=f"policy:{level}")
    except portfolio.PortfolioError as exc:
        return f"refused: {exc}"
    return f"installed (pinned {fresh.content_hash[:16]}; undo: repo-ai skills disable --third-party {cand['name']})"


PLUGIN_PARTS = {".claude-plugin/plugin.json": "plugin manifest", ".claude-plugin/marketplace.json":
                "marketplace", "hooks/hooks.json": "hooks", ".mcp.json": "MCP servers",
                "package.json": "npm package"}


VET_SCHEMA = "repo-ai.skills-vet/1"
VET_INCOMPLETE = 3  # exit status: some skill or the source itself could not be vetted


def _installable_name(name: object) -> bool:
    """A name that `skills install` accepts and that is safe to paste into a shell as it is."""
    import re as _re
    return isinstance(name, str) and len(name) <= 64 and bool(
        _re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name))


def _skills_vet(args, root: Path, state: dict, existing: dict, save_state, emit) -> int:
    """Vet one GitHub source someone pointed you at (a README, a video, a
    colleague) before anything installs it: pin the ref to a commit,
    quarantine every skill in it, inspect, and record the candidates so
    `skills install <name> --approve <hash> --online` can use them.

    The result is `complete` only when every SKILL.md in scope was vetted and the
    source checked out (identity, reachable commit, untruncated tree); otherwise
    the exit status is 3 and nothing is presented as clean."""
    from . import firewall, radar
    from .registry import policy_for
    from .textsafe import display, shell_word

    def fail(msg: str) -> int:
        if args.json:
            print(json.dumps({"schema": VET_SCHEMA, "complete": False, "error": msg}, indent=2))
            raise SystemExit(1)
        raise SystemExit(f"error: {display(msg, 600)}")

    if not args.names:
        return fail("repo-ai skills vet https://github.com/<owner>/<repo>[/tree/<ref>/<path>] --online"
                    "   |   repo-ai skills vet <local-dir>")
    if "://" not in args.names[0] and Path(args.names[0]).is_dir():
        return _vet_local(Path(args.names[0]), existing, emit)
    if not args.online:
        return fail("vetting fetches the source from GitHub at a pinned commit; "
                    "pass --online to allow that network access")
    zone, policy = policy_for(root)
    if policy.get("discovery", "allow") == "deny":
        return fail(f"online discovery is denied for zone `{zone}`")
    try:
        owner, repo, ref, under = radar.parse_github_url(args.names[0])
    except radar.RadarError as exc:
        return fail(str(exc))
    limit = args.vet_limit if args.vet_limit is not None else radar.VET_LIMIT
    client = radar.Client(_radar_cache_dir(), max_requests=args.max_requests
                          if args.max_requests is not None else radar.VET_MAX_REQUESTS)
    try:
        src = radar.vet_source(client, owner, repo, ref, under, limit=limit)
    except radar.RadarError as exc:
        return fail(str(exc))
    meta, commit = src.meta, src.commit
    paths = {e.get("path", "") for e in src.tree if e.get("type") == "blob"}
    ships = sorted({label for p, label in PLUGIN_PARTS.items() if p in paths} |
                   ({"hooks"} if any(p.endswith("/hooks/hooks.json") for p in paths) else set()))
    from . import pluginvet
    candidates = [c for c in state.get("candidates", []) if c.get("provider") != "url"
                  or not any(c["id"] == x.id for x in src.candidates)]
    reports = dict(state.get("reports", {}))
    rows: list[dict] = []
    errors: list[str] = list(src.problems)
    skill_errors = [{"path": p, "error": e} for p, e in src.skill_errors]
    radar.private_dir(firewall.quarantine_root())  # owner-only, like each quarantine in it
    for cand in src.candidates:
        try:
            dest, files, prior = firewall.quarantine_github(client, cand)
            radar.harden_tree(dest)
            report = firewall.inspect(dest, files, cand.to_json(),
                                      {k: v for k, v in existing.items() if k != cand.name}, prior)
        except (radar.RadarError, firewall.QuarantineError, OSError, ValueError, KeyError) as exc:
            # one skill's failure (request cap, a case-colliding path on a case-insensitive
            # disk, a bad blob) is that skill's error; the others are still vetted
            skill_errors.append({"path": f"{cand.path}/SKILL.md" if cand.path else "SKILL.md",
                                 "name": cand.name, "error": f"{type(exc).__name__}: {exc}"
                                 if isinstance(exc, (OSError, KeyError)) else str(exc)})
            continue
        reports[cand.id] = report.to_json()
        cj = cand.to_json()
        cj["quarantine"] = str(dest)
        cj["source_problems"] = list(src.problems)  # `skills install` refuses while any remain
        candidates.append(cj)
        rows.append({"name": cand.name, "id": cand.id, "path": cand.path, "verdict": report.verdict,
                     "license": report.license or cand.repo_license, "content_hash": report.content_hash,
                     "counts": report.counts(), "findings": [
                         f.to_json() for f in report.findings
                         if firewall.SEVERITY_ORDER[f.severity] >= firewall.SEVERITY_ORDER["medium"]][:12]})
    state.update(candidates=candidates, reports=reports)
    save_state(state)
    total = len(src.skill_paths)
    per_skill = [f"{e.get('name') or e['path']}: {e['error']}" for e in skill_errors]
    summary: list[str] = []
    if src.skipped:
        summary.append(f"{len(src.skipped)} of {total} skill(s) were not vetted: over --vet-limit "
                      f"{limit} (raise it to vet them)")
    if any("request cap" in e["error"] for e in skill_errors):
        summary.append(f"the request cap ({client.max_requests}) was reached; raise --max-requests "
                      "to vet the rest")
    errors += per_skill + summary
    lic = meta.get("license")
    source = pluginvet.GitHubSource(client, owner, repo, commit, src.tree, under or "")
    source.truncated = bool(src.truncated)  # the same tree response the skills came from
    plugin = pluginvet.vet(source, skills=_skill_summary(rows, errors))
    if not plugin.license:
        plugin.license = (lic.get("spdx_id") if isinstance(lic, dict) else "") or ""
    errors += [f"plugin inspection: {e}" for e in getattr(source, "errors", [])]
    complete = not errors and len(rows) == total
    overall = _worst(plugin.verdict, *(r["verdict"] for r in rows))
    result = {"schema": VET_SCHEMA, "complete": complete,
              "source": f"{owner}/{repo}", "full_name": src.full_name,
              "ref": ref or src.default_branch, "commit": commit,
              "stars": meta.get("stargazers_count"), "archived": bool(meta.get("archived")),
              "repo_license": (lic.get("spdx_id") if isinstance(lic, dict) else "") or "",
              "verdict": overall, "tree_truncated": src.truncated, "also_ships": ships,
              "plugin": plugin.to_json(),
              "skills_found": total, "skills_vetted": len(rows), "skills": rows,
              "skill_errors": skill_errors, "skipped": src.skipped,
              "errors": errors, "notes": list(client.notes), "requests": client.requests}
    d = display
    lines = [f"vetted {len(rows)} of {total} skill(s) in {d(owner)}/{d(repo)} at {commit[:12]} "
             f"(ref {d(result['ref'], 80)}; {client.requests} API request(s)): {overall.upper()}"]
    if src.full_name and src.full_name.lower() != f"{owner}/{repo}".lower():
        lines.append(f"  GitHub's name for this repository: {d(src.full_name, 120)}")
    if result["archived"]:
        lines.append("  note: the repository is archived")
    if plugin.plugins or plugin.components or plugin.findings:
        lines.append(pluginvet.render(plugin))
    if not total:
        lines.append("  no SKILL.md found" + (f" under {d(under, 120)}" if under else ""))
    for r in rows:
        counts = ", ".join(f"{n} {s}" for s, n in sorted(r["counts"].items(), key=lambda kv:
                                                          -firewall.SEVERITY_ORDER[kv[0]])) or "no findings"
        lines.append(f"  {r['verdict'].upper():9s} {d(r['name'], 60):32s} "
                     f"licence {d(r['license'] or 'missing', 40):12s} {counts}")
        for f in r["findings"][:4]:
            where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            lines.append(f"      [{f['severity']}] {f['category']}/{f['rule']} {d(where, 100)} "
                         f"{d(f['evidence'], 80)}")
        if r["verdict"] == "blocked":
            continue
        if src.problems:
            lines.append("      no install command: this source failed a check (see the errors below), "
                         "and `skills install` refuses it")
        elif _installable_name(r["name"]):
            lines.append(f"      to install after reading it: repo-ai skills install {shell_word(r['name'])} "
                         f"--approve {shell_word(r['content_hash'][:16])} --online")
        else:
            lines.append("      no install command: its name is not a plain lowercase-hyphenated name "
                         "(a-z, 0-9, single hyphens, at most 64 characters), so it is neither "
                         "installable as it is nor safe to paste into a shell")
    for e in [*src.problems, *per_skill[:10]]:
        lines.append(f"  error: {d(e, 300)}")
    if len(per_skill) > 10:
        lines.append(f"  error: … and {len(per_skill) - 10} more skill error(s) (all are in --json output)")
    for e in summary:
        lines.append(f"  error: {d(e, 300)}")
    for n in client.notes:
        lines.append(f"  note: {d(n, 300)}")
    if complete:
        lines.append("  nothing was installed or executed. A clean result means no known problem, not "
                     "proof of safety.")
    else:
        lines.append(f"  INCOMPLETE: {len(rows)} of {total} skill(s) vetted"
                     + (" and the source failed a check" if src.problems else "")
                     + "; this is not a clean result. Nothing was installed or executed.")
    emit(result, "\n".join(lines))
    return 0 if complete else VET_INCOMPLETE


def _worst(*verdicts: str) -> str:
    order = ["blocked", "review", "eligible"]
    return next((v for v in order if v in verdicts), "eligible")


def _skill_summary(rows: list[dict], errors: list[str]) -> dict:
    return {"status": "partial" if errors else ("inspected" if rows else "none"), "skills": len(rows),
            "verdict": _worst(*(r["verdict"] for r in rows)) if rows else "none",
            "blocked": sum(r["verdict"] == "blocked" for r in rows),
            "review": sum(r["verdict"] == "review" for r in rows)}


def _vet_local(source: Path, existing: dict, emit) -> int:
    """Vet a local checkout (something a colleague sent, a clone you have not
    opened in Claude Code yet). Read-only: nothing is recorded or installed,
    and integrity is unverified because there is no pinned commit."""
    import tempfile

    from . import firewall, pluginvet
    source = source.resolve()
    rows: list[dict] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="repo-ai-vet-") as tmp:
        skill_dirs = sorted({p.parent for p in source.rglob("SKILL.md")
                             if ".git" not in p.parts and "node_modules" not in p.parts})[:200]
        # A skill without its own licence inherits the repository's, as the online path does with
        # GitHub's `license` field: a regular top-level LICENSE / COPYING file, read with a bound.
        repo_license = ""
        for f in sorted(source.iterdir()):
            if (f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING")) and not f.is_symlink()
                    and f.is_file()):
                try:
                    with f.open("rb") as fh:
                        repo_license = firewall._detect_license(fh.read(256 * 1024).decode("utf-8", "replace"))
                except OSError:
                    continue
                break
        for d in skill_dirs:
            rel = d.relative_to(source).as_posix() or "."
            try:
                dest, files, prior = firewall.quarantine_local(d, rel, store=Path(tmp))
            except (OSError, firewall.QuarantineError) as exc:
                errors.append(f"{rel}: {exc}")
                continue
            report = firewall.inspect(dest, files, {"id": f"local:{rel}", "name": d.name, "path": rel,
                                       "repo_license": repo_license},
                                      {k: v for k, v in existing.items() if k != d.name}, prior)
            rows.append({"name": d.name, "path": rel, "verdict": report.verdict, "license": report.license,
                         "content_hash": report.content_hash, "counts": report.counts(), "findings": [
                             f.to_json() for f in report.findings
                             if firewall.SEVERITY_ORDER[f.severity] >= firewall.SEVERITY_ORDER["medium"]][:12]})
    plugin = pluginvet.vet(pluginvet.LocalSource(source), skills=_skill_summary(rows, errors))
    verdict = _worst(plugin.verdict, *(r["verdict"] for r in rows))
    result = {"source": str(source), "verdict": verdict, "integrity": "local-unverified",
              "plugin": plugin.to_json(), "skills": rows, "errors": errors}
    from .textsafe import display as disp
    lines = [f"vetted {disp(source, 160)} (local, no pinned commit; {len(rows)} skill(s)): {verdict.upper()}"]
    for r in rows:
        counts = ", ".join(f"{n} {s}" for s, n in sorted(r["counts"].items(), key=lambda kv:
                                                          -firewall.SEVERITY_ORDER[kv[0]])) or "no findings"
        lines.append(f"  {r['verdict'].upper():9s} skill {disp(r['path'], 60):40s} {counts}")
        for f in r["findings"][:3]:
            lines.append(f"      [{f['severity']}] {f['category']}/{f['rule']} {disp(f['file'], 80)}:{f['line']} "
                         f"{disp(f['evidence'], 80)}")
    if plugin.plugins or plugin.components or plugin.findings:
        lines.append(pluginvet.render(plugin))
    for e in errors:
        lines.append(f"  error: {disp(e, 300)}")
    lines.append("  nothing was installed, recorded or executed. A clean result means no known problem, "
                 "not proof of safety.")
    return emit(result, "\n".join(lines))


def _desc_of(dest: Path) -> str:
    import re as _re
    try:
        text = (dest / "files" / "SKILL.md").read_text("utf-8", errors="replace")
    except OSError:
        return ""
    m = _re.search(r"(?m)^description:\s*(.+)$", text)
    return (m.group(1).strip().strip('"') if m else "")[:1024]


def _radar_cache_dir() -> Path:
    from .registry import registry_home
    return registry_home() / "radar-cache"


def _skill_benchmark(args, root, cfg, layout, state, find) -> int:
    """Controlled trials through the coding lab, on the exact pinned content.

    benchmark <name>:        full repo-ai without it vs with it.
    tournament <a> <b> ...:  one arm per candidate against the same control,
                             same tasks; a winner only on significant evidence.
    """
    from . import coding_lab as lab
    from . import evals, portfolio
    from .fsutil import atomic_write
    names = list(dict.fromkeys(args.names))
    if args.action == "benchmark" and len(names) != 1:
        raise SystemExit("error: repo-ai skills benchmark <name>")
    if args.action == "tournament" and len(names) < 2:
        raise SystemExit("error: repo-ai skills tournament <a> <b> [more...]")
    lock = portfolio.load_lock(root)
    missing = [n for n in names if n not in lock["skills"]]
    if missing:
        raise SystemExit(f"error: {', '.join(missing)} must be approved and installed first (trials "
                         "use the exact pinned content)")
    tmp_lock = layout.state_dir / f"trial-{'-'.join(names)[:80]}.lock.json"
    atomic_write(tmp_lock, json.dumps({"version": 1, "skills": {n: lock["skills"][n] for n in names}}))
    os.environ["REPO_AI_LAB_SKILLS_LOCK"] = str(tmp_lock)
    suite = evals.default_suite_dir()
    bases, tasks = evals.load_suite(suite)
    tasks = evals.select_tasks(tasks, args.trial_tasks, args.trial_max_tasks or 6, 0,
                               "all" if args.trial_tasks else "holdout")
    if not tasks:
        raise SystemExit("error: no trial tasks selected (check --trial-tasks)")
    without = lab.Arm("without", lab.ARM_FEATURES["full"] - {"thirdparty"})
    arm_of = {n: ("with" if args.action == "benchmark" else f"with-{n}") for n in names}
    arms = [without] + [lab.Arm(arm_of[n], lab.ARM_FEATURES["full"], (n,)) for n in names]
    fake = bool(args.trial_fake)
    if fake and (not args.trial_claude_cmd or shlex.split(args.trial_claude_cmd)[0] == "claude"):
        # a "fake" run of the real client would skip the budget, config audit and preflight
        raise SystemExit("error: --trial-fake needs --trial-claude-cmd naming the fake client")
    opts = lab.LabOptions(arms=arms, max_cost_usd=args.max_cost_usd or 0.0,
                          max_cost_per_run=args.max_cost_per_run or 0.5, fake=fake,
                          claude_cmd=shlex.split(args.trial_claude_cmd or cfg.claude_cmd,
                                                 posix=os.name != "nt"),
                          dry_run=args.dry_run)
    meta = lab.run_experiment(suite, tasks, bases, opts, log=(lambda *_: None) if args.json else print)
    if args.dry_run:
        print(json.dumps(meta, indent=2) if args.json else
              f"trial plan for {', '.join(names)}: {meta['planned_runs']} runs, worst case "
              f"${meta['worst_case_usd']}")
        return 0
    _, runs = lab.load_runs(meta["id"])
    valid = [r for r in runs if r.get("valid")]
    results = {}
    for n in names:
        arm = arm_of[n]
        # explicit direction: positive diff = the candidate helps
        comp: dict = lab.compare_arms(valid, "without", arm, 0)
        status = "fake" if fake else ("pilot" if comp.get("pairs", 0) < 10 else "evaluated")
        with_runs = [r for r in valid if r["arm"] == arm]
        invoked = sum(1 for r in with_runs if n in (r.get("skills_invoked") or []))
        costs = [r["reported_cost_usd"] for r in with_runs if r.get("reported_cost_usd") is not None]
        evidence = {"status": status, "experiment": meta["id"], "verdict": comp.get("verdict"),
                    "pairs": comp.get("pairs"), "diff": comp.get("diff"),
                    "success_rate": round(sum(1 for r in with_runs if r.get("success")) / len(with_runs), 3)
                    if with_runs else None,
                    "mean_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
                    "invocation_rate": round(invoked / len(with_runs), 3) if with_runs else None}
        portfolio.record_trial(root, n, evidence)
        state.setdefault("trials", {})[n] = evidence
        results[n] = evidence
    if args.action == "benchmark":
        ev = results[names[0]]
        print(json.dumps(ev, indent=2) if args.json else
              f"trial {meta['id']} for {names[0]}: {ev['verdict']} (pairs {ev['pairs']}, status "
              f"{ev['status']}; invocation rate {ev['invocation_rate']})")
        return 0
    ranking = sorted(names, key=lambda n: (-(results[n]["diff"] or 0), -(results[n]["success_rate"] or 0),
                                           results[n]["mean_cost_usd"] or 0, n))
    leader = results[ranking[0]]
    significant = leader["status"] == "evaluated" and "better" in str(leader["verdict"]) \
        and "not significant" not in str(leader["verdict"])
    out = {"experiment": meta["id"], "ranking": ranking, "results": results,
           "winner": ranking[0] if significant else None,
           "conclusion": f"{ranking[0]} is significantly better than no skill" if significant else
           "no winner: no candidate was significantly better than the control "
           "(a small sample is directional only)"}
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"skill tournament {meta['id']} ({len(tasks)} tasks, control = full repo-ai without them):")
    for i, n in enumerate(ranking, 1):
        r = results[n]
        print(f"  {i}. {n}: success {r['success_rate']}, diff {r['diff']} vs control, "
              f"{r['verdict']} (pairs {r['pairs']}, {r['status']}), invoked {r['invocation_rate']}")
    print(f"  {out['conclusion']}")
    return 0


def _skill_texts(root: Path) -> dict[str, str]:
    out = {}
    skills_dir = root / ".claude" / "skills"
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []:
        out[skill_md.parent.name] = skill_md.read_text("utf-8", errors="replace")
    return out


def _skills_lifecycle(args, root, cfg, layout, action: str) -> int:
    from . import skills, skills_lab
    from .episodes import load_all, skill_outcomes
    from .fsutil import read_text

    index = require_index(layout)
    try:
        facts_obj = _facts_obj(layout)
        specs = {s.name: s for s in skills.discover(
            root, layout, facts_obj, index,
            signals=cfg.learning_signals in ("known-commands", "outcomes"))} if facts_obj else {}
    finally:
        index.close()
    facts = load_facts(layout)
    state = skills.SkillState.load(layout)
    on_disk = _skill_texts(root)
    names = list(args.names) or (sorted(set(specs) | {n for n in on_disk if n.startswith("repo-")})
                                 if action in {"test", "diff"} else [])
    if not names:
        raise SystemExit(f"error: name the skill: repo-ai skills {action} <name>")
    rc = 0
    for name in names:
        spec = specs.get(name)
        if action == "propose":
            if spec is None:
                raise SystemExit(f"error: no candidate named {name!r} (see `repo-ai skills discover`)")
            report = skills.validate(spec, root)
            print(spec.render(), end="")
            print(f"\n# proposed by repo-ai: risk={spec.risk}, confidence={spec.confidence:.2f}, "
                  f"valid={'yes' if report.ok else 'no: ' + '; '.join(report.errors)}")
            print(f"# evidence: {', '.join(e.pointer() for e in spec.evidence[:6])}")
            print(f"# activate: repo-ai skills promote {name}   (nothing was written)")
        elif action == "test":
            text = on_disk.get(name) or (spec.render() if spec else None)
            if text is None:
                print(f"  {name}: not found")
                rc = 1
                continue
            result = skills_lab.test_skill(root, name, text, facts, on_disk)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"  [{'ok' if result['ok'] else 'FAIL'}] /{name}  ~{result['body_tokens_est']} "
                      f"tokens, description ~{result['description_tokens_est']}; Claude validator: "
                      f"{result['claude_validator']}")
                for p in result["problems"]:
                    print(f"      problem: {p}")
                if result["closest"]:
                    print("      closest: " + ", ".join(f"/{c['skill']} ({c['overlap']})"
                                                       for c in result["closest"]))
                print(f"      ({result['method']})")
            rc = rc or (0 if result["ok"] else 1)
        elif action == "diff":
            current = read_text(root / ".claude" / "skills" / name / "SKILL.md")
            proposed = spec.render() if spec else None
            out = skills_lab.diff_text(name, current, proposed)
            if out:
                sys.stdout.write(out)
            else:
                print(f"  {name}: no difference between disk and what repo-ai would write")
        elif action == "disable":
            print(skills.rollback(layout, name))
            rc = rc or _run_update(args, incremental=True)
        elif action == "canary":
            entry = state.entries.get(name, {})
            versions: dict[int, str] = {}
            for h in entry.get("history", []):
                if h.get("body") and h.get("version"):
                    tmp = skills.SkillSpec(name, entry.get("description", ""), h["body"],
                                           entry.get("risk", "safe"))
                    versions[int(h["version"])] = tmp.render()
            if entry.get("body"):
                versions[int(entry.get("version", 1))] = skills.SkillSpec(
                    name, entry.get("description", ""), entry["body"], entry.get("risk", "safe")).render()
            result = skills_lab.canary(name, versions, skill_outcomes(load_all(layout)), root,
                                       facts, on_disk)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"  canary /{name}: {result['decision']}")
                for row in result.get("versions", []):
                    print(f"    v{row['version']}: static {'ok' if row['static_ok'] else 'FAIL'}, "
                          f"~{row['tokens_est']} tokens, {row['sessions']} sessions, verified "
                          f"rate {row['verified_rate']}")
                if result.get("note"):
                    print(f"    note: {result['note']}")
            if result.get("retire_version") and args.apply:
                hist = [h for h in entry.get("history", []) if h.get("version") != result["retire_version"]]
                if result["retire_version"] == entry.get("version") and hist:
                    entry["pinned"] = {"version": hist[-1]["version"], "body": hist[-1]["body"]}
                entry["history"] = hist
                state.save()
                print(f"    retired v{result['retire_version']}; run `repo-ai update` to rewrite")
        elif action == "draft":
            from .registry import llm_allowed
            if spec is None:
                raise SystemExit(f"error: no candidate named {name!r} to draft from")
            if cfg.skills_llm != "on":
                raise SystemExit('error: Tier-2 drafting is off. It sends minimized, redacted '
                                 'evidence (commands, paths, counts; no file contents) to Claude '
                                 'Code and is billable. Enable it with skills_llm = "on".')
            ok, why = llm_allowed(root)
            if not ok:
                raise SystemExit(f"error: {why}")
            if args.dry_run:
                print(skills_lab.draft_prompt(skills_lab.draft_evidence(spec, facts)))
                print("\n# dry run: this is exactly what would be sent; nothing was sent")
                continue
            if args.max_cost_usd is None or args.max_cost_usd <= 0:
                raise SystemExit("error: drafting needs an explicit, positive --max-cost-usd "
                                 "(billable)")
            result = skills_lab.run_draft(spec, facts, claude_cmd=cfg.claude_cmd,
                                          max_cost_usd=args.max_cost_usd)
            if not result.get("ok"):
                print(f"  draft failed: {result.get('error') or 'empty result'}")
                rc = 1
                continue
            drafted = skills.SkillSpec(name, spec.description, result["body"], spec.risk,
                                       spec.evidence, spec.confidence, "Tier-2 draft (untrusted)",
                                       spec.argument_hint)
            test = skills_lab.test_skill(root, name, drafted.render(), facts, on_disk)
            entry = state.entries.setdefault(name, {})
            entry["draft"] = {"body": drafted.body, "ok": test["ok"], "problems": test["problems"],
                              "reported_cost_usd": result.get("reported_cost_usd")}
            state.save()
            print(skills_lab.diff_text(name, spec.render(), drafted.render()) or "  (no change)")
            print(f"  draft stored as untrusted ({'passes' if test['ok'] else 'FAILS'} static tests; "
                  f"reported cost ${result.get('reported_cost_usd')}). Not active: review, then "
                  "repo-ai skills promote <name> --draft")
    return rc


# --------------------------------------------------------------------------
# workflows, registry, cross-repo
# --------------------------------------------------------------------------
def cmd_workflow(args: argparse.Namespace) -> int:
    from . import workflows

    root, cfg, layout = open_workspace(args)
    index = require_index(layout)
    try:
        books = workflows.compile_all(root, layout, load_facts(layout), index)
    finally:
        index.close()
    if args.action == "list" or not args.name:
        if args.json:
            print(json.dumps([b.to_json() for b in books], indent=2))
            return 0
        if not books:
            print("no workflows yet: they come from >= 3 verified sessions with the same edit areas "
                  "and checks (learning_signals = \"outcomes\"), or from structural evidence.")
            return 0
        for book in books:
            print(f"  {book.name:28s} [{book.source}] {book.title}")
        print("\n  preview: repo-ai workflow plan <name>   (read-only; repo-ai never executes playbooks)")
        return 0
    found = next((b for b in books if b.name == args.name), None)
    if found is None:
        raise SystemExit(f"error: no workflow named {args.name!r} (repo-ai workflow list)")
    book = found
    book.verified = workflows.verify(root, book, load_facts(layout))
    if args.json:
        print(json.dumps(book.to_json(), indent=2))
    else:
        print(workflows.render_plan(book))
    return 0 if book.verified.get("ok") else 1


def cmd_pack(args: argparse.Namespace) -> int:
    """Stack Packs from this repository's zone (never another zone)."""
    from . import learning, registry, stackpacks
    from .portfolio import load_lock

    root, cfg, layout = open_workspace(args)
    zone = registry.zone_of(root)
    if zone in (None, "!conflict"):
        raise SystemExit("error: Stack Packs come from a zone: repo-ai registry add --zone <zone>, then "
                         "`repo-ai registry contribute` in each repository of that zone")
    packs = stackpacks.build(zone)
    ranked = stackpacks.match(packs, load_facts(layout))
    if args.action == "list":
        rows = [{"id": p["id"], "match": s, "repos": p["repos"], "rules": len(p["rules"]),
                 "skills": len(p["skills"]), "thirdparty": len(p["thirdparty"])} for s, p in ranked]
        if args.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print(f"no Stack Packs for this stack in zone {zone} (a pack needs "
                  f"{stackpacks.MIN_SUPPORT}+ contributing repositories of the same stack)")
        else:
            print(f"Stack Packs in zone {zone} (best match first):")
            for r in rows:
                print(f"  {r['id']}: {r['repos']} repos; {r['rules']} rules, {r['skills']} skills, "
                      f"{r['thirdparty']} third-party skills (match {r['match']})")
        return 0
    by_id = {p["id"]: p for p in packs}
    pack = by_id.get(args.pack) if args.pack else (ranked[0][1] if ranked else None)
    if pack is None:
        raise SystemExit(f"error: no pack {args.pack!r} in zone {zone}" if args.pack else
                         "error: no Stack Pack matches this repository's stack")
    if args.action == "show":
        print(json.dumps(pack, indent=2))
        return 0
    ledger = learning.Ledger.load(layout)
    out = stackpacks.plan(root, pack, [r.to_json() for r in ledger.active()], set(_skill_texts(root)),
                          load_lock(root))
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"Stack Pack {out['pack']} ({out['repos']} repositories) for {root.name}:")
    for i in out["items"]:
        print(f"  [{i['status']}] {i['type']} {i['item']} (in {i['support']} repos)"
              + (f"\n      next: {i['next']}" if i["next"] else ""))
    print(f"  {out['note']}")
    return 0


def cmd_registry(args: argparse.Namespace) -> int:
    from . import registry

    if args.action == "audit":
        report = registry.audit()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"registry: {report['home']}")
            for z in report["zones"]:
                print(f"  zone {z['zone']}: {z['repos']} repo(s), {z['patterns']} pattern(s), "
                      f"policy {z['policy']}" + (f", {z['missing_paths']} missing path(s)"
                                                 if z["missing_paths"] else ""))
            for p in report["problems"]:
                print(f"  PROBLEM: {p}")
            print("  result: " + ("PASS" if not report["problems"] else "FAIL"))
        return 1 if report["problems"] else 0
    if args.action == "list":
        rows = {z: registry.members(z) for z in registry.zones()}
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("no repositories registered (cross-repo features are opt-in: "
                  "repo-ai registry add --zone personal|work|<name>)")
        for zone, members in rows.items():
            print(f"zone {zone}:")
            for m in members:
                state = "" if m["exists"] else " (missing)"
                print(f"  {m['label']:24s} {m['path']}{state}")
        return 0
    if args.action == "purge":
        if not args.zone:
            raise SystemExit("error: --zone is required for purge")
        print(f"zone {args.zone} purged." if registry.purge(args.zone) else f"no zone {args.zone}.")
        return 0
    if args.action == "policy":
        if not (args.zone and args.set):
            raise SystemExit("error: usage: repo-ai registry policy --zone Z --set llm=allow|deny")
        key, _, value = args.set.partition("=")
        print(json.dumps(registry.set_policy(args.zone, key, value)))
        return 0
    root = resolve_root(args.path)
    if args.action == "add":
        if not args.zone:
            raise SystemExit("error: choose a zone explicitly (--zone personal|work|<name>); "
                             "zones never share data")
        zone = registry.add(root, args.zone, args.label, move=args.move)
        print(f"registered {root.name} in zone {zone}. Only repositories in this zone are searched "
              "by `repo-ai crossrepo`.")
        return 0
    if args.action == "remove":
        removed_from = registry.remove(root)
        print(f"removed from zone {removed_from}." if removed_from else "not registered.")
        return 0
    if args.action == "inspect":
        zone_name, policy = registry.policy_for(root)
        out = {"zone": zone_name, "policy": policy, "peers": registry.peers(root)[1]}
        print(json.dumps(out, indent=2))
        return 0
    if args.action == "contribute":
        root, cfg, layout = open_workspace(args)
        from . import episodes, learning
        ledger = learning.Ledger.load(layout)
        from .portfolio import load_lock
        result = registry.contribute(
            root, load_facts(layout), [r.to_json() for r in ledger.active()],
            [n for n in _skill_texts(root) if n.startswith("repo-")],
            episodes.stats(episodes.load_all(layout)),
            [{"name": n, **e} for n, e in load_lock(root)["skills"].items()])
        print(json.dumps(result, indent=2))
        return 0
    if args.action == "suggest":
        root, cfg, layout = open_workspace(args)
        print(json.dumps(registry.suggest(root, load_facts(layout)), indent=2))
        return 0
    return 2


def cmd_crossrepo(args: argparse.Namespace) -> int:
    from . import registry

    root, cfg, layout = open_workspace(args)
    if args.action == "context":
        out = registry.crossrepo_context(root, " ".join(args.task or []))
    else:
        index = require_index(layout)
        try:
            out = registry.crossrepo_impact(root, index)
        finally:
            index.close()
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    if out["zone"] in (None, "!conflict"):
        print("this repository is not registered in a zone; cross-repo features are opt-in "
              "(repo-ai registry add --zone <zone>).")
        return 0
    print(f"zone {out['zone']}: searched {out['searched']} other repositor"
          f"{'y' if out['searched'] == 1 else 'ies'}")
    for res in out.get("results", []):
        print(f"  {res['repo']} ({res['confidence']}):")
        for f in res["files"]:
            print(f"    {f['path']} — {'; '.join(f['why'])}")
    for link in out.get("links", []):
        mark = "" if link["proof"] == "manifest" else f" [{link['proof']}]"
        print(f"  {link['repo']}: {link['kind']} {link['target']}{mark} — {link['evidence']}")
    if not out.get("results") and not out.get("links"):
        print("  nothing found in this zone.")
    return 0


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    import shutil
    import subprocess
    import time

    from .adapters import ADAPTERS, Check, SetupContext, ordered
    from .fsutil import Plan
    from .gitinfo import is_git_repo
    from .index import IndexTooNew, SCHEMA_VERSION, open_index
    from .parser import tree_sitter_available
    from .workspace import CONTEXT_FILES, recorded_agents

    root, cfg, layout = open_workspace(args, extra={"quiet": True} if args.json else None)
    checks: list[Check] = []

    def add(label, status, detail="", fix=""):
        checks.append(Check(label, status, detail, fix))

    add("python", "ok", sys.version.split()[0])
    exe = shutil.which("repo-ai")
    if exe:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15,
                                 check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        same = out.endswith(__version__)
        add("repo-ai on PATH", "ok" if same else "warn", f"{exe} ({out or '?'})",
            "" if same else "the PATH binary differs from this one; reinstall the tool")
    else:
        add("repo-ai on PATH", "fail" if (recorded_agents(root, cfg, layout) or ()) else "warn",
            "hooks call `repo-ai` by name and do nothing without it",
            "pipx install <repo-ai source>  (see README)")
    add("git repository", "ok" if is_git_repo(root) else "warn",
        "" if is_git_repo(root) else "recency, hotspots and co-change ranking need git")
    if cfg.extra.get("_untrusted_keys_ignored"):
        add("config keys from the repository", "warn", "ignored (only your own config, "
            "REPO_AI_* environment or CLI flags may set them): "
            + ", ".join(sorted(set(cfg.extra["_untrusted_keys_ignored"]))),
            "set them in ~/.config/repo-ai/config.toml if you trust this repository")
    if cfg.extra.get("_config_parse_errors"):
        add("config files", "fail", "not valid TOML, so ignored entirely: "
            + "; ".join(cfg.extra["_config_parse_errors"]),
            "fix the file (Windows paths: use 'single quotes' or forward slashes)")
    if cfg.extra.get("_bad_config_keys"):
        add("config values", "fail", "invalid: " + ", ".join(cfg.extra["_bad_config_keys"]),
            "fix the value in .repo-ai/config.toml")
    if cfg.extra.get("_retired_config_keys"):
        add("config keys", "info", "ignored (retired): " + ", ".join(cfg.extra["_retired_config_keys"]))

    add("layout", "info", f"{layout.kind}: context {layout.context_rel}/, state {layout.state_rel}/")
    if layout.index_path.is_file():
        try:
            index = open_index(layout.state_dir)
            stats = index.stats()
            schema = index.get_meta("schema_version")
            index.close()
            add("index", "ok", f"schema v{schema}/{SCHEMA_VERSION}, {stats['files']} files, "
                f"{stats['symbols']} symbols, {stats['test_links']} test links")
            if stats["symbols"] == 0 and stats["files"] > 0:
                add("symbols extracted", "fail", "no symbols — check language support")
        except IndexTooNew as exc:
            add("index", "fail", str(exc), "upgrade repo-ai or `repo-ai rebuild`")
    else:
        add("index", "fail", f"missing {layout.rel(layout.index_path)}",
            "repo-ai init --agent claude (or --agent none for verify only)")
    missing_docs = [n for n in CONTEXT_FILES if not (layout.context_dir / n).is_file()]
    add("generated docs", "ok" if not missing_docs else "fail",
        "all present" if not missing_docs else "missing " + ", ".join(missing_docs), "repo-ai update")
    from .fsutil import self_argv
    status = subprocess.run(self_argv("status", "-C", str(root), "--json"),
                            capture_output=True, text=True, check=False, timeout=60)
    if status.returncode in (0, 2):
        try:
            data = json.loads(status.stdout)
            add("freshness", "ok" if not data.get("stale") else "warn",
                "current" if not data.get("stale") else f"{len(data.get('drift', []))} changed file(s)",
                "repo-ai update")
        except ValueError:
            pass
    add("tree-sitter", "info", "installed" if tree_sitter_available()
        else "not installed — regex fallback for non-Python symbols (`pip install 'repo-ai-cli[ast]'`; with pipx: "
        "`pipx inject repo-ai-cli 'tree-sitter>=0.23' 'tree-sitter-language-pack>=0.7,<1.0'`)")

    configured = recorded_agents(root, cfg, layout) or ()
    wanted = configured if args.agent in (None, "all") else (args.agent,)
    ctx = SetupContext(root=root, cfg=cfg, layout=layout, agents=tuple(configured), plan=Plan(root))
    for name in ordered(wanted):
        if name not in configured:
            add(f"{name} adapter", "fail", "not configured for this repository",
                f"repo-ai init --agent {name}")
        for check in ADAPTERS[name].doctor(ctx):
            check.label = f"{name}: {check.label}"
            checks.append(check)
    if "claude" in wanted and exe and layout.index_path.is_file():
        probe = "where is the main entrypoint of this project"
        try:
            index = open_index(layout.state_dir)
            row = index.conn.execute(
                "SELECT s.name FROM symbols s JOIN files f ON f.path = s.path "
                "WHERE f.role = 'source' AND length(s.name) >= 6 ORDER BY s.path, s.line LIMIT 1"
            ).fetchone()
            index.close()
            if row:
                probe = f"change how {row['name']} works and update its tests"
        except Exception:
            pass
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "doctor",
                              "cwd": str(root), "prompt": probe})
        started = time.perf_counter()
        try:
            proc = subprocess.run([exe, "hook", "claude", "prompt"], input=payload, text=True,
                                  capture_output=True, timeout=15, check=False,
                                  env={**os.environ, "CLAUDE_PROJECT_DIR": str(root),
                                       "REPO_AI_NO_BACKGROUND": "1"})
            elapsed = (time.perf_counter() - started) * 1000
            ok_json = not proc.stdout.strip() or "hookSpecificOutput" in proc.stdout
            add("claude: prompt hook round-trip", "ok" if proc.returncode == 0 and ok_json and elapsed < 1500
                else "warn", f"{elapsed:.0f} ms, exit {proc.returncode}, {len(proc.stdout)} chars")
        except (OSError, subprocess.SubprocessError) as exc:
            add("claude: prompt hook round-trip", "fail", str(exc))

    if args.json:
        print(json.dumps([c.to_json() for c in checks], indent=2))
    else:
        print(f"repo-ai {__version__}   repository: {root}\n")
        for check in checks:
            mark = {"ok": "ok  ", "warn": "warn", "fail": "FAIL", "info": "info"}[check.status]
            line = f"  [{mark}] {check.label}" + (f" — {check.detail}" if check.detail else "")
            print(line)
            if check.fix and check.status in {"fail", "warn"}:
                print(f"         fix: {check.fix}")
        failed = sum(1 for c in checks if c.status == "fail")
        print("\n" + ("all checks passed" if not failed else f"{failed} check(s) failed — see above"))
    return 1 if any(c.status == "fail" for c in checks) else 0


# --------------------------------------------------------------------------
# uninstall
# --------------------------------------------------------------------------
def cmd_uninstall(args: argparse.Namespace) -> int:
    from .index import open_index
    from .workspace import plan_uninstall, recorded_agents

    root, cfg, layout = open_workspace(args)
    configured = recorded_agents(root, cfg, layout)
    configured = tuple(configured) if configured is not None else ("bob",)
    remove: tuple[str, ...]
    configured_after: tuple[str, ...]
    if args.agent in (None, "all"):
        remove = ("bob", "claude")  # also cleans up anything left behind
        configured_after = ()
    else:
        remove = (args.agent,)
        configured_after = tuple(a for a in configured if a != args.agent)
    plan, remaining = plan_uninstall(root, cfg, layout, remove,
                                     configured if args.agent not in (None, "all") else remove)
    if args.dry_run or args.diff:
        print(f"  dry run — nothing was removed. removing: {', '.join(remove)}; "
              f"remaining agents: {', '.join(remaining) or 'none (repo-ai data removed too)'}")
        for line in plan.summary_lines():
            print("  " + line)
        if args.diff:
            sys.stdout.write(plan.diff())
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("error: refusing to uninstall without confirmation; pass -y "
                             "(or --dry-run to preview)")
        print("this will:")
        for line in plan.summary_lines():
            print("  " + line)
        if input("proceed? [y/N] ").strip().lower() not in {"y", "yes"}:
            return 1
    plan.apply(layout.backup_dir if remaining else None)
    if remaining and layout.index_path.is_file():
        index = open_index(layout.state_dir)
        try:
            index.set_meta("agents", json.dumps(list(configured_after)))
            index.set_meta("wire_bob", "1" if "bob" in configured_after else "0")
        finally:
            index.close()
    for path, reason in plan.skipped:
        print(f"  kept {plan.rel(path)} ({reason})")
    if not remaining:
        from .capabilities import forget
        for gone in forget(root):
            print(f"  removed capability approvals {gone}")
    print("repo-ai removed." if not remaining else f"removed {', '.join(remove)}; "
          f"still configured: {', '.join(remaining)}")
    return 0


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------
def cmd_debug(args: argparse.Namespace) -> int:
    from . import flight

    root, cfg, layout = open_workspace(args)
    if args.action == "purge":
        print("flight recorder log deleted." if flight.purge(layout) else "nothing recorded.")
        return 0
    rows = flight.entries(layout, args.n)
    if args.json:
        sys.stdout.write(json.dumps(rows, indent=2) + "\n")
        return 0
    if not rows:
        state = "on" if cfg.flight_recorder else "off"
        print(f"no recorded hook decisions (flight recorder is {state}). Turn it on for one "
              "session with REPO_AI_FLIGHT_RECORDER=1 claude, or set flight_recorder = true "
              "in .repo-ai/config.toml. Prompts are never stored, only a hash and length.")
        return 0
    print("\n\n".join(flight.render(r) for r in rows))
    return 0


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def cmd_eval(args: argparse.Namespace) -> int:
    from . import evals

    if args.action:
        return cmd_eval_lab(args)
    suite = Path(args.suite) if args.suite else evals.default_suite_dir()
    bases, tasks = evals.load_suite(suite)
    tasks = evals.select_tasks(tasks, args.tasks, args.max_tasks, args.seed, args.split)
    if args.live:
        if args.no_network:
            raise SystemExit("error: --live runs Claude Code, which needs the network; "
                             "drop --no-network or run offline")
        if not args.dry_run and not args.fake and (args.max_cost_usd is None or args.max_cost_usd <= 0):
            raise SystemExit("error: --live requires an explicit, positive --max-cost-usd budget "
                             "(Claude usage is billable; nothing has been run)")
        # The paired A/B now runs in the coding lab: sandboxed grading (refused
        # when no sandbox exists), settings preflight, isolation checks, budget
        # gating. The old host-side runner executed model-written tests unsandboxed.
        if not args.quiet:
            print("note: `eval --live` runs `eval coding --compare baseline,full` (sandboxed)")
        args.action, args.compare = "coding", "baseline,full"
        return cmd_eval_lab(args)
    else:
        if args.dry_run:
            print(f"repo-ai eval --offline (dry run): {len(tasks)} tasks from {suite}")
            for task in tasks:
                print(f"  {task.id}  [{task.language}/{task.category}/{task.difficulty}]")
            return 0
        report = evals.run_offline(suite, tasks, bases, validate=not args.no_validate,
                                   localization=not args.no_localization,
                                   concurrency=args.concurrency)
        text = evals.render_offline(report)
    if args.out:
        Path(args.out).write_text(evals.to_json(report), encoding="utf-8")
    if args.format == "json":
        sys.stdout.write(evals.to_json(report))
    else:
        print(text)
    problems: list[str] = []
    if not args.live:
        problems += [f"invalid task {r['id']}" for r in report.get("validation", {}).get("invalid", [])]
        if args.check:
            baseline = json.loads(Path(args.check).read_text("utf-8"))
            problems += evals.compare_offline(report, baseline)
    for problem in problems:
        print(f"  GATE FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


def cmd_sandbox(args: argparse.Namespace) -> int:
    from . import sandbox

    if args.action == "pull":
        backend = sandbox.get_backend("auto")
        if not isinstance(backend, sandbox.ContainerBackend):
            print(f"{backend.name} uses host toolchains; nothing to pull")
            return 0
        ok = all(backend.pull(tc) for tc in (args.toolchain or list(sandbox.DEFAULT_IMAGES)))
        return 0 if ok else 1
    rows = sandbox.status()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        mark = "available" if row["available"] else "unavailable"
        print(f"  {row['backend']:9s} {mark:11s} {row['detail']}")
        for tc, img in (row.get("images") or {}).items():
            state = img["digest"][:19] if img["present"] else "not pulled (repo-ai sandbox pull)"
            print(f"            {tc:7s} {img['image']}  {state}")
    try:
        chosen = sandbox.get_backend("auto", toolchain="python")
        print(f"  untrusted code will run in: {chosen.name}")
    except sandbox.SandboxUnavailable:
        print("  no sandbox available: untrusted code will NOT run (static inspection only)")
    return 0


def cmd_eval_lab(args: argparse.Namespace) -> int:
    """`repo-ai eval coding|report|compare|regressions|ablate|list`."""
    from . import coding_lab as lab
    from . import evals

    action = args.action
    if action == "list":
        rows = lab.list_experiments()
        if args.format == "json":
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("no coding experiments recorded yet (repo-ai eval coding --pilot --dry-run)")
        for r in rows:
            kind = "FAKE" if r.get("fake") else "live"
            print(f"  {r['id']}  [{kind}] arms {', '.join(r['arms'])}  {r['runs_recorded']}/"
                  f"{r['planned_runs']} runs  ${r.get('spent_usd_charged', 0):.2f}")
        return 0
    if action in {"report", "regressions"}:
        exp = (args.targets or [None])[0] or (lab.list_experiments() or [{}])[-1].get("id")
        if not exp:
            raise SystemExit("error: no experiments recorded yet")
        meta, runs = lab.load_runs(exp)
        if action == "regressions":
            a, b = (args.targets[1:3] + ["baseline", "full"])[:2] if len(args.targets) > 1 \
                else ("baseline", "full")
            out = lab.regressions(runs, a, b)
            if args.format == "json":
                print(json.dumps(out, indent=2))
            else:
                print(f"regressions in {meta['id']} ({b} failed where {a} passed): {len(out)}")
                for item in out:
                    print(f"  {item['task']} (rep {item['rep']}): " + "; ".join(item["signals"]))
            return 0
        summary = lab.summarize(runs, meta.get("seed", 0))
        if args.format == "json":
            print(json.dumps({"experiment": meta, "summary": summary}, indent=2))
        else:
            sys.stdout.write(lab.render_report(meta, summary))
        return 0
    if action == "compare":
        if len(args.targets) != 2:
            raise SystemExit("error: usage: repo-ai eval compare <experiment-a> <experiment-b>")
        compared: dict[str, dict] = {}
        for exp in args.targets:
            meta, runs = lab.load_runs(exp)
            compared[meta["id"]] = lab.summarize(runs, meta.get("seed", 0))["arms"]
        if args.format == "json":
            print(json.dumps(compared, indent=2))
        else:
            for exp_id, arm_rows in compared.items():
                print(f"{exp_id}: " + "; ".join(f"{a} success {v['success_rate']} (n={v['n']})"
                                                for a, v in arm_rows.items()))
        return 0
    # coding / ablate
    suite = Path(args.suite) if args.suite else evals.default_suite_dir()
    bases, tasks = evals.load_suite(suite)
    split = args.split if args.split != "all" or not args.pilot else "holdout"
    if split in evals.ANALYZED_SPLITS:
        print(f"note: the `{split}` split was {evals.ANALYZED_SPLITS[split]}.", file=sys.stderr)
    tasks = evals.select_tasks(tasks, args.tasks, args.max_tasks or (6 if args.pilot else None),
                               args.seed, split)
    if args.task_order == "interleave":  # every prefix spread across the bases (budget stops)
        tasks = lab.interleave_by_base(tasks, args.seed)
    arms = lab.make_arms([a.strip() for a in args.compare.split(",") if a.strip()],
                         ablate=args.feature if action == "ablate" else None)
    if args.pilot:
        args.repeat = 1
    fake = args.claude_cmd != "claude" and args.fake
    opts = lab.LabOptions(
        arms=arms, max_cost_usd=args.max_cost_usd or 0.0, max_cost_per_run=args.max_cost_per_run,
        max_turns=args.max_turns, timeout_s=args.timeout, model=args.model, effort=args.effort,
        seed=args.seed, repeat=args.repeat,
        claude_cmd=shlex.split(args.claude_cmd, posix=os.name != "nt"),
        config_dir=Path(args.claude_config) if args.claude_config else None,
        results_dir=Path(args.results) if args.results else None,
        keep_workspaces=args.keep_artifacts, dry_run=args.dry_run, fake=fake, blind=args.blind,
        reserve_per_run=args.reserve_per_run, task_order=args.task_order,
        grading_backend=args.sandbox)
    meta = lab.run_experiment(suite, tasks, bases, opts, resume=args.resume,
                              log=(lambda *_: None) if args.quiet else print)
    if args.dry_run:
        if args.format == "json":
            print(json.dumps(meta, indent=2))
        else:
            print(f"repo-ai eval coding (dry run): {meta['planned_runs']} runs "
                  f"({len(tasks)} tasks × {len(arms)} arms × {args.repeat}); per-run cap "
                  f"${opts.max_cost_per_run:.2f}, reservation ${meta['reservation_per_run_usd']:.2f}; "
                  f"guaranteed-completion budget ${meta['completion_budget_usd']:.2f} against a "
                  f"${opts.max_cost_usd:.2f} budget")
            if opts.max_cost_usd + 1e-9 < meta["completion_budget_usd"]:
                print("  note: the budget is below the guaranteed-completion budget; the run may stop "
                      "at a budget stop before every task is attempted")
            print("  arms: " + "; ".join(f"{a}=[{', '.join(f) or 'plain Claude'}]"
                                         for a, f in meta["arms"].items()))
            print(f"  tasks ({meta['task_order']} order): " + ", ".join(meta["tasks"]))
            if meta.get("missing_toolchains"):
                print("  toolchain MISSING (a live run is refused): " + "; ".join(
                    f"{t}: {', '.join(v)}" for t, v in meta["missing_toolchains"].items()))
            problems = lab.audit_config_dir(opts.config_dir or lab.eval_config_dir())
            print("  eval config dir: " + (str(opts.config_dir or lab.eval_config_dir()))
                  + (" — NOT READY: " + "; ".join(problems) if problems else " — clean"))
            sp = meta.get("sandbox_problems") or []
            print("  grading sandbox: " + ("NOT AVAILABLE: " + "; ".join(sp) if sp else "available"))
            print("  nothing was executed and nothing was spent")
        return 0
    meta2, runs = lab.load_runs(str((opts.results_dir or lab.experiment_dir(meta["id"]))))
    summary = lab.summarize(runs, opts.seed)
    if args.format == "json":
        print(json.dumps({"experiment": meta2, "summary": summary}, indent=2))
    else:
        sys.stdout.write(lab.render_report(meta2, summary))
    return 0


# --------------------------------------------------------------------------
# hook entry points
# --------------------------------------------------------------------------
def cmd_hook(args: argparse.Namespace) -> int:
    """`repo-ai hook claude <event>`: always exit 0, print nothing on failure."""
    from .hooks import MAX_STDIN, run
    try:
        data = sys.stdin.read(MAX_STDIN + 1) if not sys.stdin.isatty() else ""
    except (OSError, ValueError):
        data = ""
    if args.agent != "claude":
        return 0
    out = run(args.event, data)
    if out:
        sys.stdout.write(out)
        sys.stdout.flush()
    return 0


def cmd_extract_prompt(args: argparse.Namespace) -> int:
    """Read a hook JSON payload on stdin and print the `prompt` field (Bob hooks)."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 1
    prompt = data.get("prompt") if isinstance(data, dict) else ""
    if isinstance(prompt, str) and prompt.strip():
        sys.stdout.write(prompt.strip())
        return 0
    return 1


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-ai",
        description="Local-first repository intelligence and skeptical, sandboxed change verification.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "typical use:\n"
            "  cd <repo> && repo-ai init --agent claude --smart   # once per repository\n"
            "  claude                                           # context arrives via hooks\n"
            "  repo-ai context \"fix login bug\"                   # shortlist by hand\n"
            "  repo-ai impact --changed                         # what does my diff touch?\n"
            "  repo-ai verify                                   # which tests can show it broke (read-only)\n"
            "  repo-ai verify --run                             # run them, sandboxed (executes repo code)\n"
            "  repo-ai doctor --agent claude                    # verify the wiring\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"repo-ai {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-C", "--path", metavar="DIR", help="repository directory (default: cwd)")
    common.add_argument("-v", "--verbose", action="store_true", default=None,
                        help="more detail; on an error, print the traceback")
    common.add_argument("-q", "--quiet", action="store_true", default=None, help="less output")

    # an explicit metavar keeps the usage line short and hidden commands (no help=) unlisted
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    analysis = argparse.ArgumentParser(add_help=False)
    analysis.add_argument("--workers", type=int, help="parser threads (default: auto)")
    analysis.add_argument("--max-file-bytes", type=int,
                          help="skip files larger than this (default: 1500000)")
    analysis.add_argument("--git-history-days", type=int,
                          help="git window for hotspots (default: 365)")
    analysis.add_argument("--summarize", action="store_true", default=None,
                          help="add a narrative summary via `bob run` (sends facts, not code)")
    analysis.add_argument("--no-symbols", dest="parse_symbols", action="store_false",
                          default=None, help="skip AST parsing (much faster, less useful)")
    analysis.add_argument("--no-secrets", dest="detect_secrets", action="store_false",
                          default=None, help="disable the secret scanner (not recommended)")
    analysis.add_argument("--no-commit-context", dest="commit_context",
                          action="store_false", default=None,
                          help="gitignore the generated docs instead of committing them")
    analysis.add_argument("--no-bob", action="store_true",
                          help="(v0.4 compatibility) skip Bob wiring")
    preview = argparse.ArgumentParser(add_help=False)
    preview.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    preview.add_argument("--diff", action="store_true", help="like --dry-run, with a unified diff")

    p = sub.add_parser("init", parents=[common, analysis, preview],
                       help="analyse a repository and wire up agents")
    p.add_argument("--agent", choices=AGENT_CHOICES,
                   help="claude | bob | both | auto | none (default: bob, as in v0.4)")
    p.add_argument("--smart", action="store_true",
                   help="(experimental; no benefit shown) evidence-based self-maintenance: learning_policy=safe-auto, "
                        "skills_mode=auto, learning_signals=outcomes")
    p.add_argument("--local-only", action="store_true",
                   help="personal setup: settings.local.json / CLAUDE.local.md, all outputs gitignored")
    p.add_argument("--feature-set", choices=["core", "full"],
                   help="capability set recorded in .repo-ai/config.toml: core (default for new "
                        "installs) or full (experimental, no benefit shown: adds subagents, the skeptic reviewer, "
                        "orchestration hints)")
    p.add_argument("--force", action="store_true", help="rebuild the index from scratch")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("update", parents=[common, analysis, preview], help="incremental re-analysis")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("rebuild", parents=[common, analysis, preview], help="full re-analysis from scratch")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("refresh", parents=[common], help="debounced update for hooks (never blocks)")
    p.add_argument("--background", action="store_true", help="detach and return immediately")
    p.add_argument("--force", action="store_true", help="ignore the debounce window")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("status", parents=[common], help="freshness check (exit 2 when stale)")
    p.add_argument("--brief", action="store_true", help="one-line output for a SessionStart hook")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_status)

    for name, helptext in (("context", "retrieve relevant files for a task"),
                           ("explain", "show why each file was retrieved (score breakdown)")):
        p = sub.add_parser(name, parents=[common], help=helptext)
        p.add_argument("task", nargs="+", help="the task, in plain language (stack traces welcome)")
        p.add_argument("--scope", default="",
                       help="diff | branch[:base] | component:<name> | lang:<language> | path:<glob> | tests")
        p.add_argument("--max-context-files", type=int, dest="max_context_files")
        p.add_argument("--context-budget-tokens", type=int, dest="context_budget_tokens")
        p.add_argument("--no-tests", action="store_true", help="exclude test files from results")
        p.add_argument("--no-cache", action="store_true", help="bypass the query cache")
        if name == "context":
            p.add_argument("--format", choices=["markdown", "claude", "hook", "json", "paths", "mentions"],
                           default="markdown")
            p.add_argument("--agent", choices=["claude", "bob"], help="output style for an agent")
            p.add_argument("--explain", action="store_true", help="print the score breakdown")
            p.set_defaults(func=cmd_context)
        else:
            p.set_defaults(func=cmd_explain)

    p = sub.add_parser("impact", parents=[common], help="change impact for paths or symbols")
    p.add_argument("targets", nargs="*", help="paths or symbol names")
    p.add_argument("--changed", action="store_true", help="use uncommitted changes as targets")
    p.add_argument("--branch", nargs="?", const="", default=None, metavar="BASE",
                   help="use changes since the merge-base with BASE (default: origin/HEAD or main)")
    p.add_argument("--depth", type=int, default=3, help="transitive importer depth (default 3)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser("verify", parents=[common],
                       help="what a change can break, which tests show it, and (with --run) what "
                            "running them in a sandbox showed")
    p.add_argument("--base", default="HEAD", help="compare the working tree with this revision (default HEAD)")
    p.add_argument("--run", action="store_true",
                   help="run the selected tests in the sandbox (executes repository code)")
    p.add_argument("--full", action="store_true", help="with --run: run the full suite (it includes the selection)")
    p.add_argument("--show-fixed", action="store_true",
                   help="with --run: run the base revision's full suite once (cached) to name tests the change fixed")
    p.add_argument("--paths", action="append", metavar="PATH[,PATH]",
                   help="plan only for these changed files (read-only; a per-edit preview: never with "
                        "--run or --record, never evidence for the whole change)")
    p.add_argument("--rerun", action="store_true",
                   help="with --run: run again even when evidence for this exact change and environment exists")
    p.add_argument("--record", action="store_true",
                   help="run every test file once under a tracer (sandboxed) to record which code "
                        "each one executes (executes repository code)")
    p.add_argument("--test-command", metavar="CMD",
                   help="the project's test command, when repo-ai cannot establish it")
    p.add_argument("--sandbox", default="auto", choices=["auto", "seatbelt", "bwrap", "podman", "docker"],
                   help="where --run/--record execute (default: a host sandbox with the project's "
                        "interpreter, else a container)")
    p.add_argument("--image", metavar="REF",
                   help="with --sandbox podman/docker: a local image that has the project's dependencies "
                        "(never pulled; the default images have only the standard library)")
    p.add_argument("--no-runtime", action="store_true", help="ignore recorded runtime evidence")
    p.add_argument("--workers", type=int, default=4, help="parallel test processes (default 4)")
    p.add_argument("--timeout", type=float, default=None,
                   help="seconds per test process (default: 5x its measured time + 10s, at least 30s, at most 600s; "
                        "600s when nothing has been measured)")
    p.add_argument("--deadline", type=float, default=None, metavar="SECONDS",
                   help="with --run: a total wall-clock budget for every test process of the run; no limit is "
                        "extended past it, and tests it cuts or leaves unstarted make the run 'not verified' "
                        "(never a pass)")
    p.add_argument("--gate", action="store_true",
                   help="(experimental) agent completion gate (Stop hook): silent unless the current "
                        "change is unverified")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("evidence", parents=[common],
                       help="the latest verification evidence and whether it covers the current change")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("prove", parents=[common],
                       help="(experimental) ProofLab: show that the original code fails a pinned scenario and the "
                            "change passes it: pin | plan | run | status | report",
                       description="EXPERIMENTAL, NOT CERTIFIED: ProofLab is opt-in and outside repo-ai's stable "
                                   "verification claims; it failed its independent qualification, and false proofs are "
                                   "known and open (always-equal-class, swallowed-assertion, importorskip-zero-entry-"
                                   "points; docs/PROOFLAB.md). A supported verdict is a "
                                   "local experiment record, not a proof.")
    p.add_argument("action", choices=["pin", "plan", "run", "status", "report"],
                   help="pin a claim and its scenario; plan (read-only); run (sandboxed, executes repository code); "
                        "status (is the passport fresh); report (Markdown, json or in-toto)")
    p.add_argument("claim_id", nargs="?", default=None, metavar="ID",
                   help="the claim (default: the only one pinned); with pin: the id to give it")
    p.add_argument("--claim", metavar="TEXT", help="pin: what the change is supposed to do")
    p.add_argument("--claim-stdin", action="store_true", help="pin: read the claim from stdin")
    p.add_argument("--scenario", metavar="PATH",
                   help="pin: the acceptance test file, repository-relative (its exact bytes are pinned)")
    p.add_argument("--from", dest="scenario_from", metavar="REV",
                   help="pin: take the scenario (and --support files) from this commit, e.g. a reviewer's")
    p.add_argument("--file", dest="scenario_file", metavar="PATH",
                   help="pin: take the scenario's bytes from a file outside the repository")
    p.add_argument("--support", action="append", default=[], metavar="PATH",
                   help="pin: a helper or data file the scenario needs; both runs use its pinned bytes")
    p.add_argument("--subject", action="append", default=[], metavar="GLOB",
                   help="pin: the code under test (a path or glob, repeatable). The scenario runs on the base plus "
                        "only these files of the change; without it, the changed files the scenario imports")
    p.add_argument("--target", action="append", default=[], metavar="TEST_ID",
                   help="pin: a test id that must fail at the base (default: any test of the scenario)")
    p.add_argument("--expect-failure", metavar="REGEX",
                   help="pin: the base must fail with a message matching this")
    p.add_argument("--supersedes", action="append", default=[], metavar="TEST_ID",
                   help="pin: a test of an edited test file whose old expectation the change replaces on purpose")
    p.add_argument("--redact-claim", action="store_true", help="pin: store only the claim's hash, not its text")
    p.add_argument("--replace", action="store_true", help="pin: replace a claim pinned with other settings")
    p.add_argument("--remove", action="store_true", help="pin: unpin the named claim and forget its passports")
    p.add_argument("--base", default="HEAD", help="the original code: this revision (default HEAD)")
    p.add_argument("--repeat", type=int, default=2, help="run: runs of the scenario on each side (default 2)")
    p.add_argument("--no-regressions", action="store_true",
                   help="run: skip the regression check (the claim then cannot be supported)")
    p.add_argument("--rerun", action="store_true", help="run: do not reuse verify evidence for the regression check")
    p.add_argument("--keep-going", action="store_true",
                   help="run: run the regression check even when the scenario already rules the claim out")
    p.add_argument("--test-command", metavar="CMD", help="the project's test command, as for verify")
    p.add_argument("--sandbox", default="auto", choices=["auto", "seatbelt", "bwrap", "podman", "docker"],
                   help="run: where the tests execute (as for verify)")
    p.add_argument("--image", metavar="REF", help="run: with podman/docker, a local image (never pulled)")
    p.add_argument("--workers", type=int, default=4, help="run: parallel test processes (default 4)")
    p.add_argument("--timeout", type=float, default=None,
                   help="run: seconds per test process (default 300 for the scenario, verify's own for regressions)")
    p.add_argument("--format", default="md", choices=["md", "json", "in-toto"], help="report: the output format")
    p.add_argument("--out", metavar="FILE", help="report: write to this file")
    p.add_argument("--publish-pr", type=int, metavar="N",
                   help="report: post the Markdown passport on pull request N with your `gh` (opt-in; a fresh "
                        "passport only)")
    p.add_argument("--public-ok", action="store_true",
                   help="report --publish-pr: allow posting on a public repository")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_prove)

    p = sub.add_parser("privacy", parents=[common],
                       help="audit what repo-ai stores, where, and whether it is committed")
    p.add_argument("action", nargs="?", choices=["audit"], default="audit")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_privacy)

    p = sub.add_parser("packet", parents=[common],
                       help="small, source-linked task briefing (locations, tests, constraints, blast radius)")
    p.add_argument("task", nargs="+")
    p.add_argument("--format", choices=["markdown", "claude", "json"], default="markdown")
    p.add_argument("--max-files", type=int, default=6)
    p.add_argument("--budget-tokens", type=int, default=900, help="hard cap (estimate; default 900)")
    p.set_defaults(func=cmd_packet)

    p = sub.add_parser("review", parents=[common],
                       help="pre-PR change passport: what the diff touches, tests, risks, blind spots")
    p.add_argument("--changed", action="store_true", help="uncommitted changes (default)")
    p.add_argument("--branch", nargs="?", const="", default=None, metavar="BASE",
                   help="changes since the merge-base with BASE")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("budget", parents=[common],
                       help="budget governor: always-loaded and per-prompt context, limits (estimates)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("--check", action="store_true", help="exit 1 when over budget")
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser("capabilities", parents=[common],
                       help="capability coverage map (no action), or the capability registry: list | show | "
                            "prepare | approve | revoke | run | evidence; recommend | candidates | select "
                            "are experimental")
    p.add_argument("action", nargs="?", choices=["list", "show", "recommend", "candidates", "select", "prepare",
                                                 "approve", "revoke", "run", "evidence"],
                   help="recommend | candidates | select are experimental")
    p.add_argument("ids", nargs="*", help="capability ids")
    p.add_argument("--task", default="",
                   help="recommend (experimental) / run repo-ai.context: what you are working on")
    p.add_argument("--task-stdin", action="store_true",
                   help="read the task from stdin (at most 8000 bytes); keeps pasted text out of the shell")
    p.add_argument("--task-file", metavar="PATH",
                   help="read the task from a file (at most 8000 bytes): the safest way for an agent to pass it")
    p.add_argument("--files", default=None, metavar="A,B",
                   help="recommend / run: changed files (default: the working tree against --base)")
    p.add_argument("--no-changes", action="store_true", help="recommend: ignore the working tree")
    p.add_argument("--base", default="HEAD", help="compare the working tree with this revision (default HEAD)")
    p.add_argument("--executable", metavar="PATH", help="prepare / approve: the binary to bind (absolute path)")
    p.add_argument("--sha256", metavar="PREFIX", help="approve: the hash `prepare` printed")
    p.add_argument("--all", action="store_true",
                   help="revoke: every approval; candidates/select (experimental): every record")
    p.add_argument("--deny", default="", metavar="C,C",
                   help="recommend / candidates / select (experimental): rule out capabilities (no-network, "
                        "no-exec, static-only, "
                        "no-install, no-third-party); always enforced, only ever tightens")
    p.add_argument("--digest", default="", help="select (experimental): the digest `candidates` printed")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_capabilities)

    p = sub.add_parser("performance", parents=[common],
                       help="repo-ai's measured effect here: hook, shortlist, sessions, experiments")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_performance)

    p = sub.add_parser("optimize", parents=[common],
                       help="(experimental) research proposals; --apply only what the Self-Improvement Governor "
                            "allows")
    p.add_argument("ids", nargs="*", help="--apply: only these proposal ids")
    p.add_argument("--apply", action="store_true", help="apply governor-approved tuning (journaled)")
    p.add_argument("--revert", nargs="?", const="", default=None, metavar="ID",
                   help="undo one journaled change (default: all active)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser("friction", parents=[common],
                       help="friction radar: repeated, evidence-backed waste (same as learn friction)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_friction)

    p = sub.add_parser("quickstart", parents=[common], help="where you are and what to run next")
    p.set_defaults(func=cmd_quickstart)

    p = sub.add_parser("completion", help="shell completion script: bash | zsh | fish")
    p.add_argument("shell", choices=["bash", "zsh", "fish"])
    p.set_defaults(func=cmd_completion)

    p = sub.add_parser("orchestrate", parents=[common],
                       help="advise zero, one or a few read-only specialists for a task (spawns nothing)")
    p.add_argument("action", choices=["plan"])
    p.add_argument("task", nargs="+")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_orchestrate)

    p = sub.add_parser("graph", parents=[common],
                       help="evidence graph around a file, symbol:<name>, route:<METHOD path> or component:<name>")
    p.add_argument("node")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--kind", action="append",
                   choices=["contains", "defines", "imports", "tests", "co_changes", "uses",
                            "exposes", "consumes_api"], help="only these edge kinds (repeatable)")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_graph)

    p = sub.add_parser("debug", parents=[common],
                       help="context flight recorder: what the prompt hook injected or omitted, and why")
    p.add_argument("action", nargs="?", choices=["last", "purge"], default="last")
    p.add_argument("-n", type=int, default=1, help="how many recent decisions (default 1)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_debug)

    p = sub.add_parser("sandbox", help="isolated execution backends for untrusted code: status | pull")
    p.add_argument("action", nargs="?", choices=["status", "pull"], default="status")
    p.add_argument("--toolchain", action="append", choices=["python", "node", "java"])
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_sandbox)

    p = sub.add_parser("eval", aliases=["benchmark"], parents=[common],
                       help="paired coding-task evaluation (offline by default; --live is opt-in)",
                       description="Offline (default, free): validate every task oracle and "
                       "measure localization. --live (billable, opt-in): paired headless Claude "
                       "Code runs without vs with repo-ai, hard-capped by --max-cost-usd.")
    p.add_argument("action", nargs="?",
                   choices=["coding", "report", "compare", "regressions", "ablate", "list"],
                   help="coding: three-arm task-completion experiment (baseline,core,full); "
                        "report/compare/regressions/list: read recorded experiments; "
                        "ablate --feature X: full vs full-without-X")
    p.add_argument("targets", nargs="*", help="experiment ids (report/compare/regressions)")
    p.add_argument("--compare", default="baseline,core,full",
                   help="coding: arms to run (baseline, core, full, full-<feature>)")
    p.add_argument("--feature", help="ablate: feature to remove from full")
    p.add_argument("--pilot", action="store_true",
                   help="coding: a small held-out pilot (6 tasks, 1 repeat) unless --tasks/--max-tasks")
    p.add_argument("--effort", help="coding: thinking effort, identical for every arm")
    p.add_argument("--resume", metavar="EXPERIMENT", help="coding: continue an interrupted experiment")
    p.add_argument("--results", help="coding: results directory (default: the lab home)")
    p.add_argument("--claude-config", help="coding: dedicated Claude config dir "
                   "(default: ~/.local/share/repo-ai/claude-eval)")
    p.add_argument("--sandbox", default="auto", choices=["auto", "podman", "docker", "bwrap", "seatbelt"],
                   help="coding: grading sandbox backend")
    p.add_argument("--reserve-per-run", type=float, metavar="USD",
                   help="coding: worst-case cost of one run for the budget gate (cap + its largest "
                        "API call; default 1.25 x --max-cost-per-run)")
    p.add_argument("--blind", action="store_true",
                   help="coding: do not show pass/fail while running (pre-registered experiments)")
    p.add_argument("--fake", action="store_true",
                   help="coding: the --claude-cmd is a deterministic fake (no budget; results FAKE)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="free, deterministic (default)")
    mode.add_argument("--live", action="store_true", help="run Claude Code (billable; needs --max-cost-usd)")
    p.add_argument("--suite", help="task suite directory (default: the bundled suite)")
    p.add_argument("--tasks", metavar="REGEX", help="only task ids matching REGEX")
    p.add_argument("--max-tasks", type=int, help="random sample of N tasks (seeded)")
    p.add_argument("--split", choices=["all", "dev", "holdout", "final", "calibration", "sealed-v2"],
                   default="all",
                   help="dev: tune on these; holdout: report only (by task id); final: the sealed "
                        "test set, only when named (all = dev + holdout)")
    p.add_argument("--seed", type=int, default=0, help="sampling and arm-order seed (default 0)")
    p.add_argument("--task-order", choices=["suite", "interleave"], default="suite",
                   help="coding: suite (task id order) or interleave (round-robin across bases, seeded; "
                        "an early budget stop still covers every project)")
    p.add_argument("--concurrency", type=int, default=1, help="parallel tasks (offline)")
    p.add_argument("--dry-run", action="store_true", help="list what would run; run nothing")
    p.add_argument("--no-network", action="store_true",
                   help="guarantee no network use (offline only; rejected with --live)")
    p.add_argument("--no-validate", action="store_true", help="offline: skip oracle validation")
    p.add_argument("--no-localization", action="store_true", help="offline: skip localization")
    p.add_argument("--check", metavar="BASELINE.json", help="fail if worse than a saved offline report")
    p.add_argument("--max-cost-usd", type=float, help="live: total budget (required for --live)")
    p.add_argument("--max-cost-per-run", type=float, default=1.0,
                   help="live: cap per Claude run, passed as --max-budget-usd (default 1.00)")
    p.add_argument("--max-turns", type=int, default=30, help="live: turns per run (default 30)")
    p.add_argument("--timeout", type=int, default=900, help="live: seconds per run (default 900)")
    p.add_argument("--repeat", type=int, default=1, help="live: repetitions per task")
    p.add_argument("--model", help="live: model alias or id (same for both arms)")
    p.add_argument("--claude-cmd", default="claude", help="live: Claude Code command (default: claude)")
    p.add_argument("--keep-artifacts", action="store_true", help="live: keep workspaces")
    p.add_argument("--artifacts-dir", help="live: where workspaces go (default: a temp dir)")
    p.add_argument("--out", help="also write the JSON report here")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("search", parents=[common], help="lexical search over the index")
    p.add_argument("terms", nargs="+")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("symbol", parents=[common], help="find where a symbol is defined")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_symbol)

    p = sub.add_parser("related", parents=[common], help="importers, imports, co-changes, tests of a file")
    p.add_argument("file")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_related)

    p = sub.add_parser("deps", parents=[common], help="show declared dependencies")
    p.add_argument("name", nargs="?", help="filter by substring")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_deps)

    for name, filename in (
        ("architecture", "ARCHITECTURE.md"), ("overview", "PROJECT_OVERVIEW.md"),
        ("map", "REPOSITORY_MAP.md"), ("tests", "TESTING.md"),
        ("conventions", "CONVENTIONS.md"), ("hotspots", "HOTSPOTS.md"),
    ):
        p = sub.add_parser(name, parents=[common], help=f"print {filename}")
        p.set_defaults(func=lambda a, f=filename: cmd_show(a, f))

    p = sub.add_parser("learn", parents=[common, analysis],
                       help="(experimental) evidence-backed rules and outcome learning: status | review | explain | "
                            "approve | reject | rollback | history | shadow | friction | forget | export")
    p.add_argument("action", nargs="?", choices=["status", "review", "explain", "approve", "reject",
                                                 "rollback", "history", "shadow", "friction",
                                                 "forget", "export"])
    p.add_argument("target", nargs="?", help="rule id, event id, or `ranking` (the outcome prior)")
    p.add_argument("--what", choices=["episodes", "signals", "flight", "ranking", "all"],
                   help="forget: which store (default all)")
    p.add_argument("--older-than", type=int, metavar="DAYS", help="forget: only episodes older than DAYS")
    p.add_argument("--portable", action="store_true", help="export: drop paths and repo specifics")
    p.add_argument("--force", action="store_true", help="approve ranking: promote despite the shadow gate")
    p.add_argument("--apply", action="append", metavar="ID", help="apply a proposed rule")
    p.add_argument("--apply-safe", action="store_true", help="apply every high-confidence safe proposal")
    p.add_argument("--reject", action="append", metavar="ID", help="reject a rule (not re-proposed "
                   "unless its evidence changes)")
    p.add_argument("--explain", nargs="?", const="", default=None, metavar="ID",
                   help="show evidence for one rule (or all)")
    p.add_argument("--history", action="store_true", help="list learning events")
    p.add_argument("--rollback", metavar="EVENT", help="undo a learning event")
    p.add_argument("--forget-signals", action="store_true", help="delete locally recorded signals")
    p.add_argument("--all", action="store_true", help="include retired rules")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_learn, dry_run=False, diff=False)

    p = sub.add_parser("skills", parents=[common],
                       help="skill lifecycle (experimental, except the read-only inventory and vet): list | "
                            "discover | propose | test | diff | promote | disable | rollback | canary | draft | doctor | "
                            "inventory | vet | policy | autopilot")
    p.add_argument("action", choices=["list", "discover", "candidates", "propose", "test", "diff",
                                      "promote", "generate", "disable", "rollback", "canary",
                                      "draft", "doctor", "audit", "recommend", "explain", "install",
                                      "portfolio", "updates", "compare", "benchmark", "health",
                                      "enable", "tournament", "inventory", "vet", "policy", "autopilot"])
    p.add_argument("names", nargs="*")
    p.add_argument("--online", action="store_true",
                   help="allow network access: discover (Skill Radar), install of a remote skill, "
                        "updates; off by default")
    p.add_argument("--providers", default="anthropic,vercel,github,marketplace,publishers,skills.sh",
                   help="discover --online: providers to query")
    p.add_argument("--from-path", metavar="DIR", help="discover: vet a local skill directory")
    p.add_argument("--max-requests", type=int, default=None,
                   help="network request cap (default 60; vet: 400)")
    p.add_argument("--audit-limit", type=int, default=12,
                   help="discover --online: candidates to quarantine and inspect (default 12)")
    p.add_argument("--vet-limit", type=int, default=None,
                   help="vet: skills to quarantine and inspect (default 200); any beyond it make "
                        "the result incomplete (exit 3)")
    p.add_argument("--all", action="store_true", help="audit: every quarantined candidate; "
                   "disable --third-party: the kill switch; inventory: list every item")
    p.add_argument("--no-firewall", action="store_true",
                   help="inventory: skip the static firewall pass over installed skills")
    p.add_argument("--third-party", action="store_true", help="disable: third-party skills")
    p.add_argument("--approve", metavar="HASH", help="install, enable, rollback: the content hash you reviewed")
    p.add_argument("--accept-review", action="store_true",
                   help="install: accept high-severity findings you have read")
    p.add_argument("--allow-scripts", action="store_true",
                   help="install, enable, rollback: the skill ships scripts")
    p.add_argument("--host", metavar="HOSTS",
                   help="install: comma-separated hosts (default claude-code; codex, gemini-cli, antigravity "
                        "and ibm-bob are export-only)")
    p.add_argument("--check", action="store_true", help="updates: check upstream (network); "
                   "inventory: exit 1 on a high-severity issue")
    p.add_argument("--max-cost-per-run", type=float, help="benchmark: cap per run")
    p.add_argument("--trial-tasks", metavar="REGEX", help="benchmark: task ids to use")
    p.add_argument("--trial-max-tasks", type=int, help="benchmark: number of held-out tasks")
    p.add_argument("--trial-fake", action="store_true", help="benchmark: use a fake client (tests)")
    p.add_argument("--trial-claude-cmd", help="benchmark: Claude command (fake client in tests)")
    p.add_argument("--safe", action="store_true", help="promote: every valid safe candidate")
    p.add_argument("--previous", action="store_true", help="rollback: pin the previous version")
    p.add_argument("--apply", action="store_true", help="canary: act on the decision")
    p.add_argument("--draft", action="store_true", help="promote: activate the reviewed Tier-2 draft")
    p.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="draft: print exactly what would be sent; send nothing; install: show the diff and "
                        "conflicts; autopilot: decide only")
    p.add_argument("--max-cost-usd", type=float,
                   help="draft / benchmark: hard cap in USD (required for live use; billable)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_skills, diff=False)

    p = sub.add_parser("workflow", parents=[common],
                       help="compiled playbooks from verified workflows (read-only previews)")
    p.add_argument("action", nargs="?", choices=["list", "plan"], default="list")
    p.add_argument("name", nargs="?")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_workflow)

    p = sub.add_parser("registry", parents=[common],
                       help="opt-in cross-repo registry with isolated zones")
    p.add_argument("action", choices=["add", "list", "inspect", "remove", "audit", "purge", "policy",
                                      "contribute", "suggest"])
    p.add_argument("--zone", help="personal | work | <name> (zones never share data)")
    p.add_argument("--label", help="add: display name (default: directory name)")
    p.add_argument("--move", action="store_true", help="add: move from its current zone")
    p.add_argument("--set", metavar="KEY=VALUE", help="policy: llm=allow|deny or patterns=on|off")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_registry)

    p = sub.add_parser("pack", parents=[common],
                       help="Stack Packs: evidence-backed bundles from repositories in this repo's zone")
    p.add_argument("action", nargs="?", choices=["list", "show", "plan"], default="list")
    p.add_argument("pack", nargs="?", help="pack id (default: best match)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("crossrepo", parents=[common],
                       help="context or impact across repositories in this repo's zone only")
    p.add_argument("action", choices=["context", "impact"])
    p.add_argument("task", nargs="*")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_crossrepo)

    p = sub.add_parser("doctor", parents=[common], help="diagnose installation and agent wiring")
    p.add_argument("--agent", choices=["claude", "bob", "all"])
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("uninstall", parents=[common], help="remove what repo-ai created")
    p.add_argument("--agent", choices=["claude", "bob", "all"], help="default: all")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--dry-run", action="store_true", help="list what would be removed; remove nothing")
    p.add_argument("--diff", action="store_true", help="like --dry-run, with a unified diff of edited files")
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("hook", help="agent hook entry point (reads JSON on stdin)")
    p.add_argument("agent", choices=["claude"])
    p.add_argument("event", help="session-start | prompt | post-edit | stop | post-bash | post-bash-failure "
                                 "| post-skill")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("_extract-prompt")  # internal: no help=, so `--help` does not list it
    p.set_defaults(func=cmd_extract_prompt)

    from .mission.cli import register as register_missions
    register_missions(sub, common)
    return parser


def _configure_streams() -> None:
    """Make output encodable everywhere.

    Repository text, diffs and arrows are UTF-8. A Windows pipe or redirect
    defaults to the ANSI code page, where printing them raises. Pipes and
    files get UTF-8 (what hooks, `jq` and editors expect) unless the user
    chose an encoding with PYTHONIOENCODING; an interactive console keeps its
    encoding, and anything it cannot show is replaced instead of crashing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if encoding != "utf8" and not os.environ.get("PYTHONIOENCODING") \
                    and not stream.isatty():
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _configure_streams()
    import warnings
    # repo-ai parses other people's code: their invalid escape sequences are not our output
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    if argv[:1] == ["hook"]:
        # Hooks must never fail loudly, not even on bad arguments (exit 2 blocks).
        try:
            args = build_parser().parse_args(argv)
        except SystemExit:
            return 0
        try:
            return int(args.func(args) or 0)
        except BaseException:  # noqa: BLE001 - fail open
            return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except SystemExit:
        raise
    except BrokenPipeError:  # `repo-ai search ... | head`
        os._exit(0)
    except Exception as exc:
        if getattr(args, "verbose", False):
            raise
        print(f"error: {exc}", file=sys.stderr)
        print("run with -v for a traceback, or `repo-ai doctor` to diagnose.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
