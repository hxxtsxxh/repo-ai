# Vendored from Session A's red team (PR #24, comments 6401610438 and 6402441378;
# scratchpad/redteam/v7fa), unchanged except the helper import and two lint fixes. Each test asserts the safe result.
"""Red-team probes on 7fa342d: node --test subject inference, export integrity and record
tampering. Each asserts the SAFE result.

N1  node: the subject is inferred from relative import specifiers; a module loaded with a
    dynamic import() whose specifier is a template literal is left out, and its edit puts the
    bug back in the shipped candidate
N0  node control: a genuine fix with a declared subject is supported_by_controlled_comparison
E1  in-toto with --out while stale: the written statement must not say supported without freshness
E2  a stored passport edited by hand (verdict flipped, digest not recomputed) is not accepted
E3  V1 at 7fa342d without --subject: why it no longer gives a false proof (observability)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, cli, make_repo, pin_and_run, summary, write  # noqa: E402
from test_verify_adaptive import NODE_SANDBOX  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox backend to run tests in")

PKG = '{"name": "n1", "version": "1.0.0", "type": "module", "scripts": {"test": "node --test"}}\n'
CORE = "export const impl = { mean: (xs) => xs.reduce((a, b) => a + b, 0) / xs.length };\n"
CORE_FIXED = ("export const impl = { mean: (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0) };\n")
INDEX = ("import { impl } from './core.js';\nexport function mean(xs) { return impl.mean(xs); }\n"
         "const name = 'ext';\nawait import(`./${name}.js`);\n")
EXT_REBREAK = ("import { impl } from './core.js';\n"
               "impl.mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;\n")
EXIST = ("import { test } from 'node:test';\nimport assert from 'node:assert';\nimport { mean } from '../lib/index.js';\n"
         "test('mean of three', () => { assert.strictEqual(mean([1, 2, 3]), 2); });\n")
ACCEPT = ("import { test } from 'node:test';\nimport assert from 'node:assert';\nimport { mean } from '../lib/index.js';\n"
          "test('mean of empty is 0', () => { assert.strictEqual(mean([]), 0); });\n")


def _node_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "r", {"package.json": PKG, "lib/core.js": CORE, "lib/index.js": INDEX,
                                      "lib/ext.js": "export {};\n", "test/mean.test.js": EXIST})


def _outside(tmp_path: Path, text: str, name: str = "accept.test.js") -> Path:
    p = tmp_path / "reviewer" / name
    write(p.parent, {name: text})
    return p


needs_node = pytest.mark.skipif(not NODE_SANDBOX or not shutil.which("node"), reason="the sandbox cannot start node")


@pytest.mark.xfail(strict=True, reason="by design since the corrective phase (Session B, 2026-10-25): a node claim is "
                   "never supported, because JavaScript scenarios are not parsed (the seventh review's CommonJS re-export)")
@needs_node
def test_n0_node_control_declared_subject(tmp_path: Path):
    root = _node_repo(tmp_path)
    write(root, {"lib/core.js": CORE_FIXED})
    _, pp = pin_and_run(root, "test/accept.test.js", _outside(tmp_path, ACCEPT), "--test-command", "node --test",
                        "--subject", "lib/core.js")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] == "supported" and pp["verdict"]["level"] == \
        "supported_by_controlled_comparison", summary(pp)


@needs_node
def test_n1_node_dynamic_import_left_out_of_the_inferred_subject(tmp_path: Path):
    root = _node_repo(tmp_path)
    write(root, {"lib/core.js": CORE_FIXED, "lib/ext.js": EXT_REBREAK})
    shipped = subprocess.run(["node", "--input-type=module", "-e",
                              "const m = await import('./lib/index.js'); console.log('RESULT', m.mean([]));"],
                             cwd=root, capture_output=True, text=True, timeout=60)
    assert "RESULT NaN" in shipped.stdout, (shipped.stdout, shipped.stderr)  # the shipped candidate is still buggy
    _, pp = pin_and_run(root, "test/accept.test.js", _outside(tmp_path, ACCEPT), "--test-command", "node --test")
    print("SUMMARY", summary(pp))
    assert pp["observations"]["baseline"]["state"] == "reproduced", summary(pp)
    assert pp["verdict"]["state"] != "supported", f"N1: the shipped candidate returns NaN, yet {summary(pp)}"


# ------------------------------------------------------------------ exports and the stored record
BUGGY = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
PY_ACCEPT = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"


@pytest.fixture(scope="module")
def supported(tmp_path_factory) -> tuple[Path, dict]:
    tmp = tmp_path_factory.mktemp("exp")
    root = make_repo(tmp / "r", {"mypkg/__init__.py": BUGGY, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/__init__.py": FIXED})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp, PY_ACCEPT, "test_accept.py"), *PT,
                        "--subject", "mypkg/__init__.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["level"] == "supported_by_controlled_comparison", summary(pp)
    return root, pp


def test_e1_in_toto_written_with_out_while_stale(supported, tmp_path: Path):
    root, _ = supported
    write(root, {"mypkg/__init__.py": FIXED + "# later\n"})
    try:
        out = tmp_path / "stmt.json"
        proc = cli(root, "prove", "report", "c", "--format", "in-toto", "--out", str(out))
        print("STDERR", proc.returncode, proc.stderr.strip()[:300])
        pred = json.loads(out.read_text())["predicate"]
        assert pred.get("freshness", {}).get("state") == "stale" or not pred["verdict"]["supported"], (
            f"E1: exit {proc.returncode}; the written in-toto statement of a stale passport says "
            f"{pred['verdict']['state']} / {pred['verdict'].get('level')} with no freshness (keys {sorted(pred)})")
    finally:
        write(root, {"mypkg/__init__.py": FIXED})


def test_e2_a_hand_edited_passport_is_not_accepted(tmp_path: Path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": BUGGY, "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/__init__.py": "def mean(xs):\n    return 1\n"})  # breaks the existing test
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, PY_ACCEPT, "test_accept.py"), *PT,
                        "--subject", "mypkg/__init__.py")
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] != "supported"
    path = Path(pp["path"])
    doc = json.loads(path.read_text())
    doc["verdict"] = {**doc["verdict"], "state": "supported", "supported": True}
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    st = cli(root, "prove", "status", "c", "--json")
    print("STATUS", st.returncode, st.stdout[:300])
    body = json.loads(st.stdout)
    assert not body.get("supported") and (body.get("verdict") or {}).get("state") != "supported", (
        f"E2: a passport whose verdict was edited by hand is reported as {body}")


def test_e3_v1_without_subject_is_refused_before_running(tmp_path: Path):
    fixture = "import pytest\n\n\n@pytest.fixture\ndef empty_input():\n    return {}\n"
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": BUGGY, "tests/test_mean.py": EXISTING,
                                      "mypkg/testing.py": fixture.replace("{}", "[]"),
                                      "pytest.ini": "[pytest]\naddopts = -p mypkg.testing\n"})
    write(root, {"mypkg/testing.py": fixture.replace("{}", "[0]")})
    scen = "from mypkg import mean\n\n\ndef test_empty(empty_input):\n    assert mean(empty_input) == 0\n"
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, scen, "test_accept.py"), *PT)
    print("SUMMARY", summary(pp))
    assert pp["verdict"]["state"] != "supported"
