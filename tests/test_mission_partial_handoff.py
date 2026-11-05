"""Provider A leaves verified partial work; provider B continues from it. Offline, simulated providers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conftest import run_cli
from test_provider_runtime import _make_fake_cli

TWO_BUGS = (
    "def apply_discount(price, pct):\n    return price - pct\n\n"
    "def add_tax(price, rate):\n    return price + rate\n"
)
FIX_DISCOUNT = (
    "def apply_discount(price, pct):\n    return price - price * pct / 100\n\n"
    "def add_tax(price, rate):\n    return price + rate\n"
)
FIX_BOTH = (
    "def apply_discount(price, pct):\n    return price - price * pct / 100\n\n"
    "def add_tax(price, rate):\n    return price + price * rate / 100\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                   check=True, capture_output=True)


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pricing.py").write_text(TWO_BUGS)
    (root / "test_pricing.py").write_text(
        "from pricing import apply_discount, add_tax\n\n"
        "def test_discount():\n    assert apply_discount(200, 10) == 180\n\n"
        "def test_tax():\n    assert add_tax(200, 10) == 220\n\n"
        "def test_zero_discount():\n    assert apply_discount(50, 0) == 50\n")
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.repo-ai/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _provider(tmp_path: Path, name: str, after: str, *, assert_seed: bool = False) -> Path:
    check = ""
    if assert_seed:
        check = ("seeded = 'price - price * pct / 100' in (ws / 'pricing.py').read_text()\n"
                 "assert 'PARTIAL FIX ALREADY APPLIED' in prompt and seeded, 'carried work was not present'\n")
    return _make_fake_cli(tmp_path, name, (
        "import json, os, pathlib, sys\n"
        "prompt = sys.argv[-1]\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n" + check +
        f"(ws / 'pricing.py').write_text({after!r})\n"
        "print(json.dumps({'type': 'result', 'session_id': 's', 'cost_usd': 0.0, 'result': 'edited'}))\n"))


def _run_a(shop: Path, tmp_path: Path, after: str) -> dict:
    cli = _provider(tmp_path, "claude", after)
    proc = run_cli(shop, "do", "Make pricing.py compute percentage discounts and tax correctly", "--agent", "claude",
                   "--provider-executable", str(cli), "--allow-write", "pricing.py", "--run", "--json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def _capsule(shop: Path, tmp_path: Path, mission: str, target: str) -> Path:
    proc = run_cli(shop, "handoff", mission, "--to", target, "--json")
    assert proc.returncode == 0, proc.stderr
    path = tmp_path / "capsule.json"
    path.write_text(proc.stdout)
    return path


def test_partial_progress_is_classified_from_observations_and_carried_then_reverified(shop: Path, tmp_path: Path) -> None:
    a = _run_a(shop, tmp_path, FIX_DISCOUNT)
    assert a["effective_verdict"] != "PASS"
    assert a["recovery"]["category"] == "partial_progress" and a["recovery"]["recoverable"] is True
    assert a["baseline"]["failed"] == 2 and a["candidate"]["failed"] == 1

    cap = _capsule(shop, tmp_path, a["id"], "bob")
    b_cli = _provider(tmp_path, "bob", FIX_BOTH, assert_seed=True)
    proc = run_cli(shop, "do", "--from-handoff", str(cap), "--provider-executable", str(b_cli), "--run", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    b = json.loads(proc.stdout)
    assert b["effective_verdict"] == "PASS" and b["provider"]["name"] == "bob"
    assert b["continued_from"]["partial_patch_transferred"] is True
    assert b["continued_from"]["continuation_kind"] == "partial_diff_reverified_from_same_frozen_source"
    assert b["seed"]["fixed"] and b["seed"]["still_failing"]
    # B's verdict comes from fresh frozen-test observations of the final tree, not from A's results
    assert b["candidate"]["failed"] == 0 and b["baseline"]["failed"] == 2
    assert (shop / "pricing.py").read_text() == TWO_BUGS, "source untouched until explicit apply"


def test_diff_that_breaks_a_passing_test_is_not_carried(shop: Path, tmp_path: Path) -> None:
    a = _run_a(shop, tmp_path, "def apply_discount(price, pct):\n    return 0\n\ndef add_tax(price, rate):\n    return price + rate\n")
    assert a["recovery"]["category"] != "partial_progress"
    cap = _capsule(shop, tmp_path, a["id"], "bob")
    proc = run_cli(shop, "do", "--from-handoff", str(cap), "--provider-executable",
                   str(_provider(tmp_path, "bob", FIX_BOTH)), "--run", "--json")
    assert proc.returncode != 0


def test_tampered_capsule_diff_digest_is_refused(shop: Path, tmp_path: Path) -> None:
    a = _run_a(shop, tmp_path, FIX_DISCOUNT)
    cap = _capsule(shop, tmp_path, a["id"], "bob")
    data = json.loads(cap.read_text())
    data["diff_sha256"] = "0" * 64
    cap.write_text(json.dumps(data))
    proc = run_cli(shop, "do", "--from-handoff", str(cap), "--provider-executable",
                   str(_provider(tmp_path, "bob", FIX_BOTH)), "--run", "--json")
    assert proc.returncode != 0
    assert (shop / "pricing.py").read_text() == TWO_BUGS


def test_second_continuation_of_same_capsule_is_refused(shop: Path, tmp_path: Path) -> None:
    a = _run_a(shop, tmp_path, FIX_DISCOUNT)
    cap = _capsule(shop, tmp_path, a["id"], "bob")
    args = ("do", "--from-handoff", str(cap), "--provider-executable", str(_provider(tmp_path, "bob", FIX_BOTH)), "--run", "--json")
    assert run_cli(shop, *args).returncode == 0
    again = run_cli(shop, *args)
    assert again.returncode != 0


def test_seed_touching_a_frozen_test_is_refused_even_if_the_provider_adds_nothing_unsafe(shop: Path, tmp_path: Path) -> None:
    """Defense in depth for review finding 1: the final tree is validated, so a smuggled seed hunk cannot persist."""
    from repo_ai.mission.runtime import execute, plan
    original_test = (shop / "test_pricing.py").read_text()
    (shop / "test_pricing.py").write_text(original_test.replace("== 220", "!= 0"))  # seed rewrites a frozen test
    diff = subprocess.run(["git", "diff", "--no-ext-diff"], cwd=shop, capture_output=True, text=True, check=True).stdout
    _git(shop, "checkout", "--", "test_pricing.py")
    planned = plan(shop, "Make pricing.py compute percentage discounts and tax correctly", agent="claude",
                   write_paths=["pricing.py"], execute_local=True)
    seed = {"diff": diff, "from_mission": "x" * 24, "diff_sha256": "0" * 64, "fixed": ["t"], "still_failing": ["u"]}
    cli = _provider(tmp_path, "claude", FIX_BOTH)
    result = execute(shop, planned, None, provider_executable=cli, seed=seed)
    assert result["effective_verdict"] != "PASS"
    assert any("frozen test" in r or "unapproved path" in r for r in result["passport"]["negative"]), result["passport"]
    assert (shop / "test_pricing.py").read_text() == original_test  # the original checkout is never touched


@pytest.fixture
def split_shop(tmp_path: Path) -> Path:
    # the live Codex -> agy handoff of 2026-10-29: A was scoped to one file, B needs a second
    root = tmp_path / "split"
    root.mkdir()
    (root / "pricing.py").write_text("def apply_discount(price, pct):\n    return price - pct\n")
    (root / "tax.py").write_text("def add_tax(price, rate):\n    return price + rate\n")
    (root / "test_pricing.py").write_text(
        "from pricing import apply_discount\nfrom tax import add_tax\n\n"
        "def test_discount():\n    assert apply_discount(200, 10) == 180\n\n"
        "def test_tax():\n    assert add_tax(200, 10) == 220\n")
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.repo-ai/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _split_a(shop: Path, tmp_path: Path) -> dict:
    cli = _make_fake_cli(tmp_path, "claude", (
        "import json, os, pathlib\nws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "(ws / 'pricing.py').write_text('def apply_discount(price, pct):\\n    return price - price * pct / 100\\n')\n"
        "print(json.dumps({'type': 'result', 'session_id': 's', 'cost_usd': 0.0, 'result': 'edited'}))\n"))
    proc = run_cli(shop, "do", "Fix discount and tax", "--agent", "claude", "--provider-executable", str(cli),
                   "--allow-write", "pricing.py", "--run", "--json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    a = json.loads(proc.stdout)
    assert a["recovery"]["category"] == "partial_progress"
    return a


def _split_b(tmp_path: Path) -> Path:
    return _make_fake_cli(tmp_path, "bob", (
        "import json, os, pathlib\nws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "(ws / 'tax.py').write_text('def add_tax(price, rate):\\n    return price + price * rate / 100\\n')\n"
        "print(json.dumps({'type': 'result', 'session_id': 's', 'cost_usd': 0.0, 'result': 'edited'}))\n"))


def test_continuation_takes_write_paths_the_user_adds_on_the_command(split_shop: Path, tmp_path: Path) -> None:
    a = _split_a(split_shop, tmp_path)
    cap = _capsule(split_shop, tmp_path, a["id"], "bob")
    proc = run_cli(split_shop, "do", "--from-handoff", str(cap), "--provider-executable", str(_split_b(tmp_path)),
                   "--allow-write", "tax.py", "--run", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    b = json.loads(proc.stdout)
    assert b["effective_verdict"] == "PASS"
    assert b["contract"]["write_paths"] == ["pricing.py", "tax.py"]
    assert b["continued_from"]["inherited_write_paths"] == ["pricing.py"]
    assert b["continued_from"]["write_paths_added_by_user"] == ["tax.py"]
    assert b["continued_from"]["partial_patch_transferred"] is True
    assert (split_shop / "tax.py").read_text() == "def add_tax(price, rate):\n    return price + rate\n"


def test_continuation_without_added_paths_keeps_the_original_scope(split_shop: Path, tmp_path: Path) -> None:
    a = _split_a(split_shop, tmp_path)
    cap = _capsule(split_shop, tmp_path, a["id"], "bob")
    proc = run_cli(split_shop, "do", "--from-handoff", str(cap), "--provider-executable", str(_split_b(tmp_path)),
                   "--run", "--json")
    b = json.loads(proc.stdout)
    assert b["contract"]["write_paths"] == ["pricing.py"] and b["effective_verdict"] != "PASS"
    assert b["continued_from"]["write_paths_added_by_user"] == []


def test_continuation_cannot_add_a_frozen_test_file(split_shop: Path, tmp_path: Path) -> None:
    a = _split_a(split_shop, tmp_path)
    cap = _capsule(split_shop, tmp_path, a["id"], "bob")
    proc = run_cli(split_shop, "do", "--from-handoff", str(cap), "--provider-executable", str(_split_b(tmp_path)),
                   "--allow-write", "test_pricing.py", "--run", "--json")
    assert proc.returncode != 0
    assert "PASS" not in proc.stdout
