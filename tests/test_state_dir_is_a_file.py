"""A repository that tracks a FILE named `.repo-ai`: a clear refusal, never ENOTDIR mid-run."""
from __future__ import annotations

import subprocess

import pytest
from conftest import commit_all, make_repo, run_cli

from repo_ai.config import Config
from repo_ai.paths import LayoutError, make_dir, resolve_layout
from repo_ai.verify import isolate
from repo_ai.verify.execute import RUN_HOME
from repo_ai.verify.results import RUN_DIR


def test_creating_state_refuses_a_file_where_its_directory_goes(tmp_path):
    (tmp_path / ".repo-ai").write_text("project data\n")
    layout = resolve_layout(tmp_path, Config())  # reading the layout still works (mission identity, planning)
    with pytest.raises(LayoutError, match=r"\.repo-ai is a file in this repository.*out_dir"):
        make_dir(tmp_path, layout.state_dir)
    assert (tmp_path / ".repo-ai").read_text() == "project data\n"


def test_init_names_the_file(tmp_path):
    repo = make_repo(tmp_path, "pyweb")
    (repo / ".repo-ai").write_text("project data\n")
    commit_all(repo, "a tracked .repo-ai file")
    out = run_cli(repo, "init", "--agent", "none")
    assert out.returncode != 0 and ".repo-ai is a file in this repository" in out.stderr
    assert "Errno" not in out.stderr


def test_make_dir_outside_the_repository_is_an_ordinary_error(tmp_path):
    (tmp_path / "elsewhere").write_text("x")
    with pytest.raises(FileExistsError):
        make_dir(tmp_path / "repo", tmp_path / "elsewhere")


@pytest.mark.parametrize("rel", [RUN_DIR, RUN_HOME])
def test_run_dir_names_the_tracked_file(tmp_path, rel):
    (tmp_path / ".repo-ai").write_text("project data\n")
    with pytest.raises(isolate.IsolationError, match="tracks a file named .repo-ai"):
        isolate.run_dir(tmp_path, rel)
    assert (tmp_path / ".repo-ai").read_text() == "project data\n"


def test_run_dir_is_created_normally(tmp_path):
    assert isolate.run_dir(tmp_path, RUN_HOME).is_dir()
    assert isolate.run_dir(tmp_path, RUN_HOME).is_dir()  # idempotent


def test_other_failures_are_not_blamed_on_the_state_name(tmp_path):
    (tmp_path / ".repo-ai").mkdir()
    (tmp_path / ".repo-ai" / "run").write_text("x")
    with pytest.raises(FileExistsError):
        isolate.run_dir(tmp_path, RUN_DIR)


def test_custom_layout_init_ignores_its_runtime_state_without_an_agent(tmp_path):
    """The refusal above points to `out_dir`: `init --agent none` there must keep the index, lock and evidence out
    of git's view, or they count as part of the change and the first `verify --run` fails as a moved tree."""
    repo = make_repo(tmp_path, "pyweb")
    (repo / ".repo-ai").write_text("project data\n")
    (repo / "repo-ai.toml").write_text('out_dir = ".ctx"\n')
    commit_all(repo, "a tracked .repo-ai file and a custom layout")
    out = run_cli(repo, "init", "--agent", "none")
    assert out.returncode == 0, out.stderr
    ignore = (repo / ".gitignore").read_text()
    for entry in (".ctx/index.db", ".ctx/update.lock", ".ctx/evidence/", ".ctx/verify-*.json"):
        assert entry in ignore
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo, capture_output=True,
                               text=True, check=True).stdout.split()
    assert not [p for p in untracked if p.startswith(".ctx/index.db") or p == ".ctx/update.lock"]
