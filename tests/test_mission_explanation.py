"""Readable causal explanations must retain limitations and invalidation reasons."""
import json

import pytest

from conftest import run_cli
from repo_ai.mission import runtime
from repo_ai.mission.explanation import explain
from test_mission_runtime import bug as bug_fixture, replay


@pytest.fixture
def completed(tmp_path):
    root = bug_fixture.__wrapped__(tmp_path)
    result = runtime.execute(root, runtime.plan(root, 'repair charge.py', agent='replay',
                             execute_local=True, write_paths=['charge.py']), replay(root, tmp_path))
    return root, result


def test_explanation_links_request_observations_and_diff_without_source_dump(completed):
    root, result = completed
    report = explain(root, result['id'])
    assert report['verdict'] == 'PASS'
    assert [step['role'] for step in report['evidence']] == ['baseline', 'candidate', 'regression']
    assert report['evidence'][0]['failed'] == 1
    assert report['evidence'][1]['failed'] == 0
    assert all(len(step['sha256']) == 64 for step in report['evidence'])
    assert report['diff_sha256'] == result['diff_sha256']
    assert report['provider']['simulated'] is True
    assert 'return amount' not in json.dumps(report)
    assert 'ProofLab' in ' '.join(report['limits'])
    response = run_cli(root, 'why', result['id'])
    assert response.returncode == 0
    assert 'Baseline' in response.stdout and '1 failing' in response.stdout
    assert 'candidate diff' in response.stdout


def test_source_change_explains_staleness_without_repeating_old_pass(completed):
    root, result = completed
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return 999\n')
    report = explain(root, result['id'])
    assert report['verdict'] == 'INCONCLUSIVE'
    assert 'source changed' in ' '.join(report['freshness_reasons'])
    assert all(step['standing'] == 'stale' for step in report['evidence'])


def test_kernel_change_is_a_distinct_invalidation(completed, monkeypatch):
    root, result = completed
    monkeypatch.setattr(runtime, 'kernel_identity', lambda: 'changed-kernel')
    report = explain(root, result['id'])
    assert report['verdict'] == 'INCONCLUSIVE'
    assert 'kernel changed' in ' '.join(report['freshness_reasons'])


def test_terminal_explanation_escapes_untrusted_control_characters(completed):
    from repo_ai.mission.explanation import render
    root, result = completed
    report = explain(root, result['id'])
    report['objective'] = '\x1b[2Jfake PASS\nnext-line'
    text = render(report)
    assert '\x1b' not in text
    assert '\\u001b' in text
