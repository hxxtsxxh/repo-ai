import json

from conftest import run_cli
import pytest
from test_mission_runtime import bug as bug_fixture, replay


@pytest.fixture
def bug(tmp_path):
    return bug_fixture.__wrapped__(tmp_path)


def test_do_default_json_is_a_plan_and_does_not_persist(bug):
    result = run_cli(bug, 'do', 'Fix duplicate charges in charge.py', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['contract']['execute'] is False
    assert value['decision'] == 'ASK_APPROVAL'
    assert not (bug / '.repo-ai').exists()


def test_cli_real_fixture_execution_trace_and_handoff(bug, tmp_path):
    proposal = replay(bug, tmp_path)
    result = run_cli(bug, 'do', 'Fix charge.py retries', '--agent', 'replay', '--replay', str(proposal),
                     '--allow-write', 'charge.py', '--run', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    mission = value['id']
    assert value['effective_verdict'] == 'PASS'
    for command in [('mission', 'status'), ('why',), ('trace',), ('replay',), ('handoff',)]:
        result = run_cli(bug, *command, mission, '--json')
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)
    capsule = json.loads(run_cli(bug, 'handoff', mission, '--format', 'json').stdout)
    assert 'return amount' not in json.dumps(capsule)
    assert capsule['disclosure'].startswith('LOCAL_ONLY')
    result = run_cli(bug, 'privacy', '--json')
    assert result.returncode == 0, result.stderr
    assert 'missions (experimental)' in result.stdout
    export = bug / '.repo-ai' / 'handoff-export.json'
    export.write_text(json.dumps(capsule))
    result = run_cli(bug, 'uninstall', '--yes')
    assert result.returncode == 0, result.stderr
    assert export.exists()
    assert not (bug / '.repo-ai/state/missions').exists()


def test_agent_list_does_not_invoke_a_model(bug):
    result = run_cli(bug, 'agents', 'list', '--json')
    assert result.returncode == 0, result.stderr
    profiles = json.loads(result.stdout)['providers']
    assert {p['provider'] for p in profiles} == {'codex', 'claude', 'gemini', 'bob', 'agy', 'opencode'}
    assert all(p['authentication'] == 'UNKNOWN' for p in profiles)
