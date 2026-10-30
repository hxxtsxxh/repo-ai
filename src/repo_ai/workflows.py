"""Workflow Compiler: verified, repeated workflows → typed, reversible playbooks.

A playbook is data, not a script:
- prerequisites;
- affected paths;
- ordered typed steps (`locate`, `edit`, `verify`);
- a tool policy;
- failure branches;
- a rollback recipe;
- the evidence it was compiled from.

repo-ai never executes a playbook. `repo-ai workflow plan <name>` is a
read-only preview. Following a playbook is something Claude does, step by
step, under the session's normal permissions, after the user asks.

Sources:
- **episodes** (opt-in outcomes): three or more *verified* sessions that
  edited the same areas and then ran the same known commands;
- **facts**: deterministic recipes for workflows repo-ai has structural
  evidence for. For example, adding an HTTP endpoint when routes, handlers
  and tests exist.

Verification is static and happens in a disposable copy: every path must
exist and every command must be one of the repository's declared commands.
Commands are not run. They come from repository text, which is untrusted.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MIN_SESSIONS = 3


@dataclass(slots=True)
class Step:
    id: str
    kind: str  # locate | edit | verify
    summary: str
    targets: list[str] = field(default_factory=list)
    command: str = ""
    on_failure: str = ""


@dataclass(slots=True)
class Playbook:
    name: str
    title: str
    source: str  # episodes | facts
    steps: list[Step]
    affected: list[str]
    prerequisites: list[str]
    tool_policy: dict[str, Any]
    rollback: str
    evidence: list[str]
    version: int = 1
    verified: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [asdict(s) for s in self.steps]
        return data


def _area(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return parent if parent != "." else "(root)"


def _known(facts: dict[str, Any]) -> dict[str, str]:
    return {" ".join(c.split()): kind for kind, cmds in (facts.get("commands") or {}).items()
            for c in cmds}


def from_episodes(episodes: list[dict[str, Any]], facts: dict[str, Any]) -> list[Playbook]:
    known = _known(facts)
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for ep in episodes:
        if ep.get("status") != "verified":
            continue
        edits = ep.get("edits") or []
        if not edits:
            continue
        last_edit = max(int(t) for t, _ in edits)
        areas = tuple(sorted({_area(p) for _, p in edits}))
        cmds: list[str] = []
        for t, _kind, cmd, ok in ep.get("commands") or []:
            if ok and int(t) >= last_edit and cmd in known and cmd not in cmds:
                cmds.append(cmd)
        if cmds:
            groups[(areas, tuple(cmds))].append(ep)
    out: list[Playbook] = []
    for (areas, cmds), eps in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(eps) < MIN_SESSIONS:
            continue
        edited: dict[str, int] = defaultdict(int)
        for ep in eps:
            for p in {p for _, p in ep.get("edits") or []}:
                edited[p] += 1
        affected = sorted(edited, key=lambda p: (-edited[p], p))[:12]
        slug = "-".join(PurePosixPath(a).name or "root" for a in areas[:2]).replace("(root)", "root")
        name = f"wf-{slug}"[:48].strip("-")
        steps = [Step("locate", "locate", f"Find the code to change in {', '.join(areas)}",
                      targets=[f"{a}/" for a in areas if a != "(root)"]),
                 Step("edit", "edit", "Make the change; past sessions edited these files most",
                      targets=affected[:6])]
        for i, cmd in enumerate(cmds, 1):
            steps.append(Step(f"verify-{i}", "verify", f"Run the {known.get(cmd, 'check')} check",
                              command=cmd, on_failure="fix the cause and re-run this step; "
                              "do not continue past a failing check"))
        out.append(Playbook(
            name=name, title=f"Change {', '.join(areas)} and verify with {', '.join(cmds)}",
            source="episodes", steps=steps, affected=affected,
            prerequisites=["the index is fresh (`repo-ai status`)",
                           "a clean or committed working tree, so rollback is exact"],
            tool_policy={"edits": "only the affected paths unless the task needs more",
                         "commands": list(cmds), "network": "none", "permissions": "unchanged"},
            rollback="git restore --staged --worktree -- <files you changed>",
            evidence=[f"{len(eps)} verified sessions edited {', '.join(areas)} then ran "
                      f"{' → '.join(cmds)}"]))
    return out


def from_facts(root: Path, facts: dict[str, Any], index) -> list[Playbook]:
    out: list[Playbook] = []
    routes = facts.get("routes") or []
    suites = facts.get("test_suites") or []
    if len(routes) >= 2 and suites:
        files: dict[str, int] = defaultdict(int)
        for r in routes:
            files[r.get("file", "")] += 1
        handler_files = [f for f, _ in sorted(files.items(), key=lambda kv: -kv[1]) if f][:3]
        tests: list[str] = []
        for f in handler_files:
            tests += [row["test_path"] for row in index.tests_for(f)][:2]
        suite = suites[0]
        cmd = suite.get("command", "")
        steps = [Step("locate", "locate", "Find how existing routes are declared",
                      targets=handler_files),
                 Step("edit", "edit", "Add the handler next to similar routes, following their "
                      "decorator/registration pattern", targets=handler_files[:1]),
                 Step("test", "edit", "Add a test beside the existing route tests",
                      targets=sorted(set(tests))[:2])]
        if cmd:
            steps.append(Step("verify-1", "verify", "Run the test suite", command=cmd,
                              on_failure="fix and re-run; do not continue past a failure"))
        out.append(Playbook(
            name="wf-add-endpoint", title="Add an HTTP endpoint", source="facts", steps=steps,
            affected=handler_files + sorted(set(tests))[:2],
            prerequisites=["the index is fresh (`repo-ai status`)"],
            tool_policy={"edits": "handler and test files", "commands": [cmd] if cmd else [],
                         "network": "none", "permissions": "unchanged"},
            rollback="git restore --staged --worktree -- <files you changed>",
            evidence=[f"{len(routes)} routes in {len(files)} file(s); test suite "
                      f"`{suite.get('framework', '?')}`"]))
    return out


def compile_all(root: Path, layout, facts: dict[str, Any], index) -> list[Playbook]:
    from .episodes import load_all
    books = from_episodes(load_all(layout), facts) + from_facts(root, facts, index)
    seen: set[str] = set()
    unique = []
    for book in books:
        if book.name not in seen:
            seen.add(book.name)
            unique.append(book)
    return unique


def verify(root: Path, book: Playbook, facts: dict[str, Any]) -> dict[str, Any]:
    """Static verification in a disposable copy of the tracked files."""
    problems: list[str] = []
    known = _known(facts)
    tmp = Path(tempfile.mkdtemp(prefix="repo-ai-wf-"))
    try:
        try:
            listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                                    timeout=30, check=False).stdout.decode("utf-8", "replace")
            files = [f for f in listed.split("\0") if f]
        except (OSError, subprocess.SubprocessError):
            files = []
        for rel in files:
            src = root / rel
            if src.is_file() and not src.is_symlink():
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
        def bad(rel: str) -> bool:
            p = PurePosixPath(rel.rstrip("/"))
            return p.is_absolute() or ".." in p.parts
        for path in book.affected:
            if bad(path):
                problems.append(f"affected path escapes the repository: {path}")
            elif not (tmp / path).exists():
                problems.append(f"affected path missing: {path}")
        for step in book.steps:
            for target in step.targets:
                if bad(target):
                    problems.append(f"step {step.id}: target escapes the repository: {target}")
                elif not (tmp / target.rstrip("/")).exists():
                    problems.append(f"step {step.id}: target missing: {target}")
            if step.command and " ".join(step.command.split()) not in known:
                problems.append(f"step {step.id}: `{step.command}` is not a declared command")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": not problems, "problems": problems, "method": "static (disposable copy; "
            "no command executed)"}


def render_plan(book: Playbook) -> str:
    lines = [f"workflow {book.name} (v{book.version}, from {book.source}) — {book.title}",
             "read-only preview: repo-ai does not execute playbooks"]
    if book.verified:
        state = "verified" if book.verified.get("ok") else "NOT verified"
        lines.append(f"  status: {state} ({book.verified.get('method', '')})")
        for p in book.verified.get("problems", []):
            lines.append(f"    problem: {p}")
    lines.append("  prerequisites:")
    lines += [f"    - {p}" for p in book.prerequisites]
    lines.append("  steps:")
    for step in book.steps:
        detail = f" `{step.command}`" if step.command else ""
        targets = f" → {', '.join(step.targets)}" if step.targets else ""
        lines.append(f"    {step.id:9s} [{step.kind}] {step.summary}{detail}{targets}")
        if step.on_failure:
            lines.append(f"              on failure: {step.on_failure}")
    lines.append(f"  tool policy: {json.dumps(book.tool_policy)}")
    lines.append(f"  rollback: {book.rollback}")
    lines.append(f"  evidence: {'; '.join(book.evidence)}")
    return "\n".join(lines)
