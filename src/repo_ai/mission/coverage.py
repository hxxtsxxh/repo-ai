"""Requirement -> acceptance coverage from a USER-DECLARED mapping and OBSERVED per-test outcomes.

The lexical claims heuristic (`claims.py`) can only guess. This module does not guess: the developer declares which
frozen test(s) assert each requirement, and repo-ai reports what the recorded baseline and candidate runs actually
observed for exactly those test IDs. Per requirement:

  VERIFIED_FAIL_TO_PASS   kind=change: every mapped test failed at baseline and passes on the candidate
  VERIFIED_PRESERVED      kind=preserve: every mapped test passed at baseline and still passes
  NOT_DISCRIMINATING      kind=change but a mapped test already passed at baseline, so it could not have caught the bug
  FAILING                 a mapped test does not pass on the candidate
  MISSING_TEST            a declared test ID was not collected (absent or ambiguous)
  UNMAPPED                no test declared: nothing observed supports this requirement

The headline is ACCEPTANCE_MAPPED_ALL only if every requirement is verified. It is never a task-correctness claim:
the mapping is the developer's statement, the tests may be weak, and a verified requirement only means the declared
test observed it. `task_correct` is always CLAIM_UNVERIFIED. The mapping is read at assessment time and hashed; it
is not part of the frozen contract and never changes a mission verdict.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import digest

SCHEMA = 'repo-ai.coverage/1'
REQ_SCHEMA = 'repo-ai.requirements/1'
MAX_BYTES = 200_000
MAX_REQUIREMENTS = 50
MAX_TESTS = 20
MAX_TEXT = 300
KINDS = ('change', 'preserve')


def load_requirements(path: Path) -> dict[str, Any]:
    """Strictly validated declaration; anything unexpected is refused rather than guessed."""
    if path.is_symlink() or not path.is_file():
        raise ValueError('requirements file must be a regular file')
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('requirements file too large')
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError('requirements file is not valid JSON') from exc
    if not isinstance(data, dict) or data.get('schema') != REQ_SCHEMA or not isinstance(data.get('requirements'), list):
        raise ValueError(f'requirements file must be an object with schema {REQ_SCHEMA!r} and a requirements list')
    items = data['requirements']
    if not 1 <= len(items) <= MAX_REQUIREMENTS:
        raise ValueError(f'1..{MAX_REQUIREMENTS} requirements are required')
    clean: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {'text', 'kind', 'tests'}:
            raise ValueError('each requirement is {text, kind, tests} only')
        text, kind, tests = item.get('text'), item.get('kind', 'change'), item.get('tests', [])
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError('requirement text must be a non-empty string up to %d characters' % MAX_TEXT)
        if kind not in KINDS:
            raise ValueError('requirement kind must be one of ' + ', '.join(KINDS))
        if (not isinstance(tests, list) or len(tests) > MAX_TESTS
                or any(not isinstance(t, str) or not t.strip() or len(t) > 500 for t in tests)):
            raise ValueError(f'tests must be a list of up to {MAX_TESTS} test ID strings')
        clean.append({'text': text.strip(), 'kind': kind, 'tests': list(dict.fromkeys(t.strip() for t in tests))})
    return {'requirements': clean, 'sha256': digest(clean)}


def _resolve(test: str, known: set[str]) -> tuple[str | None, str | None]:
    if test in known:
        return test, None
    hits = sorted(k for k in known if k.endswith('::' + test) or k.rsplit('::', 1)[-1] == test)
    if len(hits) == 1:
        return hits[0], None
    return None, ('ambiguous: matches ' + ', '.join(hits[:3])) if hits else 'not collected in the recorded runs'


def assess(decl: dict[str, Any], baseline: dict[str, str], candidate: dict[str, str], *,
           verdict: str, freshness: str) -> dict[str, Any]:
    known = set(baseline) | set(candidate)
    rows: list[dict[str, Any]] = []
    for req in decl['requirements']:
        if not req['tests']:
            rows.append({**req, 'status': 'UNMAPPED', 'detail': 'no test declared; nothing observed supports this requirement',
                         'observed': []})
            continue
        observed: list[dict[str, Any]] = []
        problems: list[str] = []
        for test in req['tests']:
            resolved, why = _resolve(test, known)
            if resolved is None:
                problems.append(f'{test}: {why}')
                continue
            observed.append({'test': resolved, 'baseline': baseline.get(resolved, 'absent'),
                             'candidate': candidate.get(resolved, 'absent')})
        if problems:
            status, detail = 'MISSING_TEST', '; '.join(problems)
        elif any(o['candidate'] != 'pass' for o in observed):
            status, detail = 'FAILING', 'a mapped test does not pass on the candidate'
        elif req['kind'] == 'preserve':
            ok = all(o['baseline'] == 'pass' for o in observed)
            status = 'VERIFIED_PRESERVED' if ok else 'NOT_DISCRIMINATING'
            detail = 'mapped tests passed before and after' if ok else 'a preserve test did not pass at baseline'
        elif all(o['baseline'] == 'fail' for o in observed):
            status, detail = 'VERIFIED_FAIL_TO_PASS', 'every mapped test failed at baseline and passes on the candidate'
        else:
            status = 'NOT_DISCRIMINATING'
            passed = [display_test_id(o['test']) for o in observed if o['baseline'] == 'pass']
            moved = [display_test_id(o['test']) for o in observed if o['baseline'] == 'fail']
            unseen = [display_test_id(o['test']) for o in observed if o['baseline'] not in {'pass', 'fail'}]
            parts = []
            if passed:
                parts.append('already passed at baseline, so it cannot show this change: ' + ', '.join(passed))
            if unseen:
                parts.append('no baseline observation, so it cannot show this change: ' + ', '.join(unseen))
            detail = '; '.join(parts)
            if moved:
                detail += ('; failed at baseline and passes now: ' + ', '.join(moved)
                           + '. Map the already-passing tests to a separate preserve requirement to verify this one')
            else:
                detail += ('. No mapped test failed before the change; add one that does (a requirement the original '
                           'code already met is a preserve requirement)')
        rows.append({**req, 'status': status, 'detail': detail, 'observed': observed})
    verified = {'VERIFIED_FAIL_TO_PASS', 'VERIFIED_PRESERVED'}
    unverified = [r for r in rows if r['status'] not in verified]
    if freshness == 'stale':
        headline = 'STALE'
    elif freshness != 'fresh' or verdict != 'PASS':
        headline = 'INCONCLUSIVE'
    elif not unverified:
        headline = 'ACCEPTANCE_MAPPED_ALL'
    elif len(unverified) == len(rows):
        headline = 'ACCEPTANCE_UNMAPPED'
    else:
        headline = 'ACCEPTANCE_PARTIAL'
    return {'schema': SCHEMA, 'headline': headline, 'task_correct': 'CLAIM_UNVERIFIED', 'requirements': rows,
            'requirements_sha256': decl['sha256'], 'mission_verdict': verdict, 'freshness': freshness,
            'counts': {s: sum(1 for r in rows if r['status'] == s) for s in sorted({r['status'] for r in rows})},
            'follow_up_test_needed': [r['text'] for r in unverified],
            'limits': ['The mapping is the developer\'s declaration; repo-ai checked only that the named tests exist and what '
                       'they observed.',
                       'A verified requirement means a declared test observed it, not that the test is strong enough.',
                       'Behavior not listed as a requirement is not assessed.']}


def for_mission(root: Path, mission: str, decl: dict[str, Any]) -> dict[str, Any]:
    from .runtime import status
    state = status(root.resolve(), mission)
    if state.get('kind') == 'comparison' or 'candidate' not in state or 'baseline' not in state:
        raise ValueError('coverage needs a single candidate mission with recorded baseline and candidate runs '
                         '(for a tournament, pass a candidate ID from the shortlist)')
    base = {k: str(v) for k, v in (state['baseline'].get('outcomes') or {}).items()}
    cand = {k: str(v) for k, v in (state['candidate'].get('outcomes') or {}).items()}
    report = assess(decl, base, cand, verdict=state['effective_verdict'], freshness=state['freshness'])
    report['mission'] = mission
    return report


def display_test_id(test: str) -> str:
    """A recorded identity is `file::runner-id`; pytest's id already starts with the file, so
    `f.py::f.py::test_x` reads as `f.py::test_x`. Display only: records and JSON keep the full key."""
    file, sep, rest = test.partition('::')
    return rest if sep and rest.startswith(file + '::') else test


def render(report: dict[str, Any]) -> str:
    lines = [f"Acceptance coverage for {report.get('mission', 'mission')}: {report['headline']} "
             f"(task correctness: {report['task_correct']})"]
    for row in report['requirements']:
        lines.append(f"  [{row['status']}] ({row['kind']}) {json.dumps(row['text'], ensure_ascii=True)}")
        lines.append('      ' + row['detail'])
        for o in row['observed']:
            lines.append(f"      {display_test_id(o['test'])}: baseline {o['baseline']} -> candidate {o['candidate']}")
    if report['follow_up_test_needed']:
        lines.append('Follow-up acceptance test needed for: ' + '; '.join(json.dumps(t, ensure_ascii=True)
                                                                         for t in report['follow_up_test_needed']))
    lines.extend('Limit: ' + x for x in report['limits'])
    return '\n'.join(lines)
