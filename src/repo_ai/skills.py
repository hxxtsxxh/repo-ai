"""Skill Factory: repository-specific Claude Code skills from verified facts.

Local mode (the default, and the only mode in this release) assembles skills
deterministically from facts repo-ai has evidence for — routes and where they
are registered, test suites and focused test commands, migration tooling,
release commands, component layout, and (opt-in) repeated command sequences.
It does not "reason"; it fills well-tested templates with verified specifics,
validates the result, and records provenance.

Placement rules (why something is or is not a skill):

  repeatable multi-step task with repo-specific know-how  -> skill
  repo-wide invariant                                    -> CLAUDE.md (learning.py)
  invariant for some paths                               -> .claude/rules (learning.py)
  one-off fact                                           -> index only
  dangerous workflow (deploy, migrate, publish)           -> manual-only skill

Ownership: generated skills carry a repo-ai marker with a checksum. A skill a
human edited, or any skill repo-ai did not write, is never overwritten.
User, team and plugin skills always win a name collision.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .adapters.claude_content import CURATED_SKILL_NAMES, NATIVE_MANAGEMENT_SKILLS, SkillDoc
from .fsutil import atomic_write, managed_state, read_text, short_hash
from .learning import Evidence, _admissible, _focused_command, _now
from .models import RepoFacts
from .paths import Layout
from .skillcheck import RISKY_RE, SkillReport, validate_skill_text

GENERATED_PREFIX = "repo-"


@dataclass(slots=True)
class SkillSpec:
    name: str
    description: str
    body: str
    risk: str = "safe"  # safe | risky
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    argument_hint: str = ""
    version: int = 1

    @property
    def manual_only(self) -> bool:
        return self.risk == "risky"

    def render(self) -> str:
        return SkillDoc(self.name, self.description, self.body, self.argument_hint,
                        self.manual_only).render()

    @property
    def digest(self) -> str:
        return short_hash(self.render())

    @property
    def evidence_hash(self) -> str:
        return short_hash(json.dumps([asdict(e) for e in self.evidence], sort_keys=True))


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
def _tests_for(index, paths: list[str], limit: int = 4) -> list[str]:
    out: list[str] = []
    for path in paths:
        for row in index.tests_for(path):
            if row["test_path"] not in out:
                out.append(row["test_path"])
    return out[:limit]


def endpoint_skill(facts: RepoFacts, index, root: Path) -> SkillSpec | None:
    by_fw: dict[str, list] = defaultdict(list)
    for route in facts.routes:
        by_fw[route.framework or "HTTP"].append(route)
    if not by_fw:
        return None
    framework, routes = max(sorted(by_fw.items()), key=lambda kv: len(kv[1]))
    if len(routes) < 3:
        return None
    files = Counter(r.file for r in routes)
    top_files = [f for f, _ in sorted(files.items(), key=lambda kv: (-kv[1], kv[0]))[:4]]
    example = sorted(routes, key=lambda r: (r.file, r.line))[0]
    registrars = sorted({row for f in top_files for row in index.importers_of(f, 6)
                         if index.get_file(row) is not None and index.get_file(row)["is_entrypoint"]})[:2]
    tests = _tests_for(index, top_files)
    focused = ""
    if tests:
        suite = next((s for s in facts.test_suites if tests[0].startswith(s.root.rstrip("/") + "/")
                      or s.root in {".", ""}), None)
        if suite:
            focused = _focused_command(suite.framework, suite.command)
    lines = [
        f"# Add or change an HTTP endpoint ({framework})",
        "",
        f"Routes in this repository are declared with {framework}. Existing route modules:",
        "",
        *[f"- `{f}` ({files[f]} route{'s' if files[f] > 1 else ''})" for f in top_files],
        "",
        f"Reference example: `{example.method} {example.path_pattern}` at `{example.file}:{example.line}`.",
        "",
        "Steps:",
        "",
        "1. Put the handler in the route module for the same resource; create a new module "
        "only for a new resource, following the closest existing one.",
        "2. Match that module's request/response models, validation and error style.",
    ]
    if registrars:
        lines.append("3. A new module must be registered where the others are: "
                     + ", ".join(f"`{r}`" for r in registrars) + ".")
    else:
        lines.append("3. Register a new module the same way the existing ones are registered "
                     "(`repo-ai related <route module>` shows who imports them).")
    if tests:
        lines.append("4. Add tests next to the existing ones: " + ", ".join(f"`{t}`" for t in tests)
                     + (f"; run one with `{focused}`." if focused else "."))
    else:
        lines.append("4. Add a test for the new behaviour following TESTING.md.")
    lines.append("5. Run `repo-ai impact <route module>` to find clients (frontend, SDKs) to update.")
    evidence = [Evidence(r.file, r.line, f"{r.method} {r.path_pattern}")
                for r in sorted(routes, key=lambda r: (r.file, r.line))[:5]]
    return SkillSpec(
        "repo-add-endpoint",
        f"Add or change an HTTP endpoint in this repo's {framework} API: where routes live, "
        "how they are registered and tested.",
        "\n".join(lines), "safe", evidence, 0.85 if len(routes) >= 5 else 0.75,
        f"{len(routes)} {framework} routes across {len(files)} file(s): a repeatable, repo-specific task",
        argument_hint="<endpoint to add or change>")


def tests_skill(facts: RepoFacts, index, root: Path) -> SkillSpec | None:
    suites = [s for s in facts.test_suites if s.framework and s.framework != "unknown" and s.file_count]
    if not suites:
        return None
    lines = ["# Run and write tests in this repository", "", "Suites:", ""]
    evidence: list[Evidence] = []
    for suite in suites[:6]:
        where = suite.root if suite.root not in {"", "."} else "(repo root)"
        cmd = f" — run: `{suite.command}`" if suite.command else ""
        lines.append(f"- `{where}` — {suite.framework}, {suite.kind}, {suite.file_count} file(s){cmd}")
        row = index.conn.execute(
            "SELECT path FROM files WHERE role='test' AND path LIKE ? ORDER BY path LIMIT 1",
            ((suite.root.rstrip("/") + "/%") if suite.root not in {".", ""} else "%",)).fetchone()
        if row:
            evidence.append(Evidence(row["path"], 0, f"{suite.framework} test"))
    focused = [(_focused_command(s.framework, s.command), s.framework) for s in suites[:6]]
    focused = [f for f in dict.fromkeys(focused) if f[0]]
    lines += ["", "Focused runs (fastest feedback):", ""]
    lines += [f"- {fw}: `{cmd}`" for cmd, fw in focused] or ["- use the suite command with a file path argument"]
    lines += ["",
              "To find the tests for a file: `repo-ai impact <path>` (tests section) — it uses "
              "import links and naming conventions, so treat it as a strong hint, not proof.",
              "", "When writing a test: put it beside the existing tests for that component, "
              "copy the nearest test's fixtures and naming, and make it fail before the fix."]
    if not evidence:
        return None
    return SkillSpec(
        "repo-tests",
        "How to run and write tests in this repo: suites, frameworks, focused commands, "
        "and how to find the tests for a file.",
        "\n".join(lines), "safe", evidence, 0.85,
        f"{len(suites)} test suite(s) with known frameworks: multi-step know-how")


_MIGRATION_MARKERS = (
    (r"(^|/)alembic\.ini$", "Alembic", "alembic revision --autogenerate -m '<message>'"),
    (r"(^|/)alembic/(env\.py|versions/)", "Alembic", "alembic revision --autogenerate -m '<message>'"),
    (r"(^|/)prisma/schema\.prisma$", "Prisma", "npx prisma migrate dev --name <name>"),
    (r"(^|/)db/migrate/\d+_\w+\.rb$", "Rails", "bin/rails generate migration <Name>"),
    (r"(^|/)migrations/\d{4}_\w+\.py$", "Django", "python manage.py makemigrations"),
    (r"(^|/)db/migration/V\d+__\w+\.sql$", "Flyway", ""),
    (r"(^|/)knexfile\.(js|ts)$", "Knex", "npx knex migrate:make <name>"),
)


def migrations_skill(facts: RepoFacts, index, root: Path) -> SkillSpec | None:
    paths = [r["path"] for r in index.conn.execute("SELECT path FROM files ORDER BY path")]
    found: dict[str, tuple[str, list[str]]] = {}
    for pattern, tool, cmd in _MIGRATION_MARKERS:
        rx = re.compile(pattern)
        hits = [p for p in paths if rx.search(p)]
        if hits and tool not in found:
            found[tool] = (cmd, hits[:3])
    if not found:
        return None
    tool, (create_cmd, hits) = sorted(found.items())[0]
    db_cmds = facts.commands.get("db") or []
    lines = [f"# Database schema migrations ({tool})", "",
             "**Manual-only.** Migrations change shared state. Never run one against a "
             "non-local database unless the user explicitly says so in this conversation.", "",
             "Evidence in this repo: " + ", ".join(f"`{h}`" for h in hits) + ".", "", "Steps:", ""]
    if create_cmd:
        lines.append(f"1. Create the migration: `{create_cmd}` (review the generated file; "
                     "autogenerate misses renames and data moves).")
    else:
        lines.append("1. Add a new migration file following the naming of the existing ones.")
    lines.append("2. Make it reversible where the tool supports a down/rollback step.")
    if db_cmds:
        lines.append("3. Apply locally with the project's command: " +
                     ", ".join(f"`{c}`" for c in db_cmds[:2]) + " — local database only.")
    else:
        lines.append("3. Apply it to a local/dev database only, then run the tests.")
    lines.append("4. Report the migration file and the exact commands you ran.")
    return SkillSpec(
        "repo-db-migration",
        f"Create and apply a {tool} database migration in this repo (manual-only: changes shared state).",
        "\n".join(lines), "risky", [Evidence(h, 0, f"{tool} migration artefact") for h in hits], 0.8,
        f"{tool} migration tooling detected: multi-step and risky, so manual-only",
        argument_hint="<schema change>")


def release_skill(facts: RepoFacts, index, root: Path) -> SkillSpec | None:
    from .learning import command_evidence
    deploy = facts.commands.get("deploy") or []
    if not deploy:
        return None
    evidence: list[Evidence] = []
    for cmd in deploy[:3]:
        evidence += command_evidence(root, facts, cmd)
    if not evidence:
        return None
    lines = ["# Release / deploy", "",
             "**Manual-only.** Deploying or publishing affects users. Run these only when the "
             "user explicitly asks in this conversation, and confirm the target first.", "",
             "Commands declared by this repo:", "", *[f"- `{c}`" for c in deploy[:4]], "",
             "Checklist: tests green (`/repo-verify`), version/changelog updated, working tree "
             "clean, correct branch, credentials come from the user's environment (never paste them)."]
    return SkillSpec("repo-release", "Release or deploy this project using its declared commands "
                     "(manual-only: affects users).", "\n".join(lines), "risky", evidence, 0.8,
                     "deploy/publish commands declared: risky multi-step workflow")


def components_skill(facts: RepoFacts, index, root: Path) -> SkillSpec | None:
    rows = index.conn.execute(
        "SELECT path FROM files WHERE role='source' AND (path LIKE '%/components/%') "
        "AND (path LIKE '%.tsx' OR path LIKE '%.jsx' OR path LIKE '%.vue' OR path LIKE '%.svelte') "
        "ORDER BY path").fetchall()
    if len(rows) < 3:
        return None
    dirs = Counter(str(PurePosixPath(r["path"]).parent) for r in rows)
    main_dir, count = sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if count < 2:
        return None
    files = [r["path"] for r in rows if str(PurePosixPath(r["path"]).parent) == main_dir]
    tests = [r["path"] for r in index.conn.execute(
        "SELECT path FROM files WHERE role='test' AND path LIKE ? ORDER BY path LIMIT 3",
        (main_dir + "/%",))]
    pascal = sum(1 for f in files if PurePosixPath(f).stem[:1].isupper())
    lines = ["# Add a UI component", "",
             f"Components live in `{main_dir}/` ({count} files, e.g. "
             + ", ".join(f"`{f}`" for f in files[:3]) + ").", ""]
    if pascal == len(files):
        lines.append("- File and component names are PascalCase (`MyWidget.tsx` exports `MyWidget`).")
    lines.append("- Copy the props/typing style of the closest existing component.")
    if tests:
        lines.append("- Tests sit next to components: " + ", ".join(f"`{t}`" for t in tests[:2]) + ".")
    lines.append("- Find usages to update with `repo-ai impact <component file>`.")
    return SkillSpec("repo-add-component", f"Add or change a UI component under {main_dir}/ "
                     "following this repo's naming, typing and test layout.", "\n".join(lines), "safe",
                     [Evidence(f, 0, "component") for f in files[:3]], 0.8,
                     f"{count} components share one layout: repeatable task", "<component>")


def sequence_skill(layout: Layout, facts: RepoFacts) -> SkillSpec | None:
    from .signals import command_sequences, read_signals
    sequences = command_sequences(read_signals(layout))
    ranked = sorted(((len(s), seq) for seq, s in sequences.items() if len(s) >= 3), reverse=True)
    if not ranked:
        return None
    sessions, seq = ranked[0]
    known = {c: k for k, cmds in facts.commands.items() for c in cmds}
    kinds = [known.get(c, "") for c in seq]
    if any(k not in {"lint", "test", "build"} for k in kinds):
        return None
    lines = ["# Pre-finish checks used in this repo", "",
             f"In {sessions} recent sessions the same check sequence was run before finishing:", "",
             *[f"{i}. `{c}` ({k})" for i, (c, k) in enumerate(zip(seq, kinds, strict=False), start=1)], "",
             "Run them in this order after a change; stop at the first failure and fix it."]
    return SkillSpec("repo-precheck", "Run this repo's habitual pre-finish checks in order "
                     f"({' → '.join(kinds)}).", "\n".join(lines), "safe",
                     [Evidence("(local signals)", 0, f"{sessions} sessions")], 0.8,
                     "same verified command sequence repeated across independent sessions")


def discover(root: Path, layout: Layout, facts: RepoFacts, index, signals: bool = False) -> list[SkillSpec]:
    specs: list[SkillSpec] = []
    for factory in (endpoint_skill, tests_skill, migrations_skill, release_skill, components_skill):
        try:
            spec = factory(facts, index, root)
        except Exception:  # pragma: no cover - one bad extractor must not kill update
            spec = None
        if spec is not None:
            specs.append(spec)
    if signals:
        spec = sequence_skill(layout, facts)
        if spec is not None:
            specs.append(spec)
    for spec in specs:
        spec.evidence = [e for e in spec.evidence if _admissible(e.path) or e.path == "(local signals)"]
    return [s for s in specs if s.evidence]


# --------------------------------------------------------------------------
# validation and collisions
# --------------------------------------------------------------------------
def collision(root: Path, name: str) -> str:
    if name in CURATED_SKILL_NAMES or name in NATIVE_MANAGEMENT_SKILLS:
        return "name reserved for a curated repo-ai skill"
    project = root / ".claude" / "skills" / name / "SKILL.md"
    text = read_text(project)
    from .capbundle import MARKER_KIND
    from .fsutil import marker_attrs
    if marker_attrs(text or "").get("kind") == MARKER_KIND:
        return "a third-party skill repo-ai installed uses this name"
    state = managed_state(text)
    if state == "foreign":
        return "a project skill with this name already exists (user-owned)"
    if state == "modified":
        return "the generated skill was edited by hand; it now belongs to the user"
    if (Path.home() / ".claude" / "skills" / name / "SKILL.md").is_file():
        return "a personal skill (~/.claude/skills) uses this name"
    return ""


def validate(spec: SkillSpec, root: Path) -> SkillReport:
    report = validate_skill_text(spec.render(), f".claude/skills/{spec.name}/SKILL.md", spec.name, root)
    from .skillcheck import command_text
    commands = command_text(spec.body)
    if spec.risk == "safe" and RISKY_RE.search(commands):
        report.errors.append("classified safe but references risky commands")
    return report


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------
@dataclass(slots=True)
class SkillState:
    path: Path
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, layout: Layout) -> "SkillState":
        path = layout.learning_dir / "skills.json"
        state = cls(path)
        text = read_text(path)
        if text:
            try:
                state.entries = dict(json.loads(text).get("skills", {}))
            except (ValueError, AttributeError):
                state.entries = {}
        return state

    def render(self) -> str:
        return json.dumps({"version": 1, "skills": {k: self.entries[k] for k in sorted(self.entries)}},
                          indent=2) + "\n"

    def save(self) -> None:
        atomic_write(self.path, self.render())


@dataclass(slots=True)
class FactoryResult:
    active: list[SkillSpec] = field(default_factory=list)
    candidates: list[tuple[SkillSpec, str, SkillReport]] = field(default_factory=list)  # spec, status, report
    changed: bool = False


def run_factory(root: Path, layout: Layout, facts: RepoFacts, index, *, mode: str, policy: str,
                signals: bool = False, generate: tuple[str, ...] = (), generate_safe: bool = False,
                reject: tuple[str, ...] = (), persist: bool = True,
                max_active: int = 8) -> FactoryResult:
    """Decide which generated skills should exist. Pure decision + state update;
    the Claude adapter performs the (ownership-checked) writes."""
    result = FactoryResult()
    state = SkillState.load(layout)
    before = state.render()
    specs = discover(root, layout, facts, index, signals) if mode != "off" else []
    seen: set[str] = set()
    now = _now()
    for spec in specs:
        seen.add(spec.name)
        entry = state.entries.get(spec.name, {})
        report = validate(spec, root)
        clash = collision(root, spec.name)
        status = entry.get("status", "candidate")
        if entry.get("evidence_hash") and entry.get("evidence_hash") != spec.evidence_hash \
                and status == "rejected":
            status = "candidate"  # evidence changed since the user rejected it
        if spec.name in reject:
            status = "rejected"
        elif spec.name in generate and status == "rejected" and not clash and report.ok:
            status = "active"  # the user explicitly re-promoted a skill they had disabled
        elif clash:
            status = "blocked"
        elif not report.ok:
            status = "invalid"
        elif status in {"candidate", "retired", "blocked", "invalid"}:
            explicit = spec.name in generate or (generate_safe and spec.risk == "safe")
            auto = mode == "auto" and policy in {"safe-auto", "manual-only-for-risky"} and (
                spec.risk == "safe" or policy == "safe-auto")
            if explicit or auto:
                status = "active"
        version = int(entry.get("version", 0) or 0)
        if entry.get("sha") != spec.digest:
            version += 1
            history = list(entry.get("history", []))[-4:]
            if entry.get("body"):
                history.append({"version": entry.get("version"), "sha": entry.get("sha"),
                                "body": entry.get("body")})
        else:
            history = list(entry.get("history", []))
        spec.version = max(version, 1)
        pinned = entry.get("pinned")
        if status == "active" and pinned:
            spec.body = pinned["body"]
            spec.version = pinned["version"]
            # A pinned body (a promoted draft, an older version, or a tampered
            # skills.json) is validated again before it can be written.
            pinned_report = validate(spec, root)
            if not pinned_report.ok:
                status = "invalid"
                report = pinned_report
        state.entries[spec.name] = {
            "status": status, "version": spec.version, "sha": spec.digest, "risk": spec.risk,
            "manual_only": spec.manual_only, "confidence": spec.confidence, "reason": spec.reason,
            "evidence": [asdict(e) for e in spec.evidence], "evidence_hash": spec.evidence_hash,
            "body": spec.body, "description": spec.description, "history": history,
            "updated_at": entry.get("updated_at", now) if entry.get("sha") == spec.digest
            and entry.get("status") == status else now,
            "note": clash or ("; ".join(report.errors) if report.errors else ""),
            **({"pinned": pinned} if pinned else {}),
        }
        if status == "active":
            result.active.append(spec)
        result.candidates.append((spec, status, report))
    # Budget Governor: cap the number of active generated skills; explicit
    # user requests win, then the most confident.
    if len(result.active) > max_active:
        ranked = sorted(result.active, key=lambda s: (s.name not in generate, -s.confidence, s.name))
        keep = {s.name for s in ranked[:max_active]}
        for spec in result.active:
            if spec.name not in keep:
                state.entries[spec.name]["status"] = "candidate"
                state.entries[spec.name]["note"] = f"over max_generated_skills = {max_active}"
        result.active = [s for s in result.active if s.name in keep]
    for name, entry in state.entries.items():
        if name not in seen and entry.get("status") in {"active", "candidate"}:
            entry["status"] = "retired"
            entry["note"] = "evidence no longer present"
            entry["updated_at"] = now
    if state.render() != before:
        if persist:
            state.save()
        result.changed = True
    return result


def rollback(layout: Layout, name: str, previous: bool = False) -> str:
    state = SkillState.load(layout)
    entry = state.entries.get(name)
    if not entry:
        return f"no generated skill named {name!r}"
    if previous:
        history = entry.get("history") or []
        if not history:
            return f"{name}: no previous version recorded"
        entry["pinned"] = {"version": history[-1]["version"], "body": history[-1]["body"]}
        entry["status"] = "active"
        state.save()
        return f"{name}: pinned to version {history[-1]['version']}; run `repo-ai update` to write it"
    entry["status"] = "rejected"
    entry.pop("pinned", None)
    entry["note"] = "rolled back by user"
    state.save()
    return f"{name}: rejected; it will be removed on the next `repo-ai update` (kept if hand-edited)"
