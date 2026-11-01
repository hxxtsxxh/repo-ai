"""verify/pytestcfg: name-matched test files that pytest's `norecursedirs` keeps out of a full run, read from the
configuration file pytest itself would use (pytest 9's order). For a note only: nothing is removed on this reading,
and anything uncertain (a parse error, a linked file, a command choosing its own configuration) gives no note."""
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


def skipped(root, files=FILES, **kw):
    return pytestcfg.skipped_by_config(root, files, **kw)


def test_norecursedirs_path_and_basename_patterns(tmp_path):
    root = _project(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = ".git docs tests/mypy_test_cases"\n'
                                                 'testpaths = ["tests"]\n'})
    cfg, other, found = skipped(root)
    assert cfg == "pyproject.toml" and other == ["testpaths"]
    assert found == {"norecursedirs docs": ["docs/test_doc.py"],
                     "norecursedirs tests/mypy_test_cases": ["tests/mypy_test_cases/test_case.py"]}


def test_list_values_and_native_tool_pytest(tmp_path):
    root = _project(tmp_path, {"pyproject.toml": '[tool.pytest]\nnorecursedirs = ["build"]\n'})
    assert skipped(root)[2] == {"norecursedirs build": ["build/test_gen.py"]}
    (root / "pyproject.toml").write_text("[tool.pytest]\n")  # empty: pytest looks further, finds nothing
    assert skipped(root) == ("", [], {})


def test_pytest_9_candidate_order(tmp_path):
    root = _project(tmp_path, {"pytest.toml": '[pytest]\nnorecursedirs = ["docs"]\n',
                               "pytest.ini": "[pytest]\nnorecursedirs = build\n",
                               "tox.ini": "[tox]\nenvlist = py3\n"})
    cfg, _, found = skipped(root)
    assert cfg == "pytest.toml" and list(found) == ["norecursedirs docs"]
    (root / "pytest.toml").unlink()
    cfg, _, found = skipped(root)
    assert cfg == "pytest.ini" and list(found) == ["norecursedirs build"]
    (root / "pytest.ini").unlink()
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")  # no pytest table, and tox.ini has no [pytest]
    (root / "setup.cfg").write_text("[tool:pytest]\nnorecursedirs = docs\n")
    cfg, _, found = skipped(root)
    assert cfg == "setup.cfg" and list(found) == ["norecursedirs docs"]


def test_ini_keys_are_case_sensitive_and_default_is_not_merged(tmp_path):
    root = _project(tmp_path, {"pytest.ini": "[DEFAULT]\nnorecursedirs = docs\n[pytest]\nNoRecurseDirs = build\n"
                                             "addopts = -q 100%\n"})
    cfg, other, found = skipped(root)
    assert cfg == "pytest.ini" and found == {} and other == ["addopts"]


def test_the_runner_directory_is_where_the_search_starts(tmp_path):
    root = _project(tmp_path, {"pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = "docs"\n',
                               "sub/pytest.ini": "[pytest]\nnorecursedirs = build\n"})
    cfg, _, found = skipped(root, ["sub/build/test_x.py", "sub/docs/test_y.py"], start="sub")
    assert cfg == "sub/pytest.ini" and found == {"norecursedirs build": ["sub/build/test_x.py"]}


def test_never_applied_to_the_paths_pytest_starts_from_or_their_parents(tmp_path):
    root = _project(tmp_path, {"pytest.ini": "[pytest]\nnorecursedirs = build tests\n"})
    files = ["build/tests/test_a.py", "build/tests/build/test_b.py"]
    assert skipped(root, files, paths=["build/tests"])[2] == {"norecursedirs build": ["build/tests/build/test_b.py"]}
    assert skipped(root, ["tests/test_c.py"], start="tests")[2] == {}


def test_a_command_choosing_its_configuration_gives_no_note(tmp_path):
    root = _project(tmp_path, {"pytest.ini": "[pytest]\nnorecursedirs = docs\n"})
    assert skipped(root)[2]
    for argv in (["-c", "ci.ini"], ["--config-file=ci.ini"], ["-o", "norecursedirs=x"], ["-onorecursedirs=x"],
                 ["--rootdir", "sub"], ["--pyargs", "pkg"], ["--override-ini=testpaths=x"]):
        assert skipped(root, argv=["python", "-m", "pytest", *argv]) == ("", [], {}), argv


def test_unreadable_configurations_give_no_note_and_stop_the_search(tmp_path):
    root = _project(tmp_path, {"pytest.ini": "[pytest\nbroken", "setup.cfg": "[tool:pytest]\nnorecursedirs = docs\n"})
    assert skipped(root) == ("", [], {})  # pytest would stop at the broken pytest.ini too
    (root / "pytest.ini").unlink()
    (root / "pytest.toml").write_text("a = " + "[" * 200_000)  # deep nesting: RecursionError in tomllib
    assert skipped(root) == ("", [], {})
    (root / "pytest.toml").write_text("[pytest]\nnorecursedirs = [" + ", ".join(f'"d{i}"' for i in range(300)) + "]\n")
    assert skipped(root) == ("", [], {})  # more patterns than the cap
    (root / "pytest.toml").write_text("[pytest]\nnorecursedirs = 5\n")  # not a string or list
    assert skipped(root) == ("", [], {})


def test_nothing_configured_means_no_note(tmp_path):
    assert skipped(tmp_path) == ("", [], {})
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "-q"\n')
    assert skipped(tmp_path) == ("pyproject.toml", ["addopts"], {})


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_linked_configuration_file_is_not_read_and_stops_the_search(tmp_path):
    real = tmp_path / "elsewhere.ini"
    real.write_text("[pytest]\nnorecursedirs = docs\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pytest.ini").symlink_to(real)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\nnorecursedirs = "build"\n')
    assert skipped(root) == ("", [], {})  # not the pyproject.toml pytest would not use
