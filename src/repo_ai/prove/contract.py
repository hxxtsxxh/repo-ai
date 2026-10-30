"""The passport's embedded evidence record, by Session A's contract
(`docs/PROOF-EVIDENCE-CONTRACT.md`, schema ``repo-ai.proof-evidence/1``,
contract version 1.0).

The passport never copies the record's fields into its own namespace: the
record sits under ``passport["evidence"]``, whole, and a consumer decides on
its ``claim.level``. ProofLab's own verdict is consistent with it: a passport
is ``supported`` only when the record reaches at least ``behavior_observed``.

Levels for a fix (the base fails, the candidate passes):

* ``supported_by_controlled_comparison``: the base fails and the candidate
  passes, at least twice each, all conclusive and in agreement. The control,
  an independent copy of the base, fails the same way. The scenario is
  independent of the change, and the oracle is the same on both sides;
* ``behavior_observed``: the candidate passes the scenario, with its oracle
  recorded. This is the level when the scenario is part of the change;
* ``test_passed``: the cap of §6 while verify's fingerprint has known gaps.
  These are a submodule, a flagged index entry, a rename or a CRLF file in the
  change, or a virtualenv in a host sandbox;
* ``not_established``: anything else, and anything stale or with a changed
  source tree.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__

SCHEMA = "repo-ai.proof-evidence/1"
CONTRACT_VERSION = "1.1"
LEVELS = ("not_established", "test_passed", "behavior_observed", "regression_reproduced",
          "supported_by_controlled_comparison")
MINIMUM_NOT_ESTABLISHED = ["other inputs and scenarios", "other environments", "the full test suite",
                           "correctness of the change"]


def observation(obs: dict[str, Any]) -> dict[str, Any]:
    """One process of ProofLab (`experiment.run_once`) as a contract
    observation (§4): the report outranks the exit status, only tests count,
    a time-out is never a failure."""
    outcomes = {t: o for t, o in (obs.get("outcomes") or {}).items()
                if t not in set(obs.get("load_failures") or [])}  # §4 rule 2: a module that failed to load is no test
    ran = [o for o in outcomes.values() if o != "skip"]
    failed = sum(1 for o in ran if o == "fail")
    if not obs.get("trusted"):
        state = "timeout" if obs.get("timed_out") else "incomplete"
    elif not ran:
        state = "skipped"
    else:
        state = "fail" if failed else "pass"
    rep = obs.get("report") or {}
    return {"state": state, "conclusive": state in {"pass", "fail"}, "exit_code": obs.get("exit_code"),
            "timed_out": bool(obs.get("timed_out")), "duration_s": float(obs.get("seconds") or 0.0), "processes": 1,
            "tests": {"ran": len(ran), "passed": len(ran) - failed, "failed": failed,
                      "skipped": len(outcomes) - len(ran),
                      "expected_failures": int(obs.get("expected_failures") or 0)},
            "failing_tests": sorted(t for t, o in outcomes.items() if o == "fail")[:200],
            "hung_tests": list(obs.get("hung") or [])[:200],
            "report": {"present": bool(rep.get("present")), "complete": bool(rep.get("complete")),
                       "trusted": bool(obs.get("trusted")), "reason": str(obs.get("reason") or "")},
            "stdout_sha256": str(obs.get("stdout_sha256") or ""), "stderr_sha256": str(obs.get("stderr_sha256") or "")}


# verify's fingerprint covers what the copy reads since #41 (D9, renames) and #43 (D5-D8: submodules,
# flagged index entries, CRLF, the virtualenv's packages in the environment key): §6's cap no longer applies
ENGINE_COVERS_D5_D9 = True
# node's default discovery lists TypeScript tests since #45 (D10): the 1.1 cap on it no longer applies either;
# it is a separate flag so that lifting one cap never lifts the other
ENGINE_COVERS_D10 = True


def cap_conditions(root: Path, change, python: str, host_python: bool) -> list[str]:
    """§6: the conditions under which verify's fingerprint may miss bytes the
    copy reads (D5-D9). Each caps the level at `test_passed`, until the engine
    includes the fixes (`ENGINE_COVERS_D5_D9`)."""
    out: list[str] = []
    if not ENGINE_COVERS_D10 and any(f.path.endswith((".test.ts", ".test.mts", ".test.cts", ".spec.ts"))
                                     for f in change.files):
        out.append("TypeScript tests that only node's default discovery lists (D10)")
    if ENGINE_COVERS_D5_D9:
        return out

    def git(*args: str) -> str:
        res = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60, check=False,
                             stdin=subprocess.DEVNULL)
        return res.stdout.decode("utf-8", "replace")
    if (root / ".gitmodules").is_file() or any(line.startswith("160000 ") for line in git("ls-files", "-s").splitlines()):
        out.append("submodule content not fingerprinted (D5)")
    flags = [line[:1] for line in git("ls-files", "-v").splitlines() if line[:1]]
    if any(f.islower() or f == "S" for f in flags):
        out.append("a tracked file is flagged skip-worktree or assume-unchanged (D6)")
    if any(f.status == "renamed" for f in change.files):
        out.append("a rename is in the change (D9)")
    for f in change.files:
        if f.status == "deleted":
            continue
        try:
            with (root / f.path).open("rb") as fh:
                if b"\r\n" in fh.read(4 * 1024 * 1024):
                    out.append(f"a CRLF file is in the change (D7): {f.path}")
                    break
        except OSError:
            continue
    if host_python and (Path(python).parent.parent / "pyvenv.cfg").is_file():
        out.append("a host-sandbox Python run uses a virtualenv (D8)")
    return out


def _agree(obs: list[dict[str, Any]]) -> bool:
    return len({(o["state"], tuple(o["failing_tests"])) for o in obs}) <= 1


def level(sides: dict[str, list[dict[str, Any]]], *, independent: bool, oracle_same: bool, integrity_ok: bool,
          caps: list[str], judged: tuple[str, str] = ("reproduced", "passed"),
          subject_declared: bool = True) -> tuple[str, list[str]]:
    """The strongest level whose every condition holds (§2), and why the
    next one does not. `judged`: ProofLab's own judgement of the base and the
    candidate (targets, skips, missing tests, load failures, the canary): the
    record never says more than it."""
    why: list[str] = []
    base, cand, control = sides.get("base") or [], sides.get("candidate") or [], sides.get("control") or []
    base_judged, cand_judged = judged
    if not integrity_ok:
        return "not_established", ["the source tree changed during the run"]
    if cand_judged != "passed":
        return "not_established", [f"ProofLab judged the candidate {cand_judged}"]
    if not cand or not all(o["state"] == "pass" and o["conclusive"] for o in cand):
        return "not_established", ["the candidate did not pass conclusively"]
    if not _agree(cand) or (base and not _agree(base)) or (control and not _agree(control)) or (
            base and control and base[0]["state"] in {"pass", "fail"} and control[0]["state"] in {"pass", "fail"}
            and (base[0]["state"], base[0]["failing_tests"]) != (control[0]["state"], control[0]["failing_tests"])):
        return "not_established", ["flaky: repeats disagreed"]  # §7, the control being a side
    if caps:
        return "test_passed", caps
    best = "behavior_observed"
    if base_judged != "reproduced":
        why.append(f"ProofLab judged the base {base_judged}")
    elif len(base) < 2 or len(cand) < 2 or len(control) < 2:
        why.append("fewer than 2 conclusive observations on a side (the control is a side)")
    elif not all(o["conclusive"] and o["state"] == "fail" for o in base) or not _agree(base):
        why.append("the base did not fail conclusively and consistently")
    elif not independent:
        why.append("the scenario is not independent of the change")
    elif not oracle_same:
        why.append("the oracle differs between the sides")
    elif not subject_declared:
        why.append("the code under test was inferred, not declared (`prove pin --subject`)")
    elif not all(o["conclusive"] and o["state"] == "fail"
                 and o["failing_tests"] == base[0]["failing_tests"] for o in control):
        why.append("the negative control did not reproduce the base observation")
    else:
        best = "supported_by_controlled_comparison"
    return best, why


def independent_of_change(scenario: dict[str, Any], pinned_from_agent: bool,
                          support: list[dict[str, Any]] | None = None) -> bool:
    """§3: bytes that did not come from the candidate's diff, pinned by
    someone other than an agent shell (an agent that writes the candidate can
    commit its test first, or write an outside file, too): a blob identical at
    the base, or a file kept outside the repository. Every pinned support file
    must be identical at the base as well."""
    if pinned_from_agent:
        return False
    kind = (scenario.get("provenance") or {}).get("kind")
    # an outside file counts only while the candidate's tree does not hold it: in the tree, it came with the change
    own = (kind == "file" and scenario.get("in_candidate_tree") == "absent") or (
        kind == "git" and scenario.get("in_base_tree") == "identical")
    return own and all(s.get("in_base_tree") == "identical" for s in support or [])


def source(scenario: dict[str, Any]) -> str:
    prov = scenario.get("provenance") or {}
    if prov.get("kind") == "git":
        return f"blob:{str(prov.get('commit'))[:12]}:{scenario['path']}"
    if prov.get("kind") == "file":
        return f"external:{scenario['sha256']}"
    return f"worktree:{scenario['path']}"


def record(pp: dict[str, Any], *, sides_raw: dict[str, list[dict[str, Any]]], runner_identity: dict[str, Any],
           argv: list[str], env_key: str, caps: list[str], full_suite_passed: bool, integrity_ok: bool,
           tree: str, head: str) -> dict[str, Any]:
    """The evidence record for one experiment."""
    sides = {k: [observation(o) for o in v] for k, v in sides_raw.items() if v}
    scen = pp["scenario"]
    oracle_info = (pp.get("conditions") or {}).get("oracle") or {}
    # data the change edits may be the oracle itself: never a controlled comparison then
    oracle_same = bool(oracle_info.get("identical")) and not oracle_info.get("changed_data")
    agent = bool((pp["claim"].get("pinned") or {}).get("agent_shell"))
    indep = independent_of_change(scen, agent, pp.get("support"))
    obs = pp.get("observations") or {}
    judged = (str((obs.get("baseline") or {}).get("state") or "not-run"),
              str((obs.get("candidate") or {}).get("state") or "not-run"))
    lvl, why = level(sides, independent=indep, oracle_same=oracle_same, integrity_ok=integrity_ok, caps=caps,
                     judged=judged, subject_declared=bool((pp.get("subject") or {}).get("declared")))
    not_est = [x for x in MINIMUM_NOT_ESTABLISHED if not (x == "the full test suite" and full_suite_passed)]
    not_est += [*caps, *why]
    # ProofLab's own standing travels with every record it writes, whatever the level
    from .passport import EXPERIMENTAL
    not_est.append("ProofLab is experimental and not certified")
    not_est += [f"known false proof (open): {k['id']}" for k in EXPERIMENTAL["known_false_proofs"]]
    if not indep:
        not_est.append("the scenario is not independent of the change")
    claim_spec = pp["claim"]
    oracle_spec = {"targets": claim_spec.get("targets") or [], "expect_failure": claim_spec.get("expect_failure"),
                   "scenario": scen["sha256"], "inputs": ((pp.get("conditions") or {}).get("oracle") or {}).get(
                       "candidate_sha256")}
    text = {"supported_by_controlled_comparison": "the pinned scenario fails at the base and passes with this change, "
                                                  "and an independent base copy fails it the same way",
            "behavior_observed": "the pinned scenario passes with this change",
            "test_passed": "the tests of the pinned scenario passed with this change",
            "not_established": "nothing is claimed"}.get(lvl, "")
    return {
        "schema": SCHEMA, "contract_version": CONTRACT_VERSION,
        "base": {"commit": pp["baseline"]["commit"], "tree": tree},
        "candidate": {"fingerprint": pp["candidate"]["fingerprint"], "head": head},
        "scenario": {"sha256": scen["sha256"], "source": source(scen), "independent_of_change": indep,
                     "pinned_from": "agent" if agent else "terminal"},
        "command": {"runner": runner_identity, "argv": argv},
        "oracle": {"kind": "test-ids", "spec": "every test of the scenario passes on the candidate; at the base, the "
                                               "targeted tests fail" + (" as pinned" if oracle_spec["expect_failure"]
                                                                        else ""),
                   "sha256": hashlib.sha256(json.dumps(oracle_spec, sort_keys=True).encode()).hexdigest()},
        "sides": {k: {"observations": v} for k, v in sides.items()},
        "integrity": {"source_tree_unchanged": integrity_ok, "workspace_disposable": True,
                      "sandbox": {"backend": (pp.get("environment") or {}).get("backend", "unknown"), "network": False}},
        "freshness": {"state": "fresh" if integrity_ok else "unknown",
                      "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                      "environment_key": env_key},
        "claim": {"level": lvl, "text": text, "not_established": list(dict.fromkeys(not_est))},
        "reproduction": {"engine": engine_identity(),
                         "environment": {**{k: v for k, v in (pp.get("environment") or {}).items()
                                            if k in {"image", "image_digest", "python", "node", "os", "machine"}},
                                         "platform": (pp.get("environment") or {}).get("platform") or ""},
                         "commands": [c for c in pp.get("reproduce") or [] if c.startswith("repo-ai ")]},
    }


def engine_identity() -> dict[str, Any]:
    """§8: which repo-ai produced the record: the commit of a source checkout,
    else the sha256 of the installed distribution's RECORD (its file list
    with every file's hash, so two installs with the same RECORD run the same
    code)."""
    out: dict[str, Any] = {"version": __version__}
    pkg = Path(__file__).resolve().parents[1]
    res = subprocess.run(["git", "-C", str(pkg), "rev-parse", "--verify", "--quiet", "HEAD"], capture_output=True,
                         text=True, timeout=20, check=False, stdin=subprocess.DEVNULL)
    top = subprocess.run(["git", "-C", str(pkg), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         timeout=20, check=False, stdin=subprocess.DEVNULL).stdout.strip()
    if res.returncode == 0 and top and (Path(top) / "src" / "repo_ai").resolve() == pkg:
        out["commit"] = res.stdout.strip()
        return out
    try:
        from importlib import metadata
        dist = metadata.distribution("repo-ai")
        rec = dist.read_text("RECORD") or ""
        out["installed_record_sha256"] = hashlib.sha256(rec.encode()).hexdigest() if rec else None
        # installed from a wheel file: pip records the archive's hash (PEP 610)
        info = (json.loads(dist.read_text("direct_url.json") or "{}") or {}).get("archive_info") or {}
        digest = (info.get("hashes") or {}).get("sha256") or (
            str(info.get("hash") or "").partition("sha256=")[2] if str(info.get("hash") or "").startswith("sha256=")
            else "")
        if digest:
            out["wheel_sha256"] = str(digest)[:64]
    except Exception:  # noqa: BLE001 - not installed as a distribution
        out.setdefault("installed_record_sha256", None)
    return out


def fresh_view(rec: dict[str, Any], state: str) -> dict[str, Any]:
    """The record as a consumer must show it now (§6): above
    `not_established` only while fresh. The level it held when recorded is
    kept as `claim.recorded_level`."""
    out = json.loads(json.dumps(rec))
    out["freshness"] = {**out.get("freshness", {}), "state": state,
                        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    claim = out.setdefault("claim", {})
    if state != "fresh" and claim.get("level", "not_established") != "not_established":
        claim["recorded_level"] = claim["level"]
        claim["level"], claim["text"] = "not_established", "nothing is claimed"
        claim["not_established"] = [*claim.get("not_established", []), f"the record is {state} (§6)"]
    return out
