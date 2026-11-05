# Vendored from the eighth adversarial review of ProofLab (2026-10-25, on 54830b9). Each test asserts the safe
# result (test_prove_review8_genuine: a genuine fix that must stay supported, pinned here with its subject declared).
"""Round-8 probes: second entry points hidden from the single-entry rule. Each asserts the SAFE result."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")

BASE = ("_S = {}\n\n\ndef configure(empty=None):\n    return None\n\n\n"
        "def mean(xs):\n    return sum(xs) / len(xs)\n")
CHG = ("_S = {}\n\n\ndef configure(empty=None):\n    _S['empty'] = empty\n\n\n"
       "def mean(xs):\n    if not xs and 'empty' in _S:\n        return _S['empty']\n    return sum(xs) / len(xs)\n")
INIT = "from .core import configure, mean\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"


def _outside(tmp_path, text):
    p = tmp_path / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


def _go(tmp_path, scen, extra_base=None, tag="", pin_extra=()):
    files = {"mypkg/__init__.py": INIT, "mypkg/core.py": BASE, "tests/test_mean.py": EXISTING, **(extra_base or {})}
    root = make_repo(tmp_path / "r", files)
    write(root, {"mypkg/core.py": CHG})
    res = shipped(root, "from mypkg import mean; print('RESULT', mean([]))")
    assert "ZeroDivisionError" in res.stderr, (res.stdout, res.stderr[-300:])
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, *pin_extra)
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"))
    return pp


def test_a_module_alias(tmp_path):
    scen = "import mypkg\n\n\ndef test_empty():\n    m = mypkg\n    m.configure(0)\n    assert m.mean([]) == 0\n"
    pp = _go(tmp_path, scen, tag="module-alias")
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_a2_module_alias_module_level(tmp_path):
    scen = "import mypkg\n\nm = mypkg\n\n\ndef test_empty():\n    m.configure(0)\n    assert m.mean([]) == 0\n"
    pp = _go(tmp_path, scen, tag="module-alias-toplevel")
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_b_sorted_key(tmp_path):
    scen = ("from mypkg import configure, mean\n\n\ndef test_empty():\n    sorted([0], key=configure)\n"
            "    assert mean([]) == 0\n")
    pp = _go(tmp_path, scen, tag="sorted-key")
    assert pp["verdict"]["state"] != "supported", summary(pp)


CONF_FX = "import pytest\n\nfrom mypkg import configure\n\n\n@pytest.fixture\ndef prep():\n    configure(0)\n"


def test_c_usefixtures(tmp_path):
    scen = ("import pytest\n\nfrom mypkg import mean\n\n\n@pytest.mark.usefixtures('prep')\ndef test_empty():\n"
            "    assert mean([]) == 0\n")
    pp = _go(tmp_path, scen, {"tests/conftest.py": CONF_FX}, tag="usefixtures")
    assert pp["verdict"]["state"] != "supported", summary(pp)


PLUG = ("import pytest\n\nfrom mypkg import configure\n\n\n@pytest.fixture(autouse=True)\ndef prep():\n"
        "    configure(0)\n")


def test_d_pytest_plugins(tmp_path):
    scen = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"
    pp = _go(tmp_path, scen, {"conftest.py": "pytest_plugins = ['tests.plug']\n", "tests/plug.py": PLUG},
             tag="pytest_plugins")
    assert pp["verdict"]["state"] != "supported", summary(pp)


HELP = "from mypkg import configure\n\n\ndef setup_module(module=None):\n    configure(0)\n"


def test_p_imported_setup_module(tmp_path):
    scen = ("from helpers import setup_module  # noqa: F401\nfrom mypkg import mean\n\n\ndef test_empty():\n"
            "    assert mean([]) == 0\n")
    pp = _go(tmp_path, scen, {"tests/helpers.py": HELP}, tag="imported-setup_module")
    assert pp["verdict"]["state"] != "supported", summary(pp)


API_B = ("class _API:\n    def __init__(self):\n        self.empty = None\n\n    def configure(self, empty):\n"
         "        return None\n\n    def mean(self, xs):\n        return sum(xs) / len(xs)\n\n\napi = _API()\n")
API_C = ("class _API:\n    def __init__(self):\n        self.empty = None\n\n    def configure(self, empty):\n"
         "        self.empty = empty\n\n    def mean(self, xs):\n        if not xs and self.empty is not None:\n"
         "            return self.empty\n        return sum(xs) / len(xs)\n\n\napi = _API()\n")


def test_j_module_object_methods(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": API_B,
                                      "tests/test_mean.py": "from mypkg.core import api\n\n\ndef test_mean():\n"
                                                            "    assert api.mean([1, 2, 3]) == 2\n"})
    write(root, {"mypkg/core.py": API_C})
    res = shipped(root, "from mypkg.core import api; print('RESULT', api.mean([]))")
    assert "ZeroDivisionError" in res.stderr
    scen = "from mypkg.core import api\n\n\ndef test_empty():\n    api.configure(0)\n    assert api.mean([]) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT)
    print("SUMMARY api-object", summary(pp), "| abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", summary(pp)
