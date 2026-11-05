import pytest
from repo_ai.mission.contracts import IntentContract, ExecutionDAG, Node, decode, digest


def test_intent_roundtrip_and_zero_cost():
    c = IntentContract('repair arithmetic', 'repo-local', 'a' * 40, ['existing full suite'], ['calc.py'])
    assert c.max_cost_usd == 0 and not c.execute and not c.network
    assert decode(c.to_json()) == c
    assert digest(c.to_json()) == digest(decode(c.to_json()).to_json())


@pytest.mark.parametrize('update', [dict(network='false'), dict(execute=1), dict(max_cost_usd=-1),
                                   dict(max_cost_usd=float('nan')), dict(max_parallel=0),
                                   dict(write_paths=['../secret']), dict(write_paths=['.git/config']),
                                   dict(unexpected='grant')])
def test_untrusted_fields_never_authorize(update):
    raw = IntentContract('repair', 'repo', 'a' * 40, [], ['calc.py']).to_json()
    raw.update(update)
    with pytest.raises(ValueError):
        decode(raw)


def test_schema_unknown_fails_closed():
    raw = IntentContract('repair', 'repo', 'a' * 40, [], []).to_json()
    raw['schema'] = 'repo-ai.intent/999'
    with pytest.raises(ValueError):
        decode(raw)


def test_dag_rejects_cycles_missing_dependencies_and_multiple_write_owners():
    for nodes in ([Node('a', 'read', ['b']), Node('b', 'read', ['a'])],
                  [Node('a', 'read', ['absent'])],
                  [Node('a', 'write', [], 'one'), Node('b', 'write', [], 'two')]):
        with pytest.raises(ValueError):
            ExecutionDAG(nodes).validate()
    d = ExecutionDAG([Node('read', 'read'), Node('edit', 'write', ['read']), Node('verify', 'verify', ['edit'])])
    assert decode(d.to_json()) == d
