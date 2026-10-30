"""Small explanations linking a decision to existing content-addressed evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..security import redact_text
from .contracts import digest


def explain(root: Path, mission: str) -> dict[str, Any]:
    from .runtime import classify_recovery, exercise_notes, status
    state = status(root, mission)
    contract = state.get('contract', {})
    evidence = []
    for role in ('baseline', 'candidate', 'regression'):
        record = state.get(role)
        if record is None:
            continue
        evidence.append({'role': role, 'sha256': digest(record), 'standing': state['freshness'],
                         'ran': record.get('ran'), 'failed': record.get('failed'),
                         'skipped': record.get('skipped'), 'complete': record.get('complete'),
                         'verdict': record.get('verdict'),
                         'source_sha256': record.get('pin', {}).get('fingerprint'),
                         'stdout_sha256': record.get('stdout_sha256'),
                         'stderr_sha256': record.get('stderr_sha256')})
    recovery = state.get('recovery') or classify_recovery(state)
    return {'schema': 'repo-ai.mission-explanation/1', 'mission': mission,
            'state': state['state'], 'verdict': state['effective_verdict'],
            'freshness': state['freshness'], 'freshness_reasons': state['freshness_reasons'],
            'objective': redact_text(contract.get('objective', 'not recorded')),
            'contract_sha256': digest(contract), 'source_sha256': state['source']['fingerprint'],
            'diff_sha256': state.get('diff_sha256'),
            'decision': state.get('plan', {}).get('decision', 'not recorded'),
            'routing_reason': state.get('plan', {}).get('why', 'not recorded'),
            'provider': state.get('provider', {'name': 'comparison', 'simulated': True}),
            'recovery': recovery,
            'claims': state.get('claims'),
            'evidence': evidence,
            'negative_evidence': [redact_text(r) for r in state.get('passport', {}).get('negative', [])],
            'change_exercise': (state.get('exercise') or {}).get('assurance'),
            'change_exercise_notes': exercise_notes(state.get('exercise')),
            'candidate_comparison': state.get('comparison', {}).get('candidates', []),
            'winner': state.get('comparison', {}).get('winner') if state['freshness'] == 'fresh' else None,
            'limits': [*state.get('passport', {}).get('untested', []),
                       'Evidence establishes observed test behavior, not general correctness',
                       'ProofLab is experimental and is not a completion gate',
                       'Hashes detect corruption, not forgery by a malicious local owner'],
            'next_command': ['repo-ai', 'mission', 'status', mission, '--json']}


def render(report: dict[str, Any]) -> str:
    # Quote untrusted text to avoid interpreting terminal control characters.
    def quote(text: Any) -> str:
        return json.dumps(text, ensure_ascii=True)
    lines = [f"{report['mission']}: {report['verdict']} ({report['freshness']})",
             'Outcome: ' + quote(report['objective']),
             'Route: ' + quote(report['routing_reason'])]
    for item in report['evidence']:
        if item['role'] == 'regression':
            detail = item['verdict'] or 'not checked'
        else:
            detail = f"{item['ran']} tests, {item['failed']} failing, {item['skipped']} skipped"
        lines.append(f"{item['role'].capitalize()}: {detail} [{item['standing']}; {item['sha256'][:12]}]")
    lines.extend('Invalidation: ' + quote(reason) for reason in report['freshness_reasons'])
    lines.extend('Limit: ' + quote(reason) for reason in report['negative_evidence'])
    lines.extend('Limit: ' + quote(n) for n in report.get('change_exercise_notes', []))
    claim = report.get('claims') or {}
    if claim:
        lines.append(f"Claim: {claim.get('headline')} (task correctness: {claim.get('task_correct')})")
        lines.extend('Limit: ' + quote(n) for n in claim.get('notes', [])[1:])
    if report['diff_sha256']:
        lines.append('Recorded candidate diff: ' + report['diff_sha256'] + ' (not applied to source)')
    if report['candidate_comparison']:
        lines.append('Comparison winner: ' + (report['winner'] or 'none; inspect candidate evidence'))
    lines.append('No tests or providers were invoked; use --json for evidence identities and limits.')
    return '\n'.join(lines)
