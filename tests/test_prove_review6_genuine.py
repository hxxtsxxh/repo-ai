# Vendored from the sixth adversarial review of ProofLab (2026-10-25, on 473c41a), with the assertions of the
# static probes inverted to the safe result. Each end-to-end test asserts the safe result.
"""Genuine-fix scenarios (subject = mypkg/core.py, fixed): ProofLab must not abstain, except where the docs say
it does (a result handed to unchanged code)."""
import pytest
from repo_ai.prove import dataflow

CORE = ("import enum\n\n\nclass Status(enum.Enum):\n    OK = 1\n    BAD = 2\n\n\nclass EmptyError(ValueError):\n    pass\n\n\n"
        "def parse_status(s):\n    return Status.OK if s.strip() == 'ok' else Status.BAD\n\n\nDEFAULT = 0\n\n\n"
        "def mean(xs):\n    if not xs:\n        return DEFAULT\n    return sum(xs) / len(xs)\n")
CASES = {
    "enum_member": "from mypkg.core import Status, parse_status\n\n\ndef test_e():\n    assert parse_status(' ok ') == Status.OK\n",
    "enum_is": "from mypkg import core\n\n\ndef test_e():\n    assert core.parse_status(' ok ') is core.Status.OK\n",
    "exc_type": "import pytest\nfrom mypkg import core\n\n\ndef test_e():\n    with pytest.raises(core.EmptyError) as ei:\n        core.mean(None)\n"
                "    assert ei.type is core.EmptyError\n",
    "documented_default": "from mypkg import core\n\n\ndef test_e():\n    assert core.mean([]) == core.DEFAULT\n",
    "unittest_enum": "import unittest\nfrom mypkg.core import Status, parse_status\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_e(self):\n        self.assertEqual(parse_status(' ok '), Status.OK)\n",
    "json_dumps_result": "import json\nfrom mypkg.fmt import to_json\nfrom mypkg.core import mean\n\n\ndef test_e():\n"
                         "    assert to_json(mean([])) == '0'\n",
}

BASE_CORE = CORE.replace("s.strip() == 'ok'", "s == 'ok'").replace("    if not xs:\n        return DEFAULT\n", "")
# the documented cost: a result handed to other repository code (to_json), and a module constant as the expected
# value (the code could set it: only literals, enum members and classes are independent expectations)
ABSTAINS = {"json_dumps_result", "documented_default"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_genuine_fix_checked_against_unchanged_symbols_is_followed(name):
    files = {"mypkg/__init__.py": "", "mypkg/core.py": CORE,
             "mypkg/fmt.py": "import json\n\n\ndef to_json(x):\n    return json.dumps(x)\n",
             "tests/test_accept.py": CASES[name]}
    data = {k: v.encode() for k, v in files.items()}
    base = {**data, "mypkg/core.py": BASE_CORE.encode()}
    found = dataflow.findings("tests/test_accept.py", "pytest", set(data), data.get, {"mypkg/core.py"},
                              read_base=base.get)
    assert bool(found) == (name in ABSTAINS), found
