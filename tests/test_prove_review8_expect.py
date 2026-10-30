# Vendored from the eighth adversarial review of ProofLab (2026-10-25, on 54830b9). Each test asserts the safe
# result (test_prove_review8_genuine: a genuine fix that must stay supported, pinned here with its subject declared).
"""Round-8 probes, batch 4: expectations that come from the repository. SAFE result asserted."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402
from test_prove_review8_entry import _outside  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")

EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
CONST_B = "DEFAULT = 0\n\n\ndef mean(xs):\n    return sum(xs) / len(xs)\n"
CONST_C = "DEFAULT = 5\n\n\ndef mean(xs):\n    if not xs:\n        return DEFAULT\n    return sum(xs) / len(xs)\n"


def _const(tmp_path, scen, tag):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import DEFAULT, mean\n", "mypkg/core.py": CONST_B,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": CONST_C})
    res = shipped(root, "from mypkg import mean; print('RESULT', mean([]))")
    assert "RESULT 5" in res.stdout, res
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT)
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"))
    return pp


def test_control_constant_direct_is_refused(tmp_path):
    scen = "from mypkg import DEFAULT, mean\n\n\ndef test_empty():\n    assert mean([]) == DEFAULT\n"
    pp = _const(tmp_path, scen, "control-const-direct")
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_x1_constant_through_arithmetic(tmp_path):
    scen = "from mypkg import DEFAULT, mean\n\n\ndef test_empty():\n    assert mean([]) - DEFAULT == 0\n"
    pp = _const(tmp_path, scen, "const-binop")
    assert pp["verdict"]["state"] != "supported", summary(pp)


ENUM_B = ("import enum\n\n\nclass Kind(enum.Enum):\n    ONE = 'one'\n    EMPTY = 'empty'\n\n\n"
          "def classify(xs):\n    return Kind.ONE\n")
ENUM_C = ("import enum\n\n\nclass Kind(enum.Enum):\n    ONE = 'one'\n    EMPTY = 'one'\n\n\n"
          "def classify(xs):\n    return Kind.ONE\n")


def test_x2_enum_member_redefined(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": ENUM_B,
                                      "tests/test_kind.py": "from mypkg.core import Kind, classify\n\n\ndef test_one():\n"
                                                            "    assert classify([1]) == Kind.ONE\n"})
    write(root, {"mypkg/core.py": ENUM_C})
    res = shipped(root, "from mypkg.core import Kind, classify; print('RESULT', classify([]).value, len(Kind))")
    assert "RESULT one 1" in res.stdout, res
    scen = "from mypkg.core import Kind, classify\n\n\ndef test_empty():\n    assert classify([]) == Kind.EMPTY\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT)
    print("SUMMARY enum-alias", summary(pp), "| abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", summary(pp)
