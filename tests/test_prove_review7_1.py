# Vendored from the seventh adversarial review of ProofLab (2026-10-25, on 0ec0516). Each test asserts the safe
# result, except where noted (a genuine fix that must stay supported).
"""Round-7 adversarial probes of ProofLab (0ec0516). Each test asserts the SAFE result, so it FAILS
when ProofLab gives a false proof. Fixture repos are toy code written here."""
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
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"), "| regs",
          (pp.get("regressions") or {}).get("why"), "| edited", (pp.get("edited_tests") or {}).get("why"))


def _still_raises(root):
    res = shipped(root, "from mypkg import mean; print('RESULT', mean([]))")
    assert "ZeroDivisionError" in res.stderr, (res.stdout, res.stderr[-300:])


# ---------------------------------------------------------------- G4: input changed through a registry
REG = ("REG = {}\n\n\ndef reg(f):\n    REG[f.__name__] = f\n    return f\n\n\n@reg\ndef empty():\n    return []\n\n\n"
       "def get(name):\n    return REG[name]()\n")


def test_g4_decorator_registry(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": REG, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": REG.replace("return []", "return [0]")})
    _still_raises(root)
    scen = "from mypkg import mean\nfrom mypkg.samples import get\n\n\ndef test_empty():\n    assert mean(get('empty')) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    _show("registry", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_g4_decorator_registry_inferred(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": REG, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": REG.replace("return []", "return [0]")})
    scen = "from mypkg import mean\nfrom mypkg.samples import get\n\n\ndef test_empty():\n    assert mean(get('empty')) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT)
    _show("registry-inferred", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


SUBCLS = ("class Sample:\n    registry = {}\n\n    def __init_subclass__(cls):\n        Sample.registry[cls.__name__] = cls.data\n"
          "\n\nclass Empty(Sample):\n    data = []\n\n\ndef get(name):\n    return list(Sample.registry[name])\n")


def test_g4_init_subclass(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": SUBCLS, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": SUBCLS.replace("data = []", "data = [0]")})
    _still_raises(root)
    scen = "from mypkg import mean\nfrom mypkg.samples import get\n\n\ndef test_empty():\n    assert mean(get('Empty')) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    _show("init_subclass", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


ALIASMUT_B = "EMPTY = []\n\n\ndef prepare():\n    return None\n"
ALIASMUT_C = "EMPTY = []\n\n\ndef prepare():\n    d = EMPTY\n    d.append(0)\n"


def test_g4_mutation_through_local_alias(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": ALIASMUT_B,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": ALIASMUT_C})
    _still_raises(root)
    scen = ("from mypkg import mean\nfrom mypkg import samples\n\n\ndef test_empty():\n    samples.prepare()\n"
            "    assert mean(samples.EMPTY) == 0\n")
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    _show("alias-mutation", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ---------------------------------------------------------------- comparison with a literal is not independent
ANY_FIX = "from unittest import mock\n\n\ndef mean(xs):\n    if not xs:\n        return mock.ANY\n    return sum(xs) / len(xs)\n"


def test_always_equal_result(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": ANY_FIX})
    res = shipped(root, "from mypkg import mean; r = mean([]); print('RESULT', r == 0, r == 1, type(r).__name__)")
    assert "RESULT True True _ANY" in res.stdout, res
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show("mock-ANY", pp)
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ---------------------------------------------------------------- hidden regressions: excluded from outside_subject
GREET = ("import configparser\nimport os\n\n\ndef greeting():\n    cp = configparser.ConfigParser()\n"
         "    cp.read(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'settings.ini'))\n"
         "    return cp['app']['greeting']\n")
G_TEST = "from mypkg.greet import greeting\n\n\ndef test_greeting():\n    assert greeting() == 'hello'\n"


def _hidden(tmp_path, files, edits, check, tag):
    base = {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN, "tests/test_mean.py": EXISTING,
            **files}
    root = make_repo(tmp_path / "r", base)
    write(root, {"mypkg/core.py": FIXED, **edits})
    res = shipped(root, check)
    print("SHIPPED", tag, res.stdout.strip(), res.stderr[-200:])
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, "--subject", "mypkg/core.py")
    _show(tag, pp)
    print("OUTSIDE", tag, pp.get("subject"))
    return res, pp


def test_hidden_regression_root_ini(tmp_path):
    res, pp = _hidden(tmp_path, {"settings.ini": "[app]\ngreeting = hello\n", "mypkg/greet.py": GREET,
                                 "tests/test_greet.py": G_TEST},
                      {"settings.ini": "[app]\ngreeting = \n", "tests/test_greet.py": G_TEST.replace("'hello'", "''")},
                      "from mypkg.greet import greeting; print('RESULT', repr(greeting()))", "root-ini")
    assert "RESULT ''" in res.stdout
    assert pp["verdict"]["state"] != "supported", summary(pp)


SNAP = "def label(n):\n    return f'snapshot-{n}'\n"
SNAP_TEST = "from mypkg.snapshots import label\n\n\ndef test_label():\n    assert label(1) == 'snapshot-1'\n"


def test_hidden_regression_production_dir_named_like_tests(tmp_path):
    res, pp = _hidden(tmp_path, {"mypkg/snapshots/__init__.py": SNAP, "tests/test_snap.py": SNAP_TEST},
                      {"mypkg/snapshots/__init__.py": "def label(n):\n    return 'x'\n",
                       "tests/test_snap.py": SNAP_TEST.replace("'snapshot-1'", "'x'")},
                      "from mypkg.snapshots import label; print('RESULT', label(1))", "snapshots-dir")
    assert "RESULT x" in res.stdout
    assert pp["verdict"]["state"] != "supported", summary(pp)


TPL = ("import os\n\n\ndef banner():\n    with open(os.path.join(os.path.dirname(__file__), 'banner.md')) as f:\n"
       "        return f.read().strip()\n")
TPL_TEST = "from mypkg.tpl import banner\n\n\ndef test_banner():\n    assert banner() == 'Welcome'\n"


def test_hidden_regression_md_data(tmp_path):
    res, pp = _hidden(tmp_path, {"mypkg/tpl.py": TPL, "mypkg/banner.md": "Welcome\n", "tests/test_tpl.py": TPL_TEST},
                      {"mypkg/banner.md": "\n", "tests/test_tpl.py": TPL_TEST.replace("'Welcome'", "''")},
                      "from mypkg.tpl import banner; print('RESULT', repr(banner()))", "md-data")
    assert "RESULT ''" in res.stdout
    assert pp["verdict"]["state"] != "supported", summary(pp)


PJ = ("import json\nimport os\n\n\ndef version():\n    with open(os.path.join(os.path.dirname(__file__), 'package.json')) as f:\n"
      "        return json.load(f)['version']\n")
PJ_TEST = "from mypkg.meta import version\n\n\ndef test_version():\n    assert version() == '1.0'\n"


def test_hidden_regression_nested_package_json(tmp_path):
    res, pp = _hidden(tmp_path, {"mypkg/meta.py": PJ, "mypkg/package.json": '{"version": "1.0"}\n',
                                 "tests/test_meta.py": PJ_TEST},
                      {"mypkg/package.json": '{"version": ""}\n', "tests/test_meta.py": PJ_TEST.replace("'1.0'", "''")},
                      "from mypkg.meta import version; print('RESULT', repr(version()))", "nested-package-json")
    assert "RESULT ''" in res.stdout
    assert pp["verdict"]["state"] != "supported", summary(pp)
