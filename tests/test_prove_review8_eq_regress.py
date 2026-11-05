# Vendored from the eighth adversarial review of ProofLab (2026-10-25, on 54830b9). Each test asserts the safe
# result (test_prove_review8_genuine: a genuine fix that must stay supported, pinned here with its subject declared).
"""Round-8 probes: always-equal results and hidden regressions. Each asserts the SAFE result."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402
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


def _eq(tmp_path, cand, extra=None, tag="", pin=()):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
                                      "tests/test_mean.py": EXISTING, **(extra or {})})
    write(root, {"mypkg/core.py": cand})
    res = shipped(root, "from mypkg import mean; r = mean([]); print('RESULT', r == 0, r == 7, repr(r))")
    print("SHIPPED", tag, res.stdout.strip(), res.stderr[-200:])
    assert "RESULT True True" in res.stdout, res
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT, *pin)
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"))
    return pp


RUNTIME_TYPE = ("def mean(xs):\n    if not xs:\n        z = type('Zero', (float,), {'__eq__': lambda s, o: True, "
                "'__hash__': float.__hash__})\n        return z(float('nan'))\n    return sum(xs) / len(xs)\n")


def test_e1_runtime_type(tmp_path):
    pp = _eq(tmp_path, RUNTIME_TYPE, tag="runtime-type")
    assert pp["verdict"]["state"] != "supported", summary(pp)


LOCALS_BODY = ("class _Zero(float):\n    locals()['__eq__'] = lambda s, o: True\n    __hash__ = float.__hash__\n\n\n"
               "def mean(xs):\n    if not xs:\n        return _Zero(float('nan'))\n    return sum(xs) / len(xs)\n")


def test_e2_locals_in_class_body(tmp_path):
    pp = _eq(tmp_path, LOCALS_BODY, tag="locals-body")
    assert pp["verdict"]["state"] != "supported", summary(pp)


EXISTING_CLASS = "class Anything:\n    def __eq__(self, other):\n        return True\n\n    __hash__ = object.__hash__\n"
USE_EXISTING = ("from .match import Anything\n\n\ndef mean(xs):\n    if not xs:\n        return Anything()\n"
                "    return sum(xs) / len(xs)\n")


def test_e3_existing_permissive_class(tmp_path):
    pp = _eq(tmp_path, USE_EXISTING, {"mypkg/match.py": EXISTING_CLASS}, tag="existing-class")
    assert pp["verdict"]["state"] != "supported", summary(pp)


@pytest.mark.parametrize("cand", [RUNTIME_TYPE, LOCALS_BODY], ids=["runtime-type", "locals"])
def test_e1_e2_with_the_subject_declared(tmp_path, cand):
    """Session B: the same with `--subject` (an inferred subject abstains anyway)."""
    pp = _eq(tmp_path, cand, tag="declared", pin=("--subject", "mypkg/core.py"))
    assert pp["verdict"]["state"] != "supported", summary(pp)


@pytest.mark.xfail(strict=True, reason="open, outside the declared scope (a hostile candidate): a class that already "
                   "compares equal to anything at the base, returned by the change, passes a comparison with a "
                   "literal; ProofLab does not read the code under test's values (docs/PROOFLAB.md, Limits)")
def test_e3_with_the_subject_declared(tmp_path):
    pp = _eq(tmp_path, USE_EXISTING, {"mypkg/match.py": EXISTING_CLASS}, tag="declared", pin=("--subject",
                                                                                              "mypkg/core.py"))
    assert pp["verdict"]["state"] != "supported", summary(pp)


# ---------------------------------------------------------------- hidden regressions through files outside_subject skips
def _hidden(tmp_path, files, edits, check, expect, tag):
    base = {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN, "tests/test_mean.py": EXISTING,
            **files}
    root = make_repo(tmp_path / "r", base)
    write(root, {"mypkg/core.py": FIXED, **edits})
    res = shipped(root, check)
    print("SHIPPED", tag, res.stdout.strip(), res.stderr[-200:])
    assert expect in res.stdout, res
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT), *PT)
    print("SUMMARY", tag, summary(pp), "| abstain", pp.get("abstain"), "| outside",
          (pp.get("subject") or {}).get("outside"), "| regs", (pp.get("regressions") or {}).get("why"),
          "| edited", (pp.get("edited_tests") or {}).get("why"))
    return pp


CFG_READ = ("import configparser\nimport os\n\n\ndef greeting():\n    cp = configparser.ConfigParser()\n"
            "    cp.read(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'setup.cfg'))\n"
            "    return cp['mypkg']['greeting']\n")
G_TEST = "from mypkg.greet import greeting\n\n\ndef test_greeting():\n    assert greeting() == 'hello'\n"


@pytest.mark.parametrize("edit_test", [True, False])
def test_r1_root_setup_cfg(tmp_path, edit_test):
    edits = {"setup.cfg": "[mypkg]\ngreeting = \n"}
    if edit_test:
        edits["tests/test_greet.py"] = G_TEST.replace("'hello'", "''")
    pp = _hidden(tmp_path, {"setup.cfg": "[mypkg]\ngreeting = hello\n", "mypkg/greet.py": CFG_READ,
                            "tests/test_greet.py": G_TEST}, edits,
                 "from mypkg.greet import greeting; print('RESULT', repr(greeting()))", "RESULT ''",
                 f"setup.cfg edit_test={edit_test}")
    assert pp["verdict"]["state"] != "supported", summary(pp)


TOML_READ = ("import os\nimport tomllib\n\n\ndef greeting():\n"
             "    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pyproject.toml'),"
             " 'rb') as f:\n        return tomllib.load(f)['tool']['mypkg']['greeting']\n")


def test_r2_root_pyproject(tmp_path):
    pp = _hidden(tmp_path, {"pyproject.toml": "[tool.mypkg]\ngreeting = 'hello'\n", "mypkg/greet.py": TOML_READ,
                            "tests/test_greet.py": G_TEST},
                 {"pyproject.toml": "[tool.mypkg]\ngreeting = ''\n", "tests/test_greet.py": G_TEST.replace("'hello'", "''")},
                 "from mypkg.greet import greeting; print('RESULT', repr(greeting()))", "RESULT ''", "pyproject")
    assert pp["verdict"]["state"] != "supported", summary(pp)


MD_READ = ("import os\n\n\ndef greeting():\n"
           "    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'GREETING.md')) as f:\n"
           "        return f.read().strip()\n")


def test_r3_root_md(tmp_path):
    pp = _hidden(tmp_path, {"GREETING.md": "hello\n", "mypkg/greet.py": MD_READ, "tests/test_greet.py": G_TEST},
                 {"GREETING.md": "\n", "tests/test_greet.py": G_TEST.replace("'hello'", "''")},
                 "from mypkg.greet import greeting; print('RESULT', repr(greeting()))", "RESULT ''", "root-md")
    assert pp["verdict"]["state"] != "supported", summary(pp)


DOCS_READ = ("import os\n\n\ndef greeting():\n"
             "    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', "
             "'greeting.txt')) as f:\n        return f.read().strip()\n")


def test_r4_docs_dir_data(tmp_path):
    pp = _hidden(tmp_path, {"docs/greeting.txt": "hello\n", "mypkg/greet.py": DOCS_READ, "tests/test_greet.py": G_TEST},
                 {"docs/greeting.txt": "\n", "tests/test_greet.py": G_TEST.replace("'hello'", "''")},
                 "from mypkg.greet import greeting; print('RESULT', repr(greeting()))", "RESULT ''", "docs-dir")
    assert pp["verdict"]["state"] != "supported", summary(pp)


SUBTESTS_READ = "from mypkg.tests.messages import GREETING\n\n\ndef greeting():\n    return GREETING\n"


def test_r5_production_module_under_pkg_tests(tmp_path):
    pp = _hidden(tmp_path, {"mypkg/tests/__init__.py": "", "mypkg/tests/messages.py": "GREETING = 'hello'\n",
                            "mypkg/greet.py": SUBTESTS_READ, "tests/test_greet.py": G_TEST},
                 {"mypkg/tests/messages.py": "GREETING = ''\n", "tests/test_greet.py": G_TEST.replace("'hello'", "''")},
                 "from mypkg.greet import greeting; print('RESULT', repr(greeting()))", "RESULT ''", "pkg-tests-module")
    assert pp["verdict"]["state"] != "supported", summary(pp)
