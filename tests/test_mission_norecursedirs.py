"""journey-live-v1 (C21) marshmallow control: `norecursedirs = "... tests/mypy_test_cases"` keeps two name-matched
files out of pytest's full run, so every mission observation on marshmallow was "not every discovered test file was
collected" and INCONCLUSIVE, even the upstream fix. The project's own norecursedirs now explains such a file."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from conftest import _git
from repo_ai import sandbox
from repo_ai.mission import verification


def _repo(tmp_path, config: str):
    root = tmp_path / "project"
    (root / "tests" / "typecheck").mkdir(parents=True)
    (root / "calc.py").write_text("value = 2\n")
    (root / "tests" / "test_calc.py").write_text("from calc import value\ndef test_value():\n    assert value == 2\n")
    (root / "tests" / "typecheck" / "test_types.py").write_text("import calc\ncalc.value.nonexistent\n")
    (root / "pyproject.toml").write_text(config)
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _executor(monkeypatch, collect_typecheck: bool = False):
    class FakeExecutor:
        backend = SimpleNamespace(name="test-sandbox")
        python = sys.executable
        node = ""
        site_dirs: list = []
        links: dict = {}
        is_container = False

        def in_workspace(self, ws):
            self.ws = ws
            self.inside_root = str(ws.path)
            return self

        def run(self, argv, **kwargs):
            events = []
            names = ["tests/test_calc.py"] + (["tests/typecheck/test_types.py"] if collect_typecheck else [])
            for name in names:
                path, tid = str(self.ws.path / name), f"{name}::test_value"
                events += [{"e": "module", "path": path}, {"e": "collected", "path": path, "ids": [tid]},
                           {"e": "start", "path": path, "id": tid}, {"e": "end", "path": path, "id": tid, "o": "pass"}]
            events.append({"e": "done"})
            (self.ws.path / ".repo-ai/run/mission-observation.jsonl").write_text("\n".join(json.dumps(e) for e in events))
            return sandbox.Result(exit_code=0, stdout="", stderr="", duration_s=0.01, timed_out=False,
                                  backend="test-sandbox")

    monkeypatch.setattr(verification.execute, "get_executor", lambda *a, **k: FakeExecutor())
    monkeypatch.setattr(verification.sandbox, "cleanup_problems", lambda: [])


def test_a_file_the_projects_norecursedirs_keeps_out_does_not_make_the_observation_incomplete(tmp_path, monkeypatch):
    repo = _repo(tmp_path, '[tool.pytest.ini_options]\nnorecursedirs = ".git tests/typecheck"\n')
    _executor(monkeypatch)
    obs = verification.observe(repo, "python -m pytest")
    assert obs["complete"] and not obs["reasons"], obs["reasons"]
    assert obs["config_excluded"] == ["tests/typecheck/test_types.py"]


def test_without_that_configuration_the_same_gap_is_still_incomplete(tmp_path, monkeypatch):
    repo = _repo(tmp_path, '[tool.pytest.ini_options]\naddopts = "-q"\n')
    _executor(monkeypatch)
    obs = verification.observe(repo, "python -m pytest")
    assert not obs["complete"] and "not every discovered test file was collected" in obs["reasons"]
    assert obs["config_excluded"] == []


def test_a_listed_file_pytest_did_collect_is_not_reported_as_left_out(tmp_path, monkeypatch):
    repo = _repo(tmp_path, '[tool.pytest.ini_options]\nnorecursedirs = ".git tests/typecheck"\n')
    _executor(monkeypatch, collect_typecheck=True)
    obs = verification.observe(repo, "python -m pytest")
    assert obs["complete"] and obs["config_excluded"] == [], obs


def test_baseline_and_candidate_leaving_out_different_files_are_not_comparable(tmp_path, monkeypatch):
    repo = _repo(tmp_path, '[tool.pytest.ini_options]\nnorecursedirs = ".git tests/typecheck"\n')
    _executor(monkeypatch)
    base = verification.observe(repo, "python -m pytest")
    cand = dict(base, config_excluded=[])
    assert "baseline and candidate leave out different test files" in verification.comparability(base, cand)
    assert not any("leave out" in r for r in verification.comparability(base, dict(base)))


def test_different_test_ids_are_named(tmp_path, monkeypatch):
    """marshmallow parametrizes a test with the current time, so its IDs differ between any two runs."""
    repo = _repo(tmp_path, '[tool.pytest.ini_options]\nnorecursedirs = ".git tests/typecheck"\n')
    _executor(monkeypatch)
    base = verification.observe(repo, "python -m pytest")
    a, b = "tests/test_calc.py::test_value[02:32:43]", "tests/test_calc.py::test_value[02:32:45]"
    reasons = verification.comparability(dict(base, test_ids=[a], outcomes={a: "pass"}),
                                         dict(base, test_ids=[b], outcomes={b: "pass"}))
    text = next(r for r in reasons if r.startswith("baseline and candidate have different test_ids"))
    assert a in text and b in text and "changes between runs" in text, text
