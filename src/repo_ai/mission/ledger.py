"""Bounded atomic local checkpoints; hashes detect corruption, not a malicious local owner."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from ..config import load_config
from ..paths import make_dir, resolve_layout
from ..verify.isolate import read_inside
from .contracts import canonical, digest

MAX_RECORD = 2_000_000
TERMINAL = {'COMPLETE', 'INCONCLUSIVE', 'BLOCKED', 'CANCELLED'}
FLOW = {'CREATED': {'PLANNED'}, 'PLANNED': {'READY', 'AWAITING_APPROVAL'},
        'AWAITING_APPROVAL': {'READY'}, 'READY': {'RUNNING'}, 'RUNNING': {'VERIFYING'},
        'VERIFYING': {'REVIEWING'}, 'REVIEWING': {'COMPLETE'}}


def transition(state: dict[str, Any], target: str, reason: str = '') -> None:
    old = state['state']
    if old == target:
        return
    if old in TERMINAL or target not in FLOW.get(old, set()) | {'INCONCLUSIVE', 'BLOCKED', 'CANCELLED'}:
        raise ValueError(f'illegal state transition {old} -> {target}')
    if target == 'COMPLETE':
        ev = state.get('passport') or {}
        if ev.get('verdict') != 'PASS' or len(ev.get('observations', [])) < 3:
            raise ValueError('COMPLETE requires baseline, candidate and regression evidence')
    events = state.setdefault('events', [])
    event = {'index': len(events), 'from': old, 'to': target, 'reason': reason,
             'previous': digest(events[-1]) if events else ''}
    if len(events) >= 64:
        raise ValueError('event budget exhausted')
    events.append(event)
    state['state'] = target


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.layout = resolve_layout(self.root, load_config(self.root))
        self.folder = self.layout.state_dir / 'missions'
        self.repository = digest({'root': str(self.root)})

    def path(self, mission: str) -> Path:
        if not isinstance(mission, str) or not re.fullmatch('[a-f0-9]{24}', mission):
            raise ValueError('invalid mission ID')
        return self.folder / (mission + '.json')

    def _check(self) -> None:
        resolve_layout(self.root, load_config(self.root))
        if self.folder.is_symlink():
            raise ValueError('mission store is a symlink')

    def save(self, record: dict[str, Any]) -> None:
        self._check()
        path = self.path(record['id'])
        if record.get('repository') != self.repository or path.is_symlink():
            raise ValueError('mission repository boundary mismatch')
        if path.exists():
            self.load(record['id'])  # refuse to overwrite human files or corrupt records
        elif self.folder.exists() and len(list(self.folder.glob('*.json'))) >= 64:
            raise ValueError('mission retention limit reached; inspect and purge old missions explicitly')
        data = canonical({'schema': 'repo-ai.mission-state/1', 'record': record, 'sha256': digest(record)})
        if len(data.encode()) > MAX_RECORD:
            raise ValueError('mission record exceeds size limit')
        make_dir(self.root, self.folder, mode=0o700)
        fd, temp = tempfile.mkstemp(prefix='.checkpoint-', dir=self.folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(data + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def load(self, mission: str) -> dict[str, Any]:
        self._check()
        path = self.path(mission)
        raw = read_inside(self.folder, path.name, MAX_RECORD)
        if raw is None:
            raise ValueError('mission does not exist or is not a regular owned file')
        try:
            value = json.loads(raw)
            record = value['record']
            if value['schema'] != 'repo-ai.mission-state/1' or digest(record) != value['sha256'] \
                    or record['id'] != mission or record['repository'] != self.repository:
                raise ValueError('mission integrity or repository boundary mismatch')
            events = record.get('events', [])
            previous = ''
            for i, event in enumerate(events):
                if event['index'] != i or event['previous'] != previous:
                    raise ValueError('mission event integrity mismatch')
                previous = digest(event)
            return record
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('invalid mission record') from exc
