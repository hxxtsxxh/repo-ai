"""A skill written for this repository counts as relevant (C10 pilot finding, 2026-10-30).

`skills explain` used to advise against installing a local skill that states this repository's own conventions,
because it matched no detected capability gap. Naming one of the repository's own packages is now relevance for a
local skill only: a network candidate could name the package to promote itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import commit_all, make_repo, run_cli

from repo_ai import radar, recommend

DESC = "Use when adding or changing any money, discount, tax or split logic in invoicekit. States the invoicing rules."
ELIGIBLE = {"verdict": "eligible", "findings": [], "files": []}


def cand(provider: str = "local", desc: str = DESC) -> dict:
    return {"id": f"{provider}/invoicekit-conventions@1", "name": "invoicekit-conventions", "provider": provider,
            "description": desc, "owner": "", "stars": 0, "matched_gaps": []}


def test_own_packages_are_the_repositorys_top_level_python_packages():
    paths = ["invoicekit/__init__.py", "invoicekit/money.py", "src/ledger_core/__init__.py", "app/__init__.py",
             "tests/__init__.py", "a/b/__init__.py", "abc/__init__.py", "my-pkg/__init__.py", "README.md",
             "data/__init__.py", "models/__init__.py", "users/__init__.py", "settings/__init__.py"]
    assert radar.own_packages(paths) == ["invoicekit", "ledger_core"]


def test_local_skill_naming_the_package_is_recommended():
    rec = recommend.recommend([cand()], {cand()["id"]: ELIGIBLE}, {"gaps": [], "own_packages": ["invoicekit"]}, {})
    r = rec["recommendations"][0]
    assert r["install_recommended"] is True and r["project_packages"] == ["invoicekit"]
    assert "written for this repository: names its package invoicekit" in r["reasons"]
    assert rec["summary"] == "1 skill(s) recommended: 0 for 0 gap(s), 1 written for this repository"


@pytest.mark.parametrize("provider", ["github", "url", "skills-registry"])
def test_network_skill_naming_the_package_gets_no_boost(provider: str):
    c = cand(provider)
    rec = recommend.recommend([c], {c["id"]: ELIGIBLE}, {"gaps": [], "own_packages": ["invoicekit"]}, {})
    r = rec["recommendations"][0]
    assert r["install_recommended"] is False and r["project_packages"] == []
    assert any("is not a local skill" in reason for reason in r["reasons"])
    assert rec["summary"].startswith("No additional skills are necessary")


@pytest.mark.parametrize("desc", ["Rules for myinvoicekit billing.", "Rules for invoicekits.", "Writes slides."])
def test_package_must_be_named_as_a_word(desc: str):
    c = {**cand(desc=desc), "name": "billing-rules"}  # the name counts too, so keep the package out of it
    r = recommend.score(c, ELIGIBLE, {"gaps": [], "own_packages": ["invoicekit"]}, {})
    assert r.install_recommended is False and r.project_packages == []


def test_blocked_local_project_skill_is_still_refused():
    blocked = {"verdict": "blocked", "findings": [{"category": "remote-exec", "rule": "x", "severity": "critical",
                                                   "evidence": "e"}], "files": []}
    r = recommend.score(cand(), blocked, {"gaps": [], "own_packages": ["invoicekit"]}, {})
    assert r.install_recommended is False


def test_explain_recommends_a_project_skill_end_to_end(tmp_path: Path):
    home = {"REPO_AI_HOME": str(tmp_path / "rh"), "REPO_AI_NO_BACKGROUND": "1"}
    repo = make_repo(tmp_path, "pyweb")
    (repo / "invoicekit").mkdir()
    (repo / "invoicekit" / "__init__.py").write_text('"""Invoicing helpers."""\n')
    commit_all(repo, "add invoicekit")
    assert run_cli(repo, "init", "--agent", "none", "-q", env=home).returncode == 0
    src = tmp_path / "incoming" / "invoicekit-conventions"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text(f'---\nname: invoicekit-conventions\ndescription: "{DESC}"\nlicense: MIT\n---\n'
                                  "# Rules\n\n1. Amounts are integer cents.\n", encoding="utf-8")
    proc = run_cli(repo, "skills", "discover", "--from-path", str(src), "--json", env=home)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["profile"]["own_packages"] == ["invoicekit"]
    proc = run_cli(repo, "skills", "explain", "invoicekit-conventions", env=home)
    assert proc.returncode == 0, proc.stderr
    assert "recommendation: install" in proc.stdout and "written for this repository" in proc.stdout


@pytest.mark.parametrize("desc", ["Rules for changing ledger-core postings.", "Rules for ledger_core.",
                                  "Rules for the Ledger Core package."])
def test_hyphen_underscore_and_space_forms_name_the_package(desc: str):
    r = recommend.score({**cand(desc=desc), "name": "ledger-core-conventions"}, ELIGIBLE,
                        {"gaps": [], "own_packages": ["ledger_core"]}, {})
    assert r.install_recommended is True and r.project_packages == ["ledger_core"]


def test_the_name_alone_is_not_enough():
    c = {**cand(desc=""), "name": "invoicekit"}  # the name is only the directory name
    r = recommend.score(c, ELIGIBLE, {"gaps": [], "own_packages": ["invoicekit"]}, {})
    assert r.install_recommended is False and r.project_packages == []


def test_project_skill_keeps_its_place_when_a_stronger_skill_takes_a_shared_gap():
    gap = {"id": "test-coverage", "title": "tests", "evidence": ["x"], "strength": 0.9, "covered_by": [],
           "query_terms": []}
    profile = {"gaps": [gap], "own_packages": ["invoicekit"]}
    project = {**cand(desc=DESC + " Writes tests."), "matched_gaps": ["test-coverage"]}
    strong = {"id": "github/o/r/test-writer@1", "name": "test-writer", "provider": "github", "owner": "anthropics",
              "stars": 5000, "matched_gaps": ["test-coverage"],
              "description": "Writes focused unit tests for untested modules. Use when adding tests to any package. " * 2}
    rec = recommend.recommend([project, strong], {project["id"]: ELIGIBLE, strong["id"]: ELIGIBLE}, profile, {})
    by_name = {r["name"]: r for r in rec["recommendations"]}
    assert by_name["test-writer"]["install_recommended"] is True
    assert by_name["invoicekit-conventions"]["install_recommended"] is True


def test_autopilot_does_not_act_on_project_relevance_alone():
    project_only = recommend.score(cand(), ELIGIBLE, {"gaps": [], "own_packages": ["invoicekit"]}, {}).to_json()
    assert project_only["install_recommended"] is True
    assert recommend.autopilot_wants(project_only) is False
    gap = {"id": "test-coverage", "title": "tests", "evidence": ["x"], "strength": 0.9, "covered_by": [],
           "query_terms": []}
    filled = recommend.score({**cand(desc=DESC), "matched_gaps": ["test-coverage"]}, ELIGIBLE,
                             {"gaps": [gap], "own_packages": []}, {}).to_json()
    assert recommend.autopilot_wants(filled) is True
