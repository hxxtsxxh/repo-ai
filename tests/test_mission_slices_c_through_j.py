"""Comprehensive tests for Reality Engine Slices C through J and Section 6."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from conftest import run_cli
from repo_ai import optimize, registry
from repo_ai.config import load_config
from repo_ai.mission import diagnosis, runtime, tournament, verification
from repo_ai.mission.eval_protocol import run_evaluation_protocol
from repo_ai.mission.ledger import Store
from repo_ai.paths import resolve_layout
from repo_ai.verify.testmap import TestMap
from test_mission_runtime import bug as bug_fixture, git, replay


@pytest.fixture
def bug(tmp_path: Path) -> Path:
    return bug_fixture.__wrapped__(tmp_path)


def test_slice_d_compare_cli_and_render(bug: Path, tmp_path: Path) -> None:
    with (bug / "test_charge.py").open("a", encoding="utf-8") as fh:
        fh.write("\ndef test_other_amount():\n    assert charge(7, 2) == 7\n")
    git(bug, "add", "test_charge.py")
    git(bug, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "more tests")

    bad = replay(bug, tmp_path / "bad", after="def charge(amount, retries):\n    return 10\n") if False else tmp_path / "bad.json"
    bad.write_text(
        json.dumps({
            "schema": "repo-ai.replay/1",
            "label": "bad",
            "edits": [{
                "path": "charge.py",
                "before_sha256": runtime.identity(bug)["files"]["charge.py"],
                "after": "def charge(amount, retries):\n    return 10\n",
            }],
        }),
        encoding="utf-8",
    )
    good = replay(bug, tmp_path)

    planned = runtime.plan(bug, "repair charge.py", agent="replay", write_paths=["charge.py"], execute_local=True)
    comp = tournament.compare_candidates(bug, planned, [bad, good])
    assert comp["verdict"] == "PASS"

    json_proc = run_cli(bug, "compare", comp["id"], "--json")
    assert json_proc.returncode == 0, json_proc.stderr
    inspected = json.loads(json_proc.stdout)
    assert inspected["winner"] == comp["winner"]
    assert inspected["freshness"] == "fresh"

    text_proc = run_cli(bug, "compare", comp["id"])
    assert text_proc.returncode == 0
    assert comp["winner"] in text_proc.stdout
    assert "No model self-voting" in text_proc.stdout

    # Non-comparison mission ID is rejected by inspect_comparison
    with pytest.raises(ValueError, match="not a candidate tournament"):
        tournament.inspect_comparison(bug, comp["winner"])


def test_slice_e_f_runtime_coverage_hypothesis_and_flaky_classification(bug: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Seed a TestMap with runtime coverage linking test_charge.py to charge.py
    layout = resolve_layout(bug, load_config(bug))
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    tmap = TestMap(
        runner={"kind": "pytest"},
        file_hashes={"charge.py": "d" * 64},
        tests={"test_charge.py": {"units": {"charge.py": ["charge"]}}},
    )
    tmap.save(layout.state_dir / "testmap.json")

    fake_obs_fail = {
        "schema": "repo-ai.mission-observation/1",
        "repo_ai_version": runtime.status.__module__ and __import__("repo_ai").__version__,
        "trusted": True,
        "complete": True,
        "environment_unchanged": True,
        "cleanup_confirmed": True,
        "integrity": {"unchanged": True},
        "outcomes": {"test_charge.py::test_retry": "fail", "test_charge.py::test_once": "pass"},
        "test_ids": ["test_charge.py::test_once", "test_charge.py::test_retry"],
        "ran": 2,
        "failed": 1,
        "skipped": 0,
        "exit_code": 1,
        "timed_out": False,
        "stdout_sha256": "a" * 64,
        "stderr_sha256": "b" * 64,
        "pin": {"fingerprint": "f1", "command": "python -m pytest", "runner": "py", "test_inputs": {"test_charge.py": "1" * 64}},
        "executor": {"backend": "seatbelt"},
        "environment_key": "env1",
        "environment_static": {},
    }
    fake_obs_pass_flaky = copy.deepcopy(fake_obs_fail)
    fake_obs_pass_flaky["outcomes"]["test_charge.py::test_retry"] = "pass"
    fake_obs_pass_flaky["failed"] = 0
    fake_obs_pass_flaky["exit_code"] = 0

    state = {
        "id": "c" * 24,
        "state": "INCONCLUSIVE",
        "freshness": "fresh",
        "effective_verdict": "FAIL",
        "source": {"files": {"charge.py": "d" * 64}},
        "contract": {"acceptance": ["python -m pytest"], "write_paths": ["charge.py"]},
        "plan": {"context": {"packet": {"locations": [{"path": "charge.py"}]}}},
        "baseline": fake_obs_fail,
        "candidate": fake_obs_fail,
        "attempts": [
            {"nodes": {"baseline": {"artifact": fake_obs_pass_flaky}}},
        ],
        "passport": {"negative": ["candidate did not pass every test"]},
    }
    monkeypatch.setattr(runtime, "status", lambda *a, **k: copy.deepcopy(state))
    monkeypatch.setattr(verification.cache, "static_environment_change", lambda *a, **k: ("unchanged", ""))

    rep = diagnosis.diagnose(bug, state["id"])
    assert rep["standing"] == "OBSERVED"
    by_id = {r["test_id"]: r["classification"] for r in rep["tests"]}
    assert by_id["test_charge.py::test_retry"] == "FLAKY_OR_INCONSISTENT"
    assert by_id["test_charge.py::test_once"] == "UNCHANGED_PASS"
    assert rep["source_hypotheses"][0]["priority"] == "runtime-trace-link"
    assert rep["source_hypotheses"][0]["confidence"] == "observed"
    assert rep["next_experiments"]


def test_slice_g_seven_class_recovery_classifier_and_handoff_verification(bug: Path, tmp_path: Path) -> None:
    assert set(runtime.RECOVERY_CLASSES) == {
        "none",
        "retryable_transient",
        "partial_progress",
        "contract_failure",
        "permission_required",
        "budget_limit",
        "environment",
        "provider_unavailable",
        "unrecoverable_ambiguous_side_effect",
    }

    assert runtime.classify_recovery({"state": "COMPLETE", "effective_verdict": "PASS"})["category"] == "none"
    assert (
        runtime.classify_recovery({
            "state": "INCONCLUSIVE",
            "cleanup_confirmed": False,
            "nodes": {"edit": {"status": "RUNNING"}},
        })["category"]
        == "unrecoverable_ambiguous_side_effect"
    )
    assert (
        runtime.classify_recovery({
            "state": "INCONCLUSIVE",
            "passport": {"negative": ["mission time budget exhausted"]},
        })["category"]
        == "budget_limit"
    )
    assert (
        runtime.classify_recovery({
            "state": "INCONCLUSIVE",
            "passport": {"negative": ["provider modified unapproved path: x.py"]},
        })["category"]
        == "permission_required"
    )
    assert (
        runtime.classify_recovery({
            "state": "INCONCLUSIVE",
            "provider": {"stage": "NOT_INSTALLED"},
            "passport": {"negative": ["codex executable is not installed"]},
        })["category"]
        == "provider_unavailable"
    )
    assert (
        runtime.classify_recovery({
            "state": "INCONCLUSIVE",
            "passport": {"negative": ["test environment changed during the observation"]},
        })["category"]
        == "environment"
    )
    assert (
        runtime.classify_recovery({
            "state": "INCONCLUSIVE",
            "candidate": {"failed": 1},
            "passport": {"negative": ["candidate did not pass every test"]},
        })["category"]
        == "contract_failure"
    )
    assert (
        runtime.classify_recovery({
            "state": "CANCELLED",
            "cleanup_confirmed": True,
            "passport": {"negative": ["cancellation requested"]},
        })["category"]
        == "retryable_transient"
    )

    # End-to-end handoff --to and --verify
    planned = runtime.plan(bug, "repair charge.py", agent="replay", write_paths=["charge.py"], execute_local=True)
    res = runtime.execute(bug, planned, replay(bug, tmp_path))
    cap_proc = run_cli(bug, "handoff", res["id"], "--to", "claude", "--json")
    assert cap_proc.returncode == 0, cap_proc.stderr
    cap = json.loads(cap_proc.stdout)
    assert cap["target_provider"] == "claude"
    assert cap["recovery_category"] == "none"

    cap_file = tmp_path / "capsule.json"
    cap_file.write_text(json.dumps(cap), encoding="utf-8")
    ver_proc = run_cli(bug, "handoff", "--verify", str(cap_file), "--json")
    assert ver_proc.returncode == 0, ver_proc.stderr
    ver = json.loads(ver_proc.stdout)
    assert ver["valid"] is True

    # Mutating source invalidates handoff verification
    (bug / "charge.py").write_text("mutated\n", encoding="utf-8")
    ver_stale = run_cli(bug, "handoff", "--verify", str(cap_file), "--json")
    assert ver_stale.returncode == 2
    assert json.loads(ver_stale.stdout)["valid"] is False


def test_slice_h_optimize_mission_stats_and_proposals(bug: Path) -> None:
    store = Store(bug)
    for i in range(3):
        store.save({
            "id": f"{i}" * 24,
            "repository": store.repository,
            "state": "INCONCLUSIVE",
            "events": [],
            "provider": {"name": "replay"},
            "passport": {"verdict": "FAIL"},
            "seconds_used": 1.5,
        })
    stats = optimize.mission_stats(bug)
    assert stats["missions_total"] == 3
    assert stats["verified_pass"] == 0
    cfg = load_config(bug)
    layout = resolve_layout(bug, cfg)
    props = optimize.proposals(bug, cfg, layout, [])
    assert props["missions"]["missions_total"] == 3
    assert any(p.id == "mission-acceptance-review" for p in props["proposals"])
    perf = optimize.performance(bug, cfg, layout, [])
    assert perf["missions"]["missions_total"] == 3


def test_slice_i_change_futures_local_and_same_zone_cross_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_AI_HOME", str(tmp_path / "rh"))
    # Provider repo exposing package "charge-lib"
    provider_repo = bug_fixture.__wrapped__(tmp_path)
    (provider_repo / "package.json").write_text('{"name": "charge-lib", "version": "1.0.0"}\n', encoding="utf-8")
    git(provider_repo, "add", "package.json")
    git(provider_repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "pkg")

    # Consumer repo in same zone depending on "charge-lib"
    consumer_repo = tmp_path / "consumer"
    consumer_repo.mkdir()
    (consumer_repo / "package.json").write_text(
        '{"name": "checkout-service", "dependencies": {"charge-lib": "^1.0.0"}}\n',
        encoding="utf-8",
    )
    (consumer_repo / "index.js").write_text("console.log('hi');\n", encoding="utf-8")
    git(consumer_repo, "init", "-q")
    git(consumer_repo, "add", ".")
    git(consumer_repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "init")
    assert run_cli(consumer_repo, "init", "--agent", "none", "-q", env={"REPO_AI_HOME": str(tmp_path / "rh")}).returncode == 0

    registry.add(provider_repo, "payments", label="provider-svc")
    registry.add(consumer_repo, "payments", label="consumer-svc")

    proc = run_cli(
        provider_repo,
        "futures",
        "--target-path",
        "charge.py",
        "--json",
        env={"REPO_AI_HOME": str(tmp_path / "rh")},
    )
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(proc.stdout)
    assert rep["zone"] == "payments"
    assert rep["searched_same_zone_peers"] == 1
    assert rep["local_impact"][0]["path"] == "charge.py"
    assert any(
        h["peer_repo"] == "consumer-svc" and h["kind"] == "depends_on_package" and h["confidence"] == "static"
        for h in rep["cross_repository_hypotheses"]
    )
    text_proc = run_cli(
        provider_repo,
        "futures",
        "--target-path",
        "charge.py",
        env={"REPO_AI_HOME": str(tmp_path / "rh")},
    )
    assert text_proc.returncode == 0
    assert "consumer-svc" in text_proc.stdout


def test_slice_j_and_section_6_demo_and_evaluation_protocol(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo_out"
    proc = run_cli(None, "demo", "--directory", str(demo_dir), "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    demo_rep = json.loads(proc.stdout)
    assert demo_rep["verdict"] == "PASS"
    assert demo_rep["original_unchanged"] is True

    eval_dir = tmp_path / "eval_out"
    eval_rep = run_evaluation_protocol(eval_dir)
    assert eval_rep["schema"] == "repo-ai.reality-eval/1"
    naive = eval_rep["arms"]["unassisted_naive_baseline"]
    engine = eval_rep["arms"]["reality_engine_verified"]
    assert naive["false_pass_rate"] == 1.0
    assert engine["verified_completion_rate"] == 1.0
    assert engine["false_pass_rate"] == 0.0
    assert engine["unscoped_file_touch_rate"] == 0.0
    assert engine["regression_escape_rate"] == 0.0
    assert engine["handoff_recovery_success_rate"] == 1.0
    assert (eval_dir / "eval-report.json").is_file()


def test_an_authentication_failure_is_not_a_transient_retry() -> None:
    # live probe 2026-10-29: Claude in repo-ai's isolated HOME reports "Not logged in"; resuming repeats it
    from repo_ai.mission import runtime
    rec = runtime.classify_recovery({
        "state": "INCONCLUSIVE", "effective_verdict": "BLOCKED", "cleanup_confirmed": True,
        "provider": {"name": "claude", "stage": "LIVE_FAILED"},
        "passport": {"negative": ["provider process exited with code 1; provider error event: authentication_failed; "
                                  "provider error event: Not logged in · Please run /login"]},
    })
    assert rec["category"] == "provider_unavailable" and "retrying will fail" in rec["action"]
    assert "handoff --to" in rec["action"]


def test_auth_text_outside_a_provider_error_does_not_override_a_permission_failure() -> None:
    # adversarial review finding E
    from repo_ai.mission import runtime
    rec = runtime.classify_recovery({
        "state": "INCONCLUSIVE", "effective_verdict": "FAIL", "cleanup_confirmed": True,
        "passport": {"negative": ["frozen test file changed: test_x.py", "test output: Not logged in"]},
    })
    assert rec["category"] == "permission_required"
