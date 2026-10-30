import hashlib
import json
import subprocess

import pytest
from repo_ai.mission.runtime import execute, plan, status, handoff


def git(root, *args):
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=root, capture_output=True, check=True)


@pytest.fixture
def bug(tmp_path):
    root=tmp_path/'bug'
    root.mkdir()
    (root/'charge.py').write_text('def charge(amount, retries):\n    return amount * (retries + 1)\n')
    (root/'test_charge.py').write_text('from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n\ndef test_once():\n    assert charge(10, 0) == 10\n')
    (root/'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline')
    return root


def replay(bug, tmp_path, after='def charge(amount, retries):\n    return amount\n', path='charge.py'):
    p=tmp_path/'proposal.json'
    p.write_text(json.dumps({'schema':'repo-ai.replay/1','label':'simulated fixture agent', 'edits':[
        {'path':path,'before_sha256':hashlib.sha256((bug/path).read_bytes()).hexdigest(),'after':after}]}))
    return p


def test_plan_is_offline_default_without_authority(bug):
    p=plan(bug, 'Fix duplicate charges caused by retries', agent='auto')
    assert not p['contract']['execute'] and p['contract']['max_cost_usd']==0
    assert p['decision'] in {'ASK_APPROVAL','BLOCKED'}
    assert not (bug/'.repo-ai').exists()


def test_replay_candidate_verified_but_original_untouched(bug,tmp_path):
    original=(bug/'charge.py').read_bytes()
    p=plan(bug,'Fix duplicate charge in charge.py',agent='replay',write_paths=['charge.py'],execute_local=True)
    result=execute(bug,p,replay(bug,tmp_path))
    assert result['state']=='COMPLETE',result
    assert result['passport']['verdict']=='PASS'
    assert result['provider']['simulated'] is True
    assert result['baseline']['failed']>=1 and result['candidate']['failed']==0
    assert (bug/'charge.py').read_bytes()==original
    assert 'return amount' in result['diff']
    assert status(bug,result['id'])['freshness']=='fresh'
    assert handoff(bug,result['id'])['schema']=='repo-ai.handoff/2'
    assert execute(bug,p,replay(bug,tmp_path))['id']==result['id']
    (bug/'charge.py').write_text('changed\n')
    assert status(bug,result['id'])['freshness']=='stale'


@pytest.mark.parametrize('path',['test_charge.py','pyproject.toml'])
def test_frozen_acceptance_inputs_cannot_be_edited(bug,tmp_path,path):
    p=plan(bug,'make tests pass',agent='replay',write_paths=[path],execute_local=True)
    with pytest.raises(ValueError,match='acceptance|source'):
        execute(bug,p,replay(bug,tmp_path,after='',path=path))


def test_unapproved_dirty_and_stale_edits_refuse(bug,tmp_path):
    p=plan(bug,'repair charge.py',agent='replay',write_paths=['charge.py'])
    with pytest.raises(ValueError,match='approval'):
        execute(bug,p,replay(bug,tmp_path))
    p=plan(bug,'repair charge.py',agent='replay',write_paths=['charge.py'],execute_local=True)
    (bug/'charge.py').write_text('human edit\n')
    with pytest.raises(ValueError,match='dirty|stale'):
        execute(bug,p,replay(bug,tmp_path))


def test_kernel_change_invalidates_saved_authority_before_execution(bug,tmp_path,monkeypatch):
    from repo_ai.mission import runtime
    p=plan(bug,'repair charge.py',agent='replay',write_paths=['charge.py'],execute_local=True)
    monkeypatch.setattr(runtime,'kernel_identity',lambda:'changed-kernel')
    with pytest.raises(ValueError,match='kernel'):
        execute(bug,p,replay(bug,tmp_path))


def test_uncertain_task_integrates_two_static_investigations_with_one_writer(bug,tmp_path):
    p=plan(bug,'wide uncertain retry failure',agent='replay',write_paths=['charge.py'],execute_local=True,max_parallel=2)
    assert {n['id'] for n in p['dag']['nodes']} >= {'impact','acceptance'}
    result=execute(bug,p,replay(bug,tmp_path))
    assert result['effective_verdict']=='PASS',result
    assert result['nodes']['impact']['artifact']['actor']=='builtin-static'
    assert result['nodes']['acceptance']['artifact']['test_files']
    assert sum(n['mode']=='write' for n in result['nodes'].values())==1


def test_explicit_resume_preserves_failure_and_carries_budget(bug,tmp_path,monkeypatch):
    from repo_ai.mission import verification
    original=verification.observe
    def incomplete(*a,**k):
        result=original(*a,**k)
        result['complete']=False
        return result
    p=plan(bug,'repair charge.py',agent='replay',write_paths=['charge.py'],execute_local=True)
    artifact=replay(bug,tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(verification,'observe',incomplete)
        first=execute(bug,p,artifact)
    assert first['state']=='INCONCLUSIVE'
    second=execute(bug,p,artifact,resume=True)
    assert second['effective_verdict']=='PASS',second
    assert second['id']==first['id']
    assert second['carried_seconds']>=first['seconds_used']
    assert second['attempts'][0]['passport']['verdict']=='INCONCLUSIVE'
    assert second['seconds_used']>first['seconds_used']


def test_blocked_plan_names_the_changed_paths(bug):
    (bug/'.gitignore').write_text('.repo-ai/\n')
    (bug/'charge.py').write_text('human edit\n')
    for i in range(6):
        (bug/f'note{i}.txt').write_text('x\n')
    p=plan(bug,'repair charge.py',agent='replay',write_paths=['charge.py'])
    assert p['decision']=='BLOCKED'
    assert '.gitignore' in p['why'] and 'charge.py' in p['why'] and 'and 3 more' in p['why']
    assert 'commit or stash' in p['why']


def test_dirty_checkout_refusal_names_the_paths(tmp_path):
    import subprocess as sp
    from repo_ai.mission.runtime import identity
    sp.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'a.py').write_text('x = 1\n')
    sp.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    sp.run(['git', '-C', str(tmp_path), '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', 'commit', '-qm', 'i'],
           check=True)
    (tmp_path / '__pycache__').mkdir()
    (tmp_path / '__pycache__' / 'a.cpython-312.pyc').write_bytes(b'\0')
    with pytest.raises(ValueError, match=r'__pycache__/a\.cpython-312\.pyc'):
        identity(tmp_path, require_clean=True)
