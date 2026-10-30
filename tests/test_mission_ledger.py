import json
import pytest
from repo_ai.mission.ledger import Store, transition


def test_hash_checked_atomic_state_and_root_binding(tmp_path):
    store = Store(tmp_path)
    state = {'id': 'a' * 24, 'state': 'CREATED', 'repository': store.repository, 'events': []}
    store.save(state)
    assert store.load(state['id'])['state'] == 'CREATED'
    raw = json.loads(store.path(state['id']).read_text())
    raw['record']['state'] = 'COMPLETE'
    store.path(state['id']).write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='integrity'):
        store.load(state['id'])


def test_invalid_ids_symlinks_and_unowned_data(tmp_path):
    store = Store(tmp_path)
    for value in ['../escape', '/tmp/x', 'z' * 24]:
        with pytest.raises(ValueError):
            store.path(value)
    store.folder.mkdir(parents=True)
    (store.folder / ('a' * 24 + '.json')).symlink_to(tmp_path / 'victim')
    with pytest.raises(ValueError):
        store.save({'id': 'a' * 24, 'repository': store.repository, 'state': 'CREATED', 'events': []})
    assert not (tmp_path / 'victim').exists()


def test_complete_requires_evidence_and_valid_transition():
    s = {'state': 'CREATED', 'events': []}
    with pytest.raises(ValueError):
        transition(s, 'COMPLETE')
    transition(s, 'PLANNED')
    transition(s, 'READY')
    transition(s, 'RUNNING')
    transition(s, 'VERIFYING')
    transition(s, 'REVIEWING')
    with pytest.raises(ValueError):
        transition(s, 'COMPLETE')
    s['passport'] = {'verdict': 'PASS', 'observations': ['baseline', 'candidate', 'regression']}
    transition(s, 'COMPLETE')
    assert s['state'] == 'COMPLETE'
