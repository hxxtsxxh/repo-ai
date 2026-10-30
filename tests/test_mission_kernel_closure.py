"""Executed root helpers must invalidate evidence even without a version bump."""
import pytest
from repo_ai.mission import runtime


@pytest.mark.parametrize('helper', ['_seatbelt_procs.py', 'locks.py', 'gitinfo.py'])
def test_root_runtime_helper_change_invalidates_kernel(tmp_path, monkeypatch, helper):
    package = tmp_path / 'repo_ai'
    (package / 'mission').mkdir(parents=True)
    entry = package / 'mission/runtime.py'
    entry.write_text('# fake package for identity testing\n')
    for name in ('__init__.py', 'security.py', 'config.py', 'paths.py', 'sandbox.py', 'registry.py', helper):
        (package / name).write_text('# original\n')
    monkeypatch.setattr(runtime, '__file__', str(entry))
    before = runtime.kernel_identity()
    (package / helper).write_text('# modified execution helper\n')
    assert runtime.kernel_identity() != before
