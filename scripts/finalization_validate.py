#!/usr/bin/env python3
"""Offline exact-source test manifest and disjoint three-shard validation runner."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=int)
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    os.chdir(source)
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(source / 'src'))
    os.environ['PYTHONPATH'] = str(source / 'src')
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', os.defpath)
    os.environ['REPO_AI_NO_BACKGROUND'] = '1'
    if args.collect or args.worker is not None:
        import pytest
        target = out / ('collection.json' if args.collect else f'shard-{args.worker}.json')
        record = {'exit_code': None, 'collected': [], 'markers': {}, 'outcomes': []}
        class Recording:
            def pytest_collection_modifyitems(self, session, config, items):
                if not args.collect:
                    wanted = set(json.loads((out / 'manifest.json').read_text())['shards'][args.worker])
                    items[:] = [i for i in items if i.nodeid in wanted]
            def pytest_collection_finish(self, session):
                record['collected'] = [i.nodeid for i in session.items]
                record['markers'] = {i.nodeid: [m.name for m in i.iter_markers() if m.name in {'skip', 'skipif', 'xfail'}]
                                     for i in session.items if any(m.name in {'skip', 'skipif', 'xfail'} for m in i.iter_markers())}
                target.write_text(json.dumps(record, indent=2))
            def pytest_runtest_logreport(self, report):
                if report.when == 'call' or report.failed or report.skipped:
                    record['outcomes'].append({'id': report.nodeid, 'when': report.when, 'outcome': report.outcome,
                                               'wasxfail': getattr(report, 'wasxfail', None), 'seconds': report.duration})
                    target.write_text(json.dumps(record, indent=2))
        cmd = ['-q', '--durations=15', '-o', f'cache_dir={out}/cache-{args.worker}']
        cmd += ['--collect-only'] if args.collect else [f'--junitxml={out}/shard-{args.worker}.xml']
        t0 = time.monotonic()
        code = pytest.main(cmd, plugins=[Recording()])
        record.update(exit_code=int(code), seconds=round(time.monotonic()-t0, 3))
        target.write_text(json.dumps(record, indent=2))
        return int(code)
    def git(*words):
        return subprocess.check_output(['git', *words], text=True).strip()
    identity = {'commit': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
                'status': git('status', '--porcelain'), 'python': sys.version, 'executable': sys.executable}
    if identity['status']:
        raise RuntimeError('validation source must be clean')
    (out / 'source.json').write_text(json.dumps(identity, indent=2))
    command = [sys.executable, str(Path(__file__).resolve()), '--source', str(source), '--out', str(out)]
    with (out / 'collection.log').open('w') as log:
        subprocess.run([*command, '--collect'], stdout=log, stderr=subprocess.STDOUT, check=True)
    ids = json.loads((out / 'collection.json').read_text())['collected']
    if not ids or len(set(ids)) != len(ids):
        raise RuntimeError('collection empty or duplicates')
    shards = [ids[i::3] for i in range(3)]
    (out / 'manifest.json').write_text(json.dumps({'source': identity, 'count': len(ids), 'shards': shards}, indent=2))
    jobs = []
    for index in range(3):
        log = (out / f'shard-{index}.log').open('w')
        proc = subprocess.Popen([*command, '--worker', str(index)], stdout=log, stderr=subprocess.STDOUT)
        jobs.append((proc, log))
        print(f'shard {index}: PID {proc.pid}, {len(shards[index])} tests', flush=True)
    try:
        codes = [proc.wait() for proc, _ in jobs]
    finally:
        for proc, log in jobs:
            if proc.poll() is None:
                proc.terminate()
            log.close()
    reports = [json.loads((out / f'shard-{i}.json').read_text()) for i in range(3)]
    outcomes = [o for r in reports for o in r['outcomes']]
    counts = Counter('xfailed' if o['wasxfail'] and o['outcome'] == 'skipped' else o['outcome'] for o in outcomes)
    executed = [o['id'] for o in outcomes]
    exactly_once = Counter(executed) == Counter(ids)
    verdict = {'source': identity, 'collected': len(ids), 'counts': dict(counts), 'exit_codes': codes,
               'exactly_once': exactly_once, 'source_unchanged': git('status', '--porcelain') == '',
               'status': 'PASS' if exactly_once and codes == [0, 0, 0] and not counts['failed'] and not counts['skipped'] else 'FAIL'}
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2), flush=True)
    return 0 if verdict['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
