"""A mission needs a real failing baseline and the same complete passing suite."""
from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import pytest

from conftest import _git
from repo_ai import sandbox
from repo_ai.mission import verification


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "calc.py").write_text("value = 1\n")
    (root / "test_calc.py").write_text("from calc import value\ndef test_value():\n    assert value == 2\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _fake_executor(monkeypatch, mode="fail"):
    class FakeExecutor:
        backend = SimpleNamespace(name="test-sandbox")
        python = sys.executable
        node = ""
        site_dirs = []
        links = {}
        is_container = False

        def in_workspace(self, ws):
            self.ws = ws
            self.inside_root = str(ws.path)
            return self

        def run(self, argv, **kwargs):
            assert self.ws.path != self.ws.source
            path = str(self.ws.path / "test_calc.py")
            tid = "test_calc.py::test_value"
            outcome = "fail" if mode in {"fail", "exit-mismatch"} else "skip" if mode == "skip" else "pass"
            events = [{"e": "module", "path": path},
                      {"e": "collected", "path": path, "ids": [tid, "test_calc.py::missing"]
                       if mode == "partial" else [tid]},
                      {"e": "start", "path": path, "id": tid},
                      {"e": "end", "path": path, "id": tid, "o": outcome}, {"e": "done"}]
            if mode == "empty":
                events = [{"e": "module", "path": path}, {"e": "done"}]
            if mode == "unknown-pass":
                events.insert(-1, {"e": "end", "path": str(self.ws.path / "elsewhere.py"),
                                   "id": "hidden", "o": "pass"})
            if mode == "duplicate":
                events.insert(-1, events[-2])
            report = self.ws.path / ".repo-ai/run/mission-observation.jsonl"
            if mode != "missing":
                report.write_text("bad json\n" if mode == "malformed" else
                                  "\n".join(json.dumps(e) for e in events))
            if mode == "source-edit":
                (self.ws.source / "calc.py").write_text("value = 99\n")
            return sandbox.Result(exit_code=int(mode == "fail"), stdout="private captured output", stderr="",
                                  duration_s=0.01, timed_out=mode == "timeout", backend="test-sandbox")

    monkeypatch.setattr(verification.execute, "get_executor", lambda *a, **k: FakeExecutor())
    monkeypatch.setattr(verification.sandbox, "cleanup_problems", lambda: [])


def test_same_tests_failing_then_passing_compare(repo, monkeypatch):
    _fake_executor(monkeypatch)
    baseline = verification.observe(repo, "python -m pytest")
    (repo / "calc.py").write_text("value = 2\n")
    _fake_executor(monkeypatch, "pass")
    candidate = verification.observe(repo, "python -m pytest")
    assert baseline["trusted"] and baseline["complete"], baseline
    assert baseline["failed"] == 1 and baseline["ran"] == 1
    assert candidate["failed"] == 0 and candidate["ran"] == 1
    assert baseline["pin"]["fingerprint"] != candidate["pin"]["fingerprint"]
    assert baseline["integrity"]["unchanged"] and candidate["integrity"]["unchanged"]
    assert "private captured output" not in json.dumps(candidate)
    assert verification.compare(baseline, candidate) == ("PASS", [])


@pytest.mark.parametrize("mode", ["missing", "empty", "skip", "partial", "malformed", "exit-mismatch",
                                 "unknown-pass", "duplicate", "timeout", "source-edit"])
def test_incomplete_or_untrusted_reports_never_qualify(repo, monkeypatch, mode):
    _fake_executor(monkeypatch, "fail")
    baseline = verification.observe(repo, "python -m pytest")
    _fake_executor(monkeypatch, mode)
    candidate = verification.observe(repo, "python -m pytest")
    assert not candidate["complete"], candidate
    verdict, reasons = verification.compare(baseline, candidate)
    assert verdict == "FAIL" and reasons


@pytest.mark.parametrize("command", ["true", "python -m unittest", "python -m pytest -k value",
                                    "python -m pytest test_calc.py", "node --test --test-only"])
def test_unsupported_or_partial_commands_never_execute(repo, monkeypatch, command):
    monkeypatch.setattr(verification.execute, "get_executor", lambda *a, **k: pytest.fail("executed"))
    result = verification.observe(repo, command)
    assert not result["trusted"] and not result["complete"] and result["reasons"]


@pytest.mark.parametrize("change", ["environment_static", "environment_key", "repo_ai_version", "executor",
                                   "test_ids", "test_inputs", "missing-count", "false-count", "baseline-pass"])
def test_compare_rejects_changed_or_malformed_evidence(repo, monkeypatch, change):
    _fake_executor(monkeypatch, "fail")
    baseline = verification.observe(repo, "python -m pytest")
    _fake_executor(monkeypatch, "pass")
    candidate = verification.observe(repo, "python -m pytest")
    if change == "test_inputs":
        candidate["pin"]["test_inputs"] = {"test_calc.py": "different"}
    elif change == "missing-count":
        candidate.pop("ran")
    elif change == "false-count":
        candidate["ran"] = True
    elif change == "baseline-pass":
        baseline = copy.deepcopy(candidate)
    else:
        candidate[change] = "different"
    assert verification.compare(baseline, candidate)[0] == "FAIL"


def test_changed_test_bytes_do_not_count_as_a_fix(repo, monkeypatch):
    _fake_executor(monkeypatch, "fail")
    baseline = verification.observe(repo, "python -m pytest")
    (repo / "test_calc.py").write_text("def test_value():\n    assert True\n")
    _fake_executor(monkeypatch, "pass")
    candidate = verification.observe(repo, "python -m pytest")
    assert verification.compare(baseline, candidate)[0] == "FAIL"


def test_real_pytest_baseline_and_candidate_are_isolated(repo, monkeypatch):
    preference = "seatbelt" if sys.platform == "darwin" else "bwrap"
    if sys.platform == "win32" or not sandbox.get_backend(preference).available()[0]:
        pytest.skip("host sandbox unavailable")
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    baseline = verification.observe(repo, "python -m pytest -q", sandbox_preference=preference)
    (repo / "calc.py").write_text("value = 2\n")
    candidate = verification.observe(repo, "python -m pytest -q", sandbox_preference=preference)
    assert verification.compare(baseline, candidate) == ("PASS", []), (baseline, candidate)
    assert not (repo / ".pytest_cache").exists()
    assert not (repo / ".repo-ai/run").exists()


def test_unremoved_workspace_is_not_confirmed_clean(repo,monkeypatch):
    from repo_ai.verify.isolate import Workspace
    removed=[]
    original=Workspace.cleanup
    monkeypatch.setattr(Workspace,'cleanup',lambda self:removed.append(self))
    _fake_executor(monkeypatch,'pass')
    try:
        result=verification.observe(repo,'python -m pytest')
        assert not result['cleanup_confirmed']
        assert not result['complete']
    finally:
        for workspace in removed:
            original(workspace)
