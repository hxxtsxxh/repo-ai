"""Read-only failure deltas backed by the mission's existing observation store.

This explains what the controlled comparison observed. Static source links are
investigation leads, not a root-cause finding or a second completion authority.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..security import redact_text
from ..verify import isolate
from .contracts import digest
from .verification import comparability

MAX_TEST_ROWS = 200
CLASSIFICATIONS = {
    ('fail', 'pass'): 'FIXED_IN_OBSERVED_SUITE',
    ('error', 'pass'): 'FIXED_IN_OBSERVED_SUITE',
    ('fail', 'fail'): 'PRE_EXISTING_FAILURE',
    ('error', 'error'): 'PRE_EXISTING_FAILURE',
    ('fail', 'error'): 'PRE_EXISTING_FAILURE',
    ('error', 'fail'): 'PRE_EXISTING_FAILURE',
    ('pass', 'fail'): 'NEW_FAILURE',
    ('pass', 'error'): 'NEW_FAILURE',
    ('pass', 'pass'): 'UNCHANGED_PASS',
}


def _runtime_coverage_links(
    root: Path | None,
    failing_tests: list[str],
    source_hashes: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Read existing local TestMap coverage links without running tests or creating state."""
    if root is None:
        return {}
    try:
        from ..verify.testmap import TestMap
        from .ledger import Store
        tmap_path = Store(root).layout.state_dir / 'testmap.json'
        if not tmap_path.is_file():
            return {}
        tmap = TestMap.load(tmap_path)
    except Exception:
        return {}
    if tmap is None:
        return {}
    fail_set = set(failing_tests)
    by_source: dict[str, set[str]] = {}
    file_hashes = getattr(tmap, 'file_hashes', None) or {}
    for test_file, rec in tmap.tests.items():
        if test_file not in fail_set or not isinstance(rec, dict):
            continue
        for src_path in set(rec.get('units') or {}) | set(rec.get('opened') or []) | set(rec.get('functions') or {}):
            if not isinstance(src_path, str):
                continue
            if source_hashes and src_path in file_hashes and src_path in source_hashes:
                if file_hashes[src_path] != source_hashes[src_path]:
                    continue
            by_source.setdefault(src_path, set()).add(test_file)
    return {k: sorted(v) for k, v in by_source.items()}


def _hypotheses(state: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    packet = state.get('plan', {}).get('context', {}).get('packet', {})
    impact = state.get('nodes', {}).get('impact', {}).get('artifact', {})
    source = state.get('source', {}).get('files', {})
    allowed = state.get('contract', {}).get('write_paths', [])
    failures = [test.split('::', 1)[0] for test, outcome in
                state.get('baseline', {}).get('outcomes', {}).items() if outcome in {'fail', 'error'}]
    runtime_links = _runtime_coverage_links(root, failures, source_hashes=source)
    leads = []
    priority_rank = {'runtime-trace-link': 0, 'test-import-link': 1, 'context-only': 2}
    seen_paths: set[str] = set()
    candidate_locations = list(packet.get('locations', [])[:20])
    for cov_path in sorted(runtime_links):
        if cov_path in source and all(loc.get('path') != cov_path for loc in candidate_locations):
            candidate_locations.append({'path': cov_path})

    for location in candidate_locations[:24]:
        path = location['path']
        if path not in source or path in seen_paths:
            continue
        seen_paths.add(path)
        module = path.rsplit('.', 1)[0].replace('/', '.').removesuffix('.__init__')
        cov_linked = runtime_links.get(path, [])
        static_linked = sorted({test for test in failures for imported in impact.get('imports', {}).get(test, [])
                                if imported and (module == imported or module.endswith('.' + imported))})
        if cov_linked:
            confidence = 'observed'
            priority = 'runtime-trace-link'
            linked = cov_linked
            reason = 'recorded runtime coverage link from a failing test'
            prov = digest({'coverage_tests': cov_linked, 'source_sha256': source[path]})
        elif static_linked:
            confidence = 'static'
            priority = 'test-import-link'
            linked = static_linked
            reason = 'recorded static import from a failing test'
            prov = digest(impact)
        else:
            confidence = 'static'
            priority = 'context-only'
            linked = []
            reason = 'source-linked retrieval lead; no causal link established'
            prov = digest(location)
        leads.append({'path': redact_text(path), 'confidence': confidence,
                      'priority': priority,
                      'source_sha256': source[path], 'test_paths': [redact_text(t) for t in linked],
                      'within_approved_write_scope': path in allowed,
                      'reason': reason,
                      'provenance': prov})
    return sorted(leads, key=lambda lead: (priority_rank.get(lead['priority'], 9), lead['path']))


def _changed_paths(state: dict[str, Any]) -> set[str]:
    return {m for m in re.findall(r'^diff --git a/(\S+) b/', state.get('diff') or '', flags=re.M)}


def _imported_sources(root: Path, test_file: str, sources: dict[str, str]) -> list[str]:
    """Repository modules a failing Python test file imports (static; dynamic imports are a blind spot)."""
    data = isolate.read_inside(root, test_file, 2_000_000)
    if data is None:
        return []
    try:
        tree = ast.parse(data.decode('utf-8'))
    except (UnicodeDecodeError, SyntaxError, ValueError):
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    found = set()
    for name in names:
        base = name.replace('.', '/')
        for cand in (base + '.py', base + '/__init__.py'):
            if cand in sources and cand != test_file:
                found.add(cand)
    return sorted(found)


def _failure_clusters(root: Path, state: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group still-failing tests by test file and the sources they import; compare with what the candidate changed.

    A cluster is a tentative shared-cause hypothesis from observed outcomes plus static imports.
    """
    sources = state.get('source', {}).get('files', {})
    changed = _changed_paths(state) or set(state.get('contract', {}).get('write_paths', []))
    by_file: dict[str, list[str]] = {}
    for row in rows:
        if row['classification'] in {'PRE_EXISTING_FAILURE', 'NEW_FAILURE'}:
            by_file.setdefault(row['test_id'].split('::', 1)[0], []).append(row['test_id'])
    clusters = []
    for test_file, ids in sorted(by_file.items()):
        linked = _imported_sources(root, test_file, sources)
        touched = sorted(set(linked) & changed)
        clusters.append({
            'test_file': redact_text(test_file), 'failing_tests': ids[:20], 'linked_sources': [redact_text(x) for x in linked],
            'changed_by_candidate': touched,
            'standing': 'RESIDUAL_IN_CHANGED_AREA' if touched else ('RESIDUAL_OUTSIDE_CHANGE' if linked else 'RESIDUAL_UNLINKED'),
            'confidence': 'static'})
    return clusters


def _flaky_tests(state: dict[str, Any], current_baseline: dict[str, Any]) -> set[str]:
    """Identify tests whose baseline outcome fluctuated across recorded attempts on identical test inputs."""
    current_inputs = (current_baseline.get('pin') or {}).get('test_inputs')
    current_outcomes = current_baseline.get('outcomes')
    if not current_inputs or not isinstance(current_outcomes, dict):
        return set()
    flaky: set[str] = set()
    for attempt in state.get('attempts', []):
        prev_base = (attempt.get('nodes') or {}).get('baseline', {}).get('artifact')
        if not isinstance(prev_base, dict):
            continue
        if (prev_base.get('pin') or {}).get('test_inputs') != current_inputs:
            continue
        prev_outcomes = prev_base.get('outcomes')
        if not isinstance(prev_outcomes, dict):
            continue
        for tid, out in current_outcomes.items():
            if tid in prev_outcomes and prev_outcomes[tid] != out:
                flaky.add(tid)
    return flaky


def diagnose(root: Path, mission: str, *, test: str | None = None) -> dict[str, Any]:
    from .runtime import status
    state = status(root, mission)  # source, interpreter, kernel and zone checks precede disclosure
    baseline, candidate = state.get('baseline', {}), state.get('candidate', {})
    reasons = comparability(baseline, candidate)
    if state['freshness'] != 'fresh':
        reasons.insert(0, 'mission evidence is ' + state['freshness'] + '; historical outcomes cannot establish current behavior')
    if state.get('kind') == 'comparison':
        reasons.insert(0, 'select an individual candidate mission; a tournament is not a test observation')
    before = baseline.get('outcomes', {})
    after = candidate.get('outcomes', {})
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    ids = sorted(set(before) | set(after))
    if test is not None:
        if test not in ids:
            raise ValueError('test identity not observed in this mission; inspect the unfiltered report')
        ids = [test]
    comparable = not reasons
    flaky = _flaky_tests(state, baseline) if comparable else set()
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for test_id in ids:
        if not comparable:
            classification = 'NOT_COMPARABLE'
        elif test_id in flaky:
            classification = 'FLAKY_OR_INCONSISTENT'
        else:
            classification = CLASSIFICATIONS.get((before.get(test_id, ''), after.get(test_id, '')), 'NOT_COMPARABLE')
        counts[classification] += 1
        if len(rows) < MAX_TEST_ROWS:
            rows.append({'test_id': redact_text(test_id), 'baseline': before.get(test_id, 'not checked'),
                         'candidate': after.get(test_id, 'not checked'), 'classification': classification,
                         'evidence': {'baseline': digest(baseline) if baseline else '',
                                      'candidate': digest(candidate) if candidate else ''}})
    hypotheses = _hypotheses(state, root) if comparable else []
    next_experiments: list[dict[str, Any]] = []
    if counts.get('NEW_FAILURE') or counts.get('PRE_EXISTING_FAILURE'):
        failing_ids = [r['test_id'] for r in rows if r['classification'] in {'NEW_FAILURE', 'PRE_EXISTING_FAILURE'}][:3]
        for fid in failing_ids:
            next_experiments.append({
                'kind': 'focused-diagnosis',
                'command': ['repo-ai', 'why-test-failed', mission, '--test', fid, '--json'],
                'reason': 'inspect single failing test delta and linked source hypotheses offline',
            })
    clusters = _failure_clusters(root, state, rows) if comparable and state['freshness'] == 'fresh' else []
    outside = [c for c in clusters if c['standing'] == 'RESIDUAL_OUTSIDE_CHANGE']
    if outside:
        # The remaining failures do not import anything the candidate changed: investigating the changed file again
        # would not discriminate. Aim the next check at the sources those failures actually import.
        target = outside[0]['linked_sources'][0]
        next_experiments = [{
            'kind': 'impact-check',
            'command': ['repo-ai', 'impact', target, '--format', 'json'],
            'reason': 'residual failures import ' + target + ', which the candidate did not change; start a separate mission there'}]
    elif hypotheses:
        next_experiments.append({
            'kind': 'impact-check',
            'command': ['repo-ai', 'impact', hypotheses[0]['path'], '--format', 'json'],
            'reason': 'check static importers and linked tests for highest-priority hypothesis',
        })
    return {'schema': 'repo-ai.failure-diagnosis/1', 'mission': mission,
            'standing': 'OBSERVED' if comparable else 'INCONCLUSIVE',
            'freshness': state['freshness'], 'mission_verdict': state['effective_verdict'],
            'tests': rows, 'counts': dict(sorted(counts.items())), 'omitted_rows': max(0, len(ids) - len(rows)),
            'reasons': [redact_text(reason) for reason in reasons],
            'source_hypotheses': hypotheses,
            'failure_clusters': clusters,
            'next_experiments': next_experiments,
            'negative_evidence': [redact_text(reason) for reason in (state.get('passport') or {}).get('negative', [])],
            'next_command': ['repo-ai', 'mission', 'status', mission, '--json'],
            'reran_tests': False, 'invoked_provider': False,
            'limitations': ['An outcome delta is not a root cause finding or a proof of correctness',
                            'Repeated failure may have a different cause; stack traces are not retained here',
                            'Static import leads are not runtime coverage; dynamic imports and unobserved tests remain blind spots',
                            'Diagnosis never upgrades a mission verdict or changes stored evidence']}


def render(report: dict[str, Any]) -> str:
    import json
    lines = [f"{report['mission']}: {report['standing']} ({report['freshness']})"]
    for row in report['tests']:
        lines.append(f"  {row['classification']}: {json.dumps(row['test_id'], ensure_ascii=True)} "
                     f"({row['baseline']} -> {row['candidate']})")
    for hyp in report.get('source_hypotheses', [])[:5]:
        lines.append(
            f"  Hypothesis [{hyp['confidence']}/{hyp['priority']}]: "
            f"{json.dumps(hyp['path'], ensure_ascii=True)} — {hyp['reason']}"
        )
    for exp in report.get('next_experiments', [])[:3]:
        cmd_str = ' '.join(exp['command'])
        lines.append(f"  Next experiment ({exp['kind']}): {cmd_str}")
    lines.extend('  ' + reason for reason in report['reasons'])
    if report['omitted_rows']:
        lines.append(f"  {report['omitted_rows']} additional rows; use --test with an exact identity")
    lines.append('No tests or providers were invoked. Outcome changes do not establish root cause.')
    return '\n'.join(lines)
