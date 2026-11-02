"""Findings of routing-journey-v1's pilot (benchmarks/routing-journey-v1): an explicitly chosen provider that is
cooling down after a rate limit is refused before it starts, and a crashed provider is not classified as a budget
limit because its cost is unknown. Offline; no provider process starts."""
from __future__ import annotations

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


def test_a_cooldown_that_has_passed_does_not_refuse(shop):  # noqa: F811
    import time
    registry.note_rate_limited(shop, 'claude', now=time.time() - registry.COOLDOWN_SECONDS - 1)
    planned = runtime.plan(shop, 'Fix pricing', agent='claude', write_paths=['pricing.py'], execute_local=True,
                           allow_live=True, max_cost_usd=0.5)
    try:
        runtime.execute(shop, planned, None, allow_live=True)
    except ValueError as exc:
        assert 'cooling down' not in str(exc)
    except Exception:  # noqa: BLE001 - anything else past the cooldown check is not this test's concern
        pass


def _state(negative: str) -> dict:
    return {'state': 'INCONCLUSIVE', 'effective_verdict': 'BLOCKED', 'passport': {'negative': [negative]},
            'nodes': {'edit': {'status': 'FAILED'}}, 'cleanup_confirmed': True, 'provider': {'stage': 'BLOCKED'}}


def test_a_crashed_provider_is_not_a_budget_limit():
    crash = ('live session: no init event; provider process exited with code 139; provider output did not conform to '
             'structured JSONL event contract; provider did not report cost; unknown cost cannot satisfy hard USD budget')
    assert runtime.classify_recovery(_state(crash))['category'] != 'budget_limit'


def test_a_genuine_cost_overrun_is_still_a_budget_limit():
    assert runtime.classify_recovery(_state('provider reported cost exceeding approved contract ceiling'))[
        'category'] == 'budget_limit'
    assert runtime.classify_recovery(_state('provider did not report cost; unknown cost cannot satisfy hard USD '
                                            'budget'))['category'] == 'budget_limit'
