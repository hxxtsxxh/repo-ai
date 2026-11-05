"""Mission planning reuses repository analysis without installing or executing it."""
from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from conftest import _git, commit_all


def _repo(path: Path, *, git: bool = True) -> Path:
    path.mkdir()
    (path / "billing.py").write_text(
        'def charge_once(amount, key, seen):\n'
        '    """Charge each idempotency key once."""\n'
        '    return amount\n')
    (path / "tests").mkdir()
    (path / "tests/test_billing.py").write_text(
        'from billing import charge_once\n\n'
        'def test_duplicate_retry():\n'
        '    assert charge_once(10, "key", {}) == 10\n')
    (path / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    if git:
        _git(path, "init", "-q", "-b", "main")
        commit_all(path, "fixture")
    return path


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in root.rglob("*") if p.is_file()}


def test_clean_uninitialized_repository_has_source_linked_context(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    result = build_context(root, "Fix charge_once duplicate retry charges")
    assert result["packet"]["locations"][0]["path"] == "billing.py"
    assert "tests/test_billing.py" in result["packet"]["tests"]
    assert result["source_head"]
    assert result["index_fingerprint"]
    assert result["freshness"] == "fresh_scan"
    assert not (root / ".repo-ai").exists()


def test_exact_path_wins_over_similar_prose(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    (root / "other.py").write_text('"""billing retry charge charge charge."""\ndef other(): pass\n')
    result = build_context(root, "Fix billing.py retry behavior")
    assert result["packet"]["locations"][0]["path"] == "billing.py"


def test_planning_preserves_user_files_config_and_existing_index(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    state = root / ".repo-ai/state"
    state.mkdir(parents=True)
    (state / "index.db").write_bytes(b"unrecognized old index; must not open or migrate")
    (root / ".repo-ai/config.toml").write_text('agents = ["claude"]\n')
    (root / "CLAUDE.md").write_text("Human instructions stay intact.\n")
    before = _snapshot(root)
    build_context(root, "Fix charge_once")
    assert _snapshot(root) == before


def test_planning_never_invokes_provider_repository_code_or_network(tmp_path, monkeypatch):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    real_run = subprocess.run
    calls = []

    def guarded(argv, *args, **kwargs):
        assert isinstance(argv, list) and Path(argv[0]).name == "git"
        assert not kwargs.get("shell", False)
        calls.append(argv)
        return real_run(argv, *args, **kwargs)

    def denied(*args, **kwargs):
        pytest.fail("Planning attempted a network call")

    monkeypatch.setattr(subprocess, "run", guarded)
    monkeypatch.setattr(socket, "socket", denied)
    result = build_context(root, "Fix charge_once")
    assert calls and result["packet"]["locations"]


def test_secret_quarantine_cannot_be_disabled_by_repository_config(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ1234"
    (root / "leaky.py").write_text('KEY = "-----BEGIN RSA PRIVATE KEY-----"\n'
                                   'def secret_payment(): pass\n')
    (root / ".env").write_text(f"TOKEN={token}\n")
    (root / "repo-ai.toml").write_text('detect_secrets = false\nfollow_symlinks = true\n')
    result = build_context(root, "secret_payment leaky.py")
    assert token not in json.dumps(result)
    assert not any(p["path"] in {"leaky.py", ".env"} for p in result["packet"]["locations"])
    assert result["scan"]["quarantined"] >= 2


def test_non_git_repository_reports_missing_baseline(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo", git=False)
    result = build_context(root, "Fix charge_once")
    assert result["source_head"] == ""
    assert any("git" in w.lower() for w in result["warnings"])
    assert result["packet"]["locations"]


def test_content_changes_invalidate_context_without_head_change(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    before = build_context(root, "Fix charge_once")
    (root / "billing.py").write_text('def charge_once(amount, key, seen):\n    return 0\n')
    after = build_context(root, "Fix charge_once")
    assert before["source_head"] == after["source_head"]
    assert before["index_fingerprint"] != after["index_fingerprint"]


@pytest.mark.parametrize("task,budget", [("", 900), ("x" * 8001, 900), ("fix", 0), ("fix", 5000)])
def test_invalid_or_unbounded_input_is_rejected(tmp_path, task, budget):
    from repo_ai.mission.context import build_context

    with pytest.raises(ValueError):
        build_context(tmp_path, task, budget)


def test_missing_git_executable_is_explicit_and_does_not_block_static_context(tmp_path, monkeypatch):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo", git=False)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git is unavailable")

    monkeypatch.setattr(subprocess, "run", unavailable)
    result = build_context(root, "Fix charge_once")
    assert result["source_head"] == ""
    assert result["packet"]["locations"]
    assert any("baseline" in w.lower() for w in result["warnings"])


def test_scan_cap_is_disclosed_as_partial(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    (root / "repo-ai.toml").write_text("max_files = 1\n")
    result = build_context(root, "Fix charge_once")
    assert result["scan"]["indexed"] == 1
    assert not result["complete"]
    assert any("partial" in w.lower() for w in result["warnings"])


def test_task_secrets_are_redacted_before_context_is_returned(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ1234"
    result = build_context(root, f"Fix charge_once; TOKEN={token}")
    assert token not in json.dumps(result)


def test_context_ignores_symlinks_even_when_configuration_enables_them(tmp_path):
    from repo_ai.mission.context import build_context

    root = _repo(tmp_path / "repo")
    outside = tmp_path / "outside.py"
    outside.write_text("def foreign_billing_secret(): pass\n")
    try:
        (root / "foreign.py").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    (root / "repo-ai.toml").write_text("follow_symlinks = true\n")
    result = build_context(root, "foreign_billing_secret foreign.py")
    assert not any(p["path"] == "foreign.py" for p in result["packet"]["locations"])
    assert result["scan"]["skipped"]["symlink"] == 1
