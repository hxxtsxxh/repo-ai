"""Change Futures (Slice I / Priority F): local and same-zone cross-repository impact hypotheses.

Strictly offline and zone-bound. Cross-repository links are labeled as static
(manifest dependency) or heuristic (API route literal match), never as observed
runtime truth unless explicitly rehearsed locally (`--rehearse`), and never
trigger automatic cross-repository edits.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..analyze import run_analysis
from ..config import load_config
from ..impact import analyze_impact
from ..index import open_index
from ..paths import resolve_layout
from ..registry import crossrepo_impact
from ..security import redact_text
from ..verify import isolate
from .context import MAX_FILE_BYTES, MAX_FILES
from .contracts import digest, relative_path
from .runtime import check_privacy, git, privacy_binding, status


def analyze_futures(
    root: Path,
    mission: str | None = None,
    *,
    paths: list[str] | None = None,
    rehearse: bool = False,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    zone, _ = privacy_binding(root)
    target_paths: list[str] = []
    mission_state: dict[str, Any] | None = None
    if mission:
        mission_state = status(root, mission)
        if 'contract' in mission_state and not check_privacy(root, mission_state['contract']):
            raise ValueError('zone policy changed or unbound legacy contract')
        for p in mission_state.get('contract', {}).get('write_paths', []):
            target_paths.append(relative_path(p))
    if paths:
        for p in paths:
            rel = relative_path(p)
            if rel not in target_paths:
                target_paths.append(rel)
    if not target_paths:
        raise ValueError('supply a mission ID with write_paths or explicit --target-path targets')

    cfg = load_config(root)
    layout = resolve_layout(root, cfg)
    cfg = replace(
        cfg,
        detect_secrets=True,
        follow_symlinks=False,
        summarize=False,
        max_files=max(1, min(cfg.max_files, MAX_FILES)),
        max_file_bytes=max(1, min(cfg.max_file_bytes, MAX_FILE_BYTES)),
        workers=max(1, min(cfg.workers or 2, 4)),
    )
    prune = tuple(sorted({layout.rel(p) for p in layout.owned_dirs()}))

    local_impacts: list[dict[str, Any]] = []
    cross_links: list[dict[str, Any]] = []
    searched_peers = 0

    with tempfile.TemporaryDirectory(prefix='repo-ai-mission-futures-') as temporary:
        state_dir = Path(temporary)
        analysis = run_analysis(root, cfg, layout.context_dir, state_dir=state_dir, prune=prune)
        with open_index(state_dir) as index:
            for rel in target_paths[:16]:
                rep = analyze_impact(index, analysis.facts, [rel], max_depth=2, root=root)
                direct = sorted(p for p, d in rep.importers.items() if d == 1)
                linked_tests = [redact_text(t) for t in sorted(rep.tests)[:25]]
                falsifier = (
                    ['repo-ai', 'futures', mission, '--rehearse']
                    if mission
                    else ['repo-ai', 'verify', '--run']
                )
                local_impacts.append({
                    'path': redact_text(rel),
                    'risk': rep.risk,
                    'confidence': 'static',
                    'direct_importers': [redact_text(p) for p in direct[:25]],
                    'transitive_importers': len(rep.importers),
                    'linked_tests': linked_tests,
                    'uncertainty': [redact_text(u) for u in rep.uncertainty[:10]],
                    'falsifier': falsifier,
                    'rehearsal_verdict': 'NOT_RUN',
                })
            cross = crossrepo_impact(root, index)
            searched_peers = int(cross.get('searched', 0))
            for link in cross.get('links', [])[:50]:
                conf = 'static' if link.get('proof') == 'manifest' else 'heuristic'
                peer = redact_text(str(link.get('repo', '')))
                cross_links.append({
                    'peer_repo': peer,
                    'kind': str(link.get('kind', '')),
                    'confidence': conf,
                    'evidence': redact_text(str(link.get('evidence', ''))),
                    'target': redact_text(str(link.get('target', ''))),
                    'falsifier': ['repo-ai', 'verify', '--run'],
                })

    rehearsal_summary: dict[str, Any] | None = None
    reran_tests = False
    if rehearse:
        if mission_state is None or not mission_state.get('diff'):
            raise ValueError('futures --rehearse requires a mission ID with a recorded candidate diff')
        from .verification import observe
        base_head = mission_state['source']['head']
        cmd = mission_state['contract']['acceptance'][0]
        diff_text = mission_state['diff']
        with isolate.materialize_commit(root, base_head, label='futures-rehearsal', dependencies=True) as ws:
            git(ws.path, 'init', '-q')
            git(ws.path, 'add', '-A')
            git(ws.path, 'commit', '-qm', 'futures rehearsal baseline')
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.patch', delete=False) as tf:
                tf.write(diff_text if diff_text.endswith('\n') else diff_text + '\n')
                patch_file = Path(tf.name)
            try:
                git(ws.path, 'apply', str(patch_file))
            finally:
                patch_file.unlink(missing_ok=True)
            obs = observe(ws.path, cmd, timeout_s=60.0)
            reran_tests = True
            passed = bool(obs.get('complete') and obs.get('failed', 0) == 0)
            rehearsal_summary = {
                'rehearsed': True,
                'verdict': 'PASS' if passed else 'FALSIFIED',
                'ran': obs.get('ran', 0),
                'failed': obs.get('failed', 0),
                'observation_sha256': digest(obs),
            }
            for item in local_impacts:
                item['confidence'] = 'observed'
                item['rehearsal_verdict'] = 'PASS' if passed else 'FALSIFIED'

    return {
        'schema': 'repo-ai.change-futures/1',
        'mission': mission,
        'zone': zone,
        'changed_paths': target_paths,
        'local_impact': local_impacts,
        'searched_same_zone_peers': searched_peers,
        'cross_repository_hypotheses': cross_links,
        'rehearsal': rehearsal_summary,
        'reran_tests': reran_tests,
        'invoked_provider': False,
        'limitations': [
            'Static and heuristic impact hypotheses unless --rehearse is executed on a mission diff',
            'Cross-repository search is strictly bounded to indexed peers enrolled in the same privacy zone',
            'Never performs automatic cross-repository edits or migrations',
        ],
    }


def render_futures(report: dict[str, Any]) -> str:
    def quote(text: Any) -> str:
        return json.dumps(text, ensure_ascii=True)

    header = f"Change Futures (zone: {report['zone']}; peers searched: {report['searched_same_zone_peers']})"
    lines = [header]
    for item in report.get('local_impact', []):
        reh = item.get('rehearsal_verdict', 'NOT_RUN')
        lines.append(
            f"  Local [{item['confidence']}; rehearsal={reh}] {quote(item['path'])}: risk={item['risk']}, "
            f"importers={len(item['direct_importers'])}, linked_tests={len(item['linked_tests'])}"
        )
    for link in report.get('cross_repository_hypotheses', []):
        lines.append(
            f"  Peer [{link['confidence']}] {quote(link['peer_repo'])} ({link['kind']}): "
            f"{quote(link['target'])} via {quote(link['evidence'])}"
        )
    if not report.get('cross_repository_hypotheses'):
        lines.append('  Peer hypotheses: none observed in current zone')
    if report.get('rehearsal'):
        r = report['rehearsal']
        lines.append(f"  Sandbox rehearsal: {r['verdict']} ({r['ran']} tests ran, {r['failed']} failed)")
    else:
        lines.append('Experimental static/heuristic hypotheses only; no tests or providers were invoked.')
    return '\n'.join(lines)
