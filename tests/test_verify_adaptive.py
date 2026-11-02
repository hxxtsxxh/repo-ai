"""Adaptive verification: per-test outcome reports and when they are trusted,
the run-shape decision, base comparisons and what may be cached or reused.

Unit tests run the reporters directly on fixture test files (our own code,
on the host); end-to-end tests go through the CLI and the sandbox.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import run_cli

from repo_ai.verify import cache, changes, evidence, results, strategy
from repo_ai.verify.runner import parse_command

SHIM = Path(results.__file__).with_name("rai_result.py")
REPORTER = Path(results.__file__).with_name("rai_reporter.mjs")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def _shim(root: Path, *target: str) -> tuple[int, Path]:
    out = root / "outcomes.jsonl"
    out.unlink(missing_ok=True)
    proc = subprocess.run([sys.executable, str(SHIM), "--out", str(out), "--", *target], cwd=root,
                          capture_output=True, text=True, timeout=120,
                          env={k: v for k, v in os.environ.items() if not k.startswith("PYTEST")})
    return proc.returncode, out


UNITTEST_FILES = {
    "tests/__init__.py": "",
    "tests/base.py": ("import unittest\n\n\nclass Shared(unittest.TestCase):\n"
                      "    def test_shared(self):\n        self.assertTrue(True)\n"),
    "tests/test_a.py": ("import unittest\n\n\nclass A(unittest.TestCase):\n    def test_ok(self):\n        pass\n\n"
                        "    def test_bad(self):\n        self.assertEqual(1, 2)\n\n"
                        "    def test_sub(self):\n        for i in range(2):\n            with self.subTest(i=i):\n"
                        "                self.assertEqual(i, 0)\n\n"
                        "    @unittest.expectedFailure\n    def test_xfail(self):\n        self.assertEqual(1, 2)\n\n"
                        "    @unittest.skip('later')\n    def test_skip(self):\n        pass\n"),
    "tests/test_b.py": ("import unittest\nfrom tests.base import Shared  # runs here too\n\n\n"
                        "class B(unittest.TestCase):\n    def test_err(self):\n        raise KeyError('k')\n"),
    "tests/test_import.py": "import no_such_module_xyz\n",
    "tests/test_crash.py": "raise RuntimeError('broken at import')\n",
    "tests/test_fixture.py": ("import unittest\n\n\nclass F(unittest.TestCase):\n    @classmethod\n"
                              "    def setUpClass(cls):\n        raise ValueError('fixture')\n\n"
                              "    def test_never(self):\n        pass\n"),
    "tests/test_empty.py": "X = 1\n",
}
MODS = ["tests.test_a", "tests.test_b", "tests.test_import", "tests.test_crash", "tests.test_fixture",
        "tests.test_empty"]
FILES = [m.replace(".", "/") + ".py" for m in MODS]


@pytest.fixture
def ut(tmp_path: Path) -> Path:
    root = tmp_path / "ut"
    _write(root, UNITTEST_FILES)
    return root


def _parse(root: Path, report: Path, files: list[str], code: int, runner=None, **kw) -> results.Attribution:
    runner = runner or parse_command("python -m unittest discover -s tests -t .")
    return results.parse(report, runner, files, str(root.resolve()), exit_code=code, timed_out=False, **kw)


# -- the unittest reporter -------------------------------------------------------
def test_a_unittest_batch_is_attributed_per_file_exactly_like_separate_runs(ut: Path):
    code, report = _shim(ut, "-m", "unittest", *MODS)
    att = _parse(ut, report, FILES, code)
    assert code == 1 and att.trusted, att.reason
    a, b = att.files["tests/test_a.py"], att.files["tests/test_b.py"]
    assert set(a.failing) == {"tests.test_a.A.test_bad", "tests.test_a.A.test_sub"}  # sub-test -> its test
    assert "AssertionError: 1 != 2" in a.failing["tests.test_a.A.test_bad"]
    assert a.ran == 3  # ok, xfail (expected), skip
    # a TestCase imported into another test module belongs to the file that ran it
    assert set(b.failing) == {"tests.test_b.B.test_err"} and b.ran == 1
    assert set(att.files["tests/test_import.py"].failing) and set(att.files["tests/test_crash.py"].failing)
    # a module that raises at import is one failed file, not an aborted run
    assert "RuntimeError: broken at import" in next(iter(att.files["tests/test_crash.py"].failing.values()))
    assert att.files["tests/test_fixture.py"].status == "fail"
    assert att.files["tests/test_empty.py"].ran == 0 and att.files["tests/test_empty.py"].status == "pass"
    # each file alone agrees with its share of the batch
    for mod, f in zip(MODS, FILES, strict=True):
        alone_code, alone = _shim(ut, "-m", "unittest", mod)
        one = _parse(ut, alone, [f], alone_code)
        assert set(one.files[f].failing) == set(att.files[f].failing), f


def test_a_missing_test_name_is_reported_as_not_defined(ut: Path):
    code, report = _shim(ut, "-m", "unittest", "tests.test_a.A.test_ok", "tests.test_a.A.test_gone")
    att = _parse(ut, report, ["tests/test_a.py"], code,
                 owners={"tests.test_a.A.test_gone": ["tests/test_a.py"]})
    assert att.trusted
    assert att.files["tests/test_a.py"].missing == {"tests.test_a.A.test_gone"}


def test_failfast_means_the_report_is_not_complete(ut: Path):
    code, report = _shim(ut, "-m", "unittest", "-f", "tests.test_a", "tests.test_b")
    att = _parse(ut, report, ["tests/test_a.py", "tests/test_b.py"], code)
    assert not att.trusted and "stopped" in att.reason


# -- the pytest reporter -----------------------------------------------------------
PYTEST_FILES = {
    "t/test_p.py": ("import pytest\n\n\ndef test_ok():\n    pass\n\n\ndef test_bad():\n    assert 1 == 2\n\n\n"
                    "@pytest.mark.parametrize('x', [1, 2])\ndef test_param(x):\n    assert x == 1\n\n\n"
                    "@pytest.fixture\ndef broken():\n    raise ValueError('fixture')\n\n\n"
                    "def test_fixture(broken):\n    pass\n\n\n@pytest.mark.xfail\ndef test_xfail():\n    assert 0\n"),
    "t/test_q.py": "def test_fine():\n    pass\n",
    "t/test_collect.py": "import no_such_module_xyz\n\n\ndef test_x():\n    pass\n",
}


def test_a_pytest_batch_is_attributed_per_file_and_continues_past_collection_errors(tmp_path: Path):
    pytest.importorskip("pytest")
    root = tmp_path / "pt"
    _write(root, PYTEST_FILES)
    runner = parse_command("python -m pytest t")
    files = ["t/test_collect.py", "t/test_p.py", "t/test_q.py"]
    argv = runner.group_argvs(files)[0]
    wrapped, _ = results.instrument(runner, argv, root, str(root.resolve()), "x")
    assert "--continue-on-collection-errors" in wrapped
    code, report = _shim(root, *wrapped[5:])
    att = results.parse(report, runner, files, str(root.resolve()), exit_code=code, timed_out=False)
    assert att.trusted, att.reason
    p = att.files["t/test_p.py"]
    assert set(p.failing) == {"t/test_p.py::test_bad", "t/test_p.py::test_param[2]", "t/test_p.py::test_fixture"}
    assert att.files["t/test_q.py"].status == "pass" and att.files["t/test_q.py"].ran == 1
    assert att.files["t/test_collect.py"].status == "fail"
    assert results.rerun_ids(runner, "t/test_p.py", sorted(p.failing), "") == sorted(p.failing)
    # the project's own command, run as is, stops at a collection error: never trusted as complete
    code, report = _shim(root, "-m", "pytest", "-q", "-p", "no:cacheprovider", "t")
    native = results.parse(report, runner, files, str(root.resolve()), exit_code=code, timed_out=False)
    assert code == 2 and not native.trusted


def test_pytest_exitfirst_is_not_a_complete_report(tmp_path: Path):
    pytest.importorskip("pytest")
    root = tmp_path / "pt"
    _write(root, PYTEST_FILES)
    runner = parse_command("python -m pytest t")
    code, report = _shim(root, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "t/test_p.py", "t/test_q.py")
    att = results.parse(report, runner, ["t/test_p.py", "t/test_q.py"], str(root.resolve()), exit_code=code,
                        timed_out=False)
    assert not att.trusted and "stopped" in att.reason


# -- the node reporter --------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_node_reporter_attributes_tests_files_and_load_errors(tmp_path: Path):
    root = tmp_path / "nd"
    _write(root, {
        "test/a.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                           "test('ok', () => {});\ntest('bad', () => { assert.equal(1, 2); });\n"
                           "test('suite', async (t) => { await t.test('inner', () => { throw new TypeError('x'); }); });\n"),
        "test/b.test.js": "require('./missing-module');\n",
        "test/c.test.js": "const test = require('node:test');\ntest('c', () => {});\n",
    })
    runner = parse_command("node --test test/")
    files = ["test/a.test.js", "test/b.test.js", "test/c.test.js"]
    argv = runner.group_argvs(files)[0]
    wrapped, report = results.instrument(runner, argv, root, str(root.resolve()), "n")
    wrapped = [shutil.which("node") or "node", *wrapped[1:]]
    proc = subprocess.run(wrapped, cwd=root, capture_output=True, text=True, timeout=120)
    att = results.parse(report, runner, files, str(root.resolve()), exit_code=proc.returncode, timed_out=False)
    assert att.trusted, att.reason
    assert set(att.files["test/a.test.js"].failing) == {"bad", "suite > inner"}  # not the parent "suite"
    assert set(att.files["test/b.test.js"].failing) == {"<file>"}
    assert att.files["test/c.test.js"].status == "pass"
    assert results.rerun_ids(runner, "test/a.test.js", ["bad"], "") is None  # node: by file


# -- trust rules ---------------------------------------------------------------------
def _report(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def test_reports_that_disagree_with_the_process_are_not_trusted(tmp_path: Path):
    runner = parse_command("python -m unittest discover -s tests -t .")
    root = str(tmp_path)
    f = "tests/test_a.py"
    ok = {"e": "end", "id": "tests.test_a.A.test_x", "mod": "tests.test_a", "path": "", "o": "pass"}
    bad = {**ok, "o": "fail", "msg": "AssertionError"}
    done = {"e": "done", "exit": 0}

    def att(events, code, timed_out=False):
        return results.parse(_report(tmp_path / "r.jsonl", events), runner, [f], root, exit_code=code,
                             timed_out=timed_out)
    assert att([ok, done], 0).trusted
    assert not att([ok, done], 1).trusted                 # a forged "all passed" report from a failing process
    assert not att([bad, done], 0).trusted                # failures, yet exit 0
    assert not att([ok], 0).trusted                       # incomplete (no end marker)
    assert not att([ok, done], 0, timed_out=True).trusted
    unknown = {**bad, "mod": "elsewhere.module", "id": "elsewhere.module.T.t"}
    assert not att([unknown, done], 1).trusted            # a failure no requested file owns
    (tmp_path / "r.jsonl").write_text("not json\n")
    assert not results.parse(tmp_path / "r.jsonl", runner, [f], root, exit_code=1, timed_out=False).trusted
    assert not results.parse(tmp_path / "missing.jsonl", runner, [f], root, exit_code=1, timed_out=False).trusted


def test_an_oversized_report_is_not_read(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(results, "MAX_REPORT_BYTES", 100)
    runner = parse_command("python -m unittest discover -s tests -t .")
    p = _report(tmp_path / "r.jsonl", [{"e": "end", "id": "x" * 200, "mod": "", "path": "", "o": "pass"}])
    att = results.parse(p, runner, ["tests/test_a.py"], str(tmp_path), exit_code=0, timed_out=False)
    assert not att.trusted and "too large" in att.reason


def test_rerun_ids_only_for_addressable_tests():
    ut = parse_command("python -m unittest discover -s tests -t .")
    assert results.rerun_ids(ut, "tests/test_a.py", ["tests.test_a.A.test_x"], "") == ["tests.test_a.A.test_x"]
    assert results.rerun_ids(ut, "tests/test_a.py", ["setUpClass (tests.test_a.A)"], "") is None
    assert results.rerun_ids(ut, "tests/test_a.py", ["<file>"], "") is None
    nested = parse_command("python -m unittest discover -s tests -t tests")
    assert results.rerun_ids(nested, "tests/test_a.py", ["test_a.A.test_x"], "") is None
    pt = parse_command("cd pkg && python -m pytest tests")
    assert results.rerun_ids(pt, "pkg/tests/test_a.py", ["tests/test_a.py::test_x[1]"], "") == \
        ["tests/test_a.py::test_x[1]"]
    assert results.rerun_ids(pt, "pkg/tests/test_a.py", ["tests/test_a.py"], "") is None  # collection error


# -- the run-shape decision ---------------------------------------------------------
def test_the_full_suite_is_chosen_only_when_it_is_expected_to_be_no_slower():
    r = parse_command("python -m unittest discover -s tests -t .")
    universe = [f"tests/test_{i}.py" for i in range(10)]
    d = {f: 0.3 for f in universe}
    kw = dict(full_required=False, full_requested=False, workers=4, measured_startup=0.25, full_runnable=True)
    fast_full = strategy.decide(r, universe[:6], universe, d, measured_full=0.6, **kw)
    assert fast_full.kind == "full" and "no slower" in fast_full.reason
    slow_full = strategy.decide(r, universe[:1], universe, d, measured_full=30.0, **kw)
    assert slow_full.kind == "targeted" and len(slow_full.batches) == 1
    unknown = strategy.decide(r, universe[:2], universe, {}, measured_full=None, **kw)
    assert unknown.kind == "targeted" and "no per-file durations" in unknown.reason
    # per-file times for the selection only: no full-suite estimate (speed-v1 run 5 printed "no a full-suite time")
    partial = strategy.decide(r, universe[:2], universe, {f: 0.3 for f in universe[:2]}, measured_full=None, **kw)
    assert partial.kind == "targeted" and partial.reason.startswith("no full-suite time yet")
    required = strategy.decide(r, universe[:1], universe, d, measured_full=30.0,
                               **{**kw, "full_required": True})
    assert required.kind == "full" and "not run twice" in required.reason
    assert strategy.decide(r, [], universe, d, measured_full=None, **kw).kind == "none"
    opaque = parse_command("npm test")
    assert strategy.decide(opaque, [], [], {}, measured_full=None, **kw).kind == "full"


def test_node_files_share_one_invocation_and_python_files_are_balanced():
    node = parse_command("node --test test/")
    files = [f"test/{i}.test.js" for i in range(9)]
    assert strategy.make_batches(node, files, {}, 4) == [sorted(files)]
    py = parse_command("python -m pytest tests")
    batches = strategy.make_batches(py, [f"tests/test_{i}.py" for i in range(9)], {}, 4)
    assert len(batches) == 4 and sorted(sum(batches, [])) == sorted(f"tests/test_{i}.py" for i in range(9))
    nested = parse_command("python -m unittest discover -s tests -t tests")
    assert strategy.make_batches(nested, ["tests/a.py", "tests/b.py"], {}, 4) == [["tests/a.py"], ["tests/b.py"]]


def test_an_unattributable_full_suite_is_not_chosen_for_speed_again():
    r = parse_command("python -m pytest tests")
    universe = [f"tests/test_{i}.py" for i in range(10)]
    d = {f: 0.3 for f in universe}
    kw = dict(full_required=False, full_requested=False, workers=4, measured_startup=0.25, full_runnable=True,
              measured_full=0.6)
    assert strategy.decide(r, universe[:6], universe, d, **kw).kind == "full"
    again = strategy.decide(r, universe[:6], universe, d, full_unusable="interrupted at collection", **kw)
    assert again.kind == "targeted" and "cannot be attributed" in again.reason


def test_process_limits_follow_measured_time_unless_given():
    assert strategy.process_limit(None, 600, False) == 600
    assert strategy.process_limit(2.0, 600, False) == 30.0
    assert strategy.process_limit(100.0, 600, False) == 510.0
    assert strategy.process_limit(2.0, 600, True) == 600


# -- what may be remembered ---------------------------------------------------------
def test_base_outcomes_are_trusted_asymmetrically(tmp_path: Path):
    bc = cache.BaselineCache(tmp_path, "env", "a" * 40)
    bc.put("test", "t1", "pass")
    assert bc.get("test", "t1") == ("pass", [])            # a pass can only make a failure look new
    bc.put("test", "t2", "fail")
    assert bc.get("test", "t2") is None                     # one failure is not enough to call it pre-existing
    bc.put("test", "t2", "fail")
    assert bc.get("test", "t2") == ("fail", [])
    bc.put("test", "t2", "pass")
    assert bc.get("test", "t2") is None                     # disagreeing runs: flaky, never trusted again
    bc.put("file", "f", "pass", src="record")
    assert bc.source("file", "f") == "recorded"
    bc.save()
    again = cache.BaselineCache(tmp_path, "env", "a" * 40)
    assert again.get("test", "t1") == ("pass", []) and again.get("test", "t2") is None
    assert cache.BaselineCache(tmp_path, "other-env", "a" * 40).get("test", "t1") is None
    assert cache.BaselineCache(tmp_path, "env", "b" * 40).get("test", "t1") is None
    assert cache.BaselineCache(tmp_path, "env", "").get("test", "t1") is None


def test_timings_are_per_environment_and_bounded(tmp_path: Path):
    t = cache.Timings(tmp_path, "e1")
    t.note_full(4.0)
    t.note_full(2.0)
    t.note_file("tests/a.py", 1.0)
    t.save()
    again = cache.Timings(tmp_path, "e1")
    assert again.full_s == 3.0 and again.file_s("tests/a.py") == 1.0
    assert cache.Timings(tmp_path, "e2").full_s is None
    for i in range(cache.MAX_TIMING_ENVS + 3):
        x = cache.Timings(tmp_path, f"k{i}")
        x.note_full(1.0)
        x.save()
    data = json.loads((tmp_path / cache.TIMINGS_FILE).read_text())
    assert len(data["envs"]) == cache.MAX_TIMING_ENVS


def test_the_quick_fingerprint_matches_the_full_change_detection(tmp_path: Path):
    root = tmp_path / "fp"
    _write(root, {"a.py": "A = 1\n", "b.py": "B = 1\n", "c.py": "C = 1\n", "d/e.py": "E = 1\n"})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert changes.fingerprint(root) == changes.detect(root).fingerprint
    (root / "a.py").write_text("A = 2\n")             # unstaged
    (root / "n.py").write_text("N = 1\n")             # untracked
    _git(root, "rm", "-q", "b.py")                    # deleted
    _git(root, "mv", "d/e.py", "d/f.py")              # renamed
    (root / "s.py").write_text("S = 1\n")
    _git(root, "add", "s.py")                         # staged
    (root / "deploy.pem").write_text("withheld\n")    # credential-like: not part of the change
    assert changes.fingerprint(root) == changes.detect(root).fingerprint


def test_verdicts_never_call_unverified_runs_passing():
    v = evidence.verdict
    nt = {"test": "t", "status": "no-tests"}
    assert v([nt], None, 1, False).startswith("no tests ran")
    unc = {"test": "t", "status": "fail", "classification": "not compared with the base"}
    assert v([unc], None, 1, False) == "failing (not compared with the base)"
    order = {"test": "t", "status": "fail", "baseline": "pass", "confirmed": False}
    assert v([order], None, 1, False).startswith("failing (only next to other test files")
    new = {"test": "t", "status": "fail", "baseline": "pass"}
    assert v([new, order], None, 1, False) == "regression"
    pre = {"test": "t", "status": "fail", "baseline": "fail", "new_failing_tests": []}
    assert v([pre], {"status": "fail", "attributed": True}, 1, False) == "failing (all failures pre-existing at the base)"
    assert v([], {"status": "fail", "attributed": False}, 1, False) == "full-suite-failed"
    # a full suite that timed out says nothing per file, but the selection's new failures still count
    assert v([new], {"status": "timeout", "attributed": False}, 1, False) == "regression"
    assert v([pre], {"status": "timeout", "attributed": False}, 1, False) == "full-suite-failed"
    assert v([{"test": "t", "status": "pass"}], {"status": "pass"}, 1, False) == "selected-and-full-suite-passed"
    # post-hoc (held-out-4 tomlkit): a full suite run only for speed that cannot be attributed is reported,
    # not passed off as a pass, and does not hide the selection's own result
    advisory = {"status": "fail", "attributed": False, "advisory": True}
    assert v([{"test": "t", "status": "pass"}], advisory, 1, False).startswith("selected-passed; full suite failed")
    assert v([new], advisory, 1, False) == "regression"


def test_reusable_evidence_must_match_exactly_and_be_recent(tmp_path: Path):
    rec = {"schema": evidence.SCHEMA, "fingerprint": "f" * 10, "reuse_key": "K", "verdict": "regression",
           "source_tree": {"unchanged": True}, "created": "now"}
    evidence.save(tmp_path, rec)
    assert evidence.find_reusable(tmp_path, "K")["reused"]["created"] == "now"
    assert evidence.find_reusable(tmp_path, "other") is None
    for p in (tmp_path / "evidence").glob("2*.json"):
        os.utime(p, (time.time() - evidence.REUSE_MAX_AGE_S - 10,) * 2)
    assert evidence.find_reusable(tmp_path, "K") is None
    evidence.save(tmp_path, {**rec, "source_tree": {"unchanged": False}})
    assert evidence.find_reusable(tmp_path, "K") is None


def test_aggregators_that_add_no_evidence_are_skipped(tmp_path: Path):
    from repo_ai.verify.changes import ChangedFile, Change
    from repo_ai.verify.select import Reason, Selected, _aggregators
    from repo_ai.verify.testmap import TestMap
    tm = TestMap(runner={}, commit="", backend="", created="", interpreter="")
    tm.tests = {
        "tests/__init__.py": {"status": "pass", "traced": True, "units": {
            "tests/__init__.py": ["1:<module>", "9:load_tests"], "tests/test_a.py": ["3:test_a"],
            "pkg/m.py": ["1:<module>", "4:f"]}},
        "tests/test_a.py": {"status": "pass", "traced": True, "units": {
            "tests/test_a.py": ["3:test_a"], "pkg/m.py": ["1:<module>", "4:f"]}},
    }
    universe = {"tests/__init__.py", "tests/test_a.py"}
    init = tmp_path / "tests" / "__init__.py"
    init.parent.mkdir()
    collector = ("import os\nimport unittest\n\n\ndef load_tests(loader, tests, pattern):\n"
                 "    here = os.path.dirname(__file__)\n    suite = unittest.TestSuite()\n"
                 "    suite.addTests(loader.discover(here, pattern or 'test_*.py'))\n    return suite\n")
    init.write_text(collector)
    change = Change(tmp_path, "HEAD", "c", [ChangedFile("pkg/m.py", "modified", units=["4:f"])], "fp")
    picks = {t: Selected(t, [Reason("runtime", "executed changed f", {"units": ["4:f"]})]) for t in universe}
    assert list(_aggregators(picks, tm, universe, change)) == ["tests/__init__.py"]
    for body in ("import pkg.conf\npkg.conf.STRICT = True\n",  # configures what it imports: keep it
                 "import doctest\nimport pkg.m\n\n\ndef load_tests(loader, tests, pattern):\n"
                 "    tests.addTests(doctest.DocTestSuite(pkg.m))\n    return tests\n",
                 "import pkg\n\n\ndef load_tests(loader, tests, pattern):\n    pkg.setup()\n    return tests\n"):
        init.write_text(body)
        assert list(_aggregators(picks, tm, universe, change)) == [], body
    init.write_text(collector)
    only = {"tests/__init__.py": picks["tests/__init__.py"]}  # nothing else executes the change: keep it
    assert _aggregators(only, tm, universe, change) == {}


# -- end to end, sandboxed ---------------------------------------------------------
def _sandbox() -> bool:
    import tempfile
    from repo_ai.sandbox import SandboxUnavailable
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        try:
            ex = get_executor(Path(d), "auto", "python")
            with isolate.materialize(Path(d)) as ws:
                return ex.in_workspace(ws).run(["python", "-c", "pass"], timeout_s=60).exit_code == 0
        except SandboxUnavailable:
            return False


needs_sandbox = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")
CMD = "python -m unittest discover -s tests -t ."


def _test_file(i: int, body: str = "        self.assertEqual(add({i}, 1), {j})\n") -> str:
    return ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
            f"    def test_{i}(self):\n" + body.format(i=i, j=i + 1))


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n", "tests/__init__.py": "",
             "tests/helpers.py": "VALUE = 1\n"}
    files.update({f"tests/test_m{i}.py": _test_file(i) for i in range(6)})
    _write(root, files)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _run(repo: Path, *extra: str) -> dict:
    proc = run_cli(repo, "verify", "--run", "--json", "--workers", "2", "--test-command", CMD, *extra)
    assert proc.returncode in {0, 1}, proc.stderr
    return json.loads(proc.stdout)["evidence"]


@needs_sandbox
def test_a_failing_batch_is_attributed_without_rerunning_files_and_base_checked_once(proj: Path):
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b if a not in (2, 3) else 0\n")
    ev = _run(proj)
    failed = sorted(r["test"] for r in ev["results"] if r["status"] != "pass")
    assert failed == ["tests/test_m2.py", "tests/test_m3.py"]
    assert ev["processes"].get("rerun", 0) == 0                   # no file-by-file re-runs
    assert ev["processes"]["base"] == 1                           # one grouped base re-check, by test id
    assert all(r["base_check"] == "per test" and r["classification"].startswith("new failure")
               for r in ev["results"] if r["status"] != "pass")
    assert ev["verdict"] == "regression"
    again = _run(proj)                                            # identical state: reused
    assert again.get("reused") and again["verdict"] == "regression"
    fresh = _run(proj, "--rerun")                                 # base outcomes now come from the cache
    assert fresh["processes"].get("base", 0) == 0
    assert all(r["baseline_source"] == "cached" for r in fresh["results"] if r["status"] != "pass")


@needs_sandbox
def test_a_failure_that_only_happens_next_to_another_file_is_not_called_a_regression(proj: Path):
    # test_m0 leaves global state behind; test_m1 fails only when it runs after test_m0 in one process
    (proj / "tests" / "test_m0.py").write_text(
        "import unittest\nimport tests.helpers as h\n\n\nclass T(unittest.TestCase):\n"
        "    def test_0(self):\n        h.VALUE = 2\n")
    (proj / "tests" / "test_m1.py").write_text(
        "import unittest\nimport tests.helpers as h\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
        "    def test_1(self):\n        self.assertEqual(add(h.VALUE, 0), 1)\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "order-dependent pair")
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")  # behaviour unchanged
    ev = _run(proj, "--workers", "1")
    m1 = next(r for r in ev["results"] if r["test"] == "tests/test_m1.py")
    if m1["status"] == "pass":
        pytest.skip("the files did not share a process in this run")
    assert m1.get("confirmed") is False and "only next to other test files" in m1["classification"]
    assert ev["verdict"].startswith("failing (only next to other test files")


@needs_sandbox
def test_after_a_measured_full_suite_a_cheap_suite_runs_whole_and_is_compared_in_the_same_shape(proj: Path):
    (proj / "tests" / "test_m5.py").write_text(  # already failing, and unrelated to calc
        "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_5(self):\n        self.assertEqual(1, 2)\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "a failing test at the base")
    assert run_cli(proj, "update", "-q").returncode == 0  # the index follows the new commit
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    first = _run(proj, "--full")                       # measures the full suite
    assert first["strategy"]["kind"] == "full" and first["processes"]["full"] == 1
    assert run_cli(proj, "verify", "--record", "--test-command", CMD).returncode == 0
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b if a != 4 else 0\n")
    ev = _run(proj)
    assert ev["strategy"]["kind"] == "full", ev["strategy"]
    by = {r["test"]: r for r in ev["results"] if r["status"] != "pass"}
    assert by["tests/test_m4.py"]["classification"].startswith("new failure")
    assert by["tests/test_m5.py"]["selected"] is False, by["tests/test_m5.py"]["linked_by"]
    assert by["tests/test_m5.py"]["classification"].startswith("already failing at the base")
    assert {r["base_check"] for r in by.values()} == {"full suite"}
    assert ev["verdict"] == "regression"


@needs_sandbox
def test_a_hanging_file_in_a_batch_is_reported_and_the_rest_still_run(proj: Path):
    (proj / "tests" / "test_m3.py").write_text(_test_file(3, "        import time\n        time.sleep(300)\n"))
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "a hanging test")
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    started = time.monotonic()
    ev = _run(proj, "--workers", "1", "--timeout", "8")
    assert time.monotonic() - started < 120
    status = {r["test"]: r["status"] for r in ev["results"]}
    assert status["tests/test_m3.py"] == "timeout"
    assert all(s == "pass" for t, s in status.items() if t != "tests/test_m3.py"), status
    assert ev["processes"].get("rerun", 0) == 0


@needs_sandbox
def test_helper_modules_matched_by_the_pattern_are_not_failures(proj: Path):
    cmd = "python -m unittest discover -s tests -t . -p *.py"
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    proc = run_cli(proj, "verify", "--run", "--json", "--test-command", cmd)
    ev = json.loads(proc.stdout)["evidence"]
    helpers = [r for r in ev["results"] if r["test"] == "tests/helpers.py"]
    assert not helpers or helpers[0]["status"] == "no-tests"
    assert ev["verdict"].startswith("selected-passed"), ev["verdict"]


@needs_sandbox
def test_a_forged_passing_report_cannot_turn_a_failure_into_a_pass(proj: Path):
    # the test overwrites its own outcome report with "all passed" and then fails
    (proj / "tests" / "test_m2.py").write_text(
        "import glob, json, unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
        "    def test_2(self):\n        for p in glob.glob('.repo-ai/run/*.jsonl'):\n"
        "            open(p, 'w').write(json.dumps({'e': 'done', 'exit': 0}) + '\\n')\n"
        "        self.assertEqual(add(2, 1), 4)\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-qm", "forging test")
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    ev = _run(proj)
    m2 = next(r for r in ev["results"] if r["test"] == "tests/test_m2.py")
    assert m2["status"] == "fail" and ev["verdict"] != "selected-passed (full suite not run)"


def test_the_report_mode_gate_never_blocks_and_says_what_is_missing(tmp_path: Path):
    from repo_ai.config import load_config
    from repo_ai.paths import detect_kind, resolve_layout
    from repo_ai.verify.gate import decision
    root = tmp_path / "g"
    _write(root, {"calc/core.py": "def add(a, b):\n    return a + b\n"})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = load_config(root)
    layout = resolve_layout(root, cfg, prefer=detect_kind(root) or "standard")
    out = json.loads(decision(root, layout, {}, mode="report"))
    assert "decision" not in out and "no verification evidence" in out["systemMessage"]
    assert decision(root, layout, {}, mode="report") == ""  # once per change


@needs_sandbox
def test_concurrent_runs_share_caches_safely_and_leave_the_tree_unchanged(proj: Path):
    from conftest import cli_env
    (proj / "calc" / "core.py").write_text("def add(a, b):\n    return a + b if a != 1 else 0\n")
    before = subprocess.run(["git", "diff", "--stat"], cwd=proj, capture_output=True, text=True).stdout
    cmd = [sys.executable, "-m", "repo_ai", "verify", "--run", "--rerun", "--json", "--test-command", CMD,
           "-C", str(proj)]
    procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=cli_env())
             for _ in range(3)]
    outs = [p.communicate(timeout=300) for p in procs]
    verdicts = {json.loads(o)["evidence"]["verdict"] for o, _ in outs}
    assert verdicts == {"regression"}, [e[-300:] for _, e in outs]
    assert all(json.loads(o)["evidence"]["source_tree"]["unchanged"] for o, _ in outs)
    assert subprocess.run(["git", "diff", "--stat"], cwd=proj, capture_output=True, text=True).stdout == before
    for name in (cache.BASELINE_FILE, cache.TIMINGS_FILE):  # whichever writer won, the file is whole
        path = proj / ".repo-ai" / "state" / name
        assert not path.exists() or json.loads(path.read_text())["version"] == 1


def _node_sandbox() -> tuple[bool, int]:
    """(the sandbox can start node, node's major version)."""
    import tempfile
    from repo_ai.sandbox import SandboxUnavailable
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    node = shutil.which("node")
    if node is None:
        return False, 0
    try:
        major = int(subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
                    .lstrip("v").split(".")[0])
    except ValueError:
        major = 0
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        try:
            ex = get_executor(Path(d), "auto", "node")
            with isolate.materialize(Path(d)) as ws:
                ok = ex.in_workspace(ws).run(["node", "-e", "0"], timeout_s=60, toolchain="node").exit_code == 0
        except SandboxUnavailable:
            ok = False
    return ok, major


NODE_SANDBOX, _NODE_MAJOR = _node_sandbox()


@pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")
def test_a_hanging_node_file_is_reported_and_the_finished_files_keep_their_results(tmp_path: Path):
    root = tmp_path / "nodeproj"
    files = {"src/add.js": "exports.add = (a, b) => a + b;\n",
             "test/hang.test.js": ("const test = require('node:test'); const { add } = require('../src/add');\n"
                                   "test('hang', async () => { add(1, 2); await new Promise(() => setInterval(() => {}, 1000)); });\n")}
    files.update({f"test/ok{i}.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                                          "const { add } = require('../src/add');\n"
                                          f"test('ok{i}', () => assert.equal(add({i}, 1), {i + 1}));\n") for i in range(3)})
    _write(root, files)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "src" / "add.js").write_text("exports.add = (a, b) => b + a;\n")
    proc = run_cli(root, "verify", "--run", "--json", "--timeout", "8", "--test-command", "node --test")
    ev = json.loads(proc.stdout)["evidence"]
    status = {r["test"]: r["status"] for r in ev["results"]}
    tails = {r["test"]: r.get("output_tail", "")[-300:] for r in ev["results"] if r["status"] != "pass"}
    assert status.get("test/hang.test.js") == "timeout", (status, tails, proc.stderr[-800:])
    assert all(status[f"test/ok{i}.test.js"] == "pass" for i in range(3)), (status, tails)
    # node buffers its reporter output: when the time-out's kill comes before a flush (seen on CI), the
    # finished files are unknown and the batch is re-run file by file, which is slower but still correct
    assert ev["processes"].get("rerun", 0) <= 4


@pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")
def test_a_failing_node_file_behind_a_hanging_one_is_never_reported_passing(tmp_path: Path):
    """node writes a file's test events only when its turn comes, but reports the file's completion at
    once: when the run is cut while an earlier file hangs, a later file that already failed has
    completed with no results in the report yet. It must run again, never count as passing."""
    root = tmp_path / "nodeorder"
    files = {"src/add.js": "exports.add = (a, b) => a + b;\n",
             "test/a_hang.test.js": ("const test = require('node:test'); const { add } = require('../src/add');\n"
                                     "test('hang', async () => { if (add(1, 1) !== 2) await new Promise(() => "
                                     "setInterval(() => {}, 1000)); });\n"),
             "test/z_bad.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                                    "const { add } = require('../src/add');\n"
                                    "test('bad', () => assert.equal(add(2, 2), 4));\n")}
    _write(root, files)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "src" / "add.js").write_text("exports.add = (a, b) => a + b + 1;\n")  # both files break
    proc = run_cli(root, "verify", "--run", "--json", "--timeout", "6", "--test-command", "node --test")
    ev = json.loads(proc.stdout)["evidence"]
    status = {r["test"]: r["status"] for r in ev["results"]}
    assert status.get("test/z_bad.test.js") == "fail", (status, proc.stderr[-800:])
    assert status.get("test/a_hang.test.js") == "timeout", status
    assert ev["verdict"] == "regression", ev["verdict"]


@needs_sandbox
def test_a_legacy_layout_run_keeps_its_own_state_out_of_the_integrity_check(tmp_path: Path):
    """`repo-ai init` with no `--agent` keeps state in `.bob/context`; a run
    writes timings and evidence there and must not call that a source-tree
    change (or leave it for git to pick up)."""
    root = tmp_path / "legacy"
    _write(root, {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
                  "tests/__init__.py": "", "tests/test_m0.py": _test_file(0)})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "-q").returncode == 0
    assert (root / ".bob" / "context").is_dir()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    ev = _run(root)
    assert ev["source_tree"]["unchanged"] and not ev["verdict"].startswith("invalid"), ev["source_tree"]
    assert (root / ".bob" / "context" / cache.TIMINGS_FILE).exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    assert status.split("\n")[0].strip() == "M calc/core.py" and ".bob/" not in status, status
