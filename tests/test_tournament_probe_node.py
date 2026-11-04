"""`shortlist --probe` with a JavaScript probe on a Node project (tournament-live-v1's Node abstentions could not be
probed: a probe ran Python only)."""
from __future__ import annotations

import hashlib
import json
import shutil

import pytest
from conftest import _git
from repo_ai.mission import probe as pr
from repo_ai.mission import shortlist as sl
from repo_ai.mission.tournament import inspect_comparison

pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='needs node')

BASE = 'function charge(amount, retries) { return amount * (retries + 1); }\nmodule.exports = { charge };\n'
GOOD = 'function charge(amount, retries) { return amount; }\nmodule.exports = { charge };\n'
CLAMP = 'function charge(amount, retries) { return Math.max(amount, 0); }\nmodule.exports = { charge };\n'


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'fakehome'))
    (tmp_path / 'fakehome').mkdir(exist_ok=True)


def _tournament(tmp_path, capsys):
    from repo_ai.cli import main
    root = tmp_path / 'proj'
    root.mkdir()
    (root / 'charge.js').write_text(BASE)
    (root / 'charge.test.js').write_text("const test = require('node:test');\nconst assert = require('node:assert');\n"
                                         "const { charge } = require('./charge.js');\n"
                                         "test('retry', () => { assert.strictEqual(charge(10, 2), 10); });\n")
    (root / 'package.json').write_text('{"name": "proj", "version": "1.0.0"}\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'base')
    props = []
    for name, after in (('a', GOOD), ('b', CLAMP)):
        p = tmp_path / f'{name}.json'
        p.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'fixture', 'edits': [
            {'path': 'charge.js', 'before_sha256': hashlib.sha256(BASE.encode()).hexdigest(), 'after': after}]}))
        props += ['--candidate', str(p)]
    main(['do', 'Repair duplicate charge', '-C', str(root), '--agent', 'replay', *props, '--run',
          '--allow-write', 'charge.js', '--test-command', 'node --test', '--json'])
    report = json.loads(capsys.readouterr().out)
    assert report['winner'] is None and [c['verdict'] for c in report['candidates']] == ['PASS', 'PASS'], report
    return root, sl.build(root, inspect_comparison(root, report['id']))


def test_a_javascript_probe_tells_node_candidates_apart(tmp_path, capsys):
    root, out = _tournament(tmp_path, capsys)
    probe = tmp_path / 'probe.js'
    probe.write_text("const { charge } = require('./charge.js');\nfor (const a of [10, 0, -5]) console.log(a, charge(a, 1));\n")
    rep = pr.run_probe(root, out, probe)
    assert rep['verdict'] == 'DIFFER', rep['reasons']
    assert rep['first_difference']['line'] == 3 and {rep['first_difference']['a'], rep['first_difference']['b']} == {'-5 -5', '-5 0'}


def test_a_probe_in_another_language_than_the_tests_is_refused(tmp_path, capsys):
    root, out = _tournament(tmp_path, capsys)
    probe = tmp_path / 'probe.py'
    probe.write_text('print(1)\n')
    rep = pr.run_probe(root, out, probe)
    assert rep['verdict'] == 'INCONCLUSIVE' and 'cannot run in this mission' in rep['reasons'][0], rep


def test_an_unknown_probe_extension_is_refused(tmp_path):
    probe = tmp_path / 'probe.rb'
    probe.write_text('puts 1\n')
    with pytest.raises(ValueError, match='Python'):
        pr.read_probe(probe)
