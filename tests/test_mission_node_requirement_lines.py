"""C11 end to end for `node --test` (needs a host sandbox): a real mission with a frozen requirements declaration
records, per test FILE, the changed lines each file ran alone under V8 coverage; `repo-ai coverage ID` shows them per
requirement, labelled as per-file attribution."""
import hashlib
import json
import shutil

import pytest
from conftest import _git, run_cli

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')

BEFORE = 'exports.pick = (x) => x;\n'
AFTER = 'exports.pick = (x) => {\n  if (x < 0) {\n    return -x;\n  }\n  return x;\n};\n'
HEAD = "const t = require('node:test');\nconst assert = require('node:assert');\nconst { pick } = require('./pick.js');\n"


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / 'proj'
    (root / 'test').mkdir(parents=True)
    (root / 'pick.js').write_text(BEFORE)
    (root / 'package.json').write_text('{"name": "proj", "version": "1.0.0"}\n')
    (root / 'test' / 'neg.test.js').write_text(HEAD.replace('./pick.js', '../pick.js')
                                               + "t('negative', () => assert.equal(pick(-2), 2));\n"
                                               + "t('zero', () => assert.equal(pick(0), 0));\n")
    (root / 'test' / 'pos.test.js').write_text(HEAD.replace('./pick.js', '../pick.js')
                                               + "t('positive', () => assert.equal(pick(2), 2));\n")
    (root / 'test' / 'plain.test.js').write_text("const t = require('node:test');\nt('arithmetic', () => {});\n")
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')
    return root


def _replay(root, tmp_path):
    p = tmp_path / 'proposal.json'
    p.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'simulated fixture agent', 'edits': [
        {'path': 'pick.js', 'before_sha256': hashlib.sha256(BEFORE.encode()).hexdigest(), 'after': AFTER}]}))
    return p


def test_node_mission_coverage_shows_changed_lines_per_test_file(project, tmp_path):
    from repo_ai.mission import coverage as cov
    from repo_ai.mission.runtime import execute, plan, status
    f = tmp_path / 'req.json'
    f.write_text(json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'negative input is negated', 'kind': 'change', 'tests': ['test/neg.test.js::negative']},
        {'text': 'zero stays zero', 'kind': 'preserve', 'tests': ['test/neg.test.js::zero']},
        {'text': 'positive input unchanged', 'kind': 'preserve', 'tests': ['test/pos.test.js::positive']}]}))
    p = plan(project, 'Make pick return the magnitude of a negative input', agent='replay', write_paths=['pick.js'],
             execute_local=True, command='node --test')
    p['requirements'] = cov.freeze(f)  # as `do --requirements FILE` does: the per-file record is made only then
    result = execute(project, p, _replay(project, tmp_path))
    assert result['effective_verdict'] == 'PASS', result.get('reasons')
    ex = status(project, result['id'])['exercise']
    assert ex['assurance'] == 'FULL' and ex['per_test_granularity'] == 'file', ex
    assert ex['per_test_complete'] is True and ex['per_test_unavailable'] == {}, ex
    assert sorted(ex['per_test_measured']) == ['test/neg.test.js', 'test/plain.test.js', 'test/pos.test.js']
    assert ex['per_test'] == {'test/neg.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:3', 'pick.js:5'],
                              'test/pos.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:5']}, ex

    out = run_cli(project, 'coverage', result['id'], '--json')
    data = json.loads(out.stdout)
    assert data['headline'] == 'ACCEPTANCE_MAPPED_ALL', data
    rows = {r['text']: r for r in data['requirements']}
    # per FILE: `zero` ran pick(0) only, yet it is credited with line 3, which only `negative` (same file) ran
    assert rows['negative input is negated']['changed_lines_run'] == rows['zero stays zero']['changed_lines_run'] \
        == ['pick.js:1', 'pick.js:2', 'pick.js:3', 'pick.js:5']
    assert rows['positive input unchanged']['changed_lines_run'] == ['pick.js:1', 'pick.js:2', 'pick.js:5']
    by = data['changed_lines_by_requirement']
    assert by['granularity'] == 'file' and by['complete'] is True and by['run_by_tests_of_no_requirement'] == []

    text = run_cli(project, 'coverage', result['id']).stdout
    assert 'its test file(s) ran 4 changed line(s) [per test file: test/neg.test.js]' in text
    assert 'Node attribution is per test FILE, not per test' in text
