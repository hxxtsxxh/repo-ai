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


def test_no_same_code_claim_when_the_scratch_dir_sits_inside_a_repository(repo, tmp_path, monkeypatch):
    """The shortlist regression (adversarial review finding A), through compare: inside an enclosing checkout a
    `git apply` that skipped every path made different code look identical."""
    import tempfile
    root, head = repo
    outer = tmp_path / 'outer'
    outer.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=outer, check=True)
    monkeypatch.setattr(tempfile, 'tempdir', str(outer))
    a = diff(root, {'m.py': BASE.replace('return x + x', 'return x + 1')})
    b = diff(root, {'m.py': BASE.replace('return x + x', 'raise SystemExit')})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['difference'] == 'SUBSTANTIVE' and pair['where'] == ['m.py:f']


def test_a_coding_cookie_is_never_cosmetic(repo):
    root, head = repo
    a = diff(root, {'m.py': '# coding: latin-1\n' + BASE})
    b = diff(root, {'m.py': '# coding: cp1251\n' + BASE})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['difference'] == 'SUBSTANTIVE'


def test_a_file_too_deep_to_parse_is_never_a_crash_or_a_same_code_claim(repo):
    root, head = repo
    deep = 'X = ' + ' + '.join(['1'] * 5000) + '\n'
    a = diff(root, {'m.py': BASE + deep})
    b = diff(root, {'m.py': BASE + deep.replace('X =', 'Y =')})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['difference'] == 'SUBSTANTIVE' and pair['where'] == ['m.py']  # rebuilt, compared by file name
    from repo_ai.mission.shortlist import code_fingerprint
    assert code_fingerprint({'m.py': (BASE + deep).encode()}) is None


def test_a_shared_non_python_change_does_not_hide_a_cosmetic_python_difference(repo):
    """Queue row 29: both candidates edit README.md identically and m.py differently only in formatting."""
    root, head = repo
    a = diff(root, {'m.py': BASE.replace('return x + x', 'return x + x  # fixed'), 'README.md': 'fixed\n'})
    b = diff(root, {'m.py': BASE.replace('return x + x', 'return  (x + x)'), 'README.md': 'fixed\n'})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['difference'] == 'COSMETIC'


def test_a_non_python_file_changed_differently_is_still_substantive(repo):
    root, head = repo
    a = diff(root, {'m.py': BASE + '# a\n', 'README.md': 'one\n'})
    b = diff(root, {'m.py': BASE + '# b\n', 'README.md': 'two\n'})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['difference'] == 'SUBSTANTIVE' and pair['where'] == ['README.md']


@pytest.mark.parametrize('freshness', ['fresh', 'stale'])
def test_a_stale_comparison_never_repeats_its_recorded_next_step(freshness):
    """Queue row 29: "apply the winner" written for evidence that no longer holds must not be printed as advice (in
    `repo-ai compare ID` and `repo-ai mission status ID --json`, both read through runtime.status)."""
    from repo_ai.mission import runtime, tournament
    recorded = 'repo-ai apply m1 (the only distinct passing candidate)'
    comp = runtime.stale_comparison_step({'winner': None, 'next_step': recorded, 'candidates': []}, freshness)
    text = tournament.render_comparison({**comp, 'freshness': freshness})
    if freshness == 'fresh':
        assert comp['next_step'] == recorded and 'Next: ' + recorded in text
    else:
        assert comp['recorded_next_step'] == recorded and recorded not in text and 'run the tournament again' in text
    old = runtime.stale_comparison_step({'candidates': []}, freshness)  # a record from before next_step existed
    assert ('next_step' in old) == (freshness != 'fresh') and 'recorded_next_step' not in old



GETTER = ('class C:\n    @property\n    def x(self):\n        return {v}\n\n    @x.setter\n    def x(self, value):\n'
          '        pass\n')


@pytest.mark.parametrize('a_text,b_text', [
    (GETTER.format(v=2), GETTER.format(v=3)),  # the getter's body; the setter (same name) last
    ('def f():\n    return 1\n\n\ndef g():\n    return 2\n', 'def g():\n    return 2\n\n\ndef f():\n    return 1\n'),
    ('# -*- coding: utf-8 -*-\nx = 1+1\n', '# -*- coding: utf-8 -*-\nx = (1 + 1)\n'),  # cookie: by bytes
])
def test_a_substantive_pair_always_names_where_it_differs(repo, a_text, b_text):
    root, head = repo
    a = diff(root, {'m.py': a_text, 'README.md': 'same\n'})
    b = diff(root, {'m.py': b_text, 'README.md': 'same\n'})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['difference'] == 'SUBSTANTIVE' and pair['where'], pair
    assert all(w.startswith('m.py') for w in pair['where']), pair


def test_a_duplicate_definition_name_is_named_when_it_differs(repo):
    root, head = repo
    a = diff(root, {'m.py': GETTER.format(v=2)})
    b = diff(root, {'m.py': GETTER.format(v=3)})
    [pair] = compare(root, head, {'a': a, 'b': b})['pairs']
    assert pair['where'] == ['m.py:C.x'], pair


def test_shortlist_groups_by_the_same_rule(repo):
    from repo_ai.mission.shortlist import code_identity
    one = {'m.py': b'x = 1  # a\n', 'README.md': b'same\n'}
    two = {'m.py': b'x=1\n', 'README.md': b'same\n'}
    assert code_identity(one) == code_identity(two)
    assert code_identity(one) != code_identity({**two, 'README.md': b'other\n'})
