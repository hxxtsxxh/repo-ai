"""Adversarial probes for accepting identical per-test skips: real sandbox observations (skipped without a backend)."""
import os
import subprocess
import sys

import pytest

from repo_ai import sandbox
from repo_ai.mission import coverage, diagnosis, futures, verification

REAL_OBSERVE = verification.observe

PREF = "seatbelt" if sys.platform == "darwin" else "bwrap"
try:
    _available = sandbox.get_backend(PREF).available()[0]
except sandbox.SandboxUnavailable:
    _available = False
if not _available:
    pytest.skip("host sandbox unavailable", allow_module_level=True)


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.invalid"}
    subprocess.run(["git", *args], cwd=cwd, check=True, env=env, capture_output=True)


def _repo(tmp_path, files):
    root = tmp_path / "project"
    root.mkdir()
    for rel, text in files.items():
        (root / rel).write_text(text)
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def _obs(root, monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    return REAL_OBSERVE(root, "python -m pytest -q", sandbox_preference=PREF)


# --- 1. futures --rehearse: a diff that turns the failing test into a skip is rehearsed as PASS -----------------
def test_futures_rehearsal_refuses_a_diff_that_makes_the_failing_test_skip(tmp_path, monkeypatch):
    root = _repo(tmp_path, {
        "calc.py": "value = 1\n",
        "test_calc.py": "import pytest, calc\n"
                        "def test_value():\n"
                        "    if getattr(calc, 'SKIP', False): pytest.skip('unsupported here')\n"
                        "    assert calc.value == 2\n"
                        "def test_other():\n    assert True\n"})
    base = _obs(root, monkeypatch)
    assert base["complete"] and base["failed"] == 1
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,2 @@\n value = 1\n+SKIP = True\n"
    state = {"contract": {"write_paths": ["calc.py"], "acceptance": ["python -m pytest -q"]},
             "source": {"head": head}, "diff": diff, "baseline": base}
    monkeypatch.setattr(futures, "status", lambda r, m: state)
    monkeypatch.setattr(futures, "check_privacy", lambda r, c: True)
    real = verification.observe
    monkeypatch.setattr(verification, "observe",
                        lambda p, c, timeout_s=60: real(p, c, timeout_s=timeout_s, sandbox_preference=PREF))
    report = futures.analyze_futures(root, "m1", rehearse=True)
    # the same candidate never PASSes compare(): the skip set differs from the baseline
    (root / "calc.py").write_text("value = 1\nSKIP = True\n")
    cand = _obs(root, monkeypatch)
    assert verification.compare(base, cand)[0] == "FAIL"
    assert report["rehearsal"]["verdict"] != "PASS", report["rehearsal"]


# --- 2. pytest module-level skip: the file's tests silently vanish; the observation is complete, skipped == 0 ----
def test_module_level_skip_is_recorded_and_held_to_set_equality(tmp_path, monkeypatch):
    root = _repo(tmp_path, {
        "calc.py": "value = 1\nFAST = False\n",
        "test_calc.py": "import calc\ndef test_value():\n    assert calc.value == 2\n",
        "test_fast.py": "import pytest, calc\n"
                        "if not calc.FAST: pytest.skip('no fast path', allow_module_level=True)\n"
                        "def test_fast():\n    assert calc.value == 2\n"})
    base = _obs(root, monkeypatch)
    (root / "calc.py").write_text("value = 2\nFAST = False\n")
    cand = _obs(root, monkeypatch)
    verdict = verification.compare(base, cand)
    # design/commit: "file/suite-level skips stay refused"; observed: PASS, skipped == 0, test_fast.py never ran
    assert not (verdict[0] == "PASS" and cand["skipped"] == 0), (verdict, cand["test_ids"], cand["skipped"])


# --- 3. pytest subtests: a fixed test with one always-skipping subtest becomes "skip" and the mission abstains ---
@pytest.mark.xfail(strict=True, reason="known limit: a subtest that always skips makes a fixed test read as skipped, "
                   "so the mission abstains (safe; see docs/engineering/designs/MISSION-REAL-SUITES.md)")
def test_subtest_skip_turns_a_fixed_test_into_a_skip(tmp_path, monkeypatch):
    root = _repo(tmp_path, {
        "calc.py": "def f(x):\n    return x\n",
        "test_calc.py": "import sys, unittest, calc\n"
                        "class T(unittest.TestCase):\n"
                        "    def test_f(self):\n"
                        "        for c in (1, 2):\n"
                        "            with self.subTest(c=c):\n"
                        "                if c == 1: self.skipTest('platform')\n"
                        "                self.assertEqual(calc.f(c), c * 2)\n"})
    base = _obs(root, monkeypatch)
    (root / "calc.py").write_text("def f(x):\n    return x * 2\n")
    cand = _obs(root, monkeypatch)
    assert base["complete"] and cand["complete"], (base["reasons"], cand["reasons"], cand["outcomes"])
    assert list(base["outcomes"].values()) == ["fail"]
    assert verification.compare(base, cand) == ("PASS", []), (cand["outcomes"], verification.compare(base, cand))


# --- 4. downstream consumers that assume outcomes in {pass, fail} ---------------------------------------------
def test_diagnosis_labels_identical_skips_as_skipped_both():
    assert diagnosis.CLASSIFICATIONS.get(("skip", "skip"), "NOT_COMPARABLE") != "NOT_COMPARABLE"


def test_coverage_reports_an_identically_skipped_test_as_not_observed():
    report = coverage.assess({"requirements": [{"text": "r", "kind": "preserve", "tests": ["t.py::test_win"]}],
                              "sha256": "x"},
                             {"t.py::test_win": "skip", "t.py::test_v": "fail"},
                             {"t.py::test_win": "skip", "t.py::test_v": "pass"}, verdict="PASS", freshness="fresh")
    assert report["requirements"][0]["status"] != "FAILING", report["requirements"][0]
