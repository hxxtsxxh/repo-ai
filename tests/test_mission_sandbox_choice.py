"""`do --sandbox/--image`: the test environment is frozen with the mission and every run of the project's tests
(baseline, candidate, regression, change exercise, post-apply, continuation) uses it. Offline, simulated provider."""
from __future__ import annotations

import json
import os
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


def test_a_container_sandbox_needs_an_image():
    with pytest.raises(ValueError, match='needs --image'):
        _contract(sandbox='podman').validate()


@pytest.fixture
def srcpkg(tmp_path):
    """A src-layout project with no pytest `pythonpath` setting: in a container (project not installed) its tests
    can import it only through PYTHONPATH=src."""
    from test_mission_partial_handoff import _git
    root = tmp_path / 'srcpkg'
    (root / 'src' / 'pricing').mkdir(parents=True)
    (root / 'tests').mkdir()
    (root / 'src' / 'pricing' / '__init__.py').write_text('def add_tax(price, rate):\n    return price + rate\n')
    (root / 'tests' / 'test_pricing.py').write_text(
        'from pricing import add_tax\n\n\ndef test_tax():\n    assert add_tax(200, 10) == 220\n')
    (root / '.gitignore').write_text('__pycache__/\n.pytest_cache/\n.repo-ai/\n')
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'baseline')
    return root


@pytest.mark.skipif(not _host_sandbox(), reason='needs the host sandbox (seatbelt or bwrap)')
def test_a_src_layout_project_is_imported_through_pythonpath_in_a_container(srcpkg, tmp_path, recorded,
                                                                             monkeypatch):
    seen: list[str] = []
    real_run = execute.Executor.run

    def run(self, argv, *, cwd='', env=None, **kw):
        seen.append((env or {}).get('PYTHONPATH', ''))
        return real_run(self, argv, cwd=cwd, env=env, **kw)
    monkeypatch.setattr(execute.Executor, 'run', run)
    fixed = 'def add_tax(price, rate):\n    return price + price * rate / 100\n'
    cli = _provider(tmp_path, 'claude', '')
    cli.write_text(cli.read_text().replace("(ws / 'pricing.py').write_text('')",
                                           f"(ws / 'src' / 'pricing' / '__init__.py').write_text({fixed!r})"))
    planned = runtime.plan(srcpkg, 'Make add_tax compute a percentage', agent='claude',
                           write_paths=['src/pricing/__init__.py'], execute_local=True, sandbox='podman',
                           image='localhost/deps:1')
    done = runtime.execute(srcpkg, planned, None, provider_executable=cli)
    assert done['effective_verdict'] == 'PASS', done.get('reasons')
    assert seen and all(p.split(os.pathsep)[0] == 'src' for p in seen), seen
    assert set(recorded) == {('podman', 'localhost/deps:1')}


def test_a_continuation_refuses_a_different_environment(shop, tmp_path, recorded):  # noqa: F811
    if not _host_sandbox():
        pytest.skip('needs the host sandbox (seatbelt or bwrap)')
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True)
    first = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, 'claude', FIX_DISCOUNT))
    capsule = tmp_path / 'capsule.json'
    capsule.write_text(json.dumps(runtime.handoff(shop, first['id'], target_provider='codex')))
    with pytest.raises(ValueError, match='keeps the test environment frozen'):
        runtime.continue_from_handoff(shop, capsule, agent='codex', provider_executable=_provider(
            tmp_path, 'codex', FIX_BOTH), sandbox='podman', image='localhost/deps:1')


def test_resume_refuses_a_sandbox_choice(shop):  # noqa: F811
    proc = run_cli(shop, 'do', '--resume', 'abc', '--sandbox', 'podman')
    assert proc.returncode != 0 and 'frozen with the mission' in proc.stderr


@pytest.fixture
def image_unchecked(monkeypatch):
    """As with a real container: the evidence records that its image cannot be re-checked by path."""
    from repo_ai.verify import cache
    real = cache.static_environment

    def static(executor, runner, links=None):
        return {**real(executor, runner, links), 'unchecked': ['container image']}
    monkeypatch.setattr(cache, 'static_environment', static)


@pytest.mark.skipif(not _host_sandbox(), reason='needs the host sandbox (seatbelt or bwrap)')
def test_a_container_mission_reads_not_checked_and_can_still_be_applied(shop, tmp_path, recorded, image_unchecked):  # noqa: F811
    """0.12.0 refused to apply any mission run in a container: its evidence always reads "not checked" (the image
    cannot be checked read-only). apply accepts exactly that, because it re-runs the tests in the same image."""
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True, sandbox='podman', image='localhost/deps:1')
    done = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, 'claude', FIX_BOTH))
    state = runtime.status(shop, done['id'])
    assert state['freshness'] == 'not checked' and state['passport']['verdict'] == 'PASS'
    assert runtime.image_only_pass(state) and 'repo-ai apply' in state['recovery']['action']
    before = len(recorded)
    applied = runtime.apply_mission(shop, done['id'])
    assert applied['post_apply_verdict'] == 'PASS' and applied['applied_to_source']
    assert recorded[before:] and set(recorded[before:]) == {('podman', 'localhost/deps:1')}  # re-run in that image


@pytest.mark.skipif(not _host_sandbox(), reason='needs the host sandbox (seatbelt or bwrap)')
def test_a_stale_container_mission_is_still_refused(shop, tmp_path, recorded, image_unchecked):  # noqa: F811
    planned = runtime.plan(shop, 'Make pricing.py compute percentage discounts and tax correctly', agent='claude',
                           write_paths=['pricing.py'], execute_local=True, sandbox='podman', image='localhost/deps:1')
    exe = _provider(tmp_path, 'claude', FIX_BOTH)
    done = runtime.execute(shop, planned, None, provider_executable=exe)
    exe.write_text(exe.read_text() + '\n# another build\n')  # stale for a reason only the gate checks
    state = runtime.status(shop, done['id'])
    assert state['freshness'] == 'stale' and not runtime.image_only_pass(state)
    with pytest.raises(ValueError, match='lacks fresh'):
        runtime.apply_mission(shop, done['id'])


@pytest.mark.skipif(not _host_sandbox(), reason='needs the host sandbox (seatbelt or bwrap)')
def test_do_apply_applies_a_container_mission(shop, tmp_path, recorded, image_unchecked, capsys):  # noqa: F811
    from repo_ai.cli import main
    exe = _provider(tmp_path, 'claude', FIX_BOTH)
    code = main(['do', 'Make pricing.py compute percentage discounts and tax correctly', '-C', str(shop), '--agent',
                 'claude', '--run', '--allow-write', 'pricing.py', '--sandbox', 'podman', '--image', 'localhost/deps:1',
                 '--provider-executable', str(exe), '--apply', '--json'])
    out = json.loads(capsys.readouterr().out)
    assert out['applied_to_source'] is True and out['apply_result']['post_apply_verdict'] == 'PASS'
    assert code == 0
    assert 'repo-ai apply' not in out['recovery']['action'] and 'applied' in out['recovery']['action']
