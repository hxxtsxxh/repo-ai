"""Gate E: failure clustering, Change Futures and ledger staleness each change the next decision (offline, replay)."""
import hashlib
import json

import pytest

from repo_ai.mission import diagnosis
from repo_ai.mission.futures import analyze_futures
from repo_ai.mission.runtime import execute, plan, status
from test_mission_runtime import git


@pytest.fixture
def two_areas(tmp_path):
    root = (tmp_path / 'r').resolve()
    root.mkdir()
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return amount * (retries + 1)\n')
    (root / 'refund.py').write_text('def refund(amount, fee):\n    return amount + fee\n')
    (root / 'test_charge.py').write_text('from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n')
    (root / 'test_refund.py').write_text(
        'from refund import refund\n\ndef test_fee_a():\n    assert refund(10, 1) == 9\n\n'
        'def test_fee_b():\n    assert refund(20, 2) == 18\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (root / '.gitignore').write_text('__pycache__/\n.pytest_cache/\n.repo-ai/\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'base')
    return root


def _mission(root):
    proposal = root.parent / 'p.json'
    proposal.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'simulated fixture agent', 'edits': [{
        'path': 'charge.py', 'before_sha256': hashlib.sha256((root / 'charge.py').read_bytes()).hexdigest(),
        'after': 'def charge(amount, retries):\n    return amount\n'}]}))
    planned = plan(root, 'Fix duplicate charge in charge.py', agent='replay', write_paths=['charge.py'], execute_local=True)
    return execute(root, planned, proposal)


def test_clustering_futures_and_staleness_change_the_next_decision(two_areas):
    root = two_areas
    mission = _mission(root)
    # The candidate fixed the charge failure but did not touch the refund area; the mission is not a PASS.
    assert mission['effective_verdict'] != 'PASS'

    report = diagnosis.diagnose(root, mission['id'])
    clusters = {c['test_file']: c for c in report['failure_clusters']}
    assert list(clusters) == ['test_refund.py']          # the fixed charge test is not a residual cluster
    assert clusters['test_refund.py']['standing'] == 'RESIDUAL_OUTSIDE_CHANGE'
    assert clusters['test_refund.py']['changed_by_candidate'] == []
    # Decision 1: do not re-investigate the changed file; aim at the source the residual failures import.
    assert [e['command'][2] for e in report['next_experiments']] == ['refund.py']

    # Decision 2: Change Futures on the redirected target selects the additional check (its linked tests).
    futures = analyze_futures(root, paths=['refund.py'])
    assert futures['local_impact'][0]['linked_tests'] == ['test_refund.py']
    assert futures['local_impact'][0]['confidence'] == 'static' and futures['reran_tests'] is False

    # Decision 3: changing an input the claim depends on stales it and diagnosis refuses to explain history.
    (root / 'refund.py').write_text('def refund(amount, fee):\n    return amount - fee\n')
    assert status(root, mission['id'])['freshness'] == 'stale'
    stale = diagnosis.diagnose(root, mission['id'])
    assert stale['standing'] == 'INCONCLUSIVE' and stale['failure_clusters'] == []


def test_a_residual_failure_inside_the_changed_area_does_not_redirect(two_areas):
    root = two_areas
    (root / 'test_charge.py').write_text(
        'from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n\n'
        'def test_never_satisfiable():\n    assert charge(10, 0) == 11\n')
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'hard test')
    report = diagnosis.diagnose(root, _mission(root)['id'])
    standings = {c['test_file']: c['standing'] for c in report['failure_clusters']}
    assert standings['test_charge.py'] == 'RESIDUAL_IN_CHANGED_AREA'
    assert standings['test_refund.py'] == 'RESIDUAL_OUTSIDE_CHANGE'
