# Vendored from the eighth adversarial review of ProofLab (2026-10-25, on 54830b9). Each test asserts the safe
# result (test_prove_review8_genuine: a genuine fix that must stay supported, pinned here with its subject declared).
"""Round-8 probes, batch 3: controls, fixture shadowing, class-level entry. SAFE result asserted."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402
from test_prove_review8_entry import _go, _outside  # noqa: E402
from test_prove_review8_eq_regress import _eq  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")


def test_control_direct_second_call_is_refused(tmp_path):
    scen = ("from mypkg import configure, mean\n\n\ndef test_empty():\n    configure(0)\n"
            "    assert mean([]) == 0\n")
    pp = _go(tmp_path, scen, tag="control-direct")
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_control_fixture_requested_by_param_is_refused(tmp_path):
    conf = "import pytest\n\nfrom mypkg import configure\n\n\n@pytest.fixture\ndef prep():\n    configure(0)\n"
    scen = "from mypkg import mean\n\n\ndef test_empty(prep):\n    assert mean([]) == 0\n"
    pp = _go(tmp_path, scen, {"tests/conftest.py": conf}, tag="control-fixture-param")
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_f_fixture_shadowed_by_closer_conftest(tmp_path):
    root_conf = "import pytest\n\n\n@pytest.fixture\ndef prep():\n    return None\n"
    near_conf = "import pytest\n\nfrom mypkg import configure\n\n\n@pytest.fixture\ndef prep():\n    configure(0)\n"
    scen = "from mypkg import mean\n\n\ndef test_empty(prep):\n    assert mean([]) == 0\n"
    pp = _go(tmp_path, scen, {"conftest.py": root_conf, "tests/conftest.py": near_conf}, tag="fixture-shadow")
    assert pp["verdict"]["state"] != "supported", summary(pp)


CLS_B = ("class Stats:\n    empty = None\n\n    @classmethod\n    def configure(cls, empty):\n        return None\n\n"
         "    def mean(self, xs):\n        return sum(xs) / len(xs)\n")
CLS_C = ("class Stats:\n    empty = None\n\n    @classmethod\n    def configure(cls, empty):\n        cls.empty = empty\n\n"
         "    def mean(self, xs):\n        if not xs and self.empty is not None:\n            return self.empty\n"
         "        return sum(xs) / len(xs)\n")


def test_k_classmethod_sets_class_state(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": CLS_B,
                                      "tests/test_mean.py": "from mypkg.core import Stats\n\n\ndef test_mean():\n"
                                                            "    assert Stats().mean([1, 2, 3]) == 2\n"})
    write(root, {"mypkg/core.py": CLS_C})
    res = shipped(root, "from mypkg.core import Stats; print('RESULT', Stats().mean([]))")
    assert "ZeroDivisionError" in res.stderr
    scen = ("from mypkg.core import Stats\n\n\ndef test_empty():\n    Stats.configure(0)\n"
            "    assert Stats().mean([]) == 0\n")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT)
    print("SUMMARY classmethod", summary(pp), "| abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", summary(pp)


LOCALS_NOHASH = ("class _Zero(float):\n    locals()['__eq__'] = lambda s, o: True\n\n\n"
                 "def mean(xs):\n    if not xs:\n        return _Zero(float('nan'))\n    return sum(xs) / len(xs)\n")


def test_e2b_locals_in_class_body_no_hash(tmp_path):
    pp = _eq(tmp_path, LOCALS_NOHASH, tag="locals-body-nohash")
    assert pp["verdict"]["state"] != "supported", summary(pp)
