"""Two agent sessions in one repository (or in two worktrees of it): what one
does must never corrupt, hide or invalidate the other's work. Each test
reproduces a failure found by a parallel-workload review of main 7e77912."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import evidence_environment, cli_env, run_cli

from repo_ai.verify import changes, evidence


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    for i in range(5):
        (root / "pkg" / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _layout(root: Path):
    from repo_ai.config import load_config
    from repo_ai.paths import detect_kind, resolve_layout
    return resolve_layout(root, load_config(root), prefer=detect_kind(root) or "standard")


def _counts(db: Path) -> tuple[int, int]:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT count(*) FROM files").fetchone()[0], con.execute(
            "SELECT count(*) FROM symbols").fetchone()[0]
    finally:
        con.close()


def test_a_rebuild_killed_while_waiting_for_the_lock_changes_nothing(repo: Path):
    """It used to delete index.db before taking the lock: the update holding the lock then
    wrote into an unlinked file and left an empty index that read as current."""
    from repo_ai.cli import _lock
    layout = _layout(repo)
    before = _counts(layout.index_path)
    inode = layout.index_path.stat().st_ino
    with _lock(layout) as held:
        assert held
        proc = subprocess.Popen([sys.executable, "-m", "repo_ai", "rebuild", "-q", "-C", str(repo)], env=cli_env(),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _wait_until_it_opens(proc, layout.lock_path)  # it is waiting on the lock (a fixed sleep could end earlier)
        proc.kill()
        proc.wait()
    assert layout.index_path.stat().st_ino == inode and _counts(layout.index_path) == before


def _wait_until_it_opens(proc: subprocess.Popen, path: Path, timeout: float = 30.0) -> None:
    """Until `proc` has `path` open (lsof), or a generous fixed wait without lsof."""
    import shutil
    if shutil.which("lsof") is None:
        time.sleep(5.0)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and proc.poll() is None:
        out = subprocess.run(["lsof", "-p", str(proc.pid)], capture_output=True, text=True).stdout
        if str(path.resolve()) in out or str(path) in out:
            return
        time.sleep(0.1)
    raise AssertionError("the rebuild never reached the lock")


def test_a_rebuild_killed_during_its_scan_reads_as_interrupted(repo: Path, monkeypatch):
    """The marker used to be set only after the scan: a rebuild killed while
    scanning left an empty index that `status` called current."""
    from repo_ai import analyze
    from repo_ai.config import load_config
    from repo_ai.index import open_index
    layout = _layout(repo)
    for name in ("index.db", "index.db-wal", "index.db-shm"):
        (layout.state_dir / name).unlink(missing_ok=True)

    def killed(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(analyze, "scan", killed)
    with pytest.raises(KeyboardInterrupt):
        analyze.run_analysis(repo, load_config(repo), layout.context_dir, incremental=False,
                             state_dir=layout.state_dir)
    idx = open_index(layout.state_dir)
    assert idx.get_meta("needs_reanalysis") == "1"
    idx.close()
    out = run_cli(repo, "status", "--brief").stdout
    assert "Context is current" not in out and "interrupted" in out, out


def test_status_brief_reports_an_interrupted_update(repo: Path):
    db = _layout(repo).index_path
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value='1' WHERE key='needs_reanalysis'")
    con.commit()
    con.close()
    out = run_cli(repo, "status", "--brief").stdout
    assert "Context is current" not in out and "interrupted" in out, out


def test_concurrent_evidence_writers_never_leave_a_torn_latest(tmp_path: Path):
    state = tmp_path / "state"
    rec = {"schema": evidence.SCHEMA, "fingerprint": "f" * 64, "verdict": "regression",
           "source_tree": {"unchanged": True}, "pad": "x" * 20000}
    stop = threading.Event()
    bad = []

    def read() -> None:
        while not stop.is_set():
            path = state / "evidence" / "latest.json"
            if path.exists():
                try:
                    json.loads(path.read_text("utf-8"))
                except ValueError:
                    bad.append(1)

    reader = threading.Thread(target=read)
    reader.start()
    writers = [threading.Thread(target=lambda: [evidence.save(state, rec) for _ in range(40)]) for _ in range(4)]
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    stop.set()
    reader.join()
    assert bad == [] and evidence.latest(state)["fingerprint"] == "f" * 64


def test_another_sessions_run_does_not_hide_valid_evidence_for_this_change(repo: Path):
    """Session 1 verified this exact change; session 2's run of another state (or an invalid
    run) then became latest. The gate and `repo-ai evidence` still find session 1's record."""
    from repo_ai.verify.gate import decision
    layout = _layout(repo)
    (repo / "pkg" / "m1.py").write_text("def f1():\n    return 10\n")
    fp = changes.fingerprint(repo)
    evidence.save(layout.state_dir, {**evidence_environment(repo), "schema": evidence.SCHEMA, "fingerprint": fp, "verdict": "nothing-selected",
                                     "source_tree": {"unchanged": True}})
    time.sleep(1.1)  # a later history entry
    evidence.save(layout.state_dir, {**evidence_environment(repo), "schema": evidence.SCHEMA, "fingerprint": "0" * 64, "verdict": "regression",
                                     "source_tree": {"unchanged": True}})
    assert decision(repo, layout, {"session_id": "s"}) == ""  # verified: silent
    out = json.loads(run_cli(repo, "evidence", "--json").stdout)
    assert out["current"] is True and out["evidence"]["fingerprint"] == fp


def test_an_invalid_run_never_becomes_the_latest(tmp_path: Path):
    state = tmp_path / "state"
    good = {"schema": evidence.SCHEMA, "fingerprint": "a" * 64, "verdict": "nothing-selected",
            "source_tree": {"unchanged": True}}
    evidence.save(state, good)
    evidence.save(state, {**good, "fingerprint": "b" * 64, "verdict": "invalid: the source tree changed during the run",
                          "source_tree": {"unchanged": False}}, latest=False)
    assert evidence.latest(state)["fingerprint"] == "a" * 64


def test_concurrent_testmap_saves_never_fail(tmp_path: Path):
    from repo_ai.verify.testmap import TestMap
    path = tmp_path / "testmap.json"
    errors = []

    def save() -> None:
        for _ in range(100):
            try:
                TestMap(runner={}).save(path)
            except OSError as exc:  # a fixed temporary name made concurrent writers collide
                errors.append(exc)
    threads = [threading.Thread(target=save) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and TestMap.load(path) is not None


def test_a_refresh_killed_after_claiming_the_dirty_marker_runs_again(repo: Path, monkeypatch):
    from repo_ai import hooks
    layout = _layout(repo)
    (layout.state_dir / ".dirty.processing").write_text("")
    spawned = []
    monkeypatch.setattr(hooks, "spawn_refresh", lambda root, **kw: spawned.append(root))
    hooks.on_stop({"cwd": str(repo)})
    assert spawned, "the Stop hook must respawn the refresh"


def test_drift_includes_files_whose_names_git_would_quote(repo: Path):
    from repo_ai.gitinfo import changed_since
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "pkg" / "café.py").write_text("X = 1\n")
    (repo / "pkg" / "m2.py").write_text("def f2():\n    return 20\n")
    assert {"pkg/café.py", "pkg/m2.py"} <= set(changed_since(repo, head))


def test_a_form_feed_does_not_shift_the_changed_code_unit(repo: Path):
    """str.splitlines() split on form feeds too, so the change mapped to the wrong function."""
    (repo / "pkg" / "ff.py").write_text("def f():\n    # a\x0cb\x0cc\n    return 1\n\n\ndef g():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ff")
    (repo / "pkg" / "ff.py").write_text("def f():\n    # a\x0cb\x0cc\n    return 9\n\n\ndef g():\n    return 2\n")
    change = changes.detect(repo, "HEAD")
    ff = next(f for f in change.files if f.path == "pkg/ff.py")
    assert ff.new_lines == [(3, 3)] and [u.split(":")[-1] for u in ff.units] == ["f"], (ff.new_lines, ff.units)


def test_another_sessions_refresh_and_commit_do_not_invalidate_a_running_verify(tmp_path: Path):
    """The integrity check used to stat `.git/` and `.repo-ai/context/` too: a hook-style
    refresh in the same repository, or a commit in a linked worktree, made a correct run
    "invalid: the source tree changed"."""
    from test_verify_adaptive import _sandbox
    if not _sandbox():
        pytest.skip("no sandbox backend to run tests in")
    root = tmp_path / "p"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n", "tests/__init__.py": "",
             "tests/test_slow.py": ("import time\nimport unittest\nfrom calc.core import add\n\n\n"
                                    "class S(unittest.TestCase):\n    def test_s(self):\n        time.sleep(4)\n"
                                    "        self.assertEqual(add(1, 1), 2)\n")}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    _git(root, "worktree", "add", "-q", "-b", "other", str(tmp_path / "wt2"))
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    env = cli_env({"REPO_AI_WORKSPACES": str(tmp_path / "ws")})
    proc = subprocess.Popen([sys.executable, "-m", "repo_ai", "verify", "--run", "--json", "--rerun", "-C", str(root),
                             "--test-command", "python -m unittest discover -s tests -t ."], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2.0)  # tests are running
    assert run_cli(root, "refresh", "--force").returncode == 0  # another session's hook
    (tmp_path / "wt2" / "n.txt").write_text("other session\n")
    _git(tmp_path / "wt2", "add", "-A")
    _git(tmp_path / "wt2", "commit", "-qm", "another session's commit")
    out, err = proc.communicate(timeout=300)
    ev = json.loads(out)["evidence"]
    assert ev["source_tree"]["unchanged"] is True, ev["source_tree"]
    assert not ev["verdict"].startswith("invalid"), ev["verdict"]


def test_a_killed_refreshs_claim_overrides_the_refresh_debounce(repo: Path):
    layout = _layout(repo)
    layout.stamp_path.touch()  # refreshed a moment ago: the debounce would skip
    (layout.state_dir / ".dirty.processing").write_text("pkg/m1.py\n")
    assert run_cli(repo, "refresh").returncode == 0
    assert not (layout.state_dir / ".dirty.processing").exists()


# -- the integrity check: what another session may change, and what nothing may -------------
def _snap(root: Path):
    from repo_ai.verify import engine, isolate
    before = isolate.snapshot(root, isolate.worktree_files(root)[0], skip=engine._own_state(root, _layout(root)))
    before.head = engine._head(root)
    return lambda: engine._integrity(root, before)


def test_bookkeeping_of_other_worktrees_and_submodules_is_not_a_change_but_their_hooks_are(repo: Path, tmp_path: Path):
    _git(repo, "worktree", "add", "-q", "-b", "other", str(tmp_path / "wt2"))
    sub = repo / ".git" / "modules" / "lib" / "sub"
    (sub / "hooks").mkdir(parents=True)
    (sub / "HEAD").write_text("ref: refs/heads/main\n")
    (sub / "objects").mkdir()
    check = _snap(repo)
    (tmp_path / "wt2" / "n.txt").write_text("x\n")
    _git(tmp_path / "wt2", "add", "-A")
    _git(tmp_path / "wt2", "commit", "-qm", "another session's commit")  # objects, refs, worktree logs/index
    (sub / "objects" / "ab").write_text("x")
    _git(repo, "worktree", "add", "-q", "-b", "third", str(tmp_path / "wt3"))  # a new worktree appears
    assert check()["unchanged"] is True, check()["changes"]
    for planted in (repo / ".git" / "worktrees" / "wt2" / "config.worktree", sub / "hooks" / "post-checkout",
                    repo / ".git" / "hooks" / "pre-commit"):
        check = _snap(repo)
        planted.write_text("#!/bin/sh\n")
        got = check()
        assert got["unchanged"] is False and any(planted.name in c for c in got["changes"]), (planted, got)
        planted.unlink()


def test_moving_the_checked_out_branch_is_a_change(repo: Path):
    check = _snap(repo)
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD").strip()
    _git(repo, "update-ref", "refs/heads/main", first)  # .git/HEAD itself is untouched
    got = check()
    assert got["unchanged"] is False and got["changes"][0].startswith("HEAD: moved"), got


# -- evidence history: ordering, the gate's view, Windows replace -----------------------------
def test_the_newest_record_of_a_change_wins_whatever_its_name(tmp_path: Path):
    state = tmp_path / "state"
    base = {"schema": evidence.SCHEMA, "fingerprint": "c" * 64, "source_tree": {"unchanged": True}}
    folder = state / "evidence"
    folder.mkdir(parents=True)
    old_pass, new_fail = folder / "20261103-013000-cccc-0000999.json", folder / "20261103-011000-cccc-0001000.json"
    old_pass.write_text(json.dumps({**base, "verdict": "selected-passed (full suite not run)"}))
    new_fail.write_text(json.dumps({**base, "verdict": "regression"}))
    os.utime(old_pass, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    os.utime(new_fail, ns=(1_000_000_100_000_000_000, 1_000_000_100_000_000_000))  # written later (a DST fall-back)
    assert evidence.for_fingerprint(state, "c" * 64)["verdict"] == "regression"


def test_a_formatter_rewrite_of_verified_code_is_still_verified_after_another_sessions_run(repo: Path):
    from repo_ai.verify.gate import decision
    layout = _layout(repo)
    (repo / "pkg" / "m1.py").write_text("def f1():\n    return 10\n")
    fp, sem = changes.fingerprint(repo), changes.semantic_fingerprint(repo, "HEAD")
    evidence.save(layout.state_dir, {**evidence_environment(repo), "schema": evidence.SCHEMA, "fingerprint": fp, "semantic_fingerprint": sem,
                                     "verdict": "selected-passed (full suite not run)",
                                     "source_tree": {"unchanged": True}})
    time.sleep(0.05)
    evidence.save(layout.state_dir, {**evidence_environment(repo), "schema": evidence.SCHEMA, "fingerprint": "0" * 64, "verdict": "regression",
                                     "source_tree": {"unchanged": True}})
    (repo / "pkg" / "m1.py").write_text("def f1():\n    return (10)\n")  # same behaviour, other bytes
    assert changes.fingerprint(repo) != fp and changes.semantic_fingerprint(repo, "HEAD") == sem
    assert decision(repo, layout, {"session_id": "s"}) == ""


def test_evidence_finds_this_changes_record_when_the_latest_used_another_base(repo: Path):
    layout = _layout(repo)
    _git(repo, "branch", "older", "HEAD~1")
    (repo / "pkg" / "m1.py").write_text("def f1():\n    return 10\n")
    evidence.save(layout.state_dir, {**evidence_environment(repo), "schema": evidence.SCHEMA, "fingerprint": changes.fingerprint(repo),
                                     "base": "HEAD", "verdict": "nothing-selected", "source_tree": {"unchanged": True}})
    time.sleep(0.05)
    evidence.save(layout.state_dir, {**evidence_environment(repo), "schema": evidence.SCHEMA, "fingerprint": "1" * 64, "base": "older",
                                     "verdict": "regression", "source_tree": {"unchanged": True}})
    out = json.loads(run_cli(repo, "evidence", "--json").stdout)
    assert out["current"] is True and out["evidence"]["base"] == "HEAD", out


def test_a_replace_blocked_by_a_reader_is_retried_and_leaves_no_temporary_file(tmp_path: Path, monkeypatch):
    from repo_ai import fsutil
    target = tmp_path / "latest.json"
    target.write_text("{}")
    real, calls = os.replace, []

    def held_open(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used")
        real(src, dst)
    monkeypatch.setattr(fsutil, "RETRY_SHARING_VIOLATIONS", True)
    monkeypatch.setattr(fsutil.os, "replace", held_open)
    fsutil.atomic_write(target, '{"a": 1}')
    assert json.loads(target.read_text()) == {"a": 1} and len(calls) == 3
    monkeypatch.setattr(fsutil.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError(32, "held")))
    with pytest.raises(PermissionError):
        fsutil.atomic_write(target, "{}")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["latest.json"]


# -- smaller parsing claims -----------------------------------------------------------------
def test_a_lone_carriage_return_numbers_lines_as_python_does(repo: Path):
    (repo / "pkg" / "cr.py").write_bytes(b"def f():\r    return 1\r\r\rdef g():\r    return 2\r")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "cr")
    (repo / "pkg" / "cr.py").write_bytes(b"def f():\r    return 1\r\r\rdef g():\r    return 9\r")
    ff = next(f for f in changes.detect(repo, "HEAD").files if f.path == "pkg/cr.py")
    assert ff.new_lines == [(6, 6)] and [u.split(":")[-1] for u in ff.units] == ["g"], (ff.new_lines, ff.units)


def test_drift_includes_a_renamed_file_with_an_unusual_name(repo: Path):
    from repo_ai.gitinfo import changed_since
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "mv", "pkg/m3.py", "pkg/nouveau modèle.py")  # git quotes it without -z (legal on Windows)
    assert "pkg/nouveau modèle.py" in set(changed_since(repo, head))


def test_concurrent_dynamic_cache_saves_leave_one_whole_file(tmp_path: Path):
    from repo_ai.verify import dynamic
    path = tmp_path / "dyn.json"
    threads = [threading.Thread(target=lambda: [dynamic._save_cache(path, {"a": {"x": i}}) for i in range(50)])
               for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert json.loads(path.read_text())["files"]["a"]["x"] == 49
    assert [p.name for p in tmp_path.iterdir()] == ["dyn.json"]
