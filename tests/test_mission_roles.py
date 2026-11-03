"""Opt-in provider roles: separate read-only processes around the single writer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_ai.mission import runtime
from test_provider_runtime import _make_fake_cli
from test_provider_runtime import bug as bug  # noqa: F401  (fixture)

_BODY = """\
import json, os, pathlib, sys
prompt = sys.argv[-1]
ws = pathlib.Path(os.environ['REPO_AI_WORKSPACE'])
if 'Diagnose' in prompt:
    role = 'investigator'
    if {investigator_writes!r}:
        (ws / 'scratch.txt').write_text('x')
    text = 'Root cause: charge() multiplies by retries+1 in charge.py.'
elif 'skeptical reviewer' in prompt:
    role = 'adversary'
    text = 'No counterexample found.\\nSTANCE: {stance}'
else:
    role = 'implementer'
    (ws / 'charge.py').write_text('def charge(amount, retries):\\n    return amount\\n')
    text = 'fixed'
seen = json.dumps({{'role': role, 'cwd': str(ws), 'saw_notes': 'NOTES FROM A SEPARATE' in prompt}})
print(json.dumps({{'type': 'result', 'session_id': 's-' + role, 'cost_usd': 0.0, 'result': seen + chr(10) + text}}))
"""


def _cli(tmp_path: Path, *, stance: str = "ACCEPT", investigator_writes: bool = False) -> Path:
    return _make_fake_cli(tmp_path, "claude", _BODY.format(stance=stance, investigator_writes=investigator_writes))


def _seen(res: dict) -> dict[str, dict]:
    """What each process reported about itself, taken from the recorded events."""
    out = {}
    for role, text in (res.get("role_reports") or {}).items():
        out[role] = json.loads(text.splitlines()[0])
    out["implementer"] = json.loads(res["provider"]["events"]["report"].splitlines()[0])
    return out


def test_trivial_change_refuses_roles_and_spawns_no_extra_process(bug: Path, tmp_path: Path) -> None:  # noqa: F811
    p = runtime.plan(bug, "Fix typo in comment in charge.py", agent="claude", write_paths=["charge.py"],
                     execute_local=True, roles=["investigator", "adversary"])
    assert p["contract"].get("roles") is None
    assert {n["id"] for n in p["dag"]["nodes"]} == {"context", "baseline", "edit", "candidate", "review"}
    assert len(p["orchestration"]["specialists_refused"]) >= 2


def test_replay_agent_cannot_have_provider_roles(bug: Path) -> None:  # noqa: F811
    p = runtime.plan(bug, "Fix duplicate payment charge", agent="replay", write_paths=["charge.py"],
                     execute_local=True, roles=["investigator"])
    assert p["contract"].get("roles") is None
    assert any("needs a provider process" in r for r in p["orchestration"]["specialists_refused"])


def test_investigator_and_adversary_are_separate_processes_and_advisory(bug: Path, tmp_path: Path) -> None:  # noqa: F811
    cli = _cli(tmp_path, stance="OBJECT")
    p = runtime.plan(bug, "Fix duplicate payment charge when retry uncertain", agent="claude",
                     write_paths=["charge.py"], execute_local=True, roles=["investigator", "adversary"])
    nodes = {n["id"]: n for n in p["dag"]["nodes"]}
    assert nodes["investigator"]["owner"] == "investigator" and nodes["adversary"]["owner"] == "adversary"
    assert set(nodes["edit"]["depends_on"]) == {"baseline", "investigator"}
    assert nodes["adversary"]["depends_on"] == ["candidate"]
    res = runtime.execute(bug, p, None, provider_executable=cli)
    assert res["effective_verdict"] == "PASS", res["passport"]
    seen = _seen(res)
    assert {k: v["role"] for k, v in seen.items()} == {"investigator": "investigator", "adversary": "adversary",
                                                      "implementer": "implementer"}
    assert len({v["cwd"] for v in seen.values()}) == 3, "each role needs its own checkout"
    assert seen["implementer"]["saw_notes"] is True
    assert seen["investigator"]["saw_notes"] is False and seen["adversary"]["saw_notes"] is False
    assert res["roles"]["adversary"]["stance"] == "OBJECT"
    assert any("adversary objected" in u for u in res["passport"]["untested"])
    assert res["roles"]["investigator"]["workspace_unchanged"] is True
    # advisory: an objection neither flips the verdict nor touches the source before apply
    assert "return amount * (retries + 1)" in (bug / "charge.py").read_text()


def test_role_that_writes_to_its_checkout_is_discarded_not_trusted(bug: Path, tmp_path: Path) -> None:  # noqa: F811
    cli = _cli(tmp_path, investigator_writes=True)
    p = runtime.plan(bug, "Fix duplicate payment charge when retry uncertain", agent="claude",
                     write_paths=["charge.py"], execute_local=True, roles=["investigator"])
    res = runtime.execute(bug, p, None, provider_executable=cli)
    inv = res["roles"]["investigator"]
    assert inv["status"] == "FAILED" and inv["workspace_unchanged"] is False
    assert res["provider"]["events"]["report"].splitlines()[0]
    assert json.loads(res["provider"]["events"]["report"].splitlines()[0])["saw_notes"] is False, \
        "discarded report must not reach the implementer"
    assert res["effective_verdict"] == "PASS"


def test_unknown_role_is_rejected() -> None:
    from repo_ai.mission.contracts import IntentContract
    with pytest.raises(ValueError, match="roles must be"):
        IntentContract("x", "r", "b", ["python -m pytest"], [], roles=["committee"]).validate()


def test_a_failed_mission_with_roles_records_what_they_spent(bug: Path, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    """Queue row 26: the record kept role spend only on the completed path; a failure after the investigator ran
    dropped it, so a continuation's budget could not count it."""
    from repo_ai.mission import verification
    real = verification.observe
    calls = {"n": 0}

    def observe(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # the candidate observation, after the investigator and the implementer ran
            raise ValueError("observation failed (injected)")
        return real(*a, **k)
    monkeypatch.setattr(verification, "observe", observe)
    cli = _cli(tmp_path)
    p = runtime.plan(bug, "Fix duplicate payment charge when retry uncertain again", agent="claude",
                     write_paths=["charge.py"], execute_local=True, roles=["investigator"])
    res = runtime.execute(bug, p, None, provider_executable=cli)
    assert res["effective_verdict"] != "PASS"
    assert res["spend"] == {"usd_observed_total": 0.0, "any_cost_unknown": False}, res.get("spend")


def test_a_continuation_counts_role_spend_against_the_remaining_budget() -> None:
    live = {"simulated": False, "cost_usd": 0.10, "cost_status": "OBSERVED"}
    assert runtime._prior_spend({"provider": live}) == (0.10, False)
    # the investigator spent 0.30 before the implementer's 0.10: 0.40 is gone, not 0.10
    assert runtime._prior_spend({"provider": live, "spend": {"usd_observed_total": 0.40,
                                                             "any_cost_unknown": False}}) == (0.40, False)
    assert runtime._prior_spend({"provider": live, "spend": {"usd_observed_total": 0.40,
                                                             "any_cost_unknown": True}})[1] is True
    assert runtime._prior_spend({"provider": {**live, "cost_status": "UNKNOWN"}})[1] is True
    assert runtime._prior_spend({"provider": {"simulated": True, "cost_usd": 0.5}}) == (0.0, False)
