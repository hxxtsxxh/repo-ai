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


def test_added_lines_numbers_lines_by_lf_only_as_git_does():
    """splitlines() would also split on CR, U+2028, form feed, ...: line numbers after them would shift."""
    diff = ('diff --git a/m.js b/m.js\n--- a/m.js\n+++ b/m.js\n@@ -1,2 +1,4 @@\n'
            ' const a = "x\u2028y\x0cz\x85w\x1c";\r\n+const b = 1;\r\n+const c = "\rq";\n const d = 3;\n+const e = 4;\n')
    assert exercise.added_lines(diff) == {'m.js': {2, 3, 5}}


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


def test_a_shared_fixtures_setup_lines_are_credited_to_every_test_that_uses_it(tmp_path):
    """Queue row 32: a session fixture is set up during the first test that needs it; the second user ran that code
    too, through the fixture, and is now credited with it."""
    before = 'def make(x):\n    return x\n'
    after = 'def make(x):\n    y = x * 2\n    return y\n'
    (tmp_path / 'conftest.py').write_text('import pytest\nfrom m import make\n\n\n@pytest.fixture(scope="session")\n'
                                         'def app():\n    return make(2)\n')
    tests = ('def test_first(app):\n    assert app == 4\n\n\ndef test_req(app):\n    assert app > 0\n\n\n'
             'def test_unrelated():\n    assert True\n')
    root = _repo(tmp_path, after, tests)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', before, after), per_test=True)
    assert rec['per_test'].get('test_m.py::test_first') == ['m.py:2', 'm.py:3'], rec
    assert rec['per_test'].get('test_m.py::test_req') == ['m.py:2', 'm.py:3'], rec
    assert 'test_m.py::test_unrelated' not in rec['per_test']


BRANCH_BEFORE = 'def make(x):\n    return x\n'
BRANCH_AFTER = 'def make(x):\n    if x == 1:\n        return "one"\n    return "other"\n'


def _fixture_case(tmp_path, conftest, tests):
    (tmp_path / 'conftest.py').write_text('import pytest\nfrom m import make\n\n\n' + conftest)
    root = _repo(tmp_path, BRANCH_AFTER, tests)
    return exercise.measure(root, 'python -m pytest -q', _diff('m.py', BRANCH_BEFORE, BRANCH_AFTER), per_test=True)


def test_each_run_of_a_parametrized_shared_fixture_is_credited_separately(tmp_path):
    rec = _fixture_case(tmp_path, '@pytest.fixture(scope="session", params=[1, 2])\ndef app(request):\n'
                                  '    return make(request.param)\n', 'def test_a(app):\n    assert app\n')
    assert rec['per_test']['test_m.py::test_a[1]'] == ['m.py:2', 'm.py:3'], rec['per_test']
    assert rec['per_test']['test_m.py::test_a[2]'] == ['m.py:2', 'm.py:4'], rec['per_test']


def test_a_class_scoped_fixture_credits_each_class_its_own_run(tmp_path):
    rec = _fixture_case(tmp_path, '@pytest.fixture(scope="class")\ndef app(request):\n    return make(request.cls.mode)\n',
                        'class TestA:\n    mode = 1\n\n    def test_x(self, app):\n        assert app == "one"\n\n\n'
                        'class TestB:\n    mode = 2\n\n    def test_y(self, app):\n        assert app == "other"\n')
    assert rec['per_test']['test_m.py::TestA::test_x'] == ['m.py:2', 'm.py:3'], rec['per_test']
    assert rec['per_test']['test_m.py::TestB::test_y'] == ['m.py:2', 'm.py:4'], rec['per_test']


def test_a_skipped_test_is_not_credited_with_a_fixture_it_never_ran_with(tmp_path):
    rec = _fixture_case(tmp_path, '@pytest.fixture(scope="session")\ndef app():\n    return make(1)\n',
                        'import pytest\n\n\ndef test_used(app):\n    assert app\n\n\n'
                        '@pytest.mark.skip(reason="x")\ndef test_skipped(app):\n    pass\n')
    assert 'test_m.py::test_used' in rec['per_test'] and 'test_m.py::test_skipped' not in rec['per_test']


def test_getfixturevalue_and_override_chains_are_credited(tmp_path):
    rec = _fixture_case(tmp_path, '@pytest.fixture(scope="session")\ndef app():\n    return make(1)\n',
                        'import pytest\n\n\n@pytest.fixture(scope="module")\ndef app(app):\n    return app\n\n\n'
                        'def test_override(app):\n    assert app\n\n\n'
                        'def test_dynamic(request):\n    assert request.getfixturevalue("app")\n')
    assert rec['per_test'].get('test_m.py::test_override') == ['m.py:2', 'm.py:3'], rec['per_test']
    assert rec['per_test'].get('test_m.py::test_dynamic') == ['m.py:2', 'm.py:3'], rec['per_test']


def test_a_second_shared_fixture_running_the_same_lines_is_still_seen(tmp_path):
    rec = _fixture_case(tmp_path, '@pytest.fixture(scope="session")\ndef db():\n    return make(1)\n\n\n'
                                  '@pytest.fixture(scope="module")\ndef client():\n    return make(1)\n',
                        'def test_1(db, client):\n    assert db\n\n\ndef test_2(client):\n    assert client\n')
    assert rec['per_test'].get('test_m.py::test_2') == ['m.py:2', 'm.py:3'], rec['per_test']


def test_direct_lines_fill_the_cap_before_fixture_credit(monkeypatch):
    monkeypatch.setattr(exercise, 'MAX_PER_TEST', 2)
    trace = {'per_test_complete': True, 'per_test': {'t::direct': {'m.py': [2]}},
             'fixture_lines': {'conftest::app::session#1': {'m.py': [3]}},
             'fixture_uses': {f't::user{i}': ['conftest::app::session#1'] for i in range(5)}}
    out, complete, _ = exercise._per_test(trace, {'m.py': {2, 3}})
    assert out['t::direct'] == ['m.py:2'] and len(out) == 2 and complete is False


def test_an_override_that_ignores_its_parent_is_not_credited_with_the_parents_lines(tmp_path):
    """Re-review of #121: another test left the parent's run cached; the override never ran it."""
    (tmp_path / 'conftest.py').write_text('import pytest\nfrom m import make\n\n\n@pytest.fixture(scope="session")\n'
                                         'def app():\n    return make(1)\n')
    (tmp_path / 'test_b.py').write_text('import pytest\n\n\n@pytest.fixture(scope="module")\ndef app():\n'
                                       '    return "x"\n\n\ndef test_b1(app):\n    assert app == "x"\n')
    root = _repo(tmp_path, BRANCH_AFTER, 'def test_a1(app):\n    assert app == "one"\n')
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', BRANCH_BEFORE, BRANCH_AFTER), per_test=True)
    assert rec['per_test'].get('test_m.py::test_a1') == ['m.py:2', 'm.py:3'], rec['per_test']
    assert 'test_b.py::test_b1' not in rec['per_test'], rec['per_test']


def test_lines_of_a_shared_fixture_no_test_ran_with_count_as_outside_any_test(tmp_path):
    rec = _fixture_case(tmp_path, '@pytest.fixture(scope="session")\ndef app():\n    make(1)\n    pytest.skip("not here")\n',
                        'def test_a(app):\n    pass\n')
    assert rec['per_test'] == {} and rec['changed_outside_tests'] == ['m.py:2', 'm.py:3'], rec


# -- C11, node: the per-test record per test FILE (each file alone under V8 coverage) ------------------------------

JS_BEFORE = 'exports.pick = (x) => x;\n'
JS_AFTER = 'exports.pick = (x) => {\n  if (x < 0) {\n    return -x;\n  }\n  return x;\n};\n'
JS_HEAD = "const t = require('node:test');\nconst assert = require('node:assert');\n"
JS_TESTS = {
    'pick.test.js': JS_HEAD + "const { pick } = require('./pick.js');\nt('positive', () => assert.equal(pick(2), 2));\n",
    'neg.test.js': JS_HEAD + "const { pick } = require('./pick.js');\nt('negative', () => assert.equal(pick(-2), 2));\n",
    'other.test.js': JS_HEAD + "t('unrelated', () => assert.equal(1 + 1, 2));\n",
}


def _node_repo(tmp_path, extra=None):
    root = tmp_path / 'njs'
    root.mkdir()
    (root / 'pick.js').write_text(JS_AFTER)
    (root / 'package.json').write_text('{"name": "njs", "version": "1.0.0"}\n')
    for name, text in {**JS_TESTS, **(extra or {})}.items():
        (root / name).write_text(text)
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'candidate applied')
    return root


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_per_file_record_names_the_changed_lines_each_test_file_ran(tmp_path):
    root = _node_repo(tmp_path)
    diff = _diff('pick.js', JS_BEFORE, JS_AFTER)
    plain = exercise.measure(root, 'node --test', diff)
    assert plain['assurance'] == 'FULL' and 'per_test' not in plain, plain
    rec = exercise.measure(root, 'node --test', diff, per_test=True)
    assert rec['assurance'] == 'FULL' and rec['changed_lines'] == 4, rec
    assert rec['per_test_granularity'] == 'file'
    assert rec['per_test'] == {'neg.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:3'],
                               'pick.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:5']}, rec
    assert sorted(rec['per_test_measured']) == ['neg.test.js', 'other.test.js', 'pick.test.js']
    assert rec['per_test_unavailable'] == {} and rec['per_test_complete'] is True
    assert 'changed_outside_tests' not in rec, 'module load belongs to the test file that ran it'


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_malformed_coverage_makes_that_file_unavailable_never_not_run(tmp_path):
    junk = JS_HEAD + ("const { pick } = require('./pick.js');\nconst fs = require('node:fs');\n"
                      "const path = require('node:path');\n"
                      "t('writes junk', () => { pick(-1); "
                      "fs.writeFileSync(path.join(process.env.NODE_V8_COVERAGE, 'junk.json'), '{'); });\n")
    root = _node_repo(tmp_path, {'junk.test.js': junk})
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True)
    assert rec['assurance'] == 'FULL', rec
    assert rec['per_test_unavailable'] == {'junk.test.js': 'a coverage file is not valid JSON'}, rec
    assert 'junk.test.js' not in rec['per_test'] and 'junk.test.js' not in rec['per_test_measured']
    assert rec['per_test_complete'] is False and set(rec['per_test']) == {'neg.test.js', 'pick.test.js'}


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_test_files_past_the_cap_or_the_time_left_are_not_measured(tmp_path, monkeypatch):
    root = _node_repo(tmp_path)
    monkeypatch.setattr(exercise, 'MAX_NODE_TEST_FILES', 2)
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True)
    assert rec['per_test_complete'] is False and len(rec['per_test_measured']) == 2, rec
    assert rec['per_test_reason'].startswith('only 2 of 3 test files were run')
    monkeypatch.setattr(exercise, 'MAX_NODE_TEST_FILES', 200)
    real = exercise._per_file_node_run
    monkeypatch.setattr(exercise, '_per_file_node_run', lambda *a: real(*a[:6], 0.0, *a[7:]))  # no time left
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True)
    assert rec['assurance'] == 'FULL' and rec['per_test'] == {} and rec['per_test_measured'] == [], rec
    assert set(rec['per_test_unavailable'].values()) == {'no time was left for its run'}
    assert rec['per_test_complete'] is False


def test_more_than_forty_changed_lines_are_all_kept_and_a_cut_record_is_incomplete(monkeypatch):
    """Review of #146: the stored record was cut to 40 lines (sorted as text), so lines past it read as run only by
    other tests, while the record still said complete."""
    many = {'a.py': list(range(1, 51)), 'b.py': [1, 2]}
    eligible = {'a.py': set(range(1, 51)), 'b.py': {1, 2}}
    out, complete, cut = exercise._per_test({'per_test_complete': True, 'per_test': {'t::x': many}}, eligible)
    assert len(out['t::x']) == 52 and out['t::x'][-2:] == ['b.py:1', 'b.py:2'] and complete is True and cut == {}
    assert out['t::x'][:3] == ['a.py:1', 'a.py:2', 'a.py:3'] and out['t::x'][9] == 'a.py:10', 'by number, not as text'
    monkeypatch.setattr(exercise, 'MAX_STORED_LINES', 30)
    out, complete, cut = exercise._per_test({'per_test_complete': True, 'per_test': {'t::x': many}}, eligible)
    assert len(out['t::x']) == 30 and complete is False and cut == {'t::x': 52}


def _many_lines_repo(tmp_path):
    root = tmp_path / 'many'
    root.mkdir()
    (root / 'a.js').write_text(''.join(f'exports.a{i} = {i};\n' for i in range(50)))
    (root / 'b.js').write_text('exports.b = (x) => {\n  const y = x * 2;\n  return y;\n};\n')
    (root / 'package.json').write_text('{"name": "p", "version": "1.0.0"}\n')
    (root / 'x.test.js').write_text("const t = require('node:test');\nconst assert = require('node:assert');\n"
                                    "require('./a.js');\nconst { b } = require('./b.js');\n"
                                    "t('b doubles', () => assert.equal(b(2), 4));\n")
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'c')
    diff = ('diff --git a/a.js b/a.js\n' + _diff('a.js', 'exports.a0 = 0;\n', (root / 'a.js').read_text())
            + 'diff --git a/b.js b/b.js\n' + _diff('b.js', 'exports.b = (x) => x;\n', (root / 'b.js').read_text()))
    return root, diff


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_per_file_record_keeps_more_than_forty_lines_and_flags_a_cut(tmp_path, monkeypatch):
    root, diff = _many_lines_repo(tmp_path)
    rec = exercise.measure(root, 'node --test', diff, per_test=True)
    lines = rec['per_test']['x.test.js']
    assert rec['changed_lines'] == 52 and len(lines) == 52 and lines[-3:] == ['b.js:1', 'b.js:2', 'b.js:3'], rec
    assert rec['per_test_complete'] is True and 'per_test_truncated' not in rec
    monkeypatch.setattr(exercise, 'MAX_STORED_LINES', 10)
    rec = exercise.measure(root, 'node --test', diff, per_test=True)
    assert rec['per_test_complete'] is False and rec['per_test_truncated'] == {'x.test.js': 52}, rec


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_one_file_failing_to_run_leaves_the_others_measured(tmp_path, monkeypatch):
    """Review of #146: an exception in one file's run (here from file_argv) dropped every file's record."""
    root = _node_repo(tmp_path)
    from repo_ai.verify.runner import RunnerError, TestRunner
    real = TestRunner.file_argv

    def argv(self, test):
        if test == 'neg.test.js':
            raise RunnerError('refused')
        return real(self, test)
    monkeypatch.setattr(TestRunner, 'file_argv', argv)
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True)
    assert rec['per_test_unavailable'] == {'neg.test.js': 'its run could not be measured: RunnerError'}, rec
    assert set(rec['per_test']) == {'pick.test.js'} and rec['per_test_complete'] is False


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_declared_files_run_first_and_a_failing_file_still_counts(tmp_path, monkeypatch):
    failing = JS_HEAD + "const { pick } = require('./pick.js');\nt('fails', () => assert.equal(pick(-3), 0));\n"
    root = _node_repo(tmp_path, {'zfail.test.js': failing})
    monkeypatch.setattr(exercise, 'MAX_NODE_TEST_FILES', 2)
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True,
                           declared_files=['zfail.test.js', 'pick.test.js'])
    assert rec['per_test_measured'] == ['pick.test.js', 'zfail.test.js'], rec
    # exit 1 (a failing test) still writes valid coverage
    assert rec['per_test']['zfail.test.js'] == ['pick.js:1', 'pick.js:2', 'pick.js:3'], rec


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_assurance_counts_utf16_units_so_emoji_cannot_hide_an_unrun_branch(tmp_path):
    """Review of #146 (pre-existing): offsets read as code points shifted the count-0 block of line 3 off it, so the
    measurement said FULL."""
    before = 'exports.a = (x) => 1;\n'
    for name, lead in (('emoji', '\U0001F600' * 12), ('plain', 'x')):
        after = f'const s = "{lead}";\nexports.a = (x) => {{\n  if (x) n();\n                    return 1;\n}};\n'
        root = tmp_path / name
        root.mkdir()
        (root / 'm.js').write_text(after, encoding='utf-8')
        (root / 'm.test.js').write_text(JS_HEAD + "const { a } = require('./m.js');\nt('a', () => assert.equal(a(0), 1));\n")
        _git(root, 'init', '-q')
        _git(root, 'add', '.')
        _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'c')
        rec = exercise.measure(root, 'node --test', _diff('m.js', before, after))
        assert rec['assurance'] == 'PARTIAL' and rec['unexercised'] == ['m.js:3'], (name, rec)


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_each_file_gets_a_capped_share_of_the_time_left(tmp_path, monkeypatch):
    root = _node_repo(tmp_path)
    seen = []

    def fake(ex, runner, test, texts, eligible, timeout_s, deadline):
        seen.append((test, timeout_s))
        from repo_ai.mission.v8lines import Unavailable
        raise Unavailable('stub')
    monkeypatch.setattr(exercise, '_node_file_lines', fake)
    real = exercise._per_file_node_run
    monkeypatch.setattr(exercise, '_per_file_node_run', lambda *a: real(*a[:6], 300.0, *a[7:]))
    exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True,
                     declared_files=['pick.test.js'])
    assert seen[0][0] == 'pick.test.js', 'declared files first'
    assert exercise.NODE_FILE_MIN_TIMEOUT <= seen[0][1] <= 2 * 300.0 / 3 + 1, seen


def test_pytest_per_test_record_keeps_more_than_forty_lines(tmp_path):
    before = 'def pick(x):\n    return x\n'
    after = 'def pick(x):\n' + ''.join(f'    v{i} = x + {i}\n' for i in range(45)) + '    return x\n'
    root = _repo(tmp_path, after, PY_TEST)
    rec = exercise.measure(root, 'python -m pytest -q', _diff('m.py', before, after), per_test=True)
    lines = rec['per_test']['test_m.py::test_pick']
    assert len(lines) == rec['changed_lines'] == 45 and lines[-1] == 'm.py:46', rec
    assert rec['per_test_complete'] is True and 'per_test_truncated' not in rec


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_a_file_left_out_of_a_full_record_is_unavailable_not_zero_lines(tmp_path, monkeypatch):
    """Re-review of #146: past the whole-record cap a file's lines were dropped while it stayed measured."""
    root = _node_repo(tmp_path)
    monkeypatch.setattr(exercise, 'MAX_RECORD_LINES', 4)
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), per_test=True)
    assert set(rec['per_test']) == {'neg.test.js'} and 'pick.test.js' not in rec['per_test_measured'], rec
    assert rec['per_test_unavailable'] == {'pick.test.js': 'its 3 changed lines were cut from the record (over 4 in all)'}
    assert rec['per_test_truncated'] == {'pick.test.js': 3} and rec['per_test_complete'] is False


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_assurance_holds_for_a_suite_of_many_test_files(tmp_path):
    """Re-review of #146: a whole suite writes one coverage file per test file (entries differ by call counts); 70
    files went UNMEASURED past a 64-entry cap, and about 125 would pass a 32 MiB total. 130 keep the real result."""
    before = 'exports.f = (x) => x;\n'
    after = 'exports.f = (x) => {\n  if (x > 1000) {\n    return -1;\n  }\n  return x;\n};\n'
    root = tmp_path / 'suite'
    (root / 'test').mkdir(parents=True)
    (root / 'lib.js').write_text(after)
    (root / 'package.json').write_text('{"name": "p", "version": "1.0.0"}\n')
    for i in range(130):
        (root / 'test' / f't{i}.test.js').write_text(
            f"const t = require('node:test');\nconst {{ f }} = require('../lib.js');\n"
            f"t('t{i}', () => {{ for (let k = 0; k < {i}; k++) f(k); }});\n")
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'c')
    rec = exercise.measure(root, 'node --test', _diff('lib.js', before, after), timeout_s=300)
    assert rec['assurance'] == 'PARTIAL' and rec['unexercised'] == ['lib.js:2', 'lib.js:3'], rec
