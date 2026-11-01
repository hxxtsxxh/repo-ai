"""Intent -> isolated replay or authorized live provider candidate -> observed evidence.

A replay is explicitly simulated proposal input (`SIMULATED`), whereas an authorized
live provider run is labeled `LIVE_VERIFIED` only after independent sandbox test
observations and whole-change regression verification pass.
Candidates are returned as diffs and applied to the working tree only via an explicit
`repo-ai apply <id>` (or `--apply`) operation with post-apply verification.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import gitbin
from ..config import load_config
from ..locks import file_lock
from ..providers.discovery import PROVIDERS
from ..paths import make_dir, resolve_layout
from ..security import redact_text, sanitize_provider_text, source_contains_secret
from ..verify import engine, evidence, isolate, results
from ..verify.execute import get_executor, release
from .context import build_context
from .contracts import (
    MAX_PARSE_FILE,
    MAX_SOURCE_FILE,
    EvidenceRecord,
    ExecutionDAG,
    HandoffCapsule,
    IntentContract,
    Node,
    RealityGraph,
    decode,
    digest,
    relative_path,
)
from .ledger import TERMINAL, Store, transition

MAX_PATCH = 256_000


LIVE_PROVIDERS = frozenset(PROVIDERS)


def privacy_binding(root: Path) -> tuple[str, str]:
    """Read existing enrollment only; planning never creates registry state."""
    from ..registry import policy_for
    zone, policy = policy_for(root)
    if zone == '!conflict':
        raise ValueError('conflicting repository zones; repair registry before mission access')
    return zone or 'local', digest({'registered_zone': zone, 'policy': policy})


def check_privacy(root: Path, contract: dict[str, Any]) -> bool:
    zone, policy = privacy_binding(root)
    if contract.get('zone', 'local') != zone:
        raise ValueError('mission zone changed; prior task content is withheld')
    return contract.get('policy_sha256') == policy


def kernel_identity() -> str:
    package = Path(__file__).resolve().parents[1]
    # Root helpers include process cleanup, locking, Git and context analysis.
    # Enumerating the package avoids silently omitting a newly imported helper.
    paths = sorted(package.glob('*.py'))
    for directory in ('mission', 'verify', 'providers'):
        paths.extend(sorted(p for p in (package / directory).rglob('*') if p.suffix in {'.py', '.js', '.mjs', '.cjs'}))
    return digest({str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
                   if p.is_file() else 'missing' for p in paths})


def local_path_map(root: Path, *extra: Path) -> dict[str, str]:
    """Known local prefixes -> placeholders, for text that is persisted, exported or shown to another model."""
    known: dict[str, str] = {}
    for label, path in (('<repo>', root), ('<workspaces>', isolate.workspaces_root()), *((f'<workspace:{p.name}>', p) for p in extra),
                        ('<home>', Path.home())):
        for variant in {str(path), os.path.abspath(path), str(path.resolve())}:
            if len(variant) > 1:
                known.setdefault(variant, label)
    return known


def _exec_locator(store: Store, mission: str) -> Path:
    return store.folder / (mission + '.exec')


def tree_digest(path: Path) -> str:
    """Content digest of every non-.git file; detects a read-only role writing anything."""
    entries = {}
    for item in sorted(path.rglob('*')):
        rel = item.relative_to(path)
        if rel.parts[:1] == ('.git',):
            continue
        if item.is_symlink():
            entries[rel.as_posix()] = 'link:' + os.readlink(item)
        elif item.is_file():
            entries[rel.as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    return digest(entries)


def git(root: Path, *args: str, raw: bool = False) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_TERMINAL_PROMPT='0',
               GIT_AUTHOR_NAME='repo-ai mission', GIT_AUTHOR_EMAIL='local@example.invalid',
               GIT_COMMITTER_NAME='repo-ai mission', GIT_COMMITTER_EMAIL='local@example.invalid')
    p = subprocess.run([gitbin.git(), '--no-optional-locks', '-c', 'core.hooksPath=' + os.devnull,
                        '-c', 'core.fsmonitor=false', *args], cwd=root, env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=False)
    if p.returncode:
        raise ValueError('Git operation failed: ' + redact_text(p.stderr.decode('utf-8', 'replace'))[:500])
    if len(p.stdout) > 2_000_000:
        raise ValueError('repository listing exceeds mission bound')
    text = p.stdout.decode('utf-8', 'strict')
    if raw:  # byte-exact: a patch's trailing blank context line is ' \n' and must not be stripped
        return text
    return text.rstrip('\0\r\n') if '-z' in args else text.strip()


def commit_snapshot(repo: Path, files: list[str] | Any, message: str) -> None:
    """Commit a workspace built from the source's tracked `files` as a fresh repository. `git add -A` skips a tracked
    file that a `.gitignore` pattern also matches (python-humanize tracks an ignored `_version.py` stub); those are
    added by name, and nothing else the workspace holds (dependency links) is forced in."""
    git(repo, 'init', '-q')
    git(repo, 'add', '-A')
    indexed = set(git(repo, 'ls-files', '-z').split('\0'))
    missing = sorted(set(files) - indexed)
    for i in range(0, len(missing), 200):  # literal names: `[id].py` or `:!x` must not act as patterns
        git(repo, 'add', '--force', '--', *(':(literal)' + p for p in missing[i:i + 200]))
    git(repo, 'commit', '-qm', message)


def identity(root: Path, *, require_clean: bool = False) -> dict[str, Any]:
    store = Store(root)
    head = git(root, 'rev-parse', '--verify', 'HEAD')
    tracked = git(root, 'ls-files', '-z').split('\0')
    # repo-ai's own files (and the other state the workspace archive never copies) are not mission source:
    # comparing them would read a committed `.repo-ai/config.toml` as a provider edit
    tracked = [p for p in tracked if p and not p.startswith(isolate.STATE_PREFIXES)]
    if len(tracked) > 5000:
        raise ValueError('mission scope exceeds 5000 tracked files')
    state_rel = store.layout.state_dir.relative_to(root).as_posix()
    changes = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all').split('\0')
    # repo-ai's own directory (created by `repo-ai init`) never makes the checkout dirty for a mission; a configured
    # state_dir elsewhere is exempt only for UNTRACKED entries (it can be set by configuration, so tracked source under
    # it must still count: otherwise state_dir = "lib" would hide a real edit to lib/)
    dirty = [p for p in changes if p and not (p[3:].startswith('.repo-ai/') or p.startswith('?? ' + state_rel + '/'))]
    # `repo-ai init` adds a managed block to `.gitignore` (or creates it). A file whose only change is that block does
    # not make the checkout dirty; its working bytes stay in the identity, as in the provider's workspace copy
    dirty = [p for p in dirty if not (p.startswith(' M ') and committed_if_only_managed_blocks(root, p[3:]) is not None
                                      or p.startswith('?? ') and _only_managed_blocks(root, p[3:], state_rel))]
    if require_clean and dirty:
        shown = [redact_text(p[3:])[:120] for p in dirty if len(p) > 3][:5]
        more = f' and {len(dirty) - len(shown)} more' if len(dirty) > len(shown) else ''
        raise ValueError('dirty checkout: commit or preserve edits before isolated execution (' + ', '.join(shown)
                         + more + ')')
    contents = {}
    total = 0
    for path in tracked:
        try:
            data = isolate.read_inside(root, path, MAX_SOURCE_FILE)
        except isolate.ReportTooLarge:
            raise ValueError(f'tracked file {redact_text(path)[:200]} is larger than {MAX_SOURCE_FILE // 1_000_000} MB; '
                             'isolated missions bound each source file') from None
        if data is None:
            if require_clean:
                raise ValueError('source includes missing or nonregular files; isolated mission abstains')
            contents[path] = 'missing-or-nonregular'
        else:
            total += len(data)
            if total > 50_000_000:
                raise ValueError('mission source exceeds 50 MB bound')
            contents[path] = hashlib.sha256(data).hexdigest()
    return {'head': head, 'files': contents, 'dirty': bool(dirty),
            'dirty_paths': [p[3:] for p in dirty if len(p) > 3 and p[2] == ' '][:5], 'dirty_count': len(dirty),
            'fingerprint': digest({'head': head, 'files': contents, 'dirty': dirty})}


def _without_init_block(text: str, state_rel: str) -> str | None:
    """`.gitignore` text with `repo-ai init`'s managed block removed, compared line by line (line endings
    normalized), or None when the block ignores anything but repo-ai's own state, a marker is malformed or a block is
    unterminated: a pattern there could hide real files from the dirty check."""
    from ..adapters.base import GITIGNORE_BEGIN, GITIGNORE_END
    own = (*isolate.STATE_PREFIXES, state_rel.rstrip('/') + '/')
    out: list[str] = []
    inside = False
    for line in text.replace('\r\n', '\n').split('\n'):
        entry = line.strip()
        if entry in (GITIGNORE_BEGIN, GITIGNORE_END):
            if (entry == GITIGNORE_BEGIN) == inside:
                return None  # nested or unmatched marker
            inside = entry == GITIGNORE_BEGIN
            if inside and out and not out[-1].strip():
                out.pop()  # the blank line init writes before its block
            continue
        if 'repo-ai managed' in line:
            return None  # a marker with extra text: never guess where a block starts or ends
        if inside:
            if entry and not entry.startswith('#') and not (entry.startswith(own) or entry + '/' in own):
                return None
            continue
        out.append(line)
    if inside:
        return None
    return '\n'.join(out).rstrip('\n')


def _only_managed_blocks(root: Path, path: str, state_rel: str) -> bool:
    """An untracked root `.gitignore` that `repo-ai init` created: nothing but its managed block."""
    from ..adapters.base import GITIGNORE_BEGIN
    if path != '.gitignore':
        return False
    try:
        data = isolate.read_inside(root, path, 1_000_000)
        text = data.decode('utf-8') if data is not None else ''
    except (isolate.ReportTooLarge, UnicodeError):
        return False
    rest = _without_init_block(text, state_rel)
    return GITIGNORE_BEGIN in text and rest is not None and not rest.strip()


def committed_if_only_managed_blocks(root: Path, path: str) -> bytes | None:
    """The committed bytes of the root `.gitignore` when its working copy differs from HEAD only by `repo-ai init`'s
    managed block (workspaces are built from HEAD, so this is what they hold); None otherwise."""
    if path != '.gitignore':
        return None
    try:
        work = isolate.read_inside(root, path, MAX_SOURCE_FILE)
    except isolate.ReportTooLarge:
        return None
    if work is None:
        return None
    try:
        state_rel = Store(root).layout.state_dir.relative_to(root).as_posix()
        head = git(root, 'show', 'HEAD:.gitignore', raw=True).encode('utf-8')
        work_text, head_text = work.decode('utf-8'), head.decode('utf-8')
    except (ValueError, UnicodeError):
        return None
    work_rest, head_rest = _without_init_block(work_text, state_rel), _without_init_block(head_text, state_rel)
    if work == head or work_rest is None or head_rest is None or work_rest != head_rest:
        return None
    return head


def _classify_orchestration_and_broker(task: str, context: dict[str, Any], max_parallel: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Classify task complexity for specialist delegation (P2) and capability broker routing (P7)."""
    from ..orchestrate import RISK_WORDS, TRIVIAL_RE
    packet = context.get('packet', {})
    blast = packet.get('blast') or {}
    importers = int(blast.get('transitive_importers') or 0)
    uncertainty = packet.get('uncertainty') or []
    task_lower = task.lower()
    has_trivial_marker = bool(TRIVIAL_RE.search(task))
    hard_risk = any(w in task_lower for w in ('migration', 'migrate', 'schema', 'password', 'secret', 'encrypt', 'drop', 'delete'))
    trivial = has_trivial_marker and not hard_risk and importers < 4
    risky = (not trivial) and (
        bool( hard_risk )
        or any(w in task_lower for w in RISK_WORDS)
        or any(w in task_lower for w in ('charge', 'retry', 'duplicate', 'billing'))
    )
    broad = (importers >= 8 or bool(uncertainty)) and not trivial

    specialists_spawned: list[str] = []
    specialists_refused: list[str] = []
    if trivial:
        complexity = 'trivial'
        specialists_refused.append('trivial change: refused unnecessary specialist fan-out; single writer only')
    elif risky:
        complexity = 'risky'
        if max_parallel > 1 and broad:
            specialists_spawned.extend(['impact', 'acceptance', 'skeptic'])
        else:
            specialists_spawned.append('skeptic')
    elif broad and max_parallel > 1:
        complexity = 'broad'
        specialists_spawned.extend(['impact', 'acceptance'])
    else:
        complexity = 'moderate'
        if max_parallel <= 1:
            specialists_refused.append('max_parallel=1: read-only specialist fan-out not requested')

    orchestration_info = {
        'complexity': complexity,
        'risky': risky,
        'trivial': trivial,
        'broad': broad,
        'merge_owner': 'controller',
        'specialists_spawned': specialists_spawned,
        'specialists_refused': specialists_refused,
    }
    if trivial:
        broker_info = {
            'decision': 'NO_TOOL',
            'reason': 'task is trivial/localized; external tool or skill adapters are unnecessary',
            'recommended_capabilities': [],
        }
    elif risky:
        broker_info = {
            'decision': 'SECURITY_AND_VERIFICATION_GATED',
            'reason': 'task touches high-risk domain (payments/auth/schema/security); require skeptic & secret scan gates',
            'recommended_capabilities': ['builtin.secret-scanner', 'builtin.skeptic-reviewer', 'builtin.sandbox-test-runner'],
        }
    else:
        broker_info = {
            'decision': 'STANDARD_VERIFICATION',
            'reason': 'standard code repair; route to isolated sandbox test verification',
            'recommended_capabilities': ['builtin.sandbox-test-runner'],
        }
    return orchestration_info, broker_info


def plan(root: Path, task: str, *, agent: str = 'auto', write_paths: list[str] | None = None,
         execute_local: bool = False, max_cost_usd: float = 0, max_parallel: int = 1,
         max_seconds: float = 120, command: str = 'python -m pytest',
         allow_live: bool = False, roles: list[str] | None = None,
         expect_fix: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    if agent not in {'auto', 'none', 'replay', *LIVE_PROVIDERS}:
        raise ValueError('unknown agent')
    if command not in {'python -m pytest', 'node --test'}:
        raise ValueError('mission acceptance currently requires a full pytest or node --test command')
    snapshot = identity(root)
    zone, policy = privacy_binding(root)
    clean_task = redact_text(task)
    context = build_context(root, clean_task)
    orchestration_info, broker_info = _classify_orchestration_and_broker(clean_task, context, max_parallel)
    requested_roles = list(dict.fromkeys(roles or []))
    granted_roles: list[str] = []
    for role in requested_roles:
        if orchestration_info['trivial']:
            orchestration_info['specialists_refused'].append(f'{role}: refused for a trivial change')
        elif agent in {'none', 'replay'}:
            orchestration_info['specialists_refused'].append(f'{role}: needs a provider process (not {agent})')
        else:
            granted_roles.append(role)
    orchestration_info['roles'] = granted_roles

    resolved_agent = agent
    provider_route: dict[str, Any] | None = None
    if agent == 'auto' and execute_local and allow_live:
        from ..providers.registry import route
        provider_route = route(root, max_cost_usd=max_cost_usd, run_authorized=True)
        resolved_agent = provider_route['selected'] or 'none'

    approvals: list[str] = []
    if execute_local:
        approvals.append('local sandbox tests and replay edits')
        if allow_live and resolved_agent in LIVE_PROVIDERS:
            approvals.append(f'live {resolved_agent} provider execution in isolated worktree')

    contract = IntentContract(
        clean_task,
        Store(root).repository,
        snapshot['head'],
        [command],
        write_paths or [],
        execute=execute_local,
        network=bool(allow_live and resolved_agent in LIVE_PROVIDERS),
        provider=resolved_agent,
        max_cost_usd=max_cost_usd,
        max_parallel=max_parallel,
        max_seconds=max_seconds,
        approvals=approvals,
        zone=zone,
        policy_sha256=policy,
        roles=granted_roles,
        expect_fix=sorted(set(expect_fix or [])),
    )
    contract.validate()

    if snapshot['dirty']:
        shown = list(snapshot.get('dirty_paths') or [])
        if snapshot.get('dirty_count', 0) > len(shown):
            shown.append(f"and {snapshot['dirty_count'] - len(shown)} more")
        decision, why = 'BLOCKED', ('Checkout has changes' + (f" ({', '.join(shown)})" if shown else '')
                                    + '; planning is available, execution requires a clean pinned tree: commit or stash them')
    elif resolved_agent == 'none':
        decision, why = 'NO_AGENT', 'Local source-linked context only; no model is needed or invoked'
        if provider_route is not None:
            why = 'Automatic routing selected no provider (' + provider_route['outcome'] + '): ' + provider_route['why']
    elif resolved_agent == 'replay':
        decision, why = 'SINGLE_AGENT', 'One explicitly simulated proposal is sufficient; real tests judge it'
    elif allow_live and execute_local and resolved_agent in LIVE_PROVIDERS:
        decision = 'LIVE_ORCHESTRATED_DAG' if max_parallel > 1 else 'LIVE_SINGLE_AGENT'
        why = f'Authorized live provider ({resolved_agent}) selected under isolated worktree and explicit budget ceiling'
    else:
        decision, why = 'ASK_APPROVAL', 'External execution requires verified provider policy, explicit disclosure and budget authorization; planning only'

    reads = [Node('context', 'read', reason='reuse the fresh source-linked packet')]
    baseline_dependencies = ['context']
    investigate = max_parallel > 1 and not orchestration_info['trivial'] and bool(
        context['packet']['uncertainty'] or context['packet']['blast'].get('transitive_importers', 0) >= 8
    )
    if investigate:
        reads += [Node('impact', 'read', ['context'], reason='independent static import/blind-spot check'),
                  Node('acceptance', 'read', ['context'], reason='freeze discovered test identities and bytes')]
        baseline_dependencies = ['impact', 'acceptance']
        why += '; uncertainty justifies two bounded deterministic read-only investigations, not extra model calls'
    elif orchestration_info['trivial']:
        why += '; trivial change classification refused unnecessary specialist fan-out'

    edit_dependencies = ['baseline']
    if 'investigator' in granted_roles:
        reads.append(Node('investigator', 'read', ['context'], owner='investigator',
                          reason='separate read-only provider process diagnoses the cause before any edit'))
        edit_dependencies.append('investigator')
    tail_nodes = [
        Node('baseline', 'verify', baseline_dependencies, reason='observe the original failure'),
        Node('edit', 'write', edit_dependencies, reason='one isolated candidate; source checkout untouched'),
        Node('candidate', 'verify', ['edit'], reason='same frozen tests'),
        Node('review', 'review', ['candidate'], reason='fresh whole-change regression verification'),
    ]
    if 'adversary' in granted_roles:
        tail_nodes.append(Node('adversary', 'review', ['candidate'], owner='adversary',
                               reason='separate read-only provider process challenges the verified diff; advisory only'))
    dag = ExecutionDAG([*reads, *tail_nodes], max_parallel)
    graph = RealityGraph(snapshot['fingerprint'], [
        {'source': digest(contract.to_json()), 'target': loc['path'], 'relation': 'candidate-location',
         'provenance': 'existing identity-first packet', 'scope': snapshot['head'],
         'freshness': 'fresh', 'confidence': 'static'} for loc in context['packet']['locations']])
    return {
        'schema': 'repo-ai.mission-plan/1',
        'kernel': kernel_identity(),
        'contract': contract.to_json(),
        'context': context,
        'orchestration': orchestration_info,
        'capability_broker': broker_info,
        'provider_route': provider_route,
        'source': snapshot,
        'decision': decision,
        'why': why,
        'dag': dag.to_json(),
        'graph': graph.to_json(),
        'limitations': [
            'No live agent invoked during planning',
            'No observed test result during planning',
            'ProofLab is experimental and is not a mission completion gate',
        ],
    }


def proposal(path: Path, root: Path, contract: IntentContract) -> dict[str, Any]:
    from .verification import test_support
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PATCH:
        raise ValueError('replay proposal must be a bounded regular JSON file')
    raw = json.loads(path.read_text('utf-8'))
    if not isinstance(raw, dict) or set(raw) != {'schema', 'label', 'edits'} or raw['schema'] != 'repo-ai.replay/1':
        raise ValueError('unsupported replay proposal')
    edits = raw['edits']
    if not isinstance(raw['label'], str) or not isinstance(edits, list) or not 1 <= len(edits) <= 16:
        raise ValueError('invalid replay proposal')
    runner = engine.establish_runner(root, Store(root).layout, contract.acceptance[0])
    tracked_files = engine.repo_files(root)
    tracked = set(tracked_files)
    tests = set(runner.test_files(tracked_files))
    seen: set[str] = set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'path', 'before_sha256', 'after'}:
            raise ValueError('invalid replay edit')
        rel = relative_path(edit['path'])
        if rel not in contract.write_paths or rel in seen:
            raise ValueError('edit lacks explicit path approval or duplicates another edit')
        seen.add(rel)
        if rel not in tracked or rel in tests or test_support(rel) or Path(rel).suffix not in {'.py', '.js', '.mjs', '.cjs', '.ts'}:
            raise ValueError('frozen acceptance inputs/config cannot change; only approved source files')
        before = isolate.read_inside(root, rel, MAX_PATCH)
        if before is None or hashlib.sha256(before).hexdigest() != edit['before_sha256']:
            raise ValueError('stale or nonregular source edit')
        if not isinstance(edit['after'], str) or len(edit['after'].encode()) > MAX_PATCH or '\0' in edit['after']:
            raise ValueError('invalid source replacement')
        if any(tok in edit['after'] for tok in ('mission-observation', 'rai_result', 'rai_reporter')):
            raise ValueError('source edit references internal verification reporter; refused')
        for text in (before.decode('utf-8'), edit['after']):
            if source_contains_secret(rel, text):
                raise ValueError('source edit contains secret-shaped material; withheld')
        if before.decode('utf-8') == edit['after']:
            raise ValueError('no-op proposal cannot establish a repair')
    return raw


def execute(root: Path, planned: dict[str, Any], replay_path: Path | None = None, *,
            resume: bool = False, provider_executable: Path | None = None,
            allow_live: bool = False, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..providers.adapters import contract_for, run_provider, validate_workspace_edits
    from ..providers.discovery import _identity, _inside, executable_name
    from .verification import compare, observe, pre_existing_failures
    root = root.resolve()
    contract = decode(planned['contract'])
    if not isinstance(contract, IntentContract) or not contract.execute or not contract.approvals:
        raise ValueError('explicit local execution approval is required')
    is_live_provider = bool(allow_live and contract.provider in LIVE_PROVIDERS)
    is_provider_contract = (
        contract.provider in LIVE_PROVIDERS
        and (provider_executable is not None or is_live_provider)
    )
    if contract.provider != 'replay' and not is_provider_contract:
        raise ValueError('only zero-cost offline replay execution is implemented; external providers are planning-only')
    if not is_live_provider and (contract.network or contract.max_cost_usd != 0):
        raise ValueError('only zero-cost offline replay execution is implemented; external providers are planning-only')
    if is_live_provider and contract.max_cost_usd > 0 and not contract_for(contract.provider).enforces_hard_usd_budget:
        raise ValueError(f'{contract.provider} does not enforce a hard USD CLI budget flag; execution blocked')
    if not check_privacy(root, planned['contract']):
        raise ValueError('zone policy changed or unbound legacy contract; create a fresh plan')
    dag = decode(planned['dag'])
    if not isinstance(dag, ExecutionDAG) or dag.max_parallel > contract.max_parallel:
        raise ValueError('child DAG exceeds approved parallel budget')
    expected = {'context': ('read', []), 'baseline': ('verify', ['context']),
                'edit': ('write', ['baseline']), 'candidate': ('verify', ['edit']),
                'review': ('review', ['candidate'])}
    if any(n.id == 'impact' for n in dag.nodes):
        expected.update(impact=('read', ['context']), acceptance=('read', ['context']),
                        baseline=('verify', ['impact', 'acceptance']))
    role_nodes = set(contract.roles)
    if 'investigator' in role_nodes:
        expected.update(investigator=('read', ['context']), edit=('write', ['baseline', 'investigator']))
    if 'adversary' in role_nodes:
        expected.update(adversary=('review', ['candidate']))
    owners = {r: r for r in role_nodes}
    if (contract.provider in {'none', 'replay'} and role_nodes) or \
            {n.id: (n.mode, n.depends_on) for n in dag.nodes} != expected or \
            any(n.owner != owners.get(n.id, 'controller') for n in dag.nodes):
        raise ValueError('DAG does not preserve the frozen execution ordering and ownership')
    store = Store(root)
    current = identity(root, require_clean=True)
    if planned.get('kernel') != kernel_identity():
        raise ValueError('stale mission kernel; create a fresh plan')
    if contract.repository != store.repository or contract.base != current['head'] \
            or current['fingerprint'] != planned['source']['fingerprint']:
        raise ValueError('stale source or repository boundary')
    raw: dict[str, Any] | None = None
    resolved_exe: Path | None = None
    if seed is not None and not is_provider_contract:
        raise ValueError('a carried partial diff can only seed a provider candidate')
    if is_provider_contract:
        exe_candidate = (str(provider_executable) if provider_executable is not None
                         else shutil.which(executable_name(contract.provider)))
        if not exe_candidate:
            raise ValueError(f'{contract.provider} executable is not installed on PATH')
        raw_exe = Path(os.path.abspath(exe_candidate))
        resolved_exe = raw_exe.resolve(strict=True)
        parent_exe = raw_exe.parent.resolve(strict=True) / raw_exe.name
        if _inside(raw_exe, root) or _inside(resolved_exe, root) or _inside(parent_exe, root):
            raise ValueError('repository-owned provider executable or symlink alias refused')
        exe_sha = _identity(resolved_exe)
        proposal_payload: dict[str, Any] = {
            'provider': contract.provider,
            'executable_sha256': exe_sha,
            'write_paths': list(contract.write_paths),
            'live': is_live_provider,
        }
        if seed is not None:
            proposal_payload['seed'] = seed['diff_sha256']
        provider_meta: dict[str, Any] = {
            'name': contract.provider,
            'simulated': not is_live_provider,
            'verification_label': 'LIVE_PENDING' if is_live_provider else 'SIMULATED',
            'stage': 'READY' if is_live_provider else 'SIMULATED',
            'executable': resolved_exe.name,
            'identity_sha256': exe_sha,
            'cost_usd': 0,
            'cost_status': 'UNKNOWN' if is_live_provider else 'OBSERVED',
        }
    else:
        if replay_path is None:
            raise ValueError('replay execution requires a replay proposal file')
        raw = proposal(replay_path, root, contract)
        proposal_payload = raw
        provider_meta = {
            'name': 'replay',
            'simulated': True,
            'verification_label': 'SIMULATED',
            'stage': 'SIMULATED',
            'label': redact_text(raw['label'])[:100],
            'cost_usd': 0,
            'cost_status': 'OBSERVED',
        }
    mission_id = digest({'contract': contract.to_json(), 'proposal': proposal_payload, 'source': current['fingerprint']})[:24]
    state: dict[str, Any] = {'id': mission_id, 'repository': store.repository, 'state': 'CREATED', 'events': [],
                             'contract': contract.to_json(), 'plan': planned, 'source': current, 'kernel': planned['kernel'],
                             'provider': provider_meta,
                             'proposal_sha256': digest(proposal_payload), 'seconds_used': 0, 'applied_to_source': False}
    make_dir(store.root, store.folder, mode=0o700)
    with file_lock(store.folder / (mission_id + '.lock'), timeout=0) as locked:
        if not locked:
            raise ValueError('mission is already running; status/cancel are available')
        carried = 0.0
        if resume and not store.path(mission_id).exists():
            raise ValueError('cannot resume: no prior mission checkpoint found')
        if store.path(mission_id).exists():
            old = store.load(mission_id)
            if not resume or old['state'] == 'COMPLETE':
                if old['state'] not in TERMINAL:
                    transition(old, 'INCONCLUSIVE', 'controller interrupted; inspect before explicit resume')
                    store.save(old)
                return status(root, mission_id)
            prior_nodes = old.get('nodes', {})
            if not old.get('cleanup_confirmed') and any(n.get('status') != 'SUCCEEDED' for n in prior_nodes.values()):
                raise ValueError('interrupted active execution has unconfirmed cleanup; resume is blocked, not retried')
            attempts = old.get('attempts', [])
            if len(attempts) >= 2:
                raise ValueError('three-attempt mission limit reached')
            carried = float(old.get('seconds_used', 0))
            if not old.get('cleanup_confirmed'):
                wall = time.time() - old.get('attempt_started_at', 0)
                carried = max(carried, wall + old.get('carried_seconds', 0))
                workspace = old.get('workspace')
                if workspace:
                    path = isolate.workspaces_root() / Path(str(workspace)).name
                    if path.parent != isolate.workspaces_root() or not path.name.startswith('mission-' + mission_id + '-') or path.is_symlink():
                        raise ValueError('untrusted recovery workspace')
                    marker = isolate.read_inside(path, isolate.WS_MARKER, 4096) if path.exists() else None
                    if marker:
                        pid = json.loads(marker).get('pid')
                        if type(pid) is not int or isolate._alive(pid):
                            raise ValueError('previous controller may still be alive; refusing cleanup')
                        isolate._remove(path)
            if carried >= contract.max_seconds:
                raise ValueError('carried mission time budget is exhausted')
            state['attempts'] = [*attempts, {'state': old['state'], 'passport': old.get('passport'),
                                          'nodes': prior_nodes, 'seconds_used': carried}]
            state['events'] = old['events']
            state['events'].append({'index': len(state['events']), 'from': old['state'], 'to': 'CREATED',
                                    'reason': 'explicit resume: reconstruct isolated candidate; preserve prior evidence and debit time',
                                    'previous': digest(state['events'][-1]) if state['events'] else ''})
            (store.folder / (mission_id + '.cancel')).unlink(missing_ok=True)
        state['carried_seconds'] = carried
        state['attempt_started_at'] = time.time()
        if resolved_exe is not None:
            # The absolute binary location is local-only: kept outside the mission record so it is never
            # returned, exported in a handoff or shown to a model. Freshness compares it with identity_sha256.
            locator = _exec_locator(store, mission_id)
            locator.write_text(str(resolved_exe), encoding='utf-8')
            locator.chmod(0o600)
        store.save(state)
        started = time.monotonic() - carried
        candidate_path: Path | None = None

        def checkpoint(target: str) -> None:
            state['seconds_used'] = round(time.monotonic() - started, 3)
            if (store.folder / (mission_id + '.cancel')).exists():
                raise InterruptedError('cancellation requested')
            if state['seconds_used'] >= contract.max_seconds:
                raise TimeoutError('mission time budget exhausted')
            transition(state, target)
            store.save(state)

        def remaining() -> float:
            left = contract.max_seconds - (time.monotonic() - started)
            if left <= 0:
                raise TimeoutError('mission time budget exhausted')
            return min(60.0, left)

        def provider_left() -> float:
            # A real model repair needs minutes; bound it by the mission budget, not the 60 s test-phase cap.
            left = contract.max_seconds - (time.monotonic() - started)
            if left <= 0:
                raise TimeoutError('mission time budget exhausted')
            return left

        spend: dict[str, Any] = {'usd': 0.0, 'unknown': False, 'lock': threading.Lock()}

        def account(res: dict[str, Any]) -> None:
            with spend['lock']:
                spend['usd'] += float(res.get('cost_usd') or 0.0)
                spend['unknown'] = spend['unknown'] or res.get('cost_status') != 'OBSERVED'

        def ceiling_left() -> float:
            return max(0.0, contract.max_cost_usd - spend['usd']) if is_live_provider else 0.0

        def run_role(role: str, prompt: str, setup: Callable[[Path], None] | None = None) -> dict[str, Any]:
            """One read-only provider process in its own disposable checkout. Advisory only."""
            assert resolved_exe is not None
            artifact: dict[str, Any] = {'role': role, 'provider': contract.provider, 'advisory': True,
                                        'same_provider_as_implementer': True, 'simulated': not is_live_provider}
            if is_live_provider and contract.max_cost_usd > 0 and ceiling_left() <= 0:
                return {**artifact, 'status': 'SKIPPED', 'reasons': ['cost ceiling exhausted before this role']}
            with isolate.materialize_commit(root, current['head'], label=f'role-{role}-{mission_id}',
                                            dependencies=False) as rws:
                if setup is not None:
                    setup(rws.path)
                before = tree_digest(rws.path)
                res = run_provider(contract.provider, root, rws.path, prompt, write_paths=[],
                                   executable=resolved_exe, timeout=provider_left(),
                                   max_cost_usd=ceiling_left() if (is_live_provider and contract.max_cost_usd > 0) else 0.0,
                                   simulated=not is_live_provider, allow_live=is_live_provider,
                                   constraints='This is a READ-ONLY role. Do not create, edit or delete any file and do not '
                                               'run shell commands. Answer in plain text only.')
                unchanged = tree_digest(rws.path) == before
            account(res)
            artifact.update(cost_usd=res.get('cost_usd', 0.0), cost_status=res.get('cost_status', 'UNKNOWN'),
                            session_id=(res.get('events') or {}).get('session_id'),
                            capture_status=res.get('capture_status'), workspace_unchanged=unchanged)
            if res['reasons'] or not unchanged:
                reasons = list(res['reasons']) + ([] if unchanged else ['role modified its read-only checkout; report discarded'])
                return {**artifact, 'status': 'FAILED',
                        'reasons': [sanitize_provider_text(r, local_path_map(root, rws.path))[:300] for r in reasons]}
            report = (res.get('events') or {}).get('report') or (res.get('events') or {}).get('summary') or ''
            return {**artifact, 'status': 'OK', 'report': sanitize_provider_text(report, local_path_map(root, rws.path)),
                    'reasons': []}

        def investigate_role() -> dict[str, Any]:
            return run_role('investigator',
                            'Diagnose, without changing anything, the most likely root cause for this task and name the '
                            'file/function/line to change and one behavior a fix must preserve. Task: ' + contract.objective)

        def adversary_role() -> dict[str, Any]:
            diff = nodes['edit']['artifact']['diff']

            def apply_candidate(path: Path) -> None:
                patch = path.parent / (path.name + '.patch')
                patch.write_text(diff.rstrip('\n') + '\n', encoding='utf-8')  # git() strips the final newline
                try:
                    git(path, 'init', '-q')
                    git(path, 'apply', '--whitespace=nowarn', str(patch))
                finally:
                    patch.unlink(missing_ok=True)

            out = run_role('adversary',
                           'You are a skeptical reviewer. The working tree already contains a candidate fix for this task. '
                           'Find a concrete input or interleaving where it is still wrong, or say none. Do not praise it. '
                           'End with exactly one line: STANCE: OBJECT or STANCE: ACCEPT. Task: ' + contract.objective,
                           apply_candidate)
            if out.get('status') == 'OK':
                lines = [ln.strip() for ln in out.get('report', '').splitlines() if ln.strip().startswith('STANCE:')]
                out['stance'] = lines[-1].split(':', 1)[1].strip().upper() if lines else 'UNSTATED'
            return out

        try:
            checkpoint('PLANNED')
            checkpoint('READY')
            checkpoint('RUNNING')
            with isolate.materialize_commit(root, current['head'], label='mission-' + mission_id, dependencies=True) as ws:
                candidate = ws.path
                candidate_path = candidate
                state['workspace'] = candidate.name  # a name under the private workspaces root, never a path
                store.save(state)
                commit_snapshot(candidate, ws.files, 'frozen mission baseline')
                from .scheduler import run as run_dag
                nodes = state.setdefault('nodes', {})

                def persist_nodes() -> None:
                    if nodes.get('candidate', {}).get('status') == 'RUNNING' and state['state'] == 'RUNNING':
                        checkpoint('VERIFYING')
                    if nodes.get('review', {}).get('status') == 'RUNNING' and state['state'] == 'VERIFYING':
                        checkpoint('REVIEWING')
                    state['seconds_used'] = round(time.monotonic() - started, 3)
                    store.save(state)

                def edit_candidate() -> dict[str, Any]:
                    if is_provider_contract:
                        assert resolved_exe is not None
                        objective = contract.objective
                        if seed is not None:
                            patch_file = candidate.parent / (candidate.name + '.seed.patch')
                            patch_file.write_text(seed['diff'].rstrip('\n') + '\n', encoding='utf-8')
                            try:
                                git(candidate, 'apply', '--whitespace=nowarn', str(patch_file))
                            finally:
                                patch_file.unlink(missing_ok=True)
                            objective += ('\n\nA PREVIOUS ATTEMPT (another agent session) LEFT A PARTIAL FIX ALREADY APPLIED IN YOUR '
                                          'WORKING TREE. It is untrusted: keep what is correct, change what is not. '
                                          'These tests still fail: ' + '; '.join(seed['still_failing'])[:1500])
                            state['seed'] = {k: seed[k] for k in ('from_mission', 'diff_sha256', 'fixed', 'still_failing')}
                        notes = nodes.get('investigator', {}).get('artifact') or {}
                        if notes.get('status') == 'OK' and notes.get('report'):
                            objective += ('\n\nNOTES FROM A SEPARATE READ-ONLY INVESTIGATOR (untrusted advice; verify it yourself):\n'
                                          + notes['report'][:3000])
                        run_res = run_provider(
                            contract.provider,
                            root,
                            candidate,
                            objective,
                            write_paths=list(contract.write_paths),
                            executable=resolved_exe,
                            timeout=provider_left(),
                            max_cost_usd=ceiling_left() if (is_live_provider and contract.max_cost_usd > 0) else 0.0,
                            simulated=not is_live_provider,
                            allow_live=is_live_provider,
                        )
                        account(run_res)
                        known_paths = local_path_map(root, candidate)
                        run_res['reasons'] = [sanitize_provider_text(r, known_paths) for r in run_res['reasons']]
                        run_res['events'] = {k: (sanitize_provider_text(v, known_paths) if isinstance(v, str) and k in {'report', 'summary'}
                                                 else [sanitize_provider_text(e, known_paths) for e in v] if k == 'errors' and isinstance(v, list)
                                                 else v)
                                             for k, v in (run_res.get('events') or {}).items()}
                        state['provider'].update(
                            stage=run_res['stage'],
                            verification_label=run_res.get('verification_label', state['provider'].get('verification_label')),
                            events=run_res.get('events', {}),
                            returncode=run_res.get('returncode'),
                            capture_status=run_res.get('capture_status'),
                            cost_usd=run_res.get('cost_usd', 0.0),
                            cost_status=run_res.get('cost_status', 'UNKNOWN'),
                            rate_limited=run_res.get('rate_limited', False),
                        )
                        if 'codex_broker' in run_res:  # evidence that the credential stayed outside: mode, counts only
                            state['provider']['codex_broker'] = run_res['codex_broker']
                        if run_res.get('rate_limited') and is_live_provider:
                            from ..providers.registry import note_rate_limited
                            note_rate_limited(root, contract.provider)
                        if is_live_provider:
                            _cache_observation(root, contract.provider, exe_sha, run_res)
                        if run_res['reasons']:
                            raise ValueError('; '.join(run_res['reasons']))
                        runner = engine.establish_runner(root, store.layout, contract.acceptance[0])
                        tracked_set = set(current['files'])
                        test_set = set(runner.test_files(list(tracked_set)))
                        problems = validate_workspace_edits(
                            root, candidate, list(contract.write_paths), test_set, tracked_set, MAX_PATCH
                        )
                        if problems:
                            state['provider']['stage'] = 'FAILED'
                            raise ValueError('; '.join(problems))
                    else:
                        assert raw is not None
                        for edit in raw['edits']:
                            target = candidate / edit['path']
                            data = isolate.read_inside(candidate, edit['path'], MAX_PATCH)
                            if data is None or hashlib.sha256(data).hexdigest() != edit['before_sha256']:
                                raise ValueError('candidate source is stale or nonregular')
                            target.write_text(edit['after'], encoding='utf-8')
                    diff = git(candidate, 'diff', '--no-ext-diff', '--no-textconv', '--binary', raw=True)
                    return {'diff': diff, 'sha256': hashlib.sha256(diff.encode()).hexdigest()}

                def regression() -> dict[str, Any]:
                    layout = resolve_layout(candidate, load_config(candidate))
                    vp, change = engine.build_plan(candidate, layout, command=contract.acceptance[0], use_runtime=False)
                    executor = get_executor(candidate, 'auto', vp.runner.language, interpreter_root=root)
                    try:
                        return engine.run_plan(candidate, layout, vp, change, executor,
                                               full=True, reuse=False, workers=1,
                                               timeout_s=remaining(), deadline_s=remaining())
                    finally:
                        release([executor])

                def acceptance_inventory() -> dict[str, Any]:
                    runner = engine.establish_runner(candidate, Store(candidate).layout, contract.acceptance[0])
                    files = runner.test_files(engine.repo_files(candidate))
                    return {'actor': 'builtin-static', 'test_files': {f: current['files'][f] for f in files},
                            'claim': 'discovered files only; collection is established by sandbox observation'}

                def impact_investigation() -> dict[str, Any]:
                    import ast
                    imports: dict[str, list[str]] = {}
                    dynamic = []
                    for rel in current['files']:
                        if not rel.endswith('.py'):
                            continue
                        try:
                            data = isolate.read_inside(candidate, rel, MAX_PARSE_FILE)
                        except isolate.ReportTooLarge:  # ast.parse of a 24 MB module took ~13 GB (measured)
                            dynamic.append(rel + ': too large to parse; static attribution incomplete')
                            continue
                        if data is None:
                            raise ValueError('static investigation source disappeared')
                        try:
                            tree = ast.parse(data)
                        except (SyntaxError, ValueError):
                            dynamic.append(rel + ': parser could not resolve imports')
                            continue
                        names: list[str] = []
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                names.extend(n.name for n in node.names)
                            elif isinstance(node, ast.ImportFrom):
                                names.append(node.module or '')
                            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', '__import__'}:
                                dynamic.append(rel + ': dynamic code or import; static attribution incomplete')
                        imports[rel] = sorted(set(names))[:40]
                    return {'actor': 'builtin-static', 'imports': imports, 'blind_spots': dynamic[:50],
                            'claim': 'static relationships are hypotheses, not runtime observations'}

                actions = {'context': lambda: planned['context'],
                           'baseline': lambda: observe(candidate, contract.acceptance[0], timeout_s=remaining(), project_root=root),
                           'edit': edit_candidate,
                           'candidate': lambda: observe(candidate, contract.acceptance[0], timeout_s=remaining(), project_root=root),
                           'review': regression}
                if any(n['id'] == 'impact' for n in planned['dag']['nodes']):
                    actions.update(impact=impact_investigation, acceptance=acceptance_inventory)
                if 'investigator' in contract.roles:
                    actions['investigator'] = investigate_role
                if 'adversary' in contract.roles:
                    actions['adversary'] = adversary_role
                run_dag(decode(planned['dag']), actions, nodes, deadline=started + contract.max_seconds,
                        cancelled=lambda: (store.folder / (mission_id + '.cancel')).exists(), checkpoint=persist_nodes)
                state['baseline'] = nodes['baseline']['artifact']
                state['candidate'] = nodes['candidate']['artifact']
                state['regression'] = nodes['review']['artifact']
                state['diff'] = nodes['edit']['artifact']['diff']
                state['diff_sha256'] = nodes['edit']['artifact']['sha256']
                scoped = list(getattr(contract, 'expect_fix', []) or [])
                observed, reasons = compare(state['baseline'], state['candidate'], expect_fix=scoped)
                accepted = {'selected-and-full-suite-passed'}
                if scoped:  # failures that also fail at the base are allowed only when the task set is declared
                    accepted.add('failing (all failures pre-existing at the base)')
                if state['regression'].get('verdict') not in accepted:
                    reasons.append('fresh whole-change regression verification did not pass')
                if scoped and not reasons:
                    state['scoped'] = pre_existing_failures(state['baseline'], state['candidate'], scoped)
                scoped_unclear = bool(scoped and observed == 'PASS' and state['regression'].get('verdict')
                                      == 'failing (tests that fail at the base now fail differently)')
                if not state['regression'].get('source_tree', {}).get('unchanged'):
                    reasons.append('candidate integrity check failed')
                if identity(root, require_clean=True)['fingerprint'] != current['fingerprint']:
                    reasons.append('original source changed during mission')
                if observed != 'PASS' and not reasons:
                    reasons.append('acceptance comparison did not pass')
                if kernel_identity() != state['kernel']:
                    reasons.append('mission kernel changed during execution')
                if 'acceptance' in nodes:
                    expected = nodes['acceptance']['artifact']['test_files']
                    actual = state['baseline'].get('pin', {}).get('test_inputs', {})
                    if any(actual.get(path) != sha for path, sha in expected.items()):
                        reasons.append('independent acceptance inventory disagrees with observed test bytes')
                observations = [digest(state[k]) for k in ('baseline', 'candidate', 'regression')]
                verdict = 'PASS' if not reasons else ('FAIL' if state['candidate'].get('failed', 0) else 'INCONCLUSIVE')
                if verdict == 'FAIL' and scoped_unclear and len(reasons) == 1:
                    # the declared tests were fixed and nothing regressed by test outcome; only a pre-existing
                    # failure's message changed: that cannot be judged either way here
                    verdict = 'INCONCLUSIVE'
                if scoped:
                    state['standing'] = (state.get('scoped') or {}).get('standing', verdict) if verdict == 'PASS' else verdict
                if verdict == 'PASS':
                    from .exercise import measure as measure_exercise
                    try:
                        state['exercise'] = measure_exercise(candidate, contract.acceptance[0], state['diff'], timeout_s=remaining(),
                                                             project_root=root)
                    except Exception as exc:  # noqa: BLE001 - measurement must never change a verdict
                        state['exercise'] = {'schema': 'repo-ai.change-exercise/1', 'assurance': 'UNMEASURED',
                                             'reason': type(exc).__name__, 'unexercised': [], 'changed_lines': 0}
                state['provider']['stage'] = 'VERIFIED' if verdict == 'PASS' else 'FAILED'
                if verdict == 'PASS':
                    state['provider']['verification_label'] = 'LIVE_CANDIDATE_VERIFIED' if is_live_provider else 'SIMULATED'
                else:
                    state['provider']['verification_label'] = 'LIVE_FAILED' if is_live_provider else 'SIMULATED'
                state['reality'] = RealityGraph(current['fingerprint'], [*planned['graph']['edges'], *[
                    {'source': digest(state[k]), 'target': mission_id, 'relation': k,
                     'provenance': 'sandboxed structured test observation' if k != 'regression' else 'existing verify engine',
                     'scope': digest(contract.to_json()), 'freshness': 'fresh', 'confidence': 'observed'}
                    for k in ('baseline', 'candidate', 'regression')]]).to_json()
                role_records = {k: nodes[k]['artifact'] for k in ('investigator', 'adversary') if k in nodes}
                if role_records:
                    state['roles'] = {k: {kk: vv for kk, vv in v.items() if kk != 'report'} | {'report_sha256': digest(v.get('report', ''))}
                                      for k, v in role_records.items()}
                    state['role_reports'] = {k: v.get('report', '') for k, v in role_records.items()}
                    state['spend'] = {'usd_observed_total': round(spend['usd'], 6), 'any_cost_unknown': bool(spend['unknown'])}
                    if role_records.get('adversary', {}).get('stance') == 'OBJECT':
                        reasons_note = 'adversary objected (advisory; verdict rests on frozen tests only)'
                    else:
                        reasons_note = None
                untested_notes = [
                    *( [reasons_note] if role_records and reasons_note else [] ),
                    'Only the frozen tests were observed; not a proof',
                    *exercise_notes(state.get('exercise')),
                    'Live provider execution verified by local sandbox suite' if is_live_provider else 'No live provider or product-lift evaluation',
                    'Candidate diff is NOT applied to original source until repo-ai apply is run',
                ]
                state['passport'] = EvidenceRecord(current['fingerprint'], digest(contract.to_json()), verdict,
                                                   observations, reasons, untested_notes).to_json()
            state['cleanup'] = 'candidate workspace removed'
            state['cleanup_confirmed'] = candidate_path is not None and not candidate_path.exists()
            if not state['cleanup_confirmed']:
                state['passport']['verdict'] = 'INCONCLUSIVE'
                state['passport']['negative'].append('candidate workspace cleanup was not confirmed')
                state['provider']['stage'] = 'FAILED'
                state['provider']['verification_label'] = 'LIVE_FAILED' if is_live_provider else 'SIMULATED'
                verdict = 'INCONCLUSIVE'
            checkpoint('COMPLETE' if verdict == 'PASS' else 'INCONCLUSIVE')
        except (Exception, KeyboardInterrupt) as exc:
            reason = sanitize_provider_text(str(exc), local_path_map(root, *([candidate_path] if candidate_path else [])))[:1000] \
                or type(exc).__name__
            state['provider']['verification_label'] = 'LIVE_FAILED' if is_live_provider else 'SIMULATED'
            if state['provider'].get('stage') not in {'BLOCKED', 'NOT_INSTALLED'}:
                state['provider']['stage'] = 'BLOCKED' if isinstance(exc, ValueError) and not state['provider'].get('rate_limited') else 'FAILED'
            state['passport'] = EvidenceRecord(current['fingerprint'], digest(contract.to_json()),
                                               'BLOCKED' if isinstance(exc, ValueError) else 'INCONCLUSIVE',
                                               negative=[reason], untested=['mission did not complete']).to_json()
            if state['state'] not in TERMINAL:
                transition(state, 'CANCELLED' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'INCONCLUSIVE', reason)
            state['seconds_used'] = round(time.monotonic() - started, 3)
            state['cleanup_confirmed'] = candidate_path is None or not candidate_path.exists()
            store.save(state)
        return status(root, mission_id)


def _cache_observation(root: Path, provider: str, identity_sha: str, run_res: dict[str, Any]) -> None:
    """Remember what a live run showed about readiness (expires; bound to the binary). Never affects a verdict."""
    try:
        from ..providers.registry import classify_failure, note_observation
        reasons = [str(r) for r in run_res.get('reasons', [])]
        state = classify_failure(reasons) if reasons else ('READY' if run_res.get('capture_status') == 'complete' else None)
        if state:
            note_observation(root, provider, state, identity_sha)
    except Exception:  # noqa: BLE001 - a cache write failure must not change a mission
        pass


def exercise_notes(record: dict[str, Any] | None) -> list[str]:
    """Plain-language limits from a change-exercise measurement (never a verdict change)."""
    if not record:
        return []
    level = record.get('assurance')
    if level == 'PARTIAL':
        shown = ', '.join(record.get('unexercised', [])[:8])
        more = record.get('unexercised_count', 0) - min(len(record.get('unexercised', [])), 8)
        return [f"{record.get('unexercised_count', 0)} of {record.get('changed_lines', 0)} changed executable lines were never run by the "
                f"frozen tests ({shown}{f' +{more} more' if more > 0 else ''}); behaviour there is unconstrained"]
    if level == 'UNMEASURED':
        return ['whether the frozen tests ran the changed lines could not be measured: ' + str(record.get('reason', ''))[:120]]
    return []


def status(root: Path, mission: str, *, _depth: int = 0) -> dict[str, Any]:
    state = Store(root).load(mission)
    freshness_reasons = []
    if identity(root)['fingerprint'] != state['source']['fingerprint']:
        freshness_reasons.append('source changed since the recorded experiment')
    if state.get('kernel') != kernel_identity():
        freshness_reasons.append('mission kernel changed since the recorded experiment')
    if 'contract' in state and not check_privacy(root, state['contract']):
        freshness_reasons.append('zone policy changed or was not recorded')

    prov = state.get('provider') or {}
    if isinstance(prov, dict) and prov.get('executable') and prov.get('identity_sha256'):
        from ..providers.discovery import _identity
        try:
            located = isolate.read_inside(_exec_locator(Store(root), mission).parent, mission + '.exec', 4096)
            if located is None and os.path.isabs(str(prov['executable'])):
                located = str(prov['executable']).encode('utf-8')  # legacy record written before the local-only locator
            if located is None:
                raise OSError('provider locator missing')
            exe_p = Path(located.decode('utf-8')).resolve(strict=True)
            if _identity(exe_p) != prov['identity_sha256']:
                freshness_reasons.append('provider binary changed since the recorded experiment')
        except (OSError, RuntimeError, ValueError):
            freshness_reasons.append('provider binary is unavailable or changed since the recorded experiment')

    base_inputs = ((state.get('baseline') or {}).get('pin') or {}).get('test_inputs')
    if isinstance(base_inputs, dict) and not freshness_reasons:
        for rel_test, pinned_sha in base_inputs.items():
            try:
                # the same bound the pin was taken with: a larger limit here would read every big fixture as changed
                data = isolate.read_inside(root, rel_test, results.MAX_REPORT_BYTES)
            except Exception:
                data = None
            if data is None or hashlib.sha256(data).hexdigest() != pinned_sha:
                freshness_reasons.append(f'pinned test input changed: {rel_test}')
                break

    fresh = not freshness_reasons
    unchecked = False
    if state.get('kind') == 'comparison':
        if _depth or len(state.get('candidate_ids', [])) > 3:
            raise ValueError('invalid comparison reference graph')
        for candidate_id in state.get('candidate_ids', []):
            try:
                linked = status(root, candidate_id, _depth=1)
            except (ValueError, OSError):
                fresh = False
                freshness_reasons.append('comparison child is unavailable or outside the current boundary: ' + candidate_id)
                continue
            rows = [r for r in state.get('comparison', {}).get('candidates', []) if r.get('id') == candidate_id]
            if (linked['freshness'] != 'fresh' or len(rows) != 1
                    or rows[0].get('passport_sha256') != digest(linked.get('passport', {}))
                    or rows[0].get('proposal_sha256') != linked.get('proposal_sha256')):
                fresh = False
                freshness_reasons.append('comparison child evidence changed or is stale: ' + candidate_id)
    for key in ('baseline', 'candidate', 'regression'):
        if key in state:
            env, detail = evidence.environment_check(state[key], root)
            if env != 'unchanged':
                fresh = False
                freshness_reasons.append(key + ' environment: ' + redact_text(detail))
            unchecked = unchecked or bool((state[key].get('environment_static') or {}).get('unchecked'))
    if unchecked:
        freshness_reasons.append('container image freshness was not checked by this read-only command')
    state['freshness_reasons'] = freshness_reasons
    state['freshness'] = 'stale' if not fresh else ('not checked' if unchecked else 'fresh')
    if 'reality' in state:
        for edge in state['reality']['edges']:
            edge['freshness'] = state['freshness']
    state['effective_verdict'] = (state.get('passport') or {}).get('verdict', 'BLOCKED') if fresh and not unchecked else 'INCONCLUSIVE'
    if state.get('kind') == 'comparison' and state['effective_verdict'] != 'PASS' and isinstance(state.get('comparison'), dict):
        state['comparison'] = {**state['comparison'], 'winner': None, 'verdict': 'INCONCLUSIVE'}
    if state['effective_verdict'] != 'PASS' and state.get('provider', {}).get('verification_label') in {'LIVE_VERIFIED', 'LIVE_CANDIDATE_VERIFIED'}:
        state['provider']['verification_label'] = 'LIVE_STALE' if state['freshness'] != 'fresh' else 'LIVE_FAILED'
    state['recovery'] = classify_recovery(state)
    state['claims'] = _claims_for(root, state)
    return state


def _base_source(root: Path, head: str | None) -> Callable[[str], str | None] | None:
    """Read a file as it was at the mission's base commit (read-only `git show`), bounded."""
    if not head or not re.fullmatch(r'[0-9a-f]{40}', str(head)):
        return None

    def read(rel: str) -> str | None:
        try:
            relative_path(rel)
            text = git(root, 'show', f'{head}:{rel}', raw=True)
        except (ValueError, OSError):
            return None
        return text if len(text) <= MAX_PARSE_FILE else None
    return read


def _claims_for(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Additive claim disclosure; reads only the pinned frozen test files and never changes a verdict."""
    from . import claims
    texts: dict[str, str] = {}
    pinned = ((state.get('baseline') or {}).get('pin') or {}).get('test_inputs')
    for rel in sorted(pinned if isinstance(pinned, dict) else {})[:64]:
        try:
            data = isolate.read_inside(root, rel, MAX_SOURCE_FILE)
        except Exception:  # noqa: BLE001 - unreadable test text only lowers the claim
            data = None
        if data is not None:
            texts[rel] = data.decode('utf-8', 'replace')
    value = claims.assess((state.get('contract') or {}).get('objective', ''), texts,
                          verdict=state['effective_verdict'], freshness=state['freshness'],
                          exercise=state.get('exercise'), diff=state.get('diff') or '',
                          base_source=_base_source(root, (state.get('source') or {}).get('head')))
    scoped = state.get('scoped') or {}
    remaining = scoped.get('pre_existing_failures') or []
    if remaining:
        if value['headline'] in {'OBSERVED_TESTS_PASS', 'ASSURANCE_PARTIAL'}:
            value['headline'] = 'ASSURANCE_PARTIAL'
        from .coverage import display_test_id
        count = scoped.get('pre_existing_count', len(remaining))
        errored = scoped.get('pre_existing_errors') or 0
        value['notes'].insert(1, f"{count} test(s) already failed at the base and still fail"
                                 + (f" ({errored} error at setup, so their bodies never ran)" if errored else "")
                                 + " (scoped by --expect-fix; not part of this result): "
                                 + ', '.join(display_test_id(t) for t in remaining[:5]))
    return value


RECOVERY_CLASSES = (
    'none',
    'retryable_transient',
    'partial_progress',
    'contract_failure',
    'permission_required',
    'budget_limit',
    'environment',
    'provider_unavailable',
    'unrecoverable_ambiguous_side_effect',
)


def partial_progress(state: dict[str, Any]) -> dict[str, Any] | None:
    """Validated partial work, recomputed from stored observations (never from a capsule's claims).

    Requires a stored diff, two eligible comparable observations, at least one baseline-failing test now
    passing, and no test that passed at baseline failing now."""
    from .verification import comparability
    base, cand, diff = state.get('baseline'), state.get('candidate'), state.get('diff')
    if not (isinstance(base, dict) and isinstance(cand, dict) and isinstance(diff, str) and diff):
        return None
    if hashlib.sha256(diff.encode()).hexdigest() != state.get('diff_sha256') or comparability(base, cand):
        return None
    failing = {'fail', 'error'}  # a setup error is failing for progress: it never shows the test passing
    before = {k for k, v in base['outcomes'].items() if v in failing}
    after = {k for k, v in cand['outcomes'].items() if v in failing}
    # fixed means the base showed the test failing by running it: a setup error there never ran the body
    fixed = sorted(k for k in before if base['outcomes'][k] == 'fail' and cand['outcomes'].get(k) == 'pass')
    regressed = sorted(after - before)
    if not fixed or regressed or not after:
        return None
    return {'fixed': fixed, 'still_failing': sorted(after), 'diff_sha256': state['diff_sha256']}


def classify_recovery(state: dict[str, Any]) -> dict[str, Any]:
    """Classify mission state into one of the 7 bounded recovery categories (or 'none')."""
    verdict = state.get('effective_verdict') or (state.get('passport') or {}).get('verdict', 'BLOCKED')
    if state.get('state') == 'COMPLETE' and verdict == 'PASS':
        return {'category': 'none', 'recoverable': False, 'action': 'none; mission passed verification', 'reasons': []}

    negatives = [str(x) for x in (state.get('passport') or {}).get('negative', [])]
    joined = ' | '.join(negatives).lower()
    nodes = state.get('nodes', {})
    cleanup_ok = bool(state.get('cleanup_confirmed', True))
    prov = state.get('provider') or {}
    pstage = str(prov.get('stage', ''))

    if not cleanup_ok and any(n.get('status') != 'SUCCEEDED' for n in nodes.values()):
        return {
            'category': 'unrecoverable_ambiguous_side_effect',
            'recoverable': False,
            'action': 'inspect workspace manually and create a fresh mission plan; automatic resume is refused',
            'reasons': negatives or ['interrupted active execution has unconfirmed cleanup'],
        }
    if 'integrity' in joined or 'cleanup was not confirmed' in joined or 'untrusted recovery workspace' in joined:
        return {
            'category': 'unrecoverable_ambiguous_side_effect',
            'recoverable': False,
            'action': 'abort and inspect checkout integrity before creating a new mission',
            'reasons': negatives,
        }
    if prov.get('rate_limited') or any(k in joined for k in ('rate/usage limit', 'usage limit', 'spend limit', 'rate_limit', 'not installed', 'unavailable', 'ineligibletiererror')):
        if pstage == 'NOT_INSTALLED' or any(k in joined for k in ('not installed', 'unavailable', 'rate/usage limit', 'usage limit', 'spend limit', 'rate_limit')):
            return {
                'category': 'provider_unavailable',
                'recoverable': True,
                'action': 'switch provider via handoff --to <provider> and continue with do --from-handoff <capsule.json>',
                'reasons': negatives,
            }
    if any(k in joined for k in ('time budget', 'cost', 'three-attempt', 'parallel budget', 'budget exhausted')):
        return {
            'category': 'budget_limit',
            'recoverable': False,
            'action': 'replan with an explicit time/attempt budget or narrower scope',
            'reasons': negatives,
        }
    if any(k in joined for k in ('approval', 'zone', 'unapproved path', 'frozen test', 'frozen acceptance', 'secret-shaped', 'untrusted_executable', 'repository-owned', 'symlink', 'internal verification reporter')):
        return {
            'category': 'permission_required',
            'recoverable': False,
            'action': 'update explicit --allow-write paths, zone enrollment, or execution approvals in a new plan',
            'reasons': negatives,
        }
    provider_errors = ' | '.join(n for n in negatives if 'provider error event' in n).lower()
    if any(k in provider_errors for k in ('authentication_failed', 'not logged in', 'please run /login', 'invalid api key',
                                          'failed to authenticate', 'not authenticated for isolated execution')) or \
            any('not authenticated for isolated execution' in n for n in negatives):
        # the same isolated login fails the same way: a resume would only repeat it
        return {
            'category': 'provider_unavailable',
            'recoverable': True,
            'action': ('the provider is not authenticated inside repo-ai\'s isolation; retrying will fail the same way. '
                       'See `repo-ai agents setup <provider>`, or switch provider via handoff --to <provider> and '
                       'continue with do --from-handoff <capsule.json>'),
            'reasons': negatives,
        }
    if pstage == 'NOT_INSTALLED':
        return {
            'category': 'provider_unavailable',
            'recoverable': True,
            'action': 'switch provider via handoff --to or install the target CLI before retrying',
            'reasons': negatives,
        }
    if any(k in joined for k in ('environment', 'sandbox', 'container')):
        return {
            'category': 'environment',
            'recoverable': True,
            'action': 'stabilize local test toolchain/sandbox and run explicit mission resume',
            'reasons': negatives,
        }
    progress = partial_progress(state)
    if progress is not None:
        return {
            'category': 'partial_progress',
            'recoverable': True,
            'action': (f"continue with do --from-handoff <capsule.json> --agent <provider> --run: the carried diff fixed "
                       f"{len(progress['fixed'])} baseline-failing test(s) without new failures; "
                       f"{len(progress['still_failing'])} still fail"),
            'reasons': negatives,
        }
    if (state.get('candidate') or {}).get('failed', 0) > 0 or any(
        k in joined for k in ('jsonl', 'schema', 'no-op', 'did not pass', 'regression verification')
    ):
        return {
            'category': 'contract_failure',
            'recoverable': False,
            'action': 'inspect why-test-failed diagnosis and supply a revised candidate proposal',
            'reasons': negatives,
        }
    can_resume = cleanup_ok and len(state.get('attempts', [])) < 2 and state.get('state') in {'INCONCLUSIVE', 'CANCELLED'}
    return {
        'category': 'retryable_transient',
        'recoverable': can_resume,
        'action': 'explicitly resume mission with --run if source and kernel remain unchanged' if can_resume else 'create a fresh mission plan',
        'reasons': negatives,
    }


def _handoff_snapshot(state: dict[str, Any]) -> str:
    # Export receipts are metadata, not part of the experiment they describe.
    return digest({k: v for k, v in state.items() if k != 'handoff_receipts'})


def handoff(root: Path, mission: str, *, target_provider: str | None = None) -> dict[str, Any]:
    """Export a local-store-bound receipt with unkeyed integrity, never a signature."""
    root = root.resolve()
    store = Store(root)
    with file_lock(store.path(mission).with_suffix('.lock'), timeout=0) as locked:
        if not locked:
            raise ValueError('mission is running; handoff export refused')
        capsule = _handoff_body(root, mission, target_provider=target_provider)
        stored = store.load(mission)
        capsule['mission_snapshot_sha256'] = _handoff_snapshot(stored)
        capsule['integrity_sha256'] = digest({k: v for k, v in capsule.items() if k != 'integrity_sha256'})
        receipts = stored.setdefault('handoff_receipts', [])
        if capsule['integrity_sha256'] not in receipts:
            if len(receipts) >= 16:
                raise ValueError('handoff receipt retention limit reached; create a new mission')
            receipts.append(capsule['integrity_sha256'])
            store.save(stored)
        return capsule


def _handoff_body(root: Path, mission: str, *, target_provider: str | None = None) -> dict[str, Any]:
    if target_provider is not None and target_provider not in {'', 'none', 'replay', *LIVE_PROVIDERS}:
        raise ValueError('unsupported handoff target provider')
    state = status(root, mission)
    if not check_privacy(root, state['contract']):
        raise ValueError('zone policy changed or unknown; capsule export requires a fresh contract')
    rec = state.get('recovery') or classify_recovery(state)
    facts = [
        {'claim': 'candidate outcome: ' + state['effective_verdict'],
         'evidence': digest(state.get('passport', {})), 'standing': state['freshness']},
        {'claim': 'Original checkout was explicitly patched' if state.get('applied_to_source') else 'Original checkout was not patched',
         'evidence': state['source']['fingerprint'],
         'standing': state['freshness']},
    ]
    if 'baseline' in state and isinstance(state['baseline'], dict):
        facts.append({
            'claim': f"baseline observed {state['baseline'].get('failed', 0)} failing of {state['baseline'].get('ran', 0)} tests",
            'evidence': digest(state['baseline']),
            'standing': state['freshness'],
        })
    constraints = [
        'local-only; no opaque native provider session resume',
        'candidate diff is not applied to source without explicit apply',
        'preserve frozen acceptance tests and explicit write paths',
    ]
    if target_provider:
        constraints.append(f'target provider adaptation: {target_provider} (requires local verification before completion)')
    next_cmd = ['repo-ai', 'mission', 'status', mission, '--json']
    if target_provider and state['effective_verdict'] != 'PASS':
        next_cmd = ['repo-ai', 'do', '--from-handoff', '<capsule.json>', '--agent', target_provider, '--run']
    return HandoffCapsule(
        mission,
        state['repository'],
        digest(state['contract']),
        state['state'],
        facts,
        next_cmd,
        zone=state['contract']['zone'],
        objective=redact_text(state['contract']['objective']),
        constraints=constraints,
        dag_status={k: v['status'] for k, v in state.get('nodes', {}).items()},
        modified_files=list(state['contract']['write_paths']),
        outstanding=list((state.get('passport') or {}).get('negative', [])),
        diff_sha256=state.get('diff_sha256', ''),
        target_provider=target_provider or '',
        recovery_category=rec['category'],
        source_fingerprint=state['source']['fingerprint'],
    ).to_json()


def verify_handoff(root: Path, capsule_data: dict[str, Any]) -> dict[str, Any]:
    """Check unkeyed integrity against a trusted local export receipt and fresh state.

    This is not authentication against a malicious owner of both files. A capsule
    cannot import authority into a new store or a different machine/repository.
    """
    root = root.resolve()
    reasons: list[str] = []
    response: dict[str, Any] = {
        'schema': 'repo-ai.handoff-verification/1', 'mission': '', 'valid': False,
        'freshness': 'stale', 'target_provider': '', 'recovery_category': '', 'reasons': reasons,
    }
    try:
        capsule = decode(capsule_data)
        if not isinstance(capsule, HandoffCapsule):
            raise ValueError('expected a repo-ai.handoff/2 capsule; re-export legacy capsules')
        response.update(mission=capsule.mission, target_provider=capsule.target_provider,
                        recovery_category=capsule.recovery_category)
        checksum = digest({k: v for k, v in capsule_data.items() if k != 'integrity_sha256'})
        if not capsule.integrity_sha256 or capsule.integrity_sha256 != checksum:
            reasons.append('capsule integrity checksum mismatch')
        store = Store(root)
        if capsule.repository != store.repository:
            reasons.append('capsule repository does not match current repository')
        zone, _ = privacy_binding(root)
        if capsule.zone != zone:
            reasons.append('capsule privacy zone does not match current repository zone')
        stored = store.load(capsule.mission)
        if checksum not in stored.get('handoff_receipts', []):
            reasons.append('capsule has no matching trusted local export receipt')
        if _handoff_snapshot(stored) != capsule.mission_snapshot_sha256:
            reasons.append('stored mission changed since capsule export')
        state = status(root, capsule.mission)
        if digest(state.get('contract', {})) != capsule.contract:
            reasons.append('capsule contract digest does not match stored mission contract')
        if state['source']['fingerprint'] != capsule.source_fingerprint:
            reasons.append('capsule source fingerprint does not match stored mission')
        if state['freshness'] != 'fresh':
            reasons.extend(state.get('freshness_reasons', ['stored mission is no longer fresh']))
        expected = _handoff_body(root, capsule.mission, target_provider=capsule.target_provider or None)
        for key in ('state', 'facts', 'objective', 'constraints', 'dag_status', 'modified_files',
                    'outstanding', 'diff_sha256', 'recovery_category', 'next_command', 'disclosure'):
            if capsule_data.get(key) != expected.get(key):
                reasons.append('capsule field does not match trusted state: ' + key)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        reasons.append(redact_text(str(exc))[:300])
    response['valid'] = not reasons
    response['freshness'] = 'fresh' if not reasons else 'stale'
    return response


def continue_from_handoff(
    root: Path,
    capsule_path: Path,
    *,
    agent: str | None = None,
    replay_path: Path | None = None,
    provider_executable: Path | None = None,
    allow_live: bool = False,
    max_cost_usd: float | None = None,
    extra_write_paths: list[str] | None = None,
    expect_fix: list[str] | None = None,
) -> dict[str, Any]:
    """Continue an interrupted or provider-blocked mission using a verified HandoffCapsule.

    The child inherits the original approved write paths. `extra_write_paths` are paths the user
    passes on the continuation command itself: they widen the scope by the user's authority (never
    the capsule's), go through the same plan validation, and are recorded in the child's provenance."""
    root = root.resolve()
    raw = isolate.read_inside(capsule_path.parent.resolve(), capsule_path.name, MAX_PATCH)
    if raw is None:
        raise ValueError('handoff capsule must be a bounded regular JSON file')
    capsule_data = json.loads(raw)
    if not isinstance(capsule_data, dict):
        raise ValueError('handoff capsule must be a JSON object')
    store = Store(root)
    mission_lock = store.path(capsule_data.get('mission', '')).with_suffix('.lock')
    # Serialize the whole lineage, including publishing the child's inherited
    # budget. Otherwise a second continuation could race that publication.
    with file_lock(store.folder / 'continuation.lock', timeout=0) as lineage_locked:
        if not lineage_locked:
            raise ValueError('another continuation is active in this repository')
        with file_lock(mission_lock, timeout=0) as locked:
            if not locked:
                raise ValueError('mission is running or continuing; concurrent continuation refused')
            return _continue_verified_handoff(root, capsule_data, agent=agent, replay_path=replay_path,
                                              provider_executable=provider_executable,
                                              allow_live=allow_live, max_cost_usd=max_cost_usd,
                                              extra_write_paths=extra_write_paths, expect_fix=expect_fix)


def _continue_verified_handoff(
    root: Path, capsule_data: dict[str, Any], *, agent: str | None,
    replay_path: Path | None, provider_executable: Path | None,
    allow_live: bool, max_cost_usd: float | None, extra_write_paths: list[str] | None = None,
    expect_fix: list[str] | None = None,
) -> dict[str, Any]:
    ver = verify_handoff(root, capsule_data)
    if not ver['valid']:
        raise ValueError('cannot continue from invalid or stale handoff capsule: ' + '; '.join(ver['reasons']))
    orig = status(root, capsule_data['mission'])
    orig_contract = orig['contract']
    if expect_fix and sorted(set(expect_fix)) != sorted(orig_contract.get('expect_fix') or []):
        raise ValueError('a continuation keeps the original --expect-fix scope exactly; '
                         f"it was {sorted(orig_contract.get('expect_fix') or []) or 'none'}")
    if orig.get('continuation_started'):
        raise ValueError('continuation already attempted; inspect recorded child or create a fresh approved plan')
    recovery = classify_recovery(orig)
    if not orig.get('cleanup_confirmed') or not recovery['recoverable']:
        raise ValueError('mission is not recoverable: ' + recovery['category'])
    if not orig_contract.get('execute') or not orig_contract.get('approvals'):
        raise ValueError('original mission has no local execution approval')
    seed: dict[str, Any] | None = None
    if orig.get('diff'):
        progress = partial_progress(orig)
        if progress is None:
            raise ValueError('prior diff has no validated progress (no fixed baseline failure, a new failure, or '
                             'inconsistent observations); not carried. Create a reviewed plan')
        if capsule_data.get('diff_sha256') != progress['diff_sha256']:
            raise ValueError('capsule diff digest does not match the stored diff')
        seed = {**progress, 'diff': orig['diff'], 'from_mission': orig['id']}
    depth = int(orig.get('continuation_depth', 0))
    if depth >= 2:
        raise ValueError('three-attempt continuation limit reached')
    target_agent = (
        agent
        if (agent and agent != 'auto')
        else (capsule_data.get('target_provider') or ('replay' if replay_path else orig_contract['provider']))
    )
    if capsule_data.get('target_provider') and target_agent != capsule_data['target_provider']:
        raise ValueError('target provider differs from exported scope; export a new handoff')
    prior_seconds = float(orig.get('seconds_used', 0.0))
    rem_seconds = float(orig_contract.get('max_seconds', 120.0)) - prior_seconds
    if rem_seconds < 1:
        raise ValueError('prior mission time budget exhausted; continuation refused')
    prior_provider = orig.get('provider') or {}
    inherited_budget = orig.get('continuation_budget') or {}
    prior_live = not prior_provider.get('simulated', True) or bool(inherited_budget.get('live_seen'))
    prior_cost = float(prior_provider.get('cost_usd', 0.0)) if not prior_provider.get('simulated', True) else 0.0
    cost_unknown = bool(inherited_budget.get('unknown_cost')) or (
        not prior_provider.get('simulated', True) and prior_provider.get('cost_status') != 'OBSERVED')
    prior_ceiling = float(inherited_budget.get('ceiling_usd', orig_contract.get('max_cost_usd', 0.0)))
    remaining_cost = max(0.0, prior_ceiling - prior_cost)
    eff_cost = max_cost_usd if max_cost_usd is not None else remaining_cost
    if prior_live and allow_live:
        # UNKNOWN spend only blocks when a dollar ceiling exists (or is requested) that it could silently exceed.
        # With no ceiling ever authorized (providers that cannot enforce one), there is nothing to reset; the
        # UNKNOWN cost status keeps propagating to the child instead.
        if cost_unknown and (prior_ceiling > 0 or eff_cost > 0):
            raise ValueError('prior live cost is UNKNOWN; continuation cannot establish remaining budget')
        if eff_cost > remaining_cost or (prior_ceiling > 0 and remaining_cost <= 0):
            raise ValueError('continuation exceeds remaining prior cost budget; create a newly approved plan')
    if target_agent == 'replay':
        eff_cost = 0.0

    inherited_paths = list(orig_contract['write_paths'])
    added_paths = [p for p in dict.fromkeys(extra_write_paths or []) if p not in inherited_paths]
    planned = plan(
        root,
        orig_contract['objective'],
        agent=target_agent,
        write_paths=inherited_paths + added_paths,
        execute_local=True,
        max_cost_usd=eff_cost,
        max_parallel=int(orig_contract.get('max_parallel', 1)),
        max_seconds=rem_seconds,
        command=orig_contract['acceptance'][0],
        allow_live=allow_live and target_agent in LIVE_PROVIDERS,
        expect_fix=list(orig_contract.get('expect_fix') or []),  # a continuation keeps the declared scope exactly
    )
    # Claim the attempt durably before any external side effect. A crash requires
    # inspecting the child; re-exporting cannot replay the parent's allowance.
    store = Store(root)
    parent = store.load(orig['id'])
    parent['continuation_started'] = {'capsule_sha256': digest(capsule_data),
                                    'target_provider': target_agent, 'planned_contract': digest(planned['contract'])}
    store.save(parent)
    result = execute(
        root,
        planned,
        replay_path,
        provider_executable=provider_executable,
        allow_live=allow_live and target_agent in LIVE_PROVIDERS,
        seed=seed,
    )
    store = Store(root)
    stored = store.load(result['id'])
    stored['continuation_depth'] = depth + 1
    stored['continuation_budget'] = {
        'live_seen': prior_live, 'unknown_cost': cost_unknown,
        'ceiling_usd': remaining_cost if target_agent == 'replay' else eff_cost,
    }
    stored['continued_from'] = {
        'mission': orig['id'],
        'capsule_sha256': digest(capsule_data),
        'prior_provider': (orig.get('provider') or {}).get('name', 'unknown'),
        'prior_verdict': orig.get('effective_verdict', 'INCONCLUSIVE'),
        'prior_recovery_category': capsule_data.get('recovery_category', 'unknown'),
        'prior_seconds_debited': prior_seconds,
        'inherited_write_paths': inherited_paths,
        'write_paths_added_by_user': added_paths,
        'prior_cost_usd': prior_cost if prior_provider.get('cost_status') == 'OBSERVED' else None,
        'partial_patch_transferred': seed is not None,
        'continuation_kind': ('partial_diff_reverified_from_same_frozen_source' if seed is not None
                              else 'fresh_candidate_from_same_frozen_source'),
        'preserved_facts': capsule_data.get('facts', []),
    }
    store.save(stored)
    parent['continuation_started']['child_mission'] = result['id']
    store.save(parent)
    return status(root, result['id'])


def apply_mission(root: Path, mission: str) -> dict[str, Any]:
    """Apply a verified candidate using the durable local application journal."""
    from .application import apply
    state = status(root, mission)
    if state.get('kind') == 'comparison':
        winner = (state.get('comparison') or {}).get('winner')
        if not winner or state.get('effective_verdict') != 'PASS':
            raise ValueError('candidate comparison has no fresh verified winner')
        mission = winner
    return apply(root, mission)


def undo_mission(root: Path, mission: str) -> dict[str, Any]:
    """Restore only receipt-owned bytes, refusing subsequent user changes."""
    from .application import undo
    return undo(root, mission)
