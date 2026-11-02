"""Findings of routing-journey-v1's pilot (benchmarks/routing-journey-v1): an explicitly chosen provider that is
cooling down after a rate limit is refused before it starts, and a crashed provider is not classified as a budget
limit because its cost is unknown. Offline; no provider process starts."""
from __future__ import annotations

import sys

import pytest

from repo_ai.mission import runtime
from repo_ai.providers import registry
from test_mission_partial_handoff import shop  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures('claude_fake_login')


def test_an_explicit_provider_that_is_cooling_down_is_refused_before_it_starts(shop, monkeypatch):  # noqa: F811
    started = []
    monkeypatch.setattr('repo_ai.providers.adapters.run_provider', lambda *a, **k: started.append(a) or {})
    planned = runtime.plan(shop, 'Fix pricing', agent='claude', write_paths=['pricing.py'], execute_local=True,
                           allow_live=True, max_cost_usd=0.5)
    registry.note_rate_limited(shop, 'claude')
    with pytest.raises(ValueError, match='cooling down until'):
        runtime.execute(shop, planned, None, allow_live=True)
    assert not started


def test_a_cooldown_that_has_passed_does_not_refuse(shop, tmp_path, monkeypatch):  # noqa: F811
    """run_provider is stubbed: no provider process (and never a real CLI) starts in this test."""
    import time
    started = []

    def stub(*a, **k):
        started.append(True)
        raise ValueError('stub provider: stop here')
    monkeypatch.setattr('repo_ai.providers.adapters.run_provider', stub)
    exe = tmp_path / 'bin' / 'claude'  # never run: run_provider is stubbed
    exe.parent.mkdir()
    exe.write_text('#!/bin/sh\nexit 0\n')
    exe.chmod(0o755)
    monkeypatch.setattr('repo_ai.mission.runtime.shutil.which', lambda name, *a, **k: str(exe))
    registry.note_rate_limited(shop, 'claude', now=time.time() - registry.COOLDOWN_SECONDS - 1)
    planned = runtime.plan(shop, 'Fix pricing', agent='claude', write_paths=['pricing.py'], execute_local=True,
                           allow_live=True, max_cost_usd=0.5)
    try:
        runtime.execute(shop, planned, None, allow_live=True)
    except Exception as exc:  # noqa: BLE001 - whatever stops the run, it is past the cooldown check
        assert 'cooling down' not in str(exc)
        stopped = str(exc)
    else:
        stopped = ''
    assert started, f'the run stopped before reaching the provider: {stopped}'


def test_a_malformed_cooldown_is_ignored(shop):  # noqa: F811
    import json
    path = registry.policy_path(shop)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "%s", "cooldown": {"claude": Infinity}}' % registry.POLICY_SCHEMA)
    assert registry.load_policy(shop)['cooldown'] == {}
    assert runtime.cooldown_until(shop, 'claude') is None
    path.write_text(json.dumps({"schema": registry.POLICY_SCHEMA, "cooldown": {"claude": 1e300}}))
    assert 'unreadable' in runtime.cooldown_until(shop, 'claude')


@pytest.mark.skipif(sys.platform == 'win32', reason='missions are refused on Windows (no host sandbox)')
def test_a_continuation_to_a_cooling_provider_is_refused_and_the_capsule_stays_usable(shop, tmp_path,  # noqa: F811
                                                                                       monkeypatch):
    import json

    from repo_ai.mission.ledger import Store
    from test_mission_partial_handoff import FIX_DISCOUNT, _provider
    monkeypatch.setattr('repo_ai.providers.adapters.run_provider',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('no provider may start')))
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True)
    monkeypatch.undo()
    first = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, 'claude', FIX_DISCOUNT))
    capsule = tmp_path / 'capsule.json'
    capsule.write_text(json.dumps(runtime.handoff(shop, first['id'], target_provider='claude')))
    registry.note_rate_limited(shop, 'claude')
    monkeypatch.setattr('repo_ai.providers.adapters.run_provider',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('no provider may start')))
    with pytest.raises(ValueError, match='capsule is still unused'):
        runtime.continue_from_handoff(shop, capsule, agent='claude', allow_live=True, max_cost_usd=0.5)
    assert not Store(shop).load(first['id']).get('continuation_started')


def _state(negative: str) -> dict:
    return {'state': 'INCONCLUSIVE', 'effective_verdict': 'BLOCKED', 'passport': {'negative': [negative]},
            'nodes': {'edit': {'status': 'FAILED'}}, 'cleanup_confirmed': True, 'provider': {'stage': 'BLOCKED'}}


def test_a_crashed_provider_is_not_a_budget_limit():
    crash = ('live session: no init event; provider process exited with code 139; provider output did not conform to '
             'structured JSONL event contract; provider did not report cost; unknown cost cannot satisfy hard USD budget')
    assert runtime.classify_recovery(_state(crash))['category'] != 'budget_limit'


def test_a_cost_overrun_is_a_budget_limit_even_when_the_provider_exits_non_zero():
    overrun = ('provider process exited with code 1; provider error event: budget exceeded; provider reported cost '
               'exceeding approved contract ceiling')
    assert runtime.classify_recovery(_state(overrun))['category'] == 'budget_limit'


def test_a_genuine_cost_overrun_is_still_a_budget_limit():
    assert runtime.classify_recovery(_state('provider reported cost exceeding approved contract ceiling'))[
        'category'] == 'budget_limit'
    assert runtime.classify_recovery(_state('provider did not report cost; unknown cost cannot satisfy hard USD '
                                            'budget'))['category'] == 'budget_limit'
