"""Bounded DAG execution for controller-owned actions, never arbitrary repository commands.

Actions must enforce their own subprocess timeout. Cancellation stops new work;
active bounded actions finish/clean up before this function returns. There are no
background workers, automatic retries, dynamic node creation or recursive delegation.
"""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable

from .contracts import ExecutionDAG, canonical, digest


def run(dag: ExecutionDAG, actions: dict[str, Callable[[], dict[str, Any]]],
        records: dict[str, dict[str, Any]], *, deadline: float,
        cancelled: Callable[[], bool] = lambda: False,
        checkpoint: Callable[[], None] = lambda: None) -> dict[str, dict[str, Any]]:
    dag.validate()
    ids = {n.id for n in dag.nodes}
    if set(actions) != ids or set(records) - ids:
        raise ValueError('actions/checkpoints do not match frozen DAG')
    for node in dag.nodes:
        old = records.get(node.id)
        if old and old.get('status') == 'SUCCEEDED':
            if digest(old.get('artifact')) != old.get('artifact_sha256'):
                raise ValueError('checkpoint artifact integrity mismatch')
        elif old:
            raise ValueError('interrupted or failed node requires explicit recovery; no implicit retry')
    done = {key for key, value in records.items() if value.get('status') == 'SUCCEEDED'}
    pending = ids - done
    active: dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=dag.max_parallel, thread_name_prefix='repo-ai-mission') as pool:
        try:
            while pending or active:
                if cancelled():
                    raise InterruptedError('mission cancellation requested')
                if time.monotonic() >= deadline:
                    raise TimeoutError('mission deadline reached')
                ready = [n for n in dag.nodes if n.id in pending and set(n.depends_on) <= done]
                for node in ready[:max(0, dag.max_parallel - len(active))]:
                    records[node.id] = {'status': 'RUNNING', 'mode': node.mode, 'owner': node.owner,
                                        'reason': node.reason, 'attempt': 1}
                    checkpoint()  # durable intent precedes dispatch
                    active[pool.submit(actions[node.id])] = node.id
                    pending.remove(node.id)
                if not active:
                    raise ValueError('DAG cannot make progress')
                finished, _ = wait(active, timeout=min(.05, max(0, deadline-time.monotonic())),
                                   return_when=FIRST_COMPLETED)
                for future in sorted(finished, key=lambda f: active[f]):
                    key = active.pop(future)
                    try:
                        artifact = future.result()
                        if not isinstance(artifact, dict) or len(canonical(artifact).encode()) > 512_000:
                            raise ValueError('node artifact is invalid or exceeds 512 KB')
                        records[key].update(status='SUCCEEDED', artifact=artifact, artifact_sha256=digest(artifact))
                        done.add(key)
                        checkpoint()
                    except BaseException:
                        records[key]['status'] = 'FAILED'
                        checkpoint()
                        raise
        except BaseException:
            for future, key in active.items():
                future.cancel()
                records[key]['status'] = 'INTERRUPTED'
            checkpoint()
            raise
    return records
