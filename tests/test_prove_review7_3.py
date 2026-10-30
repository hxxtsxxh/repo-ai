# Vendored from the seventh adversarial review of ProofLab (2026-10-25, on 0ec0516). Each test asserts the safe
# result, except where noted (a genuine fix that must stay supported).
"""Round-7 probes, batch 3: git archive export-ignore, production files named like tests."""
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


def _outside(tmp_path, text, name="test_accept.py"):
    p = tmp_path / "reviewer" / name
    write(p.parent, {name: text})
    return p


def _show(tag, pp):
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"), "| regs", (pp.get("regressions") or {}).get("why"),
          (pp.get("regressions") or {}).get("pre_existing"), "| edited", (pp.get("edited_tests") or {}).get("why"),
          (pp.get("edited_tests") or {}).get("tests"))


def test_export_ignored_tests_hide_a_regression(tmp_path):
    """`.gitattributes: tests/test_mean.py export-ignore` (common in packaged repos): git archive drops the existing
    test from every base copy. The change breaks mean([1, 2, 3])."""
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      ".gitattributes": "tests/test_mean.py export-ignore\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": "def mean(xs):\n    return 0\n"})
    res = shipped(root, "from mypkg import mean; print('RESULT', mean([1, 2, 3]))")
    assert "RESULT 0" in res.stdout
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("export-ignore-tests", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_export_ignored_tests_dir_hide_a_regression(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      ".gitattributes": "/tests export-ignore\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": "def mean(xs):\n    return 0\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("export-ignore-tests-dir", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_export_ignored_file_makes_the_base_fail(tmp_path):
    """The real base already returns 0 for mean([]) (through mypkg/_fast.py); git archive leaves _fast.py out, so the
    base copy fails the scenario."""
    init = "try:\n    from ._fast import mean\nexcept ImportError:\n    from .core import mean\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": init, "mypkg/core.py": MEAN, "mypkg/_fast.py": FIXED,
                                      ".gitattributes": "mypkg/_fast.py export-ignore\n",
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED + "# tidy\n"})
    import subprocess
    subprocess.run(["git", "stash", "push", "-q", "-m", "advrev7-probe"], cwd=root, check=True, capture_output=True)
    pre = shipped(root, "from mypkg import mean; print('RESULT', mean([]))")
    subprocess.run(["git", "stash", "pop", "-q"], cwd=root, check=True, capture_output=True)
    assert "RESULT 0" in pre.stdout, pre  # the real base is already correct
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("export-ignore-base", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_hidden_regression_production_module_named_like_a_test(tmp_path):
    """mypkg/ab_test.py: an A/B-testing feature module, named like a pytest file."""
    ab = "def bucket(uid):\n    return uid % 2\n"
    t = "from mypkg.ab_test import bucket\n\n\ndef test_bucket():\n    assert bucket(3) == 1\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "mypkg/ab_test.py": ab, "tests/test_mean.py": EXISTING, "tests/test_ab.py": t})
    write(root, {"mypkg/core.py": FIXED, "mypkg/ab_test.py": "def bucket(uid):\n    return 0\n",
                 "tests/test_ab.py": t.replace("bucket(3) == 1", "bucket(3) == 0")})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("ab_test-module", pp)
    print("SUBJ", pp.get("subject"))
    assert pp["verdict"]["state"] != "supported", summary(pp)
