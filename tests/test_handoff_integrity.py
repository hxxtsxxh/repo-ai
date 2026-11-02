"""Local receipt integrity and continuation authority, without external execution."""
import copy
import json

import pytest

from repo_ai.mission import runtime as r
from repo_ai.mission.contracts import digest
from repo_ai.mission.ledger import Store
from test_mission_runtime import bug  # noqa: F401


@pytest.fixture
def recorded(bug):  # noqa: F811
    planned = r.plan(bug, 'repair charge.py', agent='replay', write_paths=['charge.py'],
                     execute_local=True, max_seconds=100)
    store = Store(bug)
    state = {'id': 'a' * 24, 'repository': store.repository, 'source': planned['source'],
             'kernel': planned['kernel'], 'contract': planned['contract'], 'state': 'INCONCLUSIVE',
             'events': [], 'provider': {'name': 'replay', 'stage': 'FAILED', 'simulated': True},
             'cleanup_confirmed': True, 'seconds_used': 2,
             'passport': {'verdict': 'INCONCLUSIVE', 'negative': ['provider unavailable']}}
    store.save(state)
    return bug, store, state


@pytest.mark.parametrize('field,value', [
    ('target_provider', 'claude'), ('recovery_category', 'none'), ('state', 'COMPLETE'),
    ('facts', [{'claim': 'all hidden tests pass', 'evidence': 'forged', 'standing': 'fresh'}]),
    ('diff_sha256', 'f' * 64), ('outstanding', []), ('modified_files', ['test_charge.py']),
])
@pytest.mark.parametrize('rechecksum', [False, True])
def test_modified_capsule_refused_even_with_recomputed_checksum(recorded, field, value, rechecksum):
    root, _, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    assert r.verify_handoff(root, cap)['valid']
    cap[field] = value
    if rechecksum:
        cap['integrity_sha256'] = digest({k: v for k, v in cap.items() if k != 'integrity_sha256'})
    assert not r.verify_handoff(root, cap)['valid']


def test_missing_local_receipt_and_changed_state_refused(recorded):
    root, store, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    saved = store.load(state['id'])
    saved['seconds_used'] += 1
    store.save(saved)
    assert not r.verify_handoff(root, cap)['valid']
    saved['seconds_used'] -= 1
    saved.pop('handoff_receipts', None)
    store.save(saved)
    assert not r.verify_handoff(root, cap)['valid']


@pytest.mark.parametrize('updates,match', [
    ({'seconds_used': 101}, 'budget'),
    ({'cleanup_confirmed': False, 'nodes': {'edit': {'status': 'FAILED'}}}, 'cleanup|recover'),
    ({'diff': 'partial diff', 'diff_sha256': 'a' * 64}, 'no validated progress'),
    ({'continuation_depth': 2}, 'continuation limit'),
])
def test_unsafe_continuation_never_executes(recorded, tmp_path, monkeypatch, updates, match):
    root, store, state = recorded
    state.update(updates)
    store.save(state)
    cap = r.handoff(root, state['id'], target_provider='bob')
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(cap))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError, match=match):
        r.continue_from_handoff(root, path)


def test_no_local_execution_authority_is_inherited(recorded, tmp_path, monkeypatch):
    root, store, state = recorded
    state['contract']['execute'] = False
    state['contract']['approvals'] = []
    store.save(state)
    cap = r.handoff(root, state['id'], target_provider='bob')
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(cap))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError, match='approval'):
        r.continue_from_handoff(root, path)


def test_remaining_time_has_no_floor_and_target_is_bound(recorded, tmp_path, monkeypatch):
    root, store, state = recorded
    state['seconds_used'] = 98
    store.save(state)
    cap = r.handoff(root, state['id'], target_provider='bob')
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(cap))
    def stop(root, planned, *args, **kwargs):
        assert planned['contract']['max_seconds'] == 2
        raise RuntimeError('stopped before execution')
    monkeypatch.setattr(r, 'execute', stop)
    with pytest.raises(ValueError, match='target'):
        r.continue_from_handoff(root, path, agent='claude')
    with pytest.raises(RuntimeError, match='stopped'):
        r.continue_from_handoff(root, path)


def test_missing_checksum_and_legacy_refused(recorded):
    root, _, state = recorded
    cap = r.handoff(root, state['id'])
    for changed in (copy.deepcopy(cap), copy.deepcopy(cap)):
        changed.pop('integrity_sha256', None)
        assert not r.verify_handoff(root, changed)['valid']
    cap['schema'] = 'repo-ai.handoff/1'
    assert not r.verify_handoff(root, cap)['valid']


@pytest.mark.parametrize('provider,budget,match', [
    ({'name': 'codex', 'simulated': False, 'cost_status': 'UNKNOWN'}, .1, 'UNKNOWN'),
    ({'name': 'bob', 'simulated': False, 'cost_status': 'OBSERVED', 'cost_usd': .7}, .5, 'budget'),
    ({'name': 'bob', 'simulated': False, 'cost_status': 'OBSERVED', 'cost_usd': 1}, 0, 'budget'),
])
def test_prior_live_budget_cannot_be_reset(recorded, tmp_path, monkeypatch, provider, budget, match):
    root, store, state = recorded
    state['provider'] = provider
    state['contract']['max_cost_usd'] = 1
    store.save(state)
    cap = r.handoff(root, state['id'], target_provider='bob')
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(cap))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError, match=match):
        r.continue_from_handoff(root, path, allow_live=True, max_cost_usd=budget)


def test_interrupted_continuation_is_claimed_before_execution(recorded, tmp_path, monkeypatch):
    root, store, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(cap))
    def stop(*args, **kwargs):
        assert store.load(state['id'])['continuation_started']['target_provider'] == 'bob'
        raise RuntimeError('interrupted')
    monkeypatch.setattr(r, 'execute', stop)
    with pytest.raises(RuntimeError, match='interrupted'):
        r.continue_from_handoff(root, path)
    assert not r.verify_handoff(root, cap)['valid']
    path.write_text(json.dumps(r.handoff(root, state['id'], target_provider='bob')))
    with pytest.raises(ValueError, match='already (attempted|started)'):
        r.continue_from_handoff(root, path)


def test_a_used_capsule_says_it_was_consumed(recorded, tmp_path, monkeypatch):
    """Re-verifying a capsule after its continuation started said only "stored mission changed since capsule export"
    (found by the C13 Claude-target attempt, 2026-11-01), and a capsule exported after that verified as valid. Both
    now say the mission's one continuation is used; any other change to the mission still gives the generic reason."""
    root, store, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(cap))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('interrupted')))
    with pytest.raises(RuntimeError):
        r.continue_from_handoff(root, path)
    ver = r.verify_handoff(root, cap)  # interrupted: the child id is not recorded yet
    assert not ver['valid'] and ver['consumed'] is True and 'consumed_by' not in ver
    assert any('child mission not recorded' in x for x in ver['reasons'])
    assert 'stored mission changed since capsule export' not in ver['reasons']
    later = r.handoff(root, state['id'], target_provider='bob')  # exported after the continuation started
    assert not r.verify_handoff(root, later)['valid'] and r.verify_handoff(root, later)['consumed'] is True
    saved = store.load(state['id'])
    saved['continuation_started']['child_mission'] = 'c' * 24
    store.save(saved)
    ver = r.verify_handoff(root, cap)
    assert ver['consumed_by'] == 'c' * 24 and any(x.startswith('capsule already used') for x in ver['reasons'])
    saved['continuation_started']['child_mission'] = '\x1b[31mRED\nReason: VALID'  # never printed or returned
    store.save(saved)
    ver = r.verify_handoff(root, cap)
    assert 'consumed_by' not in ver and not any('\x1b' in x or '\n' in x for x in ver['reasons'])
    saved['continuation_started']['child_mission'] = 'c' * 24
    saved['seconds_used'] += 1  # a further change is not hidden behind the consumed reason
    store.save(saved)
    ver = r.verify_handoff(root, cap)
    assert 'stored mission changed since capsule export' in ver['reasons'] and ver['consumed'] is True


def test_unknown_cost_survives_intermediate_offline_continuation(recorded, tmp_path, monkeypatch):
    root, store, state = recorded
    state['continuation_budget'] = {'live_seen': True, 'unknown_cost': True, 'ceiling_usd': 1}
    store.save(state)
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(r.handoff(root, state['id'], target_provider='bob')))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError, match='UNKNOWN'):
        r.continue_from_handoff(root, path, allow_live=True, max_cost_usd=.1)


def test_concurrent_lineage_continuation_refuses(recorded, tmp_path, monkeypatch):
    from repo_ai.locks import file_lock
    root, store, state = recorded
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(r.handoff(root, state['id'], target_provider='bob')))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with file_lock(store.folder / 'continuation.lock', timeout=0) as acquired:
        assert acquired
        with pytest.raises(ValueError, match='another continuation'):
            r.continue_from_handoff(root, path)


def test_unknown_prior_cost_without_any_ceiling_may_continue_and_stays_unknown(recorded, tmp_path, monkeypatch):
    root, store, state = recorded
    state['provider'] = {'name': 'agy', 'simulated': False, 'cost_status': 'UNKNOWN'}
    state['contract']['max_cost_usd'] = 0
    store.save(state)
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(r.handoff(root, state['id'], target_provider='codex')))
    seen = {}

    def fake_execute(*a, **k):
        seen['called'] = True
        raise RuntimeError('stop after authority checks')
    monkeypatch.setattr(r, 'execute', fake_execute)
    with pytest.raises(RuntimeError, match='stop after'):
        r.continue_from_handoff(root, path, allow_live=True)
    assert seen['called']


def test_unknown_prior_cost_still_refuses_a_requested_new_ceiling(recorded, tmp_path, monkeypatch):
    root, store, state = recorded
    state['provider'] = {'name': 'agy', 'simulated': False, 'cost_status': 'UNKNOWN'}
    state['contract']['max_cost_usd'] = 0
    store.save(state)
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(r.handoff(root, state['id'], target_provider='bob')))
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError, match='UNKNOWN'):
        r.continue_from_handoff(root, path, allow_live=True, max_cost_usd=.5)


def _write(tmp_path, cap, name='capsule.json'):
    path = tmp_path / name
    path.write_text(json.dumps(cap))
    return path


def test_capsule_from_another_repository_store_is_refused(recorded, tmp_path, monkeypatch):
    import subprocess
    root, _, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'a.py').write_text('x = 1\n')
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'b']):
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=other, check=True, capture_output=True)
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    assert not r.verify_handoff(other, cap)['valid']
    with pytest.raises((ValueError, FileNotFoundError, KeyError)):
        r.continue_from_handoff(other, _write(tmp_path, cap))


def test_source_drift_after_export_refuses_continuation(recorded, tmp_path, monkeypatch):
    root, _, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return 0\n')
    assert not r.verify_handoff(root, cap)['valid']
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError):
        r.continue_from_handoff(root, _write(tmp_path, cap))


@pytest.mark.parametrize('payload', ['', '{', '[]', 'null', '{"schema": "repo-ai.handoff/2"}', '\x00\x01', '{"mission": "../../x"}'])
def test_corrupted_capsule_files_are_refused_before_execution(recorded, tmp_path, monkeypatch, payload):
    root, _, _ = recorded
    path = tmp_path / 'capsule.json'
    path.write_text(payload)
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(Exception) as exc:  # any refusal is fine; executing is not
        r.continue_from_handoff(root, path)
    assert 'must refuse' not in str(exc.value)


def test_symlinked_capsule_is_not_followed(recorded, tmp_path, monkeypatch):
    root, _, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    real = _write(tmp_path, cap, 'real.json')
    link = tmp_path / 'link.json'
    link.symlink_to(real)
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    with pytest.raises(ValueError):
        r.continue_from_handoff(root, link)


def test_capsule_mission_id_cannot_traverse_the_store(recorded, tmp_path, monkeypatch):
    root, _, state = recorded
    cap = r.handoff(root, state['id'], target_provider='bob')
    cap['mission'] = '../' + state['id']
    cap['integrity_sha256'] = digest({k: v for k, v in cap.items() if k != 'integrity_sha256'})
    monkeypatch.setattr(r, 'execute', lambda *a, **k: pytest.fail('must refuse before execution'))
    assert not r.verify_handoff(root, cap)['valid']
    with pytest.raises(Exception):
        r.continue_from_handoff(root, _write(tmp_path, cap))
