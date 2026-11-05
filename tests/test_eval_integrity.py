"""The independent grader must grade the selected artifact, not an answer key."""
import hashlib

import pytest

from repo_ai.mission import eval_protocol as ev


def test_grader_materializes_selected_diff(tmp_path, monkeypatch):
    fx = ev._setup_python_retry_fixture(tmp_path)
    repo = fx['repo']
    source = repo / fx['source']
    source.write_text(fx['superficial'])
    patch = ev.git(repo, 'diff')  # production stores stripped Git stdout
    source.write_text(fx['original'])
    state = {'effective_verdict': 'PASS', 'freshness': 'fresh', 'diff': patch,
             'diff_sha256': hashlib.sha256(patch.encode()).hexdigest()}
    monkeypatch.setattr(ev, 'status', lambda root, mid: state, raising=False)
    selected = ev._selected_candidate_source(repo, 'winner', fx['source'])
    assert selected == fx['superficial']
    assert selected != fx['correct']
    assert source.read_text() == fx['original']
    state['diff_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='integrity'):
        ev._selected_candidate_source(repo, 'winner', fx['source'])


def test_naive_intentional_edit_is_not_unscoped(tmp_path):
    fx = ev._setup_python_retry_fixture(tmp_path)
    row = ev._run_naive_smoke_trial(fx)
    assert row['smoke_test_passed']
    assert not row['unscoped_file_touch']
    assert row['false_pass']


def test_protocol_is_draft_until_manifest_frozen():
    spec = ev.build_preregistered_study_spec()
    assert spec['registration_status'] == 'DRAFT_REQUIRES_FROZEN_TASK_MANIFEST'
    assert spec['primary_endpoint'] == 'paired_independently_verified_completion'
    assert spec['live_runs_authorized'] is False
    assert spec['minimum_repository_clusters'] == {'python': 2, 'node_or_typescript': 2}
