"""When a per-test report outranks the exit status (and when it must not).

An exit status 0 is not taken at its word when the process's own report
shows a failing or unfinished test or stops before the runner's end. A
report that legitimately disagrees with "every recorded failure is a
failure" must not turn an ordinary passing change into a failing one:
node `todo` tests, unittest runs started by a test, a report cut at the
size limit, and node test files that are plain scripts. Found by an
independent review of the fix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import CMD, NODE_SANDBOX, _git, _write, needs_sandbox

PASSING = ("selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected")
needs_node = pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "p"
    _write(root, files)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _run(root: Path, cmd: str, *extra: str) -> dict:
    out = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", cmd, *extra)
    assert out.stdout, out.stderr
    return json.loads(out.stdout)["evidence"]


@needs_node
def test_a_failing_node_todo_test_is_not_a_failure(tmp_path: Path):
    base = "const test = require('node:test'); const assert = require('node:assert');\n" \
           "const m = require('../src/m');\ntest('add', () => assert.equal(m.add(1, 1), 2));\n"
    root = _repo(tmp_path, {"src/m.js": "exports.add = (a, b) => a + b;\n", "test/a.test.js": base})
    _write(root, {"src/m.js": "exports.add = (a, b) => b + a;\nexports.div = undefined;\n",
                  "test/a.test.js": base + "test('div, not written yet', { todo: true }, () => "
                                           "assert.equal(m.div(6, 3), 2));\n"})
    ev = _run(root, "node --test")
    assert ev["verdict"].startswith(PASSING), ev["verdict"]


@needs_sandbox
def test_a_unittest_run_started_by_a_test_is_not_the_outer_runs_result(tmp_path: Path):
    retry = ("def retry(n):\n    def deco(f):\n        def w(*a, **k):\n            for _ in range(n - 1):\n"
             "                try:\n                    return f(*a, **k)\n                except AssertionError:\n"
             "                    pass\n            return f(*a, **k)\n        return w\n    return deco\n")
    test = ("import unittest\nfrom lib.retry import retry\n\n\nclass RetryTest(unittest.TestCase):\n"
            "    def test_gives_up_after_n(self):\n        calls = []\n\n        class Inner(unittest.TestCase):\n"
            "            @retry(3)\n            def test_always_fails(self):\n                calls.append(1)\n"
            "                self.fail('boom')\n\n        result = unittest.TestResult()\n"
            "        unittest.defaultTestLoader.loadTestsFromTestCase(Inner).run(result)\n"
            "        self.assertEqual(len(result.failures), 1)\n        self.assertEqual(len(calls), 3)\n")
    root = _repo(tmp_path, {"lib/__init__.py": "", "lib/retry.py": retry, "tests/__init__.py": "",
                            "tests/test_retry.py": test})
    _write(root, {"lib/retry.py": retry.replace("for _ in range(n - 1):", "for _ in range(n - 1):  # retries")})
    ev = _run(root, CMD)
    assert ev["verdict"].startswith(PASSING), ev["verdict"]


@needs_node
def test_node_test_files_without_test_calls_still_pass_and_still_fail(tmp_path: Path):
    root = _repo(tmp_path, {
        "src/m.js": "exports.add = (a, b) => a + b;\nexports.mul = (a, b) => a * b;\n",
        "test/add.test.js": "const assert = require('node:assert');\nconst m = require('../src/m');\n"
                            "assert.equal(m.add(1, 1), 2);\n",
        "test/mul.test.js": "const assert = require('node:assert');\nconst m = require('../src/m');\n"
                            "assert.equal(m.mul(2, 3), 6);\n"})
    _write(root, {"src/m.js": "exports.add = (a, b) => b + a;\nexports.mul = (a, b) => b * a;\n"})
    assert _run(root, "node --test")["verdict"].startswith(PASSING)
    _write(root, {"src/m.js": "exports.add = (a, b) => b + a + 1;\nexports.mul = (a, b) => b * a;\n"})
    assert _run(root, "node --test")["verdict"] == "regression"


@needs_sandbox
def test_a_file_that_skips_every_test_is_not_verified_when_its_base_run_times_out(tmp_path: Path):
    test = ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")
    root = _repo(tmp_path, {"calc/__init__.py": "", "tests/__init__.py": "", "tests/test_core.py": test,
                            "calc/core.py": "import time\n\n\ndef add(a, b):\n    time.sleep(60)\n    return a + b\n"})
    _write(root, {"calc/core.py": "def add(a, b):\n    return a + b + 1\n",
                  "tests/test_core.py": test.replace("    def test_add", "    @unittest.skip('slow')\n    def test_add")})
    ev = _run(root, CMD, "--timeout", "5")
    assert not ev["verdict"].startswith(PASSING), ev["verdict"]


def test_a_report_cut_at_the_size_limit_does_not_contradict_exit_status_0():
    from repo_ai.verify import results
    att = results.Attribution(trusted=False, reason="the per-test report is too large to trust",
                              files={"t.py": results.FileOutcome()})
    assert results.hides_failure(att) == ""
    att.files["t.py"].status = "fail"
    assert results.hides_failure(att) == "its per-test report shows failing tests"
    cut = results.Attribution(trusted=False, reason="the per-test report is incomplete (the process ended early)",
                              files={"t.py": results.FileOutcome()})
    assert results.hides_failure(cut) == "its per-test report ends before the test runner finished"
    assert results.hides_failure(results.Attribution(trusted=False, reason="no per-test report was written")) == ""
