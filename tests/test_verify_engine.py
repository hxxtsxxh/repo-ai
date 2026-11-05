"""repo-ai verify: change detection, runtime evidence, selection, execution, gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import run_cli, run_hook

from repo_ai.verify import changes as ch
from repo_ai.verify import dynamic
from repo_ai.verify.runner import parse_command, resolve
from repo_ai.verify.select import Graph, plan
from repo_ai.verify.testmap import TRACER, TestMap

PKG = {
    "calc/__init__.py": "from calc.core import add, scale\n",
    "calc/core.py": ("RATE = 2\n\n\ndef add(a, b):\n    # add two numbers\n    return a + b\n\n\n"
                     "def scale(x):\n    return x * RATE\n\n\nclass Box:\n    def get(self):\n        return 1\n"),
    "calc/plugins/__init__.py": "",
    "calc/plugins/loud.py": "def shout(s):\n    return s.upper()\n",
    "calc/loader.py": ("import importlib\n\n\ndef load(name):\n"
                       "    return importlib.import_module(f'calc.plugins.{name}')\n"),
    "tests/__init__.py": "",
    "tests/test_add.py": ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n"),
    "tests/test_scale.py": ("import unittest\nfrom calc import scale\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_scale(self):\n        self.assertEqual(scale(2), 4)\n"),
    "tests/test_plugins.py": ("import unittest\nfrom calc.loader import load\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_loud(self):\n        self.assertEqual(load('loud').shout('a'), 'A')\n"),
}
CMD = "python -m unittest discover -s tests -t ."


def _git(repo: Path, *args: str) -> None:
    import os
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel, text in PKG.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _edit(root: Path, rel: str, old: str, new: str) -> None:
    p = root / rel
    text = p.read_text()
    assert old in text
    p.write_text(text.replace(old, new))


def _graph(root: Path) -> Graph:
    edges = [("calc/__init__.py", "calc/core.py"), ("tests/test_add.py", "calc/core.py"),
             ("tests/test_scale.py", "calc/__init__.py"), ("tests/test_plugins.py", "calc/loader.py")]
    files = sorted(PKG)
    return Graph(edges, files)


# -- change detection ---------------------------------------------------------
def test_a_changed_line_maps_to_the_code_unit_that_owns_it(repo: Path):
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    change = ch.detect(repo)
    [cf] = change.files
    assert cf.path == "calc/core.py" and cf.status == "modified" and cf.behavioral
    assert cf.unit_names == ["add"]  # not the module, not scale


def test_comment_only_changes_are_not_behavioural(repo: Path):
    _edit(repo, "calc/core.py", "# add two numbers", "# add two numbers together")
    [cf] = ch.detect(repo).files
    assert cf.behavioral is False


def test_a_signature_change_also_touches_the_defining_scope(repo: Path):
    _edit(repo, "calc/core.py", "def add(a, b):", "def add(a, b=0):")
    [cf] = ch.detect(repo).files
    # the def statement runs in the module (every importer is affected); since Python 3.11
    # the def line is also part of the function's own code
    assert "<module>" in cf.unit_names
    assert "add" in cf.unit_names or sys.version_info < (3, 11)


def test_untracked_added_and_deleted_files_are_part_of_the_change(repo: Path):
    (repo / "calc" / "extra.py").write_text("X = 1\n")
    (repo / "calc" / "plugins" / "loud.py").unlink()
    paths = {f.path: f.status for f in ch.detect(repo).files}
    assert paths == {"calc/extra.py": "added", "calc/plugins/loud.py": "deleted"}


def test_fingerprint_identifies_the_exact_change(repo: Path):
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    one = ch.detect(repo).fingerprint
    assert ch.detect(repo).fingerprint == one
    _edit(repo, "calc/core.py", "return a - b", "return a * b")
    assert ch.detect(repo).fingerprint != one


def test_unsafe_base_refs_are_refused(repo: Path):
    with pytest.raises(ch.ChangeError):
        ch.detect(repo, "--output=/tmp/x")


# -- runner parsing ---------------------------------------------------------
def test_runner_parsing_and_per_file_argv(tmp_path: Path):
    r = parse_command("python -m unittest discover -s tests -t .")
    assert (r.kind, r.start, r.top) == ("unittest", "tests", ".")
    assert r.group_argvs(["tests/test_a.py", "tests/test_b.py"]) == [
        ["python", "-m", "unittest", "tests.test_a", "tests.test_b"]]
    r = parse_command("python -m unittest discover -s tests")  # top-level defaults to the start dir
    assert r.file_argv("tests/sub/test_a.py") == ["python", "-m", "unittest", "discover", "-s", "tests/sub",
                                                  "-t", "tests", "-p", "test_a.py"]
    assert parse_command("cd pkg && pytest -q tests").cwd == "pkg"
    assert parse_command('sh -c "node --test test/a.test.js"').kind == "node"
    assert parse_command("PYTHONPATH=src python -m unittest discover -s tests -t .").env == {"PYTHONPATH": "src"}
    for unsafe in ("LD_PRELOAD=/x.so python -m unittest", "PYTHONPATH=/etc python -m unittest",
                   "PYTHONPATH=../.. python -m unittest", "python -m unittest; rm -rf x", "make test"):
        assert parse_command(unsafe).kind == "opaque", unsafe
    (tmp_path / "Makefile").write_text("PY ?= python3\n\ntest:\n\t$(PY) -m unittest discover -s tests -t .\n")
    assert resolve(tmp_path, "make test").kind == "unittest"
    (tmp_path / "Makefile").write_text("test:\n\tpython -m unittest\n\trm -rf build\n")
    assert resolve(tmp_path, "make test").kind == "opaque"  # several steps: never guessed


def test_runner_test_universe(repo: Path):
    files = sorted(PKG)
    assert parse_command(CMD).test_files(files) == ["tests/test_add.py", "tests/test_plugins.py",
                                                    "tests/test_scale.py"]
    node = parse_command("node --test test/**/*.test.js")
    assert node.test_files(["test/a.test.js", "test/sub/b.test.js", "test/helper.js", "src/x.js"]) == [
        "test/a.test.js", "test/sub/b.test.js"]


# -- dynamic loading ---------------------------------------------------------
def test_dynamic_loading_is_detected_with_its_prefix(repo: Path):
    facts = dynamic.analyze(repo, sorted(PKG))
    [site] = facts.loaders
    assert (site.path, site.prefix) == ("calc/loader.py", "calc.plugins.")
    exposure = facts.exposure("calc/plugins/loud.py", static_importers=0)
    assert exposure and exposure[0]["kind"] == "loaded-by-computed-name"
    assert facts.exposure("calc/core.py", static_importers=2) == []


def test_entry_points_and_string_references(tmp_path: Path):
    (tmp_path / "pkg" / "ext").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "ext" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "ext" / "toc.py").write_text("def run():\n    return 1\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="p"\n[project.entry-points."pkg.ext"]\n'
                                              'toc = "pkg.ext.toc:Toc"\n')
    (tmp_path / "test_x.py").write_text("EXT = ['toc']\nOTHER = 'pkg.ext.toc'\n")
    files = ["pkg/__init__.py", "pkg/ext/__init__.py", "pkg/ext/toc.py", "pyproject.toml", "test_x.py"]
    facts = dynamic.analyze(tmp_path, files)
    assert facts.registrations["pkg/ext/toc.py"][0]["name"] == "toc"
    assert len(facts.string_refs["pkg/ext/toc.py"]) == 2  # the registered name and the dotted path
    assert facts.exposure("pkg/ext/toc.py", 0)[0]["kind"] == "registered"


# -- selection ---------------------------------------------------------------
def test_static_selection_uses_the_full_closure_and_package_init(repo: Path):
    _edit(repo, "calc/__init__.py", "from calc.core import add, scale", "from calc.core import add, scale  # x\nX = 1")
    change = ch.detect(repo)
    p = plan(change, parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)))
    # a package __init__ runs for every import of the package or any module in it:
    # test_add imports calc.core and test_plugins imports calc.loader
    assert {s.test for s in p.selected} == {"tests/test_add.py", "tests/test_scale.py", "tests/test_plugins.py"}
    assert p.confidence == "medium" and not p.full_suite_required


def test_dynamic_exposure_without_runtime_evidence_requires_the_full_suite(repo: Path):
    _edit(repo, "calc/plugins/loud.py", "s.upper()", "s.lower()")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)))
    assert p.confidence == "low" and p.full_suite_required
    assert any("computed name" in t for t in p.triggers)


def test_configuration_changes_trigger_the_full_suite(repo: Path):
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)))
    assert p.full_suite_required and any("pyproject.toml" in t for t in p.triggers)


def test_docs_only_change_needs_no_tests(repo: Path):
    (repo / "README.md").write_text("# hi\n")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)))
    assert p.selected == [] and not p.full_suite_required


def _tmap(repo: Path, tests: dict[str, dict]) -> TestMap:
    from repo_ai.verify.testmap import hash_files
    return TestMap(runner={"command": CMD}, file_hashes=hash_files(repo), tests=tests)


def test_runtime_evidence_selects_exactly_the_tests_that_ran_the_changed_unit(repo: Path):
    units = {u.name: u.key for u in ch.code_units((repo / "calc/core.py").read_text())}
    module = units["<module>"]
    tmap = _tmap(repo, {
        "tests/test_add.py": {"status": "pass", "traced": True, "duration_s": 0.1,
                              "units": {"calc/core.py": [module, units["add"]]}},
        "tests/test_scale.py": {"status": "pass", "traced": True, "duration_s": 0.1,
                                "units": {"calc/core.py": [module, units["scale"]]}},
        "tests/test_plugins.py": {"status": "pass", "traced": True, "duration_s": 0.1, "units": {}}})
    _edit(repo, "calc/core.py", "return x * RATE", "return x * RATE + 1")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)), tmap)
    # fresh, complete runtime evidence is authoritative: test_add imports calc.core but never ran scale
    assert [s.test for s in p.selected] == ["tests/test_scale.py"]
    assert p.selected[0].reasons[0].kind == "runtime"
    assert p.confidence == "high"
    # definition-time code runs at import: a new top-level def reaches every test that imported the module
    _edit(repo, "calc/core.py", "class Box:", "def extra():\n    return 0\n\n\nclass Box:")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)), tmap)
    assert {s.test for s in p.selected} == {"tests/test_add.py", "tests/test_scale.py"}
    _edit(repo, "calc/core.py", "def extra():\n    return 0\n\n\nclass Box:", "class Box:")
    # an edit to a unit no recorded test executed is reported as untested, not as safe
    _edit(repo, "calc/core.py", "        return 1", "        return 2")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)), tmap)
    [core] = p.files
    assert "get" in core.never_executed


def test_stale_runtime_evidence_is_ignored(repo: Path):
    tmap = _tmap(repo, {"tests/test_add.py": {"status": "pass", "units": {}}})
    tmap.file_hashes["calc/core.py"] = "0" * 64  # recorded for different content
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)), tmap)
    assert p.files[0].runtime == "stale" and p.confidence == "medium"
    assert {s.test for s in p.selected} >= {"tests/test_add.py"}  # static evidence still applies


# -- the tracer --------------------------------------------------------------
def test_tracer_keys_match_static_code_units(repo: Path, tmp_path: Path):
    out = tmp_path / "trace.json"
    proc = subprocess.run([sys.executable, str(TRACER), "--out", str(out), "--root", str(repo), "--",
                           "-m", "unittest", "tests.test_add"], cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text())
    static = {u.key for u in ch.code_units((repo / "calc/core.py").read_text())}
    traced = set(data["units"]["calc/core.py"])
    assert traced <= static and any(k.endswith(":add") for k in traced)
    assert not any(k.endswith(":scale") for k in traced)  # never ran


# -- the gate ---------------------------------------------------------------
def test_gate_is_silent_until_there_is_unverified_code_and_blocks_once(repo: Path):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    proc = run_cli(repo, "verify", "--gate", stdin="{}")
    assert proc.returncode == 0 and proc.stdout.strip() == ""
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    proc = run_cli(repo, "verify", "--gate", stdin="{}")
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block" and "repo-ai verify --run" in decision["reason"]
    assert run_cli(repo, "verify", "--gate", stdin="{}").stdout.strip() == ""  # once per change
    _edit(repo, "calc/core.py", "return a - b", "return a * b")
    assert run_cli(repo, "verify", "--gate", stdin='{"stop_hook_active": true}').stdout.strip() == ""


def test_verify_plan_cli_is_read_only_and_explains(repo: Path):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    before = sorted(p.as_posix() for p in repo.rglob("*") if ".git" not in p.parts and ".repo-ai" not in p.parts)
    proc = run_cli(repo, "verify", "--json", "--test-command", CMD)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["schema"] == "repo-ai.verify-plan/1"
    assert "tests/test_add.py" in {s["test"] for s in data["selected"]}
    assert data["full_suite_command"] == CMD
    after = sorted(p.as_posix() for p in repo.rglob("*") if ".git" not in p.parts and ".repo-ai" not in p.parts)
    assert before == after  # planning wrote nothing outside repo-ai's state
    assert run_cli(repo, "evidence").returncode == 1  # nothing verified yet


def _host_sandbox() -> bool:
    """A backend exists *and* can start the interpreter (some macOS hosts refuse
    to exec it under sandbox-exec; verify then reports it and runs nothing)."""
    import subprocess
    import tempfile
    from repo_ai.sandbox import SandboxUnavailable
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        try:
            ex = get_executor(Path(d), "auto", "python")
            with isolate.materialize(Path(d)) as ws:
                return ex.in_workspace(ws).run(["python", "-c", "pass"], timeout_s=60).exit_code == 0
        except SandboxUnavailable:
            return False


@pytest.mark.skipif(not _host_sandbox(), reason="no sandbox backend to run tests in")
def test_record_run_and_evidence_end_to_end(repo: Path):
    assert run_cli(repo, "init", "--agent", "none", "-q").returncode == 0
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    rec = run_cli(repo, "verify", "--record", "--json", "--test-command", CMD)
    assert rec.returncode == 0, rec.stderr
    assert json.loads(rec.stdout)["recorded_tests"] == 3
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    proc = run_cli(repo, "verify", "--run", "--json", "--test-command", CMD)
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert out["plan"]["confidence"] == "high"
    failed = [r for r in out["evidence"]["results"] if r["status"] != "pass"]
    assert [r["test"] for r in failed] == ["tests/test_add.py"]
    assert failed[0]["baseline"] == "pass" and failed[0]["classification"].startswith("new failure")
    assert out["evidence"]["verdict"] == "regression"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert all(line[3:].startswith((".repo-ai", "calc/core.py")) for line in status.splitlines()), status
    assert ".repo-ai/run" not in status and ".sandbox-home" not in status, status
    ev = run_cli(repo, "evidence", "--json")
    assert ev.returncode == 0 and json.loads(ev.stdout)["current"] is True
    _edit(repo, "calc/core.py", "return a - b", "return a + b + 0")
    assert run_cli(repo, "evidence").returncode == 2  # stale: the tree changed after the run


def test_sandbox_extra_reads_never_open_home_or_root():
    from repo_ai.sandbox import _safe_reads
    home = str(Path.home().resolve())
    assert _safe_reads(("/", home, "relative/path")) == []


def test_the_stop_hook_gate_is_opt_in(repo: Path):
    assert run_cli(repo, "init", "--agent", "claude", "-q").returncode == 0
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _edit(repo, "calc/core.py", "return a + b", "return a - b")
    assert run_hook(repo, "stop", {"session_id": "s"}).stdout.strip() == ""  # off by default
    cfg = repo / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nverify_gate = true\n")
    out = json.loads(run_hook(repo, "stop", {"session_id": "s"}).stdout)
    assert out["decision"] == "block"
    assert run_hook(repo, "stop", {"session_id": "s"}).stdout.strip() == ""  # once per change


# -- fixes found on the verify-eval dev set ---------------------------------------
def test_import_resolution_fixes():
    from repo_ai.analyze import resolve_imports
    from repo_ai.models import ImportEdge
    paths = ["src/pkg/__init__.py", "src/pkg/keys.py", "docs/reference/markdown.md", "markdown/__init__.py",
             "markdown/core.py", "lib/index.js", "test/a.js", "package.json"]
    edges = [ImportEdge("tests/test_keys.py", "pkg.keys"),        # src layout
             ImportEdge("tests/test_md.py", "markdown"),           # a package, not docs/reference/markdown.md
             ImportEdge("test/a.js", "..")]                       # Node: the package entry
    out = {e.raw_target: e.resolved_path for e in resolve_imports(edges, paths, {}, {"": "lib/index.js"})}
    assert out == {"pkg.keys": "src/pkg/keys.py", "markdown": "markdown/__init__.py", "..": "lib/index.js"}


def test_package_main_is_read_from_package_json(tmp_path: Path):
    from repo_ai.analyze import package_mains
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "index.js").write_text("module.exports = 1\n")
    (tmp_path / "package.json").write_text('{"main": "lib/index.js"}')
    assert package_mains(tmp_path, ["package.json", "lib/index.js"]) == {"": "lib/index.js"}


def test_sources_inside_a_package_that_also_holds_its_tests_are_not_test_helpers():
    from repo_ai.verify.select import classify
    universe = {"pyflakes/test/test_api.py"}
    runner = parse_command("python -m unittest discover -s pyflakes/test -t .")
    assert classify("pyflakes/checker.py", universe, runner) == "source"
    assert classify("pyflakes/test/harness.py", universe, runner) == "test-helper"


def test_a_test_that_spawns_a_process_has_incomplete_runtime_evidence():
    tmap = TestMap(runner={}, tests={"t.py": {"status": "pass", "traced": True, "spawned": ["python3"]},
                                     "u.py": {"status": "pass", "traced": True, "spawned": []}})
    assert not tmap.complete("t.py") and tmap.complete("u.py")


def test_string_references_are_followed_transitively(tmp_path: Path):
    """simplejson: test_tool runs `python -m simplejson.tool` in a subprocess; tool
    imports the package that imports the changed encoder."""
    files = {"pkg/__init__.py": "from pkg.enc import dump\n", "pkg/enc.py": "def dump(x):\n    return str(x)\n",
             "pkg/tool.py": "import pkg\n", "tests/__init__.py": "",
             "tests/test_tool.py": "import subprocess, sys, unittest\nARGV = [sys.executable, '-m', 'pkg.tool']\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    graph = Graph([("pkg/__init__.py", "pkg/enc.py"), ("pkg/tool.py", "pkg/__init__.py")], sorted(files))
    dyn = dynamic.analyze(tmp_path, sorted(files))
    graph.add_inferred(dyn)
    chains = graph.closure(["pkg/enc.py"])
    assert "tests/test_tool.py" in chains
    assert graph.chain_kind(chains["tests/test_tool.py"]) == "string-reference"


# -- fixes found by the demos and the held-out miss (after the freeze) ----------
def test_failing_test_ids_are_parsed_per_runner():
    from repo_ai.verify.evidence import failing_tests
    text = ("FAIL: test_a (tests.test_x.T.test_a)\nERROR: test_b (tests.test_x.T.test_b)\n"
            "FAILED tests/test_y.py::test_c - assert 1\nnot ok 3 - adds numbers\n✖ subtracts (1.2ms)\n")
    assert failing_tests(text) == {"tests.test_x.T.test_a", "tests.test_x.T.test_b", "tests/test_y.py::test_c",
                                   "adds numbers", "subtracts"}


def test_tracer_records_sources_read_as_data_but_not_imports(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("VERSION = '1'\n")
    (tmp_path / "pkg" / "mod.py").write_text("X = 1\n")
    (tmp_path / "t_read.py").write_text("import pkg.mod\nopen('pkg/__init__.py').read()\n")
    (tmp_path / "t_import.py").write_text("import pkg.mod\n")
    for script, expected in (("t_read.py", ["pkg/__init__.py"]), ("t_import.py", [])):
        out = tmp_path / f"{script}.json"
        subprocess.run([sys.executable, str(TRACER), "--out", str(out), "--root", str(tmp_path), "--", script],
                       cwd=tmp_path, check=True, capture_output=True)
        data = json.loads(out.read_text())
        assert data["opened"] == expected, (script, data["opened"])
        assert "pkg/mod.py" in data["units"]


def test_a_test_that_globs_source_files_is_linked_to_every_source_change(repo: Path):
    (repo / "tests" / "test_package.py").write_text(
        "import glob, unittest\n\n\nclass T(unittest.TestCase):\n    def test_headers(self):\n"
        "        for f in glob.glob('calc/*.py'):\n            open(f).read()\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "package test")
    _edit(repo, "calc/core.py", "return a + b", "return b + a")
    files = sorted([*PKG, "tests/test_package.py"])
    p = plan(ch.detect(repo), parse_command(CMD), files, _graph(repo), dynamic.analyze(repo, files))
    assert "tests/test_package.py" in {s.test for s in p.selected}


# -- held-out-2 findings (post-hoc; reported as such in verify-eval/RESULTS.md) --
def test_a_python_file_with_a_utf8_bom_is_parsed():
    from repo_ai.parser import python_symbols_and_imports
    _, imports, _ = python_symbols_and_imports("pkg/base.py", "﻿#!/usr/bin/env python\nfrom pkg.params import P\n")
    assert "pkg.params" in [e.raw_target for e in imports]
    assert ch.code_units("﻿def f():\n    return 1\n".removeprefix("﻿")) is not None
    assert ch._decode("﻿x = 1\n".encode()) == "x = 1\n"


def test_modules_under_a_computed_loader_prefix_are_reachable_and_lower_confidence(tmp_path: Path):
    """pony: core loads `pony.orm.dbproviders.<name>`; a provider imports the changed module."""
    files = {"orm/__init__.py": "from orm.core import Database\n",
             "orm/core.py": "from importlib import import_module\n\n\ndef bind(p):\n"
                            "    return import_module('orm.providers.' + p)\n",
             "orm/providers/__init__.py": "", "orm/providers/sqlite.py": "from orm import translate\n",
             "orm/translate.py": "def t(x):\n    return x\n", "tests/__init__.py": "",
             "tests/test_db.py": "import unittest\nfrom orm import Database\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "orm/translate.py").write_text("def t(x):\n    return None\n")
    names = sorted(files)
    graph = Graph([("orm/__init__.py", "orm/core.py"), ("orm/providers/sqlite.py", "orm/__init__.py"),
                   ("orm/providers/sqlite.py", "orm/translate.py"), ("tests/test_db.py", "orm/__init__.py")], names)
    dyn = dynamic.analyze(tmp_path, names)
    graph.add_inferred(dyn)
    p = plan(ch.detect(tmp_path), parse_command(CMD), names, graph, dyn)
    assert "tests/test_db.py" in {s.test for s in p.selected}
    assert p.confidence == "low" and p.files[0].exposure[0]["kind"] == "reached-through-computed-load"


def test_a_file_no_recorded_test_loaded_keeps_its_static_links(repo: Path):
    """Regression (held-out-3, post-hoc): ZENCHE's tests read a browser script as
    text through the server; no test executed it, so V8 recorded nothing for it,
    and fresh-but-empty evidence used to override the static link that would
    have caught the change. Evidence that never observed a file says nothing."""
    units = {u.name: u.key for u in ch.code_units((repo / "calc/core.py").read_text())}
    tmap = _tmap(repo, {
        "tests/test_add.py": {"status": "pass", "traced": True, "duration_s": 0.1,
                              "units": {"calc/core.py": [units["<module>"], units["add"]]}},
        "tests/test_scale.py": {"status": "pass", "traced": True, "duration_s": 0.1,
                                "units": {"calc/core.py": [units["<module>"], units["scale"]]}},
        "tests/test_plugins.py": {"status": "pass", "traced": True, "duration_s": 0.1, "units": {}}})
    _edit(repo, "calc/loader.py", "f'calc.plugins.{name}'", "f'calc.plugins.{name}_v2'")
    p = plan(ch.detect(repo), parse_command(CMD), sorted(PKG), _graph(repo), dynamic.analyze(repo, sorted(PKG)), tmap)
    [loader] = p.files
    assert loader.runtime == "unobserved"
    assert "tests/test_plugins.py" in {s.test for s in p.selected}  # the static link survives
    assert p.confidence != "high"
