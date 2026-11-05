"""abc-v3 task set + grader integrity (free replay path; no live provider)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "abc-v3"


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
    res = grade_mod.grade("py-intervals", {"intervals.py": "raise SystemExit(0)\n"})
    assert res["outcome"] != "CORRECT"


def test_stray_bytecode_cannot_change_a_grade():
    """A stale .pyc left in a task dir (e.g. by compileall) must not leak into or alter grading."""
    junks = []
    for sub in ("repo", "hidden"):
        d = ROOT / "tasks" / "py-intervals" / sub / "__pycache__"
        d.mkdir(exist_ok=True)
        junk = d / "x.cpython-312.pyc"
        junk.write_bytes(b"\xcb\x00junk")
        junks.append(junk)
    try:
        assert grade_mod.grade("py-intervals", grade_mod.read_variant("py-intervals", "reference"))["outcome"] == "CORRECT"
        assert grade_mod.grade("py-intervals", {})["outcome"] == "FAIL"
    finally:
        for junk in junks:
            junk.unlink()
            if not any(junk.parent.iterdir()):
                junk.parent.rmdir()


def test_splits_are_declared_and_separate():
    mf = json.loads((ROOT / "manifest.json").read_text())
    cal, hold = set(mf["splits"]["calibration"]), set(mf["splits"]["holdout"])
    assert cal and hold and not cal & hold and cal | hold == set(TASKS)
    for t in TASKS:
        assert grade_mod.load_task(t)["split"] in {"calibration", "holdout"}
    assert len({grade_mod.load_task(t)["language"] for t in hold}) == 2  # holdout covers Python and Node


def test_arms_and_status_are_preregistered():
    mf = json.loads((ROOT / "manifest.json").read_text())
    assert set(mf["arms"]) == {"A", "B", "C"} and mf["status"].startswith("PREREGISTERED")
    assert all(sorted(v) == ["A", "B", "C"] for v in mf["run_order_counterbalanced_seeded"].values())
    assert "NOT_YET_DEMONSTRATED" in mf["analysis"]


def test_disjoint_from_earlier_studies():
    old_ids, old_clusters, old_sources = set(), set(), set()
    for study in ("abc-v1", "abc-v2"):
        base = ROOT.parent / study
        for tj in base.rglob("task.json"):
            j = json.loads(tj.read_text())
            old_ids.add(j["id"])
            old_clusters.add(j.get("cluster"))
        for ref in base.rglob("reference/*"):
            if ref.is_file():
                old_sources.add(ref.read_bytes())
    mine = {t: grade_mod.load_task(t) for t in TASKS}
    assert not {j["id"] for j in mine.values()} & old_ids
    assert not {j["cluster"] for j in mine.values()} & old_clusters
    for t in TASKS:
        for ref in (ROOT / "tasks" / t / "reference").iterdir():
            assert ref.read_bytes() not in old_sources


@pytest.mark.parametrize("task", TASKS)
def test_prompt_never_quotes_hidden_test_files(task):
    """Leakage guard: prompts must not quote hidden test names or file names."""
    d = ROOT / "tasks" / task
    prompt = grade_mod.load_task(task)["prompt"]
    for h in (d / "hidden").rglob("*"):
        if h.is_file() and "__pycache__" not in h.parts:
            assert h.name not in prompt and h.stem not in prompt


def test_arm_c_runner_is_wired_to_the_live_tournament():
    src = (ROOT / "run_live.py").read_text()
    assert "--tournament" in src and "codex,agy" in src and "ABSTAIN" in src
