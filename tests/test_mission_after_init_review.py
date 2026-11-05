"""Scratch adversarial tests for PR #11 (fix/init-then-do). Not for merge."""


import pytest

from repo_ai.mission.runtime import identity, plan
from repo_ai.verify import isolate
from test_mission_runtime import git

C = ["-c", "user.name=f", "-c", "user.email=f@example.invalid"]


def _repo(tmp_path, extra=None):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lib").mkdir()
    (root / "lib" / "rate.py").write_text("RATE = 1\n")
    (root / "charge.py").write_text(
        "from lib.rate import RATE\n\ndef charge(amount, retries):\n    return amount * (retries + 1) * RATE\n"
    )
    (root / "test_charge.py").write_text(
        "from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n"
    )
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    for rel, text in (extra or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, *C, "commit", "-qm", "base")
    return root


# --- CONFIRMED 1: the state_dir filter now hides MODIFIED tracked source (was: only untracked `??`) ---
@pytest.mark.parametrize("cfg", ["repo-ai.toml", ".repo-ai/config.toml"])
def test_state_dir_inside_source_does_not_hide_a_real_uncommitted_edit(tmp_path, cfg):
    # a committed repository config (or the user's/env config) chooses state_dir; `lib` holds tracked source
    root = _repo(tmp_path, {cfg: 'state_dir = "lib"\n'})
    (root / "lib" / "rate.py").write_text("RATE = 0  # real uncommitted user edit\n")
    ident = identity(root)
    assert ident["dirty"], "tracked source edit under state_dir slipped past the dirty check"
    with pytest.raises(ValueError, match="dirty checkout"):
        identity(root, require_clean=True)


def test_state_dir_staged_deletion_of_tracked_source_is_dirty(tmp_path):
    root = _repo(tmp_path, {"repo-ai.toml": 'state_dir = "lib"\n'})
    git(root, "rm", "-q", "lib/rate.py")
    with pytest.raises(ValueError):
        identity(root, require_clean=True)


# --- CONFIRMED 2: materialize now drops a tracked FILE literally named `.bob` / `.repo-ai` ---------------
@pytest.mark.parametrize("name", [".bob", ".repo-ai"])
def test_tracked_file_named_like_a_state_dir_is_still_materialized(tmp_path, name):
    root = _repo(tmp_path, {name: "project data a test reads\n"})
    assert name in identity(root, require_clean=True)["files"]  # identity: still source
    keep, _ = isolate.worktree_files(root)
    assert name in keep  # working-tree workspace: copied
    head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
    with isolate.materialize_commit(root, head, dependencies=False) as ws:
        assert name in ws.files and (ws.path / name).is_file(), "base/candidate workspace lost a tracked file"


# --- SOUND checks (should pass) -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rel", [".repo-ai-notes.py", ".repo-aix/x.py", "a b/.repo-ai/ü x.py", "src/.repo-ai/x.py"]
)
def test_lookalike_paths_still_dirty(tmp_path, rel):
    root = _repo(tmp_path, {rel: "X = 1\n"})
    (root / rel).write_text("X = 2\n")
    assert identity(root)["dirty"]


def test_rename_into_repo_ai_still_dirty(tmp_path):
    root = _repo(tmp_path)
    (root / ".repo-ai").mkdir()
    git(root, "mv", "lib/rate.py", ".repo-ai/rate.py")
    assert identity(root)["dirty"]


def test_mission_does_not_certify_head_while_user_tree_differs_under_state_dir(tmp_path):
    root = _repo(tmp_path, {"repo-ai.toml": 'state_dir = "lib"\n'})
    (root / "lib" / "rate.py").write_text("RATE = 0\n")
    p = plan(root, "Fix duplicate charge", agent="replay", write_paths=["charge.py"], execute_local=True)
    assert p["decision"] == "BLOCKED", "planned a mission over an unseen uncommitted source edit"
