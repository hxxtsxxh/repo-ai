# Vendored from the sixth adversarial review of ProofLab (2026-10-25, on 473c41a), with the assertions of the
# static probes inverted to the safe result. Each end-to-end test asserts the safe result.
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")


def _outside(tmp_path, text):
    p = tmp_path / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


def test_conftest_autouse_seeds_shared_state_from_the_subject(tmp_path):
    """Unchanged tests/conftest.py seeds mypkg.config from mypkg/samples.py; the change edits samples only.
    Production mean([]) still returns None."""
    files = {"mypkg/__init__.py": "from . import config\n\n\ndef mean(xs):\n    if not xs:\n        return config.EMPTY\n"
                                  "    return sum(xs) / len(xs)\n",
             "mypkg/config.py": "EMPTY = None\n",
             "mypkg/samples.py": "def empty_default():\n    return None\n",
             "tests/conftest.py": "import pytest\nimport mypkg.config\nfrom mypkg.samples import empty_default\n\n\n"
                                  "@pytest.fixture(autouse=True)\ndef _seed():\n    mypkg.config.EMPTY = empty_default()\n",
             "tests/test_mean.py": "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"}
    root = make_repo(tmp_path / "r", files)
    write(root, {"mypkg/samples.py": "def empty_default():\n    return 0\n"})
    assert "RESULT None" in shipped(root, "from mypkg import mean; print('RESULT', mean([]))").stdout
    scen = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/samples.py")
    print("SUMMARY conftest-autouse", summary(pp), "abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_new_keyword_is_behaviour_not_load_failure(tmp_path):
    """The change adds a keyword; plain mean([]) still raises. The base fails with TypeError (new interface)."""
    base = "def mean(xs):\n    return sum(xs) / len(xs)\n"
    cand = "def mean(xs, empty=None):\n    if not xs and empty is not None:\n        return empty\n    return sum(xs) / len(xs)\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": base,
                                      "tests/test_mean.py": "from mypkg.core import mean\n\n\ndef test_mean():\n"
                                                            "    assert mean([1, 2, 3]) == 2\n"})
    write(root, {"mypkg/core.py": cand})
    assert "ZeroDivisionError" in shipped(root, "from mypkg.core import mean; mean([])").stderr
    scen = "from mypkg.core import mean\n\n\ndef test_empty():\n    assert mean([], empty=0) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/core.py")
    print("SUMMARY new-kwarg", summary(pp), "base kind", (pp.get("observations") or {}).get("baseline", {}).get("kind"))
    assert pp["verdict"]["state"] != "supported", summary(pp)


def test_false_negative_enum_genuine_fix(tmp_path):
    core = ("import enum\n\n\nclass Status(enum.Enum):\n    OK = 1\n    BAD = 2\n\n\n"
            "def parse_status(s):\n    return Status.OK if s == 'ok' else Status.BAD\n")
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "", "mypkg/core.py": core,
                                      "tests/test_core.py": "from mypkg.core import Status, parse_status\n\n\n"
                                                            "def test_ok():\n    assert parse_status('ok') == Status.OK\n"})
    write(root, {"mypkg/core.py": core.replace("s == 'ok'", "s.strip() == 'ok'")})  # the genuine fix
    scen = "from mypkg.core import Status, parse_status\n\n\ndef test_padded():\n    assert parse_status(' ok ') == Status.OK\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen), *PT, "--subject", "mypkg/core.py")
    print("SUMMARY enum-genuine", summary(pp), "abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] == "supported", summary(pp)
