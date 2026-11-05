# Vendored from Session A's red team (#59; branch redteam/prooflab-8288b2f at 98aabc7, test_scope_903984a.py), unchanged
# except the helper import, the sandbox skip guard and the two strict xfail markers: 1d and 1e are open false proofs ProofLab names.
"""Executed checks of the read-only review's ProofLab scope findings on main 903984a.
Each asserts the SAFE result (never `supported` for a false claim), so it FAILS on a false proof.
A control (a genuine fix inside the declared scope) must stay supported."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, make_repo, pin_and_run, shipped, summary, write  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox backend to run tests in")


def _outside(tmp: Path, text: str) -> Path:
    p = tmp / "reviewer" / "test_accept.py"
    write(p.parent, {"test_accept.py": text})
    return p


def _never_supported(pp: dict, tag: str) -> None:
    assert pp["verdict"]["state"] != "supported", f"{tag}: FALSE PROOF: {summary(pp)}"


SESSION_BUGGY = ("import contextlib\n\n\nclass S:\n    def get(self, k):\n        return 1\n\n\n"
                 "@contextlib.contextmanager\ndef session():\n    yield S()\n")
SESSION_SWALLOW = ("import contextlib\n\n\nclass S:\n    def get(self, k):\n        return 1\n\n\n"
                   "@contextlib.contextmanager\ndef session():\n    try:\n        yield S()\n"
                   "    except Exception:\n        pass  # log and carry on\n")


@pytest.mark.xfail(strict=True, reason="open false proof (#59 1d, Session A): an assertion swallowed by an edited context "
                   "manager; ProofLab is experimental and not certified, and names it in every passport")
def test_1d_an_assertion_swallowed_by_an_edited_context_manager(tmp_path: Path):
    """The change makes `session()` swallow exceptions (a plausible mistake); `get` is still wrong."""
    root = make_repo(tmp_path / "r", {"pkg/__init__.py": "", "pkg/db.py": SESSION_BUGGY,
                                      "tests/test_db.py": "from pkg.db import session\n\n\ndef test_ok():\n"
                                                          "    with session() as s:\n        assert s.get(0) == 1\n"})
    write(root, {"pkg/db.py": SESSION_SWALLOW})
    res = shipped(root, "from pkg.db import session\nwith session() as s: print('RESULT', s.get(1))")
    assert "RESULT 1" in res.stdout  # still returns 1, the claim (get(1) == 2) is false
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, "from pkg.db import session\n\n\n"
                        "def test_get():\n    with session() as s:\n        assert s.get(1) == 2\n"), *PT,
                        "--subject", "pkg/db.py")
    print("SUMMARY", summary(pp))
    _never_supported(pp, "1d")


BUGGY = "def mean(xs):\n    return sum(xs) / len(xs)\n"


@pytest.mark.xfail(strict=True, reason="open false proof (#59 1e, Session A): importorskip leaves zero entry points; "
                   "ProofLab is experimental and not certified, and names it in every passport")
def test_1e_importorskip_gives_zero_entry_points(tmp_path: Path):
    """The scenario reaches the code through `pytest.importorskip` (a common idiom) and passes a module
    constant the change edits; the code under test is not fixed."""
    root = make_repo(tmp_path / "r", {"pkg/__init__.py": "", "pkg/stats.py": BUGGY, "pkg/cfg.py": "EMPTY = []\n",
                                      "tests/test_stats.py": "from pkg.stats import mean\n\n\ndef test_m():\n"
                                                             "    assert mean([2, 4]) == 3\n"})
    write(root, {"pkg/cfg.py": "EMPTY = [0]\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, "import pytest\n\n\ndef test_empty():\n"
                        "    stats = pytest.importorskip('pkg.stats')\n    cfg = pytest.importorskip('pkg.cfg')\n"
                        "    assert stats.mean(cfg.EMPTY) == 0\n"), *PT, "--subject", "pkg/*")
    print("SUMMARY", summary(pp))
    _never_supported(pp, "1e")


def test_1c_a_repo_value_stored_as_an_attribute(tmp_path: Path):
    """A repo constant the change edits is stored on the returned object instead of passed as an argument."""
    stats = ("class Stats:\n    data = None\n\n    def mean(self):\n"
             "        return sum(self.data) / len(self.data)\n")
    root = make_repo(tmp_path / "r", {"pkg/__init__.py": "", "pkg/stats.py": stats, "pkg/cfg.py": "EMPTY = []\n",
                                      "tests/test_stats.py": "from pkg.stats import Stats\n\n\ndef test_m():\n"
                                                             "    t = Stats()\n    t.data = [2, 4]\n    assert t.mean() == 3\n"})
    write(root, {"pkg/cfg.py": "EMPTY = [0]\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, "from pkg.cfg import EMPTY\n"
                        "from pkg.stats import Stats\n\n\ndef test_empty():\n    t = Stats()\n    t.data = EMPTY\n"
                        "    assert t.mean() == 0\n"), *PT, "--subject", "pkg/*")
    print("SUMMARY", summary(pp))
    _never_supported(pp, "1c")


def test_control_a_genuine_fix_in_scope_is_supported(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"pkg/__init__.py": "", "pkg/stats.py": BUGGY,
                                      "tests/test_stats.py": "from pkg.stats import mean\n\n\ndef test_m():\n"
                                                             "    assert mean([2, 4]) == 3\n"})
    write(root, {"pkg/stats.py": "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, "from pkg.stats import mean\n\n\n"
                        "def test_empty():\n    assert mean([]) == 0\n"), *PT, "--subject", "pkg/stats.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] == "supported", summary(pp)
