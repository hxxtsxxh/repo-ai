"""Mission git commands never start git's background maintenance or gc.

A commit through `mission.runtime.git` let git spawn `git maintenance run --auto` in the background, which wrote
`.git/objects/maintenance.lock` while a fixture repository was being copied (a macOS CI failure in
test_eval_integrity). repo-ai's own git calls must not leave background work in a repository or workspace."""
from __future__ import annotations

import subprocess
from pathlib import Path

from repo_ai.mission import runtime


def test_mission_git_disables_auto_maintenance_and_gc(tmp_path: Path, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(argv, *a, **k):
        seen.append(list(argv))
        return real(argv, *a, **k)
    monkeypatch.setattr(runtime.subprocess, "run", spy)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    runtime.git(tmp_path, "status", "--porcelain")
    argv = seen[-1]
    assert ["-c", "maintenance.auto=false"] == argv[argv.index("maintenance.auto=false") - 1:argv.index("maintenance.auto=false") + 1]
    assert "gc.auto=0" in argv and argv.index("gc.auto=0") < argv.index("status")
