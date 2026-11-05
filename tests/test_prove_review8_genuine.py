# Vendored from the eighth adversarial review of ProofLab (2026-10-25, on 54830b9). Each test asserts the safe
# result (test_prove_review8_genuine: a genuine fix that must stay supported, pinned here with its subject declared).
"""Round-8: textbook genuine fixes; each asserts SUPPORTED (a failure = a wrongly refused genuine fix)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, summary, write  # noqa: E402
from test_prove_review8_entry import _outside  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"


def _run(tmp_path, base, cand, scen, tag, runner=PT, extra=None):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import *  # noqa\n" if False else
                                      "from .core import mean\n", "mypkg/core.py": base, "tests/test_mean.py": EXISTING,
                                      **(extra or {})})
    write(root, {"mypkg/core.py": cand})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *runner, "--subject", "mypkg/core.py")
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"))
    return pp


def test_g1_parametrize(tmp_path):
    scen = ("import pytest\n\nfrom mypkg import mean\n\n\n@pytest.mark.parametrize('xs, want', [([], 0), ([2], 2)])\n"
            "def test_mean(xs, want):\n    assert mean(xs) == want\n")
    pp = _run(tmp_path, MEAN, FIXED, scen, "parametrize")
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_g2_unittest_setup_instance(tmp_path):
    base = MEAN + "\n\nclass Stats:\n    def __init__(self):\n        self.xs = []\n\n    def mean(self):\n        return mean(self.xs)\n"
    cand = FIXED + "\n\nclass Stats:\n    def __init__(self):\n        self.xs = []\n\n    def mean(self):\n        return mean(self.xs)\n"
    scen = ("import unittest\n\nfrom mypkg.core import Stats\n\n\nclass T(unittest.TestCase):\n    def setUp(self):\n"
            "        self.s = Stats()\n\n    def test_empty(self):\n        self.assertEqual(self.s.mean(), 0)\n")
    pp = _run(tmp_path, base, cand, scen, "unittest-setup", runner=PT)
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_g3_raises_match(tmp_path):
    cand = "def mean(xs):\n    if not xs:\n        raise ValueError('mean of empty data')\n    return sum(xs) / len(xs)\n"
    scen = ("import pytest\n\nfrom mypkg import mean\n\n\ndef test_empty():\n    with pytest.raises(ValueError, match='empty'):\n"
            "        mean([])\n")
    pp = _run(tmp_path, MEAN, cand, scen, "raises-match")
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_g4_logger_added(tmp_path):
    cand = ("import logging\n\nlog = logging.getLogger(__name__)\n\n\ndef mean(xs):\n    if not xs:\n"
            "        log.debug('empty')\n        return 0\n    return sum(xs) / len(xs)\n")
    scen = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"
    pp = _run(tmp_path, MEAN, cand, scen, "logger")
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_g5_len_fix(tmp_path):
    base = MEAN + "\n\nclass Bag:\n    def __init__(self):\n        self.items = [None]\n\n    def __len__(self):\n        return len(self.items)\n"
    cand = MEAN + "\n\nclass Bag:\n    def __init__(self):\n        self.items = []\n\n    def __len__(self):\n        return len(self.items)\n"
    scen = "from mypkg.core import Bag\n\n\ndef test_empty():\n    assert len(Bag()) == 0\n"
    pp = _run(tmp_path, base, cand, scen, "len-via-init")
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_g6_result_attribute(tmp_path):
    base = MEAN + "\n\nclass R:\n    def __init__(self, v):\n        self.v = v\n\n\ndef parse(s):\n    return R(s)\n"
    cand = MEAN + "\n\nclass R:\n    def __init__(self, v):\n        self.v = v\n\n\ndef parse(s):\n    return R(int(s))\n"
    scen = "from mypkg.core import parse\n\n\ndef test_parse():\n    assert parse('1').v == 1\n"
    pp = _run(tmp_path, base, cand, scen, "result-attr")
    assert pp["verdict"]["state"] == "supported", summary(pp)
