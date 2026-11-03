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


def test_per_test_record_names_the_changed_lines_each_test_ran(tmp_path):
    """C11: requirement-by-requirement mapping needs which changed lines each test ran, not only the union."""
    root = _repo(tmp_path, PY_AFTER, PY_TEST_BOTH)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert rec['assurance'] == 'FULL', rec
    assert rec['per_test_complete'] is True and rec['changed_outside_tests'] == []
    assert rec['per_test'] == {'test_m.py::test_neg': ['m.py:2', 'm.py:3'], 'test_m.py::test_pick': ['m.py:2']}, rec


def test_a_test_that_runs_no_changed_line_is_absent_from_the_per_test_record(tmp_path):
    other = PY_TEST_BOTH + '\n\ndef test_unrelated():\n    assert 1 + 1 == 2\n'
    root = _repo(tmp_path, PY_AFTER, other)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert 'test_m.py::test_unrelated' not in rec['per_test'] and 'test_m.py::test_neg' in rec['per_test']


def test_per_test_is_off_by_default_and_import_time_lines_are_outside_any_test(tmp_path):
    """Review of #118: a changed module constant runs at import, outside every test window."""
    before, after = 'LIMIT = 5\n\n\ndef cap(x):\n    return min(x, LIMIT)\n', 'LIMIT = 3\n\n\ndef cap(x):\n    return min(x, LIMIT)\n'
    root = _repo(tmp_path, after, 'from m import cap\n\n\ndef test_cap():\n    assert cap(9) == 3\n')
    plain = exercise.measure(root, 'python -m pytest -q', _diff('m.py', before, after))
    assert plain['assurance'] == 'FULL' and 'per_test' not in plain
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', before, after), per_test=True)
    assert rec['per_test'] == {} and rec['changed_outside_tests'] == ['m.py:1'], rec


def test_a_spawned_process_makes_the_per_test_record_incomplete(tmp_path):
    test = ('import subprocess, sys\nfrom m import pick\n\n\ndef test_cli():\n'
            '    subprocess.run([sys.executable, "-c", "pass"], check=True)\n    assert pick(-2) == 2\n')
    root = _repo(tmp_path, PY_AFTER, test)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert rec['per_test_complete'] is False, rec


def test_multiprocessing_and_an_early_stop_make_the_per_test_record_incomplete(tmp_path):
    """Re-review: multiprocessing children (no audit event) and --maxfail early stops were missed."""
    mp_test = ('import multiprocessing as mp\nfrom m import pick\n\n\ndef test_pool():\n'
               '    with mp.get_context("spawn").Pool(1) as pool:\n        assert pool.map(abs, [-1]) == [1]\n'
               '    assert pick(-2) == 2\n')
    (tmp_path / 'a').mkdir()
    root = _repo(tmp_path / 'a', PY_AFTER, mp_test)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert rec['per_test_complete'] is False, rec


def test_a_per_test_timeout_leaves_the_assurance_as_measured(tmp_path, monkeypatch):
    """The per-test run is a second run in the time left: if it cannot finish, only its record is missing."""
    root = _repo(tmp_path, PY_AFTER, PY_TEST_BOTH)
    from types import SimpleNamespace
    real_run = exercise.execute.Executor.run

    def maybe_timeout(self, argv, *a, **k):
        if '--per-test' in argv:
            return SimpleNamespace(timed_out=True, exit_code=-1)
        return real_run(self, argv, *a, **k)
    monkeypatch.setattr(exercise.execute.Executor, 'run', maybe_timeout)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert rec['assurance'] == 'FULL' and 'per_test' not in rec and rec['per_test_reason'] == 'the per-test run timed out'


def test_an_early_stop_makes_the_per_test_record_incomplete(tmp_path):
    (tmp_path / 'pytest.ini').write_text('[pytest]\naddopts = --maxfail=1\n')
    failing_first = 'from m import pick\n\n\ndef test_a_fails():\n    assert False\n\n\ndef test_neg():\n    assert pick(-2) == 2\n'
    root = _repo(tmp_path, PY_AFTER, failing_first)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert rec['per_test_complete'] is False, rec


def test_an_exception_in_the_per_test_run_keeps_the_assurance(tmp_path, monkeypatch):
    """Final check of #118: anything the second run raises (e.g. an oversized record) only leaves the record out."""
    root = _repo(tmp_path, PY_AFTER, PY_TEST_BOTH)
    real = exercise.isolate.read_inside

    def oversized(base, rel, limit):
        if rel.endswith('trace-per-test.json'):
            raise ValueError('record too large')
        return real(base, rel, limit)
    monkeypatch.setattr(exercise.isolate, 'read_inside', oversized)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    assert rec['assurance'] == 'FULL' and 'per_test' not in rec and rec['per_test_reason'].startswith('the per-test run failed')


def test_last_failed_in_addopts_does_not_shrink_the_per_test_run(tmp_path):
    (tmp_path / 'pytest.ini').write_text('[pytest]\naddopts = --lf\n')
    root = _repo(tmp_path, PY_AFTER, PY_TEST_BOTH)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', PY_BEFORE, PY_AFTER), per_test=True)
    # the cache is off in the per-test run, so --lf either runs everything or stops it as a usage error (incomplete)
    assert rec['assurance'] == 'FULL'
    assert rec.get('per_test_complete') is not True or set(rec['per_test']) == {'test_m.py::test_neg', 'test_m.py::test_pick'}
