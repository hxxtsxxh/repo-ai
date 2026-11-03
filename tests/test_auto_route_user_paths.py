"""Queue row 28 through the user paths (plan and `do` with --agent auto, an explicit ceiling provider, a mixed
tournament's readiness without injected executables). Discovery is stubbed; no provider process starts."""
from __future__ import annotations

import pytest

from repo_ai.providers import registry


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    (tmp_path / "fakehome").mkdir(exist_ok=True)


@pytest.fixture
def two_installed(monkeypatch):
    from repo_ai.providers.discovery import PROVIDERS
    installed = {"claude", "codex"}
    monkeypatch.setattr(registry, "discover", lambda root, probe=False: [
        {"provider": p, "stage": "DISCOVERED" if p in installed else "NOT_INSTALLED",
         "status": "DISCOVERED" if p in installed else "NOT_INSTALLED", "identity_sha256": "id-" + p}
        for p in PROVIDERS])
    monkeypatch.setattr(registry, "_isolated_ready", lambda name: True)
    monkeypatch.setattr(registry, "setup_problems", lambda name: [])
    return installed


@pytest.fixture
def bug(tmp_path):
    from test_mission_runtime import bug as bug_fixture
    return bug_fixture.__wrapped__(tmp_path)


def test_plan_auto_runs_codex_at_zero_and_claude_with_a_ceiling(bug, two_installed):
    from repo_ai.mission import runtime
    free = runtime.plan(bug, "Fix charge", agent="auto", write_paths=["charge.py"], execute_local=True, allow_live=True)
    assert free["contract"]["provider"] == "codex"
    capped = runtime.plan(bug, "Fix charge with a cap", agent="auto", write_paths=["charge.py"], execute_local=True,
                          allow_live=True, max_cost_usd=0.5)
    assert capped["contract"]["provider"] == "claude"


def test_mixed_tournament_readiness_judges_each_arm_at_its_own_ceiling(bug, two_installed):
    """0.12.0's `codex,claude --max-cost-usd X --allow-unknown-cost`: Claude at its share, Codex at 0 (UNKNOWN)."""
    from repo_ai.mission import live_tournament as lt
    tplan = lt.plan_tournament(bug, "Fix charge", ["codex", "claude"], write_paths=["charge.py"], max_cost_usd=1.5,
                               allow_unknown_cost=True)
    assert tplan["readiness"]["claude"]["eligible"] and tplan["readiness"]["codex"]["eligible"]
    assert tplan["bounds"]["per_arm_cost_usd_by_provider"] == {"codex": 0.0, "claude": 1.5}


def test_do_auto_with_only_a_ceiling_provider_says_how(bug, monkeypatch):
    from repo_ai.cli import build_parser
    from repo_ai.mission import runtime
    from repo_ai.providers.discovery import PROVIDERS
    monkeypatch.setattr(registry, "discover", lambda root, probe=False: [
        {"provider": p, "stage": "DISCOVERED" if p == "claude" else "NOT_INSTALLED",
         "status": "DISCOVERED" if p == "claude" else "NOT_INSTALLED", "identity_sha256": "id-" + p} for p in PROVIDERS])
    monkeypatch.setattr(registry, "_isolated_ready", lambda name: True)
    monkeypatch.setattr(registry, "setup_problems", lambda name: [])
    monkeypatch.setattr(runtime, "execute", lambda *a, **k: pytest.fail("no provider may start"))
    args = build_parser().parse_args(["do", "Fix charge", "-C", str(bug), "--agent", "auto", "--allow-live-provider",
                                      "--run", "--allow-write", "charge.py"])
    with pytest.raises(ValueError, match=r"no provider can run this mission \(NO_AGENT\).*--max-cost-usd"):
        args.func(args)


def test_an_explicit_ceiling_provider_without_one_names_the_alternative(bug, two_installed, monkeypatch):
    from repo_ai.cli import build_parser
    from repo_ai.mission import runtime
    monkeypatch.setattr(runtime, "execute", lambda *a, **k: pytest.fail("no provider may start"))
    args = build_parser().parse_args(["do", "Fix charge", "-C", str(bug), "--agent", "claude", "--allow-live-provider",
                                      "--run", "--allow-write", "charge.py"])
    with pytest.raises(ValueError, match=r"enforces a USD ceiling.*--agent codex"):
        args.func(args)


def test_a_tournament_share_under_the_flag_precision_names_the_total_needed(bug, two_installed):
    from repo_ai.mission import live_tournament as lt
    with pytest.raises(ValueError, match=r"give at least 0\.0002"):
        lt.plan_tournament(bug, "Fix charge", ["claude", "bob"], write_paths=["charge.py"], max_cost_usd=0.0001)


def test_the_explicit_agent_refusal_survives_a_failing_route(bug, monkeypatch):
    from repo_ai.mission import cli as mcli
    monkeypatch.setattr(registry, "route", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(ValueError, match="enforces a USD ceiling"):
        mcli._require_ceiling("claude", 0, None, bug)


def test_auto_routing_says_which_ceiling_provider_it_skipped(monkeypatch, tmp_path):
    from repo_ai.providers import registry as reg
    from repo_ai.providers.discovery import PROVIDERS
    policy = {"exists": True, "preferred": [], "authorized": [], "cooldown": {}, "observations": {}}
    monkeypatch.setattr(reg, "load_policy", lambda root: policy)
    monkeypatch.setattr(reg, "_isolated_ready", lambda name: True)
    monkeypatch.setattr(reg, "setup_problems", lambda name: [])
    profiles = [{"provider": p, "stage": "DISCOVERED" if p in ("claude", "codex") else "NOT_INSTALLED",
                 "status": "DISCOVERED", "identity_sha256": "id-" + p} for p in PROVIDERS]
    d = reg.route(tmp_path, run_authorized=True, profiles=profiles)
    assert d["selected"] == "codex"
    assert "skipped claude" in d["why"] and "--max-cost-usd" in d["why"] and "cost is UNKNOWN" in d["why"]
    capped = reg.route(tmp_path, run_authorized=True, max_cost_usd=0.5, profiles=profiles)
    assert capped["selected"] == "claude" and "skipped" not in capped["why"]


def test_a_skipped_unauthorized_ceiling_provider_is_named_with_both_blockers(monkeypatch, tmp_path):
    from repo_ai.providers import registry as reg
    from repo_ai.providers.discovery import PROVIDERS
    policy = {"exists": True, "preferred": [], "authorized": ["codex"], "cooldown": {}, "observations": {}}
    monkeypatch.setattr(reg, "load_policy", lambda root: policy)
    monkeypatch.setattr(reg, "_isolated_ready", lambda name: True)
    monkeypatch.setattr(reg, "setup_problems", lambda name: [])
    profiles = [{"provider": p, "stage": "DISCOVERED" if p in ("claude", "codex") else "NOT_INSTALLED",
                 "status": "DISCOVERED", "identity_sha256": "id-" + p} for p in PROVIDERS]
    d = reg.route(tmp_path, run_authorized=True, profiles=profiles)
    assert d["selected"] == "codex" and "claude (also not authorized)" in d["why"] and "authorize it" in d["why"]


def test_do_auto_prints_what_it_skipped_before_starting(bug, two_installed, monkeypatch, capsys):
    from repo_ai.cli import build_parser
    from repo_ai.mission import runtime
    monkeypatch.setattr(runtime, "execute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop before start")))
    args = build_parser().parse_args(["do", "Fix charge", "-C", str(bug), "--agent", "auto", "--allow-live-provider",
                                      "--run", "--allow-write", "charge.py", "--json"])
    with pytest.raises(RuntimeError, match="stop before start"):
        args.func(args)
    err = capsys.readouterr().err
    assert "repo-ai: routed to codex" in err and "skipped claude" in err
