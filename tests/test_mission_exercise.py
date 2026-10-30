"""Change-exercise assurance: did the frozen tests run the lines the candidate changed?"""
import difflib
import shutil

import pytest
from conftest import _git
from repo_ai.mission import exercise, runtime

PY_BEFORE = 'def pick(x):\n    return x\n'
PY_AFTER = 'def pick(x):\n    if x < 0:\n        return -x\n    return x\n'
PY_TEST = 'from m import pick\n\n\ndef test_pick():\n    assert pick(2) == 2\n'
PY_TEST_BOTH = PY_TEST + '\n\ndef test_neg():\n    assert pick(-2) == 2\n'


def _diff(path, before, after):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f'a/{path}', f'b/{path}'))


def _repo(tmp_path, source, test):
    (tmp_path / 'm.py').write_text(source)
    (tmp_path / 'test_m.py').write_text(test)
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '-qm', 'candidate applied')
    return tmp_path


def test_added_lines_tracks_new_side_numbers_and_ignores_deletions():
    diff = _diff('m.py', PY_BEFORE, PY_AFTER)
    assert exercise.added_lines(diff) == {'m.py': {2, 3}}
    assert exercise.added_lines(_diff('m.py', PY_AFTER, PY_BEFORE)) == {}
    assert exercise.added_lines('') == {}


def test_added_lines_new_file_and_dev_null():
    diff = 'diff --git a/n.py b/n.py\n--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,2 @@\n+x = 1\n+y = 2\n'
    assert exercise.added_lines(diff) == {'n.py': {1, 2}}


def test_unexercised_branch_is_reported_partial(tmp_path):
    root = _repo(tmp_path, PY_AFTER, PY_TEST)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER))
    assert rec['assurance'] == 'PARTIAL', rec
    assert rec['unexercised'] == ['m.py:3'] and rec['changed_lines'] == 2


def test_fully_exercised_change_is_full(tmp_path):
    root = _repo(tmp_path, PY_AFTER, PY_TEST_BOTH)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER))
    assert rec['assurance'] == 'FULL', rec
    assert rec['unexercised'] == []


def test_comment_only_change_has_no_executable_lines(tmp_path):
    after = PY_BEFORE + '# note\n'
    root = _repo(tmp_path, after, PY_TEST)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, after))
    assert rec['assurance'] == 'NO_EXECUTABLE_CHANGE', rec


def test_unsupported_language_or_empty_diff_is_not_claimed(tmp_path):
    root = _repo(tmp_path, PY_AFTER, PY_TEST)
    assert exercise.measure(root, 'python -m pytest -q', '')['assurance'] == 'NO_EXECUTABLE_CHANGE'
    md = 'diff --git a/R.md b/R.md\n--- a/R.md\n+++ b/R.md\n@@ -1 +1,2 @@\n x\n+y\n'
    assert exercise.measure(root, 'python -m pytest -q', md)['assurance'] == 'NO_EXECUTABLE_CHANGE'


def test_measurement_failure_is_unmeasured_never_an_exception(tmp_path):
    root = _repo(tmp_path, PY_AFTER, PY_TEST)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER).replace('m.py', 'gone.py'))
    assert rec['assurance'] in {'UNMEASURED', 'NO_EXECUTABLE_CHANGE'}


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_unexercised_collision_branch_is_partial_and_full_when_tested(tmp_path):
    src_before = 'exports.f = (a) => a;\n'
    src_after = 'exports.f = (a) => {\n  let n = a;\n  while (n > 5) n--;\n  return n;\n};\n'
    test_low = "const t = require('node:test'); const assert = require('node:assert');\nconst {f} = require('./m.js');\nt('f', () => assert.equal(f(1), 1));\n"
    test_high = test_low + "t('g', () => assert.equal(f(9), 5));\n"
    for name, test, expected in (('low', test_low, 'PARTIAL'), ('high', test_high, 'FULL')):
        root = tmp_path / name
        root.mkdir()
        (root / 'm.js').write_text(src_after)
        (root / 'm.test.js').write_text(test)
        _git(root, 'init', '-q')
        _git(root, 'add', '.')
        _git(root, 'commit', '-qm', 'c')
        rec = exercise.measure(root, 'node --test', _diff('m.js', src_before, src_after))
        assert rec['assurance'] == expected, (name, rec)


def test_exercise_notes_describe_limits_without_changing_verdict():
    assert runtime.exercise_notes(None) == []
    assert runtime.exercise_notes({'assurance': 'FULL'}) == []
    note = runtime.exercise_notes({'assurance': 'PARTIAL', 'unexercised': ['m.py:3'], 'unexercised_count': 1, 'changed_lines': 3})[0]
    assert '1 of 3 changed executable lines' in note and 'm.py:3' in note
    assert 'could not be measured' in runtime.exercise_notes({'assurance': 'UNMEASURED', 'reason': 'timeout'})[0]


def test_tracer_lines_are_opt_in():
    from repo_ai.verify.testmap import TRACER
    text = TRACER.read_text()
    assert '--lines' in text and 'sys.monitoring' in text


def _bug(tmp_path):
    root = tmp_path / 'bug'
    root.mkdir()
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return amount * (retries + 1)\n')
    (root / 'test_charge.py').write_text('from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'base')
    return root


def _replay(root, tmp_path, after):
    import hashlib
    import json
    p = tmp_path / 'proposal.json'
    p.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'simulated fixture agent', 'edits': [
        {'path': 'charge.py', 'before_sha256': hashlib.sha256((root / 'charge.py').read_bytes()).hexdigest(), 'after': after}]}))
    return p


def test_mission_pass_with_unexercised_branch_keeps_verdict_but_discloses_limit(tmp_path):
    root = _bug(tmp_path)
    after = 'def charge(amount, retries):\n    if amount < 0:\n        raise ValueError("negative")\n    return amount\n'
    planned = runtime.plan(root, 'Fix duplicate charge in charge.py', agent='replay', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, _replay(root, tmp_path, after))
    assert result['passport']['verdict'] == 'PASS', result
    assert result['exercise']['assurance'] == 'PARTIAL'
    assert any('never run by the frozen tests' in note for note in result['passport']['untested'])


def test_mission_pass_with_fully_exercised_change_has_no_exercise_limit(tmp_path):
    root = _bug(tmp_path)
    planned = runtime.plan(root, 'Fix duplicate charge in charge.py', agent='replay', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, _replay(root, tmp_path, 'def charge(amount, retries):\n    return amount\n'))
    assert result['passport']['verdict'] == 'PASS', result
    assert result['exercise']['assurance'] == 'FULL'
    assert not any('never run by the frozen tests' in note for note in result['passport']['untested'])


def test_explain_and_cli_surface_the_limit(tmp_path, capsys):
    from repo_ai.mission import cli, explanation
    root = _bug(tmp_path)
    after = 'def charge(amount, retries):\n    if amount < 0:\n        raise ValueError("negative")\n    return amount\n'
    planned = runtime.plan(root, 'Fix duplicate charge in charge.py', agent='replay', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, _replay(root, tmp_path, after))
    report = explanation.explain(root, result['id'])
    assert report['change_exercise'] == 'PARTIAL'
    assert 'never run by the frozen tests' in explanation.render(report)
    cli._emit(runtime.status(root, result['id']), type('A', (), {'json': False, 'format': ''})())
    assert 'Limit: ' in capsys.readouterr().out
