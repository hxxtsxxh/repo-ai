"""Missions on real suites: a test skipped identically at base and candidate does not block a verdict, but a
candidate can never make a test skip (or un-skip one), and file-level skips and xfail stay refused."""
import json
import sys
from types import SimpleNamespace

from repo_ai import sandbox
from repo_ai.mission import verification
from test_mission_verification import repo as repo_fixture


def _executor(monkeypatch, outcomes: dict[str, str], *, extra: list[dict] | None = None):
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
            path = str(self.ws.path / "test_calc.py")
            ids = [f"test_calc.py::{t}" for t in outcomes]
            events = [{"e": "module", "path": path}, {"e": "collected", "path": path, "ids": ids}]
            for tid, o in zip(ids, outcomes.values(), strict=True):
                events += [{"e": "start", "path": path, "id": tid}, {"e": "end", "path": path, "id": tid, "o": o}]
            events += [dict(e, path=path) for e in (extra or [])] + [{"e": "done"}]
            (self.ws.path / ".repo-ai/run/mission-observation.jsonl").write_text("\n".join(json.dumps(e) for e in events))
            return sandbox.Result(exit_code=int(any(o == "fail" for o in outcomes.values())), stdout="", stderr="",
                                  duration_s=0.01, timed_out=False, backend="test-sandbox")

    monkeypatch.setattr(verification.execute, "get_executor", lambda *a, **k: FakeExecutor())


def _observe(tmp_path, monkeypatch, outcomes, **kw):
    root = repo_fixture.__wrapped__(tmp_path) if not (tmp_path / "project").exists() else tmp_path / "project"
    _executor(monkeypatch, outcomes, **kw)
    return root, verification.observe(root, "python -m pytest")


def _pair(tmp_path, monkeypatch, base, cand, **kw):
    root, b = _observe(tmp_path, monkeypatch, base, **kw)
    (root / "calc.py").write_text("value = 2\n")
    _, c = _observe(tmp_path, monkeypatch, cand, **kw)
    return b, c


def test_identically_skipped_test_does_not_block_a_pass(tmp_path, monkeypatch):
    b, c = _pair(tmp_path, monkeypatch, {"test_value": "fail", "test_win": "skip"},
                 {"test_value": "pass", "test_win": "skip"})
    assert b["complete"] and c["complete"] and b["skipped"] == 1 and b["ran"] == 1
    assert verification.compare(b, c) == ("PASS", [])


def test_a_candidate_that_makes_a_test_skip_never_passes(tmp_path, monkeypatch):
    b, c = _pair(tmp_path, monkeypatch, {"test_value": "fail", "test_other": "pass"},
                 {"test_value": "skip", "test_other": "pass"})
    verdict, reasons = verification.compare(b, c)
    assert verdict == "FAIL" and "baseline and candidate skip different tests" in reasons


def test_a_candidate_that_unskips_a_test_is_not_comparable(tmp_path, monkeypatch):
    b, c = _pair(tmp_path, monkeypatch, {"test_value": "fail", "test_win": "skip"},
                 {"test_value": "pass", "test_win": "pass"})
    assert "baseline and candidate skip different tests" in verification.compare(b, c)[1]


def test_all_skipped_is_not_an_observation(tmp_path, monkeypatch):
    _, obs = _observe(tmp_path, monkeypatch, {"test_value": "skip"})
    assert any("real pass/fail test outcomes" in p for p in verification._problems(obs, "x"))


def test_xfail_and_file_level_skips_stay_refused(tmp_path, monkeypatch):
    _, obs = _observe(tmp_path, monkeypatch, {"test_value": "fail"},
                      extra=[{"e": "end", "id": "test_calc.py", "o": "skip", "file": True}])
    assert not obs["complete"]
    _, obs = _observe(tmp_path, monkeypatch, {"test_value": "fail"},
                      extra=[{"e": "end", "id": "test_calc.py::test_x", "o": "pass", "xfail": True}])
    assert not obs["complete"]


def test_a_skipped_test_never_counts_as_a_pass_for_the_baseline_failure(tmp_path, monkeypatch):
    b, c = _pair(tmp_path, monkeypatch, {"test_value": "pass", "test_win": "skip"},
                 {"test_value": "pass", "test_win": "skip"})
    assert "baseline did not demonstrate a real failing test" in verification.compare(b, c)[1]
