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


def test_a_probe_that_fails_at_the_base_is_inconclusive_not_same(bug, tmp_path):
    """Review of #133 (B1): a probe that cannot import or crashes everywhere made every candidate look alike."""
    out = _shortlist(bug, tmp_path, CLAMP)
    rep = pr.run_probe(bug, out, _probe(tmp_path, 'import no_such_module_for_this_probe\n'))
    assert rep['verdict'] == 'INCONCLUSIVE' and any('did not run cleanly at the base' in r for r in rep['reasons']), rep
    silent = pr.run_probe(bug, out, _probe(tmp_path, 'charge(1, 1)\n'))
    assert silent['verdict'] == 'INCONCLUSIVE' and any('no output' in r for r in silent['reasons']), silent


def test_diffs_are_applied_when_the_workspaces_sit_inside_another_checkout(bug, tmp_path, monkeypatch):
    """Review of #133 (B2): an enclosing repository made `git apply` skip every path and exit 0 (a false SAME)."""
    out = _shortlist(bug, tmp_path, CLAMP)
    outer = tmp_path / 'outer'
    (outer / 'ws').mkdir(parents=True)
    (outer / 'ws').chmod(0o700)
    _git_init(outer)
    monkeypatch.setenv('REPO_AI_WORKSPACES', str(outer / 'ws'))
    rep = pr.run_probe(bug, out, _probe(tmp_path, 'print(charge(-5, 1))\n'))
    assert rep['verdict'] == 'DIFFER', rep['reasons']


def _git_init(path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(path)], check=True)


def test_a_row_whose_recorded_diff_changed_is_refused(bug, tmp_path):
    out = _shortlist(bug, tmp_path, CLAMP)
    out['candidates'][1] = dict(out['candidates'][1], diff_sha256='0' * 64)
    rep = pr.run_probe(bug, out, _probe(tmp_path, 'print(charge(-5, 1))\n'))
    assert rep['verdict'] == 'INCONCLUSIVE' and 'not the one the shortlist listed' in rep['reasons'][0], rep


def test_a_blocked_shortlist_runs_no_probe(tmp_path):
    rep = pr.run_probe(tmp_path, {'candidates': [{'id': 'a'}, {'id': 'b'}], 'blockers': ['uncontrolled']},
                       _probe(tmp_path, 'print(1)\n'))
    assert rep['verdict'] == 'INCONCLUSIVE' and rep['candidates'] == []


def test_first_difference_uses_the_whole_output():
    long_a, long_b = 'x\n' * 3000 + 'a\n', 'x\n' * 3000 + 'b\n'
    assert pr._first_difference(long_a, long_b)['line'] == 3001
    assert pr._first_difference('ok\n', 'ok')['what'] == 'line endings or a trailing newline only'
    assert pr._first_difference('same', 'same')['what'] == 'exit status only'


def test_a_diff_that_creates_and_deletes_files_is_checked_and_applied(tmp_path):
    """Re-review of #133: a deletion (`+++ /dev/null`) was read as the path /dev/null and always refused."""
    import subprocess
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'a.txt').write_text('one\n')
    (ws / 'b.txt').write_text('gone\n')
    diff = ('diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-one\n+two\n'
            'diff --git a/b.txt b/b.txt\ndeleted file mode 100644\n--- a/b.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n'
            'diff --git a/c.txt b/c.txt\nnew file mode 100644\n--- /dev/null\n+++ b/c.txt\n@@ -0,0 +1 @@\n+new\n')
    assert pr._expected(diff) == {'a.txt': 'modified', 'b.txt': 'deleted', 'c.txt': 'created'}
    assert pr._apply(ws, diff) is None
    assert (ws / 'a.txt').read_text() == 'two\n' and not (ws / 'b.txt').exists() and (ws / 'c.txt').read_text() == 'new\n'
    assert pr._expected('--- a/../x\n+++ b/../x\n') is None and pr._expected('--- /etc/x\n+++ /etc/x\n') is None
    subprocess.run(['true'])
