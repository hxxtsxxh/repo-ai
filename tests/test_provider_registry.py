"""Capability routing: zero / one / many providers, consent, cooldown, cost policy."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repo_ai.providers import registry
from repo_ai.providers.discovery import PROVIDERS


def _profiles(*installed: str) -> list[dict]:
    return [{"provider": p, "stage": "DISCOVERED" if p in installed else "NOT_INSTALLED",
             "status": "PLANNING_ONLY" if p in installed else "NOT_INSTALLED"} for p in PROVIDERS]


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(registry, "_isolated_ready", lambda provider: True)
    return tmp_path


def test_zero_providers_is_no_agent_not_a_default(repo: Path) -> None:
    r = registry.route(repo, run_authorized=True, profiles=_profiles())
    assert r["outcome"] == "NO_AGENT" and r["selected"] is None


def test_single_provider_needs_consent(repo: Path) -> None:
    r = registry.route(repo, profiles=_profiles("agy"))
    assert r["outcome"] == "NOT_AUTHORIZED" and r["selected"] is None
    r = registry.route(repo, run_authorized=True, profiles=_profiles("agy"))
    assert (r["outcome"], r["selected"]) == ("SELECTED", "agy")


def test_policy_allowlist_limits_selection_even_when_run_is_authorized(repo: Path) -> None:
    registry.authorize(repo, "codex")
    r = registry.route(repo, run_authorized=True, profiles=_profiles("bob", "codex"))
    assert r["selected"] == "codex"
    bob = next(c for c in r["considered"] if c["provider"] == "bob")
    assert bob["authorized"] is False and not bob["eligible"]


def test_persisted_policy_authorizes_without_run_flag_and_revoke_removes_it(repo: Path) -> None:
    registry.authorize(repo, "agy")
    assert registry.route(repo, profiles=_profiles("agy"))["selected"] == "agy"
    registry.revoke(repo, "agy")
    assert registry.route(repo, profiles=_profiles("agy"))["outcome"] == "NOT_AUTHORIZED"


def test_many_providers_order_is_deterministic_and_preference_wins(repo: Path) -> None:
    prof = _profiles("bob", "codex", "agy")
    assert registry.route(repo, run_authorized=True, profiles=prof)["selected"] == "bob"
    registry.authorize(repo, "agy", prefer=True)
    registry.authorize(repo, "bob")
    assert registry.route(repo, run_authorized=True, profiles=prof)["selected"] == "agy"
    assert registry.route(repo, run_authorized=True, profiles=prof, preferred=["bob"])["selected"] == "bob"


def test_rate_limited_provider_is_skipped_until_cooldown_expires(repo: Path) -> None:
    registry.note_rate_limited(repo, "bob", now=1000.0)
    prof = _profiles("bob", "codex")
    assert registry.route(repo, run_authorized=True, profiles=prof, now=1500.0)["selected"] == "codex"
    assert registry.route(repo, run_authorized=True, profiles=prof, now=1000.0 + registry.COOLDOWN_SECONDS + 1)["selected"] == "bob"


def test_usd_ceiling_excludes_providers_that_cannot_enforce_it(repo: Path) -> None:
    prof = _profiles("codex", "agy")
    r = registry.route(repo, run_authorized=True, max_cost_usd=1.0, profiles=prof)
    assert r["outcome"] == "NO_AGENT"
    assert any("USD ceiling" in reason for c in r["considered"] for reason in c["reasons"])
    assert registry.route(repo, run_authorized=True, max_cost_usd=1.0, profiles=_profiles("bob"))["selected"] == "bob"


def test_absent_sandbox_means_not_ready(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_isolated_ready", lambda provider: provider != "agy")
    r = registry.route(repo, run_authorized=True, profiles=_profiles("agy"))
    assert r["outcome"] == "NO_AGENT"
    assert any("isolation" in x for c in r["considered"] for x in c["reasons"])


def test_corrupt_or_foreign_policy_is_treated_as_absent(repo: Path) -> None:
    path = registry.policy_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "other", "authorized": ["bob"]}')
    assert registry.load_policy(repo)["authorized"] == []
    path.write_text("not json")
    assert registry.route(repo, profiles=_profiles("bob"))["outcome"] == "NOT_AUTHORIZED"


def test_unknown_provider_names_are_rejected_and_ignored(repo: Path) -> None:
    with pytest.raises(ValueError):
        registry.authorize(repo, "evil")
    path = registry.policy_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "repo-ai.provider-policy/1", "authorized": ["evil", "bob"], "preferred": [], "cooldown": {"evil": 1}}')
    assert registry.load_policy(repo)["authorized"] == ["bob"]


def test_routing_never_reports_unevaluated_readiness_as_proven(repo: Path) -> None:
    r = registry.route(repo, run_authorized=True, profiles=_profiles("agy"))
    assert {"authenticated", "protocol_validated", "edit_proven"} <= set(r["not_evaluated"])


# ---- explicit readiness states, cached observations, and the "never billable" guarantee -------------------------
import sys  # noqa: E402


def _row(r: dict, name: str) -> dict:
    return next(c for c in r["considered"] if c["provider"] == name)


def _prof(*installed: str, identity: str = "id1") -> list[dict]:
    out = _profiles(*installed)
    for p in out:
        if p["provider"] in installed:
            p["identity_sha256"] = identity
    return out


def test_readiness_matrix_zero_one_many(repo: Path) -> None:
    none = registry.route(repo, run_authorized=True, profiles=_profiles())
    assert {c["readiness"] for c in none["considered"]} == {"NOT_INSTALLED"}
    one = registry.route(repo, profiles=_prof("bob"))
    assert _row(one, "bob")["readiness"] == "AVAILABLE_BUT_UNAUTHORIZED" and one["outcome"] == "NOT_AUTHORIZED"
    many = registry.route(repo, run_authorized=True, profiles=_prof("bob", "codex", "agy"))
    assert {_row(many, n)["readiness"] for n in ("bob", "codex", "agy")} == {"INSTALLED_UNPROBED"}
    assert _row(many, "claude")["readiness"] == "NOT_INSTALLED"


def test_agy_outside_macos_is_runtime_unsupported(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_isolated_ready", lambda provider: provider != "agy")
    monkeypatch.setattr(sys, "platform", "linux")
    r = registry.route(repo, run_authorized=True, profiles=_prof("agy", "codex"))
    assert _row(r, "agy")["readiness"] == "RUNTIME_UNSUPPORTED" and not _row(r, "agy")["eligible"]
    assert r["selected"] == "codex"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _row(registry.route(repo, run_authorized=True, profiles=_prof("agy")), "agy")["readiness"] == "ISOLATION_BLOCKED"


def test_untrusted_executable_is_isolation_blocked(repo: Path) -> None:
    prof = _profiles()
    prof[0].update(stage="BLOCKED", status="UNTRUSTED_EXECUTABLE")
    r = registry.route(repo, run_authorized=True, profiles=prof)
    assert _row(r, prof[0]["provider"])["readiness"] == "ISOLATION_BLOCKED"
    assert r["selected"] is None


def test_observed_states_block_selection_until_they_expire(repo: Path) -> None:
    for state, expected in (("USAGE_LIMITED", "USAGE_LIMITED"), ("ACCOUNT_INELIGIBLE", "ACCOUNT_INELIGIBLE"),
                            ("AUTHORIZED_BUT_UNREADY", "AUTHORIZED_BUT_UNREADY")):
        registry.note_observation(repo, "bob", state, "id1", now=1000.0)
        blocked = registry.route(repo, run_authorized=True, profiles=_prof("bob", "codex"), now=1100.0)
        assert _row(blocked, "bob")["readiness"] == expected and blocked["selected"] == "codex", state
        later = registry.route(repo, run_authorized=True, profiles=_prof("bob", "codex"), now=1000.0 + 10 ** 6)
        assert _row(later, "bob")["readiness"] == "INSTALLED_UNPROBED" and later["selected"] == "bob", state


def test_ready_observation_is_bound_to_the_binary_and_expires(repo: Path) -> None:
    registry.note_observation(repo, "codex", "READY", "id1", now=1000.0)
    ok = registry.route(repo, run_authorized=True, profiles=_prof("codex", identity="id1"), now=1100.0)
    assert _row(ok, "codex")["readiness"] == "READY"
    swapped = registry.route(repo, run_authorized=True, profiles=_prof("codex", identity="OTHER"), now=1100.0)
    assert _row(swapped, "codex")["readiness"] == "INSTALLED_UNPROBED", "a changed binary discards the observation"
    stale = registry.route(repo, run_authorized=True, profiles=_prof("codex", identity="id1"), now=1000.0 + 10 ** 6)
    assert _row(stale, "codex")["readiness"] == "INSTALLED_UNPROBED"


def test_ready_is_never_claimed_without_an_observation(repo: Path) -> None:
    r = registry.route(repo, run_authorized=True, profiles=_prof("bob", "codex", "agy", "claude"))
    assert all(c["readiness"] != "READY" for c in r["considered"])


def test_unknown_usd_provider_is_excluded_by_a_ceiling_not_treated_as_free(repo: Path) -> None:
    r = registry.route(repo, run_authorized=True, max_cost_usd=0.5, profiles=_prof("codex", "agy"))
    assert r["selected"] is None
    assert all("UNKNOWN" in c["cost_semantics"] for c in r["considered"] if c["provider"] in {"codex", "agy"})


def test_forged_observations_are_ignored(repo: Path) -> None:
    path = registry.policy_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "repo-ai.provider-policy/1", "authorized": [], "preferred": [], "cooldown": {}, '
                    '"observations": {"bob": {"state": "READY", "until": "never", "identity": "id1"}, '
                    '"evil": {"state": "READY", "until": 9e18, "identity": "x"}, '
                    '"codex": {"state": "PWNED", "until": 9e18, "identity": "id1"}, "agy": 5}}')
    assert registry.load_policy(repo)["observations"] == {}


def test_classify_failure_maps_only_account_facts() -> None:
    assert registry.classify_failure(["weekly usage limit reached"]) == "USAGE_LIMITED"
    assert registry.classify_failure(["IneligibleTierError: account"]) == "ACCOUNT_INELIGIBLE"
    assert registry.classify_failure(["Not logged in"]) == "AUTHORIZED_BUT_UNREADY"
    assert registry.classify_failure(["candidate edited a frozen test"]) is None


def test_route_list_doctor_and_dry_run_never_start_a_process(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No billable (or any) subprocess may be spawned by routing, `agents list/route`, or `do --tournament` without --run."""
    import subprocess as sp

    from repo_ai.providers import discovery
    spawned: list = []
    real_popen = sp.Popen

    def guard(*a, **k):
        argv = a[0] if a else k.get("args")
        first = str(argv[0] if isinstance(argv, (list, tuple)) and argv else argv)
        if any(n in first for n in ("codex", "agy", "bob", "claude")):
            spawned.append(first)
            raise AssertionError("provider process spawned: " + first)
        return real_popen(*a, **k)

    monkeypatch.setattr(sp, "Popen", guard)
    monkeypatch.setattr(discovery.subprocess, "Popen", guard)
    registry.route(repo, run_authorized=True)
    discovery.discover(repo, probe=False)
    from repo_ai.mission import live_tournament
    live_tournament._readiness(repo, ["codex", "agy"], 0.0)
    assert spawned == []


def test_mission_cache_observation_records_state_and_never_raises(repo: Path) -> None:
    from repo_ai.mission import runtime
    runtime._cache_observation(repo, "bob", "id1", {"reasons": ["provider reported weekly usage limit reached"]})
    runtime._cache_observation(repo, "codex", "id2", {"reasons": [], "capture_status": "complete"})
    runtime._cache_observation(repo, "agy", "id3", {"reasons": [], "capture_status": "partial"})  # no claim
    r = registry.route(repo, run_authorized=True, profiles=_prof("bob", "codex", "agy"))
    assert _row(r, "bob")["readiness"] == "USAGE_LIMITED"
    assert _row(r, "agy")["readiness"] == "INSTALLED_UNPROBED"
    runtime._cache_observation(repo / "missing" / "dir", "bob", "x", {"reasons": ["usage limit"]})  # must not raise


# ---- stable coarse status classes (additive; `readiness` remains authoritative) -------------------------------------
def test_every_readiness_state_has_a_status_class_and_no_host_ready_is_invented() -> None:
    assert set(registry.READINESS_STATES) <= set(registry.STATUS_CLASS)
    assert "HOST_READY" not in registry.STATUS_CLASS.values()
    assert registry.STATUS_CLASS["READY"] == registry.STATUS_CLASS["INSTALLED_UNPROBED"] == "ISOLATED_READY"


def test_status_class_distinguishes_auth_quota_sandbox_and_unsupported(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry.note_observation(repo, "bob", "USAGE_LIMITED", "id1", now=1000.0)
    registry.note_observation(repo, "codex", "AUTHORIZED_BUT_UNREADY", "id1", now=1000.0)
    r = registry.route(repo, run_authorized=True, profiles=_prof("bob", "codex", "agy"), now=1100.0)
    assert _row(r, "bob")["status_class"] == "BLOCKED_QUOTA"
    assert _row(r, "codex")["status_class"] == "BLOCKED_AUTH"
    assert _row(r, "agy")["status_class"] == "ISOLATED_READY"
    assert _row(r, "claude")["status_class"] == "NOT_INSTALLED"
    assert registry.route(repo, profiles=_prof("bob"))["considered"][0]["status_class"] in {"NOT_AUTHORIZED", "ISOLATED_READY"}
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(registry, "_isolated_ready", lambda provider: provider != "agy")
    assert _row(registry.route(repo, run_authorized=True, profiles=_prof("agy")), "agy")["status_class"] == "UNSUPPORTED"


def test_expired_or_swapped_observation_is_flagged_stale_not_trusted(repo: Path) -> None:
    registry.note_observation(repo, "codex", "READY", "id1", now=1000.0)
    fresh = _row(registry.route(repo, run_authorized=True, profiles=_prof("codex"), now=1100.0), "codex")
    assert fresh["auth_observed"] is True and fresh["observation_stale"] is False
    old = _row(registry.route(repo, run_authorized=True, profiles=_prof("codex"), now=1000.0 + 10 ** 6), "codex")
    assert old["auth_observed"] is False and old["observation_stale"] is True
    swapped = _row(registry.route(repo, run_authorized=True, profiles=_prof("codex", identity="OTHER"), now=1100.0), "codex")
    assert swapped["auth_observed"] is False and swapped["observation_stale"] is True


def test_zero_providers_never_selects_a_phantom_first_choice(repo: Path) -> None:
    r = registry.route(repo, run_authorized=True, profiles=_profiles(), preferred=["bob"])
    assert r["outcome"] == "NO_AGENT" and r["selected"] is None
    assert not any(c["eligible"] for c in r["considered"])


def test_claude_without_a_usable_login_is_setup_required_not_selected(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                                                      tmp_path: Path) -> None:
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("REPO_AI_CLAUDE_CONFIG_DIR", str(tmp_path / "no-login"))
    r = registry.route(repo, run_authorized=True, profiles=_profiles("claude", "codex"))
    row = next(c for c in r["considered"] if c["provider"] == "claude")
    if not row["isolated_ready"]:
        pytest.skip("no execution sandbox on this host")
    assert row["readiness"] == "SETUP_REQUIRED" and row["status_class"] == "BLOCKED_AUTH"
    assert any("claude auth login" in reason for reason in row["reasons"])
    assert r["selected"] == "codex"


def test_claude_with_a_token_or_dedicated_login_is_selectable(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    r = registry.route(repo, run_authorized=True, profiles=_profiles("claude"))
    row = r["considered"][0] if r["considered"][0]["provider"] == "claude" else \
        next(c for c in r["considered"] if c["provider"] == "claude")
    if not row["isolated_ready"]:
        pytest.skip("no execution sandbox on this host")
    assert row["readiness"] == "INSTALLED_UNPROBED" and r["selected"] == "claude"
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    (tmp_path / "login").mkdir()
    monkeypatch.setenv("REPO_AI_CLAUDE_CONFIG_DIR", str(tmp_path / "login"))
    monkeypatch.setenv("USER", "someone")
    assert registry.route(repo, run_authorized=True, profiles=_profiles("claude"))["selected"] == "claude"
