"""Which tests can show whether this change broke something, and how sure
that answer is.

A test is selected when **any** evidence links it to the change (union, never
intersection):

* ``changed-test``      the test file itself changed;
* ``runtime``           recorded evidence shows it executed a changed code
                        unit (function, method, class body, module code) or
                        opened a changed data file;
* ``static``            it reaches a changed file through the import graph
                        (the full transitive closure; package ``__init__``
                        changes reach every importer of the package);
* ``literal-load``      a loader names the changed module literally;
* ``string-reference``  it (or a module it imports) names the changed module
                        or a registered entry-point name in a string.

Full-suite **triggers** (confidence "low") are explicit: changed test or
build configuration, a changed test helper with no evidence of its users,
a module reachable through computed-name loading without fresh runtime
evidence, a changed file nothing explains, an opaque test runner.

The plan never calls a change safe. Its strongest statement is
"high: every changed code unit has fresh runtime evidence".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .changes import Change, ChangedFile
from .dynamic import DynamicFacts
from .runner import TestRunner
from .testmap import TestMap

CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx"}
CONFIG_NAMES = {"pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", ".pytest.ini", "pytest.toml",
                ".pytest.toml", "conftest.py",
                "noxfile.py", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "package.json",
                "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", ".python-version",
                ".nvmrc", ".node-version", "Makefile", "jest.config.js", "vitest.config.ts",
                "vitest.config.js", ".mocharc.json", "babel.config.js", "manage.py"}
DOC_SUFFIXES = {".md", ".rst", ".adoc"}
DOC_NAMES = {"LICENSE", "LICENSE.txt", "LICENSE.md", "CHANGELOG", "CHANGES", "AUTHORS", "NOTICE",
             "CONTRIBUTING", "COPYING"}
MAX_GRAPH = 50_000
MAX_REASONS_PER_KIND = 3


@dataclass(slots=True)
class Reason:
    kind: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, **({"evidence": self.evidence} if self.evidence else {})}


STRENGTH = {"changed-test": 0, "runtime": 1, "static": 2, "literal-load": 3, "string-reference": 4,
            "test-helper": 5, "naming": 6}


@dataclass(slots=True)
class Selected:
    test: str
    reasons: list[Reason] = field(default_factory=list)
    duration_s: float | None = None

    @property
    def strength(self) -> int:
        return min(STRENGTH.get(r.kind, 9) for r in self.reasons)

    def to_json(self) -> dict[str, Any]:
        return {"test": self.test, "duration_s": self.duration_s,
                "reasons": [r.to_json() for r in self.reasons]}


@dataclass(slots=True)
class FileFinding:
    path: str
    kind: str                       # source | test | test-helper | config | docs | data
    status: str
    behavioral: bool = True
    changed_units: list[str] = field(default_factory=list)
    runtime: str = "none"           # fresh | stale | none | unsupported
    never_executed: list[str] = field(default_factory=list)  # changed units no recorded test runs
    exposure: list[dict[str, Any]] = field(default_factory=list)
    consumers: int = 0              # tests linked to this file
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "kind": self.kind, "status": self.status, "behavioral": self.behavioral,
                "changed_units": self.changed_units, "runtime_evidence": self.runtime,
                "never_executed_by_tests": self.never_executed, "dynamic_exposure": self.exposure,
                "linked_tests": self.consumers, "notes": self.notes}


@dataclass(slots=True)
class Plan:
    base: str
    fingerprint: str
    runner: TestRunner
    files: list[FileFinding]
    selected: list[Selected]
    universe: int
    confidence: str                 # high | medium | low | none
    full_suite_required: bool
    triggers: list[str]
    uncertainty: list[str]
    targeted_commands: list[str]
    full_command: str
    estimate: dict[str, Any]
    universe_files: list[str] = field(default_factory=list)  # every test file of the runner
    durations: dict[str, float | None] = field(default_factory=dict)  # recorded per-file run times
    duplicates: dict[str, str] = field(default_factory=dict)  # selected aggregators a targeted run skips, and why
    durations_backend: str = ""  # the sandbox backend `durations` were recorded in

    def to_json(self) -> dict[str, Any]:
        return {"schema": "repo-ai.verify-plan/1", "base": self.base, "fingerprint": self.fingerprint,
                "confidence": self.confidence, "full_suite_required": self.full_suite_required,
                "triggers": self.triggers, "uncertainty": self.uncertainty,
                "runner": self.runner.to_json(),
                "test_files_total": self.universe, "selected": [s.to_json() for s in self.selected],
                "targeted_commands": self.targeted_commands, "full_suite_command": self.full_command,
                "estimate": self.estimate, "changed_files": [f.to_json() for f in self.files],
                "aggregators_skipped": self.duplicates,
                "never_claims": "a passing targeted run is evidence about the selected tests only; "
                                "it is not proof that the change is correct"}


# --------------------------------------------------------------------------
def _is_test_unit(key: str) -> bool:
    return key.partition(":")[2].startswith("test")


def _aggregators(picks: dict[str, Selected], tmap: TestMap, universe: set[str], change: Change) -> dict[str, str]:
    """Selected test files that only re-run other test files' tests (a
    package `__init__` that imports every test module, a `load_tests`
    collector) and add no evidence of their own: every changed code unit
    they executed was also executed by another selected file. A targeted run
    skips them, so the same tests do not run twice; the full suite still runs
    them. Python runtime evidence only; anything less certain keeps them."""
    changed: dict[str, set[str]] = {}
    for cf in change.files:
        if not cf.behavioral:
            continue
        if not cf.path.endswith(".py") or not cf.units or cf.status in {"added", "deleted"}:
            return {}  # evidence the rule cannot reason about: keep every selected file
        changed[cf.old_path or cf.path] = set(cf.units)
    out: dict[str, str] = {}
    selected = set(picks)
    for test, sel in picks.items():
        rec = tmap.tests.get(test) or {}
        units = rec.get("units") or {}
        runtime = [r for r in sel.reasons if r.kind == "runtime"]
        if not tmap.complete(test) or not runtime or any("units" not in r.evidence for r in runtime):
            continue
        if any(r.kind not in {"runtime", "static", "inferred", "naming"} for r in sel.reasons):
            continue
        if any(_is_test_unit(k) for k in units.get(test, [])):
            continue  # it defines tests of its own
        if not _only_imports(change.root, test):
            continue  # it runs code of its own (sets a flag, configures): the same tests in another context
        others = sorted(b for b, keys in units.items() if b != test and b in universe and
                        any(_is_test_unit(k) for k in keys))
        if not others:
            continue
        covered = True
        for path, keys in changed.items():
            for key in keys & set(units.get(path, [])):
                if not any(key in set(((tmap.tests.get(b) or {}).get("units") or {}).get(path, []))
                           for b in selected - {test} if tmap.complete(b) and b not in out):
                    covered = False
        if covered:
            out[test] = (f"re-runs the tests of {len(others)} other test file(s) (as recorded) and defines none; "
                         "every changed unit it executed is also executed by another selected file")
    return out


def _only_imports(root, test: str) -> bool:
    """The module's top level is imports, a docstring, `__all__`, a
    `__main__` guard and a `load_tests` that only collects
    (`_only_collects`): nothing that could make the tests it imports run any
    differently than in their own files."""
    import ast
    try:
        tree = ast.parse((root / test).read_bytes())
    except (OSError, SyntaxError, ValueError, RecursionError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if isinstance(node, ast.If) and "__name__" in ast.dump(node.test) and "__main__" in ast.dump(node.test):
            continue
        if isinstance(node, ast.FunctionDef) and node.name == "load_tests" and _only_collects(node):
            continue
        return False
    return True


_COLLECT_ROOTS = {"unittest", "os", "Path", "pathlib", "str", "len", "list", "sorted", "set"}


def _only_collects(fn) -> bool:
    """A `load_tests` that builds a suite from what it is given and changes
    nothing else: no attribute or item assignment, no `global`, no doctest
    (a doctest is a test of its own), and calls only on its own names and
    `unittest`/`os`."""
    import ast
    local = {a.arg for a in fn.args.args} | {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                                            and isinstance(n.ctx, ast.Store)}
    for node in ast.walk(fn):
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.Delete)):
            return False
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(not isinstance(t, (ast.Name, ast.Tuple)) for t in targets):
                return False
        if isinstance(node, ast.Call):
            root = node.func
            while isinstance(root, (ast.Attribute, ast.Call, ast.Subscript)):
                root = root.value if not isinstance(root, ast.Call) else root.func
            if not isinstance(root, ast.Name) or (root.id not in local and root.id not in _COLLECT_ROOTS):
                return False
        if isinstance(node, (ast.Name, ast.Attribute)) and "doctest" in ast.dump(node).lower():
            return False
    return True


def _matches_prefix(path: str, module: str, prefix: str) -> bool:
    if "/" in prefix or prefix.startswith("."):
        clean = prefix.lstrip("./")
        return bool(clean) and path.startswith(clean)
    return bool(module) and (module + ".").startswith(prefix) and module + "." != prefix


class Graph:
    """The repository's resolved import graph, reversed (who imports whom)."""

    def __init__(self, edges: list[tuple[str, str]], files: list[str]):
        self.imports: dict[str, set[str]] = {}  # import edges only, reversed
        self.inferred: set[tuple[str, str]] = set()  # (referencer, target) edges from strings/loaders
        self.computed: set[tuple[str, str]] = set()  # inferred edges that are computed-name loads
        for src, dst in edges:
            if src != dst:
                self.imports.setdefault(dst, set()).add(src)
        self.reverse: dict[str, set[str]] = {k: set(v) for k, v in self.imports.items()}
        self.files = set(files)

    def add_inferred(self, dyn: DynamicFacts) -> None:
        """A string reference or a literal load is a dependency the import
        graph cannot see (`subprocess.run([python, "-m", "pkg.tool"])`,
        `import_module("pkg.ext")`): follow it like an import."""
        for target, sites in [*dyn.string_refs.items(), *dyn.literal_loads.items()]:
            for site in sites:
                if site.path != target:
                    self.reverse.setdefault(target, set()).add(site.path)
                    self.inferred.add((site.path, target))
        # a loader with a known prefix (`import_module("pkg.providers." + name)`) may load any
        # module under it: an edge from the loader to each, marked as computed-name loading
        for site in dyn.loaders:
            if not site.prefix:
                continue
            for target, module in dyn.modules.items():
                if target != site.path and _matches_prefix(target, module, site.prefix):
                    self.reverse.setdefault(target, set()).add(site.path)
                    self.inferred.add((site.path, target))
                    self.computed.add((site.path, target))

    def computed_hop(self, chain: list[str]) -> tuple[str, str] | None:
        """The first computed-name load on a chain (consumer -> ... -> changed file)."""
        return next((hop for hop in zip(chain, chain[1:], strict=False) if hop in self.computed), None)

    def chain_kind(self, chain: list[str]) -> str:
        hops = zip(chain, chain[1:], strict=False)
        return "string-reference" if any(hop in self.inferred for hop in hops) else "static"

    @classmethod
    def from_index(cls, index, files: list[str]) -> Graph:
        rows = index.conn.execute(
            "SELECT DISTINCT src_path, resolved_path FROM imports WHERE resolved_path != ''").fetchall()
        return cls([(r["src_path"], r["resolved_path"]) for r in rows], files)

    def closure(self, seeds: list[str]) -> dict[str, list[str]]:
        """Every file that transitively imports a seed -> the import chain
        (file, ..., seed) that links it."""
        chains: dict[str, list[str]] = {s: [s] for s in seeds}
        # imports first, so a file reached both ways is explained by its import chain;
        # then inferred edges reach the rest (the set of files is the same either way)
        for edges in (self.imports, self.reverse):
            queue = deque(chains)
            while queue and len(chains) < MAX_GRAPH:
                cur = queue.popleft()
                for importer in sorted(edges.get(cur, ())):
                    if importer not in chains:
                        chains[importer] = [importer, *chains[cur]]
                        queue.append(importer)
        return chains

    def package_members(self, init_path: str) -> list[str]:
        pkg = str(PurePosixPath(init_path).parent)
        prefix = "" if pkg in {"", "."} else pkg + "/"
        return sorted(f for f in self.files if f.startswith(prefix) and f.endswith(".py"))


def classify(path: str, universe: set[str], runner: TestRunner) -> str:
    p = PurePosixPath(path)
    if path in universe:
        return "test"
    if p.name in CONFIG_NAMES or p.name.startswith(("requirements", "tsconfig", "jest.config", "vitest.")):
        return "config"
    if p.suffix.lower() in DOC_SUFFIXES or p.name in DOC_NAMES or (p.parts and p.parts[0] in {"docs", "doc"}):
        return "docs"
    if p.suffix.lower() in CODE_SUFFIXES:
        # a helper lives under a test directory itself (tests/, pkg/test/); sharing a
        # top-level package with the tests (pyflakes/ and pyflakes/test/) does not count
        test_dirs = {str(PurePosixPath(t).parent) for t in universe}
        in_tests = any(part in {"test", "tests", "testing", "__tests__", "spec", "specs"} for part in p.parts[:-1]) \
            or str(p.parent) in test_dirs and str(p.parent) not in {"", "."}
        return "test-helper" if in_tests else "source"
    return "data"


def plan(change: Change, runner: TestRunner, repo_files: list[str], graph: Graph,
         dyn: DynamicFacts, tmap: TestMap | None = None, index_head: str = "",
         name_links: dict[str, list[str]] | None = None) -> Plan:
    universe_list = runner.test_files(repo_files) if runner.per_file else []
    universe = set(universe_list)
    picks: dict[str, Selected] = {}
    findings: list[FileFinding] = []
    triggers: list[str] = []
    uncertainty: list[str] = []

    def pick(test: str, reason: Reason) -> None:
        if test not in universe:
            return
        sel = picks.setdefault(test, Selected(test))
        same_kind = [r for r in sel.reasons if r.kind == reason.kind]
        if len(same_kind) < MAX_REASONS_PER_KIND and not any(r.detail == reason.detail for r in same_kind):
            sel.reasons.append(reason)

    if runner.kind == "opaque":
        triggers.append(f"the test command `{runner.command}` cannot be split into per-file runs; "
                        "only the full suite can verify this change")
    if index_head and change.base_commit and not change.base_commit.startswith(index_head):
        uncertainty.append(f"the repository index was built at {index_head[:12]}, not at the base "
                           f"{change.base_commit[:12]}; run `repo-ai update` for an exact static graph")
    if tmap is not None and tmap.runner.get("command") != runner.command:
        uncertainty.append("runtime evidence was recorded with a different test command; it is ignored")
        tmap = None

    for cf in change.files:
        kind = classify(cf.path, universe, runner)
        f = FileFinding(cf.path, kind, cf.status, cf.behavioral, list(cf.unit_names))
        findings.append(f)
        if cf.binary and kind not in {"docs"}:
            f.notes.append("binary file")
        if not cf.behavioral:
            f.notes.append(cf.why_not_behavioral or "no behavioural change (only comments or formatting differ)")
            continue
        if kind == "docs":
            for test in _string_or_runtime_users(cf, dyn, tmap, graph):
                pick(test, Reason("string-reference", f"references {cf.path}"))
            f.notes.append("documentation: no test needed unless a test reads it")
            continue
        if kind == "test":
            if cf.status != "deleted":
                pick(cf.path, Reason("changed-test", "this test file changed"))
            f.consumers = 1
            if cf.path not in set(runner.included):
                continue
            # a module pytest collects for its doctests (`--doctest-modules`) is also source
            # code other tests import: the tests linked to it run too
        if kind == "config":
            triggers.append(f"{cf.path} changed: test, build or dependency configuration affects every test")
            continue
        if kind == "data":
            users = _string_or_runtime_users(cf, dyn, tmap, graph)
            for test in users:
                pick(test, Reason("runtime" if tmap and cf.path in _opened(tmap) else "string-reference",
                                  f"reads or names {cf.path}"))
            f.consumers = len(users)
            if not users:
                triggers.append(f"{cf.path} changed and no evidence shows which tests depend on it")
            continue
        # source or test helper ------------------------------------------------
        linked = _source(cf, f, runner, graph, dyn, tmap, universe, pick, name_links or {})
        f.consumers = linked
        if kind == "test-helper" and not linked:
            triggers.append(f"test helper {cf.path} changed and no evidence links it to specific tests")
        if f.exposure and f.runtime != "fresh":
            triggers.append(f"{cf.path} may be loaded by a computed name ({f.exposure[0]['detail']}); "
                            "static imports cannot list its consumers")
        if kind == "source" and not linked and not f.exposure:
            if f.runtime == "fresh":
                uncertainty.append(f"no test executes the changed code in {cf.path} "
                                   f"({', '.join(f.never_executed) or 'any of it'}): the change is untested")
            elif f.runtime == "unobserved":
                uncertainty.append(f"no recorded test executes, loads or opens {cf.path}, and no static link "
                                   "reaches it: the change appears untested")
            elif cf.status == "added":
                uncertainty.append(f"{cf.path} is new and nothing imports it yet")
            else:
                triggers.append(f"no test reaches {cf.path} through imports and there is no runtime "
                                "evidence for it")

    duplicates = _aggregators(picks, tmap, universe, change) if tmap is not None else {}
    selected = sorted(picks.values(), key=lambda s: (s.strength, (tmap.duration(s.test) if tmap else None) or 0,
                                                     s.test))
    for sel in selected:
        sel.duration_s = tmap.duration(sel.test) if tmap else None
        sel.reasons.sort(key=lambda r: STRENGTH.get(r.kind, 9))

    behavioral = [f for f in findings if f.behavioral and f.kind in {"source", "test-helper"}]
    if not change.files:
        confidence = "none"
        uncertainty.append("no changes against the base")
    elif triggers:
        confidence = "low"
    elif behavioral and all(f.runtime == "fresh" for f in behavioral):
        confidence = "high"
    elif not behavioral and all(f.kind in {"docs", "test"} or not f.behavioral for f in findings):
        confidence = "high"
    else:
        confidence = "medium"
    full_required = confidence == "low"
    if tmap is None and behavioral:
        uncertainty.append("no runtime evidence: selection rests on static imports only "
                           "(`repo-ai verify --record` records which code each test executes)")
    if tmap is not None:
        failing = [t for t in tmap.baseline_failures() if t in universe]
        if failing and tmap.uncommitted:  # what failed then says nothing about the base
            uncertainty.append(f"{len(failing)} test file(s) failed when evidence was recorded with uncommitted "
                               "changes to " + ", ".join(tmap.uncommitted[:3])
                               + (" …" if len(tmap.uncommitted) > 3 else "")
                               + "; that is not the base (`repo-ai verify --record` on a clean tree records it): "
                               + ", ".join(failing[:5]))
        elif failing:
            uncertainty.append(f"{len(failing)} test file(s) already failed when evidence was recorded: "
                               + ", ".join(failing[:5]))

    targeted: list[str] = []
    if runner.per_file and selected:
        targeted = [runner.display(argv) for argv in runner.group_argvs([s.test for s in selected])]
    full = runner.display(runner.full) if runner.full else runner.command
    estimate: dict[str, Any] = {"selected_test_files": len(selected), "test_files_total": len(universe)}
    if tmap is not None and universe:
        known = {t: tmap.duration(t) for t in universe}
        total = sum(d for d in known.values() if d)
        chosen = sum(known.get(s.test) or 0 for s in selected)
        if total:
            estimate.update(selected_seconds=round(chosen, 2), full_suite_seconds=round(total, 2),
                            share_of_suite_time=round(chosen / total, 3))
    return Plan(change.base, change.fingerprint, runner, findings, selected, len(universe), confidence,
                full_required, triggers, uncertainty, targeted, full, estimate, sorted(universe_list),
                {t: tmap.duration(t) for t in universe} if tmap is not None else {}, duplicates,
                tmap.backend if tmap is not None else "")


def _opened(tmap: TestMap) -> set[str]:
    return {p for rec in tmap.tests.values() for p in rec.get("opened") or []}


def _string_or_runtime_users(cf: ChangedFile, dyn: DynamicFacts, tmap: TestMap | None, graph: Graph) -> list[str]:
    users: set[str] = set()
    if tmap is not None:
        users.update(t for t, rec in tmap.tests.items() if cf.path in (rec.get("opened") or []))
    refs = [s.path for s in dyn.string_refs.get(cf.path, [])]
    if refs:
        users.update(graph.closure(refs))
    return sorted(users)


def _source(cf: ChangedFile, f: FileFinding, runner: TestRunner, graph: Graph, dynamic_facts: DynamicFacts,
            tmap: TestMap | None, universe: set[str], pick, name_links: dict[str, list[str]]) -> int:
    """Link tests to one changed source file.

    Static and inferred links are always computed. When the file has fresh
    runtime evidence, that evidence is authoritative for every test whose
    recording is complete (it passed and was traced): a deterministic test
    that never executed a changed code unit cannot observe the change.
    Definition-time code (module and class bodies) counts as executed by
    every test that imported it. Tests without complete evidence keep their
    static links."""
    path = cf.old_path or cf.path
    static: dict[str, list[Reason]] = {}
    seeds = [path]
    if PurePosixPath(path).name == "__init__.py":  # a package __init__ reaches its whole package
        seeds += [m for m in graph.package_members(path) if m != path]
    chains = graph.closure(seeds)
    static_importers = [p for p in chains if p not in seeds and p not in universe]
    for test, chain in chains.items():
        if test in universe:
            kind = graph.chain_kind(chain)
            verb = "reaches" if kind != "static" else "imports"
            static.setdefault(test, []).append(Reason(
                kind, f"{verb} " + " -> ".join(chain[1:]) if len(chain) > 1 else "is the changed file",
                {"chain": chain}))
    for test in name_links.get(path, []):
        if test in universe:
            static.setdefault(test, []).append(Reason("naming", f"test name matches {path}"))
    if path.endswith(".py"):
        for site in dynamic_facts.source_readers:  # globs source files and reads them as data
            for test, chain in graph.closure([site.path]).items():
                if test in universe:
                    static.setdefault(test, []).append(Reason(
                        "string-reference", f"{site.path}:{site.line} reads source files as data",
                        {"site": site.to_json(), "chain": chain}))
    f.exposure = dynamic_facts.exposure(path, len(static_importers))
    if not f.exposure:  # reached only through a module that is loaded by a computed name
        for test, chain in chains.items():
            hop = graph.computed_hop(chain) if test in universe else None
            if hop:
                f.exposure.append({"kind": "reached-through-computed-load", "detail":
                                   f"{hop[1]} is loaded by a computed name in {hop[0]}; tests reach "
                                   f"{path} only through it", "evidence": {"loader": hop[0], "module": hop[1]}})
                break

    runtime: dict[str, Reason] | None = None
    if tmap is None:
        f.runtime = "none"
    elif cf.status == "added":
        f.runtime = "none"
        f.notes.append("new file: no runtime evidence exists for it yet")
    elif not tmap.fresh(path, cf.old_sha):
        f.runtime = "stale"
        f.notes.append("runtime evidence was recorded for different content of this file; ignored")
    elif cf.status != "deleted" and not tmap.loaders_of(path):
        # no recorded test executed, loaded or opened this file: the recording cannot speak for
        # it (a server reading it as text, a child process), so it never overrides static links
        f.runtime = "unobserved"
        f.notes.append("no recorded test executed, loaded or opened this file; runtime evidence cannot "
                       "rule out other uses (read as data, run in a child process), so static links apply")
    else:
        f.runtime = "fresh"
        runtime = {}
        if cf.status in {"deleted", "renamed"}:  # every test that loaded the old path loses it
            for test in tmap.loaders_of(path):
                runtime[test] = Reason("runtime", f"executed code in {cf.status} {path}")
        elif path.endswith(".py"):
            keys = set(cf.units)
            names = dict(zip(cf.units, cf.unit_names, strict=True))
            for test, hit in tmap.consumers_of_units(path, keys).items():
                runtime[test] = Reason("runtime", "executed changed " + ", ".join(
                    sorted({names.get(k, k) for k in hit})), {"units": hit})
            f.never_executed = sorted({names.get(k, k) for k in keys - tmap.executed_units(path)})
            if not keys:  # nothing mapped (did not compile): every test that loaded the file
                for test in tmap.loaders_of(path):
                    runtime[test] = Reason("runtime", f"loaded {path}")
        else:
            lines = {line for a, b in cf.old_lines for line in range(a, b + 1)} | \
                {after for after in cf.insertions if after} | {after + 1 for after in cf.insertions}
            consumers, never = tmap.node_consumers(path, lines)
            for test, names_hit in consumers.items():
                runtime[test] = Reason("runtime", "executed changed " + ", ".join(sorted(set(names_hit))))
            f.never_executed = never
            if not tmap.functions.get(path):
                f.notes.append("no recorded test loaded this file")
        for test in tmap.tests:  # data the test opened at runtime
            if path in (tmap.tests[test].get("opened") or []):
                runtime.setdefault(test, Reason("runtime", f"opened {path}"))

    linked: set[str] = set()
    for test in sorted(universe):
        if runtime is not None and tmap is not None and tmap.complete(test):
            if test in runtime:
                pick(test, runtime[test])
                for r in static.get(test, [])[:1]:  # keep one static explanation alongside
                    pick(test, r)
                linked.add(test)
            continue
        for r in static.get(test, []):
            pick(test, r)
            linked.add(test)
        if runtime is not None and test in runtime:  # evidence from an incomplete record still counts
            pick(test, runtime[test])
            linked.add(test)
    return len(linked)
