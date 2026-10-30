"""A `repo-ai update` killed at any point between its separately committed
index writes must not leave a file marked up to date without its symbols,
imports or search entries (the cause of the intermittent
`test_killed_update_leaves_a_recoverable_index` failure).

Deterministic: the update process exits hard (os._exit, like SIGKILL) right
after one chosen write commits; then an ordinary `update` must recover.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from conftest import cli_env, run_cli

STEPS = ["set_meta", "delete_paths", "upsert_files", "insert_symbols", "replace_imports", "replace_test_links",
         "set_scores", "index_document", "replace_refs_for"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    (root / "pkg").mkdir(parents=True)
    for i in range(6):
        (root / "pkg" / f"m{i}.py").write_text(f"from pkg.m{(i + 1) % 6} import f{(i + 1) % 6}\n\n\n"
                                               f"def f{i}():\n    return {i}\n")
    (root / "pkg" / "__init__.py").write_text("")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _crash_after(repo: Path, step: str, nth: int = 1) -> int:
    """Run `repo-ai update`, exiting hard right after the `nth` commit of `step`."""
    code = textwrap.dedent(f"""
        import os, sys
        from repo_ai import index as ix
        real = getattr(ix.Index, {step!r})
        seen = [0]
        def wrapped(self, *a, **k):
            out = real(self, *a, **k)
            seen[0] += 1
            if seen[0] == {nth}:
                os._exit(9)
            return out
        setattr(ix.Index, {step!r}, wrapped)
        from repo_ai.cli import main
        sys.exit(main(["update", "-q", "-C", sys.argv[1]]))
    """)
    return subprocess.run([sys.executable, "-c", code, str(repo)], env=cli_env(), capture_output=True).returncode


@pytest.mark.parametrize("step", STEPS)
def test_an_update_killed_after_any_index_write_is_recovered_by_the_next_update(repo: Path, step: str):
    (repo / "pkg" / "m3.py").write_text("from pkg.m4 import f4\n\n\ndef f3():\n    return 3\n\n\n"
                                        "def extra_3():\n    return f4()\n")
    code = _crash_after(repo, step)
    assert code in (9, 0), code  # 0: that step did not happen in this update (nothing to crash on)
    assert run_cli(repo, "update", "-q").returncode == 0
    out = run_cli(repo, "symbol", "extra_3").stdout
    assert "pkg/m3.py" in out, (step, out)
    import sqlite3
    con = sqlite3.connect(repo / ".repo-ai" / "state" / "index.db")
    try:  # every derived table has the edited file's rows again
        assert con.execute("SELECT count(*) FROM search WHERE path='pkg/m3.py' AND identifiers LIKE '%extra_3%'"
                           ).fetchone()[0] == 1, step
        assert con.execute("SELECT resolved_path FROM imports WHERE src_path='pkg/m3.py'").fetchall() == [
            ("pkg/m4.py",)], step
    finally:
        con.close()


def test_a_completed_update_stays_incremental(repo: Path):
    """The marker is cleared when an update completes: the next one is not a full rebuild."""
    import sqlite3
    (repo / "pkg" / "m1.py").write_text("def f1():\n    return 10\n")
    assert run_cli(repo, "update", "-q").returncode == 0
    db = next(repo.glob(".repo-ai/state/index.db"))
    con = sqlite3.connect(db)
    assert con.execute("SELECT value FROM meta WHERE key='needs_reanalysis'").fetchone()[0] == "0"
    con.close()


def test_status_reports_an_interrupted_update_as_stale(repo: Path):
    (repo / "pkg" / "m3.py").write_text("def f3():\n    return 3\n\n\ndef extra_3():\n    return 4\n")
    assert _crash_after(repo, "upsert_files") == 9
    proc = run_cli(repo, "status", "--json")
    assert json.loads(proc.stdout)["stale"] is True, proc.stdout
    assert run_cli(repo, "update", "-q").returncode == 0
    assert json.loads(run_cli(repo, "status", "--json").stdout)["stale"] is False
