"""Release review of 0.12.0: the failed-mission hint and a cooldown time too large for a float."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from repo_ai.mission import cli as mcli
from repo_ai.providers import registry


@pytest.mark.parametrize("provider,target", [
    ({"cost_status": "UNKNOWN", "simulated": False}, "--to codex"),
    ({"cost_status": "OBSERVED", "simulated": False}, "--to claude"),
    ({"simulated": True}, "--to claude"),
])
def test_the_failed_mission_hint_never_suggests_a_continuation_that_would_be_refused(capsys, provider, target):
    mcli._emit({"id": "abc123", "state": "INCONCLUSIVE", "effective_verdict": "BLOCKED", "provider": provider},
               SimpleNamespace(json=False))
    assert target in capsys.readouterr().out


def test_a_cooldown_time_too_large_for_a_float_is_ignored(tmp_path):
    path = registry.policy_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": "%s", "cooldown": {"claude": %s}}' % (registry.POLICY_SCHEMA, "9" * 400))
    assert registry.load_policy(tmp_path)["cooldown"] == {}
    path.write_text(json.dumps({"schema": registry.POLICY_SCHEMA, "cooldown": {"claude": 1.0}}))
    assert registry.load_policy(tmp_path)["cooldown"] == {"claude": 1.0}
