# Vendored from the seventh adversarial review of ProofLab (2026-10-25, on 0ec0516). Each test asserts the safe
# result, except where noted (a genuine fix that must stay supported).
"""Round-7 probes, batch 4: scenario-side binding forms the dataflow pass does not follow."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")

MEAN = "def mean(xs):\n    return sum(xs) / len(xs)\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"


def _outside(tmp_path, text, name="test_accept.py"):
    p = tmp_path / "reviewer" / name
    write(p.parent, {name: text})
    return p


@pytest.mark.parametrize("form", ["except", "match"])
def test_g4_value_bound_by_except_or_match(tmp_path, form):
    if form == "except":
        base = "def empty():\n    raise LookupError([])\n"
        scen = ("from mypkg import mean\nfrom mypkg.samples import empty\n\n\ndef test_empty():\n    try:\n"
                "        empty()\n    except LookupError as e:\n        xs = e.args[0]\n    assert mean(xs) == 0\n")
    else:
        base = "def empty():\n    return []\n"
        scen = ("from mypkg import mean\nfrom mypkg.samples import empty\n\n\ndef test_empty():\n"
                "    match {'v': empty()}:\n        case {'v': xs}:\n            assert mean(xs) == 0\n")
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": MEAN, "mypkg/samples.py": base, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/samples.py": base.replace("[]", "[0]")})
    assert "ZeroDivisionError" in shipped(root, "from mypkg import mean; mean([])").stderr
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    print("SUMMARY", form, summary(pp), "| abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", summary(pp)
