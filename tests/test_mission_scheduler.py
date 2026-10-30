import threading
import time
import pytest
from repo_ai.mission.contracts import ExecutionDAG, Node
from repo_ai.mission.scheduler import run


def test_two_readers_overlap_then_one_writer_and_reverification():
    barrier=threading.Barrier(2)
    events=[]
    lock=threading.Lock()
    def read(name):
        def action():
            barrier.wait(timeout=2)
            with lock:
                events.append(name)
            return {'fact':name}
        return action
    def write():
        assert sorted(events)==['impact','tests']
        events.append('edit')
        return {'diff':'hash'}
    def verify():
        assert events[-1]=='edit'
        return {'checked':'merged candidate'}
    dag=ExecutionDAG([Node('impact','read'),Node('tests','read'),Node('edit','write',['impact','tests']),Node('verify','verify',['edit'])],2)
    records={}
    result=run(dag,{'impact':read('impact'),'tests':read('tests'),'edit':write,'verify':verify},records,
               deadline=time.monotonic()+5)
    assert all(n['status']=='SUCCEEDED' for n in result.values())
    assert len({n['artifact_sha256'] for n in result.values()})==4


def test_checkpoint_replay_never_reexecutes_a_completed_write():
    dag=ExecutionDAG([Node('edit','write')])
    records={}
    calls=[]
    actions={'edit':lambda: calls.append('edit') or {'diff':'a'}}
    run(dag,actions,records,deadline=time.monotonic()+5)
    run(dag,actions,records,deadline=time.monotonic()+5)
    assert calls==['edit']
    records['edit']['artifact']['diff']='tampered'
    with pytest.raises(ValueError,match='integrity'):
        run(dag,actions,records,deadline=time.monotonic()+5)


def test_interrupted_writer_is_not_retried_implicitly():
    with pytest.raises(ValueError,match='interrupted'):
        run(ExecutionDAG([Node('edit','write')]),{'edit':lambda:{}},
            {'edit':{'status':'RUNNING'}},deadline=time.monotonic()+5)


def test_deadline_cancellation_and_failure_stop_dependents():
    for condition in ('cancel','timeout','failure'):
        calls=[]
        def first(condition=condition, calls=calls):
            if condition=='failure':
                raise RuntimeError('reproduced fault')
            calls.append('first')
            return {}
        with pytest.raises((InterruptedError,TimeoutError,RuntimeError)):
            run(ExecutionDAG([Node('first','read'),Node('edit','write',['first'])]),
                {'first':first,'edit':lambda calls=calls:calls.append('edit') or {}},{},
                deadline=time.monotonic()+(-1 if condition=='timeout' else 5),
                cancelled=lambda condition=condition:condition=='cancel')
        assert 'edit' not in calls
