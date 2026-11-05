"""Adversarial review scratch tests for --expect-fix (not for merge)."""

import json

import pytest

from repo_ai.mission.runtime import execute, plan, status
from test_mission_runtime import git, replay

BASE_CHARGE = "def charge(amount, retries):\n    return amount * (retries + 1)\n"
FIX = "def charge(amount, retries):\n    return amount\n"


def _mk(tmp_path, files):
    root = tmp_path / "proj"
    root.mkdir()
    for k, v in files.items():
        (root / k).parent.mkdir(parents=True, exist_ok=True)
        (root / k).write_text(v)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=f", "-c", "user.email=f@example.invalid", "commit", "-qm", "base")
    return root


def _run(root, tmp_path, expect_fix, after=FIX, path="charge.py"):
    p = plan(
        root,
        "Fix duplicate charge in charge.py",
        agent="replay",
        write_paths=[path],
        execute_local=True,
        expect_fix=expect_fix,
    )
    return execute(root, p, replay(root, tmp_path, after=after, path=path))


CHARGE_TEST = (
    "from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n\n"
    "def test_once():\n    assert charge(10, 0) == 10\n"
)


def _dump(r):
    return json.dumps(
        {k: r.get(k) for k in ("effective_verdict", "scoped", "reasons")}
        | {
            "neg": (r.get("passport") or {}).get("negative"),
            "regression": (r.get("regression") or {}).get("verdict"),
            "base": (r.get("baseline") or {}).get("outcomes"),
            "cand": (r.get("candidate") or {}).get("outcomes"),
        },
        indent=1,
        default=str,
    )


# 1. fail -> fail with a different reason, statically linked legacy test
def test_fail_to_fail_differently_static(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "from charge import charge\n\ndef test_big():\n"
            "    assert charge(10, 7) == -1\n",
        },
    )
    r = _run(
        root,
        tmp_path,
        ["test_charge.py::test_retry"],
        after='def charge(amount, retries):\n    if retries > 5:\n        raise RuntimeError("boom")\n    return amount\n',
    )
    print(_dump(r))
    assert r["effective_verdict"] != "PASS", _dump(r)


# 2. same, dynamically linked (not statically selected)
def test_fail_to_fail_differently_dynamic(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "import importlib\n\ndef test_big():\n"
            '    m = importlib.import_module("cha" + "rge")\n'
            "    assert m.charge(10, 7) == -1\n",
        },
    )
    r = _run(
        root,
        tmp_path,
        ["test_charge.py::test_retry"],
        after='def charge(amount, retries):\n    if retries > 5:\n        raise RuntimeError("boom")\n    return amount\n',
    )
    print(_dump(r))
    assert r["effective_verdict"] != "PASS", _dump(r)


# 3. fail -> error (setup error via a frozen conftest fixture calling candidate code)
def test_fail_to_error(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE + "def backend():\n    return 1\n",
            "test_charge.py": CHARGE_TEST,
            "conftest.py": "import pytest\n\n@pytest.fixture\ndef be():\n    import charge\n    return charge.backend()\n",
            "test_legacy.py": "def test_old(be):\n    assert be == 2\n",
        },
    )
    r = _run(
        root,
        tmp_path,
        ["test_charge.py::test_retry"],
        after=FIX + 'def backend():\n    raise RuntimeError("x")\n',
    )
    print(_dump(r))
    assert r["effective_verdict"] != "PASS", _dump(r)


# 4. parametrized ids and the key format
def test_parametrized_ids(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": "import pytest\nfrom charge import charge\n\n"
            '@pytest.mark.parametrize("r", [0, 2])\ndef test_p(r):\n'
            "    assert charge(10, r) == 10\n",
            "test_legacy.py": "def test_old():\n    assert False\n",
        },
    )
    r = _run(root, tmp_path, ["test_charge.py::test_p[2]"])
    print(_dump(r))
    assert r["effective_verdict"] == "PASS", _dump(r)


# 5. tournament: does the comparison report carry the standing?
def test_tournament_reports_standing(tmp_path):
    from repo_ai.mission.tournament import compare_candidates, render_comparison

    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": 'def test_old():\n    assert False, "backend"\n',
        },
    )
    p = plan(
        root,
        "Fix duplicate charge in charge.py",
        agent="replay",
        write_paths=["charge.py"],
        execute_local=True,
        expect_fix=["test_charge.py::test_retry"],
    )
    good = replay(root, tmp_path, after=FIX)
    good2 = tmp_path / "good2.json"
    good2.write_text(good.read_text())
    bad = tmp_path / "bad.json"
    d = json.loads(good.read_text())
    d["edits"][0]["after"] = "def charge(amount, retries):\n    return 0\n"
    bad.write_text(json.dumps(d))
    rep = compare_candidates(root, p, [bad, good])
    text = render_comparison(rep)
    print(json.dumps(rep, indent=1, default=str))
    print(text)
    assert rep["verdict"] == "PASS"
    assert "PRE_EXISTING" in json.dumps(rep) or "pre-existing" in text.lower() or "test_old" in text, text


# 6. expect_fix in a write path that is a test file
def test_declared_test_in_write_path(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "def test_old():\n    assert False\n",
        },
    )
    with pytest.raises(ValueError):
        p = plan(
            root,
            "Fix duplicate charge",
            agent="replay",
            write_paths=["test_charge.py"],
            execute_local=True,
            expect_fix=["test_charge.py::test_retry"],
        )
        r = execute(
            root,
            p,
            replay(
                root,
                tmp_path,
                after=CHARGE_TEST.replace("== 10\n\ndef test_once", "== 30\n\ndef test_once"),
                path="test_charge.py",
            ),
        )
        assert r["effective_verdict"] != "PASS"
        raise ValueError("refused at execute: " + str((r.get("passport") or {}).get("negative")))


# 7. apply of a scoped pass: a test that passed at base fails post-apply only because of a local env change
def test_apply_scoped_rechecks_regression(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "def test_old():\n    assert False\n",
        },
    )
    r = _run(root, tmp_path, ["test_charge.py::test_retry"])
    assert r["effective_verdict"] == "PASS"
    st = status(root, r["id"])
    print(st.get("scoped"), st["claims"]["headline"], st["effective_verdict"])
    assert st["scoped"]["standing"] == "PASS_WITH_PRE_EXISTING_FAILURES"
    assert st["claims"]["headline"] == "ASSURANCE_PARTIAL"


def test_volatile_legacy_message(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "import random, time\n\ndef test_old(tmp_path):\n"
            '    assert False, f"{tmp_path} {random.random()}"\n',
        },
    )
    r = _run(root, tmp_path, ["test_charge.py::test_retry"])
    print(_dump(r))
    # a pre-existing failure whose message changes every run cannot be judged: never a FAIL of a correct fix
    assert r["effective_verdict"] == "INCONCLUSIVE", _dump(r)


SHOP = "def a(x):\n    return x + 1\n\ndef b(x):\n    return x + 1\n"
SHOP_T = (
    "from shop import a, b\n\ndef test_a():\n    assert a(1) == 1\n\ndef test_b():\n    assert b(1) == 1\n"
)


def test_write_path_test_file_execute(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "def test_old():\n    assert False\n",
        },
    )
    p = plan(
        root,
        "Fix duplicate charge",
        agent="replay",
        write_paths=["test_charge.py"],
        execute_local=True,
        expect_fix=["test_charge.py::test_retry"],
    )
    print("decision", p.get("decision"), p["contract"].get("execute"))
    try:
        r = execute(
            root,
            p,
            replay(
                root,
                tmp_path,
                after=CHARGE_TEST.replace("charge(10, 2) == 10", "charge(10, 2) == 30"),
                path="test_charge.py",
            ),
        )
    except ValueError as e:
        print("EXEC REFUSED", e)
        return
    print(_dump(r))
    assert r["effective_verdict"] != "PASS"


def test_tmp_path_legacy_message(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": 'def test_old(tmp_path):\n    assert False, f"{tmp_path}"\n',
        },
    )
    r = _run(root, tmp_path, ["test_charge.py::test_retry"])
    print(_dump(r))
    assert r["effective_verdict"] == "PASS", _dump(r)


def test_claim_unverified_drops_pre_existing_note(tmp_path):
    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "def test_old():\n    assert False\n",
        },
    )
    p = plan(
        root,
        "Do it.",
        agent="replay",
        write_paths=["charge.py"],
        execute_local=True,
        expect_fix=["test_charge.py::test_retry"],
    )
    r = execute(root, p, replay(root, tmp_path, after=FIX))
    st = status(root, r["id"])
    print(r["effective_verdict"], st["scoped"], st["claims"]["headline"], st["claims"]["notes"])
    assert any("already failed at the base" in n for n in st["claims"]["notes"]), st["claims"]


def test_futures_rehearse_on_scoped_pass(tmp_path):
    from repo_ai.mission import futures

    root = _mk(
        tmp_path,
        {
            "charge.py": BASE_CHARGE,
            "test_charge.py": CHARGE_TEST,
            "test_legacy.py": "def test_old():\n    assert False\n",
        },
    )
    r = _run(root, tmp_path, ["test_charge.py::test_retry"])
    assert r["effective_verdict"] == "PASS"
    fn = [getattr(futures, n) for n in dir(futures) if n == "analyze_futures"]
    print([n for n in dir(futures) if not n.startswith("_")])
    rep = fn[0](root, r["id"], rehearse=True)
    print(rep["rehearsal"])
    assert rep["rehearsal"]["verdict"] == "PASS", rep["rehearsal"]
