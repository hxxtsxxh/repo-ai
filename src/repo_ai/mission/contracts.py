"""Versioned local mission contracts. Repository prose never grants authority."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import PurePosixPath
from typing import Any, ClassVar

MAX_SOURCE_FILE = 25_000_000  # bytes per tracked file a mission reads; the whole source stays bounded at 50 MB
MAX_PARSE_FILE = 2_000_000    # bytes of one Python file a mission parses (an AST of a huge module costs gigabytes)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('invalid relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in {'..', '.git', '.repo-ai', '.claude', '.bob'} for x in p.parts) \
            or str(p) != value or ':' in value:
        raise ValueError('path is outside the permitted source boundary')
    return value


def strings(value: Any, name: str, limit: int = 100) -> None:
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) or len(v) > 4000 for v in value):
        raise ValueError(f'invalid {name}')


@dataclass
class Contract:
    schema: ClassVar[str]

    def validate(self) -> None:
        canonical(asdict(self))

    def to_json(self) -> dict[str, Any]:
        self.validate()
        return {'schema': self.schema, **asdict(self)}


ROLE_NAMES = frozenset({'investigator', 'adversary'})


@dataclass
class IntentContract(Contract):
    schema: ClassVar[str] = 'repo-ai.intent/1'
    objective: str
    repository: str
    base: str
    acceptance: list[str]
    write_paths: list[str]
    unknowns: list[str] = field(default_factory=lambda: ['Task intent is advisory; tests cover only observed behavior'])
    execute: bool = False
    network: bool = False
    provider: str = 'none'
    max_cost_usd: float = 0.0
    max_parallel: int = 1
    max_seconds: float = 120.0
    max_tokens: int = 0
    approvals: list[str] = field(default_factory=list)
    zone: str = 'local'
    policy_sha256: str = ''
    roles: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        value = super().to_json()
        if not value['roles']:
            del value['roles']  # keeps pre-role contract digests and stored missions valid
        return value

    def validate(self) -> None:
        strings(self.roles, 'roles', 4)
        if any(r not in ROLE_NAMES for r in self.roles) or len(set(self.roles)) != len(self.roles):
            raise ValueError('roles must be unique members of ' + ', '.join(sorted(ROLE_NAMES)))
        if not isinstance(self.policy_sha256, str) or (self.policy_sha256 and
                (len(self.policy_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.policy_sha256))):
            raise ValueError('invalid policy fingerprint')
        for name in ('objective', 'repository', 'base', 'provider', 'zone'):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip() or len(v) > 4000:
                raise ValueError(f'invalid {name}')
        for name in ('acceptance', 'write_paths', 'unknowns', 'approvals'):
            strings(getattr(self, name), name)
        for path in self.write_paths:
            relative_path(path)
        if type(self.execute) is not bool or type(self.network) is not bool:
            raise ValueError('permissions must be explicit booleans')
        for name, low, high in [('max_cost_usd', 0, 10000), ('max_seconds', 1, 3600)]:
            v = getattr(self, name)
            if type(v) not in (float, int) or not math.isfinite(v) or not low <= v <= high:
                raise ValueError(f'invalid {name}')
        if type(self.max_parallel) is not int or not 1 <= self.max_parallel <= 4:
            raise ValueError('max_parallel must be 1..4')
        if type(self.max_tokens) is not int or not 0 <= self.max_tokens <= 1000000:
            raise ValueError('invalid token budget')
        super().validate()


@dataclass
class Node:
    id: str
    mode: str
    depends_on: list[str] = field(default_factory=list)
    owner: str = 'controller'
    reason: str = ''


@dataclass
class ExecutionDAG(Contract):
    schema: ClassVar[str] = 'repo-ai.execution-dag/1'
    nodes: list[Node]
    max_parallel: int = 1
    retries: int = 0

    def validate(self) -> None:
        if type(self.max_parallel) is not int or not 1 <= self.max_parallel <= 4 or type(self.retries) is not int or self.retries != 0:
            raise ValueError('invalid execution bounds; automatic retries are disabled')
        if not isinstance(self.nodes, list) or not 1 <= len(self.nodes) <= 16:
            raise ValueError('DAG must have 1..16 nodes')
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i or len(i) > 80 for i in ids):
            raise ValueError('invalid node IDs')
        owners = set()
        for n in self.nodes:
            if not isinstance(n.owner, str) or not n.owner.strip() or len(n.owner) > 80:
                raise ValueError('invalid node owner')
            if not isinstance(n.reason, str) or len(n.reason) > 4000:
                raise ValueError('invalid node reason')
            strings(n.depends_on, 'dependencies', 16)
            if n.mode not in {'read', 'write', 'verify', 'review'} or any(d not in ids for d in n.depends_on):
                raise ValueError('invalid mode or missing dependency')
            if n.mode == 'write':
                owners.add(n.owner)
        if len(owners) > 1 or sum(n.mode == 'write' for n in self.nodes) > 1:
            raise ValueError('one accountable write owner and one write node are required')
        done: set[str] = set()
        while len(done) < len(ids):
            ready = {n.id for n in self.nodes if n.id not in done and set(n.depends_on) <= done}
            if not ready:
                raise ValueError('cyclic execution DAG')
            done |= ready
        super().validate()


@dataclass
class RealityGraph(Contract):
    schema: ClassVar[str] = 'repo-ai.reality-graph/1'
    target: str
    edges: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        if not isinstance(self.target, str) or not isinstance(self.edges, list) or len(self.edges) > 256:
            raise ValueError('invalid graph')
        for edge in self.edges:
            if set(edge) != {'source', 'target', 'relation', 'provenance', 'scope', 'freshness', 'confidence'} \
                    or edge['confidence'] not in {'observed', 'static', 'heuristic', 'unknown'} \
                    or edge['freshness'] not in {'fresh', 'stale', 'not checked'} \
                    or any(not isinstance(v, str) for v in edge.values()):
                raise ValueError('invalid evidence edge')
        super().validate()


@dataclass
class CapabilityProfile(Contract):
    schema: ClassVar[str] = 'repo-ai.capability-profile/1'
    provider: str
    status: str
    executable: str = ''
    version: str = ''
    identity_sha256: str = ''
    authentication: str = 'UNKNOWN'
    modes: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def validate(self) -> None:
        for name in ('provider', 'status', 'executable', 'version', 'identity_sha256', 'authentication'):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f'invalid {name}')
        for name in ('modes', 'provenance', 'limitations'):
            strings(getattr(self, name), name)
        super().validate()


@dataclass
class EvidenceRecord(Contract):
    schema: ClassVar[str] = 'repo-ai.mission-evidence/1'
    target: str
    contract: str
    verdict: str
    observations: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    untested: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.verdict not in {'PASS', 'FAIL', 'INCONCLUSIVE', 'BLOCKED'}:
            raise ValueError('invalid evidence verdict')
        for name in ('target', 'contract'):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f'invalid {name}')
        for name in ('observations', 'negative', 'untested'):
            strings(getattr(self, name), name)
        if self.verdict == 'PASS' and not self.observations:
            raise ValueError('PASS requires observed evidence')
        super().validate()


@dataclass
class HandoffCapsule(Contract):
    schema: ClassVar[str] = 'repo-ai.handoff/2'
    mission: str
    repository: str
    contract: str
    state: str
    facts: list[dict[str, str]]
    next_command: list[str]
    zone: str = 'local'
    disclosure: str = 'LOCAL_ONLY; local-store-bound receipt; no source or provider session included'
    objective: str = ''
    constraints: list[str] = field(default_factory=list)
    dag_status: dict[str, str] = field(default_factory=dict)
    modified_files: list[str] = field(default_factory=list)
    outstanding: list[str] = field(default_factory=list)
    diff_sha256: str = ''
    target_provider: str = ''
    recovery_category: str = 'none'
    source_fingerprint: str = ''
    mission_snapshot_sha256: str = ''
    integrity_sha256: str = ''

    def validate(self) -> None:
        if any(not isinstance(getattr(self, k), str) for k in (
                'mission', 'repository', 'contract', 'state', 'zone', 'disclosure',
                'target_provider', 'recovery_category', 'source_fingerprint',
                'mission_snapshot_sha256', 'integrity_sha256')):
            raise ValueError('invalid capsule identity')
        strings(self.next_command, 'next command', 20)
        for name in ('constraints', 'modified_files', 'outstanding'):
            strings(getattr(self, name), name)
        if not isinstance(self.objective, str) or not isinstance(self.diff_sha256, str) or not isinstance(self.dag_status, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.dag_status.items()):
            raise ValueError('invalid portable task state')
        if not isinstance(self.facts, list) or len(self.facts) > 100 or any(
            not isinstance(f, dict) or set(f) != {'claim', 'evidence', 'standing'} or
            any(not isinstance(v, str) for v in f.values()) for f in self.facts
        ):
            raise ValueError('invalid checked facts')
        super().validate()


TYPES = {c.schema: c for c in (IntentContract, RealityGraph, CapabilityProfile, ExecutionDAG, EvidenceRecord, HandoffCapsule)}


def decode(data: dict[str, Any]) -> Any:
    """Explicit version dispatch. No legacy authority is inferred; unknown versions refuse.

    These are first-version contracts; no prior mission store exists to migrate.
    Future migrations must register an explicit schema transform here and never add consent.
    """
    if not isinstance(data, dict) or not isinstance(data.get('schema'), str) or data.get('schema') not in TYPES:
        raise ValueError('unsupported contract schema; explicit migration required')
    cls = TYPES[data['schema']]
    raw = {k: v for k, v in data.items() if k != 'schema'}
    if set(raw) - {f.name for f in fields(cls)}:
        raise ValueError('unknown contract field')
    try:
        if cls is ExecutionDAG:
            raw['nodes'] = [Node(**n) for n in raw['nodes']]
        value = cls(**raw)
        value.validate()
        return value
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError('malformed contract') from exc
