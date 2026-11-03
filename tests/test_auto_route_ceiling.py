"""Queue row 28: at the default $0 (no ceiling), auto-routing must not choose a provider whose CLI enforces a USD
ceiling (it would be refused before it starts). It skips it, says why, and says how to use it. No process starts."""
from __future__ import annotations

import subprocess

import pytest

from repo_ai.providers import registry
from repo_ai.providers.adapters import contract_for


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("routing started a process")
    monkeypatch.setattr(subprocess, "Popen", refuse)


def _setup(monkeypatch, installed: list[str]):
    policy = {"exists": True, "preferred": [], "authorized": [], "cooldown": {}, "observations": {}}
    monkeypatch.setattr(registry, "load_policy", lambda root: policy)
    monkeypatch.setattr(registry, "_isolated_ready", lambda name: True)
    monkeypatch.setattr(registry, "setup_problems", lambda name: [])
    return [{"provider": n, "stage": "DISCOVERED", "status": "DISCOVERED", "identity_sha256": "id-" + n}
            for n in installed]


def test_enforcing_provider_has_a_ceiling_flag():
    assert contract_for("claude").enforces_hard_usd_budget
    assert not contract_for("codex").enforces_hard_usd_budget


def test_zero_ceiling_skips_claude_for_codex(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude", "codex"])
    d = registry.route(tmp_path, max_cost_usd=0.0, run_authorized=True, preferred=["claude", "codex"], profiles=profiles)
    assert d["outcome"] == "SELECTED" and d["selected"] == "codex"
    row = next(r for r in d["considered"] if r["provider"] == "claude")
    assert not row["eligible"]
    assert any("--max-cost-usd" in r for r in row["reasons"])


def test_ceiling_given_keeps_claude_first(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude", "codex"])
    d = registry.route(tmp_path, max_cost_usd=0.5, run_authorized=True, preferred=["claude", "codex"], profiles=profiles)
    assert d["selected"] == "claude"


def test_only_enforcing_provider_says_how_to_enable_it(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude"])
    d = registry.route(tmp_path, max_cost_usd=0.0, run_authorized=True, preferred=["claude"], profiles=profiles)
    assert d["outcome"] == "NO_AGENT" and d["selected"] is None
    assert "--max-cost-usd" in d["why"] and "claude" in d["why"]


def test_below_ceiling_precision_counts_as_none(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude", "codex"])
    d = registry.route(tmp_path, max_cost_usd=0.00001, run_authorized=True, preferred=["claude", "codex"],
                       profiles=profiles)
    # too small for the CLI flag, so Claude is out; and any positive ceiling rules out Codex (it cannot enforce one)
    assert d["outcome"] == "NO_AGENT" and d["selected"] is None
    claude = next(r for r in d["considered"] if r["provider"] == "claude")
    assert any("--max-cost-usd" in r for r in claude["reasons"])


def test_unauthorized_ceiling_provider_is_not_reported_as_usable(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude"])
    d = registry.route(tmp_path, max_cost_usd=0.0, run_authorized=False, preferred=["claude"], profiles=profiles)
    assert d["outcome"] == "NO_AGENT"
