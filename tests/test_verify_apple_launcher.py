"""Apple's system launcher must resolve without opening the Xcode bundle."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import _git
from repo_ai import __version__, gitbin
from repo_ai.verify import cache, evidence, execute

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX Apple launcher paths")


def _runtime(developer: Path) -> Path:
    target = developer / "usr" / "bin" / "python3"
    target.parent.mkdir(parents=True)
    target.write_text("must never execute during selection\n")
    target.chmod(0o755)
    return target


@pytest.fixture()
def layout(tmp_path, monkeypatch):
    monkeypatch.setattr(execute.sys, "platform", "darwin")
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    link = tmp_path / "xcode_select_link"
    clt = tmp_path / "CommandLineTools"
    monkeypatch.setattr(execute, "_APPLE_DEVELOPER_LINK", link, raising=False)
    monkeypatch.setattr(execute, "_APPLE_CLT_ROOT", clt, raising=False)
    actual_run = subprocess.run

    def no_interpreter_or_selection_probe(args, **kwargs):
        assert args[0] in {"git", gitbin.git()}, f"selection executed a program: {args}"
        return actual_run(args, **kwargs)

    monkeypatch.setattr(execute.subprocess, "run", no_interpreter_or_selection_probe)
    return link, clt


@pytest.mark.parametrize("selection", ["environment", "app-root", "system-link", "default-clt"])
def test_system_launcher_resolves_statically(tmp_path, monkeypatch, layout, selection):
    link, clt = layout
    app = tmp_path / "Xcode.app"
    developer = clt if selection == "default-clt" else app / "Contents" / "Developer"
    target = _runtime(developer)
    if selection == "environment":
        monkeypatch.setenv("DEVELOPER_DIR", str(developer))
    elif selection == "app-root":
        monkeypatch.setenv("DEVELOPER_DIR", str(app))
    elif selection == "system-link":
        link.symlink_to(developer, target_is_directory=True)
    assert execute._real_executable("/usr/bin/python3") == str(target.resolve())


@pytest.mark.parametrize("selection", ["missing-environment", "relative-environment", "broken-link"])
def test_invalid_explicit_selection_does_not_fall_back(tmp_path, monkeypatch, layout, selection):
    link, clt = layout
    _runtime(clt)
    if selection == "broken-link":
        link.symlink_to(tmp_path / "missing", target_is_directory=True)
    else:
        value = "relative-sdk" if selection == "relative-environment" else str(tmp_path / "missing")
        monkeypatch.setenv("DEVELOPER_DIR", value)
    assert execute._real_executable("/usr/bin/python3") is None


@pytest.mark.parametrize("kind", ["directory", "loop", "launcher-self-reference"])
def test_unusable_runtime_is_refused(tmp_path, monkeypatch, layout, kind):
    developer = tmp_path / "Developer"
    target = developer / "usr" / "bin" / "python3"
    target.parent.mkdir(parents=True)
    if kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(target if kind == "loop" else "/usr/bin/python3")
    monkeypatch.setenv("DEVELOPER_DIR", str(developer))
    assert execute._real_executable("/usr/bin/python3") is None


def test_virtualenv_and_non_darwin_paths_are_preserved(tmp_path, monkeypatch, layout):
    path = tmp_path / "venv" / "bin" / "python"
    path.parent.mkdir(parents=True)
    path.symlink_to("/usr/bin/python3")
    assert execute._real_executable(str(path)) == str(path)
    monkeypatch.setattr(execute.sys, "platform", "linux")
    assert execute._real_executable("/usr/bin/python3") == "/usr/bin/python3"


def test_launcher_self_reference_uses_canonical_identity(tmp_path, monkeypatch, layout):
    developer = tmp_path / "Developer"
    target = _runtime(developer)
    canonical_launcher = tmp_path / "python3.13"
    canonical_launcher.write_text("system launcher target\n")
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path in {target, Path("/usr/bin/python3")}:
            return canonical_launcher
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setenv("DEVELOPER_DIR", str(developer))
    assert execute._real_executable("/usr/bin/python3") is None


def test_environment_selection_precedes_active_system_selection(tmp_path, monkeypatch, layout):
    link, _ = layout
    active = tmp_path / "active"
    override = tmp_path / "override"
    _runtime(active)
    selected = _runtime(override)
    link.symlink_to(active, target_is_directory=True)
    monkeypatch.setenv("DEVELOPER_DIR", str(override))
    assert execute._real_executable("/usr/bin/python3") == str(selected.resolve())


def test_switching_xcode_selection_makes_evidence_stale_without_execution(tmp_path, monkeypatch, layout):
    link, _ = layout
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    first = _runtime(tmp_path / "Xcode-one" / "Developer")
    second = _runtime(tmp_path / "Xcode-two" / "Developer")
    link.symlink_to(first.parents[2], target_is_directory=True)
    monkeypatch.setattr(execute.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)
    selected = execute.interpreter(root, probe=False)
    assert selected is not None and selected.python == str(first.resolve())
    ex = SimpleNamespace(python=selected.python, node="", site_dirs=[], links={}, is_container=False)
    record = {"repo_ai_version": __version__, "environment_static": cache.static_environment(ex, SimpleNamespace(kind="pytest")),
              "plan": {"runner": {"kind": "pytest"}}}
    assert evidence.environment_check(record, root)[0] == "unchanged"
    link.unlink()
    link.symlink_to(second.parents[2], target_is_directory=True)
    current, reason = evidence.environment_check(record, root)
    assert current == "changed" and "selected interpreter changed" in reason


@pytest.mark.parametrize("tracked", [False, True])
@pytest.mark.parametrize("via_link", [False, True])
def test_repository_owned_runtime_is_never_probed(tmp_path, monkeypatch, layout, tracked, via_link):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    target = _runtime(root / "sdk")
    if tracked:
        _git(root, "add", "sdk")
        monkeypatch.setattr(execute, "static_venv", lambda path: pytest.fail("tracked target admitted to static layout"))
    developer = root / "sdk"
    if via_link:
        developer = tmp_path / "outside-sdk"
        alias = developer / "usr" / "bin" / "python3"
        alias.parent.mkdir(parents=True)
        alias.symlink_to(target)
    monkeypatch.setenv("DEVELOPER_DIR", str(developer))
    monkeypatch.setattr(execute.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None)
    selected = execute.interpreter(root)
    assert selected is None
    assert target.read_text() == "must never execute during selection\n"
