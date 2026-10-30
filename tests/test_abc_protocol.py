"""abc-v1 task set + grader integrity (free replay path; no live provider)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "abc-v1"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


grade_mod = _load("grade")
mf_mod = _load("make_manifest")
TASKS = sorted(p.name for p in (ROOT / "tasks").iterdir() if p.is_dir())


def test_manifest_matches_files():
    want = json.loads((ROOT / "manifest.json").read_text())["sha256"]
    assert want == mf_mod.digests()


def test_task_mix():
    langs = {}
    for t in TASKS:
        j = grade_mod.load_task(t)
        langs.setdefault(j["language"], set()).add(j["cluster"])
    assert len(langs["python"]) >= 2 and len(langs["node"]) >= 2


@pytest.mark.parametrize("task", TASKS)
def test_control_outcomes(task):
    g = grade_mod
    assert g.grade(task, {})["outcome"] == "FAIL"
    assert g.grade(task, g.read_variant(task, "reference"))["outcome"] == "CORRECT"
    assert g.grade(task, g.read_variant(task, "decoy"))["outcome"] == "FALSE_GREEN"


@pytest.mark.parametrize("task", TASKS)
def test_candidate_cannot_win_by_editing_tests(task):
    """Files outside write_paths (e.g. a rewritten visible test) are ignored, not trusted."""
    t = grade_mod.load_task(task)
    cand = grade_mod.read_variant(task, "decoy")
    vis = next(p for p in sorted((ROOT / "tasks" / task / "repo").rglob("*"))
               if p.is_file() and "__pycache__" not in p.parts and "test" in p.name)
    cand[str(vis.relative_to(ROOT / "tasks" / task / "repo"))] = "assert True\n"
    res = grade_mod.grade(task, cand)
    assert res["outcome"] == "FALSE_GREEN"
    assert res["ignored_paths"], t


@pytest.mark.parametrize("task", TASKS)
def test_hidden_tests_not_visible_to_agent(task):
    d = ROOT / "tasks" / task
    hidden_names = {p.name for p in (d / "hidden").rglob("*") if p.is_file()}
    repo_names = {p.name for p in (d / "repo").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert not hidden_names & repo_names
    prompt = grade_mod.load_task(task)["prompt"].lower()
    assert "hidden" not in prompt
    for p in (d / "repo").rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            assert "hidden" not in p.read_text().lower() or p.suffix == ".json"


def test_empty_or_missing_tests_are_inconclusive(tmp_path):
    # a candidate that makes the module unimportable must not read as CORRECT
    res = grade_mod.grade("py-ledger", {"ledger.py": "raise SystemExit(0)\n"})
    assert res["outcome"] != "CORRECT"


def test_stray_bytecode_cannot_change_a_grade():
    """A stale .pyc left in a task dir (e.g. by compileall) must not leak into or alter grading."""
    junks = []
    for sub in ("repo", "hidden"):
        d = ROOT / "tasks" / "py-ledger" / sub / "__pycache__"
        d.mkdir(exist_ok=True)
        junk = d / "x.cpython-312.pyc"
        junk.write_bytes(b"\xcb\x00junk")
        junks.append(junk)
    try:
        assert grade_mod.grade("py-ledger", grade_mod.read_variant("py-ledger", "reference"))["outcome"] == "CORRECT"
        assert grade_mod.grade("py-ledger", {})["outcome"] == "FAIL"
    finally:
        for junk in junks:
            junk.unlink()
            if not any(junk.parent.iterdir()):
                junk.parent.rmdir()
