"""Additive mission command surface; default planning is offline and ephemeral."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..locks import file_lock
from .ledger import TERMINAL, Store, transition
from ..providers.discovery import PROVIDERS
from .runtime import LIVE_PROVIDERS, apply_mission, continue_from_handoff, execute, handoff, plan, status, undo_mission, verify_handoff


def _root(args) -> Path:
    return Path(args.path or '.').resolve()


def _emit(value: dict[str, Any], args) -> None:
    if getattr(args, 'json', False) or getattr(args, 'format', '') == 'json':
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    schema = value.get('schema', '')
    if schema == 'repo-ai.candidate-comparison/1':
        from .tournament import render_comparison
        print(render_comparison(value))
        if value.get('winner'):
            print(f"Next: repo-ai apply {value['winner']}  (or repo-ai why {value['winner']})")
        elif sum(1 for c in value.get('candidates', []) if c.get('verdict') == 'PASS') > 1 and value.get('id'):
            print(f"Next: repo-ai shortlist {value['id']}  (evidence table for the distinct passing candidates)")
        return
    if schema == 'repo-ai.handoff/2':
        print(f"Handoff capsule for mission {value.get('mission')}: state={value.get('state')} (recovery={value.get('recovery_category')})")
        if value.get('target_provider'):
            print(f"  Target provider: {value['target_provider']}")
        print(f"  Modified scope: {', '.join(value.get('modified_files', [])) or 'none'}")
        for fact in value.get('facts', []):
            print(f"  Fact [{fact.get('standing')}]: {fact.get('claim')} ({fact.get('evidence', '')[:12]})")
        if value.get('next_command'):
            print('  Next: ' + ' '.join(value['next_command']))
        return
    if schema == 'repo-ai.handoff-verification/1':
        verdict = 'VALID' if value.get('valid') else 'INVALID'
        print(f"Handoff verification for {value.get('mission')}: {verdict} ({value.get('freshness')})")
        for reason in value.get('reasons', []):
            print('  Reason: ' + reason)
        return
    if schema == 'repo-ai.mission-trace/1':
        print(f"Mission trace {value.get('mission')}: {value.get('verdict')} ({value.get('freshness')})")
        for ev in value.get('events', []):
            print(f"  [{ev.get('index')}] {ev.get('from')} -> {ev.get('to')}: {ev.get('reason')}")
        return
    if schema == 'repo-ai.mission-undo/1':
        print(f"Restored mission {value.get('mission')} using its application receipt.")
        return
    if schema == 'repo-ai.mission-apply/1':
        print(f"Applied verified mission {value.get('mission')} to working tree: {value.get('post_apply_verdict')}")
        print(f"  Modified files: {', '.join(value.get('modified_files', []))}")
        print(f"  Post-apply verification: {value.get('post_apply_ran')} tests ran, {value.get('post_apply_failed')} failed")
        return
    if schema == 'repo-ai.reality-eval/1':
        print(f"Reality Engine Evaluation ({value.get('mode')}) — lift verdict: {value.get('comparative_lift_verdict', 'NOT_YET_DEMONSTRATED')}")
        for arm_name, arm_data in (value.get('arms') or {}).items():
            print(
                f"  {arm_name}: verified_completion={arm_data.get('verified_completion_rate')}, "
                f"false_pass={arm_data.get('false_pass_rate')}, cost=${arm_data.get('cost_usd')}"
            )
        return
    if 'decision' in value:
        print(f"{value['decision']}: {value['why']}")
        print('Planning only; no provider or tests invoked.' if not getattr(args, 'run', False) else 'Explicit local execution requested.')
        for location in value['context']['packet']['locations']:
            print('  ' + location['path'] + ': ' + '; '.join(location['why']))
        print('Unknowns: ' + '; '.join(value['context']['packet']['uncertainty']))
        orch = value.get('orchestration') or {}
        if orch:
            print(f"Orchestration ({orch.get('complexity', 'moderate')}): merge_owner={orch.get('merge_owner', 'controller')}")
        return
    if 'state' in value:
        prov = value.get('provider') or {}
        plabel = prov.get('verification_label') or ('SIMULATED' if prov.get('simulated', True) else 'LIVE')
        print(f"{value.get('id', value.get('mission'))}: {value['state']} — {value.get('effective_verdict', 'local handoff')} [{plabel}]")
        print('Freshness: ' + value.get('freshness', 'see linked evidence'))
        cost = ('$' + str(prov.get('cost_usd'))) if prov.get('cost_status') == 'OBSERVED' else 'UNKNOWN'
        print(f"Elapsed: {value.get('seconds_used', 0)}s | provider: {prov.get('name', 'none')} | observed cost: {cost}")
        cont = value.get('continued_from') or {}
        if cont:
            seeded = 'carried a verified partial diff' if cont.get('partial_patch_transferred') else 'fresh candidate'
            print(f"Continued from {cont.get('mission')} ({cont.get('prior_provider')}, "
                  f"{cont.get('prior_seconds_debited', 0)}s debited): {seeded}")
            if cont.get('write_paths_added_by_user'):
                print('  Write paths added on this continuation by you: ' + ', '.join(cont['write_paths_added_by_user']))
        for reason in (value.get('passport') or {}).get('negative', []):
            print('  ' + reason)
        claim = value.get('claims') or {}
        if claim.get('headline') and claim['headline'] != 'OBSERVED_TESTS_PASS' and value.get('effective_verdict') == 'PASS':
            print(f"  Claim: {claim['headline']} — tests passed; task correctness is not established")
            for note in claim.get('notes', [])[1:4]:
                print('  Limit: ' + note)
        if value.get('effective_verdict') == 'PASS':
            from .runtime import exercise_notes
            for note in exercise_notes(value.get('exercise')):
                print('  Limit: ' + note)
        if value.get('diff'):
            status_note = 'APPLIED to working tree' if value.get('applied_to_source') else 'Candidate tested, NOT applied to original source'
            print(f"{status_note}:\n" + value['diff'])
        mid = value.get('id') or value.get('mission')
        if mid:
            if value.get('effective_verdict') == 'PASS' and not value.get('applied_to_source'):
                print(f"Next: repo-ai apply {mid}  (or repo-ai futures {mid} --rehearse)")
            elif value.get('effective_verdict') != 'PASS':
                rec = value.get('recovery') or {}
                if rec.get('action'):
                    print(f"Recovery [{rec.get('category')}]: {rec.get('action')}")
                print(f"Next: repo-ai why-test-failed {mid}  (or repo-ai handoff {mid} --to bob)")
        return
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_do(args) -> int:
    if args.run and args.dry_run:
        raise ValueError('--run and --dry-run are mutually exclusive')
    if args.resume:
        args.id = args.resume
        args.action = 'resume'
        return cmd_mission(args)
    root = _root(args)
    if getattr(args, 'from_handoff', None):
        if not args.run:
            raise ValueError('--from-handoff continuation requires --run')
        value = continue_from_handoff(
            root,
            Path(args.from_handoff),
            agent=args.agent,
            replay_path=Path(args.replay) if getattr(args, 'replay', None) else None,
            provider_executable=Path(args.provider_executable) if getattr(args, 'provider_executable', None) else None,
            allow_live=bool(getattr(args, 'allow_live_provider', False)),
            max_cost_usd=args.max_cost_usd if args.max_cost_usd > 0 else None,
            extra_write_paths=list(args.allow_write or []),
        )
        if getattr(args, 'apply', False) and value.get('effective_verdict') == 'PASS':
            apply_res = apply_mission(root, value['id'])
            value['applied_to_source'] = apply_res['applied_to_source']
            value['apply_result'] = apply_res
            if value.get('provider') and apply_res.get('provider_verification_label'):
                value['provider']['verification_label'] = apply_res['provider_verification_label']
            if value.get('provider') and apply_res.get('provider_verification_label'):
                value['provider']['verification_label'] = apply_res['provider_verification_label']
        _emit(value, args)
        return 0 if value.get('effective_verdict') == 'PASS' else 2

    if not args.task:
        raise ValueError('supply an outcome, --from-handoff FILE, or --resume ID')
    allow_live = bool(getattr(args, 'allow_live_provider', False))
    if getattr(args, 'tournament', None):
        return _cmd_live_tournament(args, root, allow_live)
    value = plan(
        root,
        args.task,
        agent=args.agent,
        write_paths=args.allow_write,
        execute_local=args.run,
        max_cost_usd=args.max_cost_usd,
        max_parallel=args.max_parallel,
        max_seconds=args.max_seconds,
        command=args.test_command,
        allow_live=allow_live,
        roles=args.role,
    )
    if args.run:
        if args.candidate:
            if args.replay:
                raise ValueError('--replay and --candidate are mutually exclusive')
            from .tournament import compare_candidates
            value = compare_candidates(root, value, [Path(p) for p in args.candidate])
        elif args.replay:
            value = execute(root, value, Path(args.replay))
        elif getattr(args, 'provider_executable', None):
            value = execute(
                root,
                value,
                None,
                provider_executable=Path(args.provider_executable),
                allow_live=allow_live,
            )
        elif allow_live and value['contract']['provider'] in LIVE_PROVIDERS:
            value = execute(root, value, None, allow_live=True)
        else:
            raise ValueError(
                'live provider execution requires --allow-live-provider (or use --agent replay --replay FILE for simulated execution)'
            )
        if getattr(args, 'apply', False) and value.get('effective_verdict', value.get('verdict')) == 'PASS':
            target_id = value.get('winner') if value.get('schema') == 'repo-ai.candidate-comparison/1' else value.get('id')
            if target_id:
                apply_res = apply_mission(root, target_id)
                value['applied_to_source'] = apply_res['applied_to_source']
                value['apply_result'] = apply_res
                if value.get('provider') and apply_res.get('provider_verification_label'):
                    value['provider']['verification_label'] = apply_res['provider_verification_label']
    _emit(value, args)
    return 0 if not args.run or value.get('effective_verdict', value.get('verdict')) == 'PASS' else 2


def _cmd_live_tournament(args, root: Path, allow_live: bool) -> int:
    from .live_tournament import plan_tournament, run_tournament
    if args.candidate or args.replay or getattr(args, 'provider_executable', None) or args.apply:
        raise ValueError('--tournament is incompatible with --candidate, --replay, --provider-executable and --apply')
    providers = [p for p in args.tournament.split(',') if p]
    options = dict(write_paths=args.allow_write, max_cost_usd=args.max_cost_usd,
                   max_seconds=max(args.max_seconds, 600.0) if args.max_seconds == 120 else args.max_seconds,
                   command=args.test_command)
    if not args.run:
        tplan = plan_tournament(root, args.task, providers, **options)
        value = {'schema': 'repo-ai.live-tournament.plan/1', 'providers': tplan['providers'], 'bounds': tplan['bounds'],
                 'rule': tplan['rule'], 'readiness': tplan['readiness'],
                 'note': 'Planning only; no provider or test was started. Add --run --allow-live-provider to execute.'}
        if getattr(args, 'json', False):
            print(json.dumps(value, indent=2, sort_keys=True))
        else:
            print(f"Live tournament plan: {', '.join(value['providers'])} (sequential, one frozen commit, same visible tests)")
            print('Bounds: ' + json.dumps(value['bounds'], sort_keys=True))
            print('Rule: ' + value['rule'])
            for name, row in value['readiness'].items():
                print(f"  {name}: {'eligible' if row['eligible'] else '; '.join(row['reasons'])}")
            print(value['note'])
        return 0
    if not allow_live:
        raise ValueError('a live tournament needs --allow-live-provider (it starts external provider processes)')
    value = run_tournament(root, args.task, providers, **options)
    _emit(value, args)
    return 0 if value.get('winner') else 2


def cmd_apply(args) -> int:
    res = apply_mission(_root(args), args.id)
    _emit(res, args)
    return 0 if res.get('post_apply_verdict') == 'PASS' else 2


def cmd_shortlist(args) -> int:
    from .shortlist import build, render
    from .tournament import inspect_comparison
    root = _root(args)
    sl = build(root, inspect_comparison(root, args.id), args.policy)
    if args.json:
        print(json.dumps(sl, indent=2, sort_keys=True))
    else:
        print(render(sl))
    return 0


def cmd_coverage(args) -> int:
    from .coverage import for_mission, load_requirements, render
    report = for_mission(_root(args), args.id, load_requirements(Path(args.requirements)))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0 if report['headline'] == 'ACCEPTANCE_MAPPED_ALL' else 2


def cmd_undo(args) -> int:
    res = undo_mission(_root(args), args.id)
    _emit(res, args)
    return 0


def cmd_agents(args) -> int:
    from ..providers import discover
    from ..providers import registry
    root = _root(args)
    if args.action in {'authorize', 'revoke'}:
        if not args.provider:
            raise ValueError(f'agents {args.action} needs a provider name')
        policy = (registry.authorize(root, args.provider, prefer=args.prefer) if args.action == 'authorize'
                  else registry.revoke(root, args.provider))
        if args.json:
            print(json.dumps(policy, indent=2, sort_keys=True))
        else:
            print('Authorized providers for this project: ' + (', '.join(policy['authorized']) or 'none'))
            print('Authorization only permits selection; each live run still needs --allow-live-provider.')
        return 0
    if args.action == 'setup':
        return _agents_setup(args)
    if args.action == 'route':
        decision = registry.route(root, max_cost_usd=args.max_cost_usd, run_authorized=args.allow_live_provider)
        if args.json:
            print(json.dumps(decision, indent=2, sort_keys=True))
        else:
            print(f"{decision['outcome']}: {decision['why']}")
            for row in decision['considered']:
                print(f"  {row['provider']} [{row.get('readiness', 'UNKNOWN')} -> {row.get('status_class', 'UNKNOWN')}]: " + '; '.join(row['reasons']))
            print('Not evaluated (needs a live run): ' + ', '.join(decision['not_evaluated']))
        return 0
    values = discover(root, probe=args.action == 'doctor')
    if args.json:
        print(json.dumps({'schema': 'repo-ai.agent-inventory/1', 'providers': values}, indent=2))
    else:
        for value in values:
            print(f"{value['provider']}: {value['status']} | {value['version'] or 'version not probed'} | auth {value['authentication']}")
        print('No model was invoked. Installed executable does not establish authenticated runnable availability.')
    return 0


def _agents_setup(args) -> int:
    """Offline: how this provider authenticates inside repo-ai's isolation, and the one command that fixes it."""
    if args.provider == 'opencode':
        from ..providers import opencode_cfg
        problems = opencode_cfg.setup_problems()
        value: dict[str, Any] = {'schema': 'repo-ai.provider-setup/1', 'provider': 'opencode', 'mode': 'local_endpoint',
                 'endpoint': opencode_cfg.base_url(), 'model': os.environ.get(opencode_cfg.MODEL_ENV) or None,
                 'problems': problems, 'ready_to_try': not problems, 'model_invoked': False, 'credential_read': False}
        if args.json:
            print(json.dumps(value, indent=2, sort_keys=True))
        else:
            print(f"opencode: local model endpoint {value['endpoint']} (loopback only; code never leaves this machine)")
            for problem in problems:
                print(f'  - {problem}')
            print('Ready to try.' if not problems else 'Example: ollama pull qwen3:8b && export '
                  f'{opencode_cfg.MODEL_ENV}=qwen3:8b')
            print('No model was invoked.')
        return 0 if not problems else 2
    if args.provider != 'claude':
        raise ValueError('agents setup currently explains: claude, opencode (other providers authenticate as '
                         'documented in docs/engineering/INTEGRATIONS.md)')
    from ..providers import claude_auth
    plan = claude_auth.plan()
    value = {'schema': 'repo-ai.provider-setup/1', 'provider': 'claude', **plan.to_json(), 'ready_to_try': plan.usable,
             'login_command': claude_auth.login_command(claude_auth.default_config_dir()),
             'model_invoked': False, 'credential_read': False}
    if args.json:
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0 if plan.usable else 2
    modes = {'token_env': 'token from the environment (' + ', '.join(plan.env_vars) + '); scratch HOME, no keychain',
             'dedicated_config': f'dedicated repo-ai login at {plan.config_dir}; HOME read-restricted',
             'none': 'no login repo-ai can use'}
    print(f'claude: {modes[plan.mode]}')
    for problem in plan.problems:
        print(f'  - {problem}')
    if plan.usable:
        print('Ready to try. A live run still needs --allow-live-provider (or agents authorize claude) and is checked '
              'by its result, not by this command.')
    else:
        print('Fix it once, either way:')
        print(f'  1. {value["login_command"]}   (a separate login just for repo-ai; your ~/.claude is untouched)')
        print('  2. export CLAUDE_CODE_OAUTH_TOKEN=...   (from `claude setup-token`; strongest isolation)')
    print('No model was invoked and no credential was read.')
    return 0 if plan.usable else 2


def cmd_mission(args) -> int:
    root, mission = _root(args), args.id
    store = Store(root)
    if args.action == 'list':
        if mission:
            raise ValueError('mission list does not accept a mission ID')
        store._check()
        rows = []
        for path in sorted(store.folder.glob('*.json'))[:64]:
            try:
                item = status(root, path.stem)
                rows.append({'id': path.stem, 'state': item['state'],
                             'verdict': item['effective_verdict'], 'freshness': item['freshness']})
            except (ValueError, OSError):
                rows.append({'id': path.stem, 'state': 'UNAVAILABLE',
                             'verdict': 'INCONCLUSIVE', 'freshness': 'not checked'})
        if args.json:
            print(json.dumps({'schema': 'repo-ai.mission-list/1', 'missions': rows}, indent=2))
        else:
            print('No local missions.' if not rows else '\n'.join(
                f"{r['id']}: {r['state']} — {r['verdict']} ({r['freshness']})" for r in rows))
        return 0
    if not mission:
        raise ValueError('mission ID is required for ' + args.action)
    state = store.load(mission)
    from .runtime import check_privacy
    if 'contract' in state:
        check_privacy(root, state['contract'])
    if args.action == 'resume' and getattr(args, 'run', False):
        if not getattr(args, 'replay', None):
            raise ValueError('explicit resume requires the same --replay FILE and --run consent')
        from .contracts import decode, digest
        from .runtime import proposal
        if digest(proposal(Path(args.replay), root, decode(state['contract']))) != state['proposal_sha256']:
            raise ValueError('resume proposal does not match the original mission')
        value = execute(root, state['plan'], Path(args.replay), resume=True)
        if value['id'] != mission:
            raise ValueError('resume proposal does not match the original mission')
        _emit(value, args)
        return 0 if value['effective_verdict'] == 'PASS' else 2
    if args.action in {'cancel', 'resume'}:
        if state['state'] not in TERMINAL:
            if args.action == 'cancel':
                marker = store.folder / (mission + '.cancel')
                marker.touch(mode=0o600, exist_ok=True)
            with file_lock(store.folder / (mission + '.lock'), timeout=0) as locked:
                if locked:
                    state = store.load(mission)
                    if state['state'] not in TERMINAL:
                        transition(state, 'CANCELLED' if args.action == 'cancel' else 'INCONCLUSIVE',
                                   'Cancelled locally' if args.action == 'cancel' else
                                   'Interrupted controller recovered; original source untouched. Review preserved evidence before a new attempt.')
                        store.save(state)
                else:
                    state['notice'] = ('Cancellation requested; takes effect between bounded test phases' if args.action == 'cancel'
                                       else 'Controller is still running; cannot resume concurrently')
    result = status(root, mission)
    if 'notice' in state:
        result['notice'] = state['notice']
    _emit(result, args)
    return 0


def cmd_read(args) -> int:
    if args.command == 'why':
        from .explanation import explain, render
        report = explain(_root(args), args.id)
        if args.json or args.format == 'json':
            _emit(report, args)
        else:
            print(render(report))
        return 0
    if args.command == 'compare':
        from .tournament import inspect_comparison, render_comparison
        report = inspect_comparison(_root(args), args.id)
        if args.json or args.format == 'json':
            _emit(report, args)
        else:
            print(render_comparison(report))
        return 0 if report.get('verdict') == 'PASS' else 2
    if args.command == 'handoff':
        if getattr(args, 'verify', None):
            from ..verify.isolate import read_inside
            capsule_path = Path(args.verify)
            raw = read_inside(capsule_path.parent.resolve(), capsule_path.name, 256_000)
            if raw is None:
                raise ValueError('handoff capsule must be a bounded regular JSON file')
            raw_capsule = json.loads(raw)
            ver = verify_handoff(_root(args), raw_capsule)
            _emit(ver, args)
            return 0 if ver['valid'] else 2
        value = handoff(_root(args), args.id, target_provider=getattr(args, 'to', None))
        _emit(value, args)
        return 0
    value = status(_root(args), args.id)
    if args.command in {'trace', 'replay'}:
        value = {'schema': 'repo-ai.mission-trace/1', 'mission': args.id, 'events': value['events'],
                 'freshness': value['freshness'], 'verdict': value['effective_verdict'],
                 'mode': 'deterministic stored-event replay; no provider invocation or test rerun'}
    _emit(value, args)
    return 0


def cmd_diagnose(args) -> int:
    from .diagnosis import diagnose, render
    report = diagnose(_root(args), args.id, test=args.test)
    if args.json:
        _emit(report, args)
    else:
        print(render(report))
    return 0 if report['standing'] == 'OBSERVED' else 2


def cmd_futures(args) -> int:
    from .futures import analyze_futures, render_futures
    report = analyze_futures(
        _root(args),
        args.id,
        paths=args.target_paths,
        rehearse=bool(getattr(args, 'rehearse', False)),
    )
    if args.json or args.format == 'json':
        _emit(report, args)
    else:
        print(render_futures(report))
    return 0


def cmd_demo(args) -> int:
    from .demo import run_demo
    report = run_demo(Path(args.directory), language=args.language, tournament=args.tournament, quiet=args.json)
    if args.json:
        _emit(report, args)
    return 0 if report['verdict'] == 'PASS' else 2


def cmd_mission_eval(args) -> int:
    from .eval_protocol import run_evaluation_protocol
    target = Path(args.directory) if getattr(args, 'directory', None) else None
    report = run_evaluation_protocol(target)
    _emit(report, args)
    return 0 if report['arms']['reality_engine_verified']['verified_completion_rate'] == 1.0 else 2


def register(sub, common) -> None:
    p = sub.add_parser('why-test-failed', parents=[common], help='explain recorded baseline/candidate test failures; no execution')
    p.add_argument('id', help='individual candidate mission ID')
    p.add_argument('--test', metavar='EXACT_ID', help='filter to one recorded test identity')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_diagnose)
    p = sub.add_parser('futures', parents=[common], help='experimental static/heuristic change futures across local and same-zone peers')
    p.add_argument('id', nargs='?', help='optional mission ID whose write_paths will be analyzed')
    p.add_argument('--target-path', dest='target_paths', action='append', default=[], metavar='PATH',
                   help='explicit relative source path to analyze')
    p.add_argument('--rehearse', action='store_true', help='rehearse mission candidate diff against linked tests in an isolated sandbox')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.add_argument('--format', choices=['text', 'json'], default='text')
    p.set_defaults(func=cmd_futures)
    p = sub.add_parser('apply', parents=[common], help='apply a fresh verified mission diff to the working tree and verify post-apply state')
    p.add_argument('id', help='verified mission or comparison ID')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_apply)
    p = sub.add_parser('shortlist', parents=[common], help='evidence table for an abstained tournament; optional labelled policy preference; applies nothing')
    p.add_argument('id', help='tournament comparison ID')
    p.add_argument('--policy', choices=['strict', 'smallest-diff'], default='strict',
                   help='strict (default) only lists candidates; smallest-diff additionally marks a POLICY_PREFERENCE')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_shortlist)
    p = sub.add_parser('coverage', parents=[common], help='map developer-declared requirements to the tests that observed them; no execution, never a correctness claim')
    p.add_argument('id', help='single candidate mission ID')
    p.add_argument('--requirements', required=True, metavar='FILE', help='JSON {schema: repo-ai.requirements/1, requirements: [{text, kind: change|preserve, tests: [ids]}]}')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_coverage)
    p = sub.add_parser('undo', parents=[common], help='restore receipt-owned applied bytes; refuse later user edits')
    p.add_argument('id', help='applied candidate mission ID')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_undo)
    p = sub.add_parser('demo', parents=[common], help='run a zero-cost simulated local acceptance demo in an empty directory')
    p.add_argument('--directory', required=True, metavar='DIR', help='new or empty directory for the demo')
    p.add_argument('--language', choices=['python', 'node'], default='python')
    p.add_argument('--tournament', action='store_true', help='compare a superficial fix against a valid fix')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser('mission-eval', parents=[common], help='run deterministic zero-cost Reality Engine vs naive baseline protocol')
    p.add_argument('--directory', metavar='DIR', help='optional directory to persist eval-report.json')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_mission_eval)
    p = sub.add_parser('do', parents=[common], help='plan an outcome offline; run an isolated replay or authorized live provider candidate')
    p.add_argument('task', nargs='?', help='the outcome you want, in plain language')
    p.add_argument('--dry-run', action='store_true', help='plan only (the default); no persistent repository writes')
    p.add_argument('--run', action='store_true', help='authorize local sandboxed tests and candidate edits in a disposable worktree')
    p.add_argument('--allow-live-provider', action='store_true', help='authorize live external coding agent invocation in an isolated worktree')
    p.add_argument('--from-handoff', metavar='FILE', help='continue an interrupted/failed mission from a verified handoff capsule JSON file')
    p.add_argument('--apply', action='store_true', help='apply the candidate diff to the working tree after fresh PASS verification')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.add_argument('--agent', choices=['auto', 'none', 'replay', *PROVIDERS], default='auto')
    p.add_argument('--replay', metavar='FILE', help='explicitly simulated bounded JSON edit proposal; never a live agent')
    p.add_argument('--provider-executable', metavar='FILE', help='local non-billable provider executable for contract simulation')
    p.add_argument('--candidate', action='append', default=[], metavar='FILE', help='opt-in tournament: repeat for 2–3 isolated simulated proposals')
    p.add_argument('--tournament', metavar='A,B[,C]', help='live tournament: independent candidates from 2-3 providers; abstains unless exactly one distinct candidate passes')
    p.add_argument('--allow-write', action='append', default=[], metavar='PATH', help='allow one source path in the isolated candidate')
    p.add_argument('--max-cost-usd', type=float, default=0, help='explicit cost ceiling; default zero; replay requires zero')
    p.add_argument('--max-parallel', type=int, default=1, help='ceiling 1–4; P0 executes one writer sequentially')
    p.add_argument('--max-seconds', type=float, default=120, help='wall-clock limit per provider run (default: %(default)s)')
    p.add_argument('--test-command', choices=['python -m pytest', 'node --test'], default='python -m pytest')
    p.add_argument('--role', action='append', default=[], choices=['investigator', 'adversary'],
                   help='opt-in separate read-only provider process; refused for trivial changes; advisory, never a verdict')
    p.add_argument('--resume', metavar='ID', help='inspect/recover an interrupted checkpoint; no automatic model retry')
    p.set_defaults(func=cmd_do)
    p = sub.add_parser('agents', parents=[common], help='local provider availability; doctor runs sandboxed help/version only')
    p.add_argument('action', choices=['list', 'doctor', 'route', 'authorize', 'revoke', 'setup'])
    p.add_argument('provider', nargs='?', help='provider name for authorize/revoke/setup')
    p.add_argument('--prefer', action='store_true', help='with authorize: also prefer this provider in routing')
    p.add_argument('--allow-live-provider', action='store_true', help='route: evaluate as if this run were authorized')
    p.add_argument('--max-cost-usd', type=float, default=0, help='route: require an enforceable USD ceiling when > 0')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.set_defaults(func=cmd_agents)
    p = sub.add_parser('mission', parents=[common], help='inspect, cancel or recover local mission checkpoints')
    p.add_argument('action', choices=['list', 'status', 'cancel', 'resume'])
    p.add_argument('id', nargs='?', help='mission ID (list takes none)')
    p.add_argument('--json', action='store_true', help='machine-readable JSON output')
    p.add_argument('--run', action='store_true', help='explicitly resume a recoverable isolated replay attempt')
    p.add_argument('--replay', metavar='FILE', help='same proposal bytes as the interrupted mission')
    p.set_defaults(func=cmd_mission)
    for name in ('why', 'trace', 'handoff', 'replay', 'compare'):
        p = sub.add_parser(name, parents=[common], help='local mission ' + name + '; no provider disclosure')
        p.add_argument('id', nargs='?' if name == 'handoff' else None, help='mission ID')
        p.add_argument('--json', action='store_true', help='machine-readable JSON output')
        p.add_argument('--format', choices=['text', 'json'], default='text')
        if name == 'handoff':
            p.add_argument('--to', choices=['none', 'replay', *PROVIDERS],
                           help='optional target provider for local handoff adaptation')
            p.add_argument('--verify', metavar='FILE', help='verify a local handoff capsule JSON file against current repository state')
        p.set_defaults(func=cmd_read)
