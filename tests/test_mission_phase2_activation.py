"""Phase II Activation tests covering Priorities A through F and adversarial negative controls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import run_cli
from repo_ai import optimize
from repo_ai.config import load_config
from repo_ai.mission import diagnosis, futures, runtime, verification
from repo_ai.mission.eval_protocol import build_preregistered_study_spec, run_evaluation_protocol, wilson_ci_95
from repo_ai.paths import resolve_layout
from repo_ai.providers import build_invocation, parse_event_stream, run_provider, validate_workspace_edits
from repo_ai.verify.testmap import TestMap
from test_mission_runtime import bug as bug_fixture, replay

pytestmark = pytest.mark.usefixtures('claude_fake_login')


@pytest.fixture
def bug(tmp_path: Path) -> Path:
    return bug_fixture.__wrapped__(tmp_path)


def _make_fake_cli(tmp_path: Path, name: str, body: str) -> Path:
    cli_dir = tmp_path / "phase2_bins"
    cli_dir.mkdir(exist_ok=True)
    script = cli_dir / name
    script.write_text(f"#!{sys.executable} -I\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def test_priority_a_version_accurate_invocations_and_unknown_cost_fail_closed(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    # Claude 2.1.x requires --verbose with stream-json and -- before prompt
    claude_argv = build_invocation("claude", "/usr/local/bin/claude", "--dangerously-skip-permissions", ws, max_cost_usd=0.15)
    assert "--verbose" in claude_argv
    assert "--no-session-persistence" in claude_argv
    assert claude_argv[-2] == "--"
    assert claude_argv[-1] == "--dangerously-skip-permissions"

    # Bob 2.0.x uses --trust --disable-mcp --disable-subagents (never --sandbox)
    bob_argv = build_invocation("bob", "/usr/local/bin/bob", "Fix bug", ws, max_cost_usd=0.20)
    assert "--sandbox" not in bob_argv
    assert "--trust" in bob_argv
    assert "--disable-mcp" in bob_argv
    assert "--disable-subagents" in bob_argv


    # Bob JSON output with stats.session_costs and stats.tool_calls is parsed accurately
    bob_out = json.dumps({
        "type": "result",
        "status": "success",
        "stats": {"task_id": "bob-task-1", "duration_ms": 1200, "session_costs": 0.0792, "tool_calls": 2},
        "last_message": "Updated charge.py",
    }).encode("utf-8")
    parsed_bob = parse_event_stream("bob", bob_out)
    assert parsed_bob["valid_jsonl"] is True
    assert parsed_bob["session_id"] == "bob-task-1"
    assert parsed_bob["cost_reported"] is True
    assert parsed_bob["cost_status"] == "OBSERVED"
    assert parsed_bob["cost_usd"] == 0.0792
    assert len(parsed_bob["tool_calls"]) == 2

    # Unreported cost is labeled UNKNOWN, not falsely certified as OBSERVED
    unreported = parse_event_stream("codex", json.dumps({"type": "turn.completed"}).encode("utf-8"))
    assert unreported["cost_reported"] is False
    assert unreported["cost_status"] == "UNKNOWN"

    # >500 lines fails closed instead of silently truncating
    overflow_stream = ("\n".join(json.dumps({"type": "step"}) for _ in range(505))).encode("utf-8")
    overflow_parsed = parse_event_stream("codex", overflow_stream)
    assert overflow_parsed["valid_jsonl"] is False
    assert any("500-line bound" in e for e in overflow_parsed["errors"])

    # Live provider run with max_cost_usd > 0 fails closed if provider does not report cost
    root = tmp_path / "repo"
    root.mkdir()
    no_cost_cli = _make_fake_cli(
        tmp_path,
        "fake-claude-nocost",
        "import json\nprint(json.dumps({'type': 'result', 'session_id': 's1', 'summary': 'done'}))\n",
    )
    res = run_provider(
        "claude",
        root,
        ws,
        "Fix bug",
        write_paths=["charge.py"],
        executable=no_cost_cli,
        max_cost_usd=0.10,
        simulated=False,
        allow_live=True,
    )
    assert res["stage"] == "FAILED"
    assert any("unknown cost cannot satisfy hard USD budget" in r for r in res["reasons"])


def test_priority_b_conductor_trivial_vs_risky_classification_and_broker(bug: Path) -> None:
    # Trivial task refuses specialist fan-out and selects NO_TOOL
    trivial_plan = runtime.plan(
        bug,
        "Fix typo in comment in charge.py",
        agent="replay",
        write_paths=["charge.py"],
        execute_local=True,
        max_parallel=2,
    )
    assert trivial_plan["orchestration"]["complexity"] == "trivial"
    assert trivial_plan["orchestration"]["specialists_spawned"] == []
    assert trivial_plan["orchestration"]["specialists_refused"]
    assert trivial_plan["capability_broker"]["decision"] == "NO_TOOL"
    assert {n["id"] for n in trivial_plan["dag"]["nodes"]} == {"context", "baseline", "edit", "candidate", "review"}

    # Risky payment/retry task with uncertainty and max_parallel=2 spawns read-only specialists
    risky_plan = runtime.plan(
        bug,
        "Fix duplicate payment charge when retry uncertain",
        agent="replay",
        write_paths=["charge.py"],
        execute_local=True,
        max_parallel=2,
    )
    assert risky_plan["orchestration"]["complexity"] == "risky"
    assert "skeptic" in risky_plan["orchestration"]["specialists_spawned"]
    assert risky_plan["capability_broker"]["decision"] == "SECURITY_AND_VERIFICATION_GATED"
    assert {n["id"] for n in risky_plan["dag"]["nodes"]} >= {"impact", "acceptance"}


def test_priority_c_cross_provider_rate_limit_handoff_and_apply(bug: Path, tmp_path: Path) -> None:
    # Step 1: First provider (claude) hits a 429 rate_limit_event
    rate_limited_claude = _make_fake_cli(
        tmp_path,
        "fake-claude-429",
        (
            "import json, sys\n"
            "print(json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'rateLimitType': 'seven_day'}}))\n"
            "print(json.dumps({'type': 'result', 'is_error': True, 'api_error_status': 429, 'api_error': 'usage_limit_reached', 'total_cost_usd': 0.0, 'result': 'monthly spend limit'}))\n"
            "sys.exit(1)\n"
        ),
    )
    fail_proc = run_cli(
        bug,
        "do",
        "Fix duplicate charge in charge.py",
        "--agent",
        "claude",
        "--provider-executable",
        str(rate_limited_claude),
        "--allow-write",
        "charge.py",
        "--run",
        "--json",
    )
    assert fail_proc.returncode == 2
    failed_state = json.loads(fail_proc.stdout)
    assert failed_state["effective_verdict"] != "PASS"
    assert failed_state["provider"]["rate_limited"] is True
    assert failed_state["recovery"]["category"] == "provider_unavailable"
    assert failed_state["recovery"]["recoverable"] is True

    # Step 2: Export handoff capsule targeting bob
    cap_proc = run_cli(bug, "handoff", failed_state["id"], "--to", "bob", "--json")
    assert cap_proc.returncode == 0
    capsule = json.loads(cap_proc.stdout)
    assert capsule["target_provider"] == "bob"
    assert capsule["recovery_category"] == "provider_unavailable"
    cap_file = tmp_path / "handoff_to_bob.json"
    cap_file.write_text(json.dumps(capsule), encoding="utf-8")

    # Step 3: Second provider (bob) continues from the handoff capsule and applies the verified fix
    working_bob = _make_fake_cli(
        tmp_path,
        "fake-bob-ok",
        (
            "import json, os, pathlib\n"
            "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
            "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
            "print(json.dumps({'type': 'result', 'status': 'success', 'stats': {'task_id': 'b1', 'session_costs': 0.05, 'tool_calls': 1}, 'last_message': 'fixed'}))\n"
        ),
    )
    cont_proc = run_cli(
        bug,
        "do",
        "--from-handoff",
        str(cap_file),
        "--provider-executable",
        str(working_bob),
        "--allow-live-provider",
        "--max-cost-usd",
        "0.25",
        "--run",
        "--apply",
        "--json",
    )
    assert cont_proc.returncode == 0, cont_proc.stdout + cont_proc.stderr
    cont_state = json.loads(cont_proc.stdout)
    assert cont_state["effective_verdict"] == "PASS"
    assert cont_state["provider"]["name"] == "bob"
    assert cont_state["provider"]["verification_label"] == "LIVE_VERIFIED"
    assert cont_state["continued_from"]["mission"] == failed_state["id"]
    assert cont_state["continued_from"]["prior_provider"] == "claude"
    assert cont_state["applied_to_source"] is True
    assert (bug / "charge.py").read_text(encoding="utf-8") == "def charge(amount, retries):\n    return amount\n"


def test_priority_d_freshness_invalidation_and_adversarial_negative_controls(bug: Path, tmp_path: Path) -> None:
    # 1. Provider binary mutation after execution invalidates mission freshness
    cli_bin = _make_fake_cli(
        tmp_path,
        "fake-codex-mut",
        (
            "import json, os, pathlib\n"
            "ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])\n"
            "(ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')\n"
            "print(json.dumps({'type': 'turn.completed', 'cost_usd': 0.0}))\n"
        ),
    )
    planned = runtime.plan(bug, "Repair charge.py", agent="codex", write_paths=["charge.py"], execute_local=True)
    res = runtime.execute(bug, planned, None, provider_executable=cli_bin)
    assert res["effective_verdict"] == "PASS"
    assert res["freshness"] == "fresh"

    # Mutate provider binary on disk -> status() must become stale and INCONCLUSIVE
    cli_bin.write_text(cli_bin.read_text(encoding="utf-8") + "# mutated binary\n", encoding="utf-8")
    stale_state = runtime.status(bug, res["id"])
    assert stale_state["freshness"] == "stale"
    assert stale_state["effective_verdict"] == "INCONCLUSIVE"
    assert any("provider binary changed" in r for r in stale_state["freshness_reasons"])

    # 2. Negative control: candidate attempting to reference internal reporter is refused
    forger_prop = replay(
        bug,
        tmp_path,
        after="def charge(amount, retries):\n    # mission-observation forgery\n    return amount\n",
    )
    plan_rep = runtime.plan(bug, "Repair charge.py", agent="replay", write_paths=["charge.py"], execute_local=True)
    with pytest.raises(ValueError, match="internal verification reporter"):
        runtime.execute(bug, plan_rep, forger_prop)

    # 3. Negative control: symlink creation, .git/hooks tampering, and spec/ helper protection
    ws = tmp_path / "adv_ws"
    ws.mkdir()
    (ws / ".git" / "hooks").mkdir(parents=True)
    (ws / ".git" / "hooks" / "post-checkout").write_text("#!/bin/sh\n", encoding="utf-8")
    (ws / "charge.py").symlink_to(bug / "charge.py")
    reasons = validate_workspace_edits(bug, ws, ["charge.py"], {"test_charge.py"}, {"charge.py", "test_charge.py"})
    assert any("git hook" in r for r in reasons)
    assert any("symlink" in r for r in reasons)
    assert verification.test_support("spec/helper.py") is True
    assert verification.test_support("test_helpers/util.py") is True
    assert verification.test_support("tsconfig.json") is True

    # 4. Stale TestMap with mismatched file_hashes is not reported as observed runtime coverage
    layout = resolve_layout(bug, load_config(bug))
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    tmap = TestMap(
        runner={"kind": "pytest"},
        file_hashes={"charge.py": "0" * 64},  # stale hash
        tests={"test_charge.py": {"units": {"charge.py": ["charge"]}}},
    )
    tmap.save(layout.state_dir / "testmap.json")
    links = diagnosis._runtime_coverage_links(
        bug,
        ["test_charge.py"],
        source_hashes={"charge.py": runtime.identity(bug)["files"]["charge.py"]},
    )
    assert links == {}


def test_priority_e_and_f_rehearsal_skill_distillery_and_heldout_eval(bug: Path, tmp_path: Path) -> None:
    # Run a verified replay mission
    planned = runtime.plan(bug, "Repair charge.py", agent="replay", write_paths=["charge.py"], execute_local=True)
    res = runtime.execute(bug, planned, replay(bug, tmp_path))
    assert res["effective_verdict"] == "PASS"

    # Change Futures --rehearse executes the candidate diff in an isolated sandbox and upgrades confidence to observed
    fut = futures.analyze_futures(bug, res["id"], rehearse=True)
    assert fut["reran_tests"] is True
    assert fut["rehearsal"]["verdict"] == "PASS"
    assert fut["local_impact"][0]["confidence"] == "observed"
    assert fut["local_impact"][0]["rehearsal_verdict"] == "PASS"

    # Skill Distillery proposes mission-verified-playbook after a verified PASS mission
    cfg = load_config(bug)
    layout = resolve_layout(bug, cfg)
    props = optimize.proposals(bug, cfg, layout, [])
    assert any(p.id == "mission-verified-playbook" for p in props["proposals"])

    # Evaluation protocol empirically runs held-out grader, verifies negative-control abstention, and reports Wilson CIs
    assert wilson_ci_95(2, 2)[1] == 1.0
    spec = build_preregistered_study_spec()
    assert spec["comparative_lift_verdict"] == "NOT_YET_DEMONSTRATED"
    assert "single_agent_unassisted" in spec["primary_arms"]
    assert "no_tournament" in spec["ablation_arms"]

    eval_rep = run_evaluation_protocol(tmp_path / "eval2")
    assert eval_rep["mode"] == "deterministic_harness_integrity_check"
    assert eval_rep["comparative_lift_verdict"] == "NOT_YET_DEMONSTRATED"
    assert eval_rep["independent_heldout_grader"] is True
    assert eval_rep["negative_control_abstention_verified"] is True
