"""`repo-ai init` then `repo-ai do`: repo-ai's own files never block or fail a mission (found on a real repository)."""
import subprocess
import sys
from pathlib import Path

from repo_ai.mission.runtime import execute, plan
from test_mission_runtime import git, replay


def _project(tmp_path):
    root = tmp_path / 'proj'
    root.mkdir()
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return amount * (retries + 1)\n')
    (root / 'test_charge.py').write_text('from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'base')
    init = subprocess.run([sys.executable, '-m', 'repo_ai', 'init', '--agent', 'none'], cwd=root,
                          capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    return root


def _mission(root, tmp_path):
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] != 'BLOCKED', p
    return execute(root, p, replay(root, tmp_path))


def test_uncommitted_init_files_do_not_make_the_checkout_dirty(tmp_path):
    root = _project(tmp_path)
    git(root, 'add', '.gitignore')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'gitignore')
    assert _mission(root, tmp_path)['effective_verdict'] == 'PASS'


def test_committed_init_files_are_not_mistaken_for_provider_edits(tmp_path):
    root = _project(tmp_path)
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'repo-ai init')
    result = _mission(root, tmp_path)
    assert result['effective_verdict'] == 'PASS', result.get('passport', {}).get('negative')


def test_a_real_uncommitted_source_edit_still_blocks(tmp_path):
    root = _project(tmp_path)
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return amount\n')
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED' and 'charge.py' in str(p)


def test_the_mission_identity_excludes_repo_ai_files_so_provider_validation_never_compares_them(tmp_path):
    from repo_ai.mission.runtime import identity
    root = _project(tmp_path)
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'repo-ai init')
    ident = identity(root, require_clean=True)
    assert 'charge.py' in ident['files'] and not any(f.startswith('.repo-ai/') for f in ident['files'])


def test_a_provider_candidate_after_committed_init_is_verified(tmp_path):
    """The path that failed live (Codex on python-slugify): provider validation must not compare repo-ai's files."""
    from repo_ai.mission import runtime
    from test_provider_runtime import _make_fake_cli
    root = _project(tmp_path)
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'repo-ai init')
    cli = _make_fake_cli(tmp_path, 'codex', (
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"))
    planned = runtime.plan(root, 'Fix duplicate charge', agent='codex', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, None, provider_executable=cli)
    assert result['effective_verdict'] == 'PASS', result['passport']['negative']


def test_mission_tests_run_with_the_projects_interpreter_not_the_workspaces(tmp_path, monkeypatch):
    """Found on python-humanize: a workspace never holds the project's `.venv`, so resolving the interpreter from the
    workspace fell back to the first `python3` on PATH (missing the project's test dependencies). Post-apply
    verification, which runs in the checkout, used the project's venv: the python-slugify 20-vs-0 discrepancy."""
    from repo_ai.verify import execute
    seen = []
    real = execute.interpreter

    def spy(root, **kw):
        seen.append(Path(root).resolve())
        return real(root, **kw)

    monkeypatch.setattr(execute, 'interpreter', spy)
    root = _project(tmp_path)
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'repo-ai init')
    assert _mission(root, tmp_path)['effective_verdict'] == 'PASS'
    assert seen and set(seen) == {root.resolve()}, seen
