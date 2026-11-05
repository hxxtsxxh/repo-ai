"""Adversarial review A: a node test file in which no test ran is reported `pass`, not `no-tests`.

`results.parse` counts node's per-file wrapper event (`"file": true`) in `FileOutcome.ran`, so a
file that registered no test, or whose child process ended before any test was reported
(`process.exit(0)` in the code under test), has `ran == 1` and is a pass. T20 promises "a file in
which no test ran is `no-tests`, never a pass", and `_check_skips` would then find that its tests
ran at the base. Here the change breaks `add` and turns off the only test of it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import NODE_SANDBOX, _git, _write

pytestmark = pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")

PASSING = {"selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected"}


def _project(tmp_path: Path, src_after: str) -> Path:
    root = tmp_path / "p"
    _write(root, {
        "src/m.js": ("exports.add = (a, b) => a + b;\nexports.enabled = true;\n"
                     "exports.run = (args) => (args.includes('--help') ? 'usage' : 'ok');\n"
                     "exports.mul = (a, b) => a * b;\n"),
        "test/a.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                           "const m = require('../src/m');\n"
                           "if (m.enabled) { test('add', () => assert.equal(m.add(1, 1), 2)); }\n"),
        "test/b.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                           "const m = require('../src/m');\n"
                           "test('help', () => assert.equal(m.run(['--help']), 'usage'));\n"
                           "test('mul', () => assert.equal(m.mul(2, 3), 6));\n"),
    })
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "src" / "m.js").write_text(src_after)
    return root


def _verify(root: Path, *extra: str) -> tuple[dict, dict[str, str]]:
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", "node --test", *extra)
    ev = json.loads(proc.stdout)["evidence"]
    return ev, {r["test"]: r["status"] for r in ev["results"]}


def test_a_node_file_that_registers_no_test_is_not_a_pass(tmp_path: Path):
    root = _project(tmp_path, "exports.add = (a, b) => a + b + 1;\nexports.enabled = false;\n"
                              "exports.run = (args) => (args.includes('--help') ? 'usage' : 'ok');\n"
                              "exports.mul = (a, b) => a * b;\n")
    # a batch of both files, and the full suite: both say "pass" on 083b6f1
    ev, status = _verify(root)
    ev1, status1 = _verify(root, "--full")
    assert ev["verdict"] not in PASSING and status.get("test/a.test.js") != "pass", (status, ev["verdict"])
    assert ev1["verdict"] not in PASSING and status1.get("test/a.test.js") != "pass", (status1, ev1["verdict"])


def test_a_node_file_cut_short_by_process_exit_0_is_not_a_pass(tmp_path: Path):
    """The code under test calls `process.exit(0)` (a CLI's --help path): node reports the file's
    child as passing, and the later failing test `mul` (broken by the same change) never runs."""
    root = _project(tmp_path, "exports.add = (a, b) => a + b;\nexports.enabled = true;\n"
                              "exports.run = (args) => { if (args.includes('--help')) { process.exit(0); } "
                              "return 'ok'; };\nexports.mul = (a, b) => a * b + 1;\n")
    ev, status = _verify(root)
    assert ev["verdict"] not in PASSING and status.get("test/b.test.js") != "pass", (ev["verdict"], status)


def test_a_node_suite_skipped_by_the_change_is_not_a_pass(tmp_path: Path):
    """The change breaks `add` and marks the suite testing it `describe.skip` (the usual way to
    silence a failing node suite). node reports only the skipped suite, which `parse` counts as a
    test that ran (`ran`) but not as a test (`tests`), so neither `no-tests` nor the all-skipped
    base check (`_check_skips`) applies: the file passes. With `test.skip` instead the same file is
    'not verified', as T20 promises."""
    root = _project(tmp_path, "exports.add = (a, b) => a + b + 1;\nexports.enabled = true;\n"
                              "exports.run = (args) => (args.includes('--help') ? 'usage' : 'ok');\n"
                              "exports.mul = (a, b) => a * b;\n")
    (root / "test" / "a.test.js").write_text(
        "const { describe, it } = require('node:test'); const assert = require('node:assert');\n"
        "const m = require('../src/m');\n"
        "describe.skip('add', () => { it('adds', () => assert.equal(m.add(1, 1), 2)); });\n")
    ev, status = _verify(root)
    assert ev["verdict"] not in PASSING, (ev["verdict"], status)
