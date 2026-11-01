"""C06: every routing decision over the whole per-provider state space (no live call, no credential, no subprocess).

For each combination of installed / sandboxed / setup / cooldown / live observation / consent, with and without a USD
ceiling and the per-run authorization flag, `route` must select a provider only when it is installed, containable,
set up, not cooling down, not blocked by an observation, consented and within the cost policy; it must say
NOT_AUTHORIZED exactly when something capable lacks consent, NO_AGENT exactly when nothing is capable, and pick the
first eligible provider in order. Decisions are made from inputs alone: starting a process fails the test."""
from __future__ import annotations

import itertools
import subprocess

import pytest

from repo_ai.providers import registry
from repo_ai.providers.adapters import contract_for

OBSERVATIONS = (None, "READY", "USAGE_LIMITED", "ACCOUNT_INELIGIBLE", "AUTHORIZED_BUT_UNREADY")
NOW = 1_000_000.0


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("routing started a process")
    monkeypatch.setattr(subprocess, "Popen", refuse)


def _setup(monkeypatch, states: dict[str, dict], authorized: list[str]):
    policy = {"exists": True, "preferred": [], "authorized": authorized,
              "cooldown": {n: NOW + 60 for n, s in states.items() if s["cooldown"]},
              "observations": {n: {"state": s["obs"], "until": NOW + 3600, "identity": "id-" + n}
                               for n, s in states.items() if s["obs"]}}
    monkeypatch.setattr(registry, "load_policy", lambda root: policy)
    monkeypatch.setattr(registry, "_isolated_ready", lambda name: states.get(name, {}).get("isolated", False))
    monkeypatch.setattr(registry, "setup_problems",
                        lambda name: ["login missing"] if states.get(name, {}).get("setup") else [])
    return [{"provider": n, "stage": "DISCOVERED" if s["installed"] else "NOT_INSTALLED",
             "status": "DISCOVERED" if s["installed"] else "NOT_INSTALLED", "identity_sha256": "id-" + n}
            for n, s in states.items()]


def _expected_capable(name: str, s: dict, max_cost: float) -> bool:
    over_budget = max_cost > 0 and not contract_for(name).enforces_hard_usd_budget
    return (s["installed"] and s["isolated"] and not s["setup"] and not s["cooldown"]
            and s["obs"] not in {"USAGE_LIMITED", "ACCOUNT_INELIGIBLE", "AUTHORIZED_BUT_UNREADY"} and not over_budget)


def _space():
    for installed, isolated, setup, cooldown, obs, consent in itertools.product(
            (True, False), (True, False), (True, False), (True, False), OBSERVATIONS, (True, False)):
        yield {"installed": installed, "isolated": isolated, "setup": setup, "cooldown": cooldown, "obs": obs,
               "consent": consent}


@pytest.mark.parametrize("name", ["claude", "codex"])  # one enforces a USD ceiling, one does not
def test_every_single_provider_state_routes_as_specified(tmp_path, monkeypatch, name):
    checked = 0
    for s in _space():
        for max_cost, run_authorized in itertools.product((0.0, 1.0), (False, True)):
            profiles = _setup(monkeypatch, {name: s}, [name] if s["consent"] else [])
            d = registry.route(tmp_path, max_cost_usd=max_cost, run_authorized=run_authorized, now=NOW,
                               profiles=profiles)
            capable = _expected_capable(name, s, max_cost)
            # an empty persisted allowlist lets the per-run flag authorize; a non-empty one restricts it
            consented = s["consent"] or run_authorized
            want = "SELECTED" if capable and consented else "NOT_AUTHORIZED" if capable else "NO_AGENT"
            assert d["outcome"] == want, (name, s, max_cost, run_authorized, d["considered"][0])
            assert d["selected"] == (name if want == "SELECTED" else None)
            row = next(r for r in d["considered"] if r["provider"] == name)
            assert row["eligible"] == (want == "SELECTED")
            assert "authenticated" in d["not_evaluated"] and "quota_remaining" in d["not_evaluated"]
            checked += 1
    assert checked == 2 * 2 * 2 * 2 * len(OBSERVATIONS) * 2 * 4


def test_the_first_eligible_provider_in_order_is_selected(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": False, "obs": "READY", "consent": True}
    blocked = {**ready, "cooldown": True}
    order = [n for n in registry.DEFAULT_ORDER if n in ("claude", "codex", "opencode")]
    for first_ok in range(len(order)):
        states = {n: (blocked if i < first_ok else ready) for i, n in enumerate(order)}
        profiles = _setup(monkeypatch, states, list(states))
        d = registry.route(tmp_path, now=NOW, profiles=profiles)
        assert d["outcome"] == "SELECTED" and d["selected"] == order[first_ok]
    states = {n: blocked for n in order}
    profiles = _setup(monkeypatch, states, list(states))
    assert registry.route(tmp_path, now=NOW, profiles=profiles)["outcome"] == "NO_AGENT"


def test_a_persisted_allowlist_restricts_the_per_run_flag(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": False, "obs": "READY", "consent": False}
    profiles = _setup(monkeypatch, {"claude": ready}, ["codex"])  # the project allows only codex
    d = registry.route(tmp_path, run_authorized=True, now=NOW, profiles=profiles)
    assert d["outcome"] == "NOT_AUTHORIZED" and d["selected"] is None
