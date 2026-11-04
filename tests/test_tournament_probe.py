"""`shortlist --probe`: a predeclared differential probe between distinct passing candidates (mission 5B, C12)."""
from __future__ import annotations

import json

import pytest
from repo_ai.mission import probe as pr
from repo_ai.mission import shortlist as sl
from repo_ai.mission.tournament import inspect_comparison
from test_live_tournament import GOOD, fake, run
from test_mission_runtime import bug as bug_fixture


@pytest.fixture
def bug(tmp_path):
    return bug_fixture.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'fakehome'))
    (tmp_path / 'fakehome').mkdir(exist_ok=True)


pytestmark = pytest.mark.usefixtures('claude_fake_login')  # Windows / no sandbox: skipped by conftest

CLAMP = 'def charge(amount, retries):\n    return max(amount, 0)\n'   # passes the frozen tests, differs below 0
TIMES_ONE = 'def charge(amount, retries):\n    return amount * 1\n'    # passes, same as GOOD on ints


def _shortlist(bug, tmp_path, other):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex', {'charge.py': other})}
    report = run(bug, exes)
    assert report['winner'] is None, report
    out = sl.build(bug, inspect_comparison(bug, report['id']))
    assert len(out['candidates']) == 2, out
    return out


def _probe(tmp_path, body: str):
    p = tmp_path / 'probe.py'
    p.write_text('from charge import charge\n' + body)
    return p


def test_candidates_that_behave_differently_on_the_probe_differ_with_the_first_line(bug, tmp_path):
    out = _shortlist(bug, tmp_path, CLAMP)
    rep = pr.run_probe(bug, out, _probe(tmp_path, 'for a in (10, 0, -5):\n    print(a, charge(a, 1))\n'))
    assert rep['verdict'] == 'DIFFER', rep
    fd = rep['first_difference']
    assert fd['line'] == 3 and {fd['a'], fd['b']} == {'-5 -5', '-5 0'}, fd
    assert len(rep['groups']) == 2 and rep['applies_nothing']
    assert (bug / 'charge.py').read_text().count('retries + 1') == 1, 'a probe never touches the source'
    json.dumps(rep)
    assert 'DIFFER' in pr.render(rep)


def test_candidates_that_behave_alike_on_the_probe_are_the_same_not_equivalent(bug, tmp_path):
    out = _shortlist(bug, tmp_path, TIMES_ONE)
    rep = pr.run_probe(bug, out, _probe(tmp_path, 'print([charge(a, 3) for a in range(-3, 4)])\n'))
    assert rep['verdict'] == 'SAME', rep
    assert not rep['groups'][0]['same_as_base'], 'the base still has the bug, so its output differs'
    assert 'not equivalence' in rep['limitations'][0]


def test_a_probe_whose_output_changes_between_runs_compares_nothing(bug, tmp_path):
    out = _shortlist(bug, tmp_path, CLAMP)
    rep = pr.run_probe(bug, out, _probe(tmp_path, 'import time\nprint(time.perf_counter_ns())\n'))
    assert rep['verdict'] == 'INCONCLUSIVE' and any('two runs of the same base' in r for r in rep['reasons']), rep


def test_a_probe_is_refused_without_two_distinct_passing_candidates(bug, tmp_path):
    rep = pr.run_probe(bug, {'candidates': [{'id': 'x'}], 'blockers': []}, _probe(tmp_path, 'print(1)\n'))
    assert rep['verdict'] == 'INCONCLUSIVE' and 'at least two' in rep['reasons'][0]


def test_an_invalid_probe_is_refused_before_anything_runs(tmp_path):
    bad = tmp_path / 'bad.py'
    bad.write_text('def (:\n')
    with pytest.raises(ValueError, match='not valid Python'):
        pr.read_probe(bad)
    link = tmp_path / 'link.py'
    link.symlink_to(bad)
    with pytest.raises(ValueError, match='regular file'):
        pr.read_probe(link)


def test_shortlist_probe_from_the_command_line(bug, tmp_path, capsys):
    from repo_ai.cli import main
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex', {'charge.py': CLAMP})}
    report = run(bug, exes)
    probe = _probe(tmp_path, 'print(charge(-5, 1))\n')
    code = main(['shortlist', report['id'], '-C', str(bug), '--probe', str(probe), '--json'])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out['probe']['verdict'] == 'DIFFER' and out['applies_nothing'], out['probe']
