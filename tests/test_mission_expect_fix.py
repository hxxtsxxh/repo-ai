"""Scoped missions (--expect-fix): a real suite with an unrelated failure can still verify a fix, never hiding it."""
import pytest


from repo_ai.mission.contracts import IntentContract
from repo_ai.mission.runtime import apply_mission, execute, plan
from test_mission_runtime import git, replay


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'proj'
    root.mkdir()
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return amount * (retries + 1)\n')
    (root / 'test_charge.py').write_text('from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n\n'
                                         'def test_once():\n    assert charge(10, 0) == 10\n')
    # an unrelated test that already fails (an environment or legacy problem the task does not touch)
    (root / 'test_legacy.py').write_text('def test_old_backend():\n    assert False, "needs an optional backend"\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'base')
    return root


def _run(project, tmp_path, expect_fix, after='def charge(amount, retries):\n    return amount\n'):
    p = plan(project, 'Fix duplicate charge in charge.py', agent='replay', write_paths=['charge.py'],
             execute_local=True, expect_fix=expect_fix)
    return execute(project, p, replay(project, tmp_path, after=after))


def test_without_declared_tests_an_unrelated_failure_blocks_the_pass(project, tmp_path):
    result = _run(project, tmp_path, [])
    assert result['effective_verdict'] != 'PASS'


def test_declared_fix_passes_and_lists_the_remaining_base_failure(project, tmp_path):
    result = _run(project, tmp_path, ['test_charge.py::test_retry'])
    assert result['effective_verdict'] == 'PASS', result.get('reasons')
    assert result['scoped']['standing'] == 'PASS_WITH_PRE_EXISTING_FAILURES'
    assert any('test_old_backend' in t for t in result['scoped']['pre_existing_failures'])
    assert result['claims']['headline'] == 'ASSURANCE_PARTIAL'
    assert any('already failed at the base' in n for n in result['claims']['notes'])


def test_a_regression_of_a_base_passing_test_fails_even_when_scoped(project, tmp_path):
    # fixes test_retry's case but breaks test_once (which passed at the base)
    result = _run(project, tmp_path, ['test_charge.py::test_retry'],
                  after='def charge(amount, retries):\n    return amount if retries else 0\n')
    assert result['effective_verdict'] != 'PASS'


def test_a_declared_test_that_does_not_fail_at_the_base_is_refused(project, tmp_path):
    result = _run(project, tmp_path, ['test_charge.py::test_once'])
    assert result['effective_verdict'] != 'PASS'


def test_an_undeclared_or_unknown_test_id_is_refused(project, tmp_path):
    assert _run(project, tmp_path, ['test_charge.py::test_nope'])['effective_verdict'] != 'PASS'
    with pytest.raises(ValueError):
        plan(project, 'x', agent='replay', write_paths=['charge.py'], execute_local=True, expect_fix=['no-separator'])
    with pytest.raises(ValueError):
        plan(project, 'x', agent='replay', write_paths=['charge.py'], execute_local=True,
             expect_fix=['../escape.py::test'])


def test_apply_of_a_scoped_pass_reverifies_with_the_same_scope(project, tmp_path):
    result = _run(project, tmp_path, ['test_charge.py::test_retry'])
    applied = apply_mission(project, result['id'])  # raises if the post-apply re-verification fails
    assert 'validation' not in str(applied) or 'PASS' in str(applied)
    assert (project / 'charge.py').read_text() == 'def charge(amount, retries):\n    return amount\n'
    # the remaining base failure is reported, never shown as "0 failed" (found on python-slugify)
    assert applied['post_apply_failed'] == 1 and applied['post_apply_pre_existing'] == 1, applied


def test_the_apply_summary_names_remaining_base_failures(capsys):
    from types import SimpleNamespace
    from repo_ai.mission.cli import _emit
    _emit({'schema': 'repo-ai.mission-apply/1', 'mission': 'm', 'post_apply_verdict': 'PASS', 'modified_files': ['a.py'],
            'post_apply_ran': 131, 'post_apply_failed': 20, 'post_apply_pre_existing': 20}, SimpleNamespace())
    out = capsys.readouterr().out
    assert "131 tests ran, 20 failed (all 20 already failing at the base and not declared)" in out, out


def test_apply_without_the_scope_is_refused_by_the_post_apply_check(project, tmp_path, monkeypatch):
    """Control: the same applied tree, re-verified unscoped, would fail on the remaining base failure."""
    from repo_ai.mission import verification
    result = _run(project, tmp_path, ['test_charge.py::test_retry'])
    original = verification.compare
    monkeypatch.setattr(verification, 'compare', lambda b, c, expect_fix=None: original(b, c))
    with pytest.raises(ValueError, match='post-apply verification failed'):
        apply_mission(project, result['id'])
    assert (project / 'charge.py').read_text() == 'def charge(amount, retries):\n    return amount * (retries + 1)\n'


def test_contracts_without_the_field_keep_their_digest():
    c = IntentContract('o', 'r', 'b' * 40, ['python -m pytest'], ['a.py'])
    assert 'expect_fix' not in c.to_json()
