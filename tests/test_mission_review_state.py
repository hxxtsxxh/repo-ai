"""Independent review: reproduce controller races and fail-open contract limits.

These tests simulate only concurrency/control-plane events. They do not claim a
live provider or a real observed test pass.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager

import pytest

from repo_ai.mission import cli, runtime
from repo_ai.mission.contracts import ExecutionDAG, Node
from repo_ai.mission.ledger import Store, transition
from test_mission_runtime import bug as bug_fixture, replay


@pytest.fixture
def bug(tmp_path):
    return bug_fixture.__wrapped__(tmp_path)


@pytest.mark.parametrize('action', ['cancel', 'resume'])
def test_reader_reloads_state_after_acquiring_lock_before_transition(bug, monkeypatch, action):
    store = Store(bug)
    state = {'id': 'a' * 24, 'state': 'CREATED', 'events': [],
             'repository': store.repository, 'source': runtime.identity(bug),
             'kernel': runtime.kernel_identity()}
    for phase in ('PLANNED', 'READY', 'RUNNING'):
        transition(state, phase)
    store.save(state)

    completed = copy.deepcopy(state)
    for phase in ('VERIFYING', 'REVIEWING'):
        transition(completed, phase)
    completed['passport'] = {'verdict': 'PASS', 'observations': ['baseline', 'candidate', 'regression']}
    completed['preserved_controller_artifact'] = 'result published while command waited for lock'
    transition(completed, 'COMPLETE')

    @contextmanager
    def controller_finishes_before_lock(*args, **kwargs):
        store.save(completed)
        yield True

    monkeypatch.setattr(cli, 'file_lock', controller_finishes_before_lock)
    args = argparse.Namespace(path=str(bug), id=state['id'], action=action,
                              run=False, replay=None, json=True)
    cli.cmd_mission(args)
    actual = store.load(state['id'])
    assert actual['state'] == 'COMPLETE', 'stale reader must not overwrite the completed controller result'
    assert actual['preserved_controller_artifact'] == completed['preserved_controller_artifact']
    assert actual['events'] == completed['events']


def test_child_dag_cannot_exceed_approved_contract_parallelism(bug, tmp_path, monkeypatch):
    planned = runtime.plan(bug, 'repair charge.py', agent='replay', write_paths=['charge.py'],
                           execute_local=True, max_parallel=1)
    planned['dag']['max_parallel'] = 4
    touched_workspace = []

    def forbidden_workspace(*args, **kwargs):
        touched_workspace.append(True)
        raise RuntimeError('test sentinel: workspace should not be reached for an invalid child budget')

    monkeypatch.setattr(runtime.isolate, 'materialize_commit', forbidden_workspace)
    with pytest.raises(ValueError, match='parallel|budget|bound'):
        runtime.execute(bug, planned, replay(bug, tmp_path))
    assert not touched_workspace


@pytest.mark.parametrize('owner', ['', 1, True, None])
def test_dag_owner_is_a_nonempty_typed_identifier(owner):
    with pytest.raises(ValueError, match='owner|node'):
        ExecutionDAG([Node('edit', 'write', owner=owner)]).validate()


@pytest.mark.parametrize('action', ['cancel', 'resume'])
def test_cross_zone_cancel_or_resume_cannot_mutate_mission_state(bug, action):
    store = Store(bug)
    state = {'id': 'b' * 24, 'state': 'CREATED', 'events': [],
             'repository': store.repository, 'source': runtime.identity(bug),
             'kernel': runtime.kernel_identity(),
             'contract': {'zone': 'other-zone', 'policy_sha256': '0' * 64}}
    for phase in ('PLANNED', 'READY', 'RUNNING'):
        transition(state, phase)
    store.save(state)
    args = argparse.Namespace(path=str(bug), id=state['id'], action=action,
                              run=False, replay=None, json=True)
    with pytest.raises(ValueError, match='zone changed'):
        cli.cmd_mission(args)
    assert store.load(state['id'])['state'] == 'RUNNING'
    assert not (store.folder / (state['id'] + '.cancel')).exists()


def test_resume_requires_existing_mission_record(bug, tmp_path):
    planned = runtime.plan(bug, 'repair charge.py', agent='replay', write_paths=['charge.py'],
                           execute_local=True)
    with pytest.raises(ValueError, match='no prior|missing|not found|resume'):
        runtime.execute(bug, planned, replay(bug, tmp_path), resume=True)
