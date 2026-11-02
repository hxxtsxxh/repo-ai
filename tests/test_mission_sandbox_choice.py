"""`do --sandbox/--image`: the test environment is frozen with the mission and every run of the project's tests
(baseline, candidate, regression, change exercise, post-apply, continuation) uses it. Offline, simulated provider."""
from __future__ import annotations

import json
import sys

import pytest

from conftest import run_cli
from repo_ai import sandbox
from repo_ai.mission import runtime
from repo_ai.mission.contracts import IntentContract
from repo_ai.verify import execute
from test_mission_partial_handoff import FIX_BOTH, FIX_DISCOUNT, _provider, shop  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures('claude_fake_login')
HOST = 'seatbelt' if sys.platform == 'darwin' else 'bwrap'


def _host_sandbox() -> bool:
    try:
        sandbox.get_backend(HOST)
        return True
    except sandbox.SandboxUnavailable:
        return False


def _contract(**kw) -> IntentContract:
    return IntentContract('fix it', 'repo', 'a' * 40, ['python -m pytest'], [], **kw)


def test_the_default_keeps_contract_digests():
    assert 'sandbox' not in _contract().to_json() and 'image' not in _contract().to_json()
    value = _contract(sandbox='podman', image='localhost/deps:1').to_json()
    assert value['sandbox'] == 'podman' and value['image'] == 'localhost/deps:1'


@pytest.mark.parametrize('kw,problem', [
    ({'sandbox': 'vm'}, 'sandbox must be'),
    ({'image': 'x'}, 'needs sandbox podman or docker'),
    ({'sandbox': 'seatbelt', 'image': 'x'}, 'needs sandbox podman or docker'),
    ({'sandbox': 'podman', 'image': '--privileged'}, 'invalid image'),
    ({'sandbox': 'podman', 'image': 'a b'}, 'invalid image'),
    ({'sandbox': 'docker', 'image': 'x' * 301}, 'invalid image'),
])
def test_invalid_choices_are_refused(kw, problem):
    with pytest.raises(ValueError, match=problem):
        _contract(**kw).validate()


def test_do_refuses_an_image_without_a_container_sandbox(shop):  # noqa: F811
    proc = run_cli(shop, 'do', 'Fix pricing', '--image', 'localhost/deps:1')
    assert proc.returncode != 0 and 'needs sandbox podman or docker' in proc.stderr


def test_a_plan_records_the_choice(shop):  # noqa: F811
    proc = run_cli(shop, 'do', 'Fix pricing', '--sandbox', 'podman', '--image', 'localhost/deps:1', '--json')
    assert proc.returncode == 0, proc.stderr
    contract = json.loads(proc.stdout)['contract']
    assert contract['sandbox'] == 'podman' and contract['image'] == 'localhost/deps:1'


@pytest.fixture
def recorded(monkeypatch):
    """Every get_executor call a mission makes, by (preference, image); it then runs on the host sandbox (a
    container image is not available offline), so the mission completes and every call site is reached."""
    calls: list[tuple[str, str]] = []
    real = execute.get_executor

    def spy(root, preference='auto', language='python', timeout_s=600.0, image='', interpreter_root=None):
        calls.append((preference, image))
        return real(root, HOST, language, timeout_s=timeout_s, interpreter_root=interpreter_root)
    monkeypatch.setattr(execute, 'get_executor', spy)
    monkeypatch.setattr(runtime, 'get_executor', spy)
    return calls


@pytest.mark.skipif(not _host_sandbox(), reason='needs the host sandbox (seatbelt or bwrap)')
def test_every_test_run_of_a_mission_uses_the_frozen_environment(shop, tmp_path, recorded):  # noqa: F811
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True, sandbox='podman', image='localhost/deps:1')
    done = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, 'claude', FIX_BOTH))
    assert done['effective_verdict'] == 'PASS', done.get('reasons')
    before = len(recorded)
    assert before >= 3  # baseline, candidate, regression (and the change exercise)
    applied = runtime.apply_mission(shop, done['id'])
    assert applied['post_apply_verdict'] == 'PASS'
    assert len(recorded) > before  # post-apply verification
    assert set(recorded) == {('podman', 'localhost/deps:1')}


@pytest.mark.skipif(not _host_sandbox(), reason='needs the host sandbox (seatbelt or bwrap)')
def test_a_continuation_inherits_the_frozen_environment(shop, tmp_path, recorded):  # noqa: F811
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True, sandbox='docker', image='localhost/deps:2')
    first = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, 'claude', FIX_DISCOUNT))
    assert first['effective_verdict'] != 'PASS'
    capsule = tmp_path / 'capsule.json'
    capsule.write_text(json.dumps(runtime.handoff(shop, first['id'], target_provider='codex')))
    recorded.clear()
    child = runtime.continue_from_handoff(shop, capsule, agent='codex', replay_path=None,
                                          provider_executable=_provider(tmp_path, 'codex', FIX_BOTH),
                                          allow_live=False, max_cost_usd=None)
    assert child['contract']['sandbox'] == 'docker' and child['contract']['image'] == 'localhost/deps:2'
    assert recorded and set(recorded) == {('docker', 'localhost/deps:2')}
