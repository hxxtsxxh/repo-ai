import json
from conftest import run_cli


def test_empty_list_offline_and_usage_errors(pyweb):
    result = run_cli(pyweb, 'mission', 'list', '--json')
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'schema': 'repo-ai.mission-list/1', 'missions': []}
    assert run_cli(pyweb, 'mission', 'status').returncode != 0
    assert run_cli(pyweb, 'mission', 'list', 'a' * 24).returncode != 0


def test_list_withholds_cross_zone_objective(pyweb):
    from repo_ai.mission.runtime import Store, identity
    store = Store(pyweb)
    store.save({'id': 'a' * 24, 'repository': store.repository, 'source': identity(pyweb),
                'state': 'BLOCKED', 'contract': {'zone': 'another-zone', 'objective': 'PRIVATE'}})
    result = run_cli(pyweb, 'mission', 'list', '--json')
    assert result.returncode == 0
    assert 'PRIVATE' not in result.stdout
    assert json.loads(result.stdout)['missions'][0]['state'] == 'UNAVAILABLE'
