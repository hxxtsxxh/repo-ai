"""Requirement -> acceptance coverage from a USER-DECLARED mapping and OBSERVED per-test outcomes.

The lexical claims heuristic (`claims.py`) can only guess. This module does not guess: the developer declares which
frozen test(s) assert each requirement, and repo-ai reports what the recorded baseline and candidate runs actually
observed for exactly those test IDs. Per requirement:

  VERIFIED_FAIL_TO_PASS   kind=change: every mapped test failed at baseline and passes on the candidate
  VERIFIED_PRESERVED      kind=preserve: every mapped test passed at baseline and still passes
  NOT_DISCRIMINATING      kind=change but a mapped test already passed at baseline, so it could not have caught the bug
  FAILING                 a mapped test does not pass on the candidate
  NOT_OBSERVED            a mapped test was skipped on the candidate: it observed nothing
  MISSING_TEST            a declared test ID was not collected (absent or ambiguous)
  UNMAPPED                no test declared: nothing observed supports this requirement
  UNVERIFIED_STALE / UNVERIFIED_INCONCLUSIVE
                          the run is stale or not a comparable PASS: whatever the tests showed is not verification

Besides the declared requirements, the report names the obligations nothing declared covers: changed executable
lines no frozen test ran (the mission's change-exercise measurement), and failures a scoped mission accepted as
pre-existing. Either keeps the headline below ACCEPTANCE_MAPPED_ALL. For missions run with a frozen declaration it
also lists, informationally, the changed lines that ran while each requirement's own tests ran and those only
undeclared tests ran: per test for pytest (by time window; a shared fixture's setup run is credited to each test
whose call ran with it active), per test FILE for `node --test` (each file ran alone under V8 coverage, and what it
ran is credited to every test in it; a file whose coverage could not be used is shown as unavailable, with the
reason). A test named by a bare suffix and one test mapped to several requirements are flagged.

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
    return _validated(data)


def _validated(data: Any) -> dict[str, Any]:
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


def freeze(path: Path) -> dict[str, Any]:
    """The declaration as stored with a mission plan (before it runs)."""
    decl = load_requirements(path)
    return {'schema': REQ_SCHEMA, 'requirements': decl['requirements'], 'sha256': decl['sha256']}


def _frozen(state: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """(declaration, problem): the frozen declaration re-validated by the same rules as a file, or why it was not
    used. The digest is unkeyed: it catches accidental edits, not someone who rewrites the local store."""
    raw = (state.get('plan') or {}).get('requirements') if isinstance(state.get('plan'), dict) else None
    if raw is None:
        return None, ''
    try:
        decl = _validated({'schema': REQ_SCHEMA, 'requirements': raw.get('requirements') if isinstance(raw, dict) else None})
    except ValueError as exc:
        return None, f'the frozen declaration is malformed ({exc})'
    if decl['sha256'] != raw.get('sha256'):
        return None, 'the frozen declaration does not match its recorded digest'
    return decl, ''


def _prior_runs(root: Path, state: dict[str, Any]) -> list[str]:
    """Earlier missions on the same source with the same proposal or the same candidate diff: their outcomes were
    visible before this one froze its declaration, so "frozen before this mission ran" says nothing about what was
    already known. Only missions still in this store are seen."""
    from .ledger import Store
    store = Store(root)
    me, source = state.get('id'), (state.get('source') or {}).get('fingerprint')
    started = state.get('attempt_started_at') or 0
    out: list[str] = []
    for path in sorted(store.folder.glob('*.json'))[:64] if store.folder.is_dir() else []:
        if path.stem == me:
            continue
        try:
            other = store.load(path.stem)
        except (ValueError, OSError):
            continue
        same_change = (other.get('proposal_sha256') == state.get('proposal_sha256')
                       or (bool(state.get('diff_sha256')) and other.get('diff_sha256') == state.get('diff_sha256')))
        if ((other.get('source') or {}).get('fingerprint') == source and same_change
                and (other.get('attempt_started_at') or 0) < started and 'candidate' in other):
            out.append(path.stem)
    return out


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


_TIME_WINDOW_NOTE = ('attribution is by time window (a shared fixture\'s setup run is credited to each test whose call '
                     'ran with it active): lines run at import, in a teardown, in a child process or in another test\'s '
                     'thread are not credited to the test they serve; informational, never part of a status or the '
                     'headline')
_PER_FILE_NOTE = ('Node attribution is per test FILE, not per test: each test file ran alone (`node --test FILE`) under '
                  'V8 coverage, and every changed line it ran, loading its modules included, is credited to every test '
                  'in that file, so a requirement is credited with lines its file\'s other tests ran; a line counts as '
                  'run when any code on it ran; informational, never part of a status or the headline')


def _changed_lines_by_requirement(rows: list[dict[str, Any]], exercise: dict[str, Any] | None) -> dict[str, Any]:
    """Requirement by requirement, which changed executable lines ran while its mapped tests ran (the exercise
    measurement's per-test record, kept for missions with a frozen declaration). Informational only, never an
    obligation or a status. pytest (`per_test_granularity` "test", or absent in older records): keyed by test, by time
    window (a shared fixture's setup run is credited to each test whose call ran with it active), so a line that runs
    at import, in a teardown, in a child process or in another test's thread is not credited to the test it serves.
    node (`"file"`): keyed by test file; a requirement gets the lines of every file its tests are in, and a file whose
    coverage was unavailable is named with the reason instead of being counted as having run nothing."""
    per_test = (exercise or {}).get('per_test')
    total = int((exercise or {}).get('changed_lines') or 0)
    if not isinstance(per_test, dict):
        why = (exercise or {}).get('per_test_reason')
        return {'measured': False, 'reason': f'not measured: {why}' if isinstance(why, str) and why else
                'not measured (recorded for pytest and node --test missions run with a frozen --requirements '
                'declaration)'}
    if total <= 0:
        return {'measured': False, 'reason': 'no executable line changed'}
    per_file = (exercise or {}).get('per_test_granularity') == 'file'
    complete = (exercise or {}).get('per_test_complete') is True
    raw_unavailable = (exercise or {}).get('per_test_unavailable')
    unavailable = {k: v for k, v in (raw_unavailable.items() if isinstance(raw_unavailable, dict) else ())
                   if isinstance(k, str) and isinstance(v, str)}
    measured_files = {f for f in ((exercise or {}).get('per_test_measured') or []) if isinstance(f, str)} | set(per_test)
    claimed: set[str] = set()
    for r in rows:
        if not r['observed']:
            continue
        if per_file:
            # the recorded identity is `test file::test name`: the file's lines stand for each of its tests
            files = sorted({o['test'].partition('::')[0] for o in r['observed']})
            keys = [f for f in files if f in measured_files]
            missing = {f: unavailable.get(f, 'not measured') for f in files if f not in measured_files}
            if missing:
                r['changed_lines_unavailable'] = missing
            r['changed_lines_test_files'] = files
        else:
            keys = [o['test'].partition('::')[2] for o in r['observed']]
        ran = sorted({line for k in keys for line in (per_test.get(k) or []) if isinstance(line, str)})
        claimed.update(ran)
        r['changed_lines_run'] = ran[:20]
        r['changed_lines_run_count'] = len(ran)
    every = {line for lines in per_test.values() if isinstance(lines, list) for line in lines if isinstance(line, str)}
    unclaimed = sorted(every - claimed)
    out: dict[str, Any] = {'measured': True, 'granularity': 'file' if per_file else 'test', 'complete': complete,
                           'changed_lines': total, 'run_by_tests_of_no_requirement': unclaimed[:20],
                           'run_by_tests_of_no_requirement_count': len(unclaimed),
                           'note': _PER_FILE_NOTE if per_file else _TIME_WINDOW_NOTE}
    if per_file:
        out['unavailable_test_files'] = dict(sorted(unavailable.items())[:20])
        out['unavailable_test_files_count'] = len(unavailable)
    else:
        outside = [x for x in ((exercise or {}).get('changed_outside_tests') or []) if isinstance(x, str)]
        out['run_outside_any_test'] = outside[:20]
    return out


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
    per_requirement = _changed_lines_by_requirement(rows, exercise)
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
            'other_obligations': obligations, 'changed_code': changed_code, 'changed_lines_by_requirement': per_requirement,
            'shared_tests': {display_test_id(t): reqs for t, reqs in shared.items()},
            'limits': ['The mapping is the developer\'s declaration; repo-ai checked only that the named tests exist and what '
                       'they observed.',
                       'A verified requirement means a declared test observed it, not that the test is strong enough.',
                       'Behavior not listed as a requirement is not assessed; the declaration is read when coverage runs, '
                       'not frozen with the mission, so it can be written after the outcomes are known.']}


def for_mission(root: Path, mission: str, decl: dict[str, Any] | None = None) -> dict[str, Any]:
    """`decl` None: the declaration frozen with the mission (`do --requirements`). A supplied one is marked as
    written at assessment time unless it is byte-for-byte the frozen one."""
    from .runtime import status
    state = status(root.resolve(), mission)
    frozen, problem = _frozen(state)
    if decl is None:
        if frozen is None:
            raise ValueError((problem + '; ' if problem else '') + 'no requirements declaration: pass --requirements '
                             'FILE, or freeze one when planning (repo-ai do ... --requirements FILE)')
        decl = frozen
    declared = 'FROZEN_WITH_MISSION' if frozen is not None and frozen['sha256'] == decl['sha256'] \
        else 'SUPPLIED_AT_ASSESSMENT'
    prior = _prior_runs(root.resolve(), state) if declared == 'FROZEN_WITH_MISSION' else []
    if prior:
        declared = 'FROZEN_AFTER_PRIOR_RUN'
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
    report['declaration'] = declared
    if declared in {'FROZEN_WITH_MISSION', 'FROZEN_AFTER_PRIOR_RUN'}:
        report['limits'] = [x for x in report['limits'] if 'not frozen with the mission' not in x] + [
            'The declaration was frozen before this mission ran; it says nothing about outcomes known from earlier runs '
            'or local test runs. Its digest is unkeyed: it catches accidental edits, not someone who rewrites the '
            'local mission store.']
    if prior:
        report['prior_runs'] = prior
        report['limits'].append('Earlier missions on the same source and proposal had already recorded outcomes '
                                '(' + ', '.join(prior[:3]) + '): the declaration may have been written knowing them.')
    if frozen is not None and declared == 'SUPPLIED_AT_ASSESSMENT':
        report['limits'].append('A different declaration was frozen with this mission; this report assesses the '
                                'one supplied now.')
    if problem:
        report['limits'].append('Not used: ' + problem + '.')
    return report


def display_test_id(test: str) -> str:
    """A recorded identity is `file::runner-id`; pytest's id already starts with the file, so
    `f.py::f.py::test_x` reads as `f.py::test_x`. Display only: records and JSON keep the full key."""
    file, sep, rest = test.partition('::')
    return rest if sep and rest.startswith(file + '::') else test


def render(report: dict[str, Any]) -> str:
    lines = [f"Acceptance coverage for {report.get('mission', 'mission')}: {report['headline']} "
             f"(task correctness: {report['task_correct']})"]
    if report.get('declaration'):
        lines.append('Declaration: ' + {'FROZEN_WITH_MISSION': 'frozen before this mission ran',
                                        'FROZEN_AFTER_PRIOR_RUN': 'frozen before this mission ran, but after earlier '
                                                                  'runs of the same change',
                                        'SUPPLIED_AT_ASSESSMENT': 'supplied now, after the run'}[report['declaration']])
    for row in report['requirements']:
        lines.append(f"  [{row['status']}] ({row['kind']}) {json.dumps(row['text'], ensure_ascii=True)}")
        lines.append('      ' + row['detail'])
        for o in row['observed']:
            lines.append(f"      {display_test_id(o['test'])}: baseline {o['baseline']} -> candidate {o['candidate']}")
        if 'changed_lines_run_count' in row:
            ran = row['changed_lines_run']
            shown = (': ' + ', '.join(ran[:8])) if ran else ''
            if 'changed_lines_test_files' in row:
                gone = row.get('changed_lines_unavailable') or {}
                files = row['changed_lines_test_files']
                if len(gone) < len(files):
                    lines.append(f"      its test file(s) ran {row['changed_lines_run_count']} changed line(s) "
                                 f"[per test file: {', '.join(f for f in files if f not in gone)}]{shown}")
                for f, why in gone.items():
                    lines.append(f'      changed lines unavailable for its test file {f}: {why}')
            else:
                lines.append(f"      its tests ran {row['changed_lines_run_count']} changed line(s){shown}")
    if report['follow_up_test_needed']:
        lines.append('Follow-up acceptance test needed for: ' + '; '.join(json.dumps(t, ensure_ascii=True)
                                                                         for t in report['follow_up_test_needed']))
    for item in report.get('other_obligations') or []:
        lines.append('Not covered by any requirement: ' + item)
    by_req = report.get('changed_lines_by_requirement') or {}
    if by_req.get('measured') and by_req.get('granularity') == 'file':
        if by_req.get('run_by_tests_of_no_requirement_count'):
            lines.append(f"Changed lines run only by test files that hold no declared test "
                         f"({by_req['run_by_tests_of_no_requirement_count']}): "
                         + ', '.join(by_req['run_by_tests_of_no_requirement'][:8]))
        if by_req.get('unavailable_test_files_count'):
            lines.append(f"Changed lines unavailable for {by_req['unavailable_test_files_count']} test file(s): "
                         + '; '.join(f'{f} ({why})' for f, why in list(by_req['unavailable_test_files'].items())[:8]))
        if not by_req.get('complete'):
            lines.append('Changed lines by requirement (Node, per test file): the record is incomplete (coverage '
                         'unavailable or not run for some test files); a requirement shown with 0 lines may have run '
                         'some')
        lines.append('Changed lines by requirement (Node, per test file): ' + str(by_req.get('note', '')))
    elif by_req.get('measured'):
        if by_req.get('run_by_tests_of_no_requirement_count'):
            lines.append(f"Changed lines run only while tests no requirement names ran "
                         f"({by_req['run_by_tests_of_no_requirement_count']}): "
                         + ', '.join(by_req['run_by_tests_of_no_requirement'][:8]))
        if by_req.get('run_outside_any_test'):
            lines.append('Changed lines run outside any test (import, collection): '
                         + ', '.join(by_req['run_outside_any_test'][:8]))
        if not by_req.get('complete'):
            lines.append('Changed lines by requirement: the per-test record is incomplete (a child process, an early '
                         'stop or too many tests); a requirement shown with 0 lines may have run some')
        lines.append('Changed lines by requirement: ' + str(by_req.get('note', '')))
    elif by_req:
        lines.append('Changed lines by requirement: ' + str(by_req.get('reason', 'not measured')))
    for test, reqs in (report.get('shared_tests') or {}).items():
        lines.append(f'One test, {len(reqs)} requirements: {test} cannot show each of them separately')
    lines.extend('Limit: ' + x for x in report['limits'])
    return '\n'.join(lines)
