"""A differential probe for an abstained tournament (mission section 5B): one predeclared, developer-written script
runs against the base and against each distinct passing candidate, in the mission's own test sandbox (same image,
network denied), and what each prints is compared.

Why: when two candidates pass the same frozen tests, the tests cannot tell them apart. A probe asks a question the
tests did not (edge-case inputs, a property), and its answer is a neutral observation: the candidates behave the
SAME on it, or DIFFER, with the first line that differs. It is not a verdict on which candidate is right: the
developer reads the outputs and decides. No model runs, nothing is applied, and the script is never shown to a
provider (the candidates already exist). Its sha256 is reported with the result.

The base runs twice: a probe whose own output changes between runs (time, randomness, addresses) cannot compare
anything, and the result says so.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from .. import gitbin
from ..security import redact_text

SCHEMA = 'repo-ai.tournament-probe/1'
MAX_PROBE_BYTES = 64_000
MAX_SHOWN = 4_000  # characters of each output kept in the report (its sha256 covers all of it)
PROBE_NAME = 'repo-ai-probe.py'


def read_probe(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'probe must be a regular file: {path}')
    data = path.read_bytes()
    if len(data) > MAX_PROBE_BYTES:
        raise ValueError(f'probe is larger than {MAX_PROBE_BYTES} bytes')
    try:
        compile(data, str(path), 'exec')
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f'probe is not valid Python: {exc}') from exc
    return data


def _apply(ws_path: Path, diff: str) -> str | None:
    """Apply a recorded candidate diff to a disposable base checkout. git is confined to the workspace (the ceiling is
    its parent: an enclosing checkout around the workspaces directory would otherwise make `git apply` skip every path
    and still exit 0), and every file the diff names must actually change."""
    from .shortlist import _git_env, diff_stats
    files = diff_stats(diff)['files']
    if not files:
        return 'the candidate diff names no files'

    def state(rel: str) -> str | None:
        target = ws_path / rel
        return hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() and not target.is_symlink() else None

    before = {rel: state(rel) for rel in files}
    done = subprocess.run([gitbin.git(), 'apply', '--whitespace=nowarn', '-'], cwd=ws_path, input=diff.encode(),
                          capture_output=True, timeout=60, env=_git_env(ws_path.parent))
    if done.returncode != 0:
        return 'the candidate diff does not apply to the base: ' + \
            redact_text(done.stderr.decode('utf-8', 'replace'))[:300]
    if any(state(rel) == before[rel] for rel in files):
        return 'the candidate diff did not change every file it names; it was not applied as recorded'
    return None


def _run_one(root: Path, base: str, diff: str | None, probe: bytes, contract: dict[str, Any],
             timeout_s: float) -> dict[str, Any]:
    from ..verify import isolate
    from ..verify.execute import get_executor, release
    from ..verify.runner import parse_command
    from .verification import container_layout, environment
    sandbox_pref, image = environment(contract)
    runner = parse_command(str((contract.get('acceptance') or ['python -m pytest'])[0]))
    out: dict[str, Any] = {}
    with isolate.materialize_commit(root, base, label='tournament-probe', dependencies=True) as ws:
        if diff:
            problem = _apply(ws.path, diff)
            if problem:
                return {'error': problem}
        # run as `python repo-ai-probe.py` from where the tests run (their working directory and environment)
        where = (ws.path / runner.cwd if runner.cwd else ws.path).resolve()
        inside = ws.path.resolve()
        if where != inside and inside not in where.parents or not where.is_dir():
            return {'error': f'the tests\' directory ({runner.cwd}) is not a directory inside the checkout'}
        try:
            fd = os.open(where / PROBE_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except OSError:
            return {'error': f'cannot place the probe where the tests run ({runner.cwd or "."}/{PROBE_NAME})'}
        with os.fdopen(fd, 'wb') as handle:
            handle.write(probe)
        container_layout(ws.path, runner, list(ws.files), sandbox_pref)
        executor = get_executor(ws.path, sandbox_pref, 'python', timeout_s=timeout_s, interpreter_root=root,
                                image=image)
        try:
            bound = executor.in_workspace(ws)
            res = bound.run(['python', PROBE_NAME], cwd=runner.cwd,
                            env=runner.env, timeout_s=timeout_s, toolchain='python')
        finally:
            release([executor])
        stdout = res.stdout or ''
        out = {'exit_code': res.exit_code, 'timed_out': bool(res.timed_out), 'backend': res.backend,
               'image': image or None, '_stdout': stdout,
               'stdout_sha256': hashlib.sha256(stdout.encode('utf-8', 'replace')).hexdigest(),
               'stdout': redact_text(stdout[:MAX_SHOWN]), 'stdout_truncated': len(stdout) > MAX_SHOWN,
               'stderr_tail': redact_text((res.stderr or '')[-600:]),
               'notes': [redact_text(str(n))[:300] for n in (getattr(res, 'notes', None) or [])][:5]}
    return out


def _key(r: dict[str, Any]) -> tuple[Any, ...]:
    return (r.get('exit_code'), r.get('stdout_sha256'))


def _first_difference(a: str, b: str) -> dict[str, Any]:
    """The first differing line of two complete outputs (not the shortened ones shown)."""
    la, lb = a.splitlines(), b.splitlines()
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else '<no line>'
        y = lb[i] if i < len(lb) else '<no line>'
        if x != y:
            return {'line': i + 1, 'a': redact_text(x)[:300], 'b': redact_text(y)[:300]}
    if a != b:
        return {'line': None, 'what': 'line endings or a trailing newline only', 'a': '', 'b': ''}
    return {'line': None, 'what': 'exit status only', 'a': '', 'b': ''}


def run_probe(root: Path, shortlist: dict[str, Any], probe_path: Path, timeout_s: float = 60) -> dict[str, Any]:
    """Run the probe for a shortlist with at least two distinct passing candidates and no blockers."""
    from .runtime import status
    if not 0 < timeout_s <= 600:
        raise ValueError('probe timeout must be between 0 and 600 seconds')
    probe = read_probe(probe_path)
    report: dict[str, Any] = {'schema': SCHEMA, 'probe_sha256': hashlib.sha256(probe).hexdigest(),
                              'probe': str(probe_path), 'verdict': 'INCONCLUSIVE', 'reasons': [],
                              'base': None, 'candidates': [], 'groups': [], 'applies_nothing': True,
                              'limitations': ['a probe observes behaviour on the inputs it chooses (its stdout and '
                                              'exit status; stderr is not compared); SAME is not equivalence and '
                                              'DIFFER does not say which candidate is right']}
    rows = shortlist.get('candidates') or []
    if shortlist.get('blockers') or len(rows) < 2:
        report['reasons'].append('a probe needs at least two distinct passing candidates of a controlled comparison')
        return report
    states = [status(root, r['id']) for r in rows]
    contracts = [s.get('contract') or {} for s in states]
    frozen = {(c.get('base'), c.get('sandbox') or 'auto', c.get('image') or '', tuple(c.get('acceptance') or []))
              for c in contracts}
    if len(frozen) != 1:
        report['reasons'].append('the candidates were not frozen with the same base, test environment and command')
        return report
    for row, state in zip(rows, states, strict=True):
        diff = state.get('diff') or ''
        if (state.get('state') != 'COMPLETE' or hashlib.sha256(diff.encode()).hexdigest() != row.get('diff_sha256')
                or not diff.strip()):
            report['reasons'].append(f'{row["id"]}: its recorded diff is not the one the shortlist listed, or it no '
                                     'longer holds a complete result')
            return report
    contract, base = contracts[0], str(contracts[0].get('base') or '')

    def attempt(diff: str | None) -> dict[str, Any]:
        from .. import sandbox
        from ..verify import isolate
        try:
            return _run_one(root, base, diff, probe, contract, timeout_s)
        except (sandbox.SandboxUnavailable, isolate.IsolationError, OSError, ValueError,
                subprocess.TimeoutExpired) as exc:
            return {'error': redact_text(str(exc))[:300]}

    first, again = attempt(None), attempt(None)
    report['base'] = {k: v for k, v in first.items() if k != '_stdout'}
    problems = [f'base: {r["error"]}' for r in (first, again) if r.get('error')]
    problems += ['the probe timed out at the base' for r in (first, again) if r.get('timed_out')]
    if not problems and (first.get('exit_code') != 0 or not first.get('_stdout', '').strip()):
        # a probe that cannot even run on the base (an import error, a crash) would make every candidate look alike
        problems.append(f'the probe did not run cleanly at the base (exit {first.get("exit_code")}'
                        + (', no output' if not first.get('_stdout', '').strip() else '') + '); it must exit 0 and '
                        'print something there: ' + (first.get('stderr_tail') or '')[-300:])
    if not problems and _key(first) != _key(again):
        problems.append('the probe printed different output on two runs of the same base (time, randomness or '
                        'addresses in its output?); it cannot compare candidates')
    full: dict[str, str] = {}
    for row, state in zip(rows, states, strict=True):
        res = attempt(state.get('diff') or '')
        full[row['id']] = res.pop('_stdout', '')
        report['candidates'].append({'id': row['id'], 'provider': row.get('provider'), **res})
        if res.get('error'):
            problems.append(f'{row["id"]}: {res["error"]}')
        elif res.get('timed_out'):
            problems.append(f'{row["id"]}: the probe timed out')
    if problems:
        report['reasons'] += problems
        return report
    groups: dict[tuple[Any, ...], list[str]] = {}
    for c in report['candidates']:
        groups.setdefault(_key(c), []).append(c['id'])
    report['groups'] = [{'ids': ids, 'exit_code': k[0], 'stdout_sha256': k[1],
                         'same_as_base': k == _key(first)} for k, ids in groups.items()]
    if len(groups) == 1:
        report['verdict'] = 'SAME'
        report['reasons'].append('every candidate printed the same output and exit status on this probe')
    else:
        report['verdict'] = 'DIFFER'
        a, b = report['candidates'][0], next(c for c in report['candidates'] if _key(c) != _key(report['candidates'][0]))
        diff = _first_difference(full[a['id']], full[b['id']])
        report['first_difference'] = {'between': [a['id'], b['id']], **diff,
                                      'exit_codes': [a.get('exit_code'), b.get('exit_code')]}
        report['reasons'].append(f'the candidates behave differently on this probe ({len(groups)} groups)')
    return report


def render(report: dict[str, Any]) -> str:
    lines = [f"Probe {report['probe']} (sha256 {report['probe_sha256'][:12]}): {report['verdict']}"]
    lines += [f'  {r}' for r in report['reasons']]
    for g in report.get('groups') or []:
        lines.append(f"  group exit {g['exit_code']}{' (same as the base)' if g['same_as_base'] else ''}: "
                     + ', '.join(g['ids']))
    fd = report.get('first_difference')
    if fd:
        where = f"line {fd['line']}" if fd['line'] else fd.get('what', 'exit status only')
        lines.append(f"  first difference ({where}) between {fd['between'][0]} and {fd['between'][1]}:")
        lines.append(f"    {fd['between'][0]}: {fd['a']}")
        lines.append(f"    {fd['between'][1]}: {fd['b']}")
    lines.append('  ' + report['limitations'][0])
    return '\n'.join(lines)
