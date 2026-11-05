# Vendored from Session A's red team (PR #24, comments 6401610438 and 6402441378;
# scratchpad/redteam/v7fa), unchanged except the helper import and two lint fixes. Each test asserts the safe result.
"""Red-team probes on 7fa342d's "base tree plus subject" redesign. Each test asserts the SAFE
result and so FAILS when ProofLab gives a false proof.

C0   control: a genuine fix with a declared subject is supported_by_controlled_comparison
C0i  control: a genuine fix, subject inferred, is supported at behavior_observed
S1   declared subject narrower than what the scenario imports: a left-out edit to the package
     __init__ re-breaks the fix in the shipped candidate
S2   inferred subject: the scenario imports mypkg.core; the change also edits mypkg/__init__.py
     (which Python runs first) to put the bug back. imports() never adds parent packages
S3   inferred subject: a module loaded with importlib.import_module(computed name) re-breaks it
S4   inferred subject: a "constants module" (Import + Assign only) that monkeypatches at import
S5   inferred subject: a data file the subject reads at runtime re-breaks it
S17  a regression in a left-out (non-subject) file, with the test that would catch it edited: the
     base's own test is re-run against the BASE version of the regressed file, so it is hidden
S16  (should hold) the same regression without the test edit: verify, on the full tree, catches it
Run: cd rv7fa && PYTHONPATH=$PWD/src python -m pytest -q test_redteam_7fa_subject.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox backend to run tests in")

BUGGY = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
ACCEPT = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"
ACCEPT_CORE = "from mypkg.core import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"
SHIPPED_CHECK = "import mypkg; r = mypkg.mean([]) if hasattr(mypkg, 'mean') else None; print('RESULT', r)"


def _outside(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


def _bug_still_shipped(root: Path, code: str = "from mypkg import mean; print('RESULT', mean([]))") -> None:
    """Fixture sanity: the candidate as the working tree ships it still has the bug."""
    res = shipped(root, code)
    assert "ZeroDivisionError" in res.stderr or "RESULT None" in res.stdout, (res.stdout, res.stderr[-400:])


def _no_false_proof(pp: dict, tag: str) -> None:
    rec = (pp.get("evidence") or [{}])[0]
    assert pp["verdict"]["state"] != "supported" and pp["verdict"].get("level") != \
        "supported_by_controlled_comparison", (
        f"{tag}: the shipped candidate still fails the pinned scenario, yet ProofLab says: {summary(pp)}")
    assert (rec.get("claim") or {}).get("level") != "supported_by_controlled_comparison" or \
        pp["verdict"]["state"] != "supported", f"{tag}: {summary(pp)}"


# ------------------------------------------------------------------ controls
def test_c0_control_genuine_fix_with_declared_subject(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": BUGGY,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] == "supported", summary(pp)
    assert pp["verdict"]["level"] == "supported_by_controlled_comparison", summary(pp)


@pytest.mark.xfail(strict=True, reason="by design since the corrective phase (Session B, 2026-10-25): an inferred subject "
                   "is chosen by the change itself, so a claim needs a declared subject (the eighth review's 19 false "
                   "proofs all had inferred subjects)")
def test_c0i_control_genuine_fix_inferred_subject(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": BUGGY,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT)
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] == "supported" and pp["verdict"]["level"] == "behavior_observed", summary(pp)


# ------------------------------------------------------------------ the shipped candidate is not what ran
REBREAK_INIT = "from .core import mean as _fixed\n\n\ndef mean(xs):\n    return sum(xs) / len(xs)\n"


def test_s1_declared_subject_narrower_than_the_scenario_reach(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": BUGGY,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED, "mypkg/__init__.py": REBREAK_INIT})
    _bug_still_shipped(root)
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    print("SUMMARY", summary(pp))
    assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    _no_false_proof(pp, "S1")


def test_s2_inferred_subject_misses_the_parent_package_init(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": BUGGY,
                                      "tests/test_mean.py": EXISTING.replace("from mypkg import", "from mypkg.core import")})
    write(root, {"mypkg/core.py": FIXED,
                 "mypkg/__init__.py": "from . import core as _c\n\n\ndef _buggy(xs):\n    return sum(xs) / len(xs)\n\n\n"
                                      "_c.mean = _buggy\n"})
    _bug_still_shipped(root, "from mypkg.core import mean; print('RESULT', mean([]))")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT_CORE), *PT)
    print("SUMMARY", summary(pp))
    assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    _no_false_proof(pp, "S2")


def test_s2d_declared_subject_misses_the_parent_package_init(tmp_path: Path):
    """S2 with the subject declared as the module the scenario names."""
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": BUGGY,
                                      "tests/test_mean.py": EXISTING.replace("from mypkg import", "from mypkg.core import")})
    write(root, {"mypkg/core.py": FIXED,
                 "mypkg/__init__.py": "from . import core as _c\n\n\ndef _buggy(xs):\n    return sum(xs) / len(xs)\n\n\n"
                                      "_c.mean = _buggy\n"})
    _bug_still_shipped(root, "from mypkg.core import mean; print('RESULT', mean([]))")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT_CORE), *PT,
                        "--subject", "mypkg/core.py")
    _no_false_proof(pp, "S2d")


def test_s3_inferred_subject_misses_a_module_loaded_by_importlib(tmp_path: Path):
    init = ("import importlib\n\nfrom .core import mean\n\nfor _n in ['ext']:\n"
            "    importlib.import_module(__name__ + '.' + _n)\n")
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": init, "mypkg/core.py": BUGGY,
                                      "mypkg/ext.py": "def setup():\n    pass\n", "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED,
                 "mypkg/ext.py": "import mypkg\n\n\ndef _buggy(xs):\n    return sum(xs) / len(xs)\n\n\n"
                                 "mypkg.mean = _buggy\n"})
    _bug_still_shipped(root)
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT)
    print("SUMMARY", summary(pp))
    assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    _no_false_proof(pp, "S3")


def test_s4_a_constants_module_that_monkeypatches(tmp_path: Path):
    init = "from .core import mean\nfrom . import config\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": init, "mypkg/core.py": BUGGY,
                                      "mypkg/config.py": "ROUND = 2\n", "tests/test_mean.py": EXISTING})
    # Import + Assign only: constants_only() says "a module of constants", yet it rebinds mypkg.mean
    write(root, {"mypkg/core.py": FIXED,
                 "mypkg/config.py": "import mypkg\n\nROUND = 2\nmypkg.mean = lambda xs: sum(xs) / len(xs)\n"})
    _bug_still_shipped(root)
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT)
    print("SUMMARY", summary(pp))
    assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    _no_false_proof(pp, "S4")


def test_s5_a_data_file_the_subject_reads(tmp_path: Path):
    core_fixed = ("import json\nimport os\n\n\ndef mean(xs):\n    if not xs:\n"
                  "        with open(os.path.join(os.path.dirname(__file__), 'defaults.json')) as f:\n"
                  "            return json.load(f)['empty']\n    return sum(xs) / len(xs)\n")
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": BUGGY,
                                      "mypkg/defaults.json": '{"empty": 0}\n', "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": core_fixed, "mypkg/defaults.json": '{"empty": null}\n'})
    _bug_still_shipped(root)
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT)
    print("SUMMARY", summary(pp))
    assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    _no_false_proof(pp, "S5")


# ------------------------------------------------------------------ hidden regression in a left-out file
STRS = "def shout(s):\n    return s.upper()\n"
STRS_TEST = "from strs import shout\n\n\ndef test_shout():\n    assert shout('a') == 'A'\n"


def _s16_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": BUGGY,
                                      "strs.py": STRS, "tests/test_mean.py": EXISTING, "tests/test_strs.py": STRS_TEST})


@pytest.mark.parametrize("declared", [True, False])
def test_s17_a_regression_in_a_left_out_file_with_its_test_edited_is_detected(tmp_path: Path, declared: bool):
    root = _s16_repo(tmp_path)
    write(root, {"mypkg/core.py": FIXED, "strs.py": "def shout(s):\n    return s\n",
                 "tests/test_strs.py": STRS_TEST.replace("== 'A'", "== 'a'")})
    # the regression is real: the base's own test fails on the shipped candidate
    res = shipped(root, "from strs import shout; assert shout('a') == 'A'")
    assert res.returncode != 0
    extra = ("--subject", "mypkg/core.py") if declared else ()
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, *extra)
    print("SUMMARY", summary(pp))
    rows = (pp.get("edited_tests") or {}).get("files") or []
    assert pp["verdict"]["state"] == "regressions-detected", (
        f"S17: strs.py regressed and tests/test_strs.py was edited to hide it; the base's own test_strs.py ran "
        f"against the base's strs.py: {summary(pp)}; edited rows {[(r['path'], r['state']) for r in rows]}")


def test_s16_a_regression_in_a_left_out_file_is_detected_by_verify(tmp_path: Path):
    root = _s16_repo(tmp_path)
    write(root, {"mypkg/core.py": FIXED, "strs.py": "def shout(s):\n    return s\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] == "regressions-detected", summary(pp)
