"""`gitbin.git()`: Apple's `/usr/bin/git` stub resolved to the program it would run, statically.

The stub asks xcrun for the developer directory on every call (about half the cost of a git command on macOS); the
selection follows xcrun: DEVELOPER_DIR, then the xcode-select link, then `xcode-select -p` (asked once). When anything
is unusual, it falls back to plain "git", which PATH resolves exactly as before."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from repo_ai import gitbin

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX executables and symlinks")


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


@pytest.fixture()
def mac(tmp_path, monkeypatch):
    """A fake macOS layout: the stub first on PATH, no selection yet."""
    stub = _exe(tmp_path / "usr-bin" / "git")
    monkeypatch.setattr(gitbin.sys, "platform", "darwin")
    monkeypatch.setattr(gitbin, "_APPLE_STUB", stub)
    monkeypatch.setattr(gitbin, "_APPLE_DEVELOPER_LINK", tmp_path / "xcode_select_link")
    monkeypatch.setattr(gitbin, "_default_developer", lambda: None)
    monkeypatch.setenv("PATH", str(stub.parent))
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    return tmp_path


def test_other_platforms_run_git_from_path(monkeypatch):
    monkeypatch.setattr(gitbin.sys, "platform", "linux")
    assert gitbin.git() == "git"


@pytest.mark.parametrize("selection", ["environment", "app-bundle", "system-link"])
def test_the_stub_resolves_to_the_selected_developer_git(mac, monkeypatch, selection):
    developer = mac / "Xcode.app" / "Contents" / "Developer"
    target = _exe(developer / "usr" / "bin" / "git")
    if selection == "environment":
        monkeypatch.setenv("DEVELOPER_DIR", str(developer))
    elif selection == "app-bundle":
        monkeypatch.setenv("DEVELOPER_DIR", str(mac / "Xcode.app"))
    elif selection == "system-link":
        (mac / "xcode_select_link").symlink_to(developer, target_is_directory=True)
    assert gitbin.git() == str(target.resolve())


def test_without_an_explicit_selection_xcode_select_decides(mac, monkeypatch):
    """xcode-select's default search (no DEVELOPER_DIR, no link) is asked, not reproduced."""
    assert gitbin.git() == "git"  # it gave no answer
    developer = mac / "Default" / "Developer"
    target = _exe(developer / "usr" / "bin" / "git")
    monkeypatch.setattr(gitbin, "_default_developer", lambda: str(developer))
    assert gitbin.git() == str(target.resolve())
    monkeypatch.setattr(gitbin, "_default_developer", lambda: "relative/Developer")
    assert gitbin.git() == "git"


def test_xcode_select_output_is_used_only_when_it_is_one_absolute_path(monkeypatch):
    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, fake.out, "")
    monkeypatch.setattr(gitbin.subprocess, "run", fake)
    for out, want in (("/Library/Developer/CommandLineTools\n", "/Library/Developer/CommandLineTools"),
                      ("relative\n", None), ("/a\n/b\n", None), ("", None)):
        fake.out = out
        gitbin._default_developer.cache_clear()
        assert gitbin._default_developer() == want
    assert calls[0] == [gitbin._XCODE_SELECT, "-p"]
    gitbin._default_developer.cache_clear()


def test_an_explicit_selection_never_falls_back_to_another_developer_dir(mac, monkeypatch):
    (mac / "xcode_select_link").symlink_to(_exe(mac / "Linked" / "usr" / "bin" / "git").parents[2])
    monkeypatch.setenv("DEVELOPER_DIR", str(mac / "missing"))
    assert gitbin.git() == "git"
    monkeypatch.setenv("DEVELOPER_DIR", "relative/Developer")
    assert gitbin.git() == "git"


def test_a_broken_link_missing_or_non_executable_git_falls_back(mac):
    (mac / "xcode_select_link").symlink_to(mac / "gone", target_is_directory=True)
    assert gitbin.git() == "git"  # a broken selection is not replaced by anything
    (mac / "xcode_select_link").unlink()
    developer = mac / "Dev"
    target = _exe(developer / "usr" / "bin" / "git")
    (mac / "xcode_select_link").symlink_to(developer, target_is_directory=True)
    assert gitbin.git() == str(target.resolve())
    target.chmod(0o644)
    assert gitbin.git() == "git"
    target.unlink()
    assert gitbin.git() == "git"


def test_another_git_first_on_path_is_left_to_path(mac, monkeypatch):
    (mac / "xcode_select_link").symlink_to(_exe(mac / "Dev" / "usr" / "bin" / "git").parents[2])
    brew = _exe(mac / "brew" / "git")
    monkeypatch.setenv("PATH", f"{brew.parent}:{mac / 'usr-bin'}")
    assert gitbin.git() == "git"


def test_no_git_on_path_is_left_to_path(mac, monkeypatch):
    monkeypatch.setenv("PATH", str(mac / "empty"))
    assert gitbin.git() == "git"


def test_the_resolved_git_runs_on_this_host():
    out = subprocess.run([gitbin.git(), "--version"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.startswith("git version")


def test_every_git_command_in_the_package_goes_through_gitbin():
    """A literal `["git", ...]` argv (inline or in a variable, any subprocess function) would pay the stub's lookup
    again on macOS; so would a shell string starting with git."""
    root = Path(__file__).resolve().parents[1] / "src" / "repo_ai"
    found = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) > 1 and isinstance(node.elts[0], ast.Constant)
                    and node.elts[0].value == "git"):
                found.append(f"{path.relative_to(root)}:{node.lineno}")
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") in {"run", "Popen", "call", "check_call",
                                                                                  "check_output", "getoutput"}
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and node.args[0].value.lstrip().startswith("git ")):
                found.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not found, found
