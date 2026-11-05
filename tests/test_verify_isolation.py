"""Working-tree isolation for `repo-ai verify --run/--record`.

Tests run in a disposable copy, never in the developer's tree. These tests
check what the copy holds, that hostile tests cannot reach the original
(source, `.git`, ignored secrets), and that the source tree is byte-for-byte
unchanged after passing runs, failing runs, timeouts and cancellation.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import cli_env, default_sigint, run_cli

from repo_ai.verify import isolate

CMD = "python -m unittest discover -s tests -t ."
FILES = {
    "calc/__init__.py": "from calc.core import add\n",
    "calc/core.py": "def add(a, b):\n    return a + b\n",
    "tests/__init__.py": "",
    "tests/test_add.py": ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"),
    "tests/fixtures/server.key": "-----BEGIN TEST KEY (fixture, committed on purpose)-----\n",
    ".gitignore": ".env\nbuild/\nsecrets/\n*.log\nnode_modules/\n",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel, text in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    # the developer's uncommitted state: staged, unstaged, untracked, ignored, deleted
    (root / "calc" / "staged.py").write_text("STAGED = 1\n")
    _git(root, "add", "calc/staged.py")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b  # unstaged edit\n")
    (root / "calc" / "untracked.py").write_text("UNTRACKED = 1\n")
    (root / ".env").write_text("API_TOKEN=ignored-secret\n")                 # ignored
    (root / "secrets").mkdir()
    (root / "secrets" / "prod.json").write_text('{"password": "ignored"}\n')  # ignored directory
    (root / "deploy.pem").write_text("untracked, not ignored, credential-like\n")
    (root / "build").mkdir()
    (root / "build" / "out.txt").write_text("ignored build output\n")
    return root


def tree_digest(root: Path, skip: tuple[str, ...] = (".repo-ai/state",)) -> dict[str, str]:
    """Every entry under the root, `.git` and ignored files included: content
    hash, mode and mtime for files; target for symlinks."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        st = path.lstat()
        if path.is_symlink():
            out[rel] = "link:" + os.readlink(path)
        elif path.is_dir():
            out[rel] = f"dir:{stat.S_IMODE(st.st_mode):o}"
        else:
            out[rel] = (f"file:{hashlib.sha256(path.read_bytes()).hexdigest()}:"
                        f"{stat.S_IMODE(st.st_mode):o}:{st.st_mtime_ns}")
    return out


def _sandbox() -> bool:
    """A backend exists *and* can start the interpreter (some macOS hosts refuse
    to exec it under sandbox-exec; verify then reports it and runs nothing)."""
    import subprocess
    import tempfile
    from repo_ai.sandbox import SandboxUnavailable
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        try:
            ex = get_executor(Path(d), "auto", "python")
            with isolate.materialize(Path(d)) as ws:
                return ex.in_workspace(ws).run(["python", "-c", "pass"], timeout_s=60).exit_code == 0
        except SandboxUnavailable:
            return False


needs_sandbox = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")


# -- what the copy holds ------------------------------------------------------


def test_the_copy_is_the_working_tree_without_git_ignored_files_or_credentials(repo: Path):
    with isolate.materialize(repo) as ws:
        copy = ws.path
        assert (copy / "calc" / "core.py").read_text().endswith("# unstaged edit\n")  # unstaged
        assert (copy / "calc" / "staged.py").read_text() == "STAGED = 1\n"             # staged
        assert (copy / "calc" / "untracked.py").exists()                                # untracked
        assert (copy / "tests" / "fixtures" / "server.key").exists()  # tracked: part of the project
        assert not (copy / ".git").exists()
        assert not (copy / ".env").exists() and not (copy / "secrets").exists()        # ignored
        assert not (copy / "build").exists()
        assert not (copy / "deploy.pem").exists() and ws.withheld == ["deploy.pem"]     # credential-like
        assert isolate.workspaces_root() in copy.parents
    assert not copy.exists()  # deleted on exit


def test_deleted_files_are_absent_and_staged_content_is_superseded_by_the_working_tree(repo: Path):
    (repo / "calc" / "staged.py").write_text("STAGED = 2  # edited after staging\n")
    (repo / "tests" / "__init__.py").unlink()
    with isolate.materialize(repo) as ws:
        assert (ws.path / "calc" / "staged.py").read_text().startswith("STAGED = 2")
        assert not (ws.path / "tests" / "__init__.py").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes and symlinks")
def test_modes_and_symlinks(repo: Path, tmp_path: Path):
    tool = repo / "tool.sh"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    os.symlink("calc/core.py", repo / "inside-link.py")
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    os.symlink(str(outside), repo / "escape-link")
    os.symlink("../../outside.txt", repo / "calc" / "relative-escape")
    with isolate.materialize(repo) as ws:
        assert os.access(ws.path / "tool.sh", os.X_OK)
        assert os.readlink(ws.path / "inside-link.py") == "calc/core.py"
        assert not (ws.path / "escape-link").exists() and not (ws.path / "escape-link").is_symlink()
        assert not (ws.path / "calc" / "relative-escape").is_symlink()
        assert sorted(ws.skipped_links) == ["calc/relative-escape", "escape-link"]


def test_dependency_directories_are_exposed_read_only_never_copied(repo: Path):
    (repo / "package.json").write_text('{"name": "x"}\n')
    dep = repo / "node_modules" / "dep"
    dep.mkdir(parents=True)
    (dep / "index.js").write_text("module.exports = 1\n")
    with isolate.materialize(repo) as ws:
        assert ws.readonly == {"node_modules": str((repo / "node_modules").resolve())}
        assert not (ws.path / "node_modules").exists()  # until a backend exposes it
        ws.expose_dependencies("link")
        assert (ws.path / "node_modules").is_symlink()
        assert (ws.path / "node_modules" / "dep" / "index.js").read_text() == "module.exports = 1\n"


def test_the_base_revision_copy_comes_from_git_archive(repo: Path):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    with isolate.materialize_commit(repo, head) as ws:
        assert (ws.path / "calc" / "core.py").read_text() == "def add(a, b):\n    return a + b\n"
        assert not (ws.path / "calc" / "untracked.py").exists() and not (ws.path / ".git").exists()


def test_editable_installs_are_redirected_to_the_copy(tmp_path: Path):
    src = tmp_path / "proj"
    (src / "src" / "pkg").mkdir(parents=True)
    site = tmp_path / "site-packages"
    site.mkdir()
    (site / "_proj.pth").write_text(f"{src / 'src'}\nimport os\n/elsewhere/unrelated\n")
    (site / "__editable___other_0_1_finder.py").write_text(  # setuptools writes repr()-escaped paths
        f"MAPPING: dict[str, str] = {{'other': {str(src / 'lib' / 'other')!r}}}\nNAMESPACES = {{}}\n")
    (site / "proj.egg-link").write_text(str(src))
    assert isolate.editable_redirects([str(site)], src) == ["src", "lib"]


def test_the_executor_refuses_to_run_outside_a_disposable_workspace(repo: Path):
    from repo_ai import sandbox
    from repo_ai.verify.execute import Executor
    ex = Executor(sandbox.Backend(), repo)
    with pytest.raises(isolate.IsolationError):
        ex.run(["python", "-c", "print(1)"])


def test_workspaces_live_in_a_private_directory_and_stale_ones_are_swept():
    base = isolate.workspaces_root()
    if os.name == "posix":
        assert stat.S_IMODE(base.stat().st_mode) == 0o700
    stale = base / "ws-stale-test"
    stale.mkdir(exist_ok=True)
    (stale / isolate.WS_MARKER).write_text(json.dumps({"pid": 999_999_999, "created": time.time()}))
    being_made = base / "ws-being-made-test"  # created by another thread, marker not written yet
    being_made.mkdir(exist_ok=True)
    isolate.sweep()
    assert not stale.exists()
    assert being_made.exists()
    being_made.rmdir()


def test_concurrent_copies_never_delete_each_other(repo: Path):
    """Regression: sweeping inside every new copy deleted copies other threads
    were still creating (no marker yet), failing runs with ENOENT."""
    from concurrent.futures import ThreadPoolExecutor
    with isolate.materialize(repo) as template:
        def one(_):
            twin = template.clone("par")
            try:
                return sorted(twin.files) == sorted(template.files)
            finally:
                twin.cleanup()
        isolate._swept = False
        with ThreadPoolExecutor(8) as pool:
            assert all(pool.map(one, range(32)))


# -- integrity snapshots ------------------------------------------------------


def test_snapshots_detect_changes_to_source_git_and_ignored_files(repo: Path):
    before = isolate.snapshot(repo)
    assert before.changes(isolate.snapshot(repo)) == []
    for rel in ("calc/core.py", ".git/config", ".env"):
        p = repo / rel
        original = p.read_bytes()
        p.write_bytes(original + b"\n")
        assert any(c.startswith(rel + ":") for c in before.changes(isolate.snapshot(repo))), rel
        p.write_bytes(original)
        os.utime(p, ns=(before.stat[rel][2], before.stat[rel][2]))


def test_planning_leaves_the_tree_and_git_index_untouched(repo: Path):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    os.utime(repo / "calc" / "core.py")  # a stat-only change: git would refresh .git/index
    before = tree_digest(repo, skip=(".repo-ai",))
    assert run_cli(repo, "verify", "--test-command", CMD).returncode == 0
    assert run_cli(repo, "verify", "--json", "--test-command", CMD).returncode == 0
    assert tree_digest(repo, skip=(".repo-ai",)) == before


# -- hostile tests, failures, timeouts, cancellation (sandboxed runs) --------

HOSTILE = '''import json, os, pathlib, subprocess, sys, unittest

ORIG = pathlib.Path({orig!r})
HOME = pathlib.Path({home!r})


def attempt(results, name, fn):
    try:
        fn()
        results[name] = "SUCCEEDED"
    except Exception as exc:  # noqa: BLE001
        results[name] = "blocked:" + type(exc).__name__


class Hostile(unittest.TestCase):
    def test_attacks(self):
        r = {{}}
        attempt(r, "write_original_source", lambda: (ORIG / "calc" / "core.py").write_text("pwned"))
        attempt(r, "create_in_original", lambda: (ORIG / "pwned.txt").write_text("x"))
        attempt(r, "delete_in_original", lambda: (ORIG / "calc" / "__init__.py").unlink())
        attempt(r, "chmod_original", lambda: os.chmod(ORIG / "calc" / "core.py", 0o777))
        attempt(r, "write_git", lambda: (ORIG / ".git" / "config").write_text("x"))
        attempt(r, "read_git", lambda: (ORIG / ".git" / "config").read_text())
        attempt(r, "read_ignored_secret", lambda: (ORIG / ".env").read_text())
        attempt(r, "read_ignored_dir", lambda: (ORIG / "secrets" / "prod.json").read_text())
        attempt(r, "read_untracked_credential", lambda: (ORIG / "deploy.pem").read_text())
        attempt(r, "list_home", lambda: os.listdir(HOME))
        attempt(r, "secret_in_copy", lambda: pathlib.Path(".env").read_text())
        attempt(r, "credential_in_copy", lambda: pathlib.Path("deploy.pem").read_text())
        attempt(r, "git_in_copy", lambda: pathlib.Path(".git/config").read_text())
        # the copy itself is writable and disposable
        pathlib.Path("calc/core.py").write_text(pathlib.Path("calc/core.py").read_text() + "# copy edited\\n")
        pathlib.Path("tests/new_file.txt").write_text("left behind in the copy")
        # a child left running in the same process group, and one that detaches from it
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)  # rai-isolation-straggler"])
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)  # rai-isolation-straggler"],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        print("RESULTS " + json.dumps(r, sort_keys=True))
        sys.stdout.flush()
'''


def _hostile_repo(repo: Path) -> None:
    (repo / "tests" / "test_hostile.py").write_text(
        HOSTILE.format(orig=str(repo.resolve()), home=str(Path.home().resolve())))
    _git(repo, "add", "tests/test_hostile.py")


def _stragglers() -> list[str]:
    out = subprocess.run(["pgrep", "-f", "rai-isolation-straggler"], capture_output=True, text=True)
    return [p for p in out.stdout.split() if p]


@needs_sandbox
@pytest.mark.skipif(sys.platform == "win32", reason="host sandboxes are POSIX")
def test_hostile_tests_cannot_touch_the_source_tree_git_or_secrets(repo: Path):
    from repo_ai import sandbox
    from repo_ai.verify.execute import get_executor
    _hostile_repo(repo)
    before = tree_digest(repo)
    ws = isolate.materialize(repo)
    try:
        ex = get_executor(repo, "auto", "python").in_workspace(ws)
        res = ex.run(["python", "-m", "unittest", "tests.test_hostile", "-v"], timeout_s=120)
        ws_path = ws.path
        assert (ws_path / "calc" / "core.py").read_text().endswith("# copy edited\n")
    finally:
        ws.cleanup()
    text = res.stdout + res.stderr
    assert res.exit_code == 0, text[-2000:]
    results = json.loads(text.split("RESULTS ", 1)[1].splitlines()[0])
    succeeded = sorted(k for k, v in results.items() if v == "SUCCEEDED")
    assert succeeded == [], results
    assert tree_digest(repo) == before          # byte-for-byte, .git and ignored files included
    assert not ws_path.exists()
    assert sandbox.live_count() == 0
    time.sleep(0.5)
    assert _stragglers() == []                  # the process group was killed after the run


@needs_sandbox
def test_failing_runs_and_timeouts_leave_the_tree_unchanged(repo: Path):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")  # a regression
    (repo / "tests" / "test_slow.py").write_text(
        "import time, unittest\nfrom calc.core import add\n\n\nclass S(unittest.TestCase):\n"
        "    def test_slow(self):\n        add(1, 1)\n        time.sleep(60)\n")
    before = tree_digest(repo)
    own = repo.parent / "workspaces"  # this run's own: another session's runs share the default one
    proc = run_cli(repo, "verify", "--run", "--json", "--timeout", "4", "--test-command", CMD,
                   env={"REPO_AI_WORKSPACES": str(own)})
    out = json.loads(proc.stdout)
    statuses = {r["test"]: r["status"] for r in out["evidence"]["results"]}
    assert statuses.get("tests/test_add.py") == "fail" and statuses.get("tests/test_slow.py") == "timeout"
    assert out["evidence"]["source_tree"]["unchanged"] is True
    assert out["evidence"]["isolation"]["files"] >= 6 and out["evidence"]["isolation"]["withheld_credential_like"] \
        == ["deploy.pem"]
    assert tree_digest(repo) == before
    assert list(own.iterdir()) == []  # its copies were deleted


@needs_sandbox
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_cancellation_kills_tests_deletes_the_copy_and_leaves_the_tree_unchanged(repo: Path, sig: int):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    token = f"hang{os.getpid()}x{sig}x{int(time.time() * 1000) % 100000}"  # only this test's process matches
    (repo / "tests" / f"test_{token}.py").write_text(
        "import time, unittest\nfrom calc.core import add\n\n\nclass H(unittest.TestCase):\n"
        "    def test_hang(self):\n        add(1, 1)\n        time.sleep(120)  # rai-isolation-hang\n")
    before = tree_digest(repo)
    own = repo.parent / "workspaces"  # this run's own: another session's runs share the default one
    proc = subprocess.Popen([sys.executable, "-m", "repo_ai", "verify", "-C", str(repo), "--run",
                             "--test-command", CMD], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=cli_env({"REPO_AI_WORKSPACES": str(own)}), preexec_fn=default_sigint)
    deadline = time.time() + 60
    while time.time() < deadline and proc.poll() is None:
        hung = subprocess.run(["pgrep", "-f", f"tests.test_{token}"], capture_output=True, text=True)
        if hung.stdout.strip():
            break
        time.sleep(0.3)
    assert proc.poll() is None, proc.communicate()
    time.sleep(1.0)
    started = time.time()
    proc.send_signal(sig)
    _, err = proc.communicate(timeout=60)
    assert time.time() - started < 30
    assert proc.returncode == 130, err
    assert "cancelled: stopped 1 running" in err or "cancelled: stopped 2 running" in err, err
    assert tree_digest(repo) == before
    assert [p for p in own.iterdir() if p.name.startswith("run-")] == []
    time.sleep(0.5)
    left = subprocess.run(["pgrep", "-f", f"tests.test_{token}"], capture_output=True, text=True).stdout
    assert left == "", subprocess.run(["ps", "-o", "pid,ppid,pgid,stat,etime,command", "-p",
                                       ",".join(left.split())], capture_output=True, text=True).stdout


@needs_sandbox
def test_recording_runs_in_the_copy_and_hashes_what_the_tests_saw(repo: Path):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    before = tree_digest(repo)
    proc = run_cli(repo, "verify", "--record", "--json", "--test-command", CMD)
    assert proc.returncode == 0, proc.stderr
    assert tree_digest(repo) == before
    tmap = json.loads((repo / ".repo-ai" / "state" / "testmap.json").read_text())
    from repo_ai.verify.changes import sha
    assert tmap["file_hashes"]["calc/core.py"] == sha((repo / "calc" / "core.py").read_bytes())
    assert "calc/untracked.py" in tmap["file_hashes"] and ".env" not in tmap["file_hashes"]


def test_a_missing_runner_is_an_environment_error_and_grants_no_reads(tmp_path: Path, monkeypatch):
    from repo_ai import sandbox
    from repo_ai.verify.execute import get_executor
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.chdir(tmp_path)
    try:
        sandbox.get_backend("auto")
    except sandbox.SandboxUnavailable:
        pytest.skip("no sandbox backend")
    with pytest.raises(sandbox.SandboxUnavailable, match="node is not on PATH"):
        get_executor(tmp_path, "auto", "node")


def test_a_command_the_sandbox_cannot_start_is_not_reported_as_a_test_failure():
    from repo_ai import sandbox
    from repo_ai.verify.execute import _raise_if_not_started
    with pytest.raises(sandbox.SandboxUnavailable, match="could not start"):
        _raise_if_not_started(sandbox.Result(71, "", "sandbox-exec: execvp() of 'node' failed: No such file",
                                             0.0, False, "seatbelt"))
    _raise_if_not_started(sandbox.Result(1, "", "AssertionError: 1 != 2", 0.0, False, "seatbelt"))


def test_a_bubblewrap_setup_failure_is_not_reported_as_a_test_failure():
    # Found in a podman container (2026-10-29): bwrap could create namespaces but not mount /proc, so
    # every run, base and change alike, "failed", and a real regression was called pre-existing.
    from repo_ai import sandbox
    from repo_ai.verify.execute import _raise_if_not_started
    for err in ("bwrap: Can't mount proc on /proc: Permission denied\n",
                "bwrap: No permissions to creating new namespace, likely because the kernel does not allow\n",
                "bwrap: setting up uid map: Permission denied\n"):
        with pytest.raises(sandbox.SandboxUnavailable, match="nothing was verified"):
            _raise_if_not_started(sandbox.Result(1, "", err, 0.0, False, "bwrap"))
    # a test run that printed something is a run, whatever its stderr says
    _raise_if_not_started(sandbox.Result(1, "collected 2 items\n", "bwrap: hello from a test\n", 0.0, False, "bwrap"))
    _raise_if_not_started(sandbox.Result(2, "", "bwrap: odd exit code\n", 0.0, False, "bwrap"))


def test_the_bwrap_probe_mounts_what_a_real_run_mounts(monkeypatch):
    from repo_ai import sandbox
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        failed = "--proc" in argv  # namespaces work, /proc does not (the container case)
        return subprocess.CompletedProcess(argv, 1 if failed else 0, b"",
                                           b"bwrap: Can't mount proc on /proc: Permission denied" if failed else b"")
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    ok, why = sandbox.BwrapBackend().available()
    assert not ok and "mount proc" in why
    assert {"--proc", "--dev", "--tmpfs"} <= set(seen[0])


@needs_sandbox
def test_batched_runs_attribute_failures_to_files_exactly_like_per_file_runs(repo: Path):
    for i in range(6):
        (repo / "tests" / f"test_more{i}.py").write_text(
            "import unittest\nfrom calc.core import add\n\n\nclass M(unittest.TestCase):\n"
            f"    def test_{i}(self):\n        self.assertEqual(add({i}, 1), {i + 1})\n")
    _git(repo, "add", "-A", "tests")
    _git(repo, "commit", "-qm", "more tests")
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")  # behaviour unchanged
    ok = json.loads(run_cli(repo, "verify", "--run", "--json", "--workers", "2", "--test-command", CMD).stdout)
    assert ok["evidence"]["execution"].startswith("2 batch(es)")
    assert all(r["status"] == "pass" and r.get("batched") for r in ok["evidence"]["results"])
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a + b if a != 3 else 0\n")  # breaks one file
    bad = json.loads(run_cli(repo, "verify", "--run", "--json", "--workers", "2", "--test-command", CMD).stdout)
    failed = [r for r in bad["evidence"]["results"] if r["status"] != "pass"]
    assert [r["test"] for r in failed] == ["tests/test_more3.py"]
    assert failed[0]["baseline"] == "pass" and failed[0]["classification"].startswith("new failure")
    assert len(bad["evidence"]["results"]) == len(ok["evidence"]["results"])


@needs_sandbox
def test_parallel_test_files_never_share_a_copy(repo: Path):
    """Two files that use the same fixed file in the working directory (a SQLite
    database, an output file) collide when run in parallel in one copy; each
    process gets its own pristine copy, as in a sequential run."""
    body = ("import pathlib, time, unittest\n\n\nclass F(unittest.TestCase):\n    def test_fixed_file(self):\n"
            "        p = pathlib.Path('shared-state.txt')\n        p.write_text('{tag}')\n        time.sleep(1.0)\n"
            "        self.assertEqual(p.read_text(), '{tag}')\n")
    (repo / "tests" / "test_one.py").write_text(body.format(tag="one"))
    (repo / "tests" / "test_two.py").write_text(body.format(tag="two"))
    _git(repo, "add", "-A", "tests")
    _git(repo, "commit", "-qm", "fixed-file tests")
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    rec = run_cli(repo, "verify", "--record", "--json", "--workers", "4", "--test-command", CMD)
    assert rec.returncode == 0, rec.stderr
    assert json.loads(rec.stdout)["baseline_failures"] == []
    (repo / "tests" / "test_one.py").write_text(body.format(tag="one") + "\nTOUCHED = 1\n")
    (repo / "tests" / "test_two.py").write_text(body.format(tag="two") + "\nTOUCHED = 1\n")
    out = json.loads(run_cli(repo, "verify", "--run", "--json", "--workers", "4", "--test-command", CMD).stdout)
    statuses = {r["test"]: r["status"] for r in out["evidence"]["results"]}
    assert statuses.get("tests/test_one.py") == "pass" and statuses.get("tests/test_two.py") == "pass", statuses


@needs_sandbox
def test_a_batch_with_an_endless_loop_is_cut_short_and_attributed(repo: Path):
    for i in range(6):
        loop = "        while True:\n            pass\n" if i == 4 else ""
        (repo / "tests" / f"test_b{i}.py").write_text(
            "import unittest\nfrom calc.core import add\n\n\nclass B(unittest.TestCase):\n"
            f"    def test_{i}(self):\n{loop}        self.assertEqual(add({i}, 1), {i + 1})\n")
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    _git(repo, "add", "-A")  # nothing else uncommitted: the plan needs no full suite
    _git(repo, "commit", "-qm", "batch tests")
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    started = time.time()
    out = json.loads(run_cli(repo, "verify", "--run", "--json", "--workers", "2", "--timeout", "3",
                             "--test-command", CMD).stdout)
    assert time.time() - started < 60  # never len(files) x the per-file limit
    status = {r["test"]: r["status"] for r in out["evidence"]["results"]}
    assert status["tests/test_b4.py"] == "timeout"
    assert all(s == "pass" for t, s in status.items() if t != "tests/test_b4.py"), status


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_an_interpreter_reached_through_a_symlink_farm_is_readable(tmp_path: Path):
    """Regression (CI, macOS runner): the toolcache's bin/python3 is a symlink
    into /Library/Frameworks; reads were granted on the resolved prefix only, so
    sandbox-exec could not exec the path it was given."""
    from repo_ai.verify.execute import _prefixes
    farm = tmp_path / "toolcache" / "Python" / "3.x" / "arm64" / "bin"
    farm.mkdir(parents=True)
    (farm / "python3").symlink_to(Path(sys.executable).resolve())
    reads = _prefixes(str(farm / "python3"))
    assert str((farm.parent).absolute()) in reads
    assert str(Path(sys.executable).resolve().parent.parent) in reads


def test_withheld_credential_files_are_not_part_of_the_change(repo: Path):
    from repo_ai.verify import changes as ch
    c = ch.detect(repo)
    assert "deploy.pem" not in c.paths() and c.withheld == ["deploy.pem"]
    before = c.fingerprint
    (repo / "deploy.pem").write_text("rotated\n")  # tests never see it: the evidence stays current
    assert ch.detect(repo).fingerprint == before


def test_test_output_cannot_pose_as_a_bwrap_failure_on_another_backend():
    # adversarial review finding D: on seatbelt, a test printing "bwrap: ..." must stay a test result
    from repo_ai import sandbox
    from repo_ai.verify.execute import _raise_if_not_started
    _raise_if_not_started(sandbox.Result(1, "", "bwrap: Can't mount proc on /proc\n", 0.0, False, "seatbelt"))
    _raise_if_not_started(sandbox.Result(1, "", "bwrap: execvp x: No such file\n", 0.0, False, "seatbelt"))


def test_bwrap_never_binds_a_shared_temp_root(monkeypatch, tmp_path):
    # adversarial review finding C: --tmpfs /tmp first must not let a bind of /tmp itself re-expose host /tmp
    from repo_ai import sandbox
    assert sandbox._hides_temp("/tmp") and sandbox._hides_temp("/") and sandbox._hides_temp("/var")
    assert not sandbox._hides_temp("/tmp/venv") and not sandbox._hides_temp("/opt/tool")
    seen = {}
    monkeypatch.setattr(sandbox.BwrapBackend, "available", lambda self: (True, "test"))
    monkeypatch.setattr(sandbox, "check_workspace", lambda *a, **k: None)
    monkeypatch.setattr(sandbox, "_toolchain_dirs", lambda toolchain: ["/tmp", "/var/tmp"])
    monkeypatch.setattr(sandbox, "_run_host", lambda cmd, *a, **k: seen.setdefault("cmd", cmd))
    sandbox.BwrapBackend().run(["true"], tmp_path, limits=sandbox.Limits(timeout_s=5))
    cmd = seen["cmd"]
    binds = [cmd[i + 1] for i, part in enumerate(cmd) if part == "--ro-bind"]
    assert "/tmp" not in binds and "/var/tmp" not in binds
    assert cmd.index("--tmpfs") < cmd.index("--bind")
