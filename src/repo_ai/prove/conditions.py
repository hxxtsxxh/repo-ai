"""The oracle's conditions: what decides how a scenario runs besides its own
bytes, compared between the base and the candidate.

A candidate can make a pinned test pass without touching the test: by
editing a ``conftest.py`` fixture, the pytest configuration, a test helper
the scenario imports, or an expected-output file next to it. An experiment
is only a comparison when those inputs are the same at both revisions, so
every one of them is hashed at both, and any difference stops the
experiment ("conditions differ") unless it is pinned with ``--support``
(then both runs use the pinned bytes).

What counts, for a scenario at ``tests/unit/test_x.py``:

* every ``conftest.py`` in ``tests/unit``, ``tests`` and the repository root
  (pytest loads that chain);
* the pytest sections of ``pyproject.toml``, ``setup.cfg`` and ``tox.ini`` and
  the whole of ``pytest.ini``/``.pytest.ini`` in those directories;
* for node, the ``type`` and ``imports`` fields of every ``package.json`` there
  (they change how the scenario is loaded);
* when the scenario lives in a test directory (a path part named ``test``,
  ``tests``, ``__tests__``, ``spec`` …): every other file below that directory
  that is not itself a test file: helpers, data and ``__init__.py`` (packages
  decide module names and unittest's ``load_tests``).

Comparison is by content; nothing is executed.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

TEST_DIR_NAMES = {"test", "tests", "testing", "__tests__", "spec", "specs", "acceptance", "e2e", "test-support",
                  "test_support", "testsupport", "testutils", "test_utils", "test-utils", "fixtures", "__fixtures__",
                  "__mocks__", "mocks", "golden", "goldens", "snapshots", "__snapshots__", "testdata", "test-data",
                  "test_data"}
# module names of test machinery wherever they live (`calc/testing.py`, `src/pkg/fixtures.py`)
TEST_MODULE_NAMES = {"testing", "fixtures", "conftest", "testutils", "test_utils", "test_helpers", "testhelpers",
                     "pytest_plugin", "pytest_plugins", "plugin_fixtures", "mocks", "fakes", "factories"}
PY_HARNESS = ("conftest.py",)
INI_FILES = ("pytest.ini", ".pytest.ini")
SECTION_FILES = ("pyproject.toml", "setup.cfg", "tox.ini")

Reader = Callable[[str], "bytes | None"]


def _digest(data: bytes | None) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


def _pytest_section(name: str, data: bytes | None) -> bytes | None:
    """Only the part of a shared configuration file that configures pytest:
    a dependency bump in pyproject.toml is not an oracle change."""
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    try:
        if name == "pyproject.toml":
            tool = tomllib.loads(text).get("tool") or {}
            section = tool.get("pytest") if isinstance(tool, dict) else None
            return None if section is None else json.dumps(section, sort_keys=True, default=str).encode()
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)
        wanted = "tool:pytest" if name == "setup.cfg" else "pytest"
        if not parser.has_section(wanted):
            return None
        return json.dumps(sorted(parser.items(wanted, raw=True))).encode()
    except (ValueError, RecursionError, configparser.Error, tomllib.TOMLDecodeError):
        return data  # unparseable: compare it whole


def _package_fields(data: bytes | None) -> bytes | None:
    if data is None:
        return None
    try:
        doc = json.loads(data.decode("utf-8", "replace"))
    except (ValueError, RecursionError):
        return data
    if not isinstance(doc, dict):
        return data
    return json.dumps({k: doc.get(k) for k in ("type", "imports")}, sort_keys=True).encode()


def _ancestors(rel: str) -> list[str]:
    """The scenario's directory, its parents, and the root ("")."""
    parts = PurePosixPath(rel).parent.parts
    return ["/".join(parts[:i]) for i in range(len(parts), -1, -1)]


def test_dir(rel: str) -> str:
    """The outermost test directory that holds the scenario ("" when none)."""
    parts = PurePosixPath(rel).parent.parts
    for i, part in enumerate(parts):
        if part.lower() in TEST_DIR_NAMES:
            return "/".join(parts[:i + 1])
    return ""


def inputs(scenario: str, kind: str, files: list[str], read: Reader, *, test_files: set[str],
           pinned: set[str], only: set[str] | None = None, cwd: str = "", scenario_bytes: bytes | None = None
           ) -> dict[str, str]:
    """Path -> content digest of every oracle input of `scenario` in one
    revision (`files`: its file list; `read`: its bytes). Pinned paths are
    left out: both runs use the pinned bytes. `only`: read just these paths
    (the change's files); every other input is identical at both revisions
    and is listed as "same"."""
    present = set(files)

    def inner_read(rel: str, _read=read) -> bytes | None:  # real bytes, for following imports
        if rel == scenario and scenario_bytes is not None:
            return scenario_bytes
        return _read(rel) if rel in present else None
    if only is not None:
        inner = read

        def read(rel: str) -> bytes | None:  # type: ignore[no-redef]
            return inner(rel) if rel in only else b"same"
    out: dict[str, str] = {}
    for d in _ancestors(scenario):
        def at(name: str, _d: str = d) -> str:
            return f"{_d}/{name}" if _d else name
        if kind in {"pytest", "unittest"}:
            for name in PY_HARNESS:
                out[at(name)] = _digest(read(at(name)) if at(name) in present else None)
        if kind == "pytest":
            for name in INI_FILES:
                out[at(name)] = _digest(read(at(name)) if at(name) in present else None)
            for name in SECTION_FILES:
                p = at(name)
                out[p + "#pytest"] = _digest(_pytest_section(name, read(p)) if p in present else None)
        if kind == "node":
            p = at("package.json")
            out[p + "#type,imports"] = _digest(_package_fields(read(p)) if p in present else None)
    top = test_dir(scenario)
    if top:
        below = [f for f in files if f.startswith(top + "/") and f not in test_files and f != scenario]
        for f in below:
            out[f] = _digest(read(f))
    # test code the scenario imports (a helper that is itself a test file included), and data next to it;
    # the conftest chain counts as test code that the scenario loads, and so do the plugin modules it declares
    conftests = [c for c in (f"{d}/conftest.py" if d else "conftest.py" for d in _ancestors(scenario)) if c in present]
    machinery, _reach = harness(files, inner_read, cwd)
    plugins = sorted(m for m in machinery if PurePosixPath(m).name != "conftest.py")
    for f in plugins:
        out[f] = _digest(read(f))
    tests_reached = closure(scenario, files, inner_read, cwd)
    for start in [*conftests, *plugins]:
        tests_reached |= {f for f in closure(start, files, inner_read, cwd) if f != scenario}
    for f in sorted(tests_reached | data_next_to(scenario, files)):
        if f in present:
            out[f] = _digest(read(f))
    # expected values kept outside test code: a module of constants (or a JSON file) that the scenario or its
    # test helpers import directly, and a data file whose name they spell out
    sources = [scenario, *sorted(tests_reached), *conftests, *plugins]
    for f in sorted(direct_imports(sources, files, inner_read, cwd) - tests_reached - {scenario}):
        if f.endswith(".json") or (f.endswith(".py") and constants_only(inner_read(f))):
            out[f] = _digest(read(f))
    named = literal_names(sources, inner_read)
    for f in files:
        if not f.endswith(CODE_SUFFIXES) and PurePosixPath(f).name in named and f != scenario:
            out[f] = _digest(read(f))
    return {k: v for k, v in out.items() if k.split("#")[0] not in pinned and k.split("#")[0] != scenario}


def compare(base: dict[str, str], candidate: dict[str, str]) -> list[str]:
    """The inputs whose content differs (or that exist on one side only)."""
    keys = set(base) | set(candidate)
    return sorted(k for k in keys if base.get(k, "absent") != candidate.get(k, "absent"))


def base_reader(root: Path, commit: str) -> tuple[list[str], Reader]:
    """The file list of `commit` and a reader of its blobs (git plumbing; no
    hooks or filters run)."""
    out = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "--end-of-options", commit], cwd=root,
                         capture_output=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    files = sorted(p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p)

    def read(rel: str) -> bytes | None:
        res = subprocess.run(["git", "cat-file", "blob", f"{commit}:{rel}"], cwd=root, capture_output=True,
                             timeout=60, check=False, stdin=subprocess.DEVNULL)
        return res.stdout if res.returncode == 0 else None
    return files, read


def tree_reader(root: Path) -> Reader:
    def read(rel: str) -> bytes | None:
        p = root / rel
        if p.is_symlink():
            try:
                return ("symlink:" + str(p.readlink())).encode()
            except OSError:
                return None
        try:
            return p.read_bytes() if p.is_file() else None
        except OSError:
            return None
    return read


def oracle_report(root: Path, scenario: str, kind: str, base_commit: str, candidate_files: list[str],
                  test_files_base: set[str], test_files_candidate: set[str], pinned: set[str],
                  changed: set[str], scenario_bytes: bytes | None = None, cwd: str = "") -> dict[str, Any]:
    """The oracle inputs at both revisions and how they differ. `changed`:
    every path the change adds, modifies, deletes or renames (old and new
    names): only those can differ, so only those are read."""
    files_b, read_b = base_reader(root, base_commit)
    at_base = inputs(scenario, kind, files_b, read_b, test_files=test_files_base, pinned=pinned, only=changed,
                     cwd=cwd, scenario_bytes=scenario_bytes)
    at_cand = inputs(scenario, kind, candidate_files, tree_reader(root), test_files=test_files_candidate,
                     pinned=pinned, only=changed, cwd=cwd, scenario_bytes=scenario_bytes)
    differing = compare(at_base, at_cand)
    present_c = set(candidate_files)

    def cand_read(rel: str) -> bytes | None:
        if rel == scenario and scenario_bytes is not None:
            return scenario_bytes
        return tree_reader(root)(rel) if rel in present_c else None
    imported_changed = sorted((reachable(scenario, candidate_files, cand_read, cwd) & changed) - pinned)
    # data the change edits: the scenario may read it however it finds it (a joined path, a glob, a loader)
    changed_data = sorted(f for f in changed - pinned
                          if f != scenario and f in present_c and not f.endswith(CODE_SUFFIXES)
                          and not f.lower().endswith(NOT_DATA_SUFFIXES)
                          and PurePosixPath(f).name not in NOT_DATA_NAMES)
    present = sorted(k for k in set(at_base) | set(at_cand)
                     if at_base.get(k, "absent") != "absent" or at_cand.get(k, "absent") != "absent")
    return {"files": present[:200], "checked": len(present), "differing": differing[:200],
            "identical": not differing, "imported_changed": imported_changed[:50], "changed_data": changed_data[:50],
            "base_sha256": hashlib.sha256(json.dumps(at_base, sort_keys=True).encode()).hexdigest(),
            "candidate_sha256": hashlib.sha256(json.dumps(at_cand, sort_keys=True).encode()).hexdigest()}


_SKIP_MARKERS = ("pytest.mark.skip", "pytest.mark.xfail", "pytest.skip(", "pytest.xfail(", "unittest.skip",
                 "@skip", "expectedFailure", ".skip(", "{ skip:", "{skip:", "todo(", ".todo(")


def scenario_notes(data: bytes, kind: str) -> list[str]:
    """Static warnings about the scenario itself (read, never run)."""
    text = data.decode("utf-8", "replace")
    notes = []
    if any(m in text for m in _SKIP_MARKERS):
        notes.append("the scenario contains skip, xfail or todo markers: a skipped test is never counted as passing, "
                     "but check that the targeted tests are not among them")
    if kind in {"pytest", "unittest"}:
        import ast
        try:
            tree = ast.parse(text)
        except SyntaxError:
            notes.append("the scenario is not valid Python")
            return notes
        has_check = any(isinstance(n, ast.Assert) for n in ast.walk(tree)) or any(
            isinstance(n, ast.Attribute) and n.attr.startswith(("assert", "fail")) for n in ast.walk(tree)) or any(
            isinstance(n, ast.Attribute) and n.attr == "raises" for n in ast.walk(tree))
        if not has_check:
            notes.append("the scenario has no assert statement, assert* call or pytest.raises: it may not check "
                         "any behaviour")
    elif "assert" not in text:
        notes.append("the scenario never mentions assert: it may not check any behaviour")
    return notes


# --------------------------------------------------------------------------
# what a test file imports (read, never run)
# --------------------------------------------------------------------------
CODE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx")
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx", ".json")
_JS_IMPORT = re.compile(r"""(?:require\s*\(\s*|import\s*\(\s*|from\s+|import\s+)['"](\.{1,2}/[^'"]+)['"]""")
MAX_CLOSURE = 500
DOC_SUFFIXES = (".md", ".rst", ".adoc", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp")
DOC_NAMES = ("LICENSE", "LICENCE", "AUTHORS", "CONTRIBUTORS", "CHANGELOG", "NOTICE", "CODEOWNERS")
NOT_DATA_SUFFIXES = (".md", ".rst", ".adoc", ".lock", ".toml", ".cfg", ".ini")  # docs and configuration
NOT_DATA_NAMES = {".gitignore", ".gitattributes", "LICENSE", "CHANGELOG", "package.json", "package-lock.json"}
MAX_PARSE_BYTES = 1024 * 1024  # a larger file is still compared by its digest; its own imports are not followed


def is_test_name(rel: str) -> bool:
    name = PurePosixPath(rel).name
    if PurePosixPath(rel).stem.lower() in TEST_MODULE_NAMES and rel.endswith(CODE_SUFFIXES):
        return True
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py") or any(
        name.endswith(f".{kind}{sfx}") for kind in ("test", "spec") for sfx in JS_SUFFIXES)


def _is_package_dir(folder: str, present: set[str]) -> bool:
    return (f"{folder}/__init__.py" if folder else "__init__.py") in present


def testish(rel: str, scenario: str, present: set[str]) -> bool:
    """Test code rather than code under test: a test file by name, anything
    under a test directory, or a file next to the scenario when that
    directory is not a Python package (a `checks/` folder of helpers)."""
    if is_test_name(rel) or test_dir(rel + "/x") or test_dir(rel):
        return True
    here = PurePosixPath(scenario).parent.as_posix()
    folder = PurePosixPath(rel).parent.as_posix()
    return folder == here and here not in {"", "."} and not _is_package_dir(here, present)


def imports(rel: str, data: bytes | None, present: set[str], roots: list[str]) -> set[str]:
    """Repository files `rel` imports directly (Python: the syntax tree; JS:
    relative specifiers)."""
    if data is None or len(data) > MAX_PARSE_BYTES:
        return set()
    out: set[str] = set()
    folder = PurePosixPath(rel).parent
    if rel.endswith(".py"):
        import ast
        try:
            tree = ast.parse(data.decode("utf-8", "replace"))
        except (SyntaxError, ValueError, RecursionError):
            return set()
        names: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [(a.name, 0) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                names.append((base, node.level))
                names += [(f"{base}.{a.name}" if base else a.name, node.level) for a in node.names]
        for name, level in names:
            parts = [p for p in name.split(".") if p]
            if level:
                anchor = folder
                for _ in range(level - 1):
                    anchor = anchor.parent
                bases = [anchor.as_posix()]
            else:
                bases = roots
            for b in bases:
                stem = "/".join([b, *parts]) if b not in {"", "."} else "/".join(parts)
                for cand in (f"{stem}.py", f"{stem}/__init__.py"):
                    if cand in present:
                        out.add(cand)
    else:
        for m in _JS_IMPORT.finditer(data.decode("utf-8", "replace")):
            target = PurePosixPath(folder / m.group(1))
            segs: list[str] = []
            for p in target.parts:
                if p == "..":
                    if segs:
                        segs.pop()
                elif p != ".":
                    segs.append(p)
            stem = "/".join(segs)
            for cand in (stem, *(stem + s for s in JS_SUFFIXES), *(f"{stem}/index{s}" for s in JS_SUFFIXES)):
                if cand in present:
                    out.add(cand)
                    break
    return out


def roots_for(rel: str, cwd: str = "") -> list[str]:
    """Where a bare `import x` may resolve: the file's own directory and its
    parents (pytest's rootdir insertion and `python -m` both put directories
    like these first), the runner's directory and `src`."""
    out = [a for a in _ancestors(rel)]
    for extra in (cwd, "src"):
        if extra and extra not in out:
            out.append(extra)
    return out


def closure(scenario: str, files: list[str], read: Reader, cwd: str = "") -> set[str]:
    """The test code the scenario reaches by imports: followed through test
    code only, never into the code under test."""
    present = set(files)
    seen: set[str] = set()
    todo = [scenario]
    while todo and len(seen) < MAX_CLOSURE:
        cur = todo.pop()
        for dep in imports(cur, read(cur) if cur in present or cur == scenario else None, present,
                           roots_for(scenario, cwd)):
            if dep not in seen and dep != scenario and testish(dep, scenario, present):
                seen.add(dep)
                todo.append(dep)
    return seen


def data_next_to(scenario: str, files: list[str]) -> set[str]:
    """Data files in the scenario's own directory (expected outputs, golden
    files), when it is a dedicated directory: not the root, not a package."""
    here = PurePosixPath(scenario).parent.as_posix()
    present = set(files)
    if here in {"", "."} or _is_package_dir(here, present):
        return set()
    return {f for f in files if PurePosixPath(f).parent.as_posix() == here and not f.endswith(CODE_SUFFIXES)}


# a module of the test machinery that a file in the tree could stand in for (python puts the working
# directory, the test's directory or `src` first on sys.path)
SHADOWED = {"pytest", "_pytest", "unittest", "pluggy", "py", "iniconfig", "sitecustomize", "usercustomize",
            "rai_result", "doctest", "nose", "nose2"}


def shadows(changed: list[str]) -> list[str]:
    """Changed files that could replace the test runner itself."""
    out = []
    for f in changed:
        p = PurePosixPath(f)
        if p.suffix == ".pth":
            out.append(f)
            continue
        names = {p.stem if p.suffix == ".py" else "", *(part for part in p.parts[:-1])}
        if names & SHADOWED and (p.suffix == ".py" or p.name == "__init__.py"):
            out.append(f)
    return sorted(out)


def reachable(scenario: str, files: list[str], read: Reader, cwd: str = "") -> set[str]:
    """Every repository file the scenario reaches by imports, code under test
    included (bounded): what a reviewer should look at when the change edits
    one of them."""
    present = set(files)
    seen: set[str] = set()
    todo = [scenario]
    while todo and len(seen) < MAX_CLOSURE:
        cur = todo.pop()
        for dep in imports(cur, read(cur), present, roots_for(scenario, cwd)):
            if dep not in seen and dep != scenario:
                seen.add(dep)
                todo.append(dep)
    return seen


def plugin_files(data: bytes | None, present: set[str], roots: list[str]) -> set[str]:
    """The modules a conftest.py declares in `pytest_plugins` (a string or a
    list or tuple of them), as repository files."""
    if data is None or len(data) > MAX_PARSE_BYTES:
        return set()
    import ast
    try:
        tree = ast.parse(data.decode("utf-8", "replace"))
    except (SyntaxError, ValueError, RecursionError):
        return set()
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in targets):
            continue
        values = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        names += [v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    for node in tree.body:  # pytest_plugins += [...]
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "pytest_plugins":
            values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
            names += [v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    return modules_to_files([n.strip() for name in names for n in name.split(",")], present, roots)  # pytest splits


def modules_to_files(names: list[str], present: set[str], roots: list[str]) -> set[str]:
    """Dotted module names as repository files."""
    out = set()
    for name in names:
        parts = [p for p in name.split(".") if p]
        for b in roots:
            stem = "/".join([b, *parts]) if b not in {"", "."} else "/".join(parts)
            for cand in (f"{stem}.py", f"{stem}/__init__.py"):
                if cand in present:
                    out.add(cand)
    return out


_P_OPTION = re.compile(r"(?:^|[\s'\"\[,=])-p[\s=]*([A-Za-z_][\w.]*)")  # `-p name`, `-pname`, quoted in TOML


def declared_plugins(files: list[str], read: Reader) -> list[str]:
    """Plugin module names declared outside conftest files: `-p NAME` in any
    pytest configuration's addopts, and the project's own `pytest11` entry
    points."""
    names: list[str] = []
    present = set(files)
    for rel in [f for f in files if PurePosixPath(f).name in {"pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg",
                                                              "pyproject.toml"}][:50]:
        data = read(rel) if rel in present else None
        if data is None or len(data) > MAX_PARSE_BYTES:
            continue
        text = data.decode("utf-8", "replace")
        names += _P_OPTION.findall(text)
        if rel.endswith("pyproject.toml"):
            try:
                doc = tomllib.loads(text)
            except (ValueError, RecursionError, tomllib.TOMLDecodeError):
                continue
            eps = ((doc.get("project") or {}).get("entry-points") or {}).get("pytest11") or {}
            if isinstance(eps, dict):
                names += [str(v).split(":", 1)[0].strip() for v in eps.values()]
    return names


def harness(files: list[str], read: Reader, cwd: str = "") -> tuple[set[str], set[str]]:
    """pytest's own machinery in this revision: every conftest.py and every
    plugin module it is told to load (`pytest_plugins` in conftest files,
    nested and comma-separated; `-p` in the configuration; `pytest11` entry
    points of the project), and (second) everything those reach by imports."""
    present = set(files)
    roots = [r for r in ["", cwd, "src"] if r is not None]
    conftests = {f for f in files if PurePosixPath(f).name == "conftest.py"}
    plugins = modules_to_files(declared_plugins(files, read), present, roots)
    todo = sorted(conftests | plugins)
    seen: set[str] = set()
    while todo and len(seen) < MAX_CLOSURE:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for p in plugin_files(read(cur) if cur in present else None, present, roots_for(cur, cwd)):
            plugins.add(p)
            todo.append(p)
    machinery = conftests | plugins
    reach: set[str] = set()
    for m in sorted(machinery):
        reach |= reachable(m, files, read, cwd)
    return machinery, reach


_MACHINERY = re.compile(rb"(?m)^\s*(?:@pytest\.fixture|import pytest\b|from pytest\b|from _pytest\b|def pytest_\w+\s*\(|"
                        rb"import unittest\b|from unittest\b)|require\(\s*['\"]node:test['\"]|from\s+['\"]node:test['\"]")


def machinery_source(data: bytes | None) -> bool:
    """Source that is test machinery whatever its name: it uses pytest or
    unittest, defines fixtures or pytest hooks, or loads node:test."""
    return bool(data) and len(data or b"") <= MAX_PARSE_BYTES and _MACHINERY.search(data or b"") is not None


def direct_imports(sources: list[str], files: list[str], read: Reader, cwd: str = "") -> set[str]:
    """Every repository file these files import directly, code under test
    included."""
    present = set(files)
    out: set[str] = set()
    for f in sources:
        out |= imports(f, read(f), present, roots_for(sources[0], cwd))
    return out


def constants_only(data: bytes | None) -> bool:
    """A Python module that defines no function or class, only values: a
    place for expected values, not code under test."""
    if data is None or len(data) > MAX_PARSE_BYTES:
        return False
    import ast
    try:
        tree = ast.parse(data.decode("utf-8", "replace"))
    except (SyntaxError, ValueError, RecursionError):
        return False
    allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.Expr)
    return bool(tree.body) and all(isinstance(n, allowed) for n in tree.body) and any(
        isinstance(n, (ast.Assign, ast.AnnAssign)) for n in tree.body)


_QUOTED = re.compile(r"""['"]([^'"\n]{1,200})['"]""")


def literal_names(sources: list[str], read: Reader) -> set[str]:
    """File names (with an extension) that these files spell out in string
    literals: data a test opens, wherever it lives."""
    out: set[str] = set()
    for f in sources:
        data = read(f)
        if data is None or len(data) > MAX_PARSE_BYTES:
            continue
        for m in _QUOTED.finditer(data.decode("utf-8", "replace")):
            name = m.group(1).replace("\\", "/").rsplit("/", 1)[-1]
            if "." in name.strip(".") and not name.endswith(CODE_SUFFIXES) and " " not in name:
                out.add(name)
    return out
