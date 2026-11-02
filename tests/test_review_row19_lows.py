"""Queue row 19: the open lows from the 0.11.8 release review (L2, L4, L6 rest). Benign inputs only: no attack-like
fixture is written or scanned here (those stay in the CI-only security-fixture modules)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from repo_ai import coding_lab, firewall
from repo_ai.providers import discovery as d

GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "maintenance.auto=false",
       "-c", "gc.auto=0"]  # no background maintenance racing the copy of .git


# --- L4: a minified one-line file named LICENSE below the skill's root -------------------------------------------

def _inspect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str, text: str) -> list:
    monkeypatch.setenv("REPO_AI_HOME", str(tmp_path / "rh"))
    skill = tmp_path / "s"
    (skill / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("---\nname: s\ndescription: \"Summarise a failing test run.\"\n"
                                    "---\n# Steps\n\n1. Read the output.\n", encoding="utf-8")
    (skill / rel).write_text(text, encoding="utf-8")
    dest, files, prior = firewall.quarantine_local(skill, skill.name)
    report = firewall.inspect(dest, files, {"id": "local/s", "name": skill.name, "path": skill.name}, {}, prior)
    return [f for f in report.findings if f.file == rel]


MINIFIED = "var a=function(b){return b+1};" * 120 + "\n"  # one line of plain arithmetic, over 2,000 characters


@pytest.mark.parametrize("rel", ["vendor/LICENSE", "vendor/COPYING", "lib/x/NOTICE"])
def test_a_minified_line_in_a_nested_licence_named_file_is_an_overlong_code_line(tmp_path, monkeypatch, rel):
    found = _inspect(tmp_path, monkeypatch, rel, MINIFIED)
    assert [f.rule for f in found if f.severity == "high"] == ["overlong-code-line"], found


@pytest.mark.parametrize("rel", ["LICENSE", "fonts/LICENSE"])
def test_a_long_licence_paragraph_is_still_not_an_overlong_code_line(tmp_path, monkeypatch, rel):
    text = "Permission is hereby granted, free of charge, to any person obtaining a copy " * 40 + "\n"
    assert not [f for f in _inspect(tmp_path, monkeypatch, rel, text) if f.severity in ("high", "critical")]


@pytest.mark.parametrize("line,prose", [
    ("Permission is hereby granted, free of charge, to any person obtaining a copy " * 40, True),
    ('THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND (EXPRESS OR IMPLIED). ' * 30, True),
    ("var a=function(b){return b+1};" * 120, False),
    ("x" * 3000, False),  # one word: no spaces
    ("a;b " * 800, False),
    ("本软件按原样提供不附带任何明示或暗示的担保包括但不限于适销性和特定用途适用性的担保" * 40, True),  # no spaces
    ("var 本=function(b){return b+1};" * 120, False),
])
def test_prose_lines(line, prose):
    assert firewall._prose_line(line) is prose


# --- L6 (rest): an agent-written .gitignore hides new files from the untracked count ----------------------------

def _repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    ws.mkdir()
    for rel, text in files.items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(text)
    subprocess.run([*GIT, "init", "-q"], cwd=ws, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=ws, check=True)
    subprocess.run([*GIT, "commit", "-qm", "base"], cwd=ws, check=True)
    pristine = tmp_path / "git-copy"
    shutil.copytree(ws / ".git", pristine, symlinks=True)
    return ws, pristine


def test_a_gitignore_the_agent_writes_does_not_hide_its_new_files(tmp_path):
    ws, pristine = _repo(tmp_path, {"a.py": "x = 1\n"})
    (ws / ".gitignore").write_text("*.py\n")  # new, untracked
    (ws / "pkg").mkdir()
    (ws / "pkg" / ".gitignore").write_text("*\n")
    (ws / "pkg" / "b.py").write_text("y = 1\n")
    (ws / "new.py").write_text("z = 1\n")
    changed, untracked = coding_lab._workspace_changes(ws, pristine)
    assert changed == []
    assert sorted(untracked) == [".gitignore", "new.py", "pkg/.gitignore", "pkg/b.py"]


def test_an_edited_tracked_gitignore_is_a_change_and_does_not_hide_new_files(tmp_path):
    ws, pristine = _repo(tmp_path, {"a.py": "x = 1\n", ".gitignore": "*.log\n"})
    (ws / ".gitignore").write_text("*.log\n*.py\n")
    (ws / "new.py").write_text("z = 1\n")
    (ws / "run.log").write_text("ok\n")
    changed, untracked = coding_lab._workspace_changes(ws, pristine)
    assert changed == [".gitignore"] and untracked == ["new.py"]


def test_the_base_commits_gitignore_files_still_apply(tmp_path):
    """What the project ignored before the run (its own .gitignore files, at any depth) is still ignored."""
    ws, pristine = _repo(tmp_path, {"a.py": "x = 1\n", ".gitignore": "*.log\n/build/\n!keep.log\n",
                                    "sub/.gitignore": "cache/\n*.tmp\n/local.txt\n", "sub/m.py": "m = 1\n"})
    for rel in ["run.log", "keep.log", "build/out.o", "sub/cache/x", "sub/deep/cache/y", "sub/t.tmp",
                "sub/deep/u.tmp", "sub/local.txt", "sub/deep/local.txt", "other/t.tmp", "new.py"]:
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text("1\n")
    untracked = sorted(coding_lab._workspace_changes(ws, pristine)[1])
    assert untracked == ["keep.log", "new.py", "other/t.tmp", "sub/deep/local.txt"]


@pytest.mark.parametrize("files", [
    {".gitignore": "*.log\n", "-docs/.gitignore": "!keep.log\n"},  # a sibling sorting before the root file
    {".gitignore": "vendor/*\n", "sub/.gitignore": "!\n"},  # a lone `!` matches nothing
    {"[ab]/.gitignore": "*.tmp\n"},  # glob characters in the directory name
    {"sub/.gitignore": "out/  \n"},  # trailing spaces
    {".gitignore": "*.log\n!keep.log\n", "sub/.gitignore": "*.log\n", "sub/deep/.gitignore": "!keep.log\n/x\n"},
])
def test_untracked_files_match_gits_own_reading_of_the_base_ignore_files(tmp_path, files):
    """On an untouched base (no agent change), the count equals `git ls-files --others --exclude-standard`."""
    ws, pristine = _repo(tmp_path, {**files, "a.py": "x = 1\n"})
    for rel in ["keep.log", "-docs/keep.log", "-docs/x.log", "vendor/v.py", "sub/vendor/w.py", "a/y.tmp", "[ab]/x.tmp",
                "sub/out/o", "out/p", "sub/keep.log", "sub/deep/keep.log", "sub/deep/x", "sub/deep/z.log"]:
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text("1\n")
    native = subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=ws, capture_output=True,
                            check=True).stdout.decode().split("\0")
    assert sorted(coding_lab._workspace_changes(ws, pristine)[1]) == sorted(p for p in native if p)


def test_a_nested_repository_does_not_collapse_new_files_into_one_entry(tmp_path):
    ws, pristine = _repo(tmp_path, {"a.py": "x = 1\n"})
    (ws / "nest").mkdir()
    subprocess.run([*GIT, "init", "-q"], cwd=ws / "nest", check=True)
    for i in range(3):
        (ws / "nest" / f"f{i}.py").write_text("1\n")
    assert sorted(coding_lab._workspace_changes(ws, pristine)[1]) == ["nest/f0.py", "nest/f1.py", "nest/f2.py"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="macOS file systems refuse non-UTF-8 names")
def test_a_non_utf8_file_name_is_counted_not_a_crash(tmp_path):
    ws, pristine = _repo(tmp_path, {"a.py": "x = 1\n"})
    with open(os.fsencode(ws) + b"/caf\xe9.py", "w") as f:
        f.write("1\n")
    assert coding_lab._workspace_changes(ws, pristine)[1] == [os.fsdecode(b"caf\xe9.py")]


def test_gitignore_patterns_are_anchored_to_their_directory():
    assert coding_lab._anchored("sub", ["cache/", "*.tmp", "/local.txt", "!keep", "a/b", "# c", "", "\\#x"]) == [
        "/sub/**/cache/", "/sub/**/*.tmp", "/sub/local.txt", "!/sub/**/keep", "/sub/a/b", "/sub/**/\\#x"]
    assert coding_lab._anchored("", ["*.log", "/build/", "a/b/", "!", "x  ", "y\\ "]) == [
        "*.log", "/build/", "a/b/", "x", "y\\ "]
    assert coding_lab._anchored("[ab]", ["*.tmp", "!", "/"]) == ["/\\[ab]/**/*.tmp"]


# --- L2: the Linux probe binds what it resolved and checked, not whatever the path names later -------------------

def test_pin_refuses_a_path_with_a_symlinked_component(tmp_path):
    real = tmp_path.resolve() / "real"
    (real / "bin").mkdir(parents=True)
    (real / "bin" / "agent").write_text("#!/bin/sh\n")
    (tmp_path.resolve() / "link").symlink_to(real)
    for ok in (real / "bin", real / "bin" / "agent"):
        fd = d._pin(str(ok))
        assert fd is not None
        try:
            assert os.fstat(fd).st_ino == os.stat(ok).st_ino
        finally:
            os.close(fd)
    assert d._pin(str(tmp_path.resolve() / "link" / "bin")) is None  # swapped in since it was resolved
    assert d._pin(str(tmp_path.resolve() / "link")) is None
    assert d._pin(str(real / "missing")) is None


def _linux_bwrap(monkeypatch: pytest.MonkeyPatch, *, fd_binds: bool = True) -> None:
    monkeypatch.setattr(d.sys, "platform", "linux")
    monkeypatch.setattr(d.shutil, "which", lambda name, path=None: "/usr/bin/bwrap")
    monkeypatch.setattr(d, "_bwrap_binds_fds", lambda bwrap: fd_binds)


def test_the_probe_binds_the_pinned_descriptor(tmp_path, monkeypatch):
    _linux_bwrap(monkeypatch)
    hidden = tmp_path.resolve()
    monkeypatch.setattr(d, "_hidden_dirs", lambda: [str(hidden)])
    bins = hidden / "bins"
    bins.mkdir()
    agent = bins / "agent"
    agent.write_text("#!/bin/sh\n")
    prefix = d._sandbox_prefix(hidden / "scratch", [agent, bins])
    assert prefix is not None
    binds = [(prefix[i + 1], prefix[i + 2]) for i, a in enumerate(prefix) if a in ("--ro-bind", "--ro-bind-fd")]
    assert binds[0] == ("/", "/") and [dest for _, dest in binds[1:]] == [str(bins), str(agent)]
    assert all(a != "--ro-bind" or prefix[i + 1] == "/" for i, a in enumerate(prefix))  # nothing else by path
    fds = [int(src) for src, _ in binds[1:]]
    assert d.pinned_fds(prefix) == tuple(fds)
    for fd, (_, dest) in zip(fds, binds[1:], strict=True):
        assert os.fstat(fd).st_ino == os.stat(dest).st_ino  # held open while the prefix lives
    del prefix
    import gc
    gc.collect()
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)  # closed with the prefix


def test_a_path_swapped_after_resolution_is_not_bound(tmp_path, monkeypatch):
    """The exposed path resolved before a component became a symlink (to a directory that holds a socket, say):
    nothing is bound at that path, so the program does not run rather than seeing the swapped-in directory."""
    _linux_bwrap(monkeypatch)
    hidden = tmp_path.resolve()
    monkeypatch.setattr(d, "_hidden_dirs", lambda: [str(hidden)])
    real = hidden / "real"
    real.mkdir()
    (real / "agent").write_text("#!/bin/sh\n")
    (hidden / "a").symlink_to(real)  # `a` was a directory when it was resolved
    monkeypatch.setattr(d.Path, "resolve", lambda self, strict=False: Path(os.path.abspath(self)))
    prefix = d._sandbox_prefix(hidden / "scratch", [hidden / "a" / "agent", hidden / "a"])
    assert prefix is not None
    assert [prefix[i + 2] for i, a in enumerate(prefix) if a in ("--ro-bind", "--ro-bind-fd")] == ["/"]


def test_an_older_bubblewrap_binds_by_path_as_before(tmp_path, monkeypatch):
    """No --ro-bind-fd (bubblewrap before 0.8): the path binds of 0.11.9, race not closed (recorded as residual)."""
    _linux_bwrap(monkeypatch, fd_binds=False)
    hidden = tmp_path.resolve()
    monkeypatch.setattr(d, "_hidden_dirs", lambda: [str(hidden)])
    (hidden / "bins").mkdir()
    (hidden / "bins" / "agent").write_text("#!/bin/sh\n")
    prefix = d._sandbox_prefix(hidden / "scratch", [hidden / "bins" / "agent", hidden / "bins"])
    assert [(prefix[i + 1], prefix[i + 2]) for i, a in enumerate(prefix) if a == "--ro-bind"] == [
        ("/", "/"), (str(hidden / "bins"), str(hidden / "bins")), (str(hidden / "bins" / "agent"),) * 2]
    assert d.pinned_fds(prefix) == ()


def test_a_subdirectory_swapped_during_the_socket_walk_counts_as_a_socket(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    real_scandir = os.scandir
    swapped = []

    def scandir(target):
        it = real_scandir(target)
        if not swapped:  # after the top level is listed, `a` becomes another directory
            swapped.append(True)
            (tmp_path / "a").rename(tmp_path / "a-old")
            (tmp_path / "b").rename(tmp_path / "a")
        return it
    monkeypatch.setattr(d.os, "scandir", scandir)
    assert d._has_socket(str(tmp_path)) is True


def test_discovery_imports_without_the_posix_open_flags():
    """Windows has neither O_DIRECTORY nor O_NOFOLLOW (the review of #99 found the import crashing there)."""
    code = ("import os\nfor n in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_PATH'):\n    if hasattr(os, n): delattr(os, n)\n"
            "import repo_ai.providers.discovery as d\nassert d._pin('/') is None\n")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr


def _bwrap_works() -> bool:
    bwrap = shutil.which("bwrap")
    if not sys.platform.startswith("linux") or not bwrap:
        return False
    return subprocess.run([bwrap, "--ro-bind", "/", "/", "true"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _bwrap_works(), reason="needs a working bubblewrap (the sandbox-bwrap CI job)")
def test_a_program_under_a_hidden_directory_runs_from_its_pinned_bind(tmp_path):
    """Real bubblewrap: the descriptor bind (/proc/<pid>/fd/<n>) brings back the program's own directory."""
    hidden = Path(d._hidden_dirs()[0])
    folder = Path(__import__("tempfile").mkdtemp(prefix="rai-pin-", dir=hidden))
    try:
        agent = folder / "agent"
        # prints each open descriptor's target: none may be the bound directory (bubblewrap must close its op fds)
        agent.write_text("#!/bin/sh\nfor f in /proc/self/fd/*; do readlink \"$f\"; done\necho pinned-ok\n")
        agent.chmod(0o755)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        prefix = d._sandbox_prefix(scratch, [agent, folder])
        assert prefix is not None
        assert "--ro-bind-fd" in prefix, prefix  # the CI runner's bubblewrap (0.9) binds descriptors
        result = d._capture([*prefix, str(agent)], scratch, d._probe_env(scratch), pass_fds=d.pinned_fds(prefix))
        lines = result.output.decode().split()
        assert result.returncode == 0 and lines[-1] == "pinned-ok", result
        assert str(folder) not in lines and str(hidden) not in lines, lines
    finally:
        shutil.rmtree(folder, ignore_errors=True)
