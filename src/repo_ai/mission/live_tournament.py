"""Live multi-provider candidate tournament: 2-3 independently generated candidates, one verdict.

Each arm is an ordinary `runtime.execute` mission for ONE provider: its own disposable checkout of the same
frozen commit, its own provider process, the same visible acceptance command, and no visibility of any other
arm's output or of any hidden grader. repo-ai (not a model) re-observes every arm under the identical frozen
tests, then applies a predeclared rule:

  * exactly one arm PASSes                       -> that arm is the winner;
  * several PASS with byte-identical diffs       -> equivalent; the earliest listed arm is the winner;
  * several PASS with different diffs            -> ABSTAIN (no objective tie-breaker exists; not a vote,
                                                    not blended, not ranked by an LLM);
  * any arm crashed / was blocked / budget ran out / baselines differ / source changed -> ABSTAIN.

A winner means "the only distinct candidate whose frozen-test observation passed", never "correct".
Arms run sequentially, so wall-clock is the sum of arms; the aggregate time and (when enforceable) USD
ceilings are split across the remaining arms. Cost is OBSERVED only when a provider reports it; otherwise it is
UNKNOWN and is never summed as zero.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..providers.discovery import executable_name
from .contracts import decode, digest
from .runtime import LIVE_PROVIDERS, check_privacy, execute, identity, kernel_identity, plan, status
from .tournament import Collector, finalize

SCHEMA = 'repo-ai.live-tournament/1'
MIN_ARM_SECONDS = 5.0


def _validate(providers: list[str]) -> list[str]:
    names = [str(p).strip() for p in providers]
    if not 2 <= len(names) <= 3 or len(set(names)) != len(names):
        raise ValueError('a live tournament needs two or three distinct providers')
    unknown = [n for n in names if n not in LIVE_PROVIDERS]
    if unknown:
        raise ValueError('unknown provider(s): ' + ', '.join(unknown))
    # Two transports of one executable (opencode, opencode-acp) are one agent with one configured model: not
    # independent candidates, so they never count as two arms.
    families = [executable_name(n) for n in names]
    shared = sorted({f for f in families if families.count(f) > 1})
    if shared:
        raise ValueError('a live tournament needs independent providers; these share an executable: '
                         + '; '.join(f"{f} ({', '.join(n for n in names if executable_name(n) == f)})" for f in shared))
    return names


def _readiness(root: Path, providers: list[str], max_cost_usd: float) -> dict[str, dict[str, Any]]:
    """Routing facts only (no model call, no credential read, nothing billable)."""
    from ..providers.registry import route
    decision = route(root, max_cost_usd=max_cost_usd, run_authorized=True, preferred=providers)
    return {row['provider']: row for row in decision['considered'] if row['provider'] in providers}


def plan_tournament(root: Path, task: str, providers: list[str], *, write_paths: list[str] | None = None,
                    max_cost_usd: float = 0.0, max_seconds: float = 600.0, command: str = 'python -m pytest',
                    executables: dict[str, Path] | None = None) -> dict[str, Any]:
    """Plan only: one plan per arm plus the bounds and readiness. Starts no provider and runs no test."""
    root = root.resolve()
    names = _validate(providers)
    if max_seconds < MIN_ARM_SECONDS * len(names):
        raise ValueError(f'max_seconds must allow at least {MIN_ARM_SECONDS:g}s per arm')
    readiness = {} if executables else _readiness(root, names, max_cost_usd)
    problems = [f"{n}: {'; '.join(r['reasons'])}" for n, r in readiness.items() if not r['eligible']]
    if problems:
        raise ValueError('provider(s) not eligible for a live tournament: ' + ' | '.join(problems))
    per_arm_usd = round(max_cost_usd / len(names), 6) if max_cost_usd > 0 else 0.0
    if max_cost_usd > 0:
        from ..providers.adapters import contract_for
        unenforced = [n for n in names if not contract_for(n).enforces_hard_usd_budget]
        if unenforced:
            raise ValueError(f"cannot enforce a USD ceiling for: {', '.join(unenforced)} (cost would be UNKNOWN); "
                             'omit --max-cost-usd or choose providers with a hard budget flag')
    arms: list[dict[str, Any]] = []
    for name in names:
        arm = plan(root, task, agent=name, write_paths=write_paths, execute_local=True, allow_live=True,
                   max_cost_usd=per_arm_usd, max_seconds=max_seconds / len(names), command=command)
        arms.append({'provider': name, 'plan': arm})
    first = arms[0]['plan']
    if len({a['plan']['source']['fingerprint'] for a in arms}) != 1 or first['decision'] != 'LIVE_SINGLE_AGENT':
        raise ValueError('tournament arms need one clean frozen source: ' + str(first['decision']) + ': ' + first['why'])
    return {'schema': SCHEMA + '.plan', 'providers': names, 'arms': arms,
            'bounds': {'max_seconds_total': max_seconds, 'max_cost_usd_total': max_cost_usd,
                       'per_arm_cost_usd': per_arm_usd, 'sequential': True,
                       'cost_semantics': 'USD ceiling enforced per arm' if max_cost_usd > 0 else
                                         'UNKNOWN unless a provider reports it; never counted as $0'},
            'readiness': readiness,
            'rule': 'one distinct passing arm wins; identical passing diffs are equivalent; otherwise abstain'}


def run_tournament(root: Path, task: str, providers: list[str], *, write_paths: list[str] | None = None,
                   max_cost_usd: float = 0.0, max_seconds: float = 600.0, command: str = 'python -m pytest',
                   executables: dict[str, Path] | None = None) -> dict[str, Any]:
    root = root.resolve()
    tplan = plan_tournament(root, task, providers, write_paths=write_paths, max_cost_usd=max_cost_usd,
                            max_seconds=max_seconds, command=command, executables=executables)
    arms = tplan['arms']
    first = arms[0]['plan']
    if not check_privacy(root, first['contract']):
        raise ValueError('zone policy changed or unbound legacy contract; create a fresh plan')
    if first.get('kernel') != kernel_identity():
        raise ValueError('stale mission kernel; create a fresh plan')
    frozen = identity(root, require_clean=True)
    if frozen['fingerprint'] != first['source']['fingerprint']:
        raise ValueError('stale tournament plan')
    contract = decode(first['contract'])
    acceptance = digest({'source': frozen, 'acceptance': contract.acceptance, 'paths': contract.write_paths,
                         'providers': tplan['providers'], 'network': True})
    started = time.monotonic()
    col = Collector(root, frozen, dedupe_proposals=False)
    spent = 0.0
    unknown_cost: list[str] = []
    abstain: list[str] = []
    for index, arm in enumerate(arms):
        name, planned = arm['provider'], arm['plan']
        share = (max_seconds - (time.monotonic() - started)) / (len(arms) - index)
        if share < MIN_ARM_SECONDS:
            col.block(index, ['aggregate time budget exhausted'], provider=name)
            abstain.append(f'{name}: aggregate time budget exhausted')
            continue
        if max_cost_usd > 0 and spent >= max_cost_usd:
            col.block(index, ['aggregate cost ceiling exhausted'], provider=name)
            abstain.append(f'{name}: aggregate cost ceiling exhausted')
            continue
        planned['contract']['max_seconds'] = round(share, 3)
        if max_cost_usd > 0:
            planned['contract']['max_cost_usd'] = round(min(tplan['bounds']['per_arm_cost_usd'], max_cost_usd - spent), 6)
        exe = (executables or {}).get(name)

        def run_arm(planned: dict[str, Any] = planned, exe: Path | None = exe) -> dict[str, Any]:
            return execute(root, planned, None, provider_executable=exe, allow_live=True)

        before = len(col.rows)
        col.run(index, run_arm, provider=name)
        row = col.rows[-1] if len(col.rows) > before else None
        if row is None or row['id'] is None:
            detail = '; '.join(row['reasons'])[:200] if row else 'unknown'
            abstain.append(f'{name}: arm did not complete ({detail})')
            continue
        state = status(root, row['id'])
        prov = state.get('provider') or {}
        row['cost_status'] = prov.get('cost_status', 'UNKNOWN')
        row['cost_usd'] = prov.get('cost_usd') if row['cost_status'] == 'OBSERVED' else None
        row['provider_label'] = prov.get('verification_label')
        row['claims'] = (state.get('claims') or {}).get('headline')
        if row['cost_status'] == 'OBSERVED':
            spent += float(prov.get('cost_usd') or 0.0)
        else:
            unknown_cost.append(name)
        if row['verdict'] == 'PASS' and not (state.get('diff') or '').strip():
            row['verdict'] = 'INCONCLUSIVE'
            row['reasons'].append('empty candidate diff cannot win')
            if row['id'] in col.passed:
                col.passed.remove(row['id'])
    _collapse_equivalent(col)
    if len(col.passed) > 1:
        abstain.append('several distinct passing candidates and no predeclared objective tie-breaker')
    return finalize(
        root, first, frozen, acceptance, col, len(arms), started,
        provider_label='live: ' + ', '.join(tplan['providers']),
        extra={'tournament': SCHEMA, 'providers': tplan['providers'],
               'cost_usd_observed': round(spent, 6), 'cost_unknown_for': unknown_cost,
               'cost_semantics': 'UNKNOWN for providers without reported cost; the observed sum excludes them',
               'bounds': tplan['bounds']},
        limitations=[
            'Winner means the only distinct candidate whose frozen-test observation passed; not a correctness claim',
            'Candidates were generated independently from one frozen commit; no patch blending, no model self-voting',
            "Arms ran sequentially; a provider did not see another provider's output or any hidden grader",
            'Winner is never auto-applied; re-verify after repo-ai apply'],
        abstain_reasons=abstain)


def _collapse_equivalent(col: Collector) -> None:
    """Identical passing diffs are one candidate: keep the earliest, mark the rest equivalent."""
    by_diff: dict[str, dict[str, Any]] = {}
    for row in col.rows:
        if row.get('verdict') != 'PASS' or not row.get('diff_sha256'):
            continue
        keeper = by_diff.setdefault(row['diff_sha256'], row)
        if keeper is not row:
            row['equivalent_to'] = keeper['id']
            row['reasons'] = [*row['reasons'], 'byte-identical to an earlier passing candidate']
            if row['id'] in col.passed:
                col.passed.remove(row['id'])


__all__ = ['SCHEMA', 'plan_tournament', 'run_tournament']
