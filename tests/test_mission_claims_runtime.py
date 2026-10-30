"""Claims disclosure through the real mission runtime (needs a host sandbox)."""
import json

from test_mission_runtime import bug as bug_fixture, replay

bug = bug_fixture


def test_status_and_explanation_carry_claims(bug, tmp_path):
    from repo_ai.mission.explanation import explain, render
    from repo_ai.mission.runtime import execute, plan, status
    p = plan(bug, 'Fix duplicate charge in charge.py when retries happen', agent='replay',
             write_paths=['charge.py'], execute_local=True)
    result = execute(bug, p, replay(bug, tmp_path))
    assert result['effective_verdict'] == 'PASS'
    claim = status(bug, result['id'])['claims']
    assert claim['schema'] == 'repo-ai.claims/1' and claim['task_correct'] == 'CLAIM_UNVERIFIED'
    assert claim['headline'] in {'OBSERVED_TESTS_PASS', 'ASSURANCE_PARTIAL'}
    report = explain(bug, result['id'])
    assert report['claims']['headline'] == claim['headline']
    assert 'Claim:' in render(report)
    (bug / 'charge.py').write_text('changed\n')
    assert status(bug, result['id'])['claims']['headline'] == 'STALE'


def test_coverage_cli_end_to_end_on_a_real_mission(bug, tmp_path):
    from conftest import run_cli
    from repo_ai.mission import coverage as cov
    from repo_ai.mission.runtime import execute, plan
    p = plan(bug, 'Fix duplicate charge in charge.py when retries happen', agent='replay',
             write_paths=['charge.py'], execute_local=True)
    result = execute(bug, p, replay(bug, tmp_path))
    assert result['effective_verdict'] == 'PASS'
    f = tmp_path / 'req.json'
    f.write_text(json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'retries do not charge twice', 'kind': 'change', 'tests': ['test_retry']},
        {'text': 'a single charge still works', 'kind': 'preserve', 'tests': ['test_once']},
        {'text': 'concurrent retries are safe', 'tests': []}]}))
    out = run_cli(bug, 'coverage', result['id'], '--requirements', str(f), '--json')
    assert out.returncode == 2, out.stdout + out.stderr             # a gap means non-zero, by design
    data = json.loads(out.stdout)
    assert data['headline'] == 'ACCEPTANCE_PARTIAL' and data['task_correct'] == 'CLAIM_UNVERIFIED'
    assert [r['status'] for r in data['requirements']] == ['VERIFIED_FAIL_TO_PASS', 'VERIFIED_PRESERVED', 'UNMAPPED']
    f.write_text(json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'retries do not charge twice', 'tests': ['test_retry']}]}))
    full = run_cli(bug, 'coverage', result['id'], '--requirements', str(f))
    assert full.returncode == 0 and 'ACCEPTANCE_MAPPED_ALL' in full.stdout and 'CLAIM_UNVERIFIED' in full.stdout
    (bug / 'charge.py').write_text('changed\n')
    stale = json.loads(run_cli(bug, 'coverage', result['id'], '--requirements', str(f), '--json').stdout)
    assert stale['headline'] == 'STALE'
    assert run_cli(bug, 'coverage', result['id'], '--requirements', str(tmp_path / 'missing.json')).returncode != 0
