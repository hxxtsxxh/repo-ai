"""The website's release/evidence facts are generated from validated inputs and kept current.

No network: ``scripts/site_facts.py --check`` reads only files in the repository (and git tags,
when the clone has them).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "site_facts.py"


def _load():
    spec = importlib.util.spec_from_file_location("site_facts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


site_facts = _load()


@pytest.fixture()
def inputs():
    matrix = json.loads(site_facts.MATRIX.read_text(encoding="utf-8"))
    providers = json.loads(site_facts.PROVIDERS.read_text(encoding="utf-8"))
    return copy.deepcopy(matrix), copy.deepcopy(providers)


def _released(matrix=None) -> str:
    """The version of the committed verified PyPI read (the release the site describes), read from the committed
    file so tests that mutate their copy still know it."""
    committed = json.loads(site_facts.MATRIX.read_text(encoding="utf-8"))
    return committed["distribution"]["pypi"]["verified_read"]["version"]


def _build(matrix, providers, *, distribution="repo-ai-cli", version=None, tag=None):
    version = version or _released(matrix)
    tag = tag or "v" + _released(matrix)
    dist = {"distribution": distribution, "command": "repo-ai", "requires_python": ">=3.10"}
    return site_facts.build_facts(matrix=matrix, providers=providers, dist=dist, version=version, tag=tag)


def test_committed_release_facts_are_current():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_committed_inputs_are_valid(inputs):
    matrix, providers = inputs
    assert site_facts.validate_matrix(matrix) == []
    assert site_facts.validate_providers(providers) == []


def test_every_status_is_defined_and_used(inputs):
    matrix, _ = inputs
    assert tuple(matrix["statuses"]) == site_facts.EVIDENCE_STATUSES
    used = {e["status"] for e in matrix["entries"]}
    assert used == set(site_facts.EVIDENCE_STATUSES)


def test_pypi_published_only_from_a_verified_read(inputs):
    matrix, providers = inputs
    facts, problems = _build(matrix, providers)
    assert problems == []
    assert facts["pypi"]["published"] is True
    assert len(facts["pypi"]["wheel_sha256"]) == 64

    del matrix["distribution"]["pypi"]["verified_read"]
    facts, problems = _build(matrix, providers)
    assert problems == []
    assert facts["pypi"]["published"] is False


def test_published_flag_cannot_be_set_by_hand(inputs):
    matrix, providers = inputs
    del matrix["distribution"]["pypi"]["verified_read"]
    matrix["distribution"]["pypi"]["published"] = True
    facts, problems = _build(matrix, providers)
    assert facts["pypi"]["published"] is False
    assert any("must not carry 'published'" in p for p in problems)


def test_verified_read_for_another_distribution_is_rejected(inputs):
    matrix, providers = inputs
    facts, problems = _build(matrix, providers, distribution="something-else")
    assert facts["pypi"]["published"] is False
    assert any("another" in p or "distribution is" in p for p in problems)


def test_verified_read_needs_a_sha256_and_date(inputs):
    matrix, providers = inputs
    read = matrix["distribution"]["pypi"]["verified_read"]
    read["wheel_sha256"] = "not-a-hash"
    read["verified_at"] = "yesterday"
    _, problems = _build(matrix, providers)
    assert any("wheel_sha256" in p for p in problems)
    assert any("verified_at" in p for p in problems)


def test_verified_read_must_match_the_latest_release_tag(inputs):
    matrix, providers = inputs
    _, problems = _build(matrix, providers, tag="v99.0.1")
    assert any("latest release tag" in p for p in problems)


def test_site_describes_the_published_release_when_source_moves_ahead(inputs):
    matrix, providers = inputs
    ahead = _released(matrix) + ".post1.dev0"
    facts, problems = _build(matrix, providers, version=ahead)
    assert problems == []
    assert facts["site_version"] == _released(matrix)
    assert facts["package"]["version"] == ahead


def test_unknown_status_and_missing_source_are_rejected(inputs):
    matrix, providers = inputs
    matrix["entries"][0]["status"] = "PROVEN"
    matrix["entries"][1]["source"] = "docs/does-not-exist.md"
    matrix["entries"][2]["date"] = "last week"
    del matrix["entries"][3]["sample_size"]
    problems = site_facts.validate_matrix(matrix)
    assert any("unknown status 'PROVEN'" in p for p in problems)
    assert any("does-not-exist" in p for p in problems)
    assert any("date must be" in p for p in problems)
    assert any("'sample_size' is required" in p for p in problems)


def test_provider_execution_label_needs_an_execution_observation(inputs):
    _, providers = inputs
    row = next(p for p in providers["providers"] if p["id"] == "codex")
    row["label"] = "BLOCKED"  # the label no longer matches its recorded EXECUTION observation
    problems = site_facts.validate_providers(providers)
    assert any("must go together" in p for p in problems)
    row["label"] = "WORKS"
    problems = site_facts.validate_providers(providers)
    assert any("unknown label 'WORKS'" in p for p in problems)


def test_release_tag_ignores_pre_releases(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
        cwd=tmp_path,
        check=True,
    )
    for tag in ("v0.8.0", "v0.10.0-dev1", "v0.9.0", "v0.10.0rc1"):
        subprocess.run(["git", "tag", tag], cwd=tmp_path, check=True)
    assert site_facts.latest_release_tag(tmp_path) == "v0.9.0"
