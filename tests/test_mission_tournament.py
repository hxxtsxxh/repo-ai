import hashlib
import json
import pytest
from test_mission_runtime import bug as bug_fixture, git
from repo_ai.mission.runtime import plan
from repo_ai.mission.tournament import compare_candidates


@pytest.fixture
def bug(tmp_path):
    return bug_fixture.__wrapped__(tmp_path)


def proposal(root, target, text):
    target.write_text(json.dumps({'schema':'repo-ai.replay/1','label':'simulated candidate','edits':[
        {'path':'charge.py','before_sha256':hashlib.sha256((root/'charge.py').read_bytes()).hexdigest(),'after':text}]}))
    return target


def test_common_adversarial_suite_rejects_superficial_candidate(bug,tmp_path):
    with (bug/'test_charge.py').open('a') as f:
        f.write('\ndef test_other_amount():\n    assert charge(7, 2) == 7\n')
    git(bug,'add','test_charge.py')
    git(bug,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','freeze adversarial acceptance')
    p=plan(bug,'repair charge.py retries',agent='replay',write_paths=['charge.py'],execute_local=True)
    a=proposal(bug,tmp_path/'a.json','def charge(amount, retries):\n    return 10\n')
    b=proposal(bug,tmp_path/'b.json','def charge(amount, retries):\n    return amount\n')
    result=compare_candidates(bug,p,[a,b])
    assert result['verdict']=='PASS',result
    from repo_ai.mission.runtime import status
    saved=status(bug,result['id'])
    assert saved['comparison']['winner']==result['winner']
    assert saved['effective_verdict']=='PASS'
    assert result['winner']==result['candidates'][1]['id']
    assert result['candidates'][0]['verdict']=='FAIL'
    assert result['candidates'][1]['verdict']=='PASS'
    assert (bug/'charge.py').read_text().endswith('return amount * (retries + 1)\n')


def test_tournament_requires_optin_multiple_bounded_candidates(bug):
    p=plan(bug,'repair',agent='none')
    with pytest.raises(ValueError):
        compare_candidates(bug,p,[])


def test_tournament_validates_contract_kernel_and_zone_before_execution(bug, tmp_path, monkeypatch):
    from repo_ai.mission.ledger import Store
    p = plan(bug, 'repair', agent='replay', write_paths=['charge.py'], execute_local=True)
    a = proposal(bug, tmp_path / 'a.json', 'def charge(amount, retries):\n    return 10\n')
    b = proposal(bug, tmp_path / 'b.json', 'def charge(amount, retries):\n    return amount\n')

    no_approvals = json.loads(json.dumps(p))
    no_approvals['contract']['approvals'] = []
    with pytest.raises(ValueError, match='approval'):
        compare_candidates(bug, no_approvals, [a, b])

    stale_kernel = json.loads(json.dumps(p))
    stale_kernel['kernel'] = '0' * 64
    with pytest.raises(ValueError, match='kernel'):
        compare_candidates(bug, stale_kernel, [a, b])

    wrong_zone = json.loads(json.dumps(p))
    wrong_zone['contract']['zone'] = 'restricted-other-zone'
    with pytest.raises(ValueError, match='zone'):
        compare_candidates(bug, wrong_zone, [a, b])
    assert not Store(bug).folder.exists() or not list(Store(bug).folder.glob('*.json'))


def test_tournament_abstains_on_duplicate_proposals_exhausted_budget_or_unstable_third_candidate(bug, tmp_path, monkeypatch):
    from repo_ai.mission import tournament
    p = plan(bug, 'repair', agent='replay', write_paths=['charge.py'], execute_local=True)
    a = proposal(bug, tmp_path / 'a.json', 'def charge(amount, retries):\n    return amount\n')
    a_dup = proposal(bug, tmp_path / 'a_dup.json', 'def charge(amount, retries):\n    return amount\n')
    b = proposal(bug, tmp_path / 'b.json', 'def charge(amount, retries):\n    return 10\n')

    with pytest.raises(ValueError, match='distinct|duplicate'):
        compare_candidates(bug, p, [a, a_dup])

    # If candidate 1 is blocked (e.g. budget exhausted), candidate 0 cannot win by default.
    calls = []

    def fake_exec_budget(root, trial, prop):
        calls.append(prop)
        if len(calls) == 1:
            return {'id': 'a' * 24, 'effective_verdict': 'PASS', 'proposal_sha256': '1' * 64,
                    'passport': {'verdict': 'PASS', 'negative': []}, 'seconds_used': 1.0}
        raise ValueError('simulated candidate block')

    monkeypatch.setattr(tournament, 'execute', fake_exec_budget)
    res_blocked = compare_candidates(bug, p, [a, b])
    assert res_blocked['winner'] is None
    assert res_blocked['verdict'] == 'INCONCLUSIVE'

    # If candidate 1 destabilizes baseline, candidate 2 matching candidate 0 must also be INCONCLUSIVE.
    c = proposal(bug, tmp_path / 'c.json', 'def charge(amount, retries):\n    return amount + 0\n')
    idx = {'n': 0}

    def fake_exec_unstable(root, trial, prop):
        i = idx['n']
        idx['n'] += 1
        env_key = 'env-A' if i in (0, 2) else 'env-B'
        verdict = 'PASS' if i == 2 else 'FAIL'
        return {
            'id': chr(ord('a') + i) * 24,
            'effective_verdict': verdict,
            'proposal_sha256': str(i) * 64,
            'passport': {'verdict': verdict, 'negative': []},
            'seconds_used': 0.1,
            'baseline': {
                'test_ids': ['test_charge.py::test_retry'],
                'environment_static': {},
                'environment_key': env_key,
                'executor': {},
                'pin': {'test_inputs': {}},
                'outcomes': {'test_charge.py::test_retry': 'fail'},
            },
        }

    monkeypatch.setattr(tournament, 'execute', fake_exec_unstable)
    res_unstable = compare_candidates(bug, p, [a, b, c])
    assert res_unstable['winner'] is None
    assert res_unstable['verdict'] == 'INCONCLUSIVE'
    assert res_unstable['candidates'][2]['verdict'] == 'INCONCLUSIVE'
