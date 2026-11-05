"""Primary follow-up to independent review: local capsules retain zone authority."""
import pytest

from repo_ai import registry
from repo_ai.mission import runtime
from repo_ai.mission.ledger import Store
from test_mission_runtime import bug as bug_fixture, replay


@pytest.fixture
def bug(tmp_path, monkeypatch):
    monkeypatch.setenv('REPO_AI_HOME', str(tmp_path / 'registry'))
    return bug_fixture.__wrapped__(tmp_path)


def recorded(root):
    planned = runtime.plan(root, 'repair charge.py', agent='replay', execute_local=True,
                           write_paths=['charge.py'])
    store = Store(root)
    state = {'id': 'a' * 24, 'repository': store.repository, 'state': 'INCONCLUSIVE',
             'events': [], 'contract': planned['contract'], 'source': planned['source'],
             'kernel': planned['kernel']}
    store.save(state)
    return planned, state['id']


def test_capsule_retains_registered_zone_and_policy(bug):
    registry.add(bug, 'work')
    planned, mission = recorded(bug)
    assert planned['contract']['zone'] == 'work'
    assert len(planned['contract']['policy_sha256']) == 64
    assert runtime.handoff(bug, mission)['zone'] == 'work'


def test_moved_zone_blocks_trace_handoff_and_old_execution(bug, tmp_path):
    registry.add(bug, 'work')
    planned, mission = recorded(bug)
    artifact = replay(bug, tmp_path)
    registry.add(bug, 'personal', move=True)
    for call in (lambda: runtime.status(bug, mission), lambda: runtime.handoff(bug, mission),
                 lambda: runtime.execute(bug, planned, artifact)):
        with pytest.raises(ValueError, match='zone|policy'):
            call()


def test_policy_change_invalidates_evidence_and_blocks_capsule(bug):
    registry.add(bug, 'work')
    _, mission = recorded(bug)
    old = registry.policy_for(bug)[1]['patterns']
    registry.set_policy('work', 'patterns', 'off' if old == 'on' else 'on')
    assert runtime.status(bug, mission)['freshness'] == 'stale'
    with pytest.raises(ValueError, match='policy'):
        runtime.handoff(bug, mission)


def test_unregistered_planning_does_not_create_registry(bug, monkeypatch):
    from pathlib import Path
    planned = runtime.plan(bug, 'inspect', agent='none')
    assert planned['contract']['zone'] == 'local'
    assert planned['contract']['policy_sha256']
    assert not Path(registry.registry_home()).exists()
