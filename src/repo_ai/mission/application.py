"""Journaled, conservative application of existing-file candidate changes.

An advisory lock serializes repo-ai writers, not arbitrary editors. Each replace
checks bytes again; rollback/undo refuses changed content. Receipts are local
unkeyed integrity records, not authentication or portable permissions.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from ..locks import file_lock
from ..verify.isolate import read_inside
from .contracts import MAX_SOURCE_FILE, canonical, digest, relative_path
from .ledger import Store

LIMIT = 256_000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _receipt_path(store: Store, mission: str) -> Path:
    store.path(mission)  # validate ID before constructing any path
    store._check()
    folder = store.folder / 'applications'
    if folder.is_symlink():
        raise ValueError('application receipt directory is a symlink')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / (mission + '.json')
    if path.is_symlink():
        raise ValueError('application receipt is a symlink')
    return path


def _save(path: Path, record: dict[str, Any]) -> None:
    payload = canonical({'schema': 'repo-ai.application-receipt/1', 'record': record, 'sha256': digest(record)})
    fd, tmp = tempfile.mkstemp(prefix='.application-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(payload + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _load(path: Path, store: Store, mission: str) -> dict[str, Any]:
    raw = read_inside(path.parent, path.name, 2_000_000)
    if raw is None:
        raise ValueError('application recovery receipt is missing or nonregular')
    try:
        envelope = json.loads(raw)
        rec = envelope['record']
        if (envelope['schema'] != 'repo-ai.application-receipt/1'
                or envelope['sha256'] != digest(rec) or rec['repository'] != store.repository
                or rec['mission'] != mission):
            raise ValueError('application receipt integrity or repository mismatch')
        stored = store.load(mission)
        if rec['diff_sha256'] != stored.get('diff_sha256') or rec['source'] != stored['source']:
            raise ValueError('application receipt no longer matches mission')
        if digest(rec['files']) != stored.get('application_files_sha256'):
            raise ValueError('application receipt files differ from trusted authorization')
        allowed = set(stored['contract']['write_paths'])
        for rel, item in rec['files'].items():
            if relative_path(rel) != rel or rel not in allowed:
                raise ValueError('application receipt path outside approved scope')
            if item['before_sha256'] != stored['source']['files'].get(rel):
                raise ValueError('application receipt baseline integrity mismatch')
            for side in ('before', 'after'):
                data = base64.b64decode(item[side], validate=True)
                if len(data) > LIMIT or _sha(data) != item[side + '_sha256']:
                    raise ValueError('application receipt content integrity mismatch')
        return rec
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid application receipt') from exc


def _replace(root: Path, rel: str, expected: bytes, replacement: bytes) -> None:
    """Pin directory descriptors and refuse links, hardlinks, mode/type changes.

    No portable atomic compare-and-swap exists for files edited by other tools.
    A concurrent editor must therefore be quiescent during the short replacement.
    """
    if os.name != 'posix' or not getattr(os, 'O_NOFOLLOW', 0):
        raise ValueError('safe application requires POSIX no-follow directory operations')
    parts = relative_path(rel).split('/')
    with contextlib.ExitStack() as stack:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            stack.callback(os.close, directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
            raise ValueError('application target is nonregular, hardlinked or oversized')
        with os.fdopen(os.dup(fd), 'rb') as handle:
            if handle.read(LIMIT + 1) != expected:
                raise ValueError('application conflict: target bytes changed')
        # Atomic replacement would lose ACLs/xattrs; decline such files explicitly.
        if hasattr(os, 'listxattr') and os.listxattr(fd):
            raise ValueError('application target has extended metadata; manual apply required')
        tmp = '.repo-ai-apply-' + os.urandom(12).hex()
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, stat.S_IMODE(info.st_mode), dir_fd=directory)
        try:
            with os.fdopen(out, 'wb') as stream:
                stream.write(replacement)
                stream.flush()
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                os.fsync(stream.fileno())
            current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (
                    info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise ValueError('application conflict: target changed before replacement')
            # Re-resolve from root too: an ancestor might have been renamed/replaced.
            if read_inside(root, rel, LIMIT) != expected:
                raise ValueError('application conflict: target path changed')
            os.replace(tmp, parts[-1], src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(tmp, dir_fd=directory)
            except FileNotFoundError:
                pass


def _prepare(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    from .runtime import git
    text = state.get('diff', '')
    if not isinstance(text, str) or not text or len(text.encode()) > LIMIT or _sha(text.encode()) != state.get('diff_sha256'):
        raise ValueError('candidate patch hash integrity mismatch or size bound exceeded')
    allowed = {relative_path(p) for p in state['contract']['write_paths']}
    before: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix='repo-ai-apply-check-') as temp:
        scratch = Path(temp).resolve()
        for rel, sha in state['source']['files'].items():
            data = read_inside(root, rel, MAX_SOURCE_FILE)
            if data is None or _sha(data) != sha:
                raise ValueError('source changed while preparing application')
            target = scratch / relative_path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(stat.S_IMODE((root / rel).stat().st_mode))
            if rel in allowed:
                before[rel] = data
        git(scratch, 'init', '-q')
        git(scratch, 'add', '-A')
        git(scratch, 'commit', '-qm', 'application validation baseline')
        patch = scratch.parent / (scratch.name + '.patch')
        try:
            patch.write_text(text + ('\n' if not text.endswith('\n') else ''), encoding='utf-8')
            git(scratch, 'apply', '--check', str(patch))
            git(scratch, 'apply', str(patch))
        finally:
            patch.unlink(missing_ok=True)
        rows = git(scratch, 'status', '--porcelain=v1', '-z', '--untracked-files=all').split('\0')
        changed = []
        for row in rows:
            if not row:
                continue
            if not row.startswith(' M ') or row[3:] not in allowed:
                raise ValueError('patch scope outside approved existing-file updates; create/delete/rename refused')
            changed.append(row[3:])
        if not changed or git(scratch, 'diff', '--summary'):
            raise ValueError('patch must change existing file bytes without mode/type changes')
        files = {}
        for rel in changed:
            after = read_inside(scratch, rel, LIMIT)
            if after is None or len(before[rel]) > LIMIT:
                raise ValueError('candidate target missing, nonregular or oversized')
            files[rel] = {'before': base64.b64encode(before[rel]).decode(), 'after': base64.b64encode(after).decode(),
                          'before_sha256': _sha(before[rel]), 'after_sha256': _sha(after)}
        return files


def _restore(root: Path, rec: dict[str, Any], path: Path) -> None:
    # Check every target before restoring any; user edits anywhere stop rollback.
    for rel, item in rec['files'].items():
        data = read_inside(root, rel, LIMIT)
        if data is None or _sha(data) not in {item['before_sha256'], item['after_sha256']}:
            rec['phase'] = 'CONFLICT'
            _save(path, rec)
            raise ValueError('application conflict: later user edits preserved; inspect recovery receipt')
    rec['phase'] = 'RESTORING'
    _save(path, rec)
    for rel, item in rec['files'].items():
        data = read_inside(root, rel, LIMIT)
        before = base64.b64decode(item['before'])
        if data == before:
            continue
        _replace(root, rel, base64.b64decode(item['after']), before)
    rec['phase'] = 'UNDONE'
    _save(path, rec)


def apply(root: Path, mission: str) -> dict[str, Any]:
    from . import runtime, verification
    root = root.resolve()
    store = Store(root)
    with file_lock(store.folder / 'application.lock', timeout=0) as acquired:
        if not acquired:
            raise ValueError('another apply/undo operation is running')
        state = runtime.status(root, mission)
        if state.get('kind') == 'comparison':
            raise ValueError('apply the selected candidate ID explicitly')
        path = _receipt_path(store, mission)
        if path.exists():
            raise ValueError('application receipt already exists; inspect it or use repo-ai undo')
        if (state.get('state') != 'COMPLETE' or state.get('effective_verdict') != 'PASS'
                or state.get('freshness') != 'fresh'):
            raise ValueError('refusing to apply: mission lacks fresh complete passing evidence')
        current = runtime.identity(root, require_clean=True)
        if current['fingerprint'] != state['source']['fingerprint']:
            raise ValueError('working tree does not match mission baseline')
        files = _prepare(root, state)
        if runtime.identity(root, require_clean=True) != current:
            raise ValueError('source changed during application preparation')
        rec = {'mission': mission, 'repository': store.repository, 'source': current,
               'diff_sha256': state['diff_sha256'], 'files': files, 'phase': 'PREPARED',
               'validation': 'candidate verified; integration pending'}
        # Bind immutable receipt content to the local mission BEFORE writes.
        # Recomputing an exported receipt checksum cannot change its authority.
        authorized = store.load(mission)
        authorized['application_files_sha256'] = digest(files)
        store.save(authorized)
        _save(path, rec)
        try:
            for rel, item in files.items():
                _replace(root, rel, base64.b64decode(item['before']), base64.b64decode(item['after']))
            rec['phase'] = 'VERIFYING'
            _save(path, rec)
            obs = verification.observe(root, state['contract']['acceptance'][0])
            verdict, reasons = verification.compare(state['baseline'], obs)
            if (verdict != 'PASS' or not obs.get('complete') or type(obs.get('ran')) is not int
                    or obs['ran'] <= 0 or obs.get('failed') != 0):
                raise ValueError('post-apply verification failed: ' + '; '.join(reasons))
            for rel, item in files.items():
                if read_inside(root, rel, LIMIT) != base64.b64decode(item['after']):
                    raise ValueError('application conflict: source changed during verification')
            rec.update(phase='APPLIED', validation='PASS', observation_sha256=digest(obs))
            _save(path, rec)
        except BaseException:
            _restore(root, rec, path)
            raise
        stored = store.load(mission)
        stored['applied_to_source'] = True
        if not stored.get('provider', {}).get('simulated', True):
            stored['provider']['verification_label'] = 'LIVE_VERIFIED'
        stored['application_receipt'] = str(path)
        stored['post_apply_observation_sha256'] = digest(obs)
        stored['post_apply_observation'] = obs
        store.save(stored)
        return {'schema': 'repo-ai.mission-apply/1', 'mission': mission, 'applied_to_source': True,
                'modified_files': sorted(files), 'diff_sha256': rec['diff_sha256'], 'receipt': str(path),
                'post_apply_verdict': 'PASS', 'provider_verification_label': stored.get('provider', {}).get('verification_label'), 'post_apply_ran': obs['ran'], 'post_apply_failed': 0,
                'observation_sha256': digest(obs)}


def undo(root: Path, mission: str) -> dict[str, Any]:
    from .runtime import check_privacy, git
    root = root.resolve()
    store = Store(root)
    with file_lock(store.folder / 'application.lock', timeout=0) as acquired:
        if not acquired:
            raise ValueError('another apply/undo operation is running')
        stored = store.load(mission)
        if not check_privacy(root, stored['contract']):
            raise ValueError('zone policy changed; undo receipt requires local review')
        path = _receipt_path(store, mission)
        rec = _load(path, store, mission)
        if git(root, 'rev-parse', 'HEAD') != rec['source']['head']:
            raise ValueError('HEAD changed since apply; refusing automatic undo')
        if git(root, 'diff', '--cached', '--name-only', '--', *rec['files']):
            raise ValueError('staged target changes conflict with undo')
        if rec['phase'] == 'UNDONE':
            if any(read_inside(root, rel, LIMIT) != base64.b64decode(item['before'])
                   for rel, item in rec['files'].items()):
                raise ValueError('receipt claims restoration but target bytes conflict')
        else:
            _restore(root, rec, path)
        stored['applied_to_source'] = False
        if not stored.get('provider', {}).get('simulated', True):
            stored['provider']['verification_label'] = 'LIVE_CANDIDATE_VERIFIED'
        stored['application_receipt'] = str(path)
        store.save(stored)
        return {'schema': 'repo-ai.mission-undo/1', 'mission': mission, 'undone': True,
                'receipt': str(path), 'modified_files': sorted(rec['files'])}
