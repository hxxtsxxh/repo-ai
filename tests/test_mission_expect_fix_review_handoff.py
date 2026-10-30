import json
from conftest import run_cli
from test_mission_partial_handoff import TWO_BUGS, FIX_DISCOUNT, FIX_BOTH, _git, _provider, _capsule


def _shop(tmp_path):
    root = tmp_path / "shop"
    root.mkdir()
    (root / "pricing.py").write_text(TWO_BUGS)
    (root / "test_pricing.py").write_text(
        "from pricing import apply_discount, add_tax\n\n"
        "def test_discount():\n    assert apply_discount(200, 10) == 180\n\n"
        "def test_tax():\n    assert add_tax(200, 10) == 220\n\n"
        "def test_zero_discount():\n    assert apply_discount(50, 0) == 50\n"
    )
    (root / "test_legacy.py").write_text('def test_old():\n    assert False, "backend"\n')
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.repo-ai/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def test_scoped_mission_handoff_continuation_keeps_scope(tmp_path):
    shop = _shop(tmp_path)
    cli = _provider(tmp_path, "claude", FIX_DISCOUNT)
    proc = run_cli(
        shop,
        "do",
        "Make pricing.py compute percentage discounts and tax correctly",
        "--agent",
        "claude",
        "--provider-executable",
        str(cli),
        "--allow-write",
        "pricing.py",
        "--run",
        "--json",
        "--expect-fix",
        "test_pricing.py::test_discount",
        "--expect-fix",
        "test_pricing.py::test_tax",
    )
    a = json.loads(proc.stdout)
    print("A", a["effective_verdict"], a.get("recovery"), a["contract"].get("expect_fix"))
    assert a["recovery"]["category"] == "partial_progress"
    cap = _capsule(shop, tmp_path, a["id"], "bob")
    b_cli = _provider(tmp_path, "bob", FIX_BOTH, assert_seed=True)
    proc = run_cli(
        shop,
        "do",
        "--from-handoff",
        str(cap),
        "--provider-executable",
        str(b_cli),
        "--run",
        "--json",
        "--expect-fix",
        "test_pricing.py::test_discount",
        "--expect-fix",
        "test_pricing.py::test_tax",
    )
    b = json.loads(proc.stdout)
    print(
        "B",
        b["effective_verdict"],
        b["contract"].get("expect_fix"),
        b["passport"]["negative"],
        b["candidate"]["outcomes"],
    )
    assert b["contract"].get("expect_fix"), "continuation silently dropped --expect-fix"
