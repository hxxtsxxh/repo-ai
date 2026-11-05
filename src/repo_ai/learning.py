"""Evidence-backed maintenance of project instructions.

The lifecycle, per `repo-ai update` (or `repo-ai learn`):

    facts + index + (optional) local signals
      -> candidate rules, each with evidence pointers and a confidence
      -> compare with the ledger: new / unchanged / evidence-changed / gone
      -> skip anything a human already wrote (CLAUDE.md, AGENTS.md, own rules)
      -> policy decides: propose, or apply to a repo-ai-owned file/block
      -> ledger + history event (with file snapshots for rollback)

What this is **not**: an LLM writing free-form instructions. Every candidate
comes from a deterministic extractor below, so it can be re-derived, diffed,
and invalidated when its evidence changes. Placement follows one rule set:

  stable, repo-wide invariant        -> CLAUDE.md managed block
  invariant for a set of paths       -> .claude/rules/repo-ai-<topic>.md (paths:)
  volatile fact (file lists, counts) -> index only, never an instruction

Self-reference guard: evidence must point at repository content repo-ai does
not own. Managed blocks are stripped before indexing and repo-ai's own
directories are never scanned, and `_admissible()` re-checks every pointer.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .fsutil import KNOWN_BLOCKS, atomic_write, read_text, short_hash
from .models import RepoFacts
from .paths import Layout

POLICIES = ("off", "suggest", "safe-auto", "manual-only-for-risky")
AUTO_POLICIES = ("safe-auto", "manual-only-for-risky")
HIGH_CONFIDENCE = 0.8

_OWNED_PREFIXES = (".repo-ai/", ".claude/", ".bob/")
_OWNED_FILES = frozenset({"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".bobignore"})


@dataclass(slots=True)
class Evidence:
    path: str
    line: int = 0
    detail: str = ""

    def pointer(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


@dataclass(slots=True)
class Rule:
    id: str
    kind: str
    subject: str
    text: str
    placement: str  # claude-md | rules
    topic: str = ""
    paths: list[str] = field(default_factory=list)
    confidence: float = 0.0
    risk: str = "safe"
    reason: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    evidence_hash: str = ""
    source: str = "deterministic"  # deterministic | signals
    status: str = "proposed"  # proposed | active | retired | rejected | covered
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Rule":
        payload = dict(data)
        payload["evidence"] = [Evidence(**e) for e in payload.get("evidence", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _admissible(path: str) -> bool:
    """Evidence may not come from repo-ai's own output (no self-reference)."""
    if not path or path.startswith(("/", "..")):
        return False
    if path in _OWNED_FILES:
        return False
    return not path.startswith(_OWNED_PREFIXES)


def _make(kind: str, subject: str, text: str, placement: str, evidence: list[Evidence],
          confidence: float, reason: str, topic: str = "", paths: list[str] | None = None,
          risk: str = "safe", source: str = "deterministic") -> Rule | None:
    evidence = [e for e in evidence if _admissible(e.path)]
    if not evidence:
        return None
    digest = short_hash(json.dumps([text, [asdict(e) for e in evidence], sorted(paths or [])],
                                   sort_keys=True))
    rid = f"{kind}:{subject}"
    return Rule(id=rid, kind=kind, subject=subject, text=text, placement=placement,
                topic=topic, paths=sorted(paths or []), confidence=round(confidence, 2),
                risk=risk, reason=reason, evidence=evidence, evidence_hash=digest, source=source)


# --------------------------------------------------------------------------
# evidence helpers
# --------------------------------------------------------------------------
def _find_line(root: Path, rel: str, needle: str) -> int:
    text = read_text(root / rel)
    if not text:
        return 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return lineno
    return 0


def command_evidence(root: Path, facts: RepoFacts, command: str) -> list[Evidence]:
    """Locate where a command is declared: manifest script, Makefile target, doc fence."""
    out: list[Evidence] = []
    words = command.split()
    manifests = sorted({d.manifest for d in facts.dependencies if d.manifest})
    candidates = manifests + ["Makefile", "makefile", "GNUmakefile", "package.json", "pyproject.toml",
                              "README.md", "CONTRIBUTING.md", "DEVELOPMENT.md"]
    probes: list[tuple[str, str]] = []
    if len(words) >= 2 and words[0] == "make":
        target = words[-1]
        directory = words[2] if len(words) >= 4 and words[1] == "-C" else ""
        probes.append((f"{directory}/Makefile".lstrip("/"), f"{target}:"))
    match = re.match(r"^(?:cd (\S+) && )?(?:npm|pnpm|yarn|bun) run (\S+)$", command)
    if match:
        probes.append((f"{match.group(1) or ''}/package.json".lstrip("/"), f'"{match.group(2)}"'))
    if words and words[0] in {"pytest", "ruff", "mypy", "black"}:
        probes.append(("pyproject.toml", f"[tool.{words[0]}"))
    for rel, needle in probes:
        line = _find_line(root, rel, needle)
        if line:
            label = needle.strip(':"[')
            out.append(Evidence(rel, line, f"declares `{label}`"))
    if not out:
        for rel in dict.fromkeys(candidates):
            line = _find_line(root, rel, command)
            if line:
                out.append(Evidence(rel, line, "command appears here"))
                break
    return out


# --------------------------------------------------------------------------
# candidate extractors
# --------------------------------------------------------------------------
_LANG_GLOBS = {
    "Python": ["**/*.py"], "TypeScript": ["**/*.ts", "**/*.tsx"],
    "JavaScript": ["**/*.js", "**/*.jsx", "**/*.mjs"], "Go": ["**/*.go"],
    "Java": ["**/*.java"], "Kotlin": ["**/*.kt"], "Rust": ["**/*.rs"], "Ruby": ["**/*.rb"],
    "C#": ["**/*.cs"], "PHP": ["**/*.php"],
}
_IDIOMATIC = {
    "Python": ("snake_case", "PascalCase"), "Go": ("camelCase", "PascalCase"),
    "Rust": ("snake_case", "PascalCase"), "Ruby": ("snake_case", "PascalCase"),
}


def _style(name: str) -> str:
    if "_" in name.strip("_") and name.strip("_").islower():
        return "snake_case"
    if name[:1].isupper() and not name.isupper() and "_" not in name:
        return "PascalCase"
    if name[:1].islower() and any(c.isupper() for c in name) and "_" not in name:
        return "camelCase"
    if name.isupper() and len(name) > 1:
        return "UPPER_CASE"
    return "lower" if name.islower() else "mixed"


def naming_candidates(index, root: Path) -> list[Rule]:
    rows = index.conn.execute(
        "SELECT s.path, s.name, s.kind, s.line, f.language FROM symbols s "
        "JOIN files f ON f.path = s.path WHERE f.role = 'source' "
        "AND s.kind IN ('function','method') ORDER BY s.path, s.line").fetchall()
    by_lang: dict[str, list] = defaultdict(list)
    for row in rows:
        name = row["name"]
        if name.startswith("__") or len(name) < 4:
            continue  # dunders and tiny names carry no style signal
        by_lang[row["language"]].append(row)
    out: list[Rule] = []
    for lang, items in sorted(by_lang.items()):
        if lang not in _LANG_GLOBS or len(items) < 12:
            continue
        styles = Counter(_style(r["name"].lstrip("_")) for r in items)
        style, count = styles.most_common(1)[0]
        if style in {"lower", "mixed"}:
            continue
        share = count / len(items)
        if share < 0.85:
            continue
        examples = [r for r in items if _style(r["name"].lstrip("_")) == style][:3]
        evidence = [Evidence(r["path"], r["line"], f"`{r['name']}`") for r in examples]
        confidence = min(0.95, 0.6 + 0.35 * share) if len(items) >= 25 else 0.7
        text = (f"{lang} functions and methods use {style} "
                f"({count} of {len(items)} sampled, {share:.0%}); match it in new code.")
        rule = _make("naming", lang.lower().replace("#", "sharp"), text, "rules", evidence,
                     confidence, "measured naming convention; scoped to that language's files",
                     topic=f"{lang.lower().replace('#', 'sharp')}-style", paths=_LANG_GLOBS[lang])
        if rule:
            out.append(rule)
    return out


GENERATED_DIR_SHARE = 0.8  # share of a directory's indexed files that must be generated


def generated_candidates(facts: RepoFacts, index) -> list[Rule]:
    out: list[Rule] = []
    for entry in (facts.conventions.get("generated_paths") or [])[:8]:
        prefix = entry.rstrip("/")
        rows = index.conn.execute(
            "SELECT path FROM files WHERE role='generated' AND (path = ? OR path LIKE ?) "
            "ORDER BY path LIMIT 3", (prefix, prefix + "/%")).fetchall()
        if not rows:
            continue
        if entry.endswith("/"):
            # a directory is "generated output" only when most of it is: one bannered
            # file in tests/ must never declare the whole test suite off-limits
            total, generated = index.conn.execute(
                "SELECT COUNT(*), SUM(role='generated') FROM files WHERE path LIKE ?",
                (prefix + "/%",)).fetchone()
            if not total or (generated or 0) / total < GENERATED_DIR_SHARE:
                continue
        evidence = [Evidence(r["path"], 1, "generated (path pattern or banner)") for r in rows]
        glob = f"{prefix}/**" if entry.endswith("/") else prefix
        text = (f"`{entry}` is generated output: do not hand-edit it; change the generator "
                "or its input and regenerate.")
        rule = _make("generated", prefix, text, "rules", evidence, 0.9,
                     "machine-owned files; only relevant when touching them",
                     topic="generated", paths=[glob])
        if rule:
            out.append(rule)
    return out


def _focused_command(framework: str, command: str) -> str:
    """A placeholder command for running one test (shown in rules/skills)."""
    fw = (framework or "").lower()
    if fw in {"pytest", "fastapi testclient", "hypothesis"} or command.startswith("pytest"):
        return "pytest <path/to/test_file.py>::<test_name>"
    if fw == "vitest":
        return "npx vitest run <path/to/file.test.ts> -t '<name>'"
    if fw in {"jest", "testing library"}:
        return "npx jest <path/to/file.test.ts> -t '<name>'"
    if fw in {"go test", "testify"}:
        return "go test ./<pkg>/ -run '<TestName>'"
    if "junit" in fw or fw in {"testng", "spring boot test", "mockito"}:
        tool = "./gradlew test --tests" if "gradle" in command else "mvn test -Dtest="
        return f"{tool}<ClassName>" if tool.endswith("=") else f"{tool} '<ClassName>'"
    if fw == "rust test":
        return "cargo test <name>"
    if fw in {"xunit", "nunit", "mstest"}:
        return "dotnet test --filter '<TestName>'"
    if fw == "rspec":
        return "bundle exec rspec <path/to/spec.rb>:<line>"
    return ""


def testing_candidates(facts: RepoFacts, index, root: Path) -> list[Rule]:
    from .testing import verification_plan
    out: list[Rule] = []
    # one source of truth for commands: a rule never names a runner the
    # verification plan (and so the CLAUDE.md Verify line) disagrees with
    plan = verification_plan(facts.commands, facts.test_suites)
    planned = [c.command for c in plan.tests]
    for suite in facts.test_suites[:4]:
        if suite.file_count < 2 or not suite.framework or suite.framework == "unknown":
            continue
        rows = index.conn.execute(
            "SELECT path FROM files WHERE role='test' AND path LIKE ? ORDER BY path LIMIT 3",
            ((suite.root.rstrip("/") + "/%") if suite.root not in {".", ""} else "%",)).fetchall()
        evidence = [Evidence(r["path"], 0, f"{suite.framework} test") for r in rows]
        # a suite-specific command (`cd pkg && ...`, `... -s pkg/tests`) may stand on its own;
        # anything else uses the Verify line's command, so the two never disagree
        specific = suite.root not in {"", "."} and suite.root.rstrip("/") in suite.command \
            and suite.command in planned
        command = suite.command if specific else plan.test_command
        evidence += command_evidence(root, facts, command) if command else []
        if not rows:
            continue
        names = [PurePosixPath(r["path"]).name for r in rows]
        pattern = _name_pattern(names)
        focused = _focused_command(suite.framework, command)
        where = f"`{suite.root}/`" if suite.root not in {".", ""} else "the existing test directories"
        parts = [f"Tests here use {suite.framework}; add new tests under {where}"]
        if pattern:
            parts[0] += f" named like `{pattern}`"
        if command:
            parts.append(f"run the suite with `{command}`")
        if focused:
            parts.append(f"a single test with `{focused}`")
        text = "; ".join(parts) + "."
        globs = [f"{suite.root}/**"] if suite.root not in {".", ""} else ["**/test*/**", "**/*test*"]
        confidence = 0.9 if suite.file_count >= 3 else 0.7
        rule = _make("tests", suite.root or "root", text, "rules", evidence, confidence,
                     "test conventions matter only while editing tests",
                     topic="testing", paths=globs)
        if rule:
            out.append(rule)
    return out


def _name_pattern(names: list[str]) -> str:
    if not names:
        return ""
    if all(n.startswith("test_") for n in names):
        return "test_<module>" + PurePosixPath(names[0]).suffix
    for marker in (".test.", ".spec.", "_test."):
        if all(marker in n for n in names):
            ext = names[0].split(marker, 1)[1]
            return f"<name>{marker}{ext}"
    if all(re.search(r"Tests?\.\w+$", n) for n in names):
        return "<Class>Test" + PurePosixPath(names[0]).suffix
    return ""


def lint_candidates(facts: RepoFacts, root: Path) -> list[Rule]:
    out: list[Rule] = []
    from .testing import command_category, instructable
    # static analysis and type checks only: a formatter rewrites files, and
    # neither verifies behaviour, so the rule says it complements the tests
    lint = [c for c in (facts.commands.get("lint") or [])
            if command_category(c, "lint") in {"static", "typecheck"} and instructable(c)][:2]
    for command in lint:
        evidence = command_evidence(root, facts, command)
        if not evidence:
            continue
        role = "type check" if command_category(command, "lint") == "typecheck" else "static analysis"
        text = (f"Also run `{command}` ({role}) on source changes; it complements running the tests "
                "and never replaces them.")
        rule = _make("lint", command, text, "claude-md", evidence, 0.85,
                     "repo-wide quality gate declared in project config", topic="static-analysis")
        if rule:
            out.append(rule)
    return out


def boundary_candidates(facts: RepoFacts, index) -> list[Rule]:
    """One-way dependencies between components. Medium confidence by design:
    a static count cannot prove intent, so these are proposals, never auto-applied."""
    comps = {c.root: c.name for c in facts.components if c.root not in {".", ""}}
    if len(comps) < 2:
        return []
    comp_of = {r["path"]: r["component"] for r in index.conn.execute("SELECT path, component FROM files")}
    roots = {c.name: c.root for c in facts.components}
    pairs: Counter[tuple[str, str]] = Counter()
    sample: dict[tuple[str, str], tuple[str, str]] = {}
    for row in index.conn.execute(
            "SELECT src_path, resolved_path FROM imports WHERE resolved_path != '' ORDER BY src_path"):
        a, b = comp_of.get(row["src_path"], ""), comp_of.get(row["resolved_path"], "")
        if a and b and a != b and a in roots and b in roots and roots[a] in comps and roots[b] in comps:
            pairs[(a, b)] += 1
            sample.setdefault((a, b), (row["src_path"], row["resolved_path"]))
    out: list[Rule] = []
    for (a, b), count in sorted(pairs.items()):
        if count < 3 or pairs.get((b, a), 0):
            continue
        src, dst = sample[(a, b)]
        text = (f"`{roots[a]}/` depends on `{roots[b]}/` ({count} imports) and nothing imports the "
                f"other way; keep that direction (do not import `{roots[a]}/` from `{roots[b]}/`).")
        rule = _make("boundary", f"{a}->{b}", text, "claude-md",
                     [Evidence(src, 0, f"imports {dst}")], 0.6,
                     "architectural direction inferred from the import graph; needs human review")
        if rule:
            out.append(rule)
    return out


def signal_candidates(layout: Layout, facts: RepoFacts) -> list[Rule]:
    """Rules strengthened by local, opt-in signals (edits to generated files)."""
    from .signals import read_signals
    edits = Counter(s.get("key", "") for s in read_signals(layout) if s.get("event") == "edit-generated")
    out: list[Rule] = []
    for prefix, count in sorted(edits.items()):
        if count < 2 or not prefix:
            continue
        text = (f"`{prefix}` is generated: edits there were made {count} times recently and will "
                "be overwritten — change the generator instead.")
        rule = _make("generated-edits", prefix, text, "claude-md",
                     [Evidence(prefix.rstrip("/"), 0, f"{count} edit events (local signals)")],
                     0.85, "recurring mistake observed locally; promoted to an always-loaded rule",
                     source="signals")
        if rule:
            out.append(rule)
    return out


# --------------------------------------------------------------------------
# human-text coverage (dedupe against what people already wrote)
# --------------------------------------------------------------------------
def human_instruction_text(root: Path) -> str:
    chunks: list[str] = []
    for name in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/CLAUDE.md"):
        text = read_text(root / name)
        if text:
            for begin, end in KNOWN_BLOCKS:
                while begin in text and end in text:
                    start = text.find(begin)
                    stop = text.find(end, start) + len(end)
                    text = text[:start] + text[stop:]
            chunks.append(text)
    rules_dir = root / ".claude" / "rules"
    if rules_dir.is_dir():
        for path in sorted(rules_dir.glob("*.md")):
            if not path.name.startswith("repo-ai-"):
                chunks.append(read_text(path) or "")
    return "\n".join(chunks).lower()


def covered_by_human(rule: Rule, human: str) -> bool:
    if not human:
        return False
    if rule.kind == "lint":
        return rule.subject.lower() in human
    if rule.kind == "naming":
        style = re.search(r"use (\w+)", rule.text)
        return bool(style and style.group(1).lower() in human and rule.subject in human)
    if rule.kind in {"generated", "generated-edits"}:
        return rule.subject.lower() in human and ("generated" in human or "do not edit" in human)
    if rule.kind == "tests":
        command = re.search(r"suite with `([^`]+)`", rule.text)
        # people who already wrote how to run the tests keep the say: defer to any
        # documented test command, not only to the exact one repo-ai would pick
        return bool(command and command.group(1).lower() in human) \
            or bool(re.search(r"\btests?\b[^\n`]{0,60}`[^`\n]+`", human))
    return False


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Ledger:
    rules: dict[str, Rule] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, layout: Layout) -> "Ledger":
        path = layout.learning_dir / "ledger.json"
        text = read_text(path)
        ledger = cls(path=path)
        if text:
            try:
                data = json.loads(text)
                for item in data.get("rules", []):
                    rule = Rule.from_json(item)
                    ledger.rules[rule.id] = rule
            except (ValueError, TypeError, KeyError):
                pass
        return ledger

    def render(self) -> str:
        rules = [self.rules[k].to_json() for k in sorted(self.rules)]
        return json.dumps({"version": 1, "rules": rules}, indent=2) + "\n"

    def save(self) -> None:
        assert self.path is not None
        atomic_write(self.path, self.render())

    def active(self) -> list[Rule]:
        return [self.rules[k] for k in sorted(self.rules) if self.rules[k].status == "active"]


@dataclass(slots=True)
class Cycle:
    ledger: Ledger
    changes: list[tuple[str, str, str]] = field(default_factory=list)  # (rule id, from, to)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def generate_candidates(root: Path, layout: Layout, facts: RepoFacts, index,
                        signals: bool = False) -> list[Rule]:
    cands: list[Rule] = []
    cands += testing_candidates(facts, index, root)
    cands += naming_candidates(index, root)
    cands += generated_candidates(facts, index)
    cands += lint_candidates(facts, root)
    cands += boundary_candidates(facts, index)
    if signals:
        cands += signal_candidates(layout, facts)
    unique: dict[str, Rule] = {}
    for rule in cands:
        unique.setdefault(rule.id, rule)
    return [unique[k] for k in sorted(unique)]


def auto_eligible(rule: Rule) -> bool:
    return rule.confidence >= HIGH_CONFIDENCE and rule.risk == "safe"


_BACKTICKED = re.compile(r"`([^`\n]{2,200})`")


def counterevidence(rule: Rule, outcomes: dict[str, tuple[int, int]]) -> str:
    """A rule recommending a command that keeps failing in recorded sessions
    (and never passed) must not be applied automatically."""
    for cmd in _BACKTICKED.findall(rule.text):
        ok, failed = outcomes.get(" ".join(cmd.split()), (0, 0))
        if failed >= 2 and ok == 0:
            return f"`{cmd}` failed in {failed} recorded session run(s) and never passed"
    return ""


def command_outcomes(layout: Layout) -> dict[str, tuple[int, int]]:
    from .episodes import load_all
    counts: dict[str, list[int]] = {}
    for ep in load_all(layout):
        for _, _, cmd, ok in ep.get("commands") or []:
            pair = counts.setdefault(cmd, [0, 0])
            pair[0 if ok else 1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def run_cycle(root: Path, layout: Layout, facts: RepoFacts, index, policy: str,
              signals: bool = False, apply_ids: tuple[str, ...] = (),
              apply_safe: bool = False, reject_ids: tuple[str, ...] = ()) -> Cycle:
    ledger = Ledger.load(layout)
    outcomes = command_outcomes(layout)
    cycle = Cycle(ledger)
    if policy == "off" and not apply_ids and not apply_safe:
        return cycle
    now = _now()
    human = human_instruction_text(root)
    candidates = generate_candidates(root, layout, facts, index, signals)
    seen: set[str] = set()

    def move(rule: Rule, status: str, note: str = "") -> None:
        if rule.status != status:
            cycle.changes.append((rule.id, rule.status, status))
            rule.status = status
            rule.updated_at = now
            if note:
                rule.note = note

    for cand in candidates:
        seen.add(cand.id)
        existing = ledger.rules.get(cand.id)
        if existing is None:
            cand.created_at = cand.updated_at = now
            cand.status = "proposed"
            ledger.rules[cand.id] = cand
            cycle.changes.append((cand.id, "new", "proposed"))
            existing = cand
        elif existing.evidence_hash != cand.evidence_hash:
            # Evidence moved: refresh text and pointers; an active rule stays
            # active only if it is still auto-eligible, else it is re-proposed.
            was = existing.status
            cand.created_at = existing.created_at
            cand.version = existing.version + 1
            cand.status = was
            cand.updated_at = now
            ledger.rules[cand.id] = cand
            cycle.changes.append((cand.id, f"{was}@v{existing.version}", f"{was}@v{cand.version}"))
            existing = cand
            if was in {"rejected", "retired"}:
                move(existing, "proposed", "evidence changed since it was set aside")
            elif was == "active" and not (policy in AUTO_POLICIES and auto_eligible(existing)):
                move(existing, "proposed", "evidence changed; needs review")
        if existing.status not in {"rejected"} and covered_by_human(existing, human):
            move(existing, "covered", "already stated in human-written instructions")
            continue
        if existing.status == "covered" and not covered_by_human(existing, human):
            move(existing, "proposed", "no longer covered by human instructions")
        if existing.id in reject_ids:
            move(existing, "rejected", "rejected by user")
            continue
        counter = counterevidence(existing, outcomes)
        if existing.status == "active" and counter and existing.note.startswith("auto-applied"):
            move(existing, "proposed", f"counterevidence: {counter}; needs review")
            continue
        if existing.status == "proposed":
            if existing.id in apply_ids:
                move(existing, "active", "applied by user")
            elif (apply_safe or policy in AUTO_POLICIES) and auto_eligible(existing):
                if counter:
                    existing.note = f"not auto-applied — counterevidence: {counter}"
                else:
                    move(existing, "active", "auto-applied (high confidence, safe)")

    for rid, rule in ledger.rules.items():
        if rid not in seen and rule.status in {"active", "proposed", "covered"}:
            move(rule, "retired", "evidence no longer present")
    return cycle


# --------------------------------------------------------------------------
# history and rollback
# --------------------------------------------------------------------------
def record_event(layout: Layout, kind: str, changes: list[tuple[str, str, str]],
                 files: list[tuple[str, str | None, str | None]]) -> str:
    """Append a history event with before/after snapshots of touched files."""
    event_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    snap_dir = layout.learning_dir / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(snap_dir / f"{event_id}.json", json.dumps({
        "files": [{"path": p, "before": b, "after": a} for p, b, a in files]}, indent=1) + "\n")
    line = json.dumps({"id": event_id, "at": _now(), "kind": kind,
                       "changes": [list(c) for c in changes],
                       "files": [p for p, _, _ in files]}, sort_keys=True)
    hist = layout.learning_dir / "history.jsonl"
    previous = read_text(hist) or ""
    atomic_write(hist, previous + line + "\n")
    _prune_snapshots(snap_dir, keep=40)
    return event_id


def _prune_snapshots(snap_dir: Path, keep: int) -> None:
    snaps = sorted(snap_dir.glob("*.json"))
    for old in snaps[:-keep] if len(snaps) > keep else []:
        try:
            old.unlink()
        except OSError:
            pass


def history(layout: Layout) -> list[dict[str, Any]]:
    out = []
    for line in (read_text(layout.learning_dir / "history.jsonl") or "").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def load_snapshot(layout: Layout, event_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9]{14}-[0-9a-f]{6}", event_id):
        return None
    text = read_text(layout.learning_dir / "snapshots" / f"{event_id}.json")
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None
