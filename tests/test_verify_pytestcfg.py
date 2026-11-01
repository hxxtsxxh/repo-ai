"""verify/pytestcfg: name-matched test files a full pytest run would not collect, read from the configuration file
pytest itself would use. For a note only: nothing is removed on this reading."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repo_ai.verify import pytestcfg

FILES = ["tests/test_ok.py", "tests/mypy_test_cases/test_case.py", "docs/test_doc.py", "build/test_gen.py",
         "pkg/sub/tests/test_inner.py"]


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_norecursedirs_path_and_basename_patterns(tmp_path):
    root = _project(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = ".git docs tests/mypy_test_cases"\n'})
    cfg, skipped = pytestcfg.skipped_by_config(root, FILES)
    assert cfg == "pyproject.toml"
    assert skipped == {"norecursedirs docs": ["docs/test_doc.py"],
                       "norecursedirs tests/mypy_test_cases": ["tests/mypy_test_cases/test_case.py"]}


def test_testpaths_and_list_values(tmp_path):
    root = _project(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\nnorecursedirs = ["build"]\n'})
    _, skipped = pytestcfg.skipped_by_config(root, FILES)
    assert skipped["outside testpaths tests"] == ["docs/test_doc.py", "build/test_gen.py", "pkg/sub/tests/test_inner.py"]
    assert skipped["norecursedirs build"] == ["build/test_gen.py"]


def test_pytest_picks_the_first_configuration_file_in_its_order(tmp_path):
    # pytest.ini wins over pyproject.toml; a tox.ini or setup.cfg without a pytest section is not the file
    root = _project(tmp_path, {"pytest.ini": "[pytest]\nnorecursedirs = build\n",
                               "pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = "docs"\n',
                               "tox.ini": "[tox]\nenvlist = py3\n"})
    cfg, skipped = pytestcfg.skipped_by_config(root, FILES)
    assert cfg == "pytest.ini" and list(skipped) == ["norecursedirs build"]
    (root / "pytest.ini").unlink()
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")  # no pytest table: not the file
    (root / "setup.cfg").write_text("[tool:pytest]\nnorecursedirs = docs\n")
    cfg, skipped = pytestcfg.skipped_by_config(root, FILES)
    assert cfg == "setup.cfg" and list(skipped) == ["norecursedirs docs"]


def test_the_runner_directory_is_where_the_search_starts(tmp_path):
    root = _project(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = "docs"\n',
                               "sub/pytest.ini": "[pytest]\nnorecursedirs = build\n"})
    cfg, skipped = pytestcfg.skipped_by_config(root, ["sub/build/test_x.py", "sub/docs/test_y.py"], start="sub")
    assert cfg == "sub/pytest.ini" and skipped == {"norecursedirs build": ["sub/build/test_x.py"]}


def test_nothing_configured_or_unreadable_means_no_note(tmp_path):
    assert pytestcfg.skipped_by_config(tmp_path, FILES) == ("", {})
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options\nbroken")
    assert pytestcfg.skipped_by_config(tmp_path, FILES) == ("", {})
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "-q"\n')
    assert pytestcfg.skipped_by_config(tmp_path, FILES) == ("pyproject.toml", {})


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_linked_configuration_file_is_not_read_and_stops_the_search(tmp_path):
    real = tmp_path / "elsewhere.ini"
    real.write_text("[pytest]\nnorecursedirs = docs\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pytest.ini").symlink_to(real)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\nnorecursedirs = "build"\n')
    assert pytestcfg.skipped_by_config(root, FILES) == ("", {})  # not the pyproject.toml pytest would not use
