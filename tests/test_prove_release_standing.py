# Vendored from the independent review of the release-freeze code (2026-10-26): ProofLab's standing on every
# surface (status, list, an old passport's JSON report), and a full prove + verify + uninstall leaves nothing.
"""Freeze review: ProofLab standing on every surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import run_cli  # noqa: E402
from test_verify_adaptive import _git, _write  # noqa: E402
from test_verify_engine import _host_sandbox  # noqa: E402

from repo_ai.prove import passport  # noqa: E402

HOST = _host_sandbox()
needs = pytest.mark.skipif(not HOST, reason="no sandbox")

GOOD = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
ACCEPT = ("import unittest\nfrom calc import mean\n\n\nclass Accept(unittest.TestCase):\n"
          "    def test_mean_of_empty_is_zero(self):\n        self.assertEqual(mean([]), 0)\n")


def cli(root, *a, home):
    return run_cli(root, *a, env={"REPO_AI_HOME": str(home), "PATH": "/usr/bin:/bin"})


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "calc"
    home = tmp_path / "home"
    _write(root, {"calc/__init__.py": GOOD.replace(" if xs else 0", ""), "tests/__init__.py": "",
                  "tests/test_calc.py": "import unittest\nfrom calc import mean\n\n\nclass T(unittest.TestCase):\n"
                                        "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n"})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert cli(root, "init", "--agent", "none", "-q", home=home).returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "tests" / "test_accept.py").write_text(ACCEPT)
    pin = cli(root, "prove", "pin", "empty", "--claim", "mean([]) returns 0", "--scenario",
              "tests/test_accept.py", "--subject", "calc/__init__.py", home=home)
    assert pin.returncode == 0, pin.stderr
    (root / "calc" / "__init__.py").write_text(GOOD)
    return root, home


@needs
def test_status_json_names_the_false_proof(repo):
    root, home = repo
    r = cli(root, "prove", "run", "empty", "--json", home=home)
    pp = json.loads(r.stdout)
    assert pp["verdict"]["state"] == "supported", pp["verdict"]
    st = cli(root, "prove", "status", "empty", "--json", home=home)
    print(st.stdout)
    data = json.loads(st.stdout)
    assert data["supported"] is True
    assert "always-equal-class" in st.stdout, "prove status --json: supported:true, no false-proof name"


@needs
def test_status_text_names_the_false_proof(repo):
    root, home = repo
    cli(root, "prove", "run", "empty", "--json", home=home)
    st = cli(root, "prove", "status", "empty", home=home)
    print(st.stdout)
    assert "EXPERIMENTAL" in st.stdout
    assert "always-equal-class" in st.stdout


def _rewrite_as_old(root: Path) -> Path:
    files = sorted((root / ".repo-ai" / "state" / "prove" / "passports" / "empty").glob("2*.json"))
    p = files[-1]
    pp = json.loads(p.read_text())
    pp.pop("experimental", None)
    pp["limitations"] = [x for x in pp["limitations"] if not x.startswith(("EXPERIMENTAL", "KNOWN FALSE"))]
    pp["verdict"]["headline"] = pp["verdict"]["headline"].replace(" (EXPERIMENTAL, not certified)", "")
    for rec in pp.get("evidence") or []:
        rec["claim"]["not_established"] = [x for x in rec["claim"]["not_established"]
                                           if "experimental" not in x and "false proof" not in x]
    pp["repo_ai_version"] = "0.7.7"
    pp["digest"] = passport.digest(pp)
    p.write_text(json.dumps(pp))
    return p


@needs
def test_old_passport_json_report_states_standing(repo):
    root, home = repo
    cli(root, "prove", "run", "empty", "--json", home=home)
    _rewrite_as_old(root)
    md = cli(root, "prove", "report", "empty", home=home).stdout
    assert "always-equal-class" in md  # Markdown backfills
    toto = cli(root, "prove", "report", "empty", "--format", "in-toto", home=home).stdout
    assert "always-equal-class" in toto  # in-toto backfills
    js = cli(root, "prove", "report", "empty", "--format", "json", home=home)
    print(js.returncode, js.stdout[:300])
    assert "always-equal-class" in js.stdout, "report --format json on an old passport omits the standing"


@needs
def test_stale_markdown_leads_with_stale_and_keeps_standing(repo):
    root, home = repo
    cli(root, "prove", "run", "empty", "--json", home=home)
    (root / "calc" / "__init__.py").write_text(GOOD + "\n# edit\n")
    md = cli(root, "prove", "report", "empty", home=home)
    lines = [x for x in md.stdout.splitlines() if x.strip()]
    print(lines[:6])
    assert lines[1].startswith("**⚠️ STALE")
    assert "always-equal-class" in md.stdout and "EXPERIMENTAL, NOT CERTIFIED" in md.stdout
    js = json.loads(cli(root, "prove", "report", "empty", "--format", "json", home=home).stdout)
    assert js["verdict"]["supported"] is False and js["experimental"]["certified"] is False
    toto = json.loads(cli(root, "prove", "report", "empty", "--format", "in-toto", home=home).stdout)
    assert toto["predicate"]["experimental"]["known_false_proofs"][0]["id"] == "always-equal-class"
    assert toto["predicate"]["verdict"]["supported"] is False


@needs
def test_stopped_before_running_states_standing(repo):
    root, home = repo
    (root / "tests" / "test_accept.py").write_text(ACCEPT + "\n# changed\n")  # scenario-changed
    r = cli(root, "prove", "run", "empty", "--json", home=home)
    pp = json.loads(r.stdout)
    print(pp["verdict"]["state"], pp["limitations"][:2])
    assert pp["executed"] is False
    assert pp["limitations"][0].startswith("EXPERIMENTAL, NOT CERTIFIED")
    assert any("always-equal-class" in x for x in pp["limitations"])
    assert pp["experimental"]["certified"] is False
    t = cli(root, "prove", "run", "empty", home=home).stdout
    assert t.startswith("EXPERIMENTAL, NOT CERTIFIED") and "always-equal-class" in t.splitlines()[0]


@needs
def test_real_prove_and_verify_then_uninstall_leaves_nothing(repo):
    root, home = repo
    cli(root, "prove", "run", "empty", "--json", home=home)
    v = cli(root, "verify", "--run", home=home)
    print("verify rc", v.returncode, v.stderr[-200:])
    st = root / ".repo-ai" / "state"
    print(sorted(p.name for p in st.iterdir()))
    r = cli(root, "uninstall", "-y", home=home)
    assert r.returncode == 0, r.stderr
    left = sorted(p.relative_to(root).as_posix() for p in (root / ".repo-ai").rglob("*")) if (root / ".repo-ai").exists() else []
    assert left == [], left
