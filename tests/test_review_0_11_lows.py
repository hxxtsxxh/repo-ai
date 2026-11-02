"""Low findings from the v0.11.3...v0.11.7 security review (C18), each with benign inputs only: no attack-like
fixture is written or scanned here (those tests stay in the CI-only security-fixture modules)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from repo_ai import firewall
from repo_ai.verify import isolate, pytestcfg

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


@pytest.mark.parametrize("pyproject", [
    'tool = "x"\n',
    '[tool]\nsetuptools_scm = "x"\n',
    '[tool]\nhatch = 1\n',
    '[tool.hatch]\nbuild = []\n',
    '[tool.hatch.build]\nhooks = "vcs"\n',
    '[tool.hatch.build.hooks]\nvcs = true\n',
])
def test_a_non_table_tool_value_declares_no_version_file(tmp_path, pyproject):
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    assert isolate.generated_version_files(tmp_path) == []


def test_an_over_long_norecursedirs_pattern_gives_no_note(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("")
    long = "a" * (pytestcfg.MAX_PATTERN_CHARS + 1)
    (tmp_path / "pyproject.toml").write_text(f'[tool.pytest.ini_options]\nnorecursedirs = "{long} tests"\n')
    assert pytestcfg.skipped_by_config(tmp_path, ["tests/test_a.py"])[2] == {}
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\nnorecursedirs = "tests"\n')
    assert pytestcfg.skipped_by_config(tmp_path, ["tests/test_a.py"])[2] == {"norecursedirs tests": ["tests/test_a.py"]}


@pytest.mark.parametrize("path,text,executed,doc", [
    ("LICENSE", "MIT License\n", False, True),
    ("NOTICE", "Copyright\n", False, True),
    ("copying", "GPL\n", False, True),
    ("scripts/notice", "echo hi\n", False, False),  # not at the skill root
    ("sub/LICENSE", "MIT License\n", False, False),
    ("NOTICE", "#!/usr/bin/env python3\nprint(1)\n", False, False),  # a script
    ("NOTICE", "\ufeff#!/bin/sh\necho hi\n", False, False),  # a script after a byte-order mark
    ("LICENSE", "MIT License\n", True, False),  # a hook or installer runs it (pluginvet)
])
def test_licence_files_are_documentation_only_at_the_root_and_when_not_a_script(path, text, executed, doc):
    assert firewall._licence_doc(path, text, executed=executed) is doc
    assert ("prose" in firewall.line_contexts(path, text, executed=executed)) is doc


def test_coding_lab_reads_changes_with_the_git_dir_from_before_the_run(tmp_path):
    """The agent can write its workspace's .git; the host's git reads the copy taken before the run. Shown with a
    harmless setting: an excludes file the workspace config names (hiding every new file) is not read."""
    import shutil
    import subprocess

    from repo_ai import coding_lab
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x = 1\n")
    git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=ws, check=True)
    subprocess.run([*git, "add", "-A"], cwd=ws, check=True)
    subprocess.run([*git, "commit", "-qm", "base"], cwd=ws, check=True)
    pristine = tmp_path / "git-copy"
    shutil.copytree(ws / ".git", pristine, symlinks=True)
    (tmp_path / "exclude-all").write_text("*\n")
    subprocess.run(["git", "config", "core.excludesFile", str(tmp_path / "exclude-all")], cwd=ws, check=True)
    (ws / "a.py").write_text("x = 2\n")
    (ws / "new.py").write_text("y = 1\n")
    changed, untracked = coding_lab._workspace_changes(ws, pristine)
    assert changed == ["a.py"] and untracked == ["new.py"]


@pytest.mark.parametrize("name", ["diagnose.yml", "journey.yml", "speed.yml"])
def test_these_workflows_do_not_persist_the_checkout_token(name):
    text = (WORKFLOWS / name).read_text()
    checkouts = re.findall(r"- uses: actions/checkout@v4\n((?: {8,}.*\n)*)", text)
    assert checkouts and all("persist-credentials: false" in c for c in checkouts)
