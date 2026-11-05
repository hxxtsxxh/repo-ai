# Vendored from the sixth adversarial review of ProofLab (2026-10-25, on 473c41a), with the assertions of the
# static probes inverted to the safe result. Each end-to-end test asserts the safe result.
"""Static probes of prove/dataflow.py: each scenario feeds a value derived from the change to unchanged code,
so ProofLab must abstain."""
import pytest
from repo_ai.prove import dataflow

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
BASE = {"mypkg/__init__.py": MEAN,
        "mypkg/samples.py": "def empty():\n    return [0]\n\ndef fill(xs):\n    xs.append(0)\n\n"
                            "EMPTY = [0]\n\ndef with_input(f):\n    def w():\n        return f(empty())\n    return w\n"
                            "\nclass Box:\n    data = [0]\n"}

H = "from mypkg import mean\nfrom mypkg.samples import empty\nimport mypkg.samples as samples\n"
CASES = {
    "alias": H + "def test_e():\n    m = mean\n    assert m(empty()) == 0\n",
    "getattr_callee": H + "import mypkg\ndef test_e():\n    assert getattr(mypkg, 'mean')(empty()) == 0\n",
    "default_arg": H + "def test_e(xs=empty()):\n    assert mean(xs) == 0\n",
    "parametrize": "import pytest\n" + H + "@pytest.mark.parametrize('xs', [empty()])\ndef test_e(xs):\n    assert mean(xs) == 0\n",
    "class_attr": H + "class TestE:\n    xs = empty()\n    def test_e(self):\n        assert mean(self.xs) == 0\n",
    "mutation": H + "def test_e():\n    xs = []\n    samples.fill(xs)\n    assert mean(xs) == 0\n",
    "partial": "import functools\n" + H + "def test_e():\n    assert functools.partial(mean, empty())() == 0\n",
    "map": H + "def test_e():\n    assert list(map(mean, [empty()])) == [0]\n",
    "decorator": H + "@samples.with_input\ndef test_e(xs):\n    assert mean(xs) == 0\n",
    "setattr": "import unittest\n" + H + "class T(unittest.TestCase):\n    def setUp(self):\n        setattr(self, 'xs', empty())\n    def test_e(self):\n        self.assertEqual(mean(self.xs), 0)\n",
    "dict_lookup": H + "FUNCS = {'mean': mean}\ndef test_e():\n    assert FUNCS['mean'](empty()) == 0\n",
    "lambda_wrap": H + "call = lambda f, x: f(x)\ndef test_e():\n    assert call(mean, empty()) == 0\n",
    "local_helper": H + "def apply(f, x):\n    return f(x)\ndef test_e():\n    assert apply(mean, empty()) == 0\n",
    "class_obj_attr": H + "def test_e():\n    assert mean(samples.Box().data) == 0\n",
    "method_on_instance_cls": H + "class TestE:\n    def setup_method(self):\n        self.calc = mean\n    def test_e(self):\n        assert self.calc(empty()) == 0\n",
    "fixture_name_kw": "import pytest\n" + H + "@pytest.fixture(name='xs')\ndef _xs():\n    return empty()\n\ndef test_e(xs):\n    assert mean(xs) == 0\n",
    "getfixturevalue": "import pytest\n" + H + "@pytest.fixture\ndef data():\n    return empty()\n\ndef test_e(request):\n    assert mean(request.getfixturevalue('data')) == 0\n",
    "generate_tests": "import pytest\n" + H + "def pytest_generate_tests(metafunc):\n    metafunc.parametrize('xs', [empty()])\n\ndef test_e(xs):\n    assert mean(xs) == 0\n",
    "unpack_return": H + "def test_e():\n    for xs in [empty()]:\n        pass\n    ys = list(xs)\n    assert mean(ys) == 0\n",
}

@pytest.mark.parametrize("name", sorted(CASES))
def test_feeding_the_change_into_unchanged_code_abstains(name):
    files = {**BASE, "tests/test_accept.py": CASES[name]}
    data = {k: v.encode() for k, v in files.items()}
    found = dataflow.findings("tests/test_accept.py", "pytest", set(data), data.get, {"mypkg/samples.py"})
    print(name, found)
    assert found, name
