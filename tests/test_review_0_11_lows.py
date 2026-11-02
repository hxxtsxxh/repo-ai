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


@pytest.mark.parametrize("path,text,run,doc", [
    ("LICENSE", "MIT License\n", frozenset(), True),
    ("NOTICE", "Copyright\n", frozenset(), True),
    ("copying", "GPL\n", frozenset(), True),
    ("scripts/notice", "echo hi\n", frozenset(), False),  # not at the skill root
    ("sub/LICENSE", "MIT License\n", frozenset(), False),
    ("NOTICE", "#!/usr/bin/env python3\nprint(1)\n", frozenset(), False),  # a script
    ("LICENSE", "MIT License\n", frozenset({"LICENSE"}), False),  # SKILL.md runs it
])
def test_licence_files_are_documentation_only_at_the_root_and_when_not_run(path, text, run, doc):
    assert firewall._licence_doc(path, text, run) is doc


@pytest.mark.parametrize("skill_md,names", [
    ("Run `bash NOTICE` first.", {"NOTICE"}),
    ("then ./LICENSE", {"LICENSE"}),
    ("python3 COPYING", {"COPYING"}),
    ("source ./notice", {"NOTICE"}),
    ("See LICENSE and NOTICE for terms.", set()),
    ("Licensed under the terms in the LICENSE file.", set()),
])
def test_run_names_finds_licence_files_handed_to_an_interpreter(skill_md, names):
    assert firewall.run_names(skill_md) == names


@pytest.mark.parametrize("name", ["diagnose.yml", "journey.yml", "speed.yml"])
def test_these_workflows_do_not_persist_the_checkout_token(name):
    text = (WORKFLOWS / name).read_text()
    checkouts = re.findall(r"- uses: actions/checkout@v4\n((?: {8,}.*\n)*)", text)
    assert checkouts and all("persist-credentials: false" in c for c in checkouts)
