"""mission/difference.py: which source differences between passing candidates cannot change behaviour."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repo_ai.mission.difference import compare

BASE = 'def f(x):\n    """Double x."""\n    return x + x\n\n\nclass C:\n    k = 1\n\n    def m(self):\n        return 1\n'


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / 'r'
    root.mkdir()
    (root / 'm.py').write_text(BASE)
    (root / 'README.md').write_text('readme\n')
    git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'core.hooksPath=/dev/null']
    subprocess.run([*git, 'init', '-q'], cwd=root, check=True)
    subprocess.run([*git, 'add', '-A'], cwd=root, check=True)
    subprocess.run([*git, 'commit', '-qm', 'b'], cwd=root, check=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True).stdout.strip()
    return root, head


def diff(root: Path, files: dict[str, str]) -> str:
    for rel, text in files.items():
        (root / rel).write_text(text)
    out = subprocess.run(['git', 'diff'], cwd=root, capture_output=True, text=True).stdout
    subprocess.run(['git', 'checkout', '-q', '--', '.'], cwd=root, check=True)
    return out


@pytest.mark.parametrize('variant,kind,where', [
    (BASE.replace('return x + x', 'return  (x + x)  # same'), 'COSMETIC', []),
    (BASE.replace('return x + x', 'return x * 2'), 'SUBSTANTIVE', ['m.py:f']),
    (BASE.replace('Double x.', 'Twice x.'), 'SUBSTANTIVE', ['m.py:f']),  # a docstring is reachable (__doc__)
    (BASE.replace('k = 1', 'k = 2'), 'SUBSTANTIVE', ['m.py:C']),
    (BASE.replace('return 1\n', 'return 2\n'), 'SUBSTANTIVE', ['m.py:C.m']),
    (BASE + '\nY = 1\n', 'SUBSTANTIVE', ['m.py:<module level>']),
])
def test_pairs(repo, variant, kind, where):
    root, head = repo
    a = diff(root, {'m.py': BASE.replace('return x + x', 'return x + x  # fixed')})
    b = diff(root, {'m.py': variant})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert (pair['difference'], pair['where']) == (kind, where)


def test_different_files_and_groups(repo):
    root, head = repo
    one = diff(root, {'m.py': BASE + '# end\n'})
    same = diff(root, {'m.py': BASE + '\n\n# another comment\n'})
    other = diff(root, {'README.md': 'changed\n'})
    found = compare(root, head, {'x': one, 'y': same, 'z': other})
    assert found['groups'] == [['x', 'y'], ['z']]
    assert {tuple(p['candidates']): p['difference'] for p in found['pairs']}[('x', 'z')] == 'SUBSTANTIVE'


def test_a_diff_that_does_not_apply_is_unknown(repo):
    root, head = repo
    good = diff(root, {'m.py': BASE + '# end\n'})
    bad = good.replace('        return 1', '        return 9')  # a context line the frozen file does not have
    assert bad != good
    [pair] = compare(root, head, {'a': good, 'b': bad})['pairs']
    assert pair['difference'] == 'UNKNOWN'
