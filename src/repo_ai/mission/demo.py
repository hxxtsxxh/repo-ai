"""Create and execute an explicitly simulated, zero-model-cost local acceptance demo.

Run: python -m repo_ai.mission.demo --directory /path/to/new-empty-directory
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .runtime import git


def run_demo(
    directory: Path,
    *,
    language: str = 'python',
    tournament: bool = False,
    quiet: bool = False,
) -> dict[str, Any]:
    root = directory.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('directory must be empty; existing files will not be overwritten')
    root.mkdir(parents=True, exist_ok=True)
    repo = root / 'checkout'
    repo.mkdir()
    if language == 'python':
        source, command = 'charge.py', 'python -m pytest'
        original = 'def charge(amount, retries):\n    return amount * (retries + 1)\n'
        correct = 'def charge(amount, retries):\n    return amount\n'
        superficial = 'def charge(amount, retries):\n    return 10\n'
        tests = 'from charge import charge\n\ndef test_retry():\n    assert charge(10, 2) == 10\n\ndef test_once():\n    assert charge(10, 0) == 10\n'
        if tournament:
            tests += '\ndef test_other_amount():\n    assert charge(7, 2) == 7\n'
        (repo / 'test_charge.py').write_text(tests)
        (repo / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    else:
        source, command = 'charge.cjs', 'node --test'
        original = 'exports.charge = (amount, retries) => amount * (retries + 1);\n'
        correct = 'exports.charge = (amount, retries) => amount;\n'
        superficial = 'exports.charge = (amount, retries) => 10;\n'
        tests = ("const {test} = require('node:test');\nconst assert = require('node:assert/strict');\n"
                 "const {charge} = require('./charge.cjs');\n"
                 "test('retry', () => assert.equal(charge(10, 2), 10));\n"
                 "test('once', () => assert.equal(charge(10, 0), 10));\n")
        if tournament:
            tests += "test('other amount', () => assert.equal(charge(7, 2), 7));\n"
        (repo / 'charge.test.cjs').write_text(tests)
        (repo / 'package.json').write_text('{"name":"repo-ai-offline-demo","private":true}\n')
    (repo / source).write_text(original)
    git(repo, 'init', '-q')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'known duplicate-charge fixture')
    proposal = root / 'simulated-proposal.json'

    def write_proposal(path: Path, after: str) -> None:
        path.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'simulated fixture agent; NOT live AI',
                                   'edits': [{'path': source, 'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
                                              'after': after}]}, indent=2))

    write_proposal(proposal, correct)
    transcript: list[dict[str, Any]] = []

    def run(*argv: str) -> dict[str, Any]:
        cmd = [sys.executable, '-m', 'repo_ai', *argv, '-C', str(repo), '--json']
        if not quiet:
            print('$ ' + shlex.join(cmd), flush=True)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        transcript.append({'argv': cmd, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        if p.returncode:
            raise RuntimeError(p.stdout + p.stderr)
        return json.loads(p.stdout)

    comparison_id: str | None = None
    try:
        preview = run('do', 'Fix duplicate charges caused by retries', '--dry-run')
        if not quiet:
            print('Default route:', preview['decision'], '(no execution)')
        selection = ['--replay', str(proposal)]
        if tournament:
            alternative = root / 'superficial-proposal.json'
            write_proposal(alternative, superficial)
            selection = ['--candidate', str(alternative), '--candidate', str(proposal)]
        result = run('do', 'Fix duplicate charges in ' + source, '--agent', 'replay', *selection,
                     '--allow-write', source, '--run', '--test-command', command)
        if tournament:
            comparison_id = result['id']
            (root / 'comparison.json').write_text(json.dumps(result, indent=2))
            result = run('mission', 'status', result['winner'])
        if not quiet:
            print('Verdict:', result['effective_verdict'], '| baseline failures:', result['baseline']['failed'],
                  '| candidate failures:', result['candidate']['failed'])
            print(result['diff'])
        capsule = run('handoff', result['id'])
        explanation = run('why', result['id'])
        diagnosis = run('why-test-failed', result['id'])
        (root / 'explanation.json').write_text(json.dumps(explanation, indent=2))
        (root / 'diagnosis.json').write_text(json.dumps(diagnosis, indent=2))
        (root / 'handoff.json').write_text(json.dumps(capsule, indent=2))
        (root / 'passport.json').write_text(json.dumps(result, indent=2))
        assert (repo / source).read_text() == original
        if not quiet:
            print('Original checkout unchanged; handoff contains no source code; provider was simulated.')
    finally:
        (root / 'transcript.json').write_text(json.dumps(transcript, indent=2))

    return {
        'schema': 'repo-ai.mission-demo/1',
        'directory': str(root),
        'checkout': str(repo),
        'language': language,
        'tournament': tournament,
        'comparison_id': comparison_id,
        'mission': result['id'],
        'verdict': result['effective_verdict'],
        'baseline_failed': result['baseline']['failed'],
        'candidate_failed': result['candidate']['failed'],
        'original_unchanged': (repo / source).read_text() == original,
        'simulated': True,
        'cost_usd': 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True, help='new or empty directory owned by this demo')
    parser.add_argument('--language', choices=['python', 'node'], default='python')
    parser.add_argument('--tournament', action='store_true', help='compare a superficially plausible fix with a correct fixture fix')
    args = parser.parse_args()
    try:
        run_demo(args.directory, language=args.language, tournament=args.tournament, quiet=False)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
