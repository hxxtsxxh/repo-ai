"""Which test command `verify` runs, established without configuration
where the project makes it unambiguous, and always shown with its origin.

Order:
1. `--test-command` (the user's explicit choice; used as given);
2. the project's declared test commands (package.json scripts, Makefile,
   CI, docs: the index's `commands.test`), resolved through scripts,
   wrappers and lint steps (`runner.resolve`);
3. when every declared command is opaque (`tox`, `python runtests.py`) or
   none is declared: a runner inferred from the test files themselves.

Refinements, each recorded in `runner.notes`, from static evidence only:
- **src layout:** `PYTHONPATH=src` when the tests import a package that
  lives only under `src/`;
- **unittest discovery** (inferred commands only): widen the start
  directory and pattern until every file that defines `TestCase` tests is
  in the universe, choosing the narrowest pattern that does so.

Nothing here executes repository code or reads anything but files.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path, PurePosixPath

from .runner import TestRunner, resolve

UNITTEST_PATTERNS = ("test*.py", "test_*.py", "*_test.py", "*_tests.py", "*test*.py", "*.py")
_TOP_IMPORT = re.compile(r"(?m)^\s*(?:from\s+([A-Za-z_]\w*)[\w.]*\s+import|import\s+([A-Za-z_]\w*))")
TESTCASE_ROOTS = {"TestCase", "IsolatedAsyncioTestCase", "AsyncTestCase", "SimpleTestCase",
                  "TransactionTestCase", "LiveServerTestCase"}


def establish(root: Path, layout, files: list[str], override: str | None = None,
              override_source: str = "--test-command") -> TestRunner:
    if override:
        runner = resolve(root, override)
        runner.source = override_source
        return runner
    from ..cli import _facts_obj
    from ..testing import verification_plan
    facts = _facts_obj(layout)
    if facts is None:
        return TestRunner("opaque", "", source="no index")
    plan = verification_plan(facts.commands, facts.test_suites)
    declared = [c for c in plan.tests if c.source == "declared"]
    inferred_cmds = [c for c in plan.tests if c.source != "declared"]
    first: TestRunner | None = None
    for cand in declared:
        runner = resolve(root, cand.command)
        if runner.per_file:
            runner.source = cand.detail if cand.detail.startswith("declared") else f"declared ({cand.detail})"
            return _refine(root, runner, files, inferred=False)
        first = first or runner
    tox = _tox_command(root)
    if tox:
        runner = resolve(root, tox)
        # a pytest command is taken only when the tests need pytest; tests that the standard
        # library's unittest runs as well keep working without it installed
        if runner.per_file and (runner.kind != "pytest" or _imports_pytest(root, runner.test_files(files))):
            runner.source = "declared (tox.ini)"
            return _refine(root, runner, files, inferred=False)
    for command in [c.command for c in inferred_cmds] or _fallback(facts.test_suites):
        runner = resolve(root, command)
        if runner.per_file:
            runner.source = "inferred from the test files"
            if first is not None:
                runner.notes.append(f"the declared command `{first.command}` cannot be split per test file; "
                                    "per-file runs use this inferred runner")
            return _refine(root, runner, files, inferred=True)
    if first is not None:
        first.source = "declared"
        return first
    return TestRunner("opaque", "", source="none found")


def _tox_command(root: Path) -> str:
    """The test command of a `tox.ini` whose `[testenv]` runs exactly one
    command: a declaration as explicit as a package script. Read as text,
    never run through tox; `{posargs}` and similar substitutions are dropped,
    any other `{...}` makes it unusable."""
    import configparser
    path = root / "tox.ini"
    if not path.is_file():
        return ""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(path.read_text("utf-8", errors="replace")[:200_000])
    except (configparser.Error, OSError):
        return ""
    if not parser.has_section("testenv"):
        return ""
    lines = [ln.strip() for ln in parser.get("testenv", "commands", fallback="").splitlines() if ln.strip()]
    if len(lines) != 1:
        return ""
    line = re.sub(r"\s*\{posargs(?::[^}]*)?\}", "", lines[0]).strip()
    return "" if "{" in line or "}" in line else line


_PYTEST_IMPORT = re.compile(r"(?m)^\s*(?:import pytest\b|from pytest\b)")


def _imports_pytest(root: Path, tests: list[str]) -> bool:
    for rel in tests[:500]:
        try:
            if _PYTEST_IMPORT.search((root / rel).read_text("utf-8", errors="replace")[:200_000]):
                return True
        except OSError:
            continue
    return False


def _fallback(suites) -> list[str]:
    """Runner commands for the Python suites the index found, when the
    project declares only opaque commands."""
    out = []
    for s in suites:
        if s.kind == "e2e" or s.framework not in {"unittest", "pytest"}:
            continue
        root = s.root if s.root not in {"", "."} else ""
        if s.framework == "pytest":
            out.append("python -m pytest" + (f" {root}" if root else ""))
        else:
            out.append(f"python -m unittest discover -s {root or '.'} -t .")
    return out


# --------------------------------------------------------------------------
def _refine(root: Path, runner: TestRunner, files: list[str], inferred: bool) -> TestRunner:
    if runner.kind in {"unittest", "pytest"}:
        _src_layout(root, runner, files)
        if inferred and runner.kind == "unittest" and not runner.modules:
            _widen_unittest(root, runner, files)
    return runner


def _src_layout(root: Path, runner: TestRunner, files: list[str]) -> None:
    if "PYTHONPATH" in runner.env or runner.cwd:
        return
    under_src = {PurePosixPath(f).parts[1] if len(PurePosixPath(f).parts) > 2 else
                 PurePosixPath(f).stem for f in files
                 if f.startswith("src/") and f.endswith(".py")}
    under_src = {n for n in under_src if n.isidentifier()}
    at_root = {PurePosixPath(f).parts[0] if "/" in f else PurePosixPath(f).stem for f in files if f.endswith(".py")}
    only_src = under_src - (at_root - {"src"})
    if not only_src:
        return
    imported: set[str] = set()
    tests = runner.test_files(files)
    test_dirs = {str(PurePosixPath(f).parent) for f in tests}
    # the test files and what sits beside them (`tests/__init__.py` often does the importing)
    scanned = sorted(set(tests) | {f for f in files if f.endswith(".py") and str(PurePosixPath(f).parent) in test_dirs})
    for test in scanned:
        try:
            text = (root / test).read_text("utf-8", errors="replace")[:200_000]
        except OSError:
            continue
        imported |= {a or b for a, b in _TOP_IMPORT.findall(text)}
    hit = sorted(only_src & imported)
    if hit:
        runner.env["PYTHONPATH"] = "src"
        runner.notes.append(f"PYTHONPATH=src: the tests import {', '.join(hit[:3])}, which lives only under src/")


def _test_classes(root: Path, py_files: list[str]) -> dict[str, bool]:
    """file -> defines a class with test methods that (transitively, by
    name) derives from unittest's TestCase."""
    bases: dict[str, set[str]] = {}
    has_tests: dict[str, set[str]] = {}
    per_file: dict[str, list[str]] = {}
    for f in py_files:
        try:
            tree = ast.parse((root / f).read_bytes().removeprefix(b"\xef\xbb\xbf"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                names = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in node.bases}
                bases.setdefault(node.name, set()).update(names)
                if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
                       for n in node.body):
                    has_tests.setdefault(f, set()).add(node.name)
                per_file.setdefault(f, []).append(node.name)
    derived = set(TESTCASE_ROOTS)
    changed = True
    while changed:
        changed = False
        for cls, bs in bases.items():
            if cls not in derived and bs & derived:
                derived.add(cls)
                changed = True
    return {f: bool(has_tests.get(f, set()) & derived) for f in per_file}


def _widen_unittest(root: Path, runner: TestRunner, files: list[str]) -> None:
    candidates = [f for f in files if f.endswith(".py") and not f.startswith(("docs/", "doc/", "examples/"))
                  and any(p in {"test", "tests", "testing"} or p.startswith("test") for p in PurePosixPath(f).parts[:-1])]
    defining = {f for f, ok in _test_classes(root, candidates).items() if ok}
    if not defining:
        return
    universe = set(runner.test_files(files))
    if not defining - universe:
        return
    # 1. the pattern: changed only when the project's own naming convention is not the default
    #    (most TestCase files fail to match it); files named outside a convention that holds
    #    (`run_w3c_tests.py` beside `test_*.py`) are deliberately left to be run by hand
    pattern = runner.pattern
    if sum(fnmatch.fnmatch(PurePosixPath(f).name, pattern) for f in defining) * 2 < len(defining):
        pattern = min((p for p in UNITTEST_PATTERNS
                       if all(fnmatch.fnmatch(PurePosixPath(f).name, p) for f in defining)),
                      key=lambda p: sum(fnmatch.fnmatch(PurePosixPath(f).name, p) for f in candidates),
                      default=pattern)
    target = {f for f in defining if fnmatch.fnmatch(PurePosixPath(f).name, pattern)}
    # 2. the start directory: the deepest one holding every such file
    dirs = [PurePosixPath(f).parent.parts for f in target]
    common: list[str] = []
    for parts in zip(*dirs, strict=False):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    start = "/".join(common) or "."
    trial = TestRunner("unittest", runner.command, full=[], start=start, top=".", pattern=pattern)
    covered = set(trial.test_files(files))
    if len(covered & target) <= len(universe & target):
        return
    missing = len((covered & target) - universe)
    runner.start, runner.top, runner.pattern = start, ".", pattern
    runner.full = ["python", "-m", "unittest", "discover", "-s", start, "-t", ".", "-p", pattern]
    runner.command = " ".join(runner.full)
    runner.notes.append(f"unittest discovery widened to `-s {start} -p {pattern}`: {missing} file(s) defining "
                        "TestCase tests were outside the inferred start directory or pattern")
