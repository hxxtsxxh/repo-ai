"""The security-fixture tests are skipped on developer machines by default, so CI must run them."""
from __future__ import annotations

import re
from pathlib import Path

from conftest import SECURITY_FIXTURE_MODULES

ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_the_security_fixture_tests_in_every_job():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    top = workflow.split("\njobs:", 1)[0]
    assert re.search(r'(?m)^env:\n(?:  .*\n)*  REPO_AI_SECURITY_FIXTURES: "1"$', top), \
        "ci.yml must set REPO_AI_SECURITY_FIXTURES=1 at workflow level"
    assert "REPO_AI_SECURITY_FIXTURES" not in workflow.split("\njobs:", 1)[1], "no job may override it"


def test_every_listed_module_exists():
    missing = sorted(m for m in SECURITY_FIXTURE_MODULES if not (ROOT / "tests" / f"{m}.py").exists())
    assert not missing, missing


def test_a_pull_request_job_runs_the_listed_modules_on_macos():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  test-macos-security:\n", 1)[1].split("\n  # ", 1)[0]
    assert "macos" in job and "if:" not in job and "SECURITY_FIXTURE_MODULES" in job
