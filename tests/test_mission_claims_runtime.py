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


def test_requirements_frozen_with_the_mission_are_assessed_and_marked(bug, tmp_path):
    """C11 next action: `do --requirements FILE` freezes the declaration before the run; `coverage ID` uses it and
    says it was declared in advance. A declaration supplied afterwards is marked as such."""
    from conftest import run_cli
    from repo_ai.mission import coverage as cov
    f = tmp_path / 'req.json'
    f.write_text(json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'retries do not charge twice', 'tests': ['test_retry']}]}))
    done = run_cli(bug, 'do', 'Fix duplicate charge in charge.py when retries happen', '--agent', 'replay',
                   '--replay', str(replay(bug, tmp_path)), '--run', '--allow-write', 'charge.py',
                   '--requirements', str(f), '--json')
    mission = json.loads(done.stdout)
    assert mission['effective_verdict'] == 'PASS', done.stdout[-400:] + done.stderr[-400:]
    out = run_cli(bug, 'coverage', mission['id'], '--json')
    data = json.loads(out.stdout)
    assert data['declaration'] == 'FROZEN_WITH_MISSION' and data['headline'] == 'ACCEPTANCE_MAPPED_ALL', out.stdout
    assert any('frozen with the mission before it ran' in x for x in data['limits'])
    assert 'Declaration: frozen with the mission before it ran' in run_cli(bug, 'coverage', mission['id']).stdout
    same = json.loads(run_cli(bug, 'coverage', mission['id'], '--requirements', str(f), '--json').stdout)
    assert same['declaration'] == 'FROZEN_WITH_MISSION'
    later = tmp_path / 'later.json'
    later.write_text(json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'a single charge still works', 'kind': 'preserve', 'tests': ['test_once']}]}))
    after = json.loads(run_cli(bug, 'coverage', mission['id'], '--requirements', str(later), '--json').stdout)
    assert after['declaration'] == 'SUPPLIED_AT_ASSESSMENT'
    assert any('A different declaration was frozen' in x for x in after['limits'])


def test_coverage_without_a_declaration_is_refused(bug, tmp_path):
    from conftest import run_cli
    from repo_ai.mission.runtime import execute, plan
    p = plan(bug, 'Fix duplicate charge in charge.py when retries happen', agent='replay',
             write_paths=['charge.py'], execute_local=True)
    result = execute(bug, p, replay(bug, tmp_path))
    out = run_cli(bug, 'coverage', result['id'])
    assert out.returncode != 0 and 'no requirements declaration' in (out.stdout + out.stderr)
