#!/usr/bin/env python3
"""Run installed-wheel replay journeys on existing upstream snapshots, never a model.

Usage: INSTALLED_PYTHON scripts/finalization_journeys.py --source REPO --out EMPTY_DIR
Uses previously evaluated upstream bugs; this is integration, NOT a held-out benchmark.
Prerequisite: the installed interpreter's environment needs `pytest` (Cachetools) and `node` (Marked). Without pytest the
baseline exits 1 with no reported outcomes and repo-ai correctly returns INCONCLUSIVE.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        p.error('output must be new or empty')
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith('REPO_AI_')}
    env['REPO_AI_NO_BACKGROUND'] = '1'
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', os.defpath)
    summaries = []
    for group, case, base, command in [('tasks', 'oss-ct-002', 'oss-cachetools', 'python -m pytest'),
                                       ('sealed-v2', 'v2-mk-001', 'v2-marked', 'node --test')]:
        target = out / base
        repo = target / 'checkout'
        source = args.source.resolve() / 'benchmarks' / group
        task_dir = source / 'cases' / case
        task = json.loads((task_dir / 'task.json').read_text())
        shutil.copytree(source / 'bases' / base, repo, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        originals = {name: (repo / name).read_text() for name in task['gold_files']}
        for edit in task['setup']:
            (repo / edit['file']).write_text(edit['create'])
        # Existing upstream regression oracle frozen BEFORE candidate edits.
        for hidden in task['hidden']:
            shutil.copyfile(task_dir / hidden['src'], repo / hidden['dest'])
        transcript = []
        def command_run(argv, expected=(0,), repo=repo, target=target, transcript=transcript):
            result = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=900)
            transcript.append({'argv': argv, 'exit_code': result.returncode,
                               'stdout': result.stdout, 'stderr': result.stderr})
            (target / 'transcript.json').write_text(json.dumps(transcript, indent=2))
            if result.returncode not in expected:
                raise RuntimeError(f'{argv}: exit {result.returncode}; inspect {target}/transcript.json')
            return result
        def cli(*words, expected=(0,)):
            return command_run([sys.executable, '-m', 'repo_ai', *words], expected)
        for words in [('init', '-q'), ('add', '-A'), ('-c', 'user.name=journey', '-c', 'user.email=local@example.invalid',
                                                  'commit', '-qm', 'frozen upstream regression reproduction')]:
            command_run(['git', *words])
        baseline_hashes = {str(f.relative_to(repo)): hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in repo.rglob('*') if f.is_file() and '.git' not in f.parts}
        (target / 'selection.json').write_text(json.dumps({'case': case, 'attribution': task['attribution'],
            'reason': 'Existing upstream multi-file project with historical bug and regression traps; no new downloads',
            'mode': 'REPLAY; previously used development data, not a fresh holdout',
            'baseline_files': baseline_hashes}, indent=2))
        for name, files in [('robust', originals), ('superficial', dict(originals))]:
            if name == 'superficial':
                if base == 'oss-cachetools':
                    rel = task['gold_files'][0]
                    # Plausible exception broadening still misses StopIteration/custom choices.
                    files[rel] = (repo / rel).read_text().replace('except IndexError:', 'except (IndexError, ValueError):')
                else:
                    # Fixes the hook API but fails to bind the per-invocation block mode.
                    files['src/Instance.ts'] = (repo / 'src/Instance.ts').read_text()
            edits = [{'path': rel, 'before_sha256': hashlib.sha256((repo / rel).read_bytes()).hexdigest(),
                      'after': body} for rel, body in files.items() if body != (repo / rel).read_text()]
            (target / (name + '.json')).write_text(json.dumps({'schema': 'repo-ai.replay/1',
                'label': name + ' offline historical patch, not model generated', 'edits': edits}))
        cli('quickstart')
        cli('agents', 'list', '--json')
        cli('do', task['prompt'], '--dry-run', '--json')
        write_args = [v for rel in task['gold_files'] for v in ['--allow-write', rel]]
        result = cli('do', task['prompt'], '--agent', 'replay', '--run', '--test-command', command,
                     '--max-seconds', '600', *write_args, '--candidate', str(target / 'superficial.json'),
                     '--candidate', str(target / 'robust.json'), '--json', expected=(0, 2))
        comparison = json.loads(result.stdout)
        (target / 'comparison.json').write_text(json.dumps(comparison, indent=2))
        winner = comparison.get('winner')
        summary = {'project': base, 'comparison': comparison['id'], 'winner': winner,
                   'verdict': comparison.get('verdict'), 'live': False, 'model_cost_usd': 0}
        if winner:
            for words in [('mission', 'status'), ('why',), ('why-test-failed',), ('replay',), ('futures',)]:
                cli(*words, winner, '--json')
            cli('compare', comparison['id'])
            capsule = cli('handoff', winner, '--to', 'replay', '--json')
            capsule_file = target / 'handoff.json'
            capsule_file.write_text(capsule.stdout)
            cli('handoff', '--verify', str(capsule_file), '--json')
            cli('apply', winner, '--json')
            cli('undo', winner, '--json')
            summary['restored'] = all(hashlib.sha256((repo / rel).read_bytes()).hexdigest() == sha
                                      for rel, sha in baseline_hashes.items())
            if not summary['restored']:
                raise RuntimeError('undo did not restore source snapshot')
        cli('privacy', 'audit', '--json')
        summaries.append(summary)
        (out / 'summary.json').write_text(json.dumps(summaries, indent=2))
        print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
