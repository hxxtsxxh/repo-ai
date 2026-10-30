# Vendored from Session A's red team (PR #24, comments 6401610438 and 6402441378;
# scratchpad/redteam/v7fa), unchanged except the helper import and two lint fixes. Each test asserts the safe result.
"""Red-team probes on 7fa342d's declared `--subject` globs and the oracle. Each asserts the SAFE
result.

G1-G3  V1-V3 (../test_redteam_variants.py) with a declared package glob `--subject 'mypkg/*'`: the
       candidate fixes nothing and only edits the fixture module the scenario's input comes from
G4     a helper with a function, in the code package, imported directly by the scenario (inferred and
       declared): the candidate only edits the helper's return value
G5     (should hold) `--subject '*'` that also matches tests/conftest.py, which the candidate edits
G6     (should hold) a glob that matches nothing
G7     (should hold) path traversal and absolute globs are refused at pin time
G8     (should hold) a case-only mismatch on macOS (`MyPkg/core.py` for `mypkg/core.py`)
G9     (should hold) the fix needs a new file the declared subject leaves out: fails closed
G10    (should hold) a subject file replaced by a symlink: dropped, fails closed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin, pin_and_run, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox backend to run tests in")

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
FIXTURE = "import pytest\n\n\n@pytest.fixture\ndef empty_input():\n    return {}\n"
SCENARIO = "from mypkg import mean\n\n\ndef test_empty(empty_input):\n    assert mean(empty_input) == 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
ACCEPT = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"


def _outside(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


def _not_supported(pp: dict, tag: str) -> None:
    assert pp["verdict"]["state"] != "supported", f"{tag}: the candidate fixes nothing, yet: {summary(pp)}"


def _oracle_case(tmp_path: Path, files: dict[str, str], fixture_path: str, *subject: str) -> dict:
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "tests/test_mean.py": EXISTING,
                                      fixture_path: FIXTURE.replace("{}", "[]"), **files})
    write(root, {fixture_path: FIXTURE.replace("{}", "[0]")})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, SCENARIO), *PT, *subject)
    print("SUMMARY", summary(pp))
    if pp.get("executed"):
        assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    return pp


def test_g1_addopts_plugin_with_a_declared_package_glob(tmp_path: Path):
    pp = _oracle_case(tmp_path, {"pytest.ini": "[pytest]\naddopts = -p mypkg.testing\n"}, "mypkg/testing.py",
                      "--subject", "mypkg/*")
    _not_supported(pp, "G1")


def test_g2_conftest_star_import_with_a_declared_package_glob(tmp_path: Path):
    pp = _oracle_case(tmp_path, {"conftest.py": "from mypkg.testing import *  # noqa\n"}, "mypkg/testing.py",
                      "--subject", "mypkg/*")
    _not_supported(pp, "G2")


def test_g3_nested_pytest_plugins_with_a_declared_package_glob(tmp_path: Path):
    pp = _oracle_case(tmp_path, {"conftest.py": 'pytest_plugins = ["mypkg.testing"]\n',
                                 "mypkg/testing.py": 'pytest_plugins = ["mypkg.fixtures"]\n'}, "mypkg/fixtures.py",
                      "--subject", "mypkg/*")
    _not_supported(pp, "G3")


@pytest.mark.parametrize("declared", [False, True])
def test_g4_a_helper_in_the_package_imported_by_the_scenario(tmp_path: Path, declared: bool):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": "def empty():\n    return []\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": "def empty():\n    return [0]\n"})  # no fix: only the scenario's input
    scen = "from mypkg import mean\nfrom mypkg.samples import empty\n\n\ndef test_empty():\n" \
           "    assert mean(empty()) == 0\n"
    extra = ("--subject", "mypkg/*") if declared else ()
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, *extra)
    print("SUMMARY", summary(pp))
    _not_supported(pp, f"G4 declared={declared}")


def test_g5_a_glob_that_matches_the_conftest(tmp_path: Path):
    pp = _oracle_case(tmp_path, {}, "tests/conftest.py", "--subject", "*")
    print("SUMMARY", summary(pp))
    _not_supported(pp, "G5")


def test_g6_a_glob_that_matches_nothing(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/__init__.py": FIXED})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "nothing/*.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] != "supported" and not pp.get("executed"), summary(pp)


@pytest.mark.parametrize("glob", ["../mypkg/*", "/etc/*", "mypkg/../../x.py", ".git/*"])
def test_g7_traversal_globs_are_refused(tmp_path: Path, glob: str):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "tests/test_mean.py": EXISTING})
    p = pin(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", glob)
    assert p.returncode != 0, f"G7: --subject {glob!r} was accepted: {p.stdout} {p.stderr}"


def test_g8_case_only_mismatch(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "MyPkg/core.py")
    print("SUMMARY", summary(pp))
    # either it matches nothing (refused), or it ran the real fix; never a proof about other bytes
    assert pp["verdict"]["state"] != "supported" or pp["subject"]["files"] == ["mypkg/core.py"], summary(pp)


def test_g9_a_new_file_the_declared_subject_leaves_out_fails_closed(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": "from ._util import EMPTY\n\n\ndef mean(xs):\n"
                                  "    return sum(xs) / len(xs) if xs else EMPTY\n",
                 "mypkg/_util.py": "EMPTY = 0\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_g10_a_subject_that_is_a_symlink_fails_closed(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"impl/core.py": FIXED})
    (root / "mypkg/core.py").unlink()
    os.symlink("../impl/core.py", root / "mypkg/core.py")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/*")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] != "supported" or pp["verdict"].get("level") != \
        "supported_by_controlled_comparison", summary(pp)


def test_g11_a_subject_of_more_than_200_files_is_not_silently_truncated(tmp_path: Path):
    """preflight keeps `subject[:200]` and run() injects only that list: files 201+ of a declared
    subject run with the base's versions at the candidate side, outside both the subject and the
    left-out handling. Here file 201+ (mypkg/zz.py, sorted last) puts the bug back."""
    files = {f"mypkg/a{i:03d}.py": "X = 1\n" for i in range(200)}
    root = make_repo(tmp_path / "r", {**files, "mypkg/__init__.py": "from ._core import mean\nfrom . import zz\n",
                                      "mypkg/_core.py": MEAN, "mypkg/zz.py": "def hook():\n    pass\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {**{k: "X = 2\n" for k in files}, "mypkg/_core.py": FIXED,
                 "mypkg/zz.py": "import mypkg\n\n\ndef _buggy(xs):\n    return sum(xs) / len(xs)\n\n\n"
                                "mypkg.mean = _buggy\n"})
    from sa_redteam_rt7 import shipped
    res = shipped(root, "from mypkg import mean; print('RESULT', mean([]))")
    assert "ZeroDivisionError" in res.stderr, (res.stdout, res.stderr[-300:])  # the shipped candidate is buggy
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/*")
    print("SUMMARY", summary(pp)[:600], "n_subject", len(pp["subject"]["files"]))
    assert pp["verdict"]["state"] != "supported", (
        f"G11: {len(pp['subject']['files'])} subject files recorded; mypkg/zz.py in it: "
        f"{'mypkg/zz.py' in pp['subject']['files']}; {summary(pp)[:400]}")


def test_g12_ai_agent_marks_an_agent_shell(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "tests/test_mean.py": EXISTING})
    import json
    import subprocess
    from sa_redteam_rt7 import AGENT_VARS, cli_env
    env = {k: v for k, v in cli_env().items() if k not in AGENT_VARS}
    env["AI_AGENT"] = "1"
    p = subprocess.run([sys.executable, "-m", "repo_ai", "prove", "pin", "c", "--claim", "x", "--scenario",
                        "tests/test_accept.py", "--file", str(_outside(tmp_path, ACCEPT)), *PT, "--json", "-C",
                        str(root)], capture_output=True, text=True, env=env, timeout=120, check=False)
    assert p.returncode == 0, p.stderr
    rec = json.loads(p.stdout)
    assert rec["pinned_by"]["agent_shell"] is True, rec["pinned_by"]
