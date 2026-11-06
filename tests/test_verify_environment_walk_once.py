"""C16 fixed cost: one verify run walks each environment directory once.

`environment_key` (what may be remembered) and `static_environment` (what is
re-checked later) both identify the interpreter's site-packages and the
read-only dependency directories (`node_modules`) by every entry in them,
about 6 us an entry: 34 ms for a 6,500-entry virtualenv, far more for a large
`node_modules`. A run computed them back to back, walking every directory
twice. `environment_identity` takes one reading for both; nothing is kept
between calls, so a change to the environment is seen by the next call.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import run_cli

from repo_ai.verify import cache
from repo_ai.verify.runner import parse_command


def _executor(tmp_path: Path) -> SimpleNamespace:
    site = tmp_path / "venv" / "lib" / "site-packages"
    (site / "pkg").mkdir(parents=True)
    (site / "pkg" / "__init__.py").write_text("X = 1\n")
    (site / "other.py").write_text("Y = 2\n")
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    deps = tmp_path / "repo" / "node_modules"
    (deps / "left-pad").mkdir(parents=True)
    (deps / "left-pad" / "index.js").write_text("module.exports = 1;\n")
    return SimpleNamespace(backend=SimpleNamespace(name="seatbelt"), is_container=False, python=str(python),
                           node="node", site_dirs=[str(site)], links={"node_modules": str(deps)})


@pytest.fixture
def walks(monkeypatch) -> collections.Counter:
    seen: collections.Counter = collections.Counter()
    real = cache._tree_id

    def counting(path: str) -> str:
        seen[path] += 1
        return real(path)
    monkeypatch.setattr(cache, "_tree_id", counting)
    return seen


def test_one_reading_gives_both_identities_exactly_as_separately(tmp_path: Path, walks):
    ex, runner = _executor(tmp_path), parse_command("python -m pytest")
    key, static = cache.environment_key(ex, runner), cache.static_environment(ex, runner)
    assert set(walks.values()) == {2}                  # before: every directory walked twice
    walks.clear()
    assert cache.environment_identity(ex, runner) == (key, static)
    assert len(walks) == 2 and set(walks.values()) == {1}, walks   # site-packages and node_modules, once each
    assert cache.static_environment_change(static) == ("unchanged", "")


def test_nothing_is_kept_between_calls(tmp_path: Path, walks):
    ex, runner = _executor(tmp_path), parse_command("python -m pytest")
    key, static = cache.environment_identity(ex, runner)
    site = Path(ex.site_dirs[0])
    (site / "added.py").write_text("Z = 3\n")           # a package installed in place
    key2, static2 = cache.environment_identity(ex, runner)
    assert key2 != key and static2["digest"] != static["digest"]
    assert cache.static_environment_change(static)[0] == "changed"
    (Path(ex.links["node_modules"]) / "left-pad" / "index.js").write_text("module.exports = 2;;\n")
    key3, static3 = cache.environment_identity(ex, runner)
    assert key3 != key2 and static3["digest"] != static2["digest"]
    # one walk per directory per call (three calls), and the gate's re-check reads it again too
    assert set(walks.values()) == {4}


def test_the_shared_reading_ends_with_the_call_even_on_error(tmp_path: Path, monkeypatch, walks):
    ex, runner = _executor(tmp_path), parse_command("python -m pytest")
    cache.environment_identity(ex, runner)
    assert cache._TREES.get() is None
    cache.static_environment(ex, runner)
    cache.static_environment(ex, runner)
    assert walks[ex.site_dirs[0]] == 3                  # outside it, every reading is fresh (as the gate's is)

    def broken(*a, **k):
        raise OSError("gone")
    monkeypatch.setattr(cache, "static_environment", broken)
    with pytest.raises(OSError):
        cache.environment_identity(ex, runner)
    assert cache._TREES.get() is None


def test_a_tree_too_large_to_identify_never_matches(tmp_path: Path, monkeypatch, walks):
    ex, runner = _executor(tmp_path), parse_command("python -m pytest")
    monkeypatch.setattr(cache, "MAX_TREE_ENTRIES", 1)
    key, static = cache.environment_identity(ex, runner)
    key2, static2 = cache.environment_identity(ex, runner)
    assert key != key2 and static["digest"] != static2["digest"]   # as before: never reused


# -- through the real engine ---------------------------------------------------------
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _sandbox() -> bool:
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


@pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")
def test_a_verify_run_walks_each_environment_directory_once(tmp_path: Path, monkeypatch, walks):
    root = tmp_path / "p"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n", "tests/__init__.py": "",
             "tests/test_a.py": "import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                                "    def test_a(self):\n        self.assertEqual(add(1, 1), 2)\n"}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    from repo_ai.cli import main
    monkeypatch.chdir(root)
    out = __import__("io").StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(__import__("io").StringIO()):
        code = main(["verify", "--run", "--json", "--test-command", "python -m unittest discover -s tests -t ."])
    assert code == 0, out.getvalue()[-800:]
    rec = json.loads(out.getvalue())["evidence"]
    site_walks = {p: n for p, n in walks.items() if "site-packages" in p or "dist-packages" in p}
    assert site_walks and set(site_walks.values()) == {1}, dict(walks)
    # what was recorded is still a reading of the environment as it is
    assert cache.static_environment_change(rec["environment_static"]) == ("unchanged", "")
    assert rec["environment"] and sys.version_info >= (3, 10)
