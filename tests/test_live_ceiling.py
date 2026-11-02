"""A provider whose CLI enforces a USD ceiling is never started without one (the default 0 authorises no spend), and
a tournament can cap those arms while running the others with cost UNKNOWN. No provider process starts here."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_ai.mission import cli as mcli
from repo_ai.mission import live_tournament as lt
from repo_ai.mission import runtime
from test_live_tournament import GOOD, TASK, fake
from test_mission_runtime import bug as bug_fixture


@pytest.fixture
def bug(tmp_path: Path) -> Path:
    return bug_fixture.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'fakehome'))
    (tmp_path / 'fakehome').mkdir(exist_ok=True)


def test_require_ceiling():
    with pytest.raises(ValueError, match='enforces a USD ceiling'):
        mcli._require_ceiling('claude', 0)
    mcli._require_ceiling('claude', 0.5)
    mcli._require_ceiling('codex', 0)  # cannot enforce one: its cost is UNKNOWN, as before


def test_do_refuses_a_capped_provider_without_a_ceiling_before_it_starts(bug, monkeypatch, capsys):
    monkeypatch.setattr(runtime, 'execute', lambda *a, **k: pytest.fail('no provider may start'))
    from repo_ai.cli import build_parser
    args = build_parser().parse_args(['do', 'Fix charge', '-C', str(bug), '--agent', 'claude', '--allow-live-provider',
                                      '--run', '--allow-write', 'charge.py'])
    with pytest.raises(ValueError, match='enforces a USD ceiling'):
        args.func(args)


def test_a_tournament_with_a_capped_provider_needs_a_ceiling(bug):
    with pytest.raises(ValueError, match='claude enforces a USD ceiling'):
        lt.plan_tournament(bug, TASK, ['claude', 'codex'], write_paths=['charge.py'])


def test_mixed_tournament_caps_only_the_providers_that_enforce_it(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex', {'charge.py': GOOD},
                                                                                    cost=None)}
    with pytest.raises(ValueError, match='--allow-unknown-cost'):
        lt.plan_tournament(bug, TASK, list(exes), write_paths=['charge.py'], max_cost_usd=1.0, executables=exes)
    tplan = lt.plan_tournament(bug, TASK, list(exes), write_paths=['charge.py'], max_cost_usd=1.0, executables=exes,
                               allow_unknown_cost=True)
    assert tplan['bounds']['per_arm_cost_usd_by_provider'] == {'claude': 1.0, 'codex': 0.0}
    assert 'UNKNOWN for codex' in tplan['bounds']['cost_semantics']
    by = {a['provider']: a['plan']['contract']['max_cost_usd'] for a in tplan['arms']}
    assert by == {'claude': 1.0, 'codex': 0.0}
    report = lt.run_tournament(bug, TASK, list(exes), write_paths=['charge.py'], max_seconds=240, max_cost_usd=1.0,
                               executables=exes, allow_unknown_cost=True)
    assert 'codex' in report['cost_unknown_for'] and json.dumps(report)  # the stand-ins' cost fields differ


@pytest.mark.usefixtures('claude_fake_login')
def test_a_continuation_to_a_capped_provider_without_budget_is_refused_before_the_claim(tmp_path, monkeypatch):
    from repo_ai.mission.ledger import Store
    from test_mission_partial_handoff import FIX_DISCOUNT, _provider
    from test_mission_partial_handoff import shop as shop_fixture
    shop = shop_fixture.__wrapped__(tmp_path)
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True)
    first = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, 'claude', FIX_DISCOUNT))
    capsule = tmp_path / 'capsule.json'
    capsule.write_text(json.dumps(runtime.handoff(shop, first['id'], target_provider='claude')))
    monkeypatch.setattr('repo_ai.providers.adapters.run_provider', lambda *a, **k: pytest.fail('no provider may start'))
    with pytest.raises(ValueError, match='capsule is still unused'):
        runtime.continue_from_handoff(shop, capsule, agent='claude', allow_live=True, max_cost_usd=None)
    assert not Store(shop).load(first['id']).get('continuation_started')
