"""Counterexamples from the 2026-10 correctness audit of `verify --run`
(docs/VERIFY-AUDIT-2026-10.md), each pinned to the verdict it must
give. Before the fixes, every one of these reported a real regression as
pre-existing or as a pass, or reused evidence for a different tree.

End-to-end through the CLI and the sandbox, on small fixture repositories.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli

from test_verify_adaptive import _sandbox

pytestmark = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")

UNITTEST = "python -m unittest discover -s tests -t ."
OTHER = ("import unittest\nfrom pkg.other import one\n\n\nclass O(unittest.TestCase):\n"
         "    def test_one(self):\n        self.assertEqual(one(), 1)\n")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _apply(root: Path, files: dict[str, object]) -> None:
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, tuple):  # ("link", target)
            if path.is_symlink() or path.exists():
                path.unlink()
            path.symlink_to(text[1])
            continue
        path.write_text(str(text))


def _project(tmp_path: Path, base: dict[str, object]) -> Path:
    root = tmp_path / "p"
    root.mkdir()
    _apply(root, {".gitignore": "__pycache__/\n*.pyc\n", **base})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _verify(root: Path, command: str, *extra: str) -> dict:
    proc = run_cli(root, "verify", "--run", "--json", "--test-command", command, *extra)
    assert proc.returncode in {0, 1}, proc.stderr[-1500:]
    return json.loads(proc.stdout)["evidence"]


def _row(ev: dict, test: str) -> dict:
    return next(r for r in ev["results"] if r["test"] == test)


# 1. a doctest collected through `load_tests`: re-running it "by id" at the base called the function
def test_a_doctest_regression_is_new_not_pre_existing(tmp_path: Path):
    root = _project(tmp_path, {
        "pkg/__init__.py": "", "tests/__init__.py": "",
        "pkg/mod.py": 'def double(x):\n    """\n    >>> double(2)\n    4\n    """\n    return x * 2\n',
        "pkg/other.py": "def one():\n    return 1\n",
        "tests/test_doc.py": ("import doctest\nimport unittest\nimport pkg.mod\n\n\nclass Plain(unittest.TestCase):\n"
                              "    def test_ok(self):\n        self.assertTrue(True)\n\n\n"
                              "def load_tests(loader, tests, ignore):\n    tests.addTests(doctest.DocTestSuite(pkg.mod))\n"
                              "    return tests\n"),
        **{f"tests/test_other{i}.py": OTHER for i in range(1, 6)}})
    _apply(root, {"pkg/mod.py": 'def double(x):\n    """\n    >>> double(2)\n    4\n    """\n    return x * 3\n'})
    ev = _verify(root, UNITTEST)
    assert ev["verdict"] == "regression", (ev["verdict"], _row(ev, "tests/test_doc.py"))


# 3. a hang in setUpClass, in a file that already had a failing test at the base
def test_a_new_hang_in_a_file_with_a_known_failure_is_new(tmp_path: Path):
    root = _project(tmp_path, {
        "pkg/__init__.py": "", "tests/__init__.py": "", "pkg/core.py": "def connect():\n    return 1\n",
        "tests/test_db.py": ("import unittest\nfrom pkg.core import connect\n\n\nclass DB(unittest.TestCase):\n"
                             "    @classmethod\n    def setUpClass(cls):\n        cls.c = connect()\n\n"
                             "    def test_known_broken(self):\n        self.assertEqual(1, 2)\n\n"
                             "    def test_ok(self):\n        self.assertEqual(self.c, 1)\n")})
    _apply(root, {"pkg/core.py": "import time\n\n\ndef connect():\n    while True:\n        time.sleep(1)\n"})
    ev = _verify(root, UNITTEST, "--timeout", "5")
    row = _row(ev, "tests/test_db.py")
    assert row["status"] == "timeout" and ev["verdict"] == "regression", (ev["verdict"], row.get("classification"))


# 4. pytest items reordered across files (as pytest-randomly does): a timeout must not vouch for a file
def test_interleaved_tests_do_not_make_an_unfinished_file_count_as_passed(tmp_path: Path):
    if shutil.which("python") is None:
        pytest.skip("no python on PATH for the sandboxed runner")
    root = _project(tmp_path, {
        "pkg/__init__.py": "", "pkg/core.py": "def val():\n    return 1\n",
        "tests/conftest.py": "def pytest_collection_modifyitems(items):\n    items.sort(key=lambda i: i.name)\n",
        "tests/test_a.py": ("from pkg.core import val\n\n\ndef test_1_ok():\n    assert True\n\n\n"
                            "def test_3_bad():\n    assert val() == 1\n"),
        "tests/test_h.py": "import time\nfrom pkg.core import val\n\n\ndef test_2_hang():\n    time.sleep(1000)\n"})
    _apply(root, {"pkg/core.py": "def val():\n    return 2\n"})
    ev = _verify(root, "python -m pytest -q tests", "--workers", "1", "--timeout", "6")
    a = _row(ev, "tests/test_a.py")
    assert a["status"] == "fail" and "tests/test_a.py::test_3_bad" in a["failing_tests"], a
    assert ev["verdict"] == "regression"


# 5. the change makes every test of a file skip
def test_a_file_whose_tests_all_skip_with_the_change_is_not_a_pass(tmp_path: Path):
    root = _project(tmp_path, {
        "pkg/__init__.py": "", "tests/__init__.py": "",
        "pkg/ext.py": "def available():\n    return True\n\n\ndef compute():\n    return 42\n",
        "tests/test_ext.py": ("import unittest\nfrom pkg import ext\n\n\n"
                              "@unittest.skipUnless(ext.available(), 'the extension is not built')\n"
                              "class E(unittest.TestCase):\n    def test_compute(self):\n"
                              "        self.assertEqual(ext.compute(), 42)\n")})
    _apply(root, {"pkg/ext.py": "def available():\n    return False\n\n\ndef compute():\n    return 41\n"})
    ev = _verify(root, UNITTEST)
    assert ev["verdict"].startswith("not verified"), ev["verdict"]
    assert "ran at the base" in _row(ev, "tests/test_ext.py")["unverified"]


def test_a_test_that_skips_at_the_base_too_does_not_block_a_pass(tmp_path: Path):
    root = _project(tmp_path, {
        "pkg/__init__.py": "", "tests/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n",
        "tests/test_win.py": ("import unittest\nfrom pkg.core import f\n\n\n@unittest.skip('windows only')\n"
                              "class W(unittest.TestCase):\n    def test_f(self):\n        self.assertEqual(f(), 1)\n")})
    _apply(root, {"pkg/core.py": "def f():\n    return 2 - 1\n"})
    ev = _verify(root, UNITTEST)
    assert ev["verdict"].startswith(("selected-", "nothing")), ev["verdict"]
    assert _row(ev, "tests/test_win.py").get("skip_check") == "its tests are skipped at the base too"


# 6. a dependency upgrade: the base runs with the same (upgraded) dependencies
def test_a_failure_after_a_dependency_change_is_not_called_pre_existing(tmp_path: Path):
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    from test_verify_adaptive import _node_sandbox
    if not _node_sandbox()[0]:
        pytest.skip("the sandbox cannot start node here")
    root = _project(tmp_path, {
        ".gitignore": "node_modules/\n",
        "package.json": ('{"name": "app", "version": "1.0.0", "scripts": {"test": "node --test"}, '
                         '"dependencies": {"dep": "1.0.0"}}\n'),
        "src/app.js": "const dep = require('dep');\nexports.run = () => dep.f();\n",
        "test/app.test.js": ("const test = require('node:test');\nconst assert = require('node:assert');\n"
                             "const app = require('../src/app.js');\n"
                             "test('run', () => { assert.strictEqual(app.run(), 1); });\n")})
    _apply(root, {"node_modules/dep/package.json": '{"name": "dep", "version": "2.0.0", "main": "index.js"}\n',
                  "node_modules/dep/index.js": "exports.f = () => 2;\n",
                  "package.json": ('{"name": "app", "version": "1.0.0", "scripts": {"test": "node --test"}, '
                                   '"dependencies": {"dep": "2.0.0"}}\n')})
    ev = _verify(root, "node --test")
    assert ev["verdict"] != "failing (all failures pre-existing at the base)", ev["verdict"]
    assert ev["verdict"].startswith(("failing", "regression")), ev["verdict"]


AGG_CORE = "from pkg import conf\n\n\ndef parse(s):\n    if conf.STRICT and not COND:\n        raise ValueError(s)\n    return int(s)\n"
AGG = {"pkg/__init__.py": "", "tests/__init__.py": "", "pkg/conf.py": "STRICT = False\n",
       "pkg/other.py": "def one():\n    return 1\n",
       "pkg/core.py": AGG_CORE.replace("COND", "s.strip().isdigit()"),
       "tests/test_core.py": ("import unittest\nfrom pkg.core import parse\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_parse(self):\n        self.assertEqual(parse(' 1'), 1)\n"),
       "tests/test_core_strict.py": ("import pkg.conf\npkg.conf.STRICT = True  # the same tests, in strict mode\n"
                                     "from tests.test_core import T  # noqa: F401\n"),
       **{f"tests/test_other{i}.py": OTHER for i in range(1, 6)}}


# 7. an "aggregator" that re-runs another file's tests in a different configuration
def test_an_aggregator_that_configures_its_tests_is_not_skipped(tmp_path: Path):
    # a slow file keeps the full suite from being chosen for speed (it would run the aggregator anyway)
    root = _project(tmp_path, {**AGG, "tests/test_slow.py": ("import time\nimport unittest\n\n\n"
                                                              "class S(unittest.TestCase):\n    def test_slow(self):\n"
                                                              "        time.sleep(3)\n")})
    assert run_cli(root, "verify", "--record", "--test-command", UNITTEST).returncode == 0
    _apply(root, {"pkg/core.py": AGG_CORE.replace("COND", "s.isdigit()")})
    ev = _verify(root, UNITTEST)
    assert ev["verdict"] == "regression", ev["verdict"]
    assert _row(ev, "tests/test_core_strict.py")["status"] == "fail"


# 8. the same, without a record: the base check must run the importing file, not the class's module
def test_a_failure_of_an_imported_test_class_is_compared_in_its_own_file(tmp_path: Path):
    root = _project(tmp_path, AGG)
    _apply(root, {"pkg/core.py": AGG_CORE.replace("COND", "s.isdigit()")})
    ev = _verify(root, UNITTEST, "--workers", "1")
    assert ev["verdict"] == "regression", (ev["verdict"], _row(ev, "tests/test_core_strict.py"))


# 10. a symbolic link retargeted after a passing run
def test_retargeting_a_symlink_is_a_different_change(tmp_path: Path):
    root = _project(tmp_path, {
        "tests/__init__.py": "", "data/v1.txt": "ok\n", "data/v2.txt": "ok\n", "data/v3.txt": "broken\n",
        "data/current": ("link", "v1.txt"),
        "tests/test_data.py": ("import unittest\n\n\nclass D(unittest.TestCase):\n    def test_data(self):\n"
                               "        self.assertEqual(open('data/current').read(), 'ok\\n')\n")})
    _apply(root, {"data/current": ("link", "v2.txt")})
    first = _verify(root, UNITTEST, "--full")
    assert first["verdict"].startswith("selected-"), first["verdict"]
    _apply(root, {"data/current": ("link", "v3.txt")})
    again = _verify(root, UNITTEST, "--full")
    assert not again.get("reused") and again["verdict"] != first["verdict"], again["verdict"]


# 11. an edit beyond the first 4 MB of a file
def test_an_edit_past_the_first_megabytes_is_a_different_change(tmp_path: Path):
    big = "x" * 4_100_000 + "\nok\n"
    root = _project(tmp_path, {
        "tests/__init__.py": "", "data/big.txt": big,
        "tests/test_big.py": ("import unittest\n\n\nclass D(unittest.TestCase):\n    def test_tail(self):\n"
                              "        self.assertTrue(open('data/big.txt').read().endswith('ok\\n'))\n")})
    _apply(root, {"data/big.txt": "y" + big[1:]})
    first = _verify(root, UNITTEST, "--full")
    assert first["verdict"].startswith("selected-"), first["verdict"]
    _apply(root, {"data/big.txt": "y" + big[1:].replace("ok\n", "no\n")})
    again = _verify(root, UNITTEST, "--full")
    assert not again.get("reused") and again["verdict"] != first["verdict"], again["verdict"]


# 2. the same test fails at the base, but differently
def test_a_test_that_now_fails_differently_is_not_called_pre_existing(tmp_path: Path):
    root = _project(tmp_path, {
        "pkg/__init__.py": "", "tests/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n",
        "tests/test_f.py": ("import unittest\nfrom pkg.core import f\n\n\nclass F(unittest.TestCase):\n"
                            "    def test_f(self):\n        self.assertEqual(f(), 3)\n")})
    _apply(root, {"pkg/core.py": "def f():\n    raise KeyError('boom')\n"})
    ev = _verify(root, UNITTEST)
    assert ev["verdict"] == "failing (tests that fail at the base now fail differently)", ev["verdict"]
