# Vendored from the sixth adversarial review of ProofLab (2026-10-25, on 473c41a), with the assertions of the
# static probes inverted to the safe result. Each end-to-end test asserts the safe result.
"""End-to-end G4 bypasses: the change only edits the scenario's INPUT (mypkg/samples.py); unchanged mean([])
still raises ZeroDivisionError in the shipped candidate. Each test asserts the SAFE result (not supported)."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
SAMPLES_BASE = ("def empty():\n    return []\n\n\ndef fill(xs):\n    pass\n\n\n"
                "def with_input(f):\n    def w():\n        return f(empty())\n    w.__name__ = f.__name__\n    return w\n")
SAMPLES_CAND = SAMPLES_BASE.replace("return []", "return [0]").replace("    pass\n", "    xs.append(0)\n")
H = "from mypkg import mean\nfrom mypkg.samples import empty\nimport mypkg.samples as samples\n\n\n"
SCEN = {
    "parametrize": "import pytest\n" + H + "@pytest.mark.parametrize('xs', [empty()])\ndef test_empty(xs):\n"
                   "    assert mean(xs) == 0\n",
    "alias": H + "def test_empty():\n    m = mean\n    assert m(empty()) == 0\n",
    "class_attr": H + "class TestEmpty:\n    xs = empty()\n\n    def test_empty(self):\n        assert mean(self.xs) == 0\n",
    "mutation": H + "def test_empty():\n    xs = []\n    samples.fill(xs)\n    assert mean(xs) == 0\n",
    "default_arg": H + "def test_empty(xs=empty()):\n    assert mean(xs) == 0\n",
    "fixture_name_kw": "import pytest\n" + H + "@pytest.fixture(name='xs')\ndef _xs():\n    return empty()\n\n\n"
                       "def test_empty(xs):\n    assert mean(xs) == 0\n",
    "decorator": H + "@samples.with_input\ndef test_empty(xs):\n    assert mean(xs) == 0\n",
}


def _outside(tmp_path, text):
    p = tmp_path / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


@pytest.mark.parametrize("declared", [True, False])
@pytest.mark.parametrize("name", list(SCEN))
def test_g4_bypass(tmp_path, name, declared):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": SAMPLES_BASE,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": SAMPLES_CAND})
    res = shipped(root, "from mypkg import mean; print('RESULT', mean([]))")
    assert "ZeroDivisionError" in res.stderr  # nothing is fixed
    extra = ("--subject", "mypkg/samples.py") if declared else ()
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, SCEN[name]), *PT, *extra)
    print("SUMMARY", name, declared, summary(pp), "abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", f"FALSE PROOF {name} declared={declared}: {summary(pp)}"
