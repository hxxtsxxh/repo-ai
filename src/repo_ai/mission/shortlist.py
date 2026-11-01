"""Useful output when a tournament abstains: an evidence table, a shortlist and an explicit, labelled preference.

Abstention stays the default (`strict`). Nothing here selects, ranks by an LLM, blends or applies a patch.
A shortlist lists only candidates that still hold a FRESH, complete PASS under the one controlled comparison.
An optional named policy may *prefer* one shortlisted candidate. That is a POLICY_PREFERENCE (a stated tie
rule the user opted into), never a correctness claim, and it is applied only by an explicit `repo-ai apply`.
Policies are predeclared here; they cannot be supplied by a model or by the repository under test.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import gitbin

SCHEMA = 'repo-ai.shortlist/1'
POLICIES = ('strict', 'smallest-diff')
LABEL = 'POLICY_PREFERENCE'
DISCLAIMER = ('A policy preference is a stated tie rule, not evidence that the candidate is correct; '
              'every shortlisted candidate passed the same frozen tests and none is known to be better.')


def diff_stats(diff: str) -> dict[str, Any]:
    files: list[str] = []
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith('+++ '):
            name = line[4:].strip()
            files.append(name[2:] if name.startswith('b/') else name)
        elif line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1
    return {'files': sorted(set(files)), 'added': added, 'removed': removed, 'changed_lines': added + removed}


_UNSUPPORTED_DIFF = re.compile(r'^(?:new file mode|deleted file mode|rename from|copy from|old mode|new mode|'
                               r'Binary files|GIT binary patch)', re.M)
_CODING_COOKIE = re.compile(rb'^[ \t\f]*#.*?coding[:=]', re.M)


def _git_env(ceiling: Path) -> dict[str, str]:
    """git confined to the scratch directory: no enclosing repository is discovered (a TMPDIR inside a
    checkout made `git apply` skip every path and still exit 0), and no inherited GIT_* override applies."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CEILING_DIRECTORIES=str(ceiling), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return env


def _post_images(root: Path, base: str, diff: str, files: list[str]) -> dict[str, bytes] | None:
    """The changed files after the candidate diff, rebuilt from the base commit in a scratch directory.
    None when anything cannot be reconstructed exactly (then no equivalence is claimed): created, deleted,
    renamed, mode-changed or binary files, a base that is not a commit id, or a file the diff did not change."""
    if not re.fullmatch(r'[0-9a-f]{7,64}', base or '') or not files or len(files) > 20 or _UNSUPPORTED_DIFF.search(diff):
        return None
    if diff.count('\ndiff --git ') + diff.startswith('diff --git ') != len(files):
        return None  # a file section diff_stats did not see (for example one without a +++ line)
    with tempfile.TemporaryDirectory(prefix='repo-ai-shortlist-') as tmp:
        work = Path(tmp) / 'tree'
        work.mkdir()
        before: dict[str, bytes] = {}
        for rel in files:
            shown = subprocess.run([gitbin.git(), '-c', 'core.hooksPath=/dev/null', 'show', '--end-of-options', f'{base}:{rel}'],
                                   cwd=root, capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
            if shown.returncode != 0:
                return None  # a base we cannot read: no claim
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(shown.stdout)
            before[rel] = shown.stdout
        applied = subprocess.run([gitbin.git(), 'apply', '--whitespace=nowarn', '-'], cwd=work, input=diff.encode(),
                                 capture_output=True, timeout=30, env=_git_env(Path(tmp)))
        if applied.returncode != 0:
            return None
        after = {rel: (work / rel).read_bytes() for rel in files if (work / rel).is_file()}
        if set(after) != set(files) or any(after[rel] == before[rel] for rel in files):
            return None  # the diff did not change every file it names: the rebuild is not trustworthy
        return after


def code_fingerprint(images: dict[str, bytes]) -> str | None:
    """A digest of the Python syntax trees of every changed file (comments, formatting and line positions
    ignored; docstrings and every other literal included). None when any changed file is not parseable UTF-8
    Python, or declares a source encoding (the same bytes can then mean different strings)."""
    parts = []
    for rel in sorted(images):
        if not rel.endswith('.py') or _CODING_COOKIE.search(b'\n'.join(images[rel].splitlines()[:2])):
            return None
        try:
            tree = ast.parse(images[rel].decode('utf-8'))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            return None
        parts.append(rel + '\0' + ast.dump(tree, include_attributes=False))
    return hashlib.sha256('\0'.join(parts).encode()).hexdigest() if parts else None


def _row(root: Path, cand: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    from .runtime import status
    cid = cand.get('id')
    if not cid:
        return None, 'candidate was never observed'
    try:
        state = status(root, cid)
    except (ValueError, OSError):
        return None, 'candidate record unavailable'
    if state.get('freshness') != 'fresh':
        return None, 'candidate evidence is stale: ' + '; '.join(state.get('freshness_reasons', [])[:2])
    if state.get('state') != 'COMPLETE' or state.get('effective_verdict') != 'PASS':
        return None, 'candidate does not hold a fresh complete PASS'
    diff = state.get('diff') or ''
    if not diff.strip():
        return None, 'empty candidate diff'
    stats = diff_stats(diff)
    base = str((state.get('contract') or {}).get('base') or '')
    images = _post_images(root, base, diff, stats['files'])
    return {'id': cid, 'provider': cand.get('provider'), 'diff_sha256': state.get('diff_sha256'),
            **stats, 'code_fingerprint': code_fingerprint(images) if images is not None else None,
            'cost_usd': cand.get('cost_usd'),
            'cost_status': cand.get('cost_status', 'UNKNOWN'),
            'claims': (state.get('claims') or {}).get('headline'),
            'provider_label': cand.get('provider_label')}, None


def build(root: Path, report: dict[str, Any], policy: str = 'strict') -> dict[str, Any]:
    """Pure read of already recorded evidence. Runs no provider and no test."""
    if policy not in POLICIES:
        raise ValueError('unknown decision policy: ' + str(policy) + ' (choose ' + ', '.join(POLICIES) + ')')
    root = root.resolve()
    excluded: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cand in report.get('candidates', []):
        if cand.get('verdict') != 'PASS':
            excluded.append({'id': cand.get('id'), 'provider': cand.get('provider'),
                             'why': f"verdict {cand.get('verdict')}"})
            continue
        if cand.get('equivalent_to'):
            excluded.append({'id': cand.get('id'), 'provider': cand.get('provider'),
                             'why': 'byte-identical to ' + str(cand['equivalent_to'])})
            continue
        row, why = _row(root, cand)
        if row is None or row['diff_sha256'] in seen:
            excluded.append({'id': cand.get('id'), 'provider': cand.get('provider'), 'why': why or 'duplicate diff'})
            continue
        seen.add(row['diff_sha256'])
        rows.append(row)
    blockers: list[str] = []
    if report.get('freshness', 'fresh') != 'fresh':
        blockers.append('comparison is not fresh: ' + '; '.join(report.get('freshness_reasons', [])[:2]))
        excluded += [{'id': r['id'], 'provider': r['provider'], 'why': 'comparison not fresh'} for r in rows]
        rows = []
    # Every arm must have been observed under the identical frozen tests, otherwise the comparison is not controlled.
    uncontrolled = [c for c in report.get('candidates', []) if c.get('verdict') not in {'PASS', 'FAIL'}]
    if uncontrolled:
        blockers.append(f'{len(uncontrolled)} arm(s) were not cleanly observed (crash, block, inconclusive); '
                        'the comparison is not controlled, so no candidate is preferred')
    shared = set.intersection(*(set(r['files']) for r in rows)) if rows else set()
    for row in rows:
        row['distinguishing_files'] = sorted(set(row['files']) - shared)
    out: dict[str, Any] = {'schema': SCHEMA, 'policy': policy, 'candidates': rows, 'excluded': excluded,
                           'blockers': blockers, 'preferred': None, 'label': None,
                           'next': None, 'applies_nothing': True}
    if report.get('winner'):
        out['next'] = f"repo-ai apply {report['winner']}"
        out['note'] = 'the comparison already has a single controlled winner; no policy is needed'
        return out
    if not rows:
        out['note'] = 'no candidate holds a fresh controlled PASS; nothing to shortlist'
        return out
    if len(rows) == 1:
        out['note'] = 'one candidate passed but the comparison was not controlled; inspect the blockers before applying'
        out['next'] = f"repo-ai why {rows[0]['id']}"
        return out
    out['note'] = (f'{len(rows)} distinct candidates passed the same frozen tests; the tests cannot tell them apart. '
                   'Review the diffs, then apply one explicitly.')
    groups: dict[str, list[str]] = {}
    for row in rows:
        if row.get('code_fingerprint'):
            groups.setdefault(row['code_fingerprint'], []).append(row['id'])
    out['same_code'] = [ids for ids in groups.values() if len(ids) > 1]
    if out['same_code'] and len(out['same_code'][0]) == len(rows):
        out['note'] += (' All of them have identical Python syntax trees in every changed file: they differ only in '
                        'comments, formatting or layout, so choosing between them does not change the code.')
    elif out['same_code']:
        out['note'] += (' Some candidates have identical Python syntax trees (they differ only in comments or '
                        'formatting): ' + '; '.join(' = '.join(ids) for ids in out['same_code']) + '.')
    out['next'] = 'repo-ai why <candidate-id>  (inspect), then repo-ai apply <candidate-id>'
    if policy == 'smallest-diff' and not blockers:
        best = min(r['changed_lines'] for r in rows)
        tied = [r for r in rows if r['changed_lines'] == best]
        if len(tied) == 1:
            out.update(preferred=tied[0]['id'], label=LABEL, disclaimer=DISCLAIMER,
                       rule='smallest-diff: fewest added+removed lines among distinct passing candidates',
                       next=f"repo-ai apply {tied[0]['id']}  # only if you accept the policy preference")
        else:
            out['note'] += f' Policy smallest-diff is tied between {len(tied)} candidates; no preference is made.'
    elif policy == 'smallest-diff':
        out['note'] += ' Policy smallest-diff declined to prefer anything because the comparison has blockers.'
    return out


def render(sl: dict[str, Any]) -> str:
    lines = [f"Shortlist (policy: {sl['policy']}; applies nothing)"]
    for row in sl['candidates']:
        cost = f"${row['cost_usd']}" if row.get('cost_usd') is not None else 'cost UNKNOWN'
        mark = '  <- ' + LABEL if row['id'] == sl.get('preferred') else ''
        lines.append(f"  {row['id']} {row.get('provider') or ''}: +{row['added']}/-{row['removed']} in "
                     f"{', '.join(row['files'])}; {cost}; claims {row.get('claims')}{mark}")
        if row.get('distinguishing_files'):
            lines.append('      files only this candidate touches: ' + ', '.join(row['distinguishing_files']))
    for item in sl['excluded']:
        lines.append(f"  excluded {item.get('id') or 'not-run'} {item.get('provider') or ''}: {item['why']}")
    for blocker in sl['blockers']:
        lines.append('  blocker: ' + blocker)
    lines.append(sl.get('note', ''))
    if sl.get('preferred'):
        lines.append(f"{LABEL}: {sl['rule']}. {sl['disclaimer']}")
    if sl.get('next'):
        lines.append('Next: ' + sl['next'])
    if sl['candidates']:
        lines.append('PASS is not task correctness: to check a candidate against your own requirements, run '
                     '`repo-ai coverage CANDIDATE_ID --requirements FILE`.')
    return '\n'.join(x for x in lines if x)
