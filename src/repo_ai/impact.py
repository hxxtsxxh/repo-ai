"""Change-impact analysis: `repo-ai impact <path | symbol | --changed>`.

Static and explainable. For each target file it reports:

  * direct and transitive importers (reverse import graph, bounded depth),
  * tests: linked by import (strong) or naming convention (weaker), plus
    tests of the direct importers,
  * routes defined in the affected files,
  * CI / build files that mention the file's directory or component,
  * co-change partners from git history,
  * focused test commands for the linked tests,
  * explicit uncertainty: what a static import graph cannot see.

It never claims runtime completeness.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .index import Index
from .models import RepoFacts


@dataclass(slots=True)
class Impact:
    targets: list[str]
    unresolved: list[str] = field(default_factory=list)
    importers: dict[str, int] = field(default_factory=dict)  # path -> depth
    tests: dict[str, str] = field(default_factory=dict)      # test path -> evidence
    routes: list[dict[str, object]] = field(default_factory=list)
    ci: list[str] = field(default_factory=list)
    cochange: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    resolution_rate: float = 0.0
    risk: str = "low"

    def to_json(self) -> dict[str, object]:
        return {
            "targets": self.targets, "unresolved": self.unresolved,
            "risk": self.risk,
            "importers": [{"path": p, "depth": d} for p, d in
                          sorted(self.importers.items(), key=lambda kv: (kv[1], kv[0]))],
            "tests": [{"path": p, "evidence": e} for p, e in sorted(self.tests.items())],
            "routes": self.routes, "ci_and_build": self.ci, "co_changes_with": self.cochange,
            "components": self.components, "suggested_commands": self.commands,
            "import_resolution_rate": round(self.resolution_rate, 3),
            "uncertainty": self.uncertainty,
        }


def resolve_targets(index: Index, raw: list[str]) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    unresolved: list[str] = []
    all_paths = [r["path"] for r in index.all_files()]
    for item in raw:
        item = item.strip().lstrip("./")
        if not item:
            continue
        if index.get_file(item) is not None:
            targets.append(item)
            continue
        suffix = [p for p in all_paths if p.endswith("/" + item)]
        if len(suffix) == 1:
            targets.append(suffix[0])
            continue
        symbols = index.find_symbol(item, limit=8)
        exact = sorted({r["path"] for r in symbols if r["name"] == item})
        if exact:
            targets.extend(p for p in exact[:5] if p not in targets)
            continue
        unresolved.append(item)
    return list(dict.fromkeys(targets)), unresolved


def analyze_impact(index: Index, facts: RepoFacts | None, raw_targets: list[str],
                   max_depth: int = 3, root: Path | None = None) -> Impact:
    targets, unresolved = resolve_targets(index, raw_targets)
    result = Impact(targets=targets, unresolved=unresolved)
    if not targets:
        result.uncertainty.append("no target matched an indexed file or symbol")
        return result

    # reverse import BFS
    queue = deque((t, 0) for t in targets)
    seen = set(targets)
    while queue:
        path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for importer in index.importers_of(path, limit=200):
            if importer not in seen:
                seen.add(importer)
                result.importers[importer] = depth + 1
                queue.append((importer, depth + 1))

    # tests
    rows = {r["path"]: r for r in index.all_files()}
    for path in targets:
        for row in index.tests_for(path):
            result.tests.setdefault(row["test_path"], row["evidence"])
        if rows.get(path) and rows[path]["role"] == "test":
            result.tests.setdefault(path, "target")
    for importer, depth in result.importers.items():
        if rows.get(importer) and rows[importer]["role"] == "test":
            result.tests.setdefault(importer, f"imports affected code (depth {depth})")
        elif depth == 1:
            for row in index.tests_for(importer):
                result.tests.setdefault(row["test_path"], "tests a direct importer")

    # routes
    affected = set(targets) | {p for p, d in result.importers.items() if d == 1}
    for row in index.routes(2000):
        if row["file"] in affected:
            result.routes.append({"method": row["method"], "path": row["path_pattern"],
                                  "file": row["file"], "line": row["line"]})

    # co-change
    for path in targets:
        for peer in index.coupled_with(path, limit=6):
            if peer not in result.cochange and peer not in targets:
                result.cochange.append(peer)

    # components and CI/build references
    comps = sorted({rows[p]["component"] for p in targets if p in rows and rows[p]["component"]})
    result.components = comps
    ci_files = list((facts.ci_workflows if facts else []) or [])
    build_files = [p for p, r in rows.items() if r["role"] == "build"]
    probes = set()
    for path in targets:
        parent = str(PurePosixPath(path).parent)
        if parent and parent != ".":
            probes.add(parent.split("/")[0])
            probes.add(parent)
    for ci in ci_files + build_files:
        text = _read(root, ci) if root else ""
        if ci in ci_files and (not probes or any(p in text for p in probes) or not text):
            result.ci.append(ci)
        elif text and any(re.search(rf"(^|[\s/'\"]){re.escape(p)}([\s/'\"]|$)", text) for p in probes):
            result.ci.append(ci)
    result.ci = sorted(dict.fromkeys(result.ci))[:12]

    # suggested commands
    if facts:
        suites = sorted(facts.test_suites, key=lambda s: -len(s.root))
        for test in sorted(result.tests):
            suite = next((s for s in suites if s.root in {"", "."}
                          or test.startswith(s.root.rstrip("/") + "/")), None)
            if suite is None:
                continue
            command = _focused_for(suite.framework, suite.command, test)
            if command and command not in result.commands:
                result.commands.append(command)
            if len(result.commands) >= 6:
                break
        if not result.commands:
            from .testing import verification_plan
            full = verification_plan(facts.commands, facts.test_suites).test_command
            if full:
                result.commands.append(full)

    # uncertainty
    total = index.conn.execute("SELECT COUNT(*) AS n FROM imports").fetchone()["n"]
    resolved = index.conn.execute(
        "SELECT COUNT(*) AS n FROM imports WHERE resolved_path != ''").fetchone()["n"]
    external = index.conn.execute(
        "SELECT COUNT(*) AS n FROM imports WHERE external_package != ''").fetchone()["n"]
    internal = max(total - external, 0)
    result.resolution_rate = resolved / internal if internal else 1.0
    result.uncertainty.append(
        "static import graph only: dynamic imports, reflection, dependency injection, "
        "plugin registries and string-based routing are not visible")
    if result.resolution_rate < 0.9:
        result.uncertainty.append(
            f"{result.resolution_rate:.0%} of non-package imports resolved to files; "
            "some importers may be missing")
    if not result.tests:
        result.uncertainty.append("no linked tests found: coverage of this code is unknown, "
                                  "not necessarily absent")
    if unresolved:
        result.uncertainty.append(f"not found in the index: {', '.join(unresolved)}")

    n = len(result.importers)
    if n >= 15 or len(result.routes) >= 5:
        result.risk = "high"
    elif n >= 4 or result.routes or not result.tests or result.resolution_rate < 0.5:
        result.risk = "medium"
    if result.resolution_rate < 0.5:
        result.uncertainty.append(
            "risk is at least medium because under half of the imports resolved: "
            "the importer and test lists may be far from complete")
    return result


def _focused_for(framework: str, suite_command: str, test_path: str) -> str:
    """A concrete command that runs one test file. Repository paths are quoted:
    a file named `test_$(touch x).py` must not become shell syntax."""
    import shlex
    fw = (framework or "").lower()
    prefix = ""
    match = re.match(r"^(cd \S+ && )", suite_command or "")
    if match:
        prefix = match.group(1)
        base = prefix[3:-4].strip("'").rstrip("/") + "/"
        if test_path.startswith(base):
            test_path = test_path[len(base):]
    path = shlex.quote(test_path)
    stem = shlex.quote(PurePosixPath(test_path).stem)
    if fw in {"pytest", "fastapi testclient", "hypothesis"} or suite_command.startswith("pytest") \
            or (test_path.endswith(".py") and fw in {"", "unknown", "unittest"}):
        return f"{prefix}pytest {path}" if fw != "unittest" else f"{prefix}python -m unittest {path}"
    if fw == "vitest":
        return f"{prefix}npx vitest run {path}"
    if fw in {"jest", "testing library"}:
        return f"{prefix}npx jest {path}"
    if fw in {"go test", "testify"} or test_path.endswith("_test.go"):
        return f"{prefix}go test {shlex.quote('./' + str(PurePosixPath(test_path).parent) + '/')}"
    if ("junit" in fw or fw in {"testng", "spring boot test"}) and test_path.endswith((".java", ".kt")):
        if "gradle" in suite_command:
            return f"{prefix}./gradlew test --tests {stem}"
        tool = "./mvnw" if "./mvnw" in suite_command else "mvn"
        return f"{prefix}{tool} test -Dtest={stem}"
    if fw in {"xunit", "nunit", "mstest"}:
        return f"{prefix}dotnet test --filter {stem}"
    if fw == "rspec":
        return f"{prefix}bundle exec rspec {path}"
    return suite_command


def _read(root: Path | None, rel: str) -> str:
    if root is None:
        return ""
    try:
        return (root / rel).read_text("utf-8", errors="replace")[:200_000]
    except OSError:
        return ""


def render_impact(result: Impact) -> str:
    out: list[str] = []
    out.append(f"impact of: {', '.join(result.targets) or '(nothing matched)'}   risk: {result.risk}")
    if result.components:
        out.append(f"component(s): {', '.join(result.components)}")
    direct = sorted(p for p, d in result.importers.items() if d == 1)
    indirect = sorted(p for p, d in result.importers.items() if d > 1)
    out.append(f"\ndirect importers ({len(direct)}):")
    out += [f"  {p}" for p in direct[:25]] or ["  (none found)"]
    if indirect:
        out.append(f"transitive importers ({len(indirect)}):")
        out += [f"  {p}  (depth {result.importers[p]})" for p in indirect[:20]]
        if len(indirect) > 20:
            out.append(f"  … and {len(indirect) - 20} more")
    out.append(f"\ntests ({len(result.tests)}):")
    out += [f"  {p}  [{e}]" for p, e in sorted(result.tests.items())[:20]] or ["  (none linked)"]
    if result.routes:
        out.append("\nroutes in affected files:")
        out += [f"  {r['method']} {r['path']}  {r['file']}:{r['line']}" for r in result.routes[:20]]
    if result.ci:
        out.append("\nCI / build files referencing this area:")
        out += [f"  {p}" for p in result.ci]
    if result.cochange:
        out.append("\nhistorically changes together with:")
        out += [f"  {p}" for p in result.cochange]
    if result.commands:
        out.append("\nsuggested commands (focused first; read before running):")
        out += [f"  {c}" for c in result.commands]
    out.append("\nuncertainty:")
    out += [f"  - {u}" for u in result.uncertainty]
    return "\n".join(out)
