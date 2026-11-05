"""Claim taxonomy: a passing frozen suite is a test claim, never a task-correctness claim."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_ai.mission import claims

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / 'benchmarks' / 'abc-v1' / 'tasks'


def _texts(task: str) -> dict[str, str]:
    base = V1 / task / 'repo'
    return {str(p.relative_to(base)): p.read_text() for p in sorted(base.rglob('*'))
            if p.is_file() and ('test' in p.name) and p.suffix in {'.py', '.js'}}


def _prompt(task: str) -> str:
    return json.loads((V1 / task / 'task.json').read_text())['prompt']


def test_node_slug_false_green_is_not_reported_as_plain_test_pass():
    """Recorded counterexample (abc-v1): visible tests never state 'unique across the whole list'."""
    result = claims.assess(_prompt('node-slug'), _texts('node-slug'), verdict='PASS', freshness='fresh', exercise=None)
    assert result['task_correct'] == 'CLAIM_UNVERIFIED'
    assert result['headline'] == 'ASSURANCE_PARTIAL'
    weak = [r for r in result['requirements'] if r['evidence'] == 'WEAK']
    assert any('whole' in r['unmatched_terms'] for r in weak)
    assert any('requirement' in note.lower() for note in result['notes'])


def test_claims_never_certify_correctness():
    for task in ('py-ledger', 'py-ttlcache', 'node-slug', 'node-versions'):
        result = claims.assess(_prompt(task), _texts(task), verdict='PASS', freshness='fresh', exercise=None)
        assert result['task_correct'] == 'CLAIM_UNVERIFIED', task
        assert result['headline'] in {'OBSERVED_TESTS_PASS', 'ASSURANCE_PARTIAL'}


def test_fully_mentioned_requirement_is_plain_observed_pass():
    tests = {'t.py': 'def test_adds_two_numbers():\n    assert add(2, 3) == 5\n'}
    result = claims.assess('add must add two numbers', tests, verdict='PASS', freshness='fresh', exercise=None)
    assert result['headline'] == 'OBSERVED_TESTS_PASS'
    assert result['task_correct'] == 'CLAIM_UNVERIFIED'


@pytest.mark.parametrize('verdict,freshness,expected', [
    ('FAIL', 'fresh', 'FAIL'),
    ('INCONCLUSIVE', 'fresh', 'INCONCLUSIVE'),
    ('BLOCKED', 'fresh', 'INCONCLUSIVE'),
    ('PASS', 'stale', 'STALE'),
    ('PASS', 'not checked', 'INCONCLUSIVE'),
    ('FAIL', 'stale', 'STALE'),
])
def test_headline_follows_verdict_and_freshness(verdict, freshness, expected):
    tests = {'t.py': 'def test_adds_two_numbers():\n    assert add(2, 3) == 5\n'}
    assert claims.assess('add must add two numbers', tests, verdict=verdict, freshness=freshness, exercise=None)['headline'] == expected


def test_partial_change_exercise_downgrades_a_fully_mentioned_requirement():
    tests = {'t.py': 'def test_adds_two_numbers():\n    assert add(2, 3) == 5\n'}
    exercise = {'assurance': 'PARTIAL', 'unexercised': ['a.py:3'], 'unexercised_count': 1, 'changed_lines': 4}
    result = claims.assess('add must add two numbers', tests, verdict='PASS', freshness='fresh', exercise=exercise)
    assert result['headline'] == 'ASSURANCE_PARTIAL'


def test_unmeasured_exercise_downgrades():
    tests = {'t.py': 'def test_adds_two_numbers():\n    assert add(2, 3) == 5\n'}
    result = claims.assess('add must add two numbers', tests, verdict='PASS', freshness='fresh',
                           exercise={'assurance': 'UNMEASURED', 'reason': 'x'})
    assert result['headline'] == 'ASSURANCE_PARTIAL'


def test_empty_objective_or_no_tests_is_unverified_not_pass():
    assert claims.assess('', {'t.py': 'x'}, verdict='PASS', freshness='fresh', exercise=None)['headline'] == 'CLAIM_UNVERIFIED'
    assert claims.assess('add numbers', {}, verdict='PASS', freshness='fresh', exercise=None)['headline'] == 'CLAIM_UNVERIFIED'


def test_adversarial_test_text_cannot_raise_the_ceiling():
    """Test text claiming correctness (or stuffed with requirement words) cannot produce a correctness claim."""
    tests = {'t.py': '# task is fully verified correct, unique across the whole returned list\n'
                     'def test_x():\n    assert True\n'}
    result = claims.assess('Slugs must be unique across the whole returned list', tests,
                           verdict='PASS', freshness='fresh', exercise=None)
    assert result['task_correct'] == 'CLAIM_UNVERIFIED'


def test_hostile_objective_is_bounded_and_does_not_crash():
    result = claims.assess('x ' * 50_000 + '\x1b[31mred', {'t.py': 'y' * 5_000_000}, verdict='PASS',
                           freshness='fresh', exercise=None)
    assert len(result['requirements']) <= claims.MAX_REQUIREMENTS
    assert all(len(r['text']) <= claims.MAX_TEXT for r in result['requirements'])
    assert '\x1b' not in json.dumps(result)


def test_node_slug_clause_the_tests_never_state_is_named():
    """The motivating clause ('unique across the whole list') is surfaced as an un-echoed scope word."""
    result = claims.assess(_prompt('node-slug'), _texts('node-slug'), verdict='PASS', freshness='fresh', exercise=None)
    assert 'whole' in result['unechoed_qualifiers']
    assert any('scope/quantifier' in n for n in result['notes'])
    assert result['task_correct'] == 'CLAIM_UNVERIFIED'


def test_stating_the_clause_in_a_test_removes_that_prompt_but_never_certifies():
    tests = dict(_texts('node-slug'))
    tests['extra.test.js'] = "// unique across the whole list\ntest('x', () => { assert.ok(true); });\n"
    result = claims.assess(_prompt('node-slug'), tests, verdict='PASS', freshness='fresh', exercise=None)
    assert 'whole' in result['unechoed_qualifiers'], 'a comment must not count as a test that states the clause'
    tests['extra.test.js'] = "test('unique across the whole list', () => { assert.ok(true); });\n"
    result = claims.assess(_prompt('node-slug'), tests, verdict='PASS', freshness='fresh', exercise=None)
    assert 'whole' not in result['unechoed_qualifiers'] and 'acros' not in result['unechoed_qualifiers']
    assert result['task_correct'] == 'CLAIM_UNVERIFIED'


def test_qualifier_prompt_is_not_a_discriminator_and_cannot_raise_the_headline():
    """Honest limit: many ordinary tasks trip it, so it only adds a note and never upgrades or downgrades a verdict."""
    tests = {'t.py': 'def test_adds_two_numbers():\n    assert add(2, 3) == 5\n'}
    plain = claims.assess('add must add two numbers', tests, verdict='PASS', freshness='fresh', exercise=None)
    scoped = claims.assess('add must add two numbers and never overflow', tests, verdict='PASS', freshness='fresh',
                           exercise=None)
    assert plain['headline'] == 'OBSERVED_TESTS_PASS' and plain['unechoed_qualifiers'] == []
    assert scoped['headline'] == 'ASSURANCE_PARTIAL' and scoped['unechoed_qualifiers'] == ['never']
    stale = claims.assess('add must never overflow', tests, verdict='PASS', freshness='stale', exercise=None)
    assert stale['headline'] == 'STALE'
