"""Security audit F1: a repository's own config (`state_dir`, `out_dir`) may
name where repo-ai keeps its state. The integrity check left those
directories out, so a committed `state_dir = "src"` excluded the source tree
from the check that the developer's tree is unchanged by a run. A directory
named by configuration is now left out only when git tracks nothing in it:
every tracked file is always hashed before and after."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repo_ai.config import load_config
from repo_ai.paths import resolve_layout
from repo_ai.verify import engine, isolate

GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def _repo(tmp_path: Path, config: str) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("x = 1\n")
    (root / "repo-ai.toml").write_text(config)
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-qm", "c"]):
        subprocess.run([*GIT, *cmd], cwd=root, check=True)
    return root


def _changed(root: Path) -> list[str]:
    skip = engine._own_state(root, resolve_layout(root, load_config(root)))
    listing = isolate.worktree_files(root)
    before = isolate.snapshot(root, listing[0], skip=skip)
    (root / "src" / "app.py").write_text("x = 2  # changed during the run\n")
    after = isolate.snapshot(root, list(before.content), skip=before.skip)
    return before.changes(after)


def test_a_committed_state_dir_over_tracked_source_never_hides_a_change(tmp_path: Path):
    root = _repo(tmp_path, 'state_dir = "src"\n')
    assert "src/" not in engine._own_state(root, resolve_layout(root, load_config(root)))
    assert _changed(root), "a change to a tracked file under a configured state_dir was not detected"


def test_an_ignored_state_dir_leaves_out_only_what_repo_ai_writes_there(tmp_path: Path):
    root = _repo(tmp_path, 'state_dir = "build/repo-ai-state"\n')
    (root / ".gitignore").write_text("build/\n")
    skip = engine._own_state(root, resolve_layout(root, load_config(root)))
    assert "build/repo-ai-state/" not in skip, skip
    from repo_ai.verify.isolate import _skipped, _walked_only
    for rel in ("build/repo-ai-state/evidence/abc.json", "build/repo-ai-state/verify-timings.json",
                "build/repo-ai-state/index.db-wal", "build/repo-ai-state/prove/blobs/" + "a" * 64):
        assert _skipped(rel, skip), rel
    assert _walked_only("build/repo-ai-state/evidence", skip) and _walked_only("build/repo-ai-state", skip)
    # what an interpreter would load or run is never left out (the defensive review of the corrective integration)
    for rel in ("build/repo-ai-state/verify-x.pth", "build/repo-ai-state/index.db.pth",
                "build/repo-ai-state/evidence/__init__.py", "build/repo-ai-state/prove/__init__.py",
                "build/repo-ai-state/evidence/x.json.py", "build/repo-ai-state/sitecustomize.py",
                # a package's manifest (its entry point) when the state directory is node_modules (the re-check)
                "build/repo-ai-state/prove/package.json", "build/repo-ai-state/evidence/sub/package.json"):
        assert not _skipped(rel, skip), rel


def test_a_state_dir_git_does_not_ignore_is_checked_whole(tmp_path: Path):
    root = _repo(tmp_path, 'state_dir = "build/repo-ai-state"\n')
    skip = engine._own_state(root, resolve_layout(root, load_config(root)))
    assert not any(s.startswith("build/") for s in skip), skip


# Session A's rework of #53 (dcf1e24), reconciled: a state directory shared with committed docs leaves out only
# repo-ai's own runtime files, never a tracked or visible file; a directory under .repo-ai/ is repo-ai's own
def test_a_shared_out_dir_with_committed_docs_leaves_out_only_runtime_files(tmp_path: Path):
    root = _repo(tmp_path, 'out_dir = "docs/ai"\n')
    (root / "docs" / "ai").mkdir(parents=True)
    (root / "docs" / "ai" / "OVERVIEW.md").write_text("generated\n")
    (root / "docs" / "ai" / "notes.json").write_text("{}\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "docs"]):
        subprocess.run([*GIT, *cmd], cwd=root, check=True)
    layout = resolve_layout(root, load_config(root))
    if layout.state_rel != layout.context_rel:
        pytest.skip("this layout keeps state apart from out_dir")
    skip = engine._own_state(root, layout)
    listing = isolate.worktree_files(root)
    before = isolate.snapshot(root, listing[0], skip=skip)
    (root / "docs" / "ai" / "verify-timings.json").write_text("{}\n")  # repo-ai's own writes during the run
    (root / "docs" / "ai" / "evidence").mkdir()
    (root / "docs" / "ai" / "evidence" / "r.json").write_text("{}\n")
    after = isolate.snapshot(root, list(before.content), skip=before.skip)
    assert before.changes(after) == []
    (root / "docs" / "ai" / "notes.json").write_text('{"changed": 1}\n')  # a tracked file, even with a data name
    (root / "docs" / "ai" / "evil.py").write_text("x = 1\n")
    after = isolate.snapshot(root, list(before.content), skip=before.skip)
    changed = " ".join(before.changes(after))
    assert "docs/ai/notes.json" in changed and "docs/ai/evil.py" in changed, changed


def test_a_directory_under_repo_ai_is_left_out_but_not_repo_ai_itself(tmp_path: Path):
    root = _repo(tmp_path, 'state_dir = ".repo-ai/custom"\n')
    skip = engine._own_state(root, resolve_layout(root, load_config(root)))
    assert ".repo-ai/custom/" in skip and ".repo-ai/" not in skip


def _planted(root: Path, rel: str, text: str = "#!/bin/sh\necho planted\n") -> list[str]:
    skip = engine._own_state(root, resolve_layout(root, load_config(root)))
    listing = isolate.worktree_files(root)
    before = isolate.snapshot(root, listing[0], skip=skip)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as fh:
        fh.write(text)
    after = isolate.snapshot(root, list(before.content), skip=before.skip)
    return before.changes(after)


# the independent security review of #53 (2026-10-25): directories git never lists, or that repo-ai's own
# directory names covered, were left out whole by a committed config
@pytest.mark.parametrize("state_dir,planted", [
    (".git", ".git/hooks/pre-commit"), (".git", ".git/config"), (".git/hooks", ".git/hooks/pre-commit"),
    (".GIT/hooks", ".git/hooks/post-checkout"), (".bob/hooks", ".bob/hooks/h.sh"),
    (".venv", ".venv/bin/activate"), ("node_modules", "node_modules/a/index.js"),
    ("src/plugins", "src/plugins/evil.py"), (".vscode", ".vscode/tasks.json"),
])
def test_a_configured_state_dir_never_hides_what_a_run_could_plant(tmp_path: Path, state_dir: str, planted: str):
    root = _repo(tmp_path, f'state_dir = "{state_dir}"\n')
    (root / ".gitignore").write_text(".venv/\nnode_modules/\n")
    (root / ".bob" / "hooks").mkdir(parents=True)
    (root / ".bob" / "hooks" / "h.sh").write_text("#!/bin/sh\n")
    for rel in (".venv/bin/activate", "node_modules/a/index.js"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n")
    for cmd in (["add", "-A"], ["commit", "-qm", "more"]):
        subprocess.run([*GIT, *cmd], cwd=root, check=True)
    if state_dir.startswith(".GIT") and not (root / ".GIT").exists():
        pytest.skip("the filesystem is case-sensitive")
    try:
        layout = resolve_layout(root, load_config(root))
    except ValueError:
        return  # refusing the layout is fine too
    assert not any(s.rstrip("/").casefold() == state_dir.casefold() for s in engine._own_state(root, layout))
    assert _planted(root, planted), f"planting {planted} under state_dir {state_dir!r} was not detected"


def test_a_state_dir_spelled_in_another_case_never_hides_tracked_source(tmp_path: Path):
    probe = tmp_path / "CaseProbe"
    probe.write_text("")
    if not (tmp_path / "caseprobe").exists():
        pytest.skip("the filesystem is case-sensitive: `SRC` is not `src` here")
    root = _repo(tmp_path, 'state_dir = "SRC"\n')
    skip = engine._own_state(root, resolve_layout(root, load_config(root)))
    assert not any(s.lower() == "src/" for s in skip), skip


def test_a_state_dir_holding_untracked_files_of_the_change_is_checked(tmp_path: Path):
    root = _repo(tmp_path, 'state_dir = "newpkg"\n')
    (root / "newpkg").mkdir()
    (root / "newpkg" / "mod.py").write_text("y = 1\n")  # untracked, not ignored: part of the change
    assert "newpkg/" not in engine._own_state(root, resolve_layout(root, load_config(root)))
