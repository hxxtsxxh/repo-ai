"""The pytest universe follows pytest's own collection (held-out-5 marshmallow:
`norecursedirs` excludes `tests/mypy_test_cases`, which verify still ran, so
every passing change read "failing (all failures pre-existing at the base)").

Only pytest's recorded collection (from `--record`'s sandboxed full-suite
run) changes the universe, and only while every collection input is
unchanged; a static reading of the configuration never removes a file.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli

from test_verify_adaptive import _sandbox

pytestmark = pytest.mark.skipif(not _sandbox(), reason="no sandbox backend to run tests in")
CMD = "python -m pytest -q tests"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "p"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


MARSHMALLOW_SHAPE = {
    "pyproject.toml": '[tool.pytest.ini_options]\nnorecursedirs = ".git docs tests/mypy_test_cases"\n',
    "pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n",
    "tests/test_ok.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
    # type-checker fixtures, not tests: they fail when run, and pytest never runs them
    "tests/mypy_test_cases/test_case.py": "from pkg.core import f\n\n\ndef test_typed():\n    assert f() == 2\n",
}


def _plan(root: Path) -> dict:
    proc = run_cli(root, "verify", "--json", "--test-command", CMD)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _run(root: Path) -> dict:
    proc = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", CMD)
    assert proc.returncode in (0, 1), proc.stderr[-800:]
    return json.loads(proc.stdout)["evidence"]


def test_a_recorded_collection_leaves_out_what_pytest_itself_never_runs(tmp_path: Path):
    root = _project(tmp_path, MARSHMALLOW_SHAPE)
    (root / "pkg" / "core.py").write_text("def f():\n    return 2 - 1\n")  # a passing change
    before = _plan(root)
    assert any("configures which files pytest collects" in u for u in before["uncertainty"])
    assert _run(root)["verdict"] != "selected-passed (full suite not run)"  # the excluded file still runs
    assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    after = _plan(root)
    assert "tests/mypy_test_cases/test_case.py" in after["runner"]["excluded"]
    assert not any("configures which files pytest collects" in u for u in after["uncertainty"])
    ev = _run(root)
    assert ev["verdict"].startswith(("selected-passed", "selected-and-full-suite-passed")), ev["verdict"]


def test_a_changed_collection_configuration_drops_the_recorded_answer(tmp_path: Path):
    root = _project(tmp_path, MARSHMALLOW_SHAPE)
    assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    (root / "pyproject.toml").write_text(MARSHMALLOW_SHAPE["pyproject.toml"] + "# edited\n")
    plan = _plan(root)
    assert "tests/mypy_test_cases/test_case.py" not in plan["runner"]["excluded"]
    (root / "pyproject.toml").write_text(MARSHMALLOW_SHAPE["pyproject.toml"])
    (root / "tests" / "conftest.py").write_text("collect_ignore = []\n")  # a new conftest is an input too
    assert "tests/mypy_test_cases/test_case.py" not in _plan(root)["runner"]["excluded"]


def test_a_test_file_added_after_the_recording_is_never_left_out(tmp_path: Path):
    root = _project(tmp_path, MARSHMALLOW_SHAPE)
    assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    (root / "tests" / "mypy_test_cases" / "test_new.py").write_text("def test_n():\n    assert True\n")
    plan = _plan(root)
    assert "tests/mypy_test_cases/test_new.py" not in plan["runner"]["excluded"]
    assert "tests/mypy_test_cases/test_case.py" in plan["runner"]["excluded"]


def test_a_doctest_module_pytest_collects_is_run_and_its_importers_too(tmp_path: Path):
    root = _project(tmp_path, {
        "pyproject.toml": '[tool.pytest.ini_options]\naddopts = "--doctest-modules"\ntestpaths = ["pkg", "tests"]\n',
        "pkg/__init__.py": "",
        "pkg/mod.py": 'def double(x):\n    """\n    >>> double(2)\n    4\n    """\n    return x * 2\n',
        "tests/test_use.py": "from pkg.mod import double\n\n\ndef test_d():\n    assert double(0) == 0  # holds under the change: only the doctest catches it\n",
    })
    cmd = "python -m pytest -q"
    assert run_cli(root, "verify", "--record", "--test-command", cmd).returncode == 0
    (root / "pkg" / "mod.py").write_text('def double(x):\n    """\n    >>> double(2)\n    4\n    """\n    return x * 3\n')
    proc = run_cli(root, "verify", "--run", "--json", "--test-command", cmd)
    ev = json.loads(proc.stdout)["evidence"]
    ran = {r["test"] for r in ev["results"]}
    assert {"pkg/mod.py", "tests/test_use.py"} <= ran, ran
    assert ev["verdict"] == "regression", ev["verdict"]


def test_pytest_toml_is_a_collection_input(tmp_path: Path):
    """pytest 9 reads `pytest.toml`: dropping an exclusion there must drop the recorded answer."""
    files = {k: v for k, v in MARSHMALLOW_SHAPE.items() if k != "pyproject.toml"}
    files["pytest.toml"] = '[pytest]\nnorecursedirs = [".git", "docs", "tests/mypy_test_cases"]\n'
    root = _project(tmp_path, files)
    assert run_cli(root, "verify", "--record", "--test-command", CMD).returncode == 0
    (root / "pytest.toml").write_text('[pytest]\nnorecursedirs = [".git", "docs"]\n')
    plan = _plan(root)
    assert "tests/mypy_test_cases/test_case.py" not in plan["runner"]["excluded"]
    assert any(t.startswith("pytest.toml changed") for t in plan["triggers"]), plan["triggers"]


def test_an_incomplete_collection_report_is_never_used():
    """With xdist, workers forward only some collect reports: a file whose tests ran but which
    was not reported collected means the list is incomplete, and it must not shrink the universe."""
    from repo_ai.verify import engine, results
    att = results.Attribution(trusted=True, files={})
    att.modules = {"tests/test_c.py"}
    att.ended = {"tests/test_a.py": {"tests/test_a.py::test_a"}, "tests/test_c.py": {"x"}}
    assert engine.complete_collection(att) is False
    att.modules |= {"tests/test_a.py"}
    assert engine.complete_collection(att) is True
