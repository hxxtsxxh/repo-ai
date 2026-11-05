"""A real (sandboxed, replayed) mission names a requirement erasure; skipped without a host sandbox."""
from test_mission_requirement_erasure import GOOGLE_BASE
def test_a_real_mission_names_an_erasure_the_diff_alone_could_not_place(tmp_path):
    from repo_ai.mission.runtime import execute, plan
    from test_mission_runtime import git, replay
    root = tmp_path / "proj"
    root.mkdir()
    (root / "m.py").write_text(GOOGLE_BASE.replace("return max(lo, min(x, hi))", "return x"))
    (root / "test_m.py").write_text("from m import clamp\n\ndef test_clamp():\n    assert clamp(5, 0, 3) == 3\n")
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "-qm", "base")
    after = GOOGLE_BASE.replace("    Raises:\n        ValueError: If lo > hi, the call must fail.\n", "") \
                       .replace('    if lo > hi:\n        raise ValueError("lo > hi")\n', "")
    p = plan(root, "Make clamp clamp", agent="replay", write_paths=["m.py"], execute_local=True)
    result = execute(root, p, replay(root, tmp_path, after=after, path="m.py"))
    assert result["effective_verdict"] == "PASS"
    erased = result["claims"]["removed_requirement_text"]
    assert [e["text"] for e in erased] == ["ValueError: If lo > hi, the call must fail."]
    assert result["claims"]["headline"] == "ASSURANCE_PARTIAL"
