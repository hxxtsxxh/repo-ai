"""Requirement -> acceptance coverage from a USER-DECLARED mapping and OBSERVED per-test outcomes.

The lexical claims heuristic (`claims.py`) can only guess. This module does not guess: the developer declares which
frozen test(s) assert each requirement, and repo-ai reports what the recorded baseline and candidate runs actually
observed for exactly those test IDs. Per requirement:

  VERIFIED_FAIL_TO_PASS   kind=change: every mapped test failed at baseline and passes on the candidate
  VERIFIED_PRESERVED      kind=preserve: every mapped test passed at baseline and still passes
  NOT_DISCRIMINATING      kind=change but a mapped test already passed at baseline, so it could not have caught the bug
  FAILING                 a mapped test does not pass on the candidate
  NOT_OBSERVED            a mapped test was skipped at baseline and candidate: it observed nothing
  MISSING_TEST            a declared test ID was not collected (absent or ambiguous)
  UNMAPPED                no test declared: nothing observed supports this requirement
  UNVERIFIED_STALE / UNVERIFIED_INCONCLUSIVE
                          the run is stale or not a comparable PASS: whatever the tests showed is not verification

Besides the declared requirements, the report names the obligations nothing declared covers: changed executable
lines no frozen test ran (the mission's change-exercise measurement), and failures a scoped mission accepted as
pre-existing. Either keeps the headline below ACCEPTANCE_MAPPED_ALL. A test named by a bare suffix and one test
mapped to several requirements are flagged.

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


def _row(req: dict[str, Any], known: set[str], baseline: dict[str, str], candidate: dict[str, str]) -> dict[str, Any]:
    if not req['tests']:
        return {**req, 'status': 'UNMAPPED', 'detail': 'no test declared; nothing observed supports this requirement',
                'observed': []}
    observed: list[dict[str, Any]] = []
    problems: list[str] = []
    for test in req['tests']:
        resolved, why = _resolve(test, known)
        if resolved is None:
            problems.append(f'{test}: {why}')
            continue
        # `file::test` names the recorded `file::file::test` exactly (pytest's id repeats the file)
        exact = resolved == test or display_test_id(resolved) == test
        observed.append({'test': resolved, 'declared': test, 'matched': 'exact' if exact else 'suffix',
                         'baseline': baseline.get(resolved, 'absent'), 'candidate': candidate.get(resolved, 'absent')})
    if problems:
        return {**req, 'status': 'MISSING_TEST', 'detail': '; '.join(problems), 'observed': observed}
    # a failure on the candidate outranks a skipped neighbour: a regression is never called "not observed"
    if any(o['candidate'] not in {'pass', 'skip'} for o in observed):
        status, detail = 'FAILING', 'a mapped test does not pass on the candidate'
    elif any(o['candidate'] == 'skip' for o in observed):
        status, detail = 'NOT_OBSERVED', 'a mapped test was skipped on the candidate: it observed nothing'
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
    by_suffix = [o for o in observed if o['matched'] == 'suffix']
    if by_suffix:
        detail += '; matched by name, check it is the intended test: ' + ', '.join(
            f"{o['declared']} -> {display_test_id(o['test'])}" for o in by_suffix)
    return {**req, 'status': status, 'detail': detail, 'observed': observed}


def assess(decl: dict[str, Any], baseline: dict[str, str], candidate: dict[str, str], *,
           verdict: str, freshness: str, exercise: dict[str, Any] | None = None,
           pre_existing: list[str] | None = None) -> dict[str, Any]:
    """`exercise`: the mission's change-exercise record (which changed lines the frozen tests ran); `pre_existing`:
    failures a scoped mission accepted. Both are obligations no declared requirement discharges."""
    known = set(baseline) | set(candidate)
    rows = [_row(req, known, baseline, candidate) for req in decl['requirements']]
    verified = {'VERIFIED_FAIL_TO_PASS', 'VERIFIED_PRESERVED'}
    fresh_pass = freshness == 'fresh' and verdict == 'PASS'
    if not fresh_pass:
        # what the tests showed is not verification when the run is stale or not a comparable PASS
        label = 'UNVERIFIED_STALE' if freshness == 'stale' else 'UNVERIFIED_INCONCLUSIVE'
        why = ('the evidence is stale' if freshness == 'stale'
               else f'the mission verdict is {verdict} (freshness {freshness}), not a comparable fresh PASS')
        for r in rows:
            if r['status'] in verified:
                r['observed_status'] = r['status']
                r['status'], r['detail'] = label, f"{why}; the mapped tests showed {r['observed_status']}"
    # one test standing for several requirements cannot show each of them separately
    owners: dict[str, list[str]] = {}
    for r in rows:
        for o in r['observed']:
            owners.setdefault(o['test'], []).append(r['text'])
    shared = {t: reqs for t, reqs in owners.items() if len(reqs) > 1}
    obligations: list[str] = []
    # `exercise` None: not given by the caller (nothing claimed either way); a record: the mission's measurement
    changed_code: dict[str, Any] = {'assurance': 'NOT_GIVEN'}
    if exercise is not None:
        changed_code = {k: exercise.get(k) for k in ('assurance', 'changed_lines', 'unexercised', 'unexercised_count')
                        if k in exercise}
    level = changed_code.get('assurance')
    if level == 'NOT_GIVEN':
        pass
    elif level == 'PARTIAL':
        shown = ', '.join((changed_code.get('unexercised') or [])[:8])
        obligations.append(f"changed code no frozen test ran ({changed_code.get('unexercised_count', 0)} of "
                           f"{changed_code.get('changed_lines', 0)} changed executable lines: {shown})")
    elif level not in {'FULL', 'NO_EXECUTABLE_CHANGE'}:
        obligations.append('whether the frozen tests ran the changed code was not measured for this mission')
    if pre_existing:
        obligations.append('failures accepted as pre-existing in this scoped mission: '
                           + ', '.join(display_test_id(t) for t in pre_existing[:8]))
    unverified = [r for r in rows if r['status'] not in verified]
    if freshness == 'stale':
        headline = 'STALE'
    elif not fresh_pass:
        headline = 'INCONCLUSIVE'
    elif not unverified and not obligations:
        headline = 'ACCEPTANCE_MAPPED_ALL'
    elif len(unverified) == len(rows):
        headline = 'ACCEPTANCE_UNMAPPED'
    else:
        headline = 'ACCEPTANCE_PARTIAL'
    return {'schema': SCHEMA, 'headline': headline, 'task_correct': 'CLAIM_UNVERIFIED', 'requirements': rows,
            'requirements_sha256': decl['sha256'], 'mission_verdict': verdict, 'freshness': freshness,
            'counts': {s: sum(1 for r in rows if r['status'] == s) for s in sorted({r['status'] for r in rows})},
            'follow_up_test_needed': [r['text'] for r in unverified],
            'other_obligations': obligations, 'changed_code': changed_code,
            'shared_tests': {display_test_id(t): reqs for t, reqs in shared.items()},
            'limits': ['The mapping is the developer\'s declaration; repo-ai checked only that the named tests exist and what '
                       'they observed.',
                       'A verified requirement means a declared test observed it, not that the test is strong enough.',
                       'Behavior not listed as a requirement is not assessed; the declaration is read when coverage runs, '
                       'not frozen with the mission, so it can be written after the outcomes are known.']}


def for_mission(root: Path, mission: str, decl: dict[str, Any]) -> dict[str, Any]:
    from .runtime import status
    state = status(root.resolve(), mission)
    if state.get('kind') == 'comparison' or 'candidate' not in state or 'baseline' not in state:
        raise ValueError('coverage needs a single candidate mission with recorded baseline and candidate runs '
                         '(for a tournament, pass a candidate ID from the shortlist)')
    base = {k: str(v) for k, v in (state['baseline'].get('outcomes') or {}).items()}
    cand = {k: str(v) for k, v in (state['candidate'].get('outcomes') or {}).items()}
    raw_scoped, raw_exercise = state.get('scoped'), state.get('exercise')
    scoped: dict[str, Any] = raw_scoped if isinstance(raw_scoped, dict) else {}
    exercise: dict[str, Any] = raw_exercise if isinstance(raw_exercise, dict) else {'assurance': 'NOT_RECORDED'}
    report = assess(decl, base, cand, verdict=state['effective_verdict'], freshness=state['freshness'],
                    exercise=exercise, pre_existing=[str(t) for t in (scoped.get('pre_existing_failures') or [])])
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
    for item in report.get('other_obligations') or []:
        lines.append('Not covered by any requirement: ' + item)
    for test, reqs in (report.get('shared_tests') or {}).items():
        lines.append(f'One test, {len(reqs)} requirements: {test} cannot show each of them separately')
    lines.extend('Limit: ' + x for x in report['limits'])
    return '\n'.join(lines)
