"""`repo-ai init` then `repo-ai do`: repo-ai's own files never block or fail a mission (found on a real repository)."""
import subprocess
import sys
from pathlib import Path

from repo_ai.mission.runtime import execute, plan
from test_mission_runtime import git, replay


def _project(tmp_path, gitignore=None):
    root = tmp_path / 'proj'
    root.mkdir()
    if gitignore is not None:
        (root / '.gitignore').write_text(gitignore)
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


def test_a_tracked_file_that_gitignore_also_matches_reaches_the_tests(tmp_path):
    """Found on python-humanize: its `.gitignore` matches `src/*/_version.py`, and the task tracks a stub. The mission
    re-committed its workspace with `git add -A`, which dropped the file, so every test failed to import the package."""
    root = _project(tmp_path)
    (root / 'version_stub.py').write_text('VERSION = "1"\n')
    (root / 'test_version.py').write_text('from version_stub import VERSION\n\ndef test_version():\n    assert VERSION\n')
    (root / '.gitignore').write_text((root / '.gitignore').read_text() + 'version_stub.py\n')
    git(root, 'add', '-A')
    git(root, 'add', '--force', 'version_stub.py')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'tracked but ignored')
    result = _mission(root, tmp_path)
    assert result['effective_verdict'] == 'PASS', result.get('passport', {}).get('negative')


def test_init_editing_a_tracked_gitignore_does_not_block_the_mission(tmp_path):
    """Found on python-humanize with 0.11.1: init's managed block in a tracked .gitignore made `do` refuse."""
    root = _project(tmp_path, gitignore='__pycache__/\n')
    assert git(root, 'status', '--porcelain').stdout.decode().split() == ['M', '.gitignore', '??', '.repo-ai/']
    assert _mission(root, tmp_path)['effective_verdict'] == 'PASS'
    assert '# >>> repo-ai managed >>>' in (root / '.gitignore').read_text()  # the user's working copy is untouched


def test_init_creating_a_gitignore_does_not_block_the_mission(tmp_path):
    root = _project(tmp_path)
    assert '?? .gitignore' in git(root, 'status', '--porcelain').stdout.decode()
    assert _mission(root, tmp_path)['effective_verdict'] == 'PASS'


def test_a_real_gitignore_edit_next_to_the_block_still_blocks(tmp_path):
    root = _project(tmp_path, gitignore='__pycache__/\n')
    with open(root / '.gitignore', 'a') as fh:
        fh.write('secrets.txt\n')
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED' and '.gitignore' in str(p)


def test_an_untracked_file_with_more_than_the_block_still_blocks(tmp_path):
    root = _project(tmp_path)
    with open(root / '.gitignore', 'a') as fh:
        fh.write('notes.txt\n')
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED'


def test_a_provider_candidate_after_uncommitted_init_with_a_tracked_gitignore_is_verified(tmp_path):
    from repo_ai.mission import runtime
    from test_provider_runtime import _make_fake_cli
    root = _project(tmp_path, gitignore='__pycache__/\n')
    cli = _make_fake_cli(tmp_path, 'codex', (
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"))
    planned = runtime.plan(root, 'Fix duplicate charge', agent='codex', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, None, provider_executable=cli)
    assert result['effective_verdict'] == 'PASS', result['passport']['negative']


BLOCK = '# >>> repo-ai managed >>>\n# Machine-local repo-ai state.\n.repo-ai/state/\n# <<< repo-ai managed <<<\n'


def test_markers_in_source_never_hide_a_real_edit(tmp_path):
    root = _project(tmp_path, gitignore='__pycache__/\n')
    with open(root / 'charge.py', 'a') as fh:
        fh.write('\n' + BLOCK.replace('.repo-ai/state/', 'def charge(amount, retries):\n    return amount * 1000'))
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED' and 'charge.py' in str(p)


def test_an_untracked_conftest_wrapped_in_markers_is_dirty(tmp_path):
    root = _project(tmp_path, gitignore='__pycache__/\n')
    (root / 'conftest.py').write_text(BLOCK.replace('.repo-ai/state/', 'import charge; charge.charge = lambda a, r: a'))
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED'


def test_a_block_that_ignores_more_than_repo_ai_state_is_dirty(tmp_path):
    root = _project(tmp_path, gitignore='__pycache__/\n')
    text = (root / '.gitignore').read_text().replace('.repo-ai/state/', '.repo-ai/state/\n*.py')
    (root / '.gitignore').write_text(text)
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED'


def test_an_empty_committed_gitignore(tmp_path):
    root = _project(tmp_path, gitignore='')
    assert _mission(root, tmp_path)['effective_verdict'] == 'PASS'


def test_a_crlf_gitignore(tmp_path):
    root = _project(tmp_path, gitignore='__pycache__/\r\n*.log\r\n')
    (root / '.gitignore').write_bytes((root / '.gitignore').read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    assert _mission(root, tmp_path)['effective_verdict'] == 'PASS'


def test_a_provider_that_copies_the_working_gitignore_has_edited_it(tmp_path):
    from repo_ai.mission import runtime
    from test_provider_runtime import _make_fake_cli
    root = _project(tmp_path, gitignore='__pycache__/\n')
    working = (root / '.gitignore').read_text()
    cli = _make_fake_cli(tmp_path, 'codex', (
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        f"(ws / '.gitignore').write_text({working!r})\n"
        "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"))
    planned = runtime.plan(root, 'Fix duplicate charge', agent='codex', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, None, provider_executable=cli)
    assert result['effective_verdict'] != 'PASS'
    assert any('.gitignore' in n for n in result['passport']['negative'])


def test_apply_after_an_uncommitted_init_leaves_the_users_gitignore_alone(tmp_path):
    from repo_ai.mission.application import apply
    root = _project(tmp_path, gitignore='__pycache__/\n')
    before = (root / '.gitignore').read_bytes()
    result = _mission(root, tmp_path)
    assert result['effective_verdict'] == 'PASS'
    apply(root, result['id'])
    assert (root / '.gitignore').read_bytes() == before
    assert (root / 'charge.py').read_text() == 'def charge(amount, retries):\n    return amount\n'


def test_a_marker_with_extra_text_is_never_read_as_a_block(tmp_path):
    root = _project(tmp_path, gitignore='__pycache__/\n')
    with open(root / '.gitignore', 'a') as fh:
        fh.write('\n# >>> repo-ai managed >>> x\n*.py\n# <<< repo-ai managed <<<\n')
    p = plan(root, 'Fix duplicate charge', agent='replay', write_paths=['charge.py'], execute_local=True)
    assert p['decision'] == 'BLOCKED'


def test_without_init_block_is_line_exact():
    from repo_ai.mission.runtime import _without_init_block
    begin, end = '# >>> repo-ai managed >>>', '# <<< repo-ai managed <<<'
    assert _without_init_block(f'a\n\n{begin}\n.repo-ai/state/\n{end}\n', '.repo-ai/state') == 'a'
    assert _without_init_block(f'a\n{begin}\n.repo-ai/state/\n', '.repo-ai/state') is None  # unterminated
    assert _without_init_block(f'{end}\na\n', '.repo-ai/state') is None  # unmatched end
    assert _without_init_block(f'{begin}\n{begin}\n{end}\n', '.repo-ai/state') is None  # nested
    assert _without_init_block(f'{begin}\nsrc/\n{end}\n', '.repo-ai/state') is None  # ignores source


def test_a_provider_that_rewrites_gitignore_line_endings_has_edited_it(tmp_path):
    from repo_ai.mission import runtime
    from test_provider_runtime import _make_fake_cli
    root = _project(tmp_path, gitignore='__pycache__/\n')
    cli = _make_fake_cli(tmp_path, 'codex', (
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "g = ws / '.gitignore'\n"
        "g.write_bytes(g.read_bytes().replace(b'\\n', b'\\r\\n'))\n"
        "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"))
    planned = runtime.plan(root, 'Fix duplicate charge', agent='codex', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, None, provider_executable=cli)
    assert result['effective_verdict'] != 'PASS'
    assert any('.gitignore' in n for n in result['passport']['negative'])


def test_an_autocrlf_checkout_after_init_passes(tmp_path):
    """core.autocrlf=true: the working tree and the archived workspace hold CRLF, HEAD's blob holds LF."""
    from repo_ai.mission import runtime
    from test_provider_runtime import _make_fake_cli
    root = tmp_path / 'proj'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'core.autocrlf', 'true')
    (root / '.gitignore').write_bytes(b'__pycache__/\n')
    (root / 'charge.py').write_text('def charge(amount, retries):\n    return amount * (retries + 1)\n')
    (root / 'test_charge.py').write_text('from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'base')
    for rel in ('.gitignore', 'charge.py', 'test_charge.py', 'pyproject.toml'):
        (root / rel).unlink()
    git(root, 'checkout', '--', '.')  # a fresh CRLF checkout
    assert (root / '.gitignore').read_bytes() == b'__pycache__/\r\n'
    init = subprocess.run([sys.executable, '-m', 'repo_ai', 'init', '--agent', 'none'], cwd=root,
                          capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    cli = _make_fake_cli(tmp_path, 'codex', (
        "import json, os, pathlib\n"
        "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
        "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"))
    planned = runtime.plan(root, 'Fix duplicate charge', agent='codex', write_paths=['charge.py'], execute_local=True)
    result = runtime.execute(root, planned, None, provider_executable=cli)
    assert result['effective_verdict'] == 'PASS', result['passport']['negative']
