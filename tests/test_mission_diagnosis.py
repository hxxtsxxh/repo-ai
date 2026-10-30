"""Failure diagnosis consumes recorded observations, never agent self-report."""
import copy
import json

import pytest

from conftest import run_cli
from repo_ai.mission import runtime, verification
from repo_ai.mission.diagnosis import diagnose
from test_mission_runtime import bug as bug_fixture, replay
from test_mission_verification import repo as observer_fixture, _fake_executor


@pytest.fixture
def observations(tmp_path, monkeypatch):
    root = observer_fixture.__wrapped__(tmp_path)
    _fake_executor(monkeypatch, 'fail')
    baseline = verification.observe(root, 'python -m pytest')
    (root / 'calc.py').write_text('value = 2\n')
    _fake_executor(monkeypatch, 'pass')
    candidate = verification.observe(root, 'python -m pytest')
    state = {'id': 'a' * 24, 'state': 'COMPLETE', 'freshness': 'fresh', 'effective_verdict': 'PASS',
             'baseline': baseline, 'candidate': candidate, 'events': [],
             'contract': {'acceptance': ['python -m pytest']},
             'plan': {'context': {'packet': {'locations': []}}}}
    monkeypatch.setattr(runtime, 'status', lambda *a, **k: copy.deepcopy(state))
    return root, state


@pytest.mark.parametrize(('before', 'after', 'classification'), [
    ('fail', 'pass', 'FIXED_IN_OBSERVED_SUITE'), ('fail', 'fail', 'PRE_EXISTING_FAILURE'),
    ('pass', 'fail', 'NEW_FAILURE'), ('pass', 'pass', 'UNCHANGED_PASS'),
])
def test_classifies_real_baseline_delta_without_requiring_a_winning_candidate(observations, before, after, classification):
    root, state = observations
    for key, value in [('baseline', before), ('candidate', after)]:
        record = state[key]
        record['outcomes'] = {test: value for test in record['test_ids']}
        record['failed'] = len(record['test_ids']) if value == 'fail' else 0
        record['exit_code'] = int(value == 'fail')
    report = diagnose(root, state['id'])
    assert report['standing'] == 'OBSERVED'
    assert {row['classification'] for row in report['tests']} == {classification}
    assert all(len(row['evidence']['baseline']) == 64 for row in report['tests'])
    assert report['reran_tests'] is False
    assert 'root cause' in ' '.join(report['limitations'])


@pytest.mark.parametrize('attack', ['missing_baseline', 'stale', 'changed_tests', 'skip', 'contradictory_exit', 'missing_test'])
def test_false_confidence_is_inconclusive(observations, attack):
    root, state = observations
    if attack == 'missing_baseline':
        del state['baseline']
    elif attack == 'stale':
        state['freshness'] = 'stale'
    elif attack == 'changed_tests':
        state['candidate']['pin']['test_inputs'] = {'test_calc.py': 'changed'}
    elif attack == 'skip':
        state['candidate']['skipped'] = 1
    elif attack == 'contradictory_exit':
        state['candidate']['exit_code'] = 9
    else:
        state['candidate']['test_ids'] = []
    report = diagnose(root, state['id'])
    assert report['standing'] == 'INCONCLUSIVE'
    assert report['reasons']
    assert all(row['classification'] == 'NOT_COMPARABLE' for row in report['tests'])


def test_unknown_test_filter_is_not_empty_success(observations):
    root, state = observations
    with pytest.raises(ValueError, match='not observed'):
        diagnose(root, state['id'], test='unobserved::test')


def test_cli_explains_repair_and_keeps_original_unchanged(tmp_path):
    bug = bug_fixture.__wrapped__(tmp_path)
    artifact = replay(bug, tmp_path)
    result = runtime.execute(bug, runtime.plan(bug, 'repair charge.py', agent='replay',
                             execute_local=True, write_paths=['charge.py']), artifact)
    response = run_cli(bug, 'why-test-failed', result['id'], '--json')
    assert response.returncode == 0, response.stderr
    report = json.loads(response.stdout)
    assert report['standing'] == 'OBSERVED'
    assert 'FIXED_IN_OBSERVED_SUITE' in {r['classification'] for r in report['tests']}
    assert 'return amount * (retries + 1)' in (bug / 'charge.py').read_text()
    text = run_cli(bug, 'why-test-failed', result['id'])
    assert 'FIXED_IN_OBSERVED_SUITE' in text.stdout
    assert 'No tests or providers were invoked' in text.stdout


def test_static_import_lead_is_labeled_and_does_not_claim_causality(observations):
    root, state = observations
    test_path = state['baseline']['test_ids'][0].split('::', 1)[0]
    state['source'] = {'files': {'calc.py': 'a' * 64, 'other.py': 'b' * 64, 'pkg/__init__.py': 'c' * 64}}
    state['plan']['context']['packet']['locations'] = [{'path': 'other.py'}, {'path': 'calc.py'}, {'path': 'pkg/__init__.py'}]
    state['nodes'] = {'impact': {'artifact': {'imports': {test_path: ['calc', 'pkg']}}}}
    report = diagnose(root, state['id'])
    first, second, third = report['source_hypotheses']
    assert first['path'] == 'calc.py' and first['priority'] == 'test-import-link'
    assert first['confidence'] == 'static'
    assert first['test_paths'] == [test_path]
    assert second['path'] == 'pkg/__init__.py' and second['priority'] == 'test-import-link'
    assert third['priority'] == 'context-only'
    assert 'runtime coverage' in ' '.join(report['limitations'])


def test_diagnosis_never_promotes_failed_whole_change_verification(observations):
    root, state = observations
    state['effective_verdict'] = 'INCONCLUSIVE'
    state['passport'] = {'negative': ['fresh whole-change regression verification did not pass']}
    report = diagnose(root, state['id'])
    assert report['standing'] == 'OBSERVED'
    assert report['mission_verdict'] == 'INCONCLUSIVE'
    assert report['negative_evidence'] == state['passport']['negative']
    assert state['effective_verdict'] == 'INCONCLUSIVE'


def test_render_shows_pytest_identities_once_and_accepts_the_displayed_form(observations):
    from repo_ai.mission.diagnosis import render
    root, state = observations
    key = next(iter(state['candidate']['outcomes']))
    doubled = key.split('::', 1)[0] + '::' + key
    for side in ('baseline', 'candidate'):
        state[side]['outcomes'] = {doubled: next(iter(state[side]['outcomes'].values()))}
    text = render(diagnose(root, state['id']))
    assert doubled not in text and json.dumps(key) in text
    assert diagnose(root, state['id'], test=key)['tests'][0]['test_id'] == doubled
