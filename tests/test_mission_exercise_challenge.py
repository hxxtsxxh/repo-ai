"""Challenge set (independent of abc-v1): visible tests that under-pin behaviour.

Each case has a plausible patch that satisfies the visible tests but is wrong on an unpinned input, and a
correct patch. The detector (change-exercise) is only a disclosure: this records exactly what it can and cannot
tell apart, including a known false alarm, so the signal is not oversold.
"""
import difflib
import shutil

import pytest
from conftest import _git
from repo_ai.mission import exercise

CASES = {
    # name: (path, before, plausible_wrong_after, correct_after, visible_test, command)
    'py-clamp': ('clamp.py',
        'def clamp(x, lo, hi):\n    return x\n',
        'def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    return x\n',
        'def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n',
        'from clamp import clamp\n\n\ndef test_low():\n    assert clamp(-1, 0, 5) == 0\n',
        'python -m pytest -q'),
    'py-dedupe': ('dedupe.py',
        'def dedupe(xs):\n    return list(xs)\n',
        'def dedupe(xs):\n    out = []\n    for x in xs:\n        if x not in out:\n            out.append(x)\n    return out\n',
        'def dedupe(xs):\n    out = []\n    for x in xs:\n        if x not in out:\n            out.append(x)\n    return out\n',
        'from dedupe import dedupe\n\n\ndef test_dup():\n    assert dedupe([1, 1, 2]) == [1, 2]\n',
        'python -m pytest -q'),
    'node-pad': ('pad.js',
        'exports.pad = (s, n) => s;\n',
        'exports.pad = (s, n) => {\n  if (s.length >= n) return s;\n  return " ".repeat(n - s.length) + s;\n};\n',
        'exports.pad = (s, n) => {\n  s = String(s);\n  if (s.length >= n) return s;\n  return " ".repeat(n - s.length) + s;\n};\n',
        "const t = require('node:test'); const a = require('node:assert');\nconst {pad} = require('./pad.js');\nt('p', () => a.equal(pad('a', 3), '  a'));\n",
        'node --test'),
}


def _diff(path, before, after):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f'a/{path}', f'b/{path}'))


def _measure(tmp_path, name, after):
    path, before, _wrong, _right, test, command = CASES[name]
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / path).write_text(after)
    (root / ('test_x.py' if command.startswith('python') else 'x.test.js')).write_text(test)
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'c')
    return exercise.measure(root, command, _diff(path, before, after))


@pytest.mark.parametrize('name', ['py-clamp', 'node-pad'])
def test_unpinned_guard_branch_is_disclosed_as_partial(tmp_path, name):
    """The *correct* patch has a guard the visible tests never run: disclosed, because it is unconstrained."""
    if name.startswith('node') and shutil.which('node') is None:
        pytest.skip('node not installed')
    rec = _measure(tmp_path, name, CASES[name][3])
    assert rec['assurance'] == 'PARTIAL' and rec['unexercised'], rec


def test_recorded_blind_spots_line_coverage_cannot_tell_wrong_from_right(tmp_path):
    """Honest limit: an incomplete patch whose every changed line runs (clamp without the upper guard) is FULL.
    The detector measures what the tests exercise, not correctness, and must never be used as a verdict."""
    assert _measure(tmp_path / 'a', 'py-clamp', CASES['py-clamp'][2])['assurance'] == 'FULL'
    assert _measure(tmp_path / 'b', 'py-dedupe', CASES['py-dedupe'][2])['assurance'] == 'FULL'
