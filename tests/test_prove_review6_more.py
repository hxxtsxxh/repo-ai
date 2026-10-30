# Vendored from the sixth adversarial review of ProofLab (2026-10-25, on 473c41a), with the assertions of the
# static probes inverted to the safe result. Each end-to-end test asserts the safe result.
"""More end-to-end probes. Each asserts the SAFE result."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
ACCEPT = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"


def _outside(tmp_path, text):
    p = tmp_path / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


def _show(tag, pp):
    print("SUMMARY", tag, summary(pp), "abstain", pp.get("abstain"), "regs", (pp.get("regressions") or {}).get("why"))


# ---- G4 (b): the expected value comes from a function of the code under test
def test_expected_value_from_a_call(tmp_path):
    core = "def mean(xs):\n    return sum(xs) / len(xs) if xs else None\n\n\ndef empty_mean():\n    return 0\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": core,
                                      "tests/test_mean.py": "from mypkg.core import mean\n\n\ndef test_mean():\n"
                                                            "    assert mean([1, 2, 3]) == 2\n"})
    write(root, {"mypkg/core.py": core.replace("return 0", "return None")})  # only the expectation moves
    res = shipped(root, "from mypkg.core import mean; print('RESULT', mean([]))")
    assert "RESULT None" in res.stdout
    scen = "from mypkg import core\n\n\ndef test_empty():\n    assert core.mean([]) == core.empty_mean()\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/core.py")
    _show("expected-call", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ---- G4 (a): the subject's value reaches unchanged mean through an unchanged non-test helper module
def test_value_through_an_unchanged_nontest_helper(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": "def empty():\n    return []\n",
                                      "mypkg/demo.py": "from mypkg.samples import empty\n\n\ndef demo_input():\n"
                                                       "    return empty()\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": "def empty():\n    return [0]\n"})
    assert "ZeroDivisionError" in shipped(root, "from mypkg import mean; mean([])").stderr
    scen = "from mypkg import mean\nfrom mypkg.demo import demo_input\n\n\ndef test_empty():\n" \
           "    assert mean(demo_input()) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    _show("nontest-helper", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ---- G4 (a): functools.partial hides the callee
def test_partial(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": "def empty():\n    return []\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": "def empty():\n    return [0]\n"})
    scen = "import functools\nfrom mypkg import mean\nfrom mypkg.samples import empty\n\n\ndef test_empty():\n" \
           "    assert functools.partial(mean, empty())() == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    _show("partial", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ---- hidden regressions
def test_regression_in_a_public_testing_module_with_its_test_edited(tmp_path):
    """mypkg/testing.py is shipped public API (like numpy.testing); ProofLab classes it as test code."""
    testing = "def approx_equal(a, b):\n    return abs(a - b) < 1e-9\n"
    t_test = "from mypkg.testing import approx_equal\n\n\ndef test_ae():\n    assert not approx_equal(1, 2)\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "mypkg/testing.py": testing, "tests/test_mean.py": EXISTING,
                                      "tests/test_testing.py": t_test})
    write(root, {"mypkg/core.py": FIXED, "mypkg/testing.py": "def approx_equal(a, b):\n    return True\n",
                 "tests/test_testing.py": t_test.replace("assert not approx_equal(1, 2)", "assert approx_equal(1, 1)")})
    assert "RESULT True" in shipped(root, "from mypkg.testing import approx_equal; print('RESULT', approx_equal(1, 2))").stdout
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("testing-module", pp)
    assert pp["verdict"]["state"] == "regressions-detected" or pp["verdict"]["state"] != "supported", summary(pp)


def test_regression_via_far_data_with_its_test_edited(tmp_path):
    strs = ("import json\nimport os\n\n\ndef greeting():\n"
            "    with open(os.path.join(os.path.dirname(__file__), 'conf', 'strs.json')) as f:\n"
            "        return json.load(f)['hello']\n")
    s_test = "from strs import greeting\n\n\ndef test_greeting():\n    assert greeting() == 'hello'\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "strs.py": strs, "conf/strs.json": '{"hello": "hello"}\n',
                                      "tests/test_mean.py": EXISTING, "tests/test_strs.py": s_test})
    write(root, {"mypkg/core.py": FIXED, "conf/strs.json": '{"hello": ""}\n',
                 "tests/test_strs.py": s_test.replace("== 'hello'", "== ''")})
    assert "RESULT ''" in shipped(root, "from strs import greeting; print('RESULT', repr(greeting()))").stdout
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("far-data", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_regression_via_far_data_no_test_edit(tmp_path):
    """Control: without the test edit, the regression should be detected."""
    strs = ("import json\nimport os\n\n\ndef greeting():\n"
            "    with open(os.path.join(os.path.dirname(__file__), 'conf', 'strs.json')) as f:\n"
            "        return json.load(f)['hello']\n")
    s_test = "from strs import greeting\n\n\ndef test_greeting():\n    assert greeting() == 'hello'\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "strs.py": strs, "conf/strs.json": '{"hello": "hello"}\n',
                                      "tests/test_mean.py": EXISTING, "tests/test_strs.py": s_test})
    write(root, {"mypkg/core.py": FIXED, "conf/strs.json": '{"hello": ""}\n'})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("far-data-noedit", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)
