# Vendored from the seventh adversarial review of ProofLab (2026-10-25, on 0ec0516). Each test asserts the safe
# result, except where noted (a genuine fix that must stay supported).
"""Round-7 adversarial probes, batch 2. Each test asserts the SAFE result (fails on a false proof),
except the GENUINE_* tests, which assert a textbook fix is supported."""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, UT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402
from test_verify_adaptive import NODE_SANDBOX  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")
needs_node = pytest.mark.skipif(not NODE_SANDBOX or not shutil.which("node"), reason="no node")

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
ACCEPT = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"


def _outside(tmp_path, text, name="test_accept.py"):
    p = tmp_path / "reviewer" / name
    write(p.parent, {name: text})
    return p


def _show(tag, pp):
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"), "| base",
          (pp.get("observations") or {}).get("baseline", {}) and pp["observations"]["baseline"].get("state"),
          pp["observations"]["baseline"].get("why") if pp.get("observations") and pp["observations"].get("baseline") else "")


# ------------------------------------------------ comparison with a literal that is not independent
ALWAYS = ("class _Zero(float):\n    def __eq__(self, other):\n        return True\n\n    __hash__ = float.__hash__\n\n\n"
          "def mean(xs):\n    if not xs:\n        return _Zero(float('nan'))\n    return sum(xs) / len(xs)\n")


def test_always_equal_custom_class(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": ALWAYS})
    res = shipped(root, "from mypkg import mean; r = mean([]); print('RESULT', r == 0, r == 7, r + 1)")
    assert "RESULT True True nan" in res.stdout, res
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("always-equal", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ------------------------------------------------ G4 through a data file the declared subject is
LOADER = ("import json\nimport os\n\n\ndef load(name):\n    with open(os.path.join(os.path.dirname(__file__), 'samples', "
          "name + '.json')) as f:\n        return json.load(f)\n")


def test_g4_data_subject_through_unchanged_loader(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/loader.py": LOADER,
                                      "mypkg/samples/empty.json": "[]\n", "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples/empty.json": "[0]\n"})
    res = shipped(root, "from mypkg import mean; mean([])")
    assert "ZeroDivisionError" in res.stderr
    scen = "from mypkg import mean\nfrom mypkg.loader import load\n\n\ndef test_empty():\n    assert mean(load('empty')) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples/empty.json")
    _show("data-subject", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ------------------------------------------------ G4: a changed setup function sets state an unchanged function reads
ENV_B = ("import os\n\n\ndef configure():\n    os.environ['MYPKG_EMPTY'] = ''\n\n\ndef mean(xs):\n"
         "    if not xs and os.environ.get('MYPKG_EMPTY'):\n        return int(os.environ['MYPKG_EMPTY'])\n"
         "    return sum(xs) / len(xs)\n")


def test_g4_env_side_channel(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": ENV_B,
                                      "tests/test_mean.py": EXISTING.replace("from mypkg import", "from mypkg.core import")})
    write(root, {"mypkg/core.py": ENV_B.replace("= ''", "= '0'")})
    res = shipped(root, "from mypkg.core import mean; mean([])")
    assert "ZeroDivisionError" in res.stderr
    scen = "from mypkg.core import configure, mean\n\n\ndef test_empty():\n    configure()\n    assert mean([]) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/core.py")
    _show("env-side-channel", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ------------------------------------------------ node: CommonJS re-export from the subject
@needs_node
def test_node_g4_commonjs_reexport(tmp_path):
    pkg = '{"name": "n1", "version": "1.0.0", "scripts": {"test": "node --test"}}\n'
    index = "function mean(xs) { return xs.reduce((a, b) => a + b, 0) / xs.length; }\nmodule.exports = { mean };\n"
    samples = "const { mean } = require('./index.js');\nfunction empty() { return []; }\nmodule.exports = { mean, empty };\n"
    exist = ("const { test } = require('node:test');\nconst assert = require('node:assert');\n"
             "const { mean } = require('../lib/index.js');\n"
             "test('mean of three', () => { assert.strictEqual(mean([1, 2, 3]), 2); });\n")
    root = make_repo(tmp_path / "r", {"package.json": pkg, "lib/index.js": index, "lib/samples.js": samples,
                                      "test/mean.test.js": exist})
    write(root, {"lib/samples.js": samples.replace("return [];", "return [0];")})
    scen = ("const { test } = require('node:test');\nconst assert = require('node:assert');\n"
            "const { mean, empty } = require('../lib/samples.js');\n"
            "test('mean of empty is 0', () => { assert.strictEqual(mean(empty()), 0); });\n")
    _, pp = pin_and_run(root, "test/accept.test.js", _outside(tmp_path, scen, "accept.test.js"),
                        "--test-command", "node --test", "--subject", "lib/samples.js")
    _show("node-cjs-reexport", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ------------------------------------------------ fix (6): new interfaces not recognised as load failures
@needs_node
def test_node_new_function_counts_as_behaviour(tmp_path):
    pkg = '{"name": "n1", "version": "1.0.0", "scripts": {"test": "node --test"}}\n'
    index = "function mean(xs) { return xs.reduce((a, b) => a + b, 0) / xs.length; }\nmodule.exports = { mean };\n"
    exist = ("const { test } = require('node:test');\nconst assert = require('node:assert');\n"
             "const { mean } = require('../lib/index.js');\n"
             "test('mean of three', () => { assert.strictEqual(mean([1, 2, 3]), 2); });\n")
    root = make_repo(tmp_path / "r", {"package.json": pkg, "lib/index.js": index, "test/mean.test.js": exist})
    write(root, {"lib/index.js": index.replace("module.exports = { mean };",
                                               "function median(xs) { return xs.length ? xs[0] : 0; }\n"
                                               "module.exports = { mean, median };")})
    scen = ("const { test } = require('node:test');\nconst assert = require('node:assert');\n"
            "const { median } = require('../lib/index.js');\n"
            "test('median of empty is 0', () => { assert.strictEqual(median([]), 0); });\n")
    _, pp = pin_and_run(root, "test/accept.test.js", _outside(tmp_path, scen, "accept.test.js"),
                        "--test-command", "node --test", "--subject", "lib/index.js")
    _show("node-new-function", pp)
    assert pp["observations"]["baseline"]["state"] != "reproduced", summary(pp)


def test_py_class_gains_constructor_counts_as_behaviour(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/conf.py": "class Config:\n    pass\n",
                                      "tests/test_conf.py": "from mypkg.conf import Config\n\n\ndef test_c():\n"
                                                            "    assert Config() is not None\n"})
    write(root, {"mypkg/conf.py": "class Config:\n    def __init__(self, path=''):\n        self.path = path\n"})
    scen = "from mypkg.conf import Config\n\n\ndef test_path():\n    assert Config('x').path == 'x'\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/conf.py")
    _show("ctor-new", pp)
    assert pp["observations"]["baseline"]["state"] != "reproduced", summary(pp)


# ------------------------------------------------ genuine fixes that should stay supported
def test_genuine_method_fix_unittest(tmp_path):
    stats = "class Stats:\n    def mean(self, xs):\n        return sum(xs) / len(xs)\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/stats.py": stats,
                                      "tests/__init__.py": "",
                                      "tests/test_stats.py": "import unittest\nfrom mypkg.stats import Stats\n\n\n"
                                      "class T(unittest.TestCase):\n    def test_m(self):\n"
                                      "        self.assertEqual(Stats().mean([1, 2, 3]), 2)\n"})
    write(root, {"mypkg/stats.py": stats.replace("return sum(xs) / len(xs)", "return sum(xs) / len(xs) if xs else 0")})
    scen = ("import unittest\nfrom mypkg.stats import Stats\n\n\nclass TestEmpty(unittest.TestCase):\n"
            "    def setUp(self):\n        self.s = Stats()\n\n    def test_empty(self):\n"
            "        self.assertEqual(self.s.mean([]), 0)\n")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *UT, "--subject", "mypkg/stats.py")
    _show("genuine-unittest-method", pp)
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_genuine_fix_with_optional_import_fallback(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": "try:\n    from math import fsum\nexcept ImportError:  # pragma: no cover\n"
                                  "    fsum = sum\n\n\ndef mean(xs):\n    return fsum(xs) / len(xs) if xs else 0\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("genuine-try-import", pp)
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_genuine_fix_raises(tmp_path):
    core = "def parse(s):\n    return int(s)\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/errors.py": "class ParseError(ValueError):\n    pass\n",
                                      "mypkg/core.py": core,
                                      "tests/test_core.py": "from mypkg.core import parse\n\n\ndef test_p():\n    assert parse('1') == 1\n"})
    write(root, {"mypkg/core.py": "from mypkg.errors import ParseError\n\n\ndef parse(s):\n    if not s.strip():\n"
                                  "        raise ParseError('empty')\n    return int(s)\n"})
    scen = ("import pytest\nfrom mypkg.core import parse\nfrom mypkg.errors import ParseError\n\n\ndef test_empty():\n"
            "    with pytest.raises(ParseError):\n        parse('  ')\n")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/core.py")
    _show("genuine-raises", pp)
    assert pp["verdict"]["state"] == "supported", summary(pp)


def test_genuine_fix_capsys(tmp_path):
    core = "def report(xs):\n    print('mean', sum(xs) / len(xs))\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": core,
                                      "tests/test_core.py": "from mypkg.core import report\n\n\ndef test_r(capsys):\n"
                                      "    report([2])\n    assert capsys.readouterr().out == 'mean 2.0\\n'\n"})
    write(root, {"mypkg/core.py": "def report(xs):\n    print('mean', sum(xs) / len(xs) if xs else 0)\n"})
    scen = ("from mypkg.core import report\n\n\ndef test_empty(capsys):\n    report([])\n"
            "    assert capsys.readouterr().out == 'mean 0\\n'\n")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/core.py")
    _show("genuine-capsys", pp)
    assert pp["verdict"]["state"] == "supported", summary(pp)
