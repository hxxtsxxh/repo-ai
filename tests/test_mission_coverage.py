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
