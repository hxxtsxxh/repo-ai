"""The false proofs Session A reproduced at 8288b2f (PR #24, comment
6402441378), at the unit level, with the adjacent cases each fix must not
break. The end-to-end probes are vendored as tests/test_sa_redteam_*.py.

* S1, S2d, S17: a claim that is not established never carries a level above
  `not_established` (`passport._align`);
* S1, S2d, S5: the scenario must also pass on the whole working tree as it
  ships (`experiment.judge_shipped`); data next to the code under test that
  the run left out keeps the claim incomplete (`experiment.data_near`);
* S17: the base's own tests also run on the base plus every code edit
  (`experiment.merge_code_check`);
* G4: a scenario that feeds the code under test's values into unchanged
  code abstains (`dataflow.findings`);
* E1: every export of a passport that is not fresh supports nothing
  (`passport.export_view`, `contract.fresh_view`).
"""

from __future__ import annotations

import json

import pytest

from repo_ai.prove import contract, dataflow, experiment, passport, render

LEVEL_TOP = "supported_by_controlled_comparison"


def _rec(level: str = LEVEL_TOP) -> dict:
    return {"claim": {"level": level, "text": "x", "not_established": list(contract.MINIMUM_NOT_ESTABLISHED)},
            "freshness": {"state": "fresh", "environment_key": "k"}}


# ------------------------------------------------------------------ the level follows the verdict
@pytest.mark.parametrize("state", [s for s in passport.STATES if s != "supported"])
def test_a_claim_that_is_not_established_carries_no_level(state: str):
    rec = _rec()
    v = {"state": state, "supported": False, "headline": "", "reasons": ["why"]}
    passport._align(v, rec)
    assert v["level"] == rec["claim"]["level"] == "not_established"
    assert rec["claim"]["scenario_level"] == LEVEL_TOP and rec["claim"]["text"] == "nothing is claimed"


def test_a_supported_claim_keeps_its_level():
    rec = _rec()
    v = {"state": "supported", "supported": True, "headline": "", "reasons": []}
    passport._align(v, rec)
    assert v["level"] == rec["claim"]["level"] == LEVEL_TOP and "scenario_level" not in rec["claim"]


def test_an_abstention_makes_the_claim_incomplete():
    ok = {"state": "reproduced"}, {"state": "passed"}, {"state": "none-detected", "files": []}, \
        {"state": "none-detected"}, {"unchanged": True}
    assert passport.decide(None, *ok)["state"] == "supported"
    v = passport.decide(None, *ok, abstain=["the scenario feeds the change's values to unchanged code"])
    assert v["state"] == "incomplete" and not v["supported"] and any("unchanged code" in r for r in v["reasons"])


# ------------------------------------------------------------------ the candidate as shipped
def _runs(outcomes: dict[str, str], n: int = 2) -> list[dict]:
    return [{"trusted": True, "reason": "", "outcomes": dict(outcomes), "failures": {}} for _ in range(n)]


def _judged(outcomes: dict[str, str]) -> dict:
    return experiment.judge_candidate(_runs(outcomes), _runs({"t": "fail"}), ["t"], [])


SUBJ = {"left_out": ["mypkg/__init__.py"]}


def test_the_whole_working_tree_must_pass_the_scenario_too():
    c = experiment.judge_shipped(_judged({"t": "pass"}), _judged({"t": "fail"}), SUBJ)
    assert c["state"] == "failed" and "as shipped" in c["why"] and "mypkg/__init__.py" in c["why"]
    assert c["shipped"]["state"] == "failed"


def test_a_shipped_run_that_is_incomplete_or_differs_is_not_a_pass():
    bad = experiment.judge_candidate([{"trusted": False, "reason": "timed out", "outcomes": {}, "failures": {}}],
                                     _runs({"t": "fail"}), ["t"], [])
    assert experiment.judge_shipped(_judged({"t": "pass"}), bad, SUBJ)["state"] == "incomplete"
    two = experiment.judge_shipped(_judged({"t": "pass"}), _judged({"t": "pass", "u": "pass"}), SUBJ)
    assert two["state"] == "incomplete" and "differs" in two["why"]


def test_both_passing_the_same_way_is_a_pass_and_a_failure_stays_a_failure():
    assert experiment.judge_shipped(_judged({"t": "pass"}), _judged({"t": "pass"}), SUBJ)["state"] == "passed"
    assert experiment.judge_shipped(_judged({"t": "fail"}), _judged({"t": "pass"}), SUBJ)["state"] == "failed"


def test_every_edit_but_tests_docs_and_root_configuration_is_outside_the_subject():
    left = ["mypkg/defaults.json", "conf/strs.json", "mypkg/testing.py", "mypkg/defaults.toml", "strs.py",
            "README.md", "docs/guide.md", "pyproject.toml", "tests/test_strs.py", "tests/data/golden.json",
            "tests/helpers.py", "conftest.py", "CHANGELOG", ".gitignore", ".repo-ai/config.toml", "check_strs.py"]
    assert experiment.outside_subject(left, {"tests/test_strs.py", "check_strs.py"}) == [
        "conf/strs.json", "mypkg/defaults.json", "mypkg/defaults.toml", "mypkg/testing.py", "strs.py"]


# ------------------------------------------------------------------ the second regression tree
def test_a_regression_on_the_base_plus_every_code_edit_is_detected():
    ed = {"state": "none-detected", "files": [], "tests": 3}
    wide = {"state": "detected", "files": [{"path": "tests/test_strs.py", "state": "detected",
                                            "new_failures": ["test_shout"], "superseded": [], "messages": {}}]}
    out = experiment.merge_code_check(ed, wide)
    assert out["state"] == "detected" and out["files"][0]["with_all_code_edits"]
    v = passport.decide(None, {"state": "reproduced"}, {"state": "passed"}, out, {"state": "none-detected"},
                        {"unchanged": True})
    assert v["state"] == "regressions-detected"


def test_an_incomplete_second_tree_never_reads_as_none_detected():
    out = experiment.merge_code_check({"state": "none-detected", "files": []},
                                      {"state": "incomplete", "why": "timed out", "files": []})
    assert out["state"] == "incomplete"
    same = experiment.merge_code_check({"state": "none-detected", "files": []},
                                       {"state": "none-detected", "files": []})
    assert same["state"] == "none-detected"


# ------------------------------------------------------------------ G4: the scenario's input
MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
SAMPLES = {"mypkg/__init__.py": MEAN, "mypkg/samples.py": "def empty():\n    return [0]\n"}


def _find(files: dict[str, str], subject: list[str], scen: str = "tests/test_accept.py", kind: str = "pytest"):
    data = {k: v.encode() for k, v in files.items()}
    return dataflow.findings(scen, kind, set(data), data.get, set(subject))


@pytest.mark.parametrize("scenario,extra", [
    ("from mypkg import mean\nfrom mypkg.samples import empty\n\ndef test_e():\n    assert mean(empty()) == 0\n", {}),
    ("import mypkg.samples\nfrom mypkg import mean\n\ndef test_e():\n    assert mean(mypkg.samples.empty()) == 0\n",
     {}),
    ("from mypkg import mean\nfrom mypkg.samples import empty\n\ndef test_e():\n    xs = empty()\n    ys = xs\n"
     "    assert mean(xs=ys) == 0\n", {}),
    ("from mypkg import mean\n\ndef test_e(data):\n    assert mean(data) == 0\n",
     {"tests/conftest.py": "import pytest\nfrom mypkg.samples import empty\n\n@pytest.fixture\ndef data():\n"
                           "    return empty()\n"}),
    ("import unittest\nfrom mypkg import mean, samples\n\nclass T(unittest.TestCase):\n    @classmethod\n"
     "    def setUpClass(cls):\n        cls.xs = samples.empty()\n    def test_e(self):\n"
     "        self.assertEqual(mean(self.xs), 0)\n", {}),
    ("from tests.helpers import data\nfrom mypkg import mean\n\ndef test_e():\n    assert mean(data()) == 0\n",
     {"tests/__init__.py": "", "tests/helpers.py": "from mypkg.samples import empty\n\ndef data():\n"
                                                   "    return empty()\n"}),
    ("from mypkg.calc import Calc\nfrom mypkg.samples import empty\n\ndef test_e():\n    c = Calc()\n"
     "    assert c.mean(empty()) == 0\n", {"mypkg/calc.py": "class Calc:\n    def mean(self, xs):\n        return 0\n"}),
], ids=["direct", "dotted", "aliased-kwarg", "fixture", "unittest-class", "test-helper", "method"])
def test_a_value_from_the_code_under_test_fed_to_unchanged_code_abstains(scenario: str, extra: dict):
    found = _find({**SAMPLES, **extra, "tests/test_accept.py": scenario}, ["mypkg/samples.py"])
    assert found and any("passes a value of the repository" in f or "more than one entry point" in f
                         for f in found), found


def test_a_re_exported_helper_is_followed_to_its_module():
    files = {"mypkg/__init__.py": "from .samples import empty\n" + MEAN,
             "mypkg/samples.py": "def empty():\n    return [0]\n",
             "tests/test_accept.py": "from mypkg import mean, empty\n\ndef test_e():\n    assert mean(empty()) == 0\n"}
    assert _find(files, ["mypkg/samples.py"])


def test_an_expected_value_from_the_code_under_test_abstains():
    files = {"mypkg/__init__.py": "", "mypkg/core.py": MEAN + "EMPTY = 0\n",
             "tests/test_accept.py": "from mypkg import core\n\ndef test_e():\n    assert core.mean([]) == core.EMPTY\n"}
    assert "expected value" in _find(files, ["mypkg/core.py"])[0]


def test_values_from_two_changed_modules_abstain():
    files = {"mypkg/__init__.py": "", "mypkg/core.py": MEAN, "mypkg/samples.py": "def empty():\n    return [0]\n",
             "tests/test_accept.py": "from mypkg.core import mean\nfrom mypkg.samples import empty\n\n"
                                     "def test_e():\n    assert mean(empty()) == 0\n"}
    assert any("more than one entry point" in f for f in _find(files, ["mypkg/core.py", "mypkg/samples.py"]))


@pytest.mark.parametrize("scenario", [
    "import importlib\nm = importlib.import_module('mypkg.samples')\n\ndef test_e():\n    assert m.empty() == []\n",
    "from mypkg.samples import *\n\ndef test_e():\n    assert empty() == []\n",
])
def test_names_that_cannot_be_followed_abstain(scenario: str):
    assert _find({**SAMPLES, "tests/test_accept.py": scenario}, ["mypkg/samples.py"])


@pytest.mark.parametrize("files,subject", [
    # the textbook fix: the scenario calls the package, which re-exports the fixed function, with literal inputs
    ({"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": MEAN,
      "tests/test_accept.py": "from mypkg import mean\n\ndef test_e():\n    assert mean([]) == 0\n"}, ["mypkg/core.py"]),
    # an unchanged checker (pytest, a test helper, the standard library) receiving the result is the oracle
    ({"mypkg/__init__.py": "", "mypkg/core.py": MEAN, "tests/__init__.py": "",
      "tests/helpers.py": "def close(a, b):\n    return abs(a - b) < 1e-9\n",
      "tests/test_accept.py": "import math\nimport pytest\nfrom mypkg.core import mean\nfrom tests.helpers import close\n\n"
                              "def test_e():\n    r = mean([])\n    assert r == pytest.approx(0)\n    assert close(r, 0)\n"
                              "    assert math.isclose(r, 0)\n    assert len(str(r)) == 1\n"}, ["mypkg/core.py"]),
    # a result compared with a literal
    ({"mypkg/__init__.py": "", "mypkg/core.py": MEAN,
      "tests/test_accept.py": "from mypkg.core import mean\n\ndef test_e():\n    assert mean([]) == 0\n"}, ["mypkg/core.py"]),
])
def test_a_scenario_that_checks_the_code_under_test_directly_does_not_abstain(files: dict, subject: list[str]):
    assert _find(files, subject) == []


def test_two_results_of_the_changed_code_compared_with_each_other_abstain():
    """Neither side is an independent expectation (the documented cost)."""
    files = {"mypkg/__init__.py": "", "mypkg/core.py": MEAN,
             "tests/test_accept.py": "from mypkg.core import mean\n\ndef test_e():\n    assert mean([2]) == mean([1, 3])\n"}
    assert _find(files, ["mypkg/core.py"])


def test_a_genuine_fix_observed_through_unchanged_code_abstains_too():
    """The documented cost of the rule: inputs and outputs cannot be told apart."""
    files = {"mypkg/__init__.py": "", "mypkg/parse.py": "def parse(s):\n    return s\n",
             "mypkg/render.py": "def render(x):\n    return x\n",
             "tests/test_accept.py": "from mypkg.parse import parse\nfrom mypkg.render import render\n\n"
                                     "def test_e():\n    assert render(parse('a')) == 'a'\n"}
    assert _find(files, ["mypkg/parse.py"])


def test_node_scenarios_always_abstain():
    """JavaScript is not parsed, so no node claim is supported (the seventh review's CommonJS re-export)."""
    base = {"package.json": "{}", "lib/index.js": "", "lib/core.js": ""}
    for scen in ("import { mean } from '../lib/core.js';\n", "const { mean } = require('../lib/index.js');\n"):
        assert _find({**base, "test/a.test.js": scen}, ["lib/core.js"], "test/a.test.js", "node") == [
            dataflow.NODE_REASON]


# ------------------------------------------------------------------ E1: exports of a passport that is not fresh
def _pp() -> dict:
    v = {"state": "supported", "supported": True, "level": LEVEL_TOP, "headline": "CLAIM SUPPORTED", "reasons": []}
    return {"verdict": v, "evidence": [_rec()], "digest": "d" * 64, "path": "/local/x.json",
            "candidate": {"fingerprint": "f"}, "scenario": {"path": "tests/t.py", "sha256": "s" * 64},
            "baseline": {"commit": "c" * 40}, "claim": {"id": "c"}}


@pytest.mark.parametrize("state", ["stale", "unknown"])
def test_an_export_that_is_not_fresh_supports_nothing(state: str):
    pp = _pp()
    view = passport.export_view(pp, {"state": state, "reasons": ["the working tree changed"]})
    v = view["verdict"]
    assert v["state"] == "stale" and not v["supported"] and v["level"] == "not_established"
    assert v["recorded"] == {"state": "supported", "supported": True, "level": LEVEL_TOP, "headline": "CLAIM SUPPORTED"}
    assert view["freshness"]["state"] == state and "path" not in view
    pred = render.in_toto(view)["predicate"]
    assert pred["freshness"]["state"] == state and not pred["verdict"]["supported"]
    assert pp["verdict"]["supported"]  # the stored passport is not changed


def test_a_fresh_export_is_the_passport_verdict_exactly():
    pp = _pp()
    view = passport.export_view(pp, {"state": "fresh", "reasons": []})
    assert view["verdict"] == pp["verdict"] and render.in_toto(view)["predicate"]["verdict"] == pp["verdict"]


@pytest.mark.parametrize("state", ["stale", "unknown"])
def test_a_record_shown_while_not_fresh_is_not_established(state: str):
    out = contract.fresh_view(_rec(), state)
    assert out["claim"]["level"] == "not_established" and out["claim"]["recorded_level"] == LEVEL_TOP
    assert any(state in x for x in out["claim"]["not_established"])
    fresh = contract.fresh_view(_rec(), "fresh")
    assert fresh["claim"]["level"] == LEVEL_TOP and "recorded_level" not in fresh["claim"]
    json.dumps(out)  # still plain JSON


def _find_base(files: dict[str, str], base: dict[str, str], subject: list[str], scenario: str) -> list[str]:
    data = {k: v.encode() for k, v in {**files, "tests/test_accept.py": scenario}.items()}
    old = {**data, **{k: v.encode() for k, v in base.items()}}
    return dataflow.findings("tests/test_accept.py", "pytest", set(data), data.get, set(subject), read_base=old.get)


def test_state_a_changed_function_sets_up_for_another_abstains():
    cand = {"mypkg/__init__.py": MEAN,
            "mypkg/samples.py": "DATA = []\n\n\ndef empty():\n    DATA.append(0)\n    return None\n"}
    base = {"mypkg/samples.py": "DATA = []\n\n\ndef empty():\n    return None\n"}
    scen = "from mypkg import mean, samples\n\ndef test_e():\n    x = samples.empty()\n    assert mean(samples.DATA) == 0\n"
    assert any("more than one entry point" in f for f in _find_base(cand, base, ["mypkg/samples.py"], scen))


def test_a_changed_function_setting_up_another_module_abstains():
    cand = {"mypkg/__init__.py": "DATA = []\n" + MEAN,
            "mypkg/samples.py": "import mypkg\n\n\ndef empty():\n    mypkg.DATA.append(0)\n"}
    base = {"mypkg/samples.py": "import mypkg\n\n\ndef empty():\n    pass\n"}
    scen = "import mypkg\nfrom mypkg import samples\n\ndef test_e():\n    samples.empty()\n    assert mypkg.mean(mypkg.DATA) == 0\n"
    assert any("more than one entry point" in f for f in _find_base(cand, base, ["mypkg/samples.py"], scen))


def test_a_fix_with_its_own_cache_and_unchanged_symbols_is_followed():
    core = ("import enum\n\n\nclass Status(enum.Enum):\n    OK = 1\n\n\n_C = {}\n\n\ndef mean(xs):\n    k = tuple(xs)\n"
            "    if k not in _C:\n        _C[k] = sum(xs) / len(xs) if xs else 0\n    return _C[k]\n")
    base = core.replace(" if xs else 0", "")
    scen = ("from mypkg.core import Status, mean\n\ndef test_e():\n    assert mean([]) == 0\n"
            "    assert Status.OK is Status.OK\n")
    assert _find_base({"mypkg/__init__.py": "", "mypkg/core.py": core}, {"mypkg/core.py": base},
                      ["mypkg/core.py"], scen) == []


def test_import_time_code_the_change_edits_abstains():
    cand = {"mypkg/__init__.py": MEAN, "mypkg/samples.py": "import mypkg\n\nmypkg.mean = lambda xs: 0\n"}
    base = {"mypkg/samples.py": "import mypkg\n"}
    scen = "from mypkg import mean\nimport mypkg.samples\n\ndef test_e():\n    assert mean([]) == 0\n"
    assert "imported" in _find_base(cand, base, ["mypkg/samples.py"], scen)[0]


def test_an_optional_import_with_a_fallback_is_not_import_time_code():
    """The seventh review's false negative: `try: from math import fsum / except ImportError: fsum = sum`."""
    core = "try:\n    from math import fsum\nexcept ImportError:\n    fsum = sum\n\n\ndef mean(xs):\n" \
           "    return fsum(xs) / len(xs) if xs else 0\n"
    base = "def mean(xs):\n    return sum(xs) / len(xs)\n"
    scen = "from mypkg.core import mean\n\ndef test_e():\n    assert mean([]) == 0\n"
    assert _find_base({"mypkg/__init__.py": "", "mypkg/core.py": core}, {"mypkg/core.py": base}, ["mypkg/core.py"],
                      scen) == []


@pytest.mark.parametrize("scenario", [
    # the seventh review: an exception's arguments, a match capture, a registry, a set-up call, an environment variable
    "from mypkg import mean\nfrom mypkg.samples import empty\n\ndef test_e():\n    try:\n        empty()\n"
    "    except LookupError as e:\n        xs = e.args[0]\n    assert mean(xs) == 0\n",
    "from mypkg import mean\nfrom mypkg.samples import empty\n\ndef test_e():\n    match {'v': empty()}:\n"
    "        case {'v': xs}:\n            assert mean(xs) == 0\n",
    "from mypkg import mean\nfrom mypkg.samples import get\n\ndef test_e():\n    assert mean(get('empty')) == 0\n",
    "from mypkg import mean\nfrom mypkg import samples\n\ndef test_e():\n    samples.prepare()\n    assert mean([]) == 0\n",
    "from mypkg import mean\nfrom mypkg.samples import configure\n\ndef test_e():\n    assert configure() is None\n"
    "    assert mean([]) == 0\n",
], ids=["except", "match", "registry", "set-up-call", "consumed-set-up"])
def test_a_second_entry_point_or_a_repository_value_as_input_abstains(scenario: str):
    files = {**SAMPLES, "mypkg/samples.py": "def empty():\n    return [0]\n\ndef get(n):\n    return [0]\n\n"
                                            "def prepare():\n    pass\n\ndef configure():\n    pass\n"}
    assert _find({**files, "tests/test_accept.py": scenario}, ["mypkg/samples.py"])


@pytest.mark.parametrize("scenario", [
    "from mypkg.calc import Calc\n\ndef test_e():\n    c = Calc()\n    assert c.mean([]) == 0\n    assert c.count == 1\n",
    "import unittest\nfrom mypkg.calc import Calc\n\nclass T(unittest.TestCase):\n    def setUp(self):\n"
    "        self.c = Calc()\n    def test_e(self):\n        self.assertEqual(self.c.mean([]), 0)\n",
    "import pytest\nfrom mypkg.calc import Calc\n\n@pytest.fixture\ndef calc():\n    return Calc()\n\n"
    "def test_e(calc):\n    assert calc.mean([]) == pytest.approx(0)\n",
    "import pytest\nfrom mypkg.calc import Calc, CalcError\n\ndef test_e():\n    with pytest.raises(CalcError):\n"
    "        Calc().mean(None)\n",
], ids=["object", "unittest-setup", "fixture-object", "raises"])
def test_one_class_with_its_methods_is_one_entry_point(scenario: str):
    files = {"mypkg/__init__.py": "", "mypkg/calc.py": "class CalcError(ValueError):\n    pass\n\n\nclass Calc:\n"
             "    count = 0\n\n    def mean(self, xs):\n        return 0\n"}
    assert _find({**files, "tests/test_accept.py": scenario}, ["mypkg/calc.py"]) == [], scenario
