"""C06: routing decisions over the per-provider state space (no live call, no credential, no process).

For each combination of installed / sandboxed / setup / cooldown (none, active, expired) / live observation (each
storable state, fresh, expired or recorded for another binary) / consent, with and without a USD ceiling and the
per-run authorization flag, `route` must select a provider only when it is installed, containable,
set up, not cooling down, not blocked by an observation, consented and within the cost policy; it must say
NOT_AUTHORIZED exactly when something capable lacks consent, NO_AGENT exactly when nothing is capable, and pick the
first eligible provider in order. Decisions are made from inputs alone: starting a process fails the test."""
from __future__ import annotations

import itertools
import shutil
import subprocess
import sys

import pytest

from repo_ai.providers import adapters, registry
from repo_ai.providers.adapters import contract_for
from repo_ai.providers.discovery import PROVIDERS

OBSERVATIONS = (None, "READY", "USAGE_LIMITED", "ACCOUNT_INELIGIBLE", "AUTHORIZED_BUT_UNREADY")
NOW = 1_000_000.0


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("routing started a process")
    import os
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(os, "system", refuse)
    if hasattr(os, "posix_spawn"):
        monkeypatch.setattr(os, "posix_spawn", refuse)


def _setup(monkeypatch, states: dict[str, dict], authorized: list[str]):
    cool = {"active": NOW + 60, "expired": NOW - 1}
    until = {"fresh": NOW + 3600, "expired": NOW - 1, "other-binary": NOW + 3600}
    policy = {"exists": True, "preferred": [], "authorized": authorized,
              "cooldown": {n: cool[s["cooldown"]] for n, s in states.items() if s["cooldown"] in cool},
              "observations": {n: {"state": s["obs"], "until": until[s.get("fresh", "fresh")],
                                   "identity": "another-binary" if s.get("fresh") == "other-binary" else "id-" + n}
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
    # an observation that expired or was recorded for another binary does not count; an expired cooldown neither
    obs = s["obs"] if s["fresh"] == "fresh" else None
    return (s["installed"] and s["isolated"] and not s["setup"] and s["cooldown"] != "active"
            and obs not in {"USAGE_LIMITED", "ACCOUNT_INELIGIBLE", "AUTHORIZED_BUT_UNREADY"} and not over_budget)


# Providers with no tested live containment anywhere but macOS seatbelt (checked against the adapter below).
NO_CONTAINMENT_OFF_MACOS = {"agy", "opencode", "opencode-acp"}


class _Platform:
    """`sys` as seen by one module, with another platform name (the real `sys` is untouched)."""

    def __init__(self, platform: str):
        self.platform = platform

    def __getattr__(self, key):
        return getattr(sys, key)


def _expected_readiness(s: dict, consented: bool, name: str = "claude", platform: str = "darwin") -> str:
    """The label, by the documented priority: not installed, sandbox, setup, quota, account/auth, consent, probed."""
    obs = s["obs"] if s["fresh"] == "fresh" else None
    if not s["installed"]:
        return "NOT_INSTALLED"
    if not s["isolated"]:
        # no containment exists for this provider on this platform, versus a sandbox that exists but did not pass
        unsupported = name in NO_CONTAINMENT_OFF_MACOS and platform != "darwin"
        return "RUNTIME_UNSUPPORTED" if unsupported else "ISOLATION_BLOCKED"
    if s["setup"]:
        return "SETUP_REQUIRED"
    if s["cooldown"] == "active" or obs == "USAGE_LIMITED":
        return "USAGE_LIMITED"
    if obs in {"ACCOUNT_INELIGIBLE", "AUTHORIZED_BUT_UNREADY"}:
        return obs
    if not consented:
        return "AVAILABLE_BUT_UNAUTHORIZED"
    return "READY" if obs == "READY" else "INSTALLED_UNPROBED"


def _space():
    for installed, isolated, setup, cooldown, obs, fresh, consent in itertools.product(
            (True, False), (True, False), (True, False), ("none", "active", "expired"), OBSERVATIONS,
            ("fresh", "expired", "other-binary"), (True, False)):
        if obs is None and fresh != "fresh":
            continue  # freshness applies to a recorded observation only
        yield {"installed": installed, "isolated": isolated, "setup": setup, "cooldown": cooldown, "obs": obs,
               "fresh": fresh, "consent": consent}


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("name", PROVIDERS)  # every provider repo-ai knows, each alone
def test_every_single_provider_state_routes_as_specified(tmp_path, monkeypatch, name, platform):
    monkeypatch.setattr(registry, "sys", _Platform(platform))
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
            row = next(r for r in d["considered"] if r["provider"] == name)
            assert d["outcome"] == want, (name, s, max_cost, run_authorized, row)
            assert d["selected"] == (name if want == "SELECTED" else None)
            assert row["eligible"] == (want == "SELECTED")
            label = _expected_readiness(s, consented, name, platform)
            assert row["readiness"] == label, (name, s, run_authorized, row)
            assert row["status_class"] == registry.STATUS_CLASS[row["readiness"]]
            assert "authenticated" in d["not_evaluated"] and "quota_remaining" in d["not_evaluated"]
            # a provider discovery said nothing about is UNKNOWN and never eligible
            others = [r for r in d["considered"] if r["provider"] != name]
            assert len(others) == len(PROVIDERS) - 1
            assert all(r["readiness"] == "UNKNOWN" and not r["eligible"] for r in others), others
            checked += 1
    states = 2 * 2 * 2 * 3 * (1 + (len(OBSERVATIONS) - 1) * 3) * 2  # 624 states
    assert checked == states * 4  # 2,496 decisions per provider and platform


class _Which:
    """`shutil` as seen by the adapter, where only bwrap is on PATH (the real `shutil` is untouched)."""

    @staticmethod
    def which(name, path=None):
        return "/usr/bin/bwrap" if name == "bwrap" else None

    def __getattr__(self, key):
        return getattr(shutil, key)


@pytest.mark.parametrize("name", PROVIDERS)
def test_runtime_unsupported_matches_the_adapter(tmp_path, monkeypatch, name):
    """The label's premise: on Linux with bubblewrap present, the adapter builds a live sandbox for every provider
    except these, which it refuses (a positive control for the rest, so the refusal is not just a missing bwrap)."""
    from repo_ai.providers import claude_auth
    monkeypatch.setattr(adapters, "sys", _Platform("linux"))
    monkeypatch.setattr(adapters, "shutil", _Which())
    plan = claude_auth.ClaudeAuthPlan("token_env", None, ("ANTHROPIC_API_KEY",), ())
    prefix = adapters._execution_sandbox_prefix(tmp_path, tmp_path, allow_network=True, provider=name, live=True,
                                                claude_plan=plan)
    if name in NO_CONTAINMENT_OFF_MACOS:
        assert prefix is None
    else:
        assert prefix is not None and prefix[0] == "/usr/bin/bwrap", (name, prefix)


def test_a_failed_discovery_is_unknown_and_never_selected(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": "none", "obs": "READY", "fresh": "fresh",
             "consent": True}
    profiles = _setup(monkeypatch, {"claude": ready}, ["claude"])
    profiles[0]["stage"] = profiles[0]["status"] = "FAILED"
    d = registry.route(tmp_path, run_authorized=True, now=NOW, profiles=profiles)
    row = next(r for r in d["considered"] if r["provider"] == "claude")
    assert d["outcome"] == "NO_AGENT" and row["readiness"] == "UNKNOWN" and not row["eligible"]
    assert row["status_class"] == "UNKNOWN"


def test_the_first_eligible_provider_in_order_is_selected(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": "none", "obs": "READY", "fresh": "fresh",
             "consent": True}
    blocked = {**ready, "cooldown": "active"}
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
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": "none", "obs": "READY", "fresh": "fresh",
             "consent": False}
    profiles = _setup(monkeypatch, {"claude": ready}, ["codex"])  # the project allows only codex
    d = registry.route(tmp_path, run_authorized=True, now=NOW, profiles=profiles)
    assert d["outcome"] == "NOT_AUTHORIZED" and d["selected"] is None


def test_a_blocked_stage_is_never_selected(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": "none", "obs": "READY", "fresh": "fresh",
             "consent": True}
    profiles = _setup(monkeypatch, {"claude": ready}, ["claude"])
    profiles[0]["stage"] = "BLOCKED"
    d = registry.route(tmp_path, now=NOW, profiles=profiles)
    row = next(r for r in d["considered"] if r["provider"] == "claude")
    assert d["outcome"] == "NO_AGENT" and row["readiness"] == "ISOLATION_BLOCKED" and not row["eligible"]


def test_preferred_providers_come_first_from_the_argument_and_the_policy(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": "none", "obs": "READY", "fresh": "fresh",
             "consent": True}
    names = ["claude", "codex", "opencode"]
    profiles = _setup(monkeypatch, {n: ready for n in names}, names)
    default = registry.route(tmp_path, now=NOW, profiles=profiles)["selected"]
    other = next(n for n in names if n != default)
    assert registry.route(tmp_path, now=NOW, profiles=profiles, preferred=[other])["selected"] == other
    policy = registry.load_policy(tmp_path)
    policy["preferred"] = [other]
    assert registry.route(tmp_path, now=NOW, profiles=profiles)["selected"] == other


def test_the_argument_outranks_the_policy_and_unknown_names_are_ignored(tmp_path, monkeypatch):
    ready = {"installed": True, "isolated": True, "setup": False, "cooldown": "none", "obs": "READY", "fresh": "fresh",
             "consent": True}
    names = ["claude", "codex", "opencode"]
    profiles = _setup(monkeypatch, {n: ready for n in names}, names)
    registry.load_policy(tmp_path)["preferred"] = ["codex"]
    d = registry.route(tmp_path, now=NOW, profiles=profiles, preferred=["no-such-agent", "opencode"])
    assert d["selected"] == "opencode"
    assert [r["provider"] for r in d["considered"]][:2] == ["opencode", "codex"]
    assert "no-such-agent" not in {r["provider"] for r in d["considered"]}
    # the argument's provider cannot run: the policy's preference is next, ahead of the default order
    profiles = _setup(monkeypatch, {"claude": ready, "codex": ready, "opencode": {**ready, "cooldown": "active"}}, names)
    registry.load_policy(tmp_path)["preferred"] = ["codex"]
    assert registry.route(tmp_path, now=NOW, profiles=profiles, preferred=["opencode"])["selected"] == "codex"
