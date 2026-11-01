"""Adversarial source-write boundary tests; verification is injected, Git is real."""
from __future__ import annotations

import json

import hashlib
from pathlib import Path

import pytest

from repo_ai.mission import runtime, verification
from conftest import _git


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    root = (tmp_path / 'repo').resolve()
    root.mkdir()
    for name in ('allowed.py', 'outside.py'):
        (root / name).write_text('old\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'baseline')
    state = {'id': 'a' * 24, 'repository': runtime.Store(root).repository,
             'state': 'COMPLETE', 'effective_verdict': 'PASS', 'freshness': 'fresh',
             'source': runtime.identity(root, require_clean=True),
             'contract': {'write_paths': ['allowed.py'], 'acceptance': ['python -m pytest']},
             'baseline': {}, 'provider': {'simulated': True}}
    zone, policy = runtime.privacy_binding(root)
    state['contract'].update(zone=zone, policy_sha256=policy)
    monkeypatch.setattr(runtime, 'status', lambda *a, **k: state)
    monkeypatch.setattr(verification, 'observe', lambda *a, **k: {'complete': True, 'ran': 1, 'failed': 0})
    monkeypatch.setattr(verification, 'compare', lambda *a, **k: ('PASS', []))

    def proposal(paths=('allowed.py',)):
        for name in paths:
            (root / name).write_text('new\n')
        state['diff'] = runtime.git(root, 'diff')
        state['diff_sha256'] = hashlib.sha256(state['diff'].encode()).hexdigest()
        for name in paths:
            (root / name).write_text('old\n')
        runtime.Store(root).save(state)
        return state
    proposal()
    return root, state, proposal


def test_patch_hash_checked_before_source_write(prepared):
    root, state, _ = prepared
    state['diff_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='hash|integrity'):
        runtime.apply_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'old\n'


def test_outside_patch_refused_without_leaving_changes(prepared):
    root, state, proposal = prepared
    proposal(('allowed.py', 'outside.py'))
    with pytest.raises(ValueError, match='scope|approved|allowlist'):
        runtime.apply_mission(root, state['id'])
    assert (root / 'outside.py').read_text() == 'old\n'
    assert (root / 'allowed.py').read_text() == 'old\n'


def test_failed_verification_preserves_concurrent_edit(prepared, monkeypatch):
    root, state, _ = prepared
    def concurrent(*a, **k):
        (root / 'allowed.py').write_text('human edit\n')
        return {'complete': False, 'ran': 0, 'failed': 0}
    monkeypatch.setattr(verification, 'observe', concurrent)
    with pytest.raises(ValueError):
        runtime.apply_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'human edit\n'


def test_empty_verification_cannot_apply(prepared, monkeypatch):
    root, state, _ = prepared
    monkeypatch.setattr(verification, 'observe', lambda *a, **k: {'complete': True, 'ran': 0, 'failed': 0})
    with pytest.raises(ValueError):
        runtime.apply_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'old\n'


def test_receipt_undo_and_duplicate_apply(prepared):
    root, state, _ = prepared
    result = runtime.apply_mission(root, state['id'])
    assert result['post_apply_verdict'] == 'PASS'
    assert Path(result['receipt']).is_file()
    with pytest.raises(ValueError, match='receipt|already'):
        runtime.apply_mission(root, state['id'])
    result = runtime.undo_mission(root, state['id'])
    assert result['undone'] is True
    assert (root / 'allowed.py').read_text() == 'old\n'
    assert runtime.undo_mission(root, state['id'])['undone'] is True


def test_undo_refuses_later_user_edit(prepared):
    root, state, _ = prepared
    runtime.apply_mission(root, state['id'])
    (root / 'allowed.py').write_text('human edit\n')
    with pytest.raises(ValueError, match='conflict|changed'):
        runtime.undo_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'human edit\n'


def test_live_label_demoted_if_candidate_cleanup_fails(tmp_path, monkeypatch):
    """Inject successful observations to isolate the post-verdict cleanup boundary."""
    from types import SimpleNamespace
    from test_mission_runtime import bug as bug_fixture
    from repo_ai.providers import adapters
    root = bug_fixture.__wrapped__(tmp_path)
    planned = runtime.plan(root, 'repair charge.py', agent='codex', write_paths=['charge.py'],
                           execute_local=True, allow_live=True)
    import sys
    def provider(*args, **kwargs):
        (args[2] / 'charge.py').write_text('def charge(amount, retries):\n    return amount\n')
        return {'stage': 'READY', 'verification_label': 'LIVE_READY', 'reasons': []}
    monkeypatch.setattr(adapters, 'run_provider', provider)
    monkeypatch.setattr(verification, 'observe', lambda *a, **k: {'complete': True, 'ran': 1, 'failed': 0})
    monkeypatch.setattr(verification, 'compare', lambda *a, **k: ('PASS', []))
    monkeypatch.setattr(runtime, 'get_executor', lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(runtime, 'release', lambda *a, **k: None)
    monkeypatch.setattr(runtime.engine, 'run_plan', lambda *a, **k: {
        'verdict': 'selected-and-full-suite-passed', 'source_tree': {'unchanged': True}})
    monkeypatch.setattr(runtime.evidence, 'environment_check', lambda *a, **k: ('unchanged', ''))
    original = runtime.isolate.Workspace.cleanup
    retained = []
    monkeypatch.setattr(runtime.isolate.Workspace, 'cleanup', lambda ws: retained.append(ws))
    try:
        result = runtime.execute(root, planned, None, provider_executable=Path(sys.executable), allow_live=True)
        assert result.get('cleanup_confirmed') is False, result
        assert result['provider']['stage'] == 'FAILED', result
        assert result['provider']['verification_label'] == 'LIVE_FAILED', result
        assert result['effective_verdict'] != 'PASS'
    finally:
        for ws in retained:
            original(ws)


@pytest.mark.parametrize('dirty', ['staged', 'unstaged', 'untracked', 'symlink'])
def test_apply_refuses_dirty_or_nonregular_target(prepared, dirty):
    root, state, _ = prepared
    if dirty == 'symlink':
        (root / 'allowed.py').unlink()
        (root / 'allowed.py').symlink_to(root / 'outside.py')
    elif dirty == 'untracked':
        (root / 'notes.txt').write_text('human notes\n')
    else:
        (root / 'allowed.py').write_text('human edit\n')
        if dirty == 'staged':
            _git(root, 'add', 'allowed.py')
    with pytest.raises(ValueError):
        runtime.apply_mission(root, state['id'])
    assert (root / 'outside.py').read_text() == 'old\n'
    if dirty in {'staged', 'unstaged'}:
        assert (root / 'allowed.py').read_text() == 'human edit\n'


def test_apply_and_undo_share_repository_lock(prepared):
    from repo_ai.locks import file_lock
    root, state, _ = prepared
    with file_lock(runtime.Store(root).folder / 'application.lock', timeout=0) as held:
        assert held
        for action in (runtime.apply_mission, runtime.undo_mission):
            with pytest.raises(ValueError, match='another apply/undo'):
                action(root, state['id'])


def test_failed_second_write_restores_only_owned_first_write(prepared, monkeypatch):
    from repo_ai.mission import application
    root, state, proposal = prepared
    state['contract']['write_paths'].append('outside.py')
    proposal(('allowed.py', 'outside.py'))
    original = application._replace
    calls = []
    def fail_second(root, rel, before, after):
        calls.append(rel)
        if len(calls) == 2:
            raise PermissionError('injected permission failure')
        return original(root, rel, before, after)
    monkeypatch.setattr(application, '_replace', fail_second)
    with pytest.raises(PermissionError):
        runtime.apply_mission(root, state['id'])
    assert calls == ['allowed.py', 'outside.py', 'allowed.py']
    assert (root / 'allowed.py').read_text() == 'old\n'
    assert (root / 'outside.py').read_text() == 'old\n'


def test_undo_recovers_prepared_receipt_after_crash(prepared):
    from repo_ai.mission import application
    root, state, _ = prepared
    store = runtime.Store(root)
    files = application._prepare(root, state)
    path = application._receipt_path(store, state['id'])
    state['application_files_sha256'] = application.digest(files)
    store.save(state)
    application._save(path, {'mission': state['id'], 'repository': store.repository,
                            'source': state['source'], 'diff_sha256': state['diff_sha256'],
                            'files': files, 'phase': 'PREPARED'})
    (root / 'allowed.py').write_text('new\n')  # crash after source replace, before next journal update
    assert runtime.undo_mission(root, state['id'])['undone']
    assert (root / 'allowed.py').read_text() == 'old\n'


def test_tampered_receipt_and_staged_undo_refuse(prepared):
    import json
    root, state, _ = prepared
    result = runtime.apply_mission(root, state['id'])
    _git(root, 'add', 'allowed.py')
    with pytest.raises(ValueError, match='staged'):
        runtime.undo_mission(root, state['id'])
    receipt = Path(result['receipt'])
    value = json.loads(receipt.read_text())
    value['record']['phase'] = 'UNDONE'
    receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='integrity'):
        runtime.undo_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'new\n'


def test_installed_command_shape_undo_json_and_missing_receipt(prepared):
    import json
    from conftest import run_cli
    root, state, _ = prepared
    no_receipt = run_cli(root, 'undo', state['id'], '--json')
    assert no_receipt.returncode != 0
    runtime.apply_mission(root, state['id'])
    result = run_cli(root, 'undo', state['id'], '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['undone'] is True


def test_rechecksummed_receipt_cannot_forge_restored_bytes(prepared):
    import base64
    import json
    from repo_ai.mission import application
    root, state, _ = prepared
    result = runtime.apply_mission(root, state['id'])
    path = Path(result['receipt'])
    rec = json.loads(path.read_text())['record']
    forged = b'attacker-chosen restoration\n'
    rec['files']['allowed.py']['before'] = base64.b64encode(forged).decode()
    rec['files']['allowed.py']['before_sha256'] = hashlib.sha256(forged).hexdigest()
    application._save(path, rec)  # attacker recomputes an unkeyed checksum
    with pytest.raises(ValueError, match='receipt|integrity'):
        runtime.undo_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'new\n'


def test_forged_undone_phase_does_not_claim_restoration(prepared):
    import json
    from repo_ai.mission import application
    root, state, _ = prepared
    result = runtime.apply_mission(root, state['id'])
    path = Path(result['receipt'])
    rec = json.loads(path.read_text())['record']
    rec['phase'] = 'UNDONE'
    application._save(path, rec)
    with pytest.raises(ValueError, match='receipt|restor|conflict'):
        runtime.undo_mission(root, state['id'])


def test_replace_refuses_a_symlinked_parent_and_writes_nothing_outside(tmp_path):
    from repo_ai.mission import application
    root = (tmp_path / 'repo').resolve()
    outside = (tmp_path / 'outside').resolve()
    (root / 'pkg').mkdir(parents=True)
    outside.mkdir()
    (outside / 'mod.py').write_text('old\n')
    (root / 'pkg').rmdir()
    (root / 'pkg').symlink_to(outside, target_is_directory=True)  # parent swapped for a link after verification
    with pytest.raises(OSError):
        application._replace(root, 'pkg/mod.py', b'old\n', b'new\n')
    assert (outside / 'mod.py').read_text() == 'old\n'
    assert [p.name for p in outside.iterdir()] == ['mod.py']  # no temp file left in the link target


def test_crash_between_temp_write_and_rename_leaves_target_and_no_temp(tmp_path, monkeypatch):
    import os
    from repo_ai.mission import application
    root = (tmp_path / 'repo').resolve()
    root.mkdir()
    (root / 'a.py').write_text('old\n')

    def boom(*a, **k):
        raise OSError('injected crash before rename')
    monkeypatch.setattr(os, 'replace', boom)
    with pytest.raises(OSError, match='injected'):
        application._replace(root, 'a.py', b'old\n', b'new\n')
    assert (root / 'a.py').read_text() == 'old\n'
    assert [p.name for p in root.iterdir()] == ['a.py']


def test_failed_rollback_keeps_receipt_and_never_overwrites_foreign_bytes(prepared, monkeypatch):
    from repo_ai.mission import application
    root, state, _ = prepared
    real = application._replace

    def flaky(r, rel, before, after):
        if before == b'new\n':  # the restore direction
            raise PermissionError('injected rollback failure')
        return real(r, rel, before, after)
    monkeypatch.setattr(application, '_replace', flaky)
    monkeypatch.setattr(verification, 'compare', lambda *a, **k: ('FAIL', ['injected post-apply failure']))
    with pytest.raises(PermissionError):
        runtime.apply_mission(root, state['id'])
    # rollback failed: the applied bytes remain, the journal says so, and undo can still finish later
    assert (root / 'allowed.py').read_text() == 'new\n'
    receipt = application._receipt_path(runtime.Store(root), state['id'])
    assert '"phase":"RESTORING"' in receipt.read_text().replace(' ', '')
    monkeypatch.setattr(application, '_replace', real)
    (root / 'allowed.py').write_text('user edit made meanwhile\n')
    with pytest.raises(ValueError, match='conflict'):
        runtime.undo_mission(root, state['id'])
    assert (root / 'allowed.py').read_text() == 'user edit made meanwhile\n'


def test_the_claude_auth_mode_reaches_the_mission_record(tmp_path, monkeypatch):
    """The adapter reports how a live Claude run authenticated (token_env or dedicated_config, a name only); the
    mission record keeps it, so the evidence says which isolation mode the run used."""
    from types import SimpleNamespace
    from test_mission_runtime import bug as bug_fixture
    from repo_ai.providers import adapters
    root = bug_fixture.__wrapped__(tmp_path)
    planned = runtime.plan(root, 'repair charge.py', agent='claude', write_paths=['charge.py'],
                           execute_local=True, allow_live=True)
    import sys

    def provider(*args, **kwargs):
        (args[2] / 'charge.py').write_text('def charge(amount, retries):\n    return amount\n')
        return {'stage': 'READY', 'verification_label': 'LIVE_READY', 'reasons': [], 'auth_mode': 'token_env',
                'cost_usd': 0.01, 'cost_status': 'OBSERVED'}
    monkeypatch.setattr(adapters, 'run_provider', provider)
    monkeypatch.setattr(verification, 'observe', lambda *a, **k: {'complete': True, 'ran': 1, 'failed': 0})
    monkeypatch.setattr(verification, 'compare', lambda *a, **k: ('PASS', []))
    monkeypatch.setattr(runtime, 'get_executor', lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(runtime, 'release', lambda *a, **k: None)
    monkeypatch.setattr(runtime.engine, 'run_plan', lambda *a, **k: {
        'verdict': 'selected-and-full-suite-passed', 'source_tree': {'unchanged': True}})
    monkeypatch.setattr(runtime.evidence, 'environment_check', lambda *a, **k: ('unchanged', ''))
    result = runtime.execute(root, planned, None, provider_executable=Path(sys.executable), allow_live=True)
    assert result['provider'].get('auth_mode') == 'token_env', result['provider']
    assert 'CLAUDE_CODE_OAUTH_TOKEN' not in json.dumps(result)
