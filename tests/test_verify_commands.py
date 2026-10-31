"""How `verify` establishes the test command without configuration: script
and wrapper resolution, lint steps, src layouts, unittest discovery. Static
rules only; every rule applied is recorded on the runner."""

from __future__ import annotations

import json
from pathlib import Path

from repo_ai.verify.commands import _src_layout, _widen_unittest
from repo_ai.verify.runner import parse_command, resolve


def _write(root: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return sorted(files)


def _pkg(root: Path, scripts: dict[str, str]) -> None:
    (root / "package.json").write_text(json.dumps({"name": "x", "scripts": scripts}))


def test_package_manager_scripts_resolve_any_script_name(tmp_path: Path):
    _pkg(tmp_path, {"test:unit": "node --test", "test": "npm run test:unit"})
    for cmd in ("npm run test:unit", "npm test", "pnpm run test", "pnpm test", "yarn test", "yarn test:unit",
                "bun run test"):
        r = resolve(tmp_path, cmd)
        assert r.kind == "node", cmd
        assert r.command == cmd and r.notes[0].startswith(f"`{cmd}` runs")
    assert resolve(tmp_path, "bun test").kind == "opaque"  # bun's own runner, not the script


def test_lint_and_type_steps_are_named_and_skipped_but_build_steps_keep_it_opaque(tmp_path: Path):
    _pkg(tmp_path, {"lint": "eslint .", "prelint": "tsc --noEmit", "test": "npm run lint && node --test test/",
                    "types": "tstyche", "both": "node --test && npm run types",
                    "built": "npm run build && node --test", "build": "rollup -c"})
    r = resolve(tmp_path, "npm test")
    assert r.kind == "node" and r.paths == ["test/"]
    assert any("`npm run lint` is a lint/type check" in n for n in r.notes)
    assert resolve(tmp_path, "npm run both").kind == "node"
    assert resolve(tmp_path, "npm run built").kind == "opaque"  # the tests may need the build
    assert resolve(tmp_path, "npm run lint").kind == "opaque"   # a check alone is not a test suite


def test_a_pre_script_that_is_not_a_check_keeps_the_command_opaque(tmp_path: Path):
    _pkg(tmp_path, {"pretest": "node scripts/generate.js", "test": "node --test"})
    assert resolve(tmp_path, "npm test").kind == "opaque"
    _pkg(tmp_path, {"pretest": "eslint . && tsc --noEmit", "test": "node --test"})
    r = resolve(tmp_path, "npm test")
    assert r.kind == "node" and any("`pretest`" in n for n in r.notes)


def test_coverage_wrappers_and_thresholds_are_not_applied_per_file(tmp_path: Path):
    _pkg(tmp_path, {"t1": "c8 --check-coverage --lines 100 node --test",
                    "t2": "node --test --experimental-test-coverage --test-coverage-lines=100 test/"})
    r1 = resolve(tmp_path, "npm run t1")
    assert r1.kind == "node" and r1.file_argv("test/a.test.js") == ["node", "--test", "test/a.test.js"]
    r2 = resolve(tmp_path, "npm run t2")
    assert r2.file_argv("test/a.test.js") == ["node", "--test", "test/a.test.js"]
    assert any("coverage thresholds" in n for n in r2.notes)
    r3 = resolve(tmp_path, "coverage run --source=pkg -m unittest discover -s tests -t .")
    assert r3.kind == "unittest" and r3.start == "tests"


def test_makefile_recipes_whose_other_lines_report_coverage(tmp_path: Path):
    (tmp_path / "Makefile").write_text("test:\n\tcoverage run --source=m -m unittest discover tests\n"
                                       "\tcoverage report --show-missing\n\n"
                                       "build:\n\tpython setup.py build\n\tpython -m unittest\n")
    r = resolve(tmp_path, "make test")
    assert r.kind == "unittest" and r.start == "tests"
    assert resolve(tmp_path, "make build").kind == "opaque"


def test_shell_operators_other_than_and_stay_opaque(tmp_path: Path):
    _pkg(tmp_path, {"a": "node --test || true", "b": "node --test; echo done", "c": "node --test | tee log"})
    assert {resolve(tmp_path, f"npm run {s}").kind for s in "abc"} == {"opaque"}


def test_runner_options_survive_per_file_runs_and_values_are_not_paths():
    r = parse_command("node --import tsx --test 'test/**/*.test.ts'")
    assert r.paths == ["test/**/*.test.ts"]
    assert r.file_argv("test/a.test.ts") == ["node", "--import", "tsx", "--test", "test/a.test.ts"]
    p = parse_command('pytest -m "not slow" --cov=pkg -n 4 -x -p no:randomly tests')
    assert p.paths == ["tests"]
    assert p.file_argv("tests/test_a.py")[-5:] == ["-m", "not slow", "-p", "no:randomly", "tests/test_a.py"]
    assert "--cov=pkg" not in p.file_argv("tests/test_a.py") and "-n" not in p.file_argv("tests/test_a.py")


def test_src_layout_sets_pythonpath_only_when_the_tests_import_a_src_only_package(tmp_path: Path):
    files = _write(tmp_path, {"src/pkg/__init__.py": "", "tests/__init__.py": "",
                              "tests/test_a.py": "import unittest\nfrom pkg import x\n"})
    r = resolve(tmp_path, "python -m unittest discover -s tests -t .")
    _src_layout(tmp_path, r, files)
    assert r.env == {"PYTHONPATH": "src"} and "PYTHONPATH=src" in r.notes[-1]
    # a package that also exists at the root is not src-only: nothing changes
    files2 = _write(tmp_path / "b", {"src/pkg/__init__.py": "", "pkg/__init__.py": "", "tests/test_a.py": "import pkg\n"})
    r2 = resolve(tmp_path / "b", "python -m unittest discover -s tests -t .")
    _src_layout(tmp_path / "b", r2, files2)
    assert r2.env == {}


def test_inferred_unittest_discovery_widens_to_every_file_with_testcase_tests(tmp_path: Path):
    files = _write(tmp_path, {
        "pkg/__init__.py": "", "pkg/a/__init__.py": "", "pkg/a/tests/__init__.py": "",
        "pkg/a/tests/test_one.py": "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n",
        "pkg/b/__init__.py": "", "pkg/b/tests/__init__.py": "",
        "pkg/b/tests/test_two.py": "from pkg.a.tests.base import Base\nclass U(Base):\n    def test_y(self): pass\n",
        "pkg/a/tests/base.py": "import unittest\nclass Base(unittest.TestCase):\n    pass\n",
        "pkg/b/tests/helpers.py": "def helper(): pass\n"})
    r = resolve(tmp_path, "python -m unittest discover -s pkg/a/tests -t .")
    _widen_unittest(tmp_path, r, files)
    assert (r.start, r.pattern) == ("pkg", "test*.py")
    assert set(r.test_files(files)) == {"pkg/a/tests/test_one.py", "pkg/b/tests/test_two.py"}
    assert "widened" in r.notes[-1]


def test_unittest_pattern_follows_the_test_files_naming(tmp_path: Path):
    files = _write(tmp_path, {
        "tests/__init__.py": "", "tests/base.py": "import unittest\nclass B(unittest.TestCase):\n    pass\n",
        "tests/models.py": "from tests.base import B\nclass M(B):\n    def test_m(self): pass\n",
        "tests/queries.py": "from tests.base import B\nclass Q(B):\n    def test_q(self): pass\n"})
    r = resolve(tmp_path, "python -m unittest discover -s tests -t .")
    _widen_unittest(tmp_path, r, files)
    assert r.pattern == "*.py" and {"tests/models.py", "tests/queries.py"} <= set(r.test_files(files))


def test_repo_ai_init_adding_its_own_gitignore_block_is_not_a_behavioural_change():
    from repo_ai.verify.changes import _describe
    block = b"# >>> repo-ai managed >>>\n# state\n.repo-ai/state/\n# <<< repo-ai managed <<<\n"
    cf = _describe(".gitignore", b"*.pyc\n", b"*.pyc\n\n" + block, "modified")
    assert cf.behavioral is False
    other = _describe(".gitignore", b"*.pyc\n", b"*.pyc\nfixtures/\n" + block, "modified")
    assert other.behavioral is True  # a project rule changed too


def test_makefile_variables_defined_through_other_variables_expand(tmp_path: Path):
    # post-hoc (held-out-4: colorama): `python=$(virtualenv)/bin/python`
    (tmp_path / "Makefile").write_text("virtualenv=~/.venvs/x\npython=$(virtualenv)/bin/python\n\n"
                                       "test:\n\t$(python) -m unittest discover -p *_test.py\n")
    r = resolve(tmp_path, "make test")
    assert r.kind == "unittest" and r.pattern == "*_test.py"
    assert r.full[:3] == ["python", "-m", "unittest"]  # the sandbox's interpreter, never the path
    (tmp_path / "Makefile").write_text("a=$(b)\nb=$(a)\n\ntest:\n\t$(a) -m pytest\n")
    assert resolve(tmp_path, "make test").kind == "opaque"  # a cycle never expands


def test_a_single_tox_command_is_a_declaration(tmp_path: Path):
    # post-hoc (held-out-4: jmespath.py): `commands = python -m pytest tests` in tox.ini
    from repo_ai.verify.commands import _tox_command
    (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py312\n\n[testenv]\ncommands = python -m pytest tests {posargs}\n"
                                      "deps =\n    pytest\n")
    assert _tox_command(tmp_path) == "python -m pytest tests"
    (tmp_path / "tox.ini").write_text("[testenv]\ncommands =\n    pytest\n    coverage report\n")
    assert _tox_command(tmp_path) == ""  # several commands: not a single test invocation
    (tmp_path / "tox.ini").write_text("[testenv]\ncommands = pytest {envsitepackagesdir}\n")
    assert _tox_command(tmp_path) == ""  # tox substitutions are never guessed


def test_a_tox_pytest_command_is_taken_only_when_the_tests_need_pytest(tmp_path: Path):
    from repo_ai.verify.commands import _imports_pytest
    _write(tmp_path, {"tests/test_a.py": "import unittest\n", "tests/test_b.py": "import pytest\n"})
    assert _imports_pytest(tmp_path, ["tests/test_b.py"]) and not _imports_pytest(tmp_path, ["tests/test_a.py"])


def test_unittest_with_only_options_is_discovery(tmp_path: Path):
    """speed-v1, more-itertools: `make test` runs `python -m unittest -v`. It was read as an empty module list and
    left opaque, so verify fell back to `make check` (black, flake8, mypy, then the tests) and reported a passing
    suite as `full-suite-failed` when black was missing."""
    for cmd in ("python -m unittest -v", "python -m unittest -q -f", "python -m unittest -k first -v",
                "python3 -m unittest --locals"):
        r = resolve(tmp_path, cmd)
        assert r.kind == "unittest" and r.per_file and not r.modules and r.start == ".", cmd
    r = resolve(tmp_path, "python -m unittest -v discover -s tests -t .")
    assert r.kind == "unittest" and r.start == "tests" and r.top == "."
    r = resolve(tmp_path, "python -m unittest -v tests.test_more")
    assert r.kind == "unittest" and r.modules == ["tests.test_more"]


def test_a_make_target_running_unittest_with_options_is_split_per_file(tmp_path: Path):
    (tmp_path / "Makefile").write_text("check:\n\tblack --check .\n\tpython -m unittest -v\n\n"
                                       "test:\n\tpython -m unittest -v\n")
    assert resolve(tmp_path, "make test").per_file
    assert not resolve(tmp_path, "make check").per_file  # several steps: still the full suite only
