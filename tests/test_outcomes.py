"""Outcome-aware learning, end to end, offline.

Simulates Claude sessions through the real hook entry points (prompt →
edits → known test command → Stop). Checks that outcomes are classified,
the outcome prior is gated by a shadow evaluation, that promoting it changes
a candidate ranking, that rollback restores it, and that human instructions
are never edited. Also checks the privacy audit and forgetting.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import commit_all, run_cli, run_hook

PROMPT = "billing charge amounts are wrong for customers"


def _setup(repo: Path) -> str:
    (repo / "CLAUDE.md").write_text("# Team\n\nNever touch the payments provider config.\n")
    commit_all(repo, "team notes")
    proc = run_cli(repo, "init", "--agent", "claude", "--smart", "-q")
    assert proc.returncode == 0, proc.stderr
    facts = json.loads((repo / ".repo-ai" / "context" / "facts.json").read_text())
    test_cmds = facts["commands"].get("test") or []
    assert test_cmds, facts["commands"]
    return test_cmds[0]


def _ranked(repo: Path) -> list[str]:
    data = json.loads(run_cli(repo, "context", PROMPT, "--format", "json", "--no-cache").stdout)
    return [r["path"] for r in data["results"] if r["role"] != "test"]


def _ranked_all(repo: Path) -> list[str]:
    data = json.loads(run_cli(repo, "context", PROMPT, "--format", "json", "--no-cache").stdout)
    return [r["path"] for r in data["results"]]


def _rank(ranked: list[str], path: str) -> int:
    return ranked.index(path) if path in ranked else 99


def _session(repo: Path, sid: str, edit: str, test_cmd: str, test_ok: bool | None) -> None:
    run_hook(repo, "prompt", {"prompt": PROMPT, "session_id": sid})
    run_hook(repo, "post-edit", {"session_id": sid, "tool_name": "Edit",
                                 "tool_input": {"file_path": str(repo / edit)}})
    if test_ok is not None:
        event = "post-bash" if test_ok else "post-bash-failure"
        run_hook(repo, event, {"session_id": sid, "tool_name": "Bash",
                               "tool_input": {"command": test_cmd + " -q"}})
    run_hook(repo, "stop", {"session_id": sid})


def test_outcomes_drive_a_shadow_gated_ranking_change(pyweb: Path):
    test_cmd = _setup(pyweb)
    human = (pyweb / "CLAUDE.md").read_bytes()[:60]
    before = _ranked(pyweb)
    _all_ranked_before = _ranked_all(pyweb)
    assert len(before) >= 2
    target = before[1]  # sessions keep fixing the *second* candidate
    for i in range(9):
        _session(pyweb, f"s{i}", target, test_cmd, True)
    _session(pyweb, "s-fail", before[0], test_cmd, False)
    _session(pyweb, "s-untested", target, test_cmd, None)

    status = json.loads(run_cli(pyweb, "learn", "status", "--json").stdout)
    assert status["signals"] == "outcomes"
    assert status["outcomes"]["by_status"] == {"failed": 1, "unverified": 1, "verified": 9}

    episodes = list((pyweb / ".repo-ai" / "state" / "episodes").glob("*.json"))
    assert len(episodes) == 11
    blob = " ".join(p.read_text() for p in episodes)
    assert PROMPT not in blob and "customers" not in blob  # prompts are never stored

    shadow = json.loads(run_cli(pyweb, "learn", "shadow", "--json").stdout)
    assert shadow["sessions"] >= 3 and shadow["gain"] > 0 and shadow["promotable"], shadow

    proc = run_cli(pyweb, "learn", "approve", "ranking")
    assert proc.returncode == 0, proc.stdout
    after = _ranked(pyweb)
    full_before = _all_ranked_before
    assert after != before
    assert _rank(after, target) < _rank(before, target) or \
        _rank(_ranked_all(pyweb), target) < _rank(full_before, target)
    assert (pyweb / "CLAUDE.md").read_bytes().startswith(human)
    assert any(e["kind"] == "ranking" for e in json.loads(
        run_cli(pyweb, "learn", "history", "--json").stdout))

    assert run_cli(pyweb, "learn", "rollback", "ranking").returncode == 0
    assert _ranked(pyweb) == before


def test_promotion_is_refused_without_enough_evidence(pyweb: Path):
    test_cmd = _setup(pyweb)
    target = _ranked(pyweb)[1]
    _session(pyweb, "only-one", target, test_cmd, True)
    proc = run_cli(pyweb, "learn", "approve", "ranking")
    assert proc.returncode == 1 and "not promoted" in proc.stdout
    assert not (pyweb / ".repo-ai" / "state" / "ranking.json").exists()


def test_nothing_is_recorded_without_opt_in(pyweb: Path):
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0  # no --smart
    _session(pyweb, "x", "app/billing/charges.py", "pytest", True)
    assert not (pyweb / ".repo-ai" / "state" / "episodes").exists()
    assert not (pyweb / ".repo-ai" / "state" / "signals.jsonl").exists()


def test_friction_radar_reports_repeated_waste(pyweb: Path):
    test_cmd = _setup(pyweb)
    for i in range(3):
        _session(pyweb, f"f{i}", "app/main.py", test_cmd, None)  # never injected, never tested
    data = json.loads(run_cli(pyweb, "learn", "friction", "--json").stdout)
    kinds = {f["kind"] for f in data}
    assert "unverified" in kinds
    assert "missed-file" in kinds or any("app/main.py" in f["paths"] for f in data)


def test_privacy_audit_and_forget(pyweb: Path):
    test_cmd = _setup(pyweb)
    _session(pyweb, "p1", "app/billing/charges.py", test_cmd, True)
    proc = run_cli(pyweb, "privacy", "audit", "--json")
    assert proc.returncode == 0, proc.stdout
    stores = {s["name"]: s for s in json.loads(proc.stdout)}
    assert stores["episodes"]["exists"] and stores["episodes"]["committed"].startswith("no")
    assert stores["ownership ledger"]["committed"] != "yes"

    # a planted free-text field is caught
    ep = next((pyweb / ".repo-ai" / "state" / "episodes").glob("*.json"))
    data = json.loads(ep.read_text())
    data["prompt"] = "please fix the billing bug that customers keep reporting " * 5
    ep.write_text(json.dumps(data))
    bad = run_cli(pyweb, "privacy", "audit")
    assert bad.returncode == 1 and "unexpected field" in bad.stdout

    assert run_cli(pyweb, "learn", "forget").returncode == 0
    assert not (pyweb / ".repo-ai" / "state" / "episodes").exists()


def test_export_portable_drops_repo_specifics(pyweb: Path):
    _setup(pyweb)
    full = json.loads(run_cli(pyweb, "learn", "export").stdout)
    portable = json.loads(run_cli(pyweb, "learn", "export", "--portable").stdout)
    assert portable["portable"] and full["rules"]
    for rule in portable["rules"]:
        assert set(rule) == {"kind", "topic", "text", "confidence", "evidence_count"}


def test_uninstall_removes_outcome_stores(pyweb: Path):
    test_cmd = _setup(pyweb)
    _session(pyweb, "u1", "app/billing/charges.py", test_cmd, True)
    assert run_cli(pyweb, "uninstall", "-y").returncode == 0
    assert not (pyweb / ".repo-ai").exists()


def test_failing_command_is_counterevidence_for_an_auto_applied_rule(pyweb: Path):
    _setup(pyweb)
    rules = {r["id"]: r for r in json.loads(run_cli(pyweb, "learn", "--json").stdout)["rules"]}
    lint = next(r for r in rules.values() if "`make lint`" in r["text"] and r["status"] == "active")
    assert "make lint" in (pyweb / "CLAUDE.md").read_text()
    for sid in ("c1", "c2"):
        run_hook(pyweb, "post-bash-failure", {"session_id": sid, "tool_name": "Bash",
                                              "tool_input": {"command": "make lint"}})
        run_hook(pyweb, "stop", {"session_id": sid})
    assert run_cli(pyweb, "update", "-q").returncode == 0
    rules = {r["id"]: r for r in json.loads(run_cli(pyweb, "learn", "--json").stdout)["rules"]}
    assert rules[lint["id"]]["status"] == "proposed"
    assert "counterevidence" in rules[lint["id"]]["note"]
    text = (pyweb / "CLAUDE.md").read_text()
    block = text[text.index("<!-- BEGIN repo-ai:claude"):text.index("<!-- END repo-ai:claude")]
    assert "make lint" not in block  # a demoted rule is no longer presented, as a rule or a check
    assert text.startswith("# Team\n\nNever touch the payments provider config.\n")


def test_directory_edit_payloads_are_ignored(pyweb: Path):
    _setup(pyweb)
    for target in (str(pyweb), str(pyweb / "app")):
        run_hook(pyweb, "post-edit", {"session_id": "d1", "tool_name": "Edit",
                                      "tool_input": {"file_path": target}})
    run_hook(pyweb, "stop", {"session_id": "d1"})
    episodes = list((pyweb / ".repo-ai" / "state" / "episodes").glob("*.json"))
    assert all(json.loads(p.read_text())["edits"] == [] for p in episodes)
