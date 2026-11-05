"""A valid DAG must also retain the evaluator's required causal ordering."""
import pytest
from repo_ai.mission import runtime
from test_mission_runtime import bug as bug_fixture, replay


@pytest.mark.parametrize('change', ['edit-first', 'review-first', 'foreign-owner'])
def test_structurally_valid_but_unsafe_dag_refused(tmp_path, monkeypatch, change):
    bug = bug_fixture.__wrapped__(tmp_path)
    planned = runtime.plan(bug, 'repair', agent='replay', execute_local=True,
                           write_paths=['charge.py'])
    nodes = {n['id']: n for n in planned['dag']['nodes']}
    if change == 'edit-first':
        nodes['edit']['depends_on'] = ['context']
    elif change == 'review-first':
        nodes['review']['depends_on'] = ['context']
    else:
        nodes['edit']['owner'] = 'unapproved-specialist'
    touched = []
    monkeypatch.setattr(runtime.isolate, 'materialize_commit', lambda *a, **k: touched.append(True))
    with pytest.raises(ValueError, match='ordering|ownership'):
        runtime.execute(bug, planned, replay(bug, tmp_path))
    assert not touched
