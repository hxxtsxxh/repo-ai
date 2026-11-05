"""The packaged demo is a real executable, explicitly simulated acceptance flow."""
import json
import shutil
import subprocess
import sys

import pytest
from conftest import cli_env


@pytest.mark.parametrize(('language', 'tournament'), [('python', False), ('node', True)])
def test_demo_exercises_language_and_explanations(tmp_path, language, tournament):
    if language == 'node' and not shutil.which('node'):
        pytest.skip('Node is not installed; executable demo cannot be run')
    root = tmp_path / 'demo'
    argv = [sys.executable, '-m', 'repo_ai.mission.demo', '--directory', str(root), '--language', language]
    if tournament:
        argv.append('--tournament')
    p = subprocess.run(argv, env=cli_env(), capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stdout + p.stderr
    transcript = json.loads((root / 'transcript.json').read_text())
    assert all(r['exit_code'] == 0 for r in transcript)
    assert any('why-test-failed' in r['argv'] for r in transcript)
    passport = json.loads((root / 'passport.json').read_text())
    assert passport['effective_verdict'] == 'PASS'
    assert passport['provider']['simulated'] is True
    if tournament:
        report = json.loads((root / 'comparison.json').read_text())
        assert [r['verdict'] for r in report['candidates']] == ['FAIL', 'PASS']
    # Refuse to overwrite a developer's existing demonstration artifacts.
    second = subprocess.run(argv, env=cli_env(), capture_output=True, text=True, timeout=10)
    assert second.returncode != 0 and 'must be empty' in second.stderr
