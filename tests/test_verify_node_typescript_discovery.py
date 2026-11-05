"""`node --test` with no paths runs node's default patterns, which since node
23.6 (types stripped by default) include `*.test.ts`, `*.test.mts` and
`*.test.cts`. verify listed only the JavaScript forms, so a TypeScript
project tested that way had no test file at all: every change selected
nothing (`nothing-selected`, a passing verdict), a failing one included
(held-out-6 setup, Homebrew/actions: 0 test files)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import NODE_SANDBOX, _NODE_MAJOR, _git, _write

from repo_ai.verify.runner import parse_command

PASSING = ("selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected")


def test_node_default_discovery_lists_typescript_test_files():
    runner = parse_command("node --test")
    files = ["a/x.test.mts", "a/y.test.ts", "test/z.cts", "test/helper.mjs", "src/q.ts", "src/q.mts",
             "x.test.js", "node_modules/p/a.test.ts"]
    assert runner.test_files(files) == ["a/x.test.mts", "a/y.test.ts", "test/helper.mjs", "test/z.cts", "x.test.js"]


@pytest.mark.skipif(not NODE_SANDBOX or (_NODE_MAJOR or 0) < 24, reason="needs node 24 (types stripped by default)")
def test_a_failing_change_in_a_typescript_project_is_not_a_pass(tmp_path: Path):
    root = tmp_path / "p"
    _write(root, {
        "package.json": '{"name": "p", "type": "module", "scripts": {"test": "node --test"}}\n',
        "src/add.mts": "export function add(a: number, b: number): number {\n  return a + b;\n}\n",
        "src/neg.mts": "export function neg(a: number): number {\n  return -a;\n}\n",
        "add.test.mts": "import test from 'node:test';\nimport assert from 'node:assert';\n"
                        "import { add } from './src/add.mts';\ntest('add', () => assert.equal(add(1, 2), 3));\n",
        "neg.test.mts": "import test from 'node:test';\nimport assert from 'node:assert';\n"
                        "import { neg } from './src/neg.mts';\ntest('neg', () => assert.equal(neg(1), -1));\n",
    })
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    plan = json.loads(run_cli(root, "verify", "--json", "--test-command", "node --test").stdout)
    assert plan["test_files_total"] == 2, plan
    (root / "src" / "add.mts").write_text("export function add(a: number, b: number): number {\n  return a - b;\n}\n")
    out = json.loads(run_cli(root, "verify", "--run", "--json", "--test-command", "node --test").stdout)
    assert out["evidence"]["verdict"] == "regression", out["evidence"]["verdict"]
