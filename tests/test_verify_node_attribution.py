"""node writes a file's test events only when its turn comes, after every earlier file's, while the
file's own completion is reported at once. When a run is cut (the time limit) while an earlier file
hangs, a later file may have completed with none of its results in the report. Whatever the shape
(a batch, the full suite) and whatever the base does, such a file is never reported passing, never
"no tests", and its new failure never becomes pre-existing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli
from test_verify_adaptive import NODE_SANDBOX, _git, _write

pytestmark = pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")

HANG = "await new Promise(() => setInterval(() => {}, 1000));"


def _project(tmp_path: Path, hang_at_base: bool) -> Path:
    root = tmp_path / "p"
    base_hang = HANG if hang_at_base else ""
    _write(root, {
        "src/add.js": "exports.add = (a, b) => a + b;\n",
        "test/a_hang.test.js": ("const test = require('node:test'); const { add } = require('../src/add');\n"
                                f"test('hang', async () => {{ add(1, 1); {base_hang} if (add(1, 1) !== 2) {{ {HANG} }} }});\n"),
        "test/b_ok.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                              "const { add } = require('../src/add');\n"
                              "test('ok', () => assert.equal(typeof add, 'function'));\n"),
        "test/c_bad.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                               "const { add } = require('../src/add');\n"
                               "test('bad', () => assert.equal(add(2, 2), 4));\n"),
    })
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "src" / "add.js").write_text("exports.add = (a, b) => a + b + 1;\n")
    return root


def _rebase(root: Path, files: dict[str, str | None]) -> None:
    """Commit more test files at the base, then apply the change again."""
    (root / "src" / "add.js").write_text("exports.add = (a, b) => a + b;\n")
    for rel, text in files.items():
        if text is None:
            (root / rel).unlink()
        else:
            (root / rel).write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "more tests")
    (root / "src" / "add.js").write_text("exports.add = (a, b) => a + b + 1;\n")


def _verify(root: Path, *extra: str) -> tuple[dict, dict[str, str]]:
    proc = run_cli(root, "verify", "--run", "--json", "--timeout", "6", "--test-command", "node --test", *extra)
    ev = json.loads(proc.stdout)["evidence"]
    return ev, {r["test"]: r["status"] for r in ev["results"]}


def test_a_passing_and_a_failing_file_after_a_hanging_one_keep_their_own_results(tmp_path: Path):
    ev, status = _verify(_project(tmp_path, hang_at_base=False))
    assert status.get("test/c_bad.test.js") == "fail", status
    assert status.get("test/b_ok.test.js") == "pass", status
    assert status.get("test/a_hang.test.js") == "timeout", status
    assert ev["verdict"] == "regression", ev["verdict"]


DESCRIBE_HANG = ("const { describe, it } = require('node:test'); const { add } = require('../src/add');\n"
                 "describe('S', () => { it('ok', () => {}); it('hang', async () => { if (add(1, 1) !== 2) "
                 "{ " + HANG + " } }); });\n")


def test_the_full_suite_cut_by_its_limit_never_passes_a_later_failing_file(tmp_path: Path):
    """A hang inside a suite leaves the suite open in the report, so the full suite's time-out names
    it (`_full_timed_out`); a later failing file completed without results must not become passing
    or "no tests" (on main it was "no tests")."""
    root = _project(tmp_path, hang_at_base=False)
    _rebase(root, {"test/a_hang.test.js": DESCRIBE_HANG})
    ev, status = _verify(root, "--full")
    assert status.get("test/c_bad.test.js") == "fail", (status, ev.get("full_suite"))
    assert status.get("test/a_hang.test.js") == "timeout", status
    assert ev["verdict"] == "regression", ev["verdict"]


def test_a_file_reported_before_the_hang_keeps_its_result_without_a_re_run(tmp_path: Path):
    root = _project(tmp_path, hang_at_base=False)
    _rebase(root, {"test/a_hang.test.js": None, "test/m_hang.test.js": DESCRIBE_HANG,
                   "test/0_bad.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                                          "const { add } = require('../src/add');\n"
                                          "test('first', () => assert.equal(add(1, 1), 2));\n")})
    ev, status = _verify(root)
    assert status.get("test/0_bad.test.js") == "fail", status
    assert status.get("test/m_hang.test.js") == "timeout", status
    assert status.get("test/c_bad.test.js") == "fail", status


def test_a_hang_already_at_the_base_never_hides_a_new_failure_behind_it(tmp_path: Path):
    ev, status = _verify(_project(tmp_path, hang_at_base=True))
    rows = {r["test"]: r for r in ev["results"]}
    assert status.get("test/c_bad.test.js") == "fail", status
    assert str(rows["test/c_bad.test.js"].get("classification", "")).startswith("new failure"), \
        rows["test/c_bad.test.js"].get("classification")
    assert ev["verdict"] == "regression", (ev["verdict"], {t: r.get("classification") for t, r in rows.items()})


def test_only_files_whose_results_were_followed_by_another_files_count_as_reported():
    """Sandbox-free: `_node_reported` and the hung / done / pending partition of a cut node batch."""
    import random
    from repo_ai.verify import engine
    from repo_ai.verify.results import Attribution

    def att(order, finished, done):
        a = Attribution(trusted=False)
        a.order, a.finished, a.done = list(order), set(finished), done
        return a

    assert engine._node_reported(att(["a", "b"], {"a", "b", "c"}, False)) == {"a"}
    assert engine._node_reported(att(["a", "b"], {"a", "b", "c"}, True)) == {"a", "b"}
    assert engine._node_reported(att([], {"a"}, False)) == set()
    rng = random.Random(7)
    files = ["a", "b", "c", "d", "e"]
    for _ in range(500):
        order = rng.sample(files, rng.randint(0, 5))
        finished = {f for f in files if rng.random() < 0.6}
        done = rng.random() < 0.3
        a = att(order, finished, done)
        rep = engine._node_reported(a)
        started = set(order)
        hung = [x for x in files if x in started and x not in finished]
        ok = [x for x in files if x in rep]
        pending = [x for x in files if x not in ok and x not in hung]
        assert sorted(hung + ok + pending) == sorted(files) and not set(hung) & set(ok)
        allowed = set(order) if done else set(order[:-1])
        assert set(ok) <= allowed & finished
