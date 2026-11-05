"""X13b: `repo-ai evidence` and the Stop-hook gate judged evidence current by
the change fingerprint and base alone, so after `pip install -U` or an edit
inside site-packages they called a pass of the same change current although
its tests now fail. A run now records a static identity of its test
environment (`environment_static`: the interpreter and `pyvenv.cfg` by
`stat`, the site-packages and dependency directories by `cache._tree_id`),
and both readers recompute it from the recorded paths alone: the gate runs
on every stop and must never execute the project's interpreter or any
repository code."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import run_cli, run_hook
from test_verify_adaptive import CMD, needs_sandbox
from test_verify_environment_key_venv import _project
from test_verify_gate import PASSED, _decide, _git, _layout

from repo_ai import __version__
from repo_ai.verify import cache, changes, evidence

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX virtualenv layout; Windows has no host sandbox")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))
    root = tmp_path / "g"
    (root / "calc").mkdir(parents=True)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A virtualenv outside the repository whose interpreter touches a marker
    when executed (it must never be)."""
    marker = tmp_path / "interpreter-executed"
    venv = tmp_path / "venv"
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "depcalc.py").write_text("def plus(a, b):\n    return a + b\n")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.1\n")
    py = venv / "bin" / "python"
    py.parent.mkdir()
    py.write_text(f"#!/bin/sh\ntouch {marker}\nexec {sys.executable} \"$@\"\n")
    py.chmod(0o755)
    return py, site, marker


def _record(root: Path, python: Path, site: Path) -> dict:
    """What a passing `verify --run` of the current tree records."""
    executor = SimpleNamespace(is_container=False, python=str(python), node="node", site_dirs=[str(site)], links={})
    rec = {"schema": evidence.SCHEMA, "repo_ai_version": __version__, "fingerprint": changes.fingerprint(root), "base": "HEAD",
           "semantic_fingerprint": changes.semantic_fingerprint(root), "verdict": PASSED,
           "source_tree": {"unchanged": True},
           "environment_static": cache.static_environment(executor, SimpleNamespace(kind="unittest"), links={})}
    evidence.save(_layout(root).state_dir, rec)
    return rec


def _evidence(root: Path) -> dict:
    return json.loads(run_cli(root, "evidence", "--json").stdout)


def test_an_unchanged_environment_stays_current_and_nothing_is_executed(repo: Path, tmp_path: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, marker = _env(tmp_path)
    rec = _record(repo, python, site)
    assert rec["environment_static"]["dirs"] == [str(site)]
    assert str(tmp_path / "venv" / "pyvenv.cfg") in rec["environment_static"]["files"]
    assert _decide(repo) is None  # a pass in the same environment: silent
    out = _evidence(repo)
    assert out["current"] and out["stale_reason"] is None and out["environment_check"] == "unchanged", out
    cfg = repo / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nverify_gate = true\n")
    assert run_hook(repo, "stop", {"session_id": "s"}).stdout.strip() == ""  # the real Stop hook
    assert not marker.exists(), "the gate or `repo-ai evidence` executed the project's interpreter"


def test_an_edit_inside_site_packages_makes_the_pass_stale(repo: Path, tmp_path: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, marker = _env(tmp_path)
    _record(repo, python, site)
    (site / "depcalc.py").write_text("def plus(a, b):\n    return a - b\n")  # an in-place edit
    out = _evidence(repo)
    assert out["current"] is False and out["same_behaviour"] is False, out
    assert out["stale_reason"] == "environment" and out["environment_check"] == "changed"
    assert run_cli(repo, "evidence").returncode == 2
    cfg = repo / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nverify_gate = true\n")
    blocked = json.loads(run_hook(repo, "stop", {"session_id": "s"}).stdout)  # the real Stop hook
    assert blocked["decision"] == "block" and "environment" in blocked["reason"], blocked
    assert _decide(repo) is None  # once per stale pass
    assert not marker.exists()


def test_the_report_mode_gate_says_a_stale_pass_is_unverified(repo: Path, tmp_path: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, _marker = _env(tmp_path)
    _record(repo, python, site)
    (site / "depcalc.py").write_text("def plus(a, b):\n    return a - b\n")
    out = _decide(repo, mode="report")
    assert out and "unverified" in out["systemMessage"] and "environment" in out["systemMessage"], out


def test_an_upgraded_package_and_a_vanished_directory_are_stale(repo: Path, tmp_path: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, _marker = _env(tmp_path)
    _record(repo, python, site)
    (site / "depcalc-2.0.dist-info").mkdir()  # `pip install -U depcalc`
    assert _evidence(repo)["stale_reason"] == "environment"
    _record(repo, python, site)
    assert _evidence(repo)["current"]
    import shutil
    shutil.rmtree(tmp_path / "venv")  # the virtualenv was deleted or recreated elsewhere
    out = _evidence(repo)
    assert out["current"] is False and "no longer exists" in out["environment_detail"], out


def test_a_record_without_the_environment_identity_is_stale(repo: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    evidence.save(_layout(repo).state_dir, {
        "schema": evidence.SCHEMA, "repo_ai_version": __version__, "fingerprint": changes.fingerprint(repo), "base": "HEAD",
        "semantic_fingerprint": changes.semantic_fingerprint(repo), "verdict": PASSED, "source_tree": {"unchanged": True}})
    out = _evidence(repo)
    assert not out["current"] and out["environment_check"] == "changed", out
    assert "does not identify its test environment" in run_cli(repo, "evidence").stdout
    assert _decide(repo)["decision"] == "block"


def test_a_malformed_environment_identity_is_stale_not_trusted(repo: Path, tmp_path: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, _marker = _env(tmp_path)
    rec = _record(repo, python, site)
    for bad in ({**rec["environment_static"], "dirs": ["relative/site-packages"]},
                {**rec["environment_static"], "version": 99}, "not a dict"):
        evidence.save(_layout(repo).state_dir, {**rec, "environment_static": bad})
        assert _evidence(repo)["stale_reason"] == "environment", bad
    blocked = _decide(repo)  # the gate does not fail open on it either
    assert blocked and blocked["decision"] == "block", blocked


@needs_sandbox
def test_after_a_real_run_an_installed_module_edited_in_place_is_not_current(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))
    root, site = _project(tmp_path)
    env = {"VIRTUAL_ENV": str(tmp_path / "venv")}
    (root / "calc" / "core.py").write_text("from depcalc import plus\n\n\ndef add(a, b):\n    return plus(b, a)\n")
    first = run_cli(root, "verify", "--run", "--json", "--test-command", CMD, env=env)
    assert first.returncode == 0, first.stdout[-1500:] + first.stderr
    assert json.loads(run_cli(root, "evidence", "--json", env=env).stdout)["current"]
    assert _decide(root) is None

    (site / "depcalc.py").write_text("def plus(a, b):\n    return a - b\n")  # the tests now fail
    out = json.loads(run_cli(root, "evidence", "--json", env=env).stdout)
    assert out["current"] is False, "`repo-ai evidence` called a pass from another environment current"
    blocked = _decide(root)
    assert blocked and blocked["decision"] == "block", "the gate counted a pass from another environment"
    assert out["stale_reason"] == "environment", out
    rec = json.loads(first.stdout)["evidence"]
    assert any(Path(d).resolve() == site.resolve() for d in rec["environment_static"]["dirs"]), rec


def test_evidence_written_by_another_repo_ai_version_is_stale(repo: Path, tmp_path: Path):
    """The release-freeze fresh-wheel review (D1): evidence written by another build (main 903984a reports 0.7.7)
    read as current under 0.8.0rc1, and the gate accepted it. A pass vouches only for the engine that judged it."""
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, marker = _env(tmp_path)
    rec = _record(repo, python, site)
    assert _evidence(repo)["current"]
    rec["repo_ai_version"] = "0.7.7"
    evidence.save(_layout(repo).state_dir, rec)
    out = _evidence(repo)
    assert out["current"] is False and out["stale_reason"] == "environment", out
    assert "0.7.7" in out["environment_detail"] and __version__ in out["environment_detail"]
    assert run_cli(repo, "evidence").returncode == 2
    cfg = repo / ".repo-ai" / "config.toml"
    cfg.write_text(cfg.read_text() + "\nverify_gate = true\n")
    blocked = json.loads(run_hook(repo, "stop", {"session_id": "s"}).stdout)
    assert blocked["decision"] == "block", blocked
    rec["repo_ai_version"] = __version__
    evidence.save(_layout(repo).state_dir, rec)
    assert _evidence(repo)["current"]
    assert not marker.exists()


@pytest.mark.parametrize("version", [None, "", "0.7.7"])
def test_missing_or_old_version_never_counts_as_current(repo, tmp_path, version):
    python, site, marker = _env(tmp_path)
    rec = _record(repo, python, site)
    rec.pop("repo_ai_version")
    if version is not None:
        rec["repo_ai_version"] = version
    evidence.save(_layout(repo).state_dir, rec)
    out = _evidence(repo)
    assert not out["current"] and out["stale_reason"] == "environment", out
    assert not marker.exists()


def test_changed_active_virtualenv_is_stale_without_executing_it(repo, tmp_path, monkeypatch):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, marker = _env(tmp_path)
    _record(repo, python, site)
    assert _evidence(repo)["current"]
    other = tmp_path / "other"
    other.mkdir()
    alt, _, alt_marker = _env(other)
    monkeypatch.setenv("VIRTUAL_ENV", str(alt.parent.parent))
    out = _evidence(repo)
    assert not out["current"] and "selected interpreter changed" in out["environment_detail"], out
    assert "STALE" in run_cli(repo, "evidence").stdout
    assert _decide(repo)["decision"] == "block"
    assert not marker.exists() and not alt_marker.exists()


@pytest.mark.parametrize("kind,executable", [("pytest", "python3"), ("node", "node")])
def test_changed_path_interpreter_is_stale_without_execution(repo, tmp_path, monkeypatch, kind, executable):
    import os
    import shutil
    from repo_ai.verify.execute import interpreter

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    binary = interpreter(repo, probe=False).python if kind == "pytest" else shutil.which("node")
    if binary is None:
        pytest.skip("node not installed")
    executor = SimpleNamespace(is_container=False, python=binary, node=binary, site_dirs=[], links={})
    rec = {"schema": evidence.SCHEMA, "repo_ai_version": __version__, "base": "HEAD",
           "fingerprint": changes.fingerprint(repo), "verdict": PASSED,
           "environment_static": cache.static_environment(executor, SimpleNamespace(kind=kind))}
    evidence.save(_layout(repo).state_dir, rec)
    assert _evidence(repo)["current"]
    altbin = tmp_path / "altbin"
    altbin.mkdir()
    marker = tmp_path / "executed"
    alt = altbin / executable
    alt.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    alt.chmod(0o755)
    monkeypatch.setenv("PATH", str(altbin) + os.pathsep + os.environ["PATH"])
    out = _evidence(repo)
    assert not out["current"] and "selected interpreter changed" in out["environment_detail"], out
    assert not marker.exists()


@pytest.mark.parametrize("binary", [None, "", "/different/python"])
def test_incomplete_host_interpreter_identity_is_stale(repo, tmp_path, binary):
    python, site, marker = _env(tmp_path)
    rec = _record(repo, python, site)
    if binary is None:
        rec["environment_static"].pop("interpreter")
    else:
        rec["environment_static"]["interpreter"] = binary
    evidence.save(_layout(repo).state_dir, rec)
    out = _evidence(repo)
    assert not out["current"] and out["stale_reason"] == "environment", out
    assert not marker.exists()


@pytest.mark.parametrize("plan", ["bad", {"runner": "bad"}, {"runner": []},
                                  {"runner": {"kind": []}}, {"runner": {"kind": ["python"]}},
                                  {"runner": {"kind": {}}}])
def test_malformed_legacy_runner_identity_is_stale(repo, tmp_path, plan):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    python, site, marker = _env(tmp_path)
    rec = _record(repo, python, site)
    rec["environment_static"].pop("toolchain")
    rec["plan"] = plan
    evidence.save(_layout(repo).state_dir, rec)
    assert not _evidence(repo)["current"]
    assert _decide(repo)["decision"] == "block"
    assert not marker.exists()


def test_container_identity_remains_explicitly_unchecked(repo):
    executor = SimpleNamespace(is_container=True, links={})
    rec = {"repo_ai_version": __version__,
           "environment_static": cache.static_environment(executor, SimpleNamespace(kind="pytest"))}
    assert evidence.environment_check(rec, repo) == ("unchanged", "")
    rec["environment_static"].pop("unchecked")
    assert evidence.environment_check(rec, repo)[0] == "changed"
