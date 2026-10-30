"""`verify --run --deadline S`: one wall-clock budget for the whole run.

A hang costs no more than the budget (held-out-6: a project verify cannot split
paid the 1800 s full-suite cap per hang). The budget never extends any limit,
and what it cuts is never a pass: a run it cuts is "not verified", unless a
new failure was already observed (a regression stays a regression)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import CMD, _git, _write, needs_sandbox

from repo_ai.verify import evidence

PASSING = evidence.PASSING_VERDICTS
TEST = ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")


def _project(tmp_path: Path, n: int = 2) -> Path:
    root = tmp_path / "p"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n", "tests/__init__.py": ""}
    files.update({f"tests/test_c{i}.py": TEST.replace("test_add", f"test_add{i}") for i in range(n)})
    _write(root, files)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _run(root: Path, *extra: str) -> tuple[int, dict, float]:
    t = time.monotonic()
    out = run_cli(root, "verify", "--run", "--json", "--rerun", "--test-command", CMD, *extra)
    assert out.stdout, out.stderr
    return out.returncode, json.loads(out.stdout)["evidence"], time.monotonic() - t


def test_the_budget_never_lets_a_cut_run_pass():
    cut = [{"test": "t.py", "status": "timeout", "deadline": True, "baseline": "pass"}]
    v = evidence.verdict(cut, None, 1, False, incomplete="the time budget of 5 s ran out before every test ran")
    assert v.startswith("not verified: the time budget") and not evidence.is_passing(v)
    real = cut + [{"test": "u.py", "status": "fail", "baseline": "pass"}]
    assert evidence.verdict(real, None, 2, False, incomplete="x") == "regression"
    ok = [{"test": "u.py", "status": "pass"}]
    assert evidence.verdict(ok, None, 1, False, incomplete="x") == "not verified: x"


@needs_sandbox
def test_a_hanging_change_costs_no_more_than_the_budget(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text("import time\n\n\ndef add(a, b):\n    time.sleep(120)\n    return a + b\n")
    code, ev, wall = _run(root, "--deadline", "8")
    assert code == 1 and ev["verdict"].startswith("not verified: the time budget of 8 s"), ev["verdict"]
    assert wall < 40, wall  # the budget, the base comparison it leaves no time for, and verify's fixed cost
    assert ev["deadline_s"] == 8


@needs_sandbox
def test_a_generous_budget_changes_nothing(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    code, ev, _ = _run(root, "--deadline", "300")
    assert code == 0 and ev["verdict"].startswith(PASSING), ev["verdict"]
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")
    code, ev, _ = _run(root, "--deadline", "300")
    assert code == 1 and ev["verdict"] == "regression", ev["verdict"]


def test_the_budget_needs_run_and_a_positive_value(tmp_path: Path):
    root = _project(tmp_path)
    for extra in (["--deadline", "5"], ["--run", "--deadline", "0"], ["--run", "--deadline", "-3"],
                  ["--run", "--deadline", "inf"], ["--run", "--deadline", "nan"], ["--run", "--record", "--deadline", "9"]):
        out = run_cli(root, "verify", "--test-command", CMD, *extra)
        assert out.returncode != 0 and "--deadline" in out.stderr, out.stderr


@needs_sandbox
def test_a_confirmation_the_budget_cut_is_never_a_regression(tmp_path: Path):
    """An order-dependent failure (test_b fails only after test_a ran in the same process) is
    'failing (only next to other test files ...)' once its confirmation runs. When the budget leaves
    no time for that confirmation, the failure is unconfirmed, not a regression."""
    root = tmp_path / "o"
    _write(root, {
        "pkg/__init__.py": "", "pkg/core.py": "def val():\n    return 1\n", "tests/__init__.py": "",
        "tests/test_a.py": ("import os\nimport time\nimport unittest\nfrom pkg.core import val\n\n\n"
                            "class A(unittest.TestCase):\n    def test_a(self):\n        time.sleep(2)\n"
                            "        os.environ['ORDER_DEP'] = '1'\n        self.assertEqual(val(), 1)\n"),
        "tests/test_b.py": ("import os\nimport unittest\nfrom pkg.core import val\n\n\n"
                            "class B(unittest.TestCase):\n    def test_b(self):\n"
                            "        self.assertNotIn('ORDER_DEP', os.environ)\n        self.assertEqual(val(), 1)\n"),
    })
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "pkg" / "core.py").write_text("def val():\n    return 2 - 1\n")
    first = run_cli(root, "verify", "--run", "--json", "--workers", "1", "--test-command", CMD)
    assert json.loads(first.stdout)["evidence"]["verdict"].startswith("failing (only next to"), first.stdout[-300:]
    seen = set()
    for budget in ("2.6", "2.8", "3.0", "3.2"):
        out = run_cli(root, "verify", "--run", "--json", "--rerun", "--workers", "1", "--deadline", budget,
                      "--test-command", CMD)
        v = json.loads(out.stdout)["evidence"]["verdict"]
        seen.add(v)
        assert v != "regression" and not v.startswith(PASSING), (budget, v)
    assert seen, seen
