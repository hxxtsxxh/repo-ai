# Vendored from the sixth adversarial review of ProofLab (2026-10-25, on 473c41a), with the assertions of the
# static probes inverted to the safe result. Each end-to-end test asserts the safe result.
"""Node G4 bypass, and export consistency while stale. Each asserts the SAFE result."""
import json
import shutil
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sa_redteam_rt7 import PT, _host_sandbox, cli, make_repo, pin_and_run, summary, write  # noqa: E402
from test_verify_adaptive import NODE_SANDBOX  # noqa: E402

pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox")
needs_node = pytest.mark.skipif(not NODE_SANDBOX or not shutil.which("node"), reason="no node")

PKG = '{"name": "n1", "version": "1.0.0", "type": "module", "scripts": {"test": "node --test"}}\n'
INDEX = "export function mean(xs) { return xs.reduce((a, b) => a + b, 0) / xs.length; }\n"
SAMPLES = "export function empty() { return []; }\n"
EXIST = ("import { test } from 'node:test';\nimport assert from 'node:assert';\nimport { mean } from '../lib/index.js';\n"
         "test('mean of three', () => { assert.strictEqual(mean([1, 2, 3]), 2); });\n")


def _outside(tmp_path, text, name):
    p = tmp_path / "reviewer" / name
    write(p.parent, {name: text})
    return p


@needs_node
@pytest.mark.parametrize("variant", ["test-helper", "subject-reexport"])
def test_node_g4_bypass(tmp_path, variant):
    files = {"package.json": PKG, "lib/index.js": INDEX, "lib/samples.js": SAMPLES, "test/mean.test.js": EXIST}
    if variant == "test-helper":
        files["test/helpers.js"] = "export { mean } from '../lib/index.js';\n"
        imp = "import { mean } from './helpers.js';\nimport { empty } from '../lib/samples.js';\n"
        cand = {"lib/samples.js": "export function empty() { return [0]; }\n"}
    else:
        imp = "import { mean, empty } from '../lib/samples.js';\n"
        files["lib/samples.js"] = "export { mean } from './index.js';\n" + SAMPLES
        cand = {"lib/samples.js": "export { mean } from './index.js';\nexport function empty() { return [0]; }\n"}
    root = make_repo(tmp_path / "r", files)
    write(root, cand)
    scen = ("import { test } from 'node:test';\nimport assert from 'node:assert';\n" + imp +
            "test('mean of empty is 0', () => { assert.strictEqual(mean(empty()), 0); });\n")
    _, pp = pin_and_run(root, "test/accept.test.js", _outside(tmp_path, scen, "accept.test.js"),
                        "--test-command", "node --test", "--subject", "lib/samples.js")
    print("SUMMARY", variant, summary(pp), "abstain", pp.get("abstain"))
    assert pp["verdict"]["state"] != "supported", summary(pp)


BUGGY = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = "from mypkg import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n"
ACCEPT = "from mypkg import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"


def test_exports_while_stale(tmp_path):
    root = make_repo(tmp_path / "r", {"mypkg/__init__.py": "from .core import mean\n", "mypkg/core.py": BUGGY,
                                      "tests/test_mean.py": EXISTING})
    write(root, {"mypkg/core.py": FIXED})
    _, pp = pin_and_run(root, "tests/test_accept.py", _outside(tmp_path, ACCEPT, "test_accept.py"), *PT,
                        "--subject", "mypkg/core.py")
    print("SUMMARY fresh", summary(pp))
    assert pp["verdict"]["state"] == "supported"
    write(root, {"mypkg/core.py": BUGGY + "# reverted\n"})  # the fix is gone
    outs = {}
    d = cli(root, "prove", "pin", "d", "--claim", "y", "--scenario", "tests/test_accept2.py", "--file",
            str(_outside(tmp_path, ACCEPT, "test_accept2.py")), *PT)
    assert d.returncode == 0, d.stderr
    outs["status_all"] = cli(root, "prove", "status", "--json").stdout
    outs["status_c"] = cli(root, "prove", "status", "c", "--json").stdout
    outs["report_json"] = cli(root, "prove", "report", "c", "--format", "json").stdout
    outs["report_intoto"] = cli(root, "prove", "report", "c", "--format", "in-toto").stdout
    outs["report_md"] = cli(root, "prove", "report", "c").stdout
    bad = []
    for k, v in outs.items():
        print("OUT", k, v[:600].replace("\n", " "))
        if k == "report_md":
            continue
        doc = json.loads(v)
        if k == "status_all":
            for row in doc["claims"]:
                if row.get("verdict") == "supported":
                    bad.append((k, row))
            continue
        # walk: any "supported": true or level supported_by_controlled_comparison outside 'recorded'/'scenario_level'
        def walk(o, path):
            if isinstance(o, dict):
                for kk, vv in o.items():
                    if kk in {"recorded", "recorded_level", "scenario_level"}:
                        continue
                    if kk == "supported" and vv is True:
                        bad.append((k, path + "/" + kk))  # noqa: B023 - called within the same iteration
                    if kk in {"level", "state"} and vv in {"supported_by_controlled_comparison", "supported"}:
                        bad.append((k, path + "/" + kk + "=" + vv))  # noqa: B023
                    walk(vv, path + "/" + kk)
            elif isinstance(o, list):
                for i, vv in enumerate(o):
                    walk(vv, f"{path}[{i}]")
        walk(doc, "")
    print("BAD", bad)
    assert not bad, bad
