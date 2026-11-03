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


def _cli(tmp_path: Path, *, stance: str = "ACCEPT", investigator_writes: bool = False,
         investigator_cost: float = 0.0) -> Path:
    body = _BODY.format(stance=stance, investigator_writes=investigator_writes)
    if investigator_cost:  # the investigator reports a cost; every other process $0
        body = body.replace("'cost_usd': 0.0", "'cost_usd': (" + repr(investigator_cost) + " if role == 'investigator' else 0.0)")
    return _make_fake_cli(tmp_path, "claude", body)


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
    cli = _cli(tmp_path, investigator_cost=0.25)
    p = runtime.plan(bug, "Fix duplicate payment charge when retry uncertain again", agent="claude",
                     write_paths=["charge.py"], execute_local=True, roles=["investigator"])
    res = runtime.execute(bug, p, None, provider_executable=cli)
    assert res["effective_verdict"] != "PASS"
    # the investigator's 0.25 is counted (it is over the simulated run's $0 ceiling, so the role itself FAILED)
    assert res["spend"] == {"usd_observed_total": 0.25, "any_cost_unknown": False}, res.get("spend")


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



def test_a_live_continuation_is_refused_when_role_spend_used_up_the_ceiling(tmp_path, monkeypatch) -> None:
    """The wiring: the continuation budget reads the role-inclusive total (main read only the implementer's cost and
    would have allowed $0.20 more here). Refused before any provider starts."""
    from test_mission_partial_handoff import FIX_DISCOUNT, _provider
    from test_mission_partial_handoff import shop as shop_fixture
    shop = shop_fixture.__wrapped__(tmp_path)
    planned = runtime.plan(shop, "Make pricing.py compute percentage discounts and tax correctly", agent="claude",
                           write_paths=["pricing.py"], execute_local=True)
    first = runtime.execute(shop, planned, None, provider_executable=_provider(tmp_path, "claude", FIX_DISCOUNT))
    capsule = tmp_path / "capsule.json"
    capsule.write_text(json.dumps(runtime.handoff(shop, first["id"], target_provider="claude")))
    real = runtime.status

    def as_live(root, mid, **kw):  # controlled injection: the first mission as a live run with roles
        state = real(root, mid, **kw)
        if mid == first["id"]:
            state = {**state, "provider": {**state["provider"], "simulated": False, "cost_usd": 0.10,
                                           "cost_status": "OBSERVED"},
                     "spend": {"usd_observed_total": 0.50, "any_cost_unknown": False},
                     "continuation_budget": {"ceiling_usd": 0.50}}  # the contract (and its digest) unchanged
        return state
    monkeypatch.setattr(runtime, "status", as_live)
    monkeypatch.setattr("repo_ai.providers.adapters.run_provider", lambda *a, **k: pytest.fail("no provider may start"))
    with pytest.raises(ValueError, match="exceeds remaining prior cost budget"):
        runtime.continue_from_handoff(shop, capsule, agent="claude", allow_live=True, max_cost_usd=0.20)
