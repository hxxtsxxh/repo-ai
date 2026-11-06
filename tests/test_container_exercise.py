"""C11 in a container backend (podman, or docker in CI): the change-exercise measurement and the per-test (pytest) /
per-file (node) records run with the same tracer and V8 machinery inside the container, whose root is read-only and
which has no network; everything is written under the mounted workspace's `.repo-ai/run` and mapped back from `/work`.

Skipped unless podman or docker is running with the image already present (nothing is pulled). Node uses repo-ai's
default node image (`repo-ai sandbox pull`; CI's sandbox job pulls it). pytest needs an image that has pytest, named by
REPO_AI_TEST_PYTEST_IMAGE: CI builds tests/fixtures/containers/pytest/Containerfile. With
REPO_AI_REQUIRE_CONTAINER_TESTS=1 (CI) a missing backend or image fails instead of skipping."""
import difflib
import hashlib
import json
import os

import pytest
from conftest import _git, run_cli
from repo_ai import sandbox

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='missions are POSIX-only')

JS_BEFORE = 'exports.pick = (x) => x;\n'
JS_AFTER = 'exports.pick = (x) => {\n  if (x < 0) {\n    return -x;\n  }\n  return x;\n};\n'
JS_HEAD = "const t = require('node:test');\nconst assert = require('node:assert');\nconst { pick } = require('./pick.js');\n"
PY_BEFORE = 'def pick(x):\n    return x\n'
PY_AFTER = 'def pick(x):\n    if x < 0:\n        return -x\n    return x\n'


def _backend(toolchain: str, image: str) -> str | None:
    """The first running container backend that already has `image` (never pulls)."""
    for cls in (sandbox.PodmanBackend, sandbox.DockerBackend):
        backend = cls({toolchain: image})
        try:
            if backend.available()[0] and backend.has_image(toolchain):
                return backend.name
        except (OSError, ValueError, RuntimeError):
            continue
    return None


NODE_IMAGE = sandbox.DEFAULT_IMAGES['node']
PYTEST_IMAGE = os.environ.get('REPO_AI_TEST_PYTEST_IMAGE', '')
# CI's sandbox job sets this: there a missing backend or image is a failure, not a quiet skip
REQUIRED = os.environ.get('REPO_AI_REQUIRE_CONTAINER_TESTS') == '1'


def _unavailable(reason: str):
    if REQUIRED:
        pytest.fail(f'REPO_AI_REQUIRE_CONTAINER_TESTS=1 but {reason}')
    pytest.skip(reason)


@pytest.fixture(scope='module')
def node_backend():
    name = _backend('node', NODE_IMAGE)
    if name is None:
        _unavailable(f'no running podman/docker with {NODE_IMAGE} present')
    return name


@pytest.fixture(scope='module')
def pytest_backend():
    if not PYTEST_IMAGE:
        _unavailable('REPO_AI_TEST_PYTEST_IMAGE is not set (build tests/fixtures/containers/pytest/Containerfile)')
    name = _backend('python', PYTEST_IMAGE)
    if name is None:
        _unavailable(f'no running podman/docker with {PYTEST_IMAGE} present')
    return name


def _diff(path, before, after):
    return f'diff --git a/{path} b/{path}\n' + ''.join(
        difflib.unified_diff(before.splitlines(True), after.splitlines(True), f'a/{path}', f'b/{path}'))


def _commit(root):
    _git(root, 'init', '-q')
    _git(root, 'add', '.')
    _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'c')
    return root


def _node_project(root, source=JS_AFTER, extra=None):
    root.mkdir(parents=True)
    (root / 'pick.js').write_text(source)
    (root / 'package.json').write_text('{"name": "p", "version": "1.0.0"}\n')
    (root / 'pick.test.js').write_text(JS_HEAD + "t('positive', () => assert.equal(pick(2), 2));\n")
    (root / 'neg.test.js').write_text(JS_HEAD + "t('negative', () => assert.equal(pick(-2), 2));\n")
    for name, text in (extra or {}).items():
        (root / name).write_text(text)
    return _commit(root)


def test_node_exercise_and_per_file_record_run_in_the_container(tmp_path, node_backend):
    from repo_ai.mission import exercise
    root = _node_project(tmp_path / 'njs')
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), sandbox_preference=node_backend,
                           per_test=True, timeout_s=300)
    assert rec['assurance'] == 'FULL' and rec['changed_lines'] == 4, rec
    assert rec['backend'] == node_backend and rec['container']['image_digest'].startswith('sha256:')
    assert rec['per_test_granularity'] == 'file' and rec['per_test_complete'] is True, rec
    assert rec['per_test'] == {'neg.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:3'],
                               'pick.test.js': ['pick.js:1', 'pick.js:2', 'pick.js:5']}, rec


def test_node_unrun_branch_in_the_container_is_partial(tmp_path, node_backend):
    from repo_ai.mission import exercise
    root = _node_project(tmp_path / 'njs')
    (root / 'neg.test.js').unlink()
    _git(root, 'add', '-A')
    _git(root, '-c', 'user.name=f', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'only positive')
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), sandbox_preference=node_backend,
                           timeout_s=300)
    assert rec['assurance'] == 'PARTIAL' and rec['unexercised'] == ['pick.js:2', 'pick.js:3'], rec


def test_a_link_planted_in_the_coverage_directory_inside_the_container_is_refused_on_the_host(tmp_path, node_backend):
    """The container writes through the workspace mount: a symbolic link it leaves there is seen and refused."""
    from repo_ai.mission import exercise
    plant = JS_HEAD + ("const fs = require('node:fs');\nconst path = require('node:path');\n"
                       "t('plants a link', () => { pick(1); fs.symlinkSync('../../../pick.js', "
                       "path.join(process.env.NODE_V8_COVERAGE, 'zz-link.json')); });\n")
    root = _node_project(tmp_path / 'njs', extra={'plant.test.js': plant})
    rec = exercise.measure(root, 'node --test', _diff('pick.js', JS_BEFORE, JS_AFTER), sandbox_preference=node_backend,
                           per_test=True, timeout_s=300)
    assert rec['assurance'] == 'UNMEASURED' and 'symbolic link' in rec['reason'], rec
    assert 'per_test' not in rec


def test_node_mission_in_a_container_shows_per_file_lines_in_coverage(tmp_path, node_backend):
    """The real path a journey takes: `do --sandbox <container>` with a frozen declaration, then `coverage ID`."""
    from repo_ai.mission import coverage as cov
    from repo_ai.mission.runtime import execute, plan, status
    plain = "const t = require('node:test');\nconst assert = require('node:assert');\nt('sum', () => assert.equal(1 + 1, 2));\n"
    root = _node_project(tmp_path / 'proj', source=JS_BEFORE, extra={'plain.test.js': plain})
    req = tmp_path / 'req.json'
    req.write_text(json.dumps({'schema': cov.REQ_SCHEMA, 'requirements': [
        {'text': 'negative input is negated', 'kind': 'change', 'tests': ['neg.test.js::negative']},
        {'text': 'positive input unchanged', 'kind': 'preserve', 'tests': ['pick.test.js::positive']},
        {'text': 'arithmetic', 'kind': 'preserve', 'tests': ['plain.test.js::sum']}]}))
    proposal = tmp_path / 'proposal.json'
    proposal.write_text(json.dumps({'schema': 'repo-ai.replay/1', 'label': 'simulated fixture agent', 'edits': [
        {'path': 'pick.js', 'before_sha256': hashlib.sha256(JS_BEFORE.encode()).hexdigest(), 'after': JS_AFTER}]}))
    p = plan(root, 'Make pick return the magnitude of a negative input', agent='replay', write_paths=['pick.js'],
             execute_local=True, command='node --test', sandbox=node_backend, image=NODE_IMAGE,
             max_seconds=600)
    p['requirements'] = cov.freeze(req)
    result = execute(root, p, proposal)
    state = status(root, result['id'])
    # a read-only status does not re-check a container image, so the effective verdict reads INCONCLUSIVE; the run
    # itself passed, which is when the exercise is measured
    assert state['passport']['verdict'] == 'PASS', state.get('freshness_reasons')
    ex = state['exercise']
    assert ex['backend'] == node_backend and ex['assurance'] == 'FULL', ex
    assert ex['container']['image_digest'] == state['candidate']['executor']['image_digest'], 'the verified image'
    assert ex['per_test_measured'] == ['neg.test.js', 'pick.test.js', 'plain.test.js'], ex
    assert ex['per_test_complete'] is True and ex['per_test_traced']['plain.test.js'] == {
        'exit_code': 0, 'outcomes': {'sum': 'pass'}}, ex
    data = json.loads(run_cli(root, 'coverage', result['id'], '--json').stdout)
    rows = {r['text']: r for r in data['requirements']}
    assert rows['negative input is negated']['changed_lines_run'] == ['pick.js:1', 'pick.js:2', 'pick.js:3']
    assert rows['positive input unchanged']['changed_lines_run'] == ['pick.js:1', 'pick.js:2', 'pick.js:5']
    assert data['changed_lines_by_requirement']['granularity'] == 'file'
    # traced in the container, as verified; the plain file ran no changed line: a positive "nothing"
    assert rows['negative input is negated']['changed_lines_trace'][0]['trace'] == 'TRACED'
    assert rows['arithmetic']['changed_lines_trace'][0]['trace'] == 'TRACED_NONE'
    assert data['changed_lines_by_requirement']['diverged_tests'] == []
    # the image is the only thing this read-only command cannot check: the observed outcomes count, labelled
    assert data['headline'] == 'ACCEPTANCE_MAPPED_ALL' and data['follow_up_test_needed'] == [], data
    assert data['image_check']['checked'] is False
    assert data['image_check']['image_digest'] == state['candidate']['executor']['image_digest']
    shown = run_cli(root, 'coverage', result['id'])
    assert shown.returncode == 0 and 'Image: image not re-checked by this read-only command' in shown.stdout
    assert 'plain.test.js::sum: traced, ran no changed line' in shown.stdout


def test_pytest_exercise_and_per_test_record_run_in_the_container(tmp_path, pytest_backend):
    from repo_ai.mission import exercise
    root = tmp_path / 'py'
    root.mkdir()
    (root / 'm.py').write_text(PY_AFTER)
    (root / 'test_m.py').write_text('from m import pick\n\n\ndef test_pick():\n    assert pick(2) == 2\n\n\n'
                                    'def test_neg():\n    assert pick(-2) == 2\n')
    (root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    _commit(root)
    rec = exercise.measure(root, 'python -m pytest', _diff('m.py', PY_BEFORE, PY_AFTER),
                           sandbox_preference=pytest_backend, image=PYTEST_IMAGE, per_test=True, timeout_s=300)
    assert rec['assurance'] == 'FULL' and rec['backend'] == pytest_backend, rec
    assert rec['tracer']['line_events'] in {'sys.monitoring', 'settrace'} and rec['tracer']['python'], rec
    assert rec['per_test'] == {'test_m.py::test_neg': ['m.py:2', 'm.py:3'], 'test_m.py::test_pick': ['m.py:2']}, rec
    assert rec['per_test_complete'] is True and rec['changed_outside_tests'] == []
    assert rec['per_test_traced'] == {'test_m.py::test_neg': 'pass', 'test_m.py::test_pick': 'pass'}, rec
    assert rec['per_test_exit_code'] == 0
