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


def test_a_positive_ceiling_below_the_flag_precision_is_named_as_such(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude"])
    d = registry.route(tmp_path, max_cost_usd=0.00005, run_authorized=True, preferred=["claude"], profiles=profiles)
    claude = next(r for r in d["considered"] if r["provider"] == "claude")
    assert any("$0.00005 is below the smallest it can enforce" in r for r in claude["reasons"])
    assert not any("none was given" in r for r in claude["reasons"])


def test_an_unauthorized_ceiling_provider_names_both_blockers(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude"])
    d = registry.route(tmp_path, max_cost_usd=0.0, run_authorized=False, preferred=["claude"], profiles=profiles)
    assert "--max-cost-usd" in d["why"] and "also not authorized" in d["why"] and "authorize" in d["why"]
    claude = next(r for r in d["considered"] if r["provider"] == "claude")
    assert any(r.startswith("not authorized") for r in claude["reasons"])


def test_the_ceiling_reason_is_only_given_to_otherwise_usable_providers(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["codex"])  # claude and bob are not installed
    d = registry.route(tmp_path, max_cost_usd=0.0, run_authorized=True, profiles=profiles)
    for name in ("claude", "bob"):
        row = next(r for r in d["considered"] if r["provider"] == name)
        assert not any("USD ceiling" in r for r in row["reasons"]), row



def test_an_authorized_ceiling_provider_is_named_behind_another_providers_not_authorized(monkeypatch, tmp_path):
    profiles = _setup(monkeypatch, ["claude", "codex"])
    registry.load_policy(tmp_path)["authorized"] = ["claude"]  # `agents authorize claude`, then no --max-cost-usd
    d = registry.route(tmp_path, max_cost_usd=0.0, run_authorized=True, preferred=["claude", "codex"], profiles=profiles)
    assert d["outcome"] == "NOT_AUTHORIZED" and "codex" in d["why"]
    assert "claude enforces a USD ceiling" in d["why"] and "--max-cost-usd" in d["why"]
