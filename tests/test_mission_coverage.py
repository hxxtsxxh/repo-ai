"""Requirement -> acceptance coverage from declared mappings and observed per-test outcomes (never a correctness claim)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from repo_ai.mission import coverage as cov

ROOT = Path(__file__).resolve().parents[1]


def decl(*reqs):
    return {'requirements': list(reqs), 'sha256': cov.digest(list(reqs))}


def req(text, tests, kind='change'):
    return {'text': text, 'kind': kind, 'tests': tests}


def _node_outcomes(slug_js: Path, tests_dir: Path, tmp: Path) -> dict[str, str]:
    """Run the REAL abc-v1 node-slug visible tests against one slug.js and return {test name: pass|fail}."""
    work = tmp / slug_js.parent.name
    (work / 'test').mkdir(parents=True)
    shutil.copy(slug_js, work / 'slug.js')
    for f in tests_dir.glob('*.js'):
        shutil.copy(f, work / 'test' / f.name)
    out = subprocess.run(['node', '--test', '--test-reporter=tap'], cwd=work, capture_output=True, text=True, timeout=60).stdout
    return {m.group(2): 'pass' if m.group(1) == 'ok' else 'fail'
            for m in re.finditer(r'^(ok|not ok) \d+ - (.+?)(?: #.*)?$', out, re.M)}


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_node_slug_false_green_with_real_controls(tmp_path):
    """Recorded abc-v1 FALSE_GREEN, reproduced with the real files: base FAILs, decoy and reference both pass every
    visible test, so the oracle cannot tell them apart. The unmapped requirement is what exposes that."""
    task = ROOT / 'benchmarks' / 'abc-v1' / 'tasks' / 'node-slug'
    tests = task / 'repo' / 'test'
    base = _node_outcomes(task / 'repo' / 'slug.js', tests, tmp_path / 'base')
    decoy = _node_outcomes(task / 'decoy' / 'slug.js', tests, tmp_path / 'decoy')
    ref = _node_outcomes(task / 'reference' / 'slug.js', tests, tmp_path / 'ref')
    assert len(base) == 4 and set(base) == set(decoy) == set(ref)
    assert 'fail' in base.values() and set(decoy.values()) == {'pass'} == set(ref.values()), (base, decoy, ref)
    d = decl(req('slugify strips leading and trailing dashes', ['trims leading and trailing separators']),
             req('duplicate titles get -2, -3 suffixes', ['uniqueSlugs suffixes duplicates with -2, -3']),
             req('slugs are unique across the whole returned list', []))
    for name, cand in (('decoy', decoy), ('reference', ref)):
        out = cov.assess(d, base, cand, verdict='PASS', freshness='fresh')
        assert out['headline'] == 'ACCEPTANCE_PARTIAL', name        # the SAME honest answer for the wrong and the right patch
        assert out['requirements'][2]['status'] == 'UNMAPPED' and out['follow_up_test_needed']
    # Adding the hidden-requirement test (disclosed here only because abc-v1 is development evidence) separates them.
    hidden = task / 'hidden' / 'test'
    both = tmp_path / 'both_tests'
    both.mkdir()
    for f in (*tests.glob('*.js'), *hidden.glob('*.js')):
        shutil.copy(f, both / f.name)
    clause = 'a generated suffix never collides with a literal title'
    b2, d2, r2 = (_node_outcomes(task / sub / 'slug.js', both, tmp_path / ('x' + sub)) for sub in ('repo', 'decoy', 'reference'))
    assert d2[clause] == 'fail' and r2[clause] == 'pass'
    d3 = decl(req('slugs are unique across the whole returned list', [clause]))
    assert cov.assess(d3, b2, d2, verdict='PASS', freshness='fresh')['requirements'][0]['status'] == 'FAILING'
    assert cov.assess(d3, b2, r2, verdict='PASS', freshness='fresh')['requirements'][0]['status'] == 'VERIFIED_FAIL_TO_PASS'


def test_new_unseen_controls_a_test_that_already_passed_cannot_verify_a_change():
    d = decl(req('refuse negative amounts', ['t::test_negative']))
    out = cov.assess(d, {'t::test_negative': 'pass'}, {'t::test_negative': 'pass'}, verdict='PASS', freshness='fresh')
    assert out['requirements'][0]['status'] == 'NOT_DISCRIMINATING' and out['headline'] == 'ACCEPTANCE_UNMAPPED'


def test_mixed_fail_and_pass_baseline_is_not_discriminating():
    d = decl(req('x', ['t::a', 't::b']))
    out = cov.assess(d, {'t::a': 'fail', 't::b': 'pass'}, {'t::a': 'pass', 't::b': 'pass'}, verdict='PASS', freshness='fresh')
    assert out['requirements'][0]['status'] == 'NOT_DISCRIMINATING'
    # the explanation names which test moved and which could not (abc-v5 calibration finding)
    detail = out['requirements'][0]['detail']
    assert 'cannot show this change: t::b' in detail and 'passes now: t::a' in detail and 'preserve' in detail


def test_preserve_requirements():
    d = decl(req('deposit unchanged', ['t::dep'], 'preserve'))
    assert cov.assess(d, {'t::dep': 'pass'}, {'t::dep': 'pass'}, verdict='PASS', freshness='fresh')['headline'] == 'ACCEPTANCE_MAPPED_ALL'
    regressed = cov.assess(d, {'t::dep': 'pass'}, {'t::dep': 'fail'}, verdict='FAIL', freshness='fresh')
    assert regressed['requirements'][0]['status'] == 'FAILING' and regressed['headline'] == 'INCONCLUSIVE'
    broken = cov.assess(d, {'t::dep': 'fail'}, {'t::dep': 'pass'}, verdict='PASS', freshness='fresh')
    assert broken['requirements'][0]['status'] == 'NOT_DISCRIMINATING'


def test_missing_ambiguous_and_suffix_test_ids():
    b = {'a.py::t1': 'fail', 'a.py::T::t2': 'fail', 'b.py::t2': 'fail'}
    c = {k: 'pass' for k in b}
    d = decl(req('exact', ['a.py::t1']), req('suffix', ['t1']), req('ambiguous', ['t2']), req('ghost', ['nope']))
    out = cov.assess(d, b, c, verdict='PASS', freshness='fresh')
    assert [r['status'] for r in out['requirements']] == ['VERIFIED_FAIL_TO_PASS', 'VERIFIED_FAIL_TO_PASS',
                                                         'MISSING_TEST', 'MISSING_TEST']
    assert 'ambiguous' in out['requirements'][2]['detail']
    assert 'not collected' in out['requirements'][3]['detail']


def test_stale_or_non_pass_mission_never_reports_mapped():
    d = decl(req('x', ['t::a']))
    ok = ({'t::a': 'fail'}, {'t::a': 'pass'})
    assert cov.assess(d, *ok, verdict='PASS', freshness='stale')['headline'] == 'STALE'
    assert cov.assess(d, *ok, verdict='INCONCLUSIVE', freshness='fresh')['headline'] == 'INCONCLUSIVE'
    assert cov.assess(d, *ok, verdict='PASS', freshness='not checked')['headline'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('payload', [
    'not json', '[]', '{}',
    json.dumps({'schema': 'other/1', 'requirements': [{'text': 'x'}]}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': []}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [{'text': '', 'tests': []}]}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [{'text': 'x', 'kind': 'bogus'}]}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [{'text': 'x', 'tests': 'a'}]}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [{'text': 'x', 'tests': [3]}]}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [{'text': 'x', 'extra': 1}]}),
    json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [{'text': 'x'}] * 51}),
])
def test_malformed_declarations_are_refused(tmp_path, payload):
    f = tmp_path / 'r.json'
    f.write_text(payload)
    with pytest.raises(ValueError):
        cov.load_requirements(f)


def test_symlinked_or_oversized_declaration_is_refused(tmp_path):
    real = tmp_path / 'real.json'
    real.write_text('{}')
    link = tmp_path / 'link.json'
    link.symlink_to(real)
    with pytest.raises(ValueError):
        cov.load_requirements(link)
    big = tmp_path / 'big.json'
    big.write_text(' ' * (cov.MAX_BYTES + 1))
    with pytest.raises(ValueError, match='too large'):
        cov.load_requirements(big)


def test_render_states_follow_up_and_limits():
    d = decl(req('a thing nobody tested', []))
    text = cov.render(cov.assess(d, {}, {}, verdict='PASS', freshness='fresh'))
    assert 'UNMAPPED' in text and 'Follow-up acceptance test needed' in text and 'CLAIM_UNVERIFIED' in text


def test_render_shows_a_pytest_identity_once():
    # recorded keys are file::runner-id, and pytest's id already starts with the file
    key = 'tests/test_money.py::tests/test_money.py::test_sum'
    d = decl(req('parts sum to the total', ['tests/test_money.py::test_sum']))
    report = cov.assess(d, {key: 'fail'}, {key: 'pass'}, verdict='PASS', freshness='fresh')
    assert report['requirements'][0]['observed'][0]['test'] == key  # JSON keeps the full key
    text = cov.render(report)
    assert 'tests/test_money.py::test_sum: baseline fail -> candidate pass' in text
    assert 'test_money.py::tests/' not in text
    assert cov.display_test_id('test_a.py::A.test_x') == 'test_a.py::A.test_x'  # unittest-style ids unchanged


def test_not_discriminating_with_a_missing_baseline_names_the_test():
    # adversarial review finding G: no empty list in the explanation
    d = decl(req('x', ['t::a', 't::b']))
    out = cov.assess(d, {'t::a': 'fail'}, {'t::a': 'pass', 't::b': 'pass'}, verdict='PASS', freshness='fresh')
    detail = out['requirements'][0]['detail']
    assert out['requirements'][0]['status'] == 'NOT_DISCRIMINATING' and 'no baseline observation' in detail
    assert 't::b' in detail and ': .' not in detail


# C11 review (2026-11-02): false greens and unnoted obligations
NEG = decl(req('reject negative amounts', ['tests/test_a.py::test_neg']))
B = {'tests/test_a.py::tests/test_a.py::test_neg': 'fail'}
C = {'tests/test_a.py::tests/test_a.py::test_neg': 'pass'}


@pytest.mark.parametrize('freshness,verdict,label', [('stale', 'PASS', 'UNVERIFIED_STALE'),
                                                     ('fresh', 'FAIL', 'UNVERIFIED_INCONCLUSIVE'),
                                                     ('fresh', 'BLOCKED', 'UNVERIFIED_INCONCLUSIVE')])
def test_rows_are_not_verified_when_the_run_is_stale_or_not_a_pass(freshness, verdict, label):
    out = cov.assess(NEG, B, C, verdict=verdict, freshness=freshness)
    row = out['requirements'][0]
    assert row['status'] == label and row['observed_status'] == 'VERIFIED_FAIL_TO_PASS'
    assert 'VERIFIED_FAIL_TO_PASS' not in out['counts'] and out['follow_up_test_needed'] == ['reject negative amounts']


def test_changed_code_no_test_ran_is_an_obligation():
    ex = {'assurance': 'PARTIAL', 'changed_lines': 3, 'unexercised': ['src/bank.py:41', 'src/audit.py:10'],
          'unexercised_count': 2}
    out = cov.assess(NEG, B, C, verdict='PASS', freshness='fresh', exercise=ex)
    assert out['headline'] == 'ACCEPTANCE_PARTIAL' and out['changed_code']['assurance'] == 'PARTIAL'
    assert any('src/bank.py:41' in o for o in out['other_obligations'])
    assert 'Not covered by any requirement: changed code no frozen test ran' in cov.render(out)
    full = cov.assess(NEG, B, C, verdict='PASS', freshness='fresh', exercise={'assurance': 'FULL', 'changed_lines': 3})
    assert full['headline'] == 'ACCEPTANCE_MAPPED_ALL' and full['other_obligations'] == []
    unknown = cov.assess(NEG, B, C, verdict='PASS', freshness='fresh', exercise={'assurance': 'NOT_RECORDED'})
    assert unknown['headline'] == 'ACCEPTANCE_PARTIAL' and 'not measured' in unknown['other_obligations'][0]


def test_pre_existing_failures_of_a_scoped_mission_are_named():
    out = cov.assess(NEG, B, C, verdict='PASS', freshness='fresh', exercise={'assurance': 'FULL'},
                     pre_existing=['tests/test_b.py::tests/test_b.py::test_limit'])
    assert out['headline'] == 'ACCEPTANCE_PARTIAL'
    assert out['other_obligations'] == ['failures accepted as pre-existing in this scoped mission: '
                                        'tests/test_b.py::test_limit']


def test_a_bare_name_matched_to_another_file_is_flagged():
    d = decl(req('new parser keeps old results', ['test_parse'], 'preserve'))
    both = {'tests/test_new_parser.py::<module skipped>': 'skip', 'tests/test_legacy.py::tests/test_legacy.py::test_parse': 'pass'}
    row = cov.assess(d, both, both, verdict='PASS', freshness='fresh')['requirements'][0]
    assert row['observed'][0]['matched'] == 'suffix'
    assert 'matched by name, check it is the intended test: test_parse -> tests/test_legacy.py::test_parse' in row['detail']


def test_one_test_for_several_requirements_is_flagged():
    d = decl(req('reject negative', ['t::neg']), req('reject over limit', ['t::neg']))
    out = cov.assess(d, {'t::neg': 'fail'}, {'t::neg': 'pass'}, verdict='PASS', freshness='fresh')
    assert out['shared_tests'] == {'t::neg': ['reject negative', 'reject over limit']}
    assert 'One test, 2 requirements: t::neg' in cov.render(out)


def test_a_failure_is_not_hidden_by_a_skipped_neighbour():
    d = decl(req('deposit unchanged', ['t::a', 't::b'], 'preserve'))
    out = cov.assess(d, {'t::a': 'skip', 't::b': 'pass'}, {'t::a': 'skip', 't::b': 'fail'}, verdict='FAIL', freshness='fresh')
    assert out['requirements'][0]['status'] == 'FAILING'


def test_the_canonical_file_and_test_form_is_not_flagged():
    """Review of #94: `tests/test_a.py::test_neg` names `tests/test_a.py::tests/test_a.py::test_neg` exactly."""
    row = cov.assess(NEG, B, C, verdict='PASS', freshness='fresh', exercise={'assurance': 'FULL'})['requirements'][0]
    assert row['observed'][0]['matched'] == 'exact' and 'matched by name' not in row['detail']


# -- C11: requirement by requirement, the changed lines its own tests ran (pytest per-test line record) ------------

T_NEG, T_PICK, T_OTHER = 'm_test.py::m_test.py::test_neg', 'm_test.py::m_test.py::test_pick', 'm_test.py::m_test.py::test_other'
C11_EXERCISE = {'assurance': 'FULL', 'changed_lines': 2, 'unexercised': [], 'unexercised_count': 0, 'per_test_complete': True,
            'per_test': {'m_test.py::test_neg': ['m.py:2', 'm.py:3'], 'm_test.py::test_pick': ['m.py:2']}}


def test_each_requirement_names_the_changed_lines_its_tests_ran():
    d = decl(req('negative input is negated', ['m_test.py::test_neg']),
             req('positive input unchanged', ['m_test.py::test_pick'], kind='preserve'))
    out = cov.assess(d, {T_NEG: 'fail', T_PICK: 'pass'}, {T_NEG: 'pass', T_PICK: 'pass'}, verdict='PASS', freshness='fresh',
                     exercise=C11_EXERCISE)
    rows = {r['text']: r for r in out['requirements']}
    assert rows['negative input is negated']['changed_lines_run'] == ['m.py:2', 'm.py:3']
    assert rows['positive input unchanged']['changed_lines_run'] == ['m.py:2']
    assert out['headline'] == 'ACCEPTANCE_MAPPED_ALL', out
    by = out['changed_lines_by_requirement']
    assert {k: by[k] for k in ('measured', 'complete', 'changed_lines', 'run_by_tests_of_no_requirement',
                               'run_outside_any_test')} == {'measured': True, 'complete': True, 'changed_lines': 2,
                                                            'run_by_tests_of_no_requirement': [],
                                                            'run_outside_any_test': []}
    assert 'its tests ran 2 changed line(s): m.py:2, m.py:3' in cov.render(out)


def test_a_requirement_whose_tests_ran_no_changed_line_is_informational_only():
    """Review of #118: attribution is by time window (import-time and shared-fixture code is credited to no test or
    to another test), so it never becomes an obligation, a status or a headline change."""
    d = decl(req('negative input is negated', ['m_test.py::test_other']))
    ex = {**C11_EXERCISE, 'changed_outside_tests': ['m.py:1']}
    out = cov.assess(d, {T_OTHER: 'fail', T_NEG: 'fail'}, {T_OTHER: 'pass', T_NEG: 'pass'}, verdict='PASS',
                     freshness='fresh', exercise=ex)
    [row] = out['requirements']
    assert row['status'] == 'VERIFIED_FAIL_TO_PASS' and row['changed_lines_run'] == []
    assert out['headline'] == 'ACCEPTANCE_MAPPED_ALL' and out['other_obligations'] == []
    by = out['changed_lines_by_requirement']
    assert by['run_by_tests_of_no_requirement'] == ['m.py:2', 'm.py:3'] and by['run_outside_any_test'] == ['m.py:1']
    text = cov.render(out)
    assert 'outside any test (import, collection): m.py:1' in text and 'time window' in text


def test_without_a_per_test_record_the_mapping_is_not_measured():
    d = decl(req('negative input is negated', ['m_test.py::test_neg']))
    plain = {k: v for k, v in C11_EXERCISE.items() if k not in ('per_test', 'per_test_complete')}
    out = cov.assess(d, {T_NEG: 'fail'}, {T_NEG: 'pass'}, verdict='PASS', freshness='fresh', exercise=plain)
    assert out['changed_lines_by_requirement']['measured'] is False
    assert 'changed_lines_run' not in out['requirements'][0]
    assert 'Changed lines by requirement: not measured' in cov.render(out)
    no_code = cov.assess(d, {T_NEG: 'fail'}, {T_NEG: 'pass'}, verdict='PASS', freshness='fresh',
                         exercise={**C11_EXERCISE, 'changed_lines': 0})
    assert no_code['changed_lines_by_requirement']['reason'] == 'no executable line changed'


# -- C11, node: the same fields, per test FILE (`per_test_granularity: "file"`) -----------------------------------

N_NEG, N_POS, N_POS2 = 'neg.test.js::negative', 'pick.test.js::positive', 'pick.test.js::positive again'
N_OTHER = 'deep/other.test.js::suite > unrelated'
NODE_EXERCISE = {'assurance': 'FULL', 'changed_lines': 4, 'unexercised': [], 'unexercised_count': 0,
                 'per_test_granularity': 'file', 'per_test_complete': True,
                 'per_test_measured': ['deep/other.test.js', 'neg.test.js', 'pick.test.js', 'side.test.js'],
                 'per_test_unavailable': {},
                 'per_test': {'neg.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:3'],
                              'pick.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:5'],
                              'side.test.js': ['pick.js:1', 'pick.js:6']}}
N_BASE = {N_NEG: 'fail', N_POS: 'pass', N_POS2: 'pass', N_OTHER: 'pass'}
N_CAND = {N_NEG: 'pass', N_POS: 'pass', N_POS2: 'pass', N_OTHER: 'pass'}


def test_node_lines_are_credited_to_every_test_in_the_file_and_labelled_per_file():
    d = decl(req('negative input is negated', ['neg.test.js::negative']),
             req('positive input unchanged', ['pick.test.js::positive'], kind='preserve'),
             req('positive again unchanged', ['pick.test.js::positive again'], kind='preserve'),
             req('unrelated still works', [N_OTHER], kind='preserve'))
    out = cov.assess(d, N_BASE, N_CAND, verdict='PASS', freshness='fresh', exercise=NODE_EXERCISE)
    rows = {r['text']: r for r in out['requirements']}
    assert rows['negative input is negated']['changed_lines_run'] == ['pick.js:1', 'pick.js:2', 'pick.js:3']
    # two tests in one file: both get the file's lines, including those only the other test may have run
    assert rows['positive input unchanged']['changed_lines_run'] == rows['positive again unchanged']['changed_lines_run'] \
        == ['pick.js:1', 'pick.js:2', 'pick.js:5']
    assert rows['unrelated still works']['changed_lines_run'] == [] and 'changed_lines_unavailable' not in rows[
        'unrelated still works'], 'measured and ran nothing is not unavailable'
    assert rows['negative input is negated']['changed_lines_test_files'] == ['neg.test.js']
    by = out['changed_lines_by_requirement']
    assert by['measured'] is True and by['granularity'] == 'file' and by['complete'] is True
    assert by['run_by_tests_of_no_requirement'] == ['pick.js:6'], 'only side.test.js, which holds no declared test, ran it'
    assert 'run_outside_any_test' not in by
    assert out['headline'] == 'ACCEPTANCE_MAPPED_ALL', 'informational only'
    text = cov.render(out)
    assert 'its test file(s) ran 3 changed line(s) [per test file: neg.test.js]: pick.js:1, pick.js:2, pick.js:3' in text
    assert 'Changed lines run only by test files that hold no declared test (1): pick.js:6' in text
    assert 'Changed lines by requirement (Node, per test file): Node attribution is per test FILE, not per test' in text
    assert 'time window' not in text


def test_node_unavailable_coverage_is_named_with_its_reason_not_shown_as_zero_lines():
    ex = {**NODE_EXERCISE, 'per_test_complete': False, 'per_test_measured': ['pick.test.js'],
          'per_test_unavailable': {'neg.test.js': 'a coverage file is not valid JSON'},
          'per_test': {'pick.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:5']}}
    d = decl(req('negative input is negated', ['neg.test.js::negative']),
             req('both', ['neg.test.js::negative', 'pick.test.js::positive']),
             req('never measured', [N_OTHER], kind='preserve'))
    base = {**N_BASE, 'pick.test.js::positive': 'fail'}
    out = cov.assess(d, base, N_CAND, verdict='PASS', freshness='fresh', exercise=ex)
    rows = {r['text']: r for r in out['requirements']}
    neg = rows['negative input is negated']
    assert neg['changed_lines_unavailable'] == {'neg.test.js': 'a coverage file is not valid JSON'}
    assert rows['both']['changed_lines_run'] == ['pick.js:1', 'pick.js:2', 'pick.js:5']
    assert rows['both']['changed_lines_unavailable'] == {'neg.test.js': 'a coverage file is not valid JSON'}
    assert rows['never measured']['changed_lines_unavailable'] == {'deep/other.test.js': 'not measured'}
    by = out['changed_lines_by_requirement']
    assert by['complete'] is False and by['unavailable_test_files'] == {'neg.test.js': 'a coverage file is not valid JSON'}
    text = cov.render(out)
    neg_block = text.split('"negative input is negated"')[1].split('[')[0]
    assert 'changed lines unavailable for its test file neg.test.js: a coverage file is not valid JSON' in neg_block
    assert 'ran 0 changed line' not in neg_block
    assert 'Changed lines unavailable for 1 test file(s): neg.test.js (a coverage file is not valid JSON)' in text
    assert 'the record is incomplete' in text


def test_node_without_a_per_file_record_says_why():
    d = decl(req('negative input is negated', ['neg.test.js::negative']))
    ex = {k: v for k, v in NODE_EXERCISE.items() if not k.startswith('per_test')}
    out = cov.assess(d, N_BASE, N_CAND, verdict='PASS', freshness='fresh', exercise=ex)
    assert 'pytest and node --test missions' in out['changed_lines_by_requirement']['reason']
    ex['per_test_reason'] = 'no changed JavaScript file'
    out = cov.assess(d, N_BASE, N_CAND, verdict='PASS', freshness='fresh', exercise=ex)
    assert out['changed_lines_by_requirement']['reason'] == 'not measured: no changed JavaScript file'


def test_lines_only_undeclared_tests_ran_carry_a_caveat_when_the_record_is_incomplete():
    """Review of #146: a cut or unavailable declared record can make a line look run only by other tests."""
    d = decl(req('negative input is negated', ['neg.test.js::negative']))
    ex = {**NODE_EXERCISE, 'per_test_complete': False, 'per_test_truncated': {'neg.test.js': 2500},
          'per_test': {**NODE_EXERCISE['per_test'], 'side.test.js': ['pick.js:10', 'pick.js:9']}}
    out = cov.assess(d, N_BASE, N_CAND, verdict='PASS', freshness='fresh', exercise=ex)
    by = out['changed_lines_by_requirement']
    assert by['run_by_tests_of_no_requirement'] == ['pick.js:5', 'pick.js:9', 'pick.js:10'], 'by number'
    assert 'may have run some of them too' in cov.render(out)
    pytest_ex = {**C11_EXERCISE, 'per_test_complete': False}
    text = cov.render(cov.assess(decl(req('x', ['m_test.py::test_pick'])), {T_PICK: 'fail', T_NEG: 'fail'},
                                 {T_PICK: 'pass', T_NEG: 'pass'}, verdict='PASS', freshness='fresh', exercise=pytest_ex))
    assert 'a declared test may have run some of them too' in text


def test_a_pytest_test_left_out_of_a_full_record_is_unavailable_not_zero_lines():
    ex = {**C11_EXERCISE, 'per_test_complete': False, 'per_test_truncated': {'m_test.py::test_pick': 3000},
          'per_test': {'m_test.py::test_neg': ['m.py:2', 'm.py:3']}}
    out = cov.assess(decl(req('positive', ['m_test.py::test_pick'], kind='preserve')), {T_PICK: 'pass'},
                     {T_PICK: 'pass'}, verdict='PASS', freshness='fresh', exercise=ex)
    [row] = out['requirements']
    assert row['changed_lines_unavailable'] == {'m_test.py::test_pick': 'its changed lines were cut from the record'}
    assert 'changed lines unavailable for its test m_test.py::test_pick' in cov.render(out)


# -- container missions: the image is the only thing a read-only command cannot check -------------------------------

DIGEST = 'sha256:' + 'c' * 64


def _state(**over):
    from repo_ai.mission.runtime import IMAGE_UNCHECKED
    decl_ = cov._validated({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'negative input is negated', 'kind': 'change', 'tests': ['m_test.py::test_neg']}]})
    state = {'id': 'm1', 'state': 'COMPLETE', 'passport': {'verdict': 'PASS'}, 'freshness': 'not checked',
             'freshness_reasons': [IMAGE_UNCHECKED], 'effective_verdict': 'INCONCLUSIVE',
             'baseline': {'outcomes': {T_NEG: 'fail'}},
             'candidate': {'outcomes': {T_NEG: 'pass'}, 'executor': {
                 'backend': 'podman', 'image': 'localhost/deps:1@' + DIGEST, 'image_digest': DIGEST}},
             'exercise': dict(C11_EXERCISE),
             'plan': {'requirements': {'requirements': decl_['requirements'], 'sha256': decl_['sha256']}}}
    state.update(over)
    return state


def _for(monkeypatch, tmp_path, state, decl_=None):
    from repo_ai.mission import runtime
    monkeypatch.setattr(runtime, 'status', lambda root, mission: state)
    return cov.for_mission(tmp_path, 'm1', decl_)


def test_a_container_mission_whose_only_open_point_is_the_image_reaches_its_observed_status(monkeypatch, tmp_path):
    """C11 study: the image of a container mission is never re-checked by a read-only command, so every requirement
    was UNVERIFIED_INCONCLUSIVE and the headline INCONCLUSIVE even when its tests observed fail-to-pass."""
    out = _for(monkeypatch, tmp_path, _state())
    [row] = out['requirements']
    assert row['status'] == 'VERIFIED_FAIL_TO_PASS' and out['headline'] == 'ACCEPTANCE_MAPPED_ALL', out
    assert out['follow_up_test_needed'] == [] and out['freshness'] == 'not checked'
    assert out['image_check'] == {'checked': False, 'image': 'localhost/deps:1@' + DIGEST, 'image_digest': DIGEST,
                                  'note': f'image not re-checked by this read-only command; the observation ran in '
                                          f'image {DIGEST}'}
    text = cov.render(out)
    assert f'Image: image not re-checked by this read-only command; the observation ran in image {DIGEST}' in text
    assert any('was not re-checked' in x and DIGEST in x for x in out['limits'])


@pytest.mark.parametrize('over, headline', [
    ({'freshness_reasons': ['container image freshness was not checked by this read-only command',
                            'source changed']}, 'INCONCLUSIVE'),                     # something else is open too
    ({'passport': {'verdict': 'FAIL'}, 'effective_verdict': 'INCONCLUSIVE'}, 'INCONCLUSIVE'),  # it did not pass
    ({'state': 'RUNNING'}, 'INCONCLUSIVE'),
    ({'freshness': 'stale', 'freshness_reasons': ['source changed'], 'effective_verdict': 'STALE'}, 'STALE'),
])
def test_anything_beyond_an_unchecked_image_keeps_the_mission_unverified(monkeypatch, tmp_path, over, headline):
    out = _for(monkeypatch, tmp_path, _state(**over))
    assert out['headline'] == headline and out['requirements'][0]['status'].startswith('UNVERIFIED_'), out
    assert 'image_check' not in out and 'Image:' not in cov.render(out)


def test_not_measured_names_the_real_reason(monkeypatch, tmp_path):
    """C11 study (marshmallow): a frozen declaration but a verdict that was not PASS read as "recorded for pytest and
    node --test missions run with a frozen declaration"."""
    no_pass = _state(passport={'verdict': 'FAIL'}, freshness='fresh', freshness_reasons=[], effective_verdict='FAIL')
    del no_pass['exercise']
    reason = _for(monkeypatch, tmp_path, no_pass)['changed_lines_by_requirement']['reason']
    assert reason == "not measured: the change exercise runs only after a PASS verdict, and this mission's verdict was FAIL"
    unmeasured = _state(exercise={'assurance': 'UNMEASURED', 'reason': 'measurement run timed out', 'changed_lines': 0})
    assert _for(monkeypatch, tmp_path, unmeasured)['changed_lines_by_requirement']['reason'] == (
        'not measured: the change-exercise measurement itself was UNMEASURED (measurement run timed out)')
    no_code = _state(exercise={'assurance': 'NO_EXECUTABLE_CHANGE', 'changed_lines': 0})
    assert _for(monkeypatch, tmp_path, no_code)['changed_lines_by_requirement']['reason'] == \
        'not measured: no executable line changed'
    unfrozen = _state(plan={}, exercise={'assurance': 'FULL', 'changed_lines': 2})
    supplied = decl(req('negative input is negated', ['m_test.py::test_neg']))
    assert 'no requirements declaration was frozen' in _for(monkeypatch, tmp_path, unfrozen, supplied)[
        'changed_lines_by_requirement']['reason']
    own = _state(exercise={'assurance': 'FULL', 'changed_lines': 2, 'per_test_reason': 'no changed python file'})
    assert _for(monkeypatch, tmp_path, own)['changed_lines_by_requirement']['reason'] == \
        'not measured: no changed python file', "the exercise record's own reason wins"


def test_the_image_only_rule_needs_a_content_digest(monkeypatch, tmp_path):
    """Review of the image-only rule: "pinned" must hold, so a record without a sha256 digest gets no observed status."""
    for digest in ('unknown', '', 'sha256:short', None):
        state = _state()
        state['candidate']['executor']['image_digest'] = digest
        out = _for(monkeypatch, tmp_path, state)
        assert out['headline'] != 'ACCEPTANCE_MAPPED_ALL' and 'image_check' not in out, (digest, out['headline'])


def test_no_frozen_declaration_is_named_first_among_not_measured_reasons():
    for exercise, state in (({'assurance': 'UNMEASURED', 'reason': 'x'}, {'exercise': {}}),
                            ({}, {'passport': {'verdict': 'FAIL'}})):
        why = cov._why_no_per_test(state, exercise, frozen=False)
        assert why.startswith('no requirements declaration was frozen'), why
