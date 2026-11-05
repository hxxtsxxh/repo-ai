"""Real controller termination, honest ambiguous-phase blocking, no live model."""
import json
import os
import signal
import subprocess
import sys

import pytest
from conftest import cli_env
from test_mission_runtime import bug as bug_fixture, replay
from repo_ai.mission.ledger import Store
from repo_ai.mission.runtime import execute
from repo_ai.verify import isolate


@pytest.fixture
def bug(tmp_path):
    return bug_fixture.__wrapped__(tmp_path)


@pytest.mark.skipif(os.name!='posix',reason='SIGKILL recovery probe is POSIX-specific')
@pytest.mark.parametrize('phase',['PLANNED','edit'])
def test_controller_death_at_durable_boundaries(bug,tmp_path,phase):
    artifact=replay(bug,tmp_path)
    script='''
import os,signal,sys
from pathlib import Path
from repo_ai.mission.runtime import plan,execute
from repo_ai.mission.ledger import Store
root,artifact,phase=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
original=Store.save
def save(self,record):
    original(self,record)
    if ((phase=='PLANNED' and record['state']=='PLANNED') or
        (phase=='edit' and record.get('nodes',{}).get('edit',{}).get('status')=='RUNNING')):
        os.kill(os.getpid(),signal.SIGKILL)
Store.save=save
p=plan(root,'repair charge.py',agent='replay',write_paths=['charge.py'],execute_local=True)
execute(root,p,artifact)
'''
    result=subprocess.run([sys.executable,'-c',script,str(bug),str(artifact),phase],env=cli_env(),
                          capture_output=True,text=True,timeout=90)
    assert result.returncode==-signal.SIGKILL,result.stderr
    store=Store(bug)
    [path]=list(store.folder.glob('*.json'))
    old=store.load(path.stem)
    before=(bug/'charge.py').read_bytes()
    if phase=='PLANNED':
        resumed=execute(bug,old['plan'],artifact,resume=True)
        assert resumed['effective_verdict']=='PASS',resumed
        assert resumed['attempts'][0]['state']=='PLANNED'
        assert resumed['carried_seconds']>0
        assert resumed['cleanup_confirmed']
        assert not isolate.workspaces_root().joinpath(resumed['workspace']).exists()
    else:
        try:
            with pytest.raises(ValueError,match='unconfirmed cleanup'):
                execute(bug,old['plan'],artifact,resume=True)
        finally:
            # This test killed before writer dispatch, after completed observer cleanup.
            # Production conservatively refuses to infer that fact from RUNNING alone.
            workspace=old.get('workspace')
            if workspace:
                from pathlib import Path
                assert Path(workspace).name==workspace, 'workspace is persisted as a bare name, never a path'
                path=isolate.workspaces_root()/workspace
                assert path.name.startswith('mission-'+old['id']+'-')
                isolate._remove(path)
    assert (bug/'charge.py').read_bytes()==before


def test_copied_mission_cannot_cross_repository_boundary(bug,tmp_path):
    from repo_ai.mission.contracts import digest
    other=tmp_path/'other-zone'
    other.mkdir()
    a,b=Store(bug),Store(other)
    record={'id':'a'*24,'repository':a.repository,'state':'CREATED','events':[]}
    a.save(record)
    b.folder.mkdir(parents=True)
    b.path(record['id']).write_text(json.dumps({'schema':'repo-ai.mission-state/1','record':record,'sha256':digest(record)}))
    with pytest.raises(ValueError,match='boundary'):
        b.load(record['id'])
