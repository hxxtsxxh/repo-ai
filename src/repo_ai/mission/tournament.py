"""Opt-in comparisons of isolated simulated candidates; no model self-voting."""
from __future__ import annotations

import copy
import hashlib
import time
from pathlib import Path
from typing import Any

from .contracts import EvidenceRecord, IntentContract, decode, digest
from .ledger import Store, transition
from .runtime import check_privacy, execute, identity, kernel_identity


def compare_candidates(root: Path, planned: dict[str, Any], proposals: list[Path]) -> dict[str, Any]:
    root = root.resolve()
    contract = decode(planned['contract'])
    if (not isinstance(contract, IntentContract) or not contract.execute or not contract.approvals
            or contract.provider != 'replay' or contract.network or contract.max_cost_usd != 0):
        raise ValueError('candidate comparison requires explicit zero-cost local replay execution approval')
    if not 2 <= len(proposals) <= 3:
        raise ValueError('candidate comparison requires two or three explicit proposals')
    if not check_privacy(root, planned['contract']):
        raise ValueError('zone policy changed or unbound legacy contract; create a fresh plan')
    if planned.get('kernel') != kernel_identity():
        raise ValueError('stale mission kernel; create a fresh plan')
    store = Store(root)
    frozen = identity(root, require_clean=True)
    if (contract.repository != store.repository or contract.base != frozen['head']
            or frozen['fingerprint'] != planned['source']['fingerprint']):
        raise ValueError('stale tournament plan')
    prop_keys = [
        hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else str(p.resolve())
        for p in proposals
    ]
    if len(set(prop_keys)) != len(proposals):
        raise ValueError('candidate comparison requires distinct proposals')
    acceptance = digest({'source': frozen, 'acceptance': contract.acceptance, 'paths': contract.write_paths,
                         'network': contract.network, 'provider': contract.provider})
    started = time.monotonic()
    col = Collector(root, frozen, dedupe_proposals=True)
    for index, proposal in enumerate(proposals):
        remaining = contract.max_seconds - (time.monotonic() - started)
        if remaining < 1:
            col.block(index, ['aggregate time budget exhausted'])
            continue
        trial = copy.deepcopy(planned)
        trial['contract']['max_seconds'] = remaining
        col.run(index, lambda trial=trial, proposal=proposal: execute(root, trial, proposal))
    return finalize(root, planned, frozen, acceptance, col, len(proposals), started,
                    provider_label='replay; explicitly simulated', extra={'cost_usd': 0}, limitations=[
                        'Winner means the only eligible observed candidate under this frozen suite; not a universal safest-fix claim',
                        'No patch blending, source application, live model invocation, or product-lift claim'])


class Collector:
    """Rows + controlled-comparison bookkeeping shared by replay and live tournaments."""

    def __init__(self, root: Path, frozen: dict[str, Any], *, dedupe_proposals: bool) -> None:
        self.root, self.frozen = root, frozen
        self.rows: list[dict[str, Any]] = []
        self.passed: list[str] = []
        self.stable = True
        self._seen: set[str] = set()
        self._signature: str | None = None
        self._dedupe = dedupe_proposals

    def block(self, index: int, reasons: list[str], **extra: Any) -> None:
        self.rows.append({'index': index, 'id': None, 'verdict': 'BLOCKED', 'reasons': reasons, **extra})

    def run(self, index: int, action: Any, **extra: Any) -> None:
        try:
            if identity(self.root, require_clean=True)['fingerprint'] != self.frozen['fingerprint']:
                raise ValueError('original source changed during tournament')
            result = action()
        except (ValueError, OSError) as exc:
            from ..security import redact_text
            self.block(index, [redact_text(str(exc))[:500]], **extra)
            return
        self._add(index, result, extra)

    def _add(self, index: int, result: dict[str, Any], extra: dict[str, Any]) -> None:
        rows = self.rows
        verdict = result['effective_verdict']
        prop_sha = result.get('proposal_sha256', '')
        row = {'index': index, 'id': result['id'], 'verdict': verdict,
               'proposal_sha256': prop_sha,
               'passport_sha256': digest(result.get('passport', {})),
               'diff_sha256': result.get('diff_sha256'),
               'reasons': list((result.get('passport') or {}).get('negative', [])),
               'seconds_used': result.get('seconds_used', 0), **extra}
        if self._dedupe and prop_sha in self._seen:
            row['verdict'] = 'INCONCLUSIVE'
            row['reasons'].append('duplicate candidate proposal in tournament')
            self.stable = False
            self.passed.clear()
        elif self._dedupe and prop_sha:
            self._seen.add(prop_sha)
        baseline = result.get('baseline')
        if baseline:
            signature = digest({k: baseline.get(k) for k in ('test_ids', 'environment_static', 'environment_key', 'executor')}
                               | {'test_inputs': baseline.get('pin', {}).get('test_inputs'),
                                  'outcomes': baseline.get('outcomes')})
            if self._signature is None:
                self._signature = signature
            elif self._signature != signature:
                row['verdict'] = 'INCONCLUSIVE'
                row['reasons'] = [*row['reasons'], 'baseline/test/runtime observations differ across candidates']
                # Earlier apparent eligibility is also withdrawn: comparison is no longer controlled.
                self.stable = False
                self.passed.clear()
                for previous in rows:
                    if previous['verdict'] == 'PASS':
                        previous['verdict'] = 'INCONCLUSIVE'
                        previous['reasons'].append('baseline differs across candidates')
        if not self.stable and row['verdict'] == 'PASS':
            row['verdict'] = 'INCONCLUSIVE'
            row['reasons'].append('baseline differs across candidates')
        if row['verdict'] == 'PASS':
            self.passed.append(result['id'])
        rows.append(row)


def finalize(root: Path, planned: dict[str, Any], frozen: dict[str, Any], acceptance: str, col: Collector,
             expected: int, started: float, *, provider_label: str, extra: dict[str, Any],
             limitations: list[str], abstain_reasons: list[str] | None = None) -> dict[str, Any]:
    rows, passed = col.rows, col.passed
    contract = decode(planned['contract'])
    unchanged = identity(root)['fingerprint'] == frozen['fingerprint']
    all_observed = len(rows) == expected and all(r.get('id') is not None and r.get('verdict') in {'PASS', 'FAIL'} for r in rows)
    winner = passed[0] if len(passed) == 1 and unchanged and col.stable and all_observed and not abstain_reasons else None
    reasons = ([] if winner else ['comparison abstained: zero or multiple eligible candidates, or changed source',
                                  *(abstain_reasons or [])])
    report = {'schema': 'repo-ai.candidate-comparison/1', 'acceptance_sha256': acceptance,
              'source': frozen['fingerprint'], 'provider': provider_label,
              'candidates': rows, 'winner': winner, 'verdict': 'PASS' if winner else 'INCONCLUSIVE',
              'reason': reasons, 'seconds_used': round(time.monotonic() - started, 3),
              'applied_to_source': False, 'limitations': limitations, **extra}

    comparison_id = digest({'acceptance': acceptance, 'candidates': rows})[:24]
    store = Store(root)
    record = {'id': comparison_id, 'kind': 'comparison', 'repository': store.repository,
              'state': 'CREATED', 'events': [], 'source': frozen, 'contract': contract.to_json(),
              'plan': planned, 'kernel': planned['kernel'], 'comparison': dict(report),
              'candidate_ids': [r['id'] for r in rows if r['id']],
              'passport': EvidenceRecord(frozen['fingerprint'], digest(contract.to_json()), report['verdict'],
                                         [digest(rows), digest(frozen), acceptance], reasons,
                                         report['limitations']).to_json()}
    for phase in ('PLANNED', 'READY', 'RUNNING', 'VERIFYING', 'REVIEWING'):
        transition(record, phase, 'comparison of already recorded isolated candidate evidence')
    transition(record, 'COMPLETE' if winner else 'INCONCLUSIVE')
    store.save(record)
    report['id'] = comparison_id
    return report


def inspect_comparison(root: Path, mission: str) -> dict[str, Any]:
    """Read-only inspection of a recorded candidate comparison with live freshness checks."""
    from .runtime import status
    state = status(root.resolve(), mission)
    if state.get('kind') != 'comparison' or not isinstance(state.get('comparison'), dict):
        raise ValueError('mission is not a candidate tournament comparison')
    comp = dict(state['comparison'])
    comp['id'] = mission
    comp['freshness'] = state['freshness']
    comp['freshness_reasons'] = list(state.get('freshness_reasons', []))
    comp['verdict'] = state['effective_verdict']
    comp['winner'] = comp.get('winner') if state['freshness'] == 'fresh' and state['effective_verdict'] == 'PASS' else None
    return comp


def render_comparison(report: dict[str, Any]) -> str:
    import json
    def quote(text: Any) -> str:
        return json.dumps(text, ensure_ascii=True)
    mid = report.get('id', 'comparison')
    freshness = report.get('freshness', 'fresh')
    lines = [
        f"{mid}: {report.get('verdict', 'INCONCLUSIVE')} ({freshness})",
        f"Winner: {report.get('winner') or 'none (abstained)'}",
    ]
    for cand in report.get('candidates', []):
        cid = cand.get('id') or 'not-run'
        cverdict = cand.get('verdict', 'BLOCKED')
        sec = cand.get('seconds_used', 0)
        who = f" {cand['provider']}" if cand.get('provider') else ''
        cost = ''
        if cand.get('provider'):
            cost = ', cost $' + str(cand['cost_usd']) if cand.get('cost_usd') is not None else ', cost UNKNOWN'
        claim = f", claims {cand['claims']}" if cand.get('claims') else ''
        lines.append(f"  [{cand.get('index', 0)}]{who} {cid}: {cverdict} ({sec}s{cost}{claim})")
        if cand.get('equivalent_to'):
            lines.append(f"      equivalent to {cand['equivalent_to']}")
        for reason in cand.get('reasons', []):
            lines.append(f"      reason: {quote(reason)}")
    for reason in report.get('freshness_reasons', []):
        lines.append('Invalidation: ' + quote(reason))
    if report.get('winner') or any(c.get('verdict') == 'PASS' for c in report.get('candidates', [])):
        lines.append('PASS means the frozen tests passed; task correctness is CLAIM_UNVERIFIED (see repo-ai why ID).')
    lines.append('No model self-voting or patch blending; winner is never auto-applied to source.')
    return '\n'.join(lines)
