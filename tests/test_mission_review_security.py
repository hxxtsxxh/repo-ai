"""Independent adversarial regressions: assertions express required safe behavior."""
import hashlib
import json

import pytest

from repo_ai.mission import runtime, tournament
from repo_ai.mission.contracts import digest
from repo_ai.mission.ledger import Store
from test_mission_runtime import bug as bug_fixture, git


@pytest.fixture
def bug(tmp_path):
    return bug_fixture.__wrapped__(tmp_path)


def test_assertion_helper_cannot_turn_broken_production_into_a_pass(bug, tmp_path):
    (bug / 'tests').mkdir()
    (bug / 'tests/__init__.py').write_text('')
    helper = bug / 'tests/assertions.py'
    helper.write_text('def assert_charge(actual, expected):\n    assert actual == expected\n')
    (bug / 'test_charge.py').write_text(
        'from charge import charge\nfrom tests.assertions import assert_charge\n'
        'def test_retry():\n    assert_charge(charge(10, 2), 10)\n'
        'def test_once():\n    assert_charge(charge(10, 0), 10)\n')
    git(bug, 'add', '.')
    git(bug, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-qm', 'acceptance helper')
    planned = runtime.plan(bug, 'Repair duplicate charges while preserving acceptance',
                           agent='replay', execute_local=True,
                           write_paths=['tests/assertions.py'])
    artifact = tmp_path / 'helper-replay.json'
    artifact.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'disable assertion',
        'edits': [{'path': 'tests/assertions.py',
                   'before_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
                   'after': 'def assert_charge(actual, expected):\n    pass\n'}]}))
    try:
        result = runtime.execute(bug, planned, artifact)
    except ValueError:
        return  # Rejecting a test-support edit before execution is also safe.
    assert result['effective_verdict'] != 'PASS', result


def test_kernel_identity_covers_executed_node_reporter(tmp_path, monkeypatch):
    package = tmp_path / 'repo_ai'
    for directory in ('mission', 'verify', 'providers'):
        (package / directory).mkdir(parents=True)
    for name in ('__init__.py', 'security.py', 'config.py', 'paths.py', 'sandbox.py'):
        (package / name).write_text('# fixture\n')
    entry = package / 'mission/runtime.py'
    entry.write_text('# fixture\n')
    reporter = package / 'verify/rai_reporter.mjs'
    reporter.write_text('// original reporting protocol\n')
    monkeypatch.setattr(runtime, '__file__', str(entry))
    before = runtime.kernel_identity()
    reporter.write_text('// different reporting protocol\n')
    assert runtime.kernel_identity() != before


def test_comparison_is_stale_when_a_resumed_child_passport_changes(bug, monkeypatch):
    planned = runtime.plan(bug, 'Repair charges', agent='replay', execute_local=True,
                           write_paths=['charge.py'])
    store = Store(bug)
    ids = ['a' * 24, 'b' * 24]

    def recorded_execution(root, trial, proposal):
        index = len(list(store.folder.glob('*.json'))) if store.folder.exists() else 0
        verdict = 'PASS' if index == 0 else 'FAIL'
        record = {'id': ids[index], 'repository': store.repository,
                  'state': 'COMPLETE' if index == 0 else 'INCONCLUSIVE', 'events': [],
                  'source': planned['source'], 'kernel': planned['kernel'],
                  'proposal_sha256': digest(str(proposal)),
                  'passport': {'verdict': verdict, 'negative': [], 'observations': [digest(index)]}}
        store.save(record)
        return runtime.status(root, record['id'])

    monkeypatch.setattr(tournament, 'execute', recorded_execution)
    result = tournament.compare_candidates(bug, planned, [bug / 'a.json', bug / 'b.json'])
    assert result['verdict'] == 'PASS'
    assert runtime.status(bug, result['id'])['effective_verdict'] == 'PASS'
    # A permitted explicit resume replaces an INCONCLUSIVE child's latest passport
    # at the same ID. It does not alter source, kernel or environment freshness.
    resumed = store.load(ids[1])
    resumed['state'] = 'COMPLETE'
    resumed['passport'] = {'verdict': 'PASS', 'negative': [], 'observations': [digest('resumed')]}
    store.save(resumed)
    assert runtime.status(bug, ids[1])['effective_verdict'] == 'PASS'
    stale_status = runtime.status(bug, result['id'])
    assert stale_status['effective_verdict'] != 'PASS'
    assert stale_status['comparison']['winner'] is None
    assert stale_status['comparison']['verdict'] == 'INCONCLUSIVE'


def test_git_porcelain_preserves_leading_unstaged_space(bug):
    (bug / 'charge.py').write_text('def charge(amount, retries):\n    return amount\n')
    raw = runtime.git(bug, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    entries = [e for e in raw.split('\0') if e]
    assert entries == [' M charge.py']


def test_case_variant_or_sitecustomize_cannot_bypass_frozen_test_protection(bug, tmp_path):
    from repo_ai.mission.verification import test_support
    assert test_support('Tests/assertions.py')
    assert test_support('CONFTEST.PY')
    assert test_support('sitecustomize.py')
    assert test_support('usercustomize.py')
    planned = runtime.plan(bug, 'Repair charge', agent='replay', execute_local=True,
                           write_paths=['Charge.py'])
    artifact = tmp_path / 'case-replay.json'
    artifact.write_text(json.dumps({
        'schema': 'repo-ai.replay/1',
        'label': 'case variant path',
        'edits': [{
            'path': 'Charge.py',
            'before_sha256': hashlib.sha256((bug / 'charge.py').read_bytes()).hexdigest(),
            'after': 'def charge(amount, retries):\n    return amount\n',
        }],
    }))
    with pytest.raises(ValueError, match='frozen|tracked|approved|stale'):
        runtime.proposal(artifact, bug, runtime.decode(planned['contract']))


def test_proposal_blocks_all_secret_scanner_findings_and_verification_redacts_exceptions(bug, tmp_path, monkeypatch):
    from repo_ai.mission import verification
    planned = runtime.plan(bug, 'Repair charge', agent='replay', execute_local=True,
                           write_paths=['charge.py'])
    secret_after = (
        'def charge(amount, retries):\n'
        '    passphrase = "x9#mK2$pL8@vQ5!nR7^wT4&yU6*zB3(cF1"\n'
        '    return amount\n'
    )
    artifact = tmp_path / 'secret-replay.json'
    artifact.write_text(json.dumps({
        'schema': 'repo-ai.replay/1',
        'label': 'secret edit',
        'edits': [{
            'path': 'charge.py',
            'before_sha256': hashlib.sha256((bug / 'charge.py').read_bytes()).hexdigest(),
            'after': secret_after,
        }],
    }))
    with pytest.raises(ValueError, match='secret-shaped material'):
        runtime.proposal(artifact, bug, runtime.decode(planned['contract']))

    def boom(*args, **kwargs):
        raise RuntimeError('failed with token=sk-1234567890abcdefghijklmnop')

    monkeypatch.setattr(verification, '_runner', boom)
    obs = verification.observe(bug, 'python -m pytest')
    assert 'sk-1234567890abcdefghijklmnop' not in json.dumps(obs)
