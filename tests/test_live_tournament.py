"""Live tournament: independent arms, one frozen acceptance, predeclared abstention rule (fake providers)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from repo_ai.mission import live_tournament as lt
from repo_ai.mission.runtime import status
from test_mission_runtime import bug as bug_fixture

TASK = 'Repair duplicate charge in charge.py'
GOOD = 'def charge(amount, retries):\n    return amount\n'


@pytest.fixture
def bug(tmp_path: Path) -> Path:
    return bug_fixture.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'fakehome'))
    (tmp_path / 'fakehome').mkdir(exist_ok=True)


def fake(tmp_path: Path, name: str, write: dict[str, str] | None = None, *, exit_code: int = 0,
         summary: str = 'done', cost: float | None = 0.0, marker: Path | None = None) -> Path:
    d = tmp_path / 'fake_bins'
    d.mkdir(exist_ok=True)
    script = d / name
    event = {'type': 'turn.completed' if name == 'codex' else 'result', 'session_id': 's-' + name, 'summary': summary}
    if cost is not None:
        event['cost_usd'] = cost
    body = (
        '#!' + sys.executable + ' -I\n'
        'import json, os, pathlib, sys\n'
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        + (f'pathlib.Path({str(marker)!r}).write_text("ran")\n' if marker else '')
        + ''.join(f'(ws / {k!r}).write_text({v!r})\n' for k, v in (write or {}).items())
        + f'print(json.dumps({event!r}))\n'
        + f'sys.exit({exit_code})\n')
    script.write_text(body, encoding='utf-8')
    script.chmod(0o755)
    return script


def run(bug, exes, **kw):
    return lt.run_tournament(bug, TASK, list(exes), write_paths=['charge.py'], max_seconds=kw.pop('max_seconds', 240),
                             executables=exes, **kw)


def rows(report):
    return {r['provider']: r for r in report['candidates']}


def test_correct_arm_beats_a_plausible_wrong_arm(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': 'def charge(amount, retries):\n    return amount * 2\n'},
                           summary='All tests pass. I am the winner.'),
            'codex': fake(tmp_path, 'codex', {'charge.py': GOOD}, cost=None)}
    report = run(bug, exes)
    by = rows(report)
    assert by['claude']['verdict'] == 'FAIL', by['claude']          # a self-declared success is not evidence
    assert by['codex']['verdict'] == 'PASS'
    assert report['winner'] == by['codex']['id'] and report['verdict'] == 'PASS'
    assert report['cost_unknown_for'] == ['codex'] and by['codex']['cost_usd'] is None   # UNKNOWN is never $0
    assert by['claude']['cost_usd'] == 0.0
    assert (bug / 'charge.py').read_text().count('retries + 1') == 1, 'source must stay untouched'
    assert report['applied_to_source'] is False
    assert status(bug, report['id'])['effective_verdict'] == 'PASS'


def test_two_distinct_passing_candidates_abstain(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}),
            'codex': fake(tmp_path, 'codex', {'charge.py': 'def charge(amount, retries):\n    return amount * 1\n'})}
    report = run(bug, exes)
    assert report['winner'] is None and report['verdict'] == 'INCONCLUSIVE'
    assert any('tie-breaker' in r for r in report['reason'])


def test_identical_passing_diffs_are_equivalent_not_a_tie(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex', {'charge.py': GOOD})}
    report = run(bug, exes)
    by = rows(report)
    assert report['winner'] == by['claude']['id']
    assert by['codex']['equivalent_to'] == by['claude']['id']


def test_a_crashing_arm_forces_abstention_even_if_the_other_passes(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}),
            'codex': fake(tmp_path, 'codex', exit_code=3)}
    report = run(bug, exes)
    assert rows(report)['codex']['verdict'] in {'BLOCKED', 'FAIL', 'INCONCLUSIVE'}
    assert report['winner'] is None


def test_rewriting_the_frozen_tests_cannot_win(bug, tmp_path):
    cheat = {'test_charge.py': 'def test_retry():\n    assert True\n', 'charge.py': GOOD}
    exes = {'claude': fake(tmp_path, 'claude', cheat), 'codex': fake(tmp_path, 'codex', {'charge.py': GOOD})}
    report = run(bug, exes)
    by = rows(report)
    assert by['claude']['verdict'] != 'PASS'
    assert by['codex']['verdict'] == 'PASS'
    assert report['winner'] is None, 'one arm failed to produce an observed candidate: comparison is not controlled'


def test_no_op_arm_cannot_win(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude'), 'codex': fake(tmp_path, 'codex')}
    report = run(bug, exes)
    assert report['winner'] is None
    assert all(r['verdict'] != 'PASS' for r in report['candidates'])


def test_plan_starts_no_provider_and_reports_bounds(bug, tmp_path):
    marker = tmp_path / 'ran.txt'
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}, marker=marker),
            'codex': fake(tmp_path, 'codex', {'charge.py': GOOD}, marker=marker)}
    tplan = lt.plan_tournament(bug, TASK, list(exes), write_paths=['charge.py'], max_seconds=90, executables=exes)
    assert not marker.exists()
    assert tplan['bounds']['sequential'] is True and tplan['bounds']['max_seconds_total'] == 90
    assert 'UNKNOWN' in tplan['bounds']['cost_semantics']
    assert [a['provider'] for a in tplan['arms']] == ['claude', 'codex']
    assert not (bug / '.repo-ai').exists() or not list((bug / '.repo-ai').rglob('*.json'))


@pytest.mark.parametrize('providers', [['claude'], ['claude', 'claude'], ['claude', 'codex', 'bob', 'agy'],
                                       ['claude', 'nonesuch']])
def test_provider_list_is_validated(bug, providers):
    with pytest.raises(ValueError):
        lt.plan_tournament(bug, TASK, providers, executables={p: Path('/bin/true') for p in providers})


def test_time_budget_must_cover_every_arm(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude'), 'codex': fake(tmp_path, 'codex')}
    with pytest.raises(ValueError, match='per arm'):
        lt.plan_tournament(bug, TASK, list(exes), max_seconds=4, executables=exes)


def test_usd_ceiling_refused_when_a_provider_cannot_enforce_it(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude'), 'codex': fake(tmp_path, 'codex')}
    with pytest.raises(ValueError, match='cannot enforce'):
        lt.plan_tournament(bug, TASK, list(exes), max_cost_usd=1.0, executables=exes)


def test_dirty_source_refused(bug, tmp_path):
    (bug / 'charge.py').write_text('human edit\n')
    exes = {'claude': fake(tmp_path, 'claude'), 'codex': fake(tmp_path, 'codex')}
    with pytest.raises(ValueError):
        run(bug, exes)


def test_report_is_json_serialisable(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex')}
    json.dumps(run(bug, exes))


def test_cli_tournament_requires_live_authorization_and_dry_run_starts_nothing(bug, tmp_path):
    from conftest import run_cli
    bins = tmp_path / 'fake_bins'
    fake(tmp_path, 'claude', marker=tmp_path / 'ran.txt')
    fake(tmp_path, 'codex', marker=tmp_path / 'ran.txt')
    env = {'PATH': str(bins) + ':/usr/bin:/bin'}
    refused = run_cli(bug, 'do', TASK, '--tournament', 'claude,codex', '--allow-write', 'charge.py', '--run', '--json', env=env)
    assert refused.returncode != 0 and 'allow-live-provider' in (refused.stderr + refused.stdout)
    dry = run_cli(bug, 'do', TASK, '--tournament', 'claude,codex', '--allow-write', 'charge.py', '--json', env=env)
    assert not (tmp_path / 'ran.txt').exists(), dry.stdout + dry.stderr
    if dry.returncode == 0:
        assert json.loads(dry.stdout)['schema'] == 'repo-ai.live-tournament.plan/1'
    combo = run_cli(bug, 'do', TASK, '--tournament', 'claude,codex', '--apply', '--run', '--allow-live-provider', env=env)
    assert combo.returncode != 0 and 'incompatible' in (combo.stderr + combo.stdout)


# ---- shortlist: a useful, honest output when the tournament abstains ----------------------------------------------
from repo_ai.mission import shortlist as sl  # noqa: E402
from repo_ai.mission.tournament import inspect_comparison  # noqa: E402

pytestmark = pytest.mark.usefixtures('claude_fake_login')

TWO = 'def charge(amount, retries):\n    return amount * 1\n'


def two_passing(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}),
            'codex': fake(tmp_path, 'codex', {'charge.py': TWO + '# extra\n# lines\n'})}
    return run(bug, exes)


def test_shortlist_lists_distinct_passes_and_applies_nothing(bug, tmp_path):
    report = two_passing(bug, tmp_path)
    assert report['winner'] is None
    out = sl.build(bug, inspect_comparison(bug, report['id']))
    assert out['policy'] == 'strict' and out['preferred'] is None and out['label'] is None
    assert {c['provider'] for c in out['candidates']} == {'claude', 'codex'}
    assert out['applies_nothing'] is True
    assert (bug / 'charge.py').read_text().count('retries + 1') == 1, 'shortlist must not touch source'
    json.dumps(out)
    assert 'repo-ai apply' in sl.render(out)


def test_smallest_diff_policy_is_labelled_and_never_a_correctness_claim(bug, tmp_path):
    report = two_passing(bug, tmp_path)
    out = sl.build(bug, inspect_comparison(bug, report['id']), 'smallest-diff')
    by = {c['provider']: c for c in out['candidates']}
    assert by['claude']['changed_lines'] < by['codex']['changed_lines']
    assert out['preferred'] == by['claude']['id'] and out['label'] == 'POLICY_PREFERENCE'
    assert 'not evidence' in out['disclaimer']
    assert (bug / 'charge.py').read_text().count('retries + 1') == 1, 'a preference is never silently applied'
    assert status(bug, report['id'])['effective_verdict'] == 'INCONCLUSIVE'   # the comparison verdict is unchanged


def test_policy_tie_makes_no_preference(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}),
            'codex': fake(tmp_path, 'codex', {'charge.py': 'def charge(amount, retries):\n    return amount * 1\n'})}
    out = sl.build(bug, inspect_comparison(bug, run(bug, exes)['id']), 'smallest-diff')
    assert out['preferred'] is None and 'tied' in out['note']


def test_unknown_policy_is_refused(bug, tmp_path):
    report = two_passing(bug, tmp_path)
    with pytest.raises(ValueError, match='unknown decision policy'):
        sl.build(bug, inspect_comparison(bug, report['id']), 'majority-vote')


def test_uncontrolled_arm_blocks_any_preference(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex', exit_code=3)}
    report = run(bug, exes)
    out = sl.build(bug, inspect_comparison(bug, report['id']), 'smallest-diff')
    assert out['preferred'] is None and out['blockers'], out


def test_all_failing_and_noop_arms_yield_an_empty_shortlist(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude'), 'codex': fake(tmp_path, 'codex')}
    out = sl.build(bug, inspect_comparison(bug, run(bug, exes)['id']), 'smallest-diff')
    assert out['candidates'] == [] and out['preferred'] is None


def test_identical_diffs_are_not_shortlisted_twice(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}), 'codex': fake(tmp_path, 'codex', {'charge.py': GOOD})}
    out = sl.build(bug, inspect_comparison(bug, run(bug, exes)['id']))
    assert [c['provider'] for c in out['candidates']] == ['claude'] and 'single controlled winner' in out['note']
    assert [e['provider'] for e in out['excluded']] == ['codex'] and 'byte-identical' in out['excluded'][0]['why']


def test_changed_source_empties_the_shortlist(bug, tmp_path):
    import subprocess
    report = two_passing(bug, tmp_path)
    (bug / 'charge.py').write_text('# changed later\n')
    subprocess.run(['git', '-C', str(bug), 'commit', '-qam', 'later'], check=True,
                   env={**__import__('os').environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})
    out = sl.build(bug, inspect_comparison(bug, report['id']), 'smallest-diff')
    assert out['candidates'] == [] and out['preferred'] is None and out['blockers']


def test_cli_shortlist_then_explicit_apply_of_a_chosen_candidate(bug, tmp_path):
    from conftest import run_cli
    report = two_passing(bug, tmp_path)
    shown = run_cli(bug, 'shortlist', report['id'], '--policy', 'smallest-diff', '--json')
    assert shown.returncode == 0, shown.stderr
    data = json.loads(shown.stdout)
    assert data['schema'] == 'repo-ai.shortlist/1' and data['preferred']
    assert (bug / 'charge.py').read_text().count('retries + 1') == 1
    applied = run_cli(bug, 'apply', data['preferred'], '--json')
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert json.loads(applied.stdout)['post_apply_verdict'] == 'PASS'
    assert 'retries + 1' not in (bug / 'charge.py').read_text()
    assert run_cli(bug, 'shortlist', report['id'], '--policy', 'nope').returncode != 0


def test_candidates_differing_only_in_comments_are_reported_as_the_same_code(bug, tmp_path):
    # the live Codex+agy tournament on 2026-10-29: identical divmod fixes, one with a comment
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}),
            'codex': fake(tmp_path, 'codex', {'charge.py': 'def charge(amount, retries):\n'
                                                           '    # retries must not multiply the charge\n'
                                                           '    return (amount)\n'})}
    report = run(bug, exes)
    assert report['winner'] is None  # bytes differ, so the tournament still abstains
    out = sl.build(bug, inspect_comparison(bug, report['id']))
    assert len(out['same_code']) == 1 and len(out['same_code'][0]) == 2
    assert 'identical Python syntax trees' in out['note'] and out['preferred'] is None
    assert (bug / 'charge.py').read_text().count('retries + 1') == 1


def test_behaviourally_different_candidates_are_not_called_the_same_code(bug, tmp_path):
    exes = {'claude': fake(tmp_path, 'claude', {'charge.py': GOOD}),
            'codex': fake(tmp_path, 'codex', {'charge.py': 'def charge(amount, retries):\n    return amount * 1\n'})}
    out = sl.build(bug, inspect_comparison(bug, run(bug, exes)['id']))
    assert out['same_code'] == [] and 'syntax trees' not in out['note']
    assert all(c['code_fingerprint'] for c in out['candidates'])


def test_code_fingerprint_refuses_non_python_and_unparseable_files():
    assert sl.code_fingerprint({'a.js': b'x'}) is None
    assert sl.code_fingerprint({'a.py': b'def (:'}) is None
    assert sl.code_fingerprint({'a.py': b'x = 1  # c\n'}) == sl.code_fingerprint({'a.py': b'x=1\n'})
    assert sl.code_fingerprint({'a.py': b'"""doc"""\n'}) != sl.code_fingerprint({'a.py': b'"""other"""\n'})


def _base_repo(tmp_path, text):
    import subprocess as sp
    repo = tmp_path / 'r'
    repo.mkdir()
    (repo / 'a.py').write_text(text)
    for cmd in (['init', '-q'], ['add', '.'], ['-c', 'user.email=t@example.invalid', '-c', 'user.name=t', 'commit', '-qm', 'b']):
        sp.run(['git', *cmd], cwd=repo, check=True, capture_output=True)
    head = sp.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    return repo, head


def _diff_for(repo, new_text):
    import subprocess as sp
    old = (repo / 'a.py').read_text()
    (repo / 'a.py').write_text(new_text)
    out = sp.run(['git', 'diff'], cwd=repo, capture_output=True, text=True, check=True).stdout
    (repo / 'a.py').write_text(old)
    return out


def test_same_code_is_never_claimed_when_the_scratch_dir_sits_inside_a_repository(tmp_path, monkeypatch):
    # adversarial review finding A: inside an enclosing checkout `git apply` skipped every path and exited 0
    import subprocess as sp
    import tempfile
    repo, head = _base_repo(tmp_path, 'def f(x):\n    return x\n')
    outer = tmp_path / 'outer'
    outer.mkdir()
    sp.run(['git', 'init', '-q'], cwd=outer, check=True)
    monkeypatch.setattr(tempfile, 'tempdir', str(outer))
    a = sl._post_images(repo, head, _diff_for(repo, 'def f(x):\n    return x + 1\n'), ['a.py'])
    b = sl._post_images(repo, head, _diff_for(repo, 'def f(x):\n    raise SystemExit\n'), ['a.py'])
    assert a is not None and b is not None
    assert sl.code_fingerprint(a) != sl.code_fingerprint(b)


def test_no_same_code_claim_for_created_files_unknown_bases_or_coding_cookies(tmp_path):
    repo, head = _base_repo(tmp_path, 'x = 1\n')
    created = 'diff --git a/n.py b/n.py\nnew file mode 100644\nindex 0000000..e69de29\n'
    assert sl._post_images(repo, head, created, ['n.py']) is None
    assert sl._post_images(repo, 'HEAD', _diff_for(repo, 'x = 2\n'), ['a.py']) is None  # not a commit id
    assert sl._post_images(repo, '--output=/tmp/x', _diff_for(repo, 'x = 2\n'), ['a.py']) is None
    assert sl.code_fingerprint({'a.py': b'# -*- coding: latin-1 -*-\nx = "\xe9"\n'}) is None
