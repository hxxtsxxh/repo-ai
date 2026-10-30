"""A stored candidate diff must survive byte-exactly, including a trailing blank context line."""
from __future__ import annotations

import hashlib
import json
import subprocess

from repo_ai.mission import runtime
from repo_ai.mission.runtime import execute, plan


def _git(root, *args):
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=root, capture_output=True, check=True)


def test_git_diff_keeps_trailing_blank_context_line(tmp_path):
    root = tmp_path / 'r'
    root.mkdir()
    (root / 'f.txt').write_text('a\nb\nc\n\nz\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'b')
    (root / 'f.txt').write_text('a\nB\nc\n\nz\n')
    diff = runtime.git(root, 'diff', '--no-ext-diff', '--no-textconv', '--binary', raw=True)
    assert diff.endswith('\n')
    (root / 'f.txt').write_text('a\nb\nc\n\nz\n')
    patch = tmp_path / 'p.patch'
    patch.write_text(diff)
    _git(root, 'apply', '--check', str(patch))


def test_verified_mission_diff_applies_when_hunk_ends_in_blank_line(tmp_path):
    root = tmp_path / 'bug'
    root.mkdir()
    src = 'def f(x):\n    return x - 1\n\n'
    (root / 'm.py').write_text(src)
    (root / 'test_m.py').write_text('from m import f\n\ndef test_f():\n    assert f(2) == 3\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'b')
    p = tmp_path / 'proposal.json'
    p.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'simulated fixture agent', 'edits': [
        {'path': 'm.py', 'before_sha256': hashlib.sha256(src.encode()).hexdigest(),
         'after': 'def f(x):\n    return x + 1\n\n'}]}))
    pl = plan(root, 'Fix f so it increments', agent='replay', write_paths=['m.py'], execute_local=True)
    state = execute(root, pl, p)
    assert state['effective_verdict'] == 'PASS'
    assert state['diff'].endswith('\n')
    patch = tmp_path / 'stored.patch'
    patch.write_text(state['diff'])
    _git(root, 'apply', '--check', str(patch))
    res = runtime.apply_mission(root, state['id'])
    assert res['post_apply_verdict'] == 'PASS'
