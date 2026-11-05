"""X13 (Session B's challenge of #44): the environment key listed only the
*names* in site-packages and in `node_modules`, so an installed package
edited in place (a patched module in the virtualenv, a hand-fixed file in
`node_modules`, `patch-package`) left it unchanged: `verify --run` reused a
pass, and `repo-ai evidence` and `prove status` reported it current, although
the tests now fail. The key now covers every entry of those directories
(path, type, size, modification and change times)."""
from __future__ import annotations

import json
import os
import sys
import pytest
from pathlib import Path

from conftest import run_cli
from test_verify_adaptive import CMD, needs_sandbox
from test_verify_environment_key_venv import _project

from repo_ai.verify import cache


@needs_sandbox
def test_editing_an_installed_module_in_place_invalidates_reuse_and_evidence(tmp_path: Path):
    root, site = _project(tmp_path)
    env = {"VIRTUAL_ENV": str(tmp_path / "venv")}
    (root / "calc" / "core.py").write_text("from depcalc import plus\n\n\ndef add(a, b):\n    return plus(b, a)\n")
    first = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env=env)
    assert first.returncode == 0, first.stdout[-1500:] + first.stderr

    same = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env=env)
    assert json.loads(same.stdout)["evidence"].get("reused"), "nothing changed, yet the pass was not reused"

    # the same version, the same names: only the module's body changed
    (site / "depcalc.py").write_text("def plus(a, b):\n    return a - b\n")
    second = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env=env)
    out = json.loads(second.stdout)
    assert not out["evidence"].get("reused"), "the pass recorded before the edit was reused"
    ev = json.loads(run_cli(root, "evidence", "--json", env=env).stdout)
    assert not (ev.get("current") and str((ev.get("evidence") or {}).get("verdict")).startswith("selected")), ev
    fresh = run_cli(root, "verify", "--run", "--rerun", "--json", "--test-command", CMD, env=env)
    assert fresh.returncode == 1, fresh.stdout[-800:]  # the state really fails
    assert second.returncode == 1, f"verify --run reported {out['summary']['verdict']!r} after an in-place edit"


@pytest.mark.xfail(sys.platform == "win32", strict=False,
                   reason="Windows: the tree identity is not stable between two reads (seen in CI 40225661892); it "
                          "only stops reuse there, never yields a wrong verdict (release-risk register R13)")
def test_the_tree_identity_sees_in_place_edits_and_nothing_else(tmp_path: Path):
    deps = tmp_path / "node_modules"
    (deps / "left-pad").mkdir(parents=True)
    (deps / "left-pad" / "package.json").write_text('{"name": "left-pad", "version": "1.3.0"}\n')
    (deps / "left-pad" / "index.js").write_text("module.exports = (s, n) => String(s).padStart(n);\n")
    (deps / "left-pad" / "__pycache__").mkdir()
    (deps / ".cache").mkdir()
    first = cache._tree_id(str(deps))
    assert cache._tree_id(str(deps)) == first  # stable while nothing changes

    (deps / "left-pad" / "__pycache__" / "x.pyc").write_bytes(b"\0")  # written by a run: not an input
    (deps / ".cache" / "babel.json").write_text("{}")
    assert cache._tree_id(str(deps)) == first

    js = deps / "left-pad" / "index.js"
    st = js.stat()
    js.write_text("module.exports = (s, n) => String(s).padEnd(n);\n")  # the same size
    os.utime(js, ns=(st.st_atime_ns, st.st_mtime_ns))  # even with the old modification time restored
    assert cache._tree_id(str(deps)) != first  # the change time cannot be set back


def test_a_tree_too_large_to_identify_is_never_reused(tmp_path: Path, monkeypatch):
    deps = tmp_path / "site-packages"
    deps.mkdir()
    for i in range(5):
        (deps / f"m{i}.py").write_text("")
    monkeypatch.setattr(cache, "MAX_TREE_ENTRIES", 3)
    a, b = cache._tree_id(str(deps)), cache._tree_id(str(deps))
    assert a != b and "too-large" in a
