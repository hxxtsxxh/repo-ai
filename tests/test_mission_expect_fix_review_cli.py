import json
import hashlib
from conftest import run_cli
from test_mission_partial_handoff import _git


def test_cli_render(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "charge.py").write_text("def charge(amount, retries):\n    return amount * (retries + 1)\n")
    (root / "test_charge.py").write_text(
        "from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n\ndef test_once():\n    assert charge(10, 0) == 10\n"
    )
    (root / "test_legacy.py").write_text('def test_old():\n    assert False, "backend"\n')
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.repo-ai/\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "b")
    prop = tmp_path / "prop.json"
    prop.write_text(
        json.dumps(
            {
                "schema": "repo-ai.replay/1",
                "label": "sim",
                "edits": [
                    {
                        "path": "charge.py",
                        "before_sha256": hashlib.sha256((root / "charge.py").read_bytes()).hexdigest(),
                        "after": "def charge(amount, retries):\n    return amount\n",
                    }
                ],
            }
        )
    )
    for extra in (
        [],
        ["--expect-fix", ""],
        ["--expect-fix", "test_charge.py::test_retry", "--expect-fix", "test_charge.py::test_retry"],
    ):
        proc = run_cli(
            root,
            "do",
            "Fix duplicate charge in charge.py",
            "--agent",
            "replay",
            "--replay",
            str(prop),
            "--allow-write",
            "charge.py",
            "--run",
            *extra,
        )
        print("=== ", extra, "rc", proc.returncode)
        print(proc.stdout[-1500:])
        print(proc.stderr[-400:])
    proc = run_cli(
        root,
        "do",
        "Fix duplicate charge in charge.py",
        "--agent",
        "replay",
        "--replay",
        str(prop),
        "--allow-write",
        "charge.py",
        "--run",
        "--json",
        "--expect-fix",
        "test_charge.py::test_retry",
    )
    v = json.loads(proc.stdout)
    for args in (["mission", "status", v["id"]], ["why", v["id"]]):
        p2 = run_cli(root, *args)
        print("=== ", args, p2.returncode)
        print(p2.stdout[-1500:])
        print(p2.stderr[-300:])
