"""The verification passport: one experiment's record, its verdict, what it
does not establish, how to reproduce it, and whether it still describes the
working tree.

**Schema** ``repo-ai.proof-passport/1``. Fields are only ever added within
it; a consumer ignores fields it does not know.

**Verdict** (``verdict.state``): exactly one of

* ``supported``: the base shows the targeted failure, the candidate passes
  every test of the same scenario bytes under the same conditions, the
  base's own versions of edited tests still pass, verify finds no new
  failure, and the source tree was untouched;
* ``candidate-failed``, ``baseline-not-reproduced``, ``regressions-detected``,
  ``incomplete``, ``environment-unavailable``, ``scenario-changed``,
  ``conditions-differ``: the claim is not established.

Only ``supported`` is a supported claim (``verdict.supported`` is true for it
alone). **Freshness** is not stored: ``status`` computes it, and a passport for
another working tree, base, or pin is ``stale``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..verify import changes as ch
from . import claim as cl

SCHEMA = "repo-ai.proof-passport/1"
KEEP = 20
STATES = ("supported", "candidate-failed", "baseline-not-reproduced", "regressions-detected", "incomplete",
          "environment-unavailable", "scenario-changed", "conditions-differ")
_PRE_RUN_ORDER = ("scenario-changed", "conditions-differ", "environment-unavailable")
HEADLINES = {
    "supported": "CLAIM SUPPORTED (EXPERIMENTAL, not certified) for the pinned scenario: the original code fails "
                 "it, the candidate passes it, and no regression was detected",
    "candidate-failed": "CLAIM NOT ESTABLISHED: the candidate fails the pinned scenario",
    "baseline-not-reproduced": "CLAIM NOT ESTABLISHED: the original code does not show the targeted failure",
    "regressions-detected": "CLAIM NOT ESTABLISHED: the candidate breaks existing behaviour",
    "incomplete": "CLAIM NOT ESTABLISHED: the experiment is incomplete",
    "environment-unavailable": "CLAIM NOT ESTABLISHED: the experiment could not run here",
    "scenario-changed": "CLAIM NOT ESTABLISHED: the acceptance scenario is not the pinned one",
    "conditions-differ": "CLAIM NOT ESTABLISHED: the scenario would not run under the same conditions at both revisions",
}


# ProofLab's standing, in every passport and every export of one: experimental, not certified, and the false
# proofs known to be open. A consumer must not read a `supported` verdict without it.
EXPERIMENTAL: dict[str, Any] = {
    "status": "experimental",
    "certified": False,
    "certification": "not certified: it did not qualify in its independent evaluation, and its sealed "
                     "certification has not run",
    "stable_claims": "excluded: ProofLab is not part of repo-ai's stable verification claims; a passport is a local "
                     "experiment record, not a certificate",
    "known_false_proofs": [{
        "id": "always-equal-class",
        "open": True,
        "summary": "a value of a class that already compares equal to anything at the base (an __eq__ that always "
                   "returns True), returned by the change, passes a comparison with a literal: ProofLab reports the "
                   "claim supported although nothing is fixed",
        "regression_test": "tests/test_prove_review8_eq_regress.py::test_e3_with_the_subject_declared (strict xfail)",
    }, {
        "id": "swallowed-assertion",
        "open": True,
        "summary": "a context manager of the code under test, edited to swallow exceptions, hides the scenario's failing "
                   "assertion: ProofLab reports the claim supported although nothing is fixed",
        "regression_test": "tests/test_sa_redteam_scope_903984a.py::test_1d_an_assertion_swallowed_by_an_edited_context_"
                           "manager (strict xfail; issue #59)",
    }, {
        "id": "importorskip-zero-entry-points",
        "open": True,
        "summary": "a scenario that imports through pytest.importorskip has no entry point ProofLab follows, so a change "
                   "that only alters the scenario's input is reported supported",
        "regression_test": "tests/test_sa_redteam_scope_903984a.py::test_1e_importorskip_gives_zero_entry_points "
                           "(strict xfail; issue #59)",
    }],
    "unexecuted_paths": "a code review lists further paths that may give a false supported verdict (issue #59): "
                        "star imports from test helpers, values through helper classes, enum or exception aliases, "
                        "non-.py or unparseable scenarios, indirect comparison methods, analysis groups past 60 files",
}


def experimental_notes() -> list[str]:
    """The standing as sentences, first in every passport's limitations."""
    out = ["EXPERIMENTAL, NOT CERTIFIED: ProofLab is experimental and opt-in, its independent certification is "
           "blocked, and it is not part of repo-ai's stable verification claims. A supported verdict is a local "
           "experiment record, not a proof."]
    out += [f"KNOWN FALSE PROOF (open, {k['id']}): {k['summary']}." for k in EXPERIMENTAL["known_false_proofs"]]
    return out


def new(record: dict[str, Any], pre: dict[str, Any], base: str, change: ch.Change) -> dict[str, Any]:
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    claim_part = record.get("claim") or {}
    return {
        "schema": SCHEMA, "created": created, "repo_ai_version": __version__,
        "experimental": json.loads(json.dumps(EXPERIMENTAL)),
        "claim": {"id": record["id"], "text": claim_part.get("text"), "sha256": claim_part.get("sha256"),
                  "redacted": bool(claim_part.get("redacted")), "settings": record.get("settings"),
                  "targets": record.get("targets") or [], "expect_failure": record.get("expect_failure"),
                  "supersedes": record.get("supersedes") or [],
                  "pinned": {"created": record.get("created"), **(record.get("pinned_by") or {})},
                  "replaced": len(record.get("history") or []),
                  "earlier_scenarios": [h.get("scenario_sha256") for h in record.get("history") or []][-5:]},
        "scenario": pre["scenario"], "support": pre["support"],
        "baseline": {"revision": base, "commit": change.base_commit},
        "candidate": {"kind": "working tree", "fingerprint": change.fingerprint,
                      "changed_files": change.paths()[:200], "changed_files_total": len(change.files),
                      "withheld_credential_like": len(change.withheld)},
        "conditions": {"runner": pre["runner"], "command": pre["command"], "oracle": pre["oracle"],
                       "same_sandbox_and_interpreter": True},
        "edited_tests_planned": pre["edited_tests"],
        "subject": pre.get("subject") or {},
        "environment": {"repo_ai": __version__},
        "observations": {"baseline": None, "candidate": None},
        "edited_tests": None, "regressions": None, "integrity": None,
    }


def decide(problems: list[dict[str, str]] | None, baseline: dict | None, candidate: dict | None, edited: dict | None,
           regressions: dict | None, integrity: dict | None, abstain: list[str] | None = None) -> dict[str, Any]:
    """The verdict. `abstain`: reasons the scenario may not check the change's
    behaviour at all (`dataflow.findings`); a claim with any is never
    supported."""
    reasons: list[str] = []
    if problems:
        state = next(s for s in _PRE_RUN_ORDER + STATES if any(p["state"] == s for p in problems))
        reasons = [p["why"] for p in problems]
        return {"state": state, "supported": False, "headline": HEADLINES[state], "reasons": reasons}
    assert baseline is not None and candidate is not None and edited is not None and regressions is not None
    parts = [("baseline", baseline), ("candidate", candidate), ("regressions", regressions)]
    for name, part in parts:
        if part.get("state") not in {"reproduced", "passed", "none-detected"}:
            reasons.append(f"{name}: {part.get('why', part.get('state'))}")
    if edited.get("state") == "incomplete" and edited.get("why"):
        reasons.append(f"subject-only check: {edited['why']}")
    for row in edited.get("files") or []:
        if row["state"] == "detected":
            reasons.append(f"edited tests: the base's own {row['path']} fails at the candidate: "
                           + ", ".join(row["new_failures"][:3]))
        elif row["state"] == "incomplete":
            reasons.append(f"edited tests: {row['path']} could not be compared: {row.get('why', '')}")
    reasons += [f"scenario: {a}" for a in abstain or []]
    if integrity is not None and not integrity.get("unchanged"):
        state = "incomplete"
        reasons.insert(0, "the source tree changed during the experiment: " + "; ".join(
            (integrity.get("changes") or [])[:3]))
    elif candidate["state"] == "failed":
        state = "candidate-failed"
    elif baseline["state"] in {"not-reproduced", "load-failure"}:
        state = "baseline-not-reproduced"
    elif regressions["state"] == "detected" or edited["state"] == "detected":
        state = "regressions-detected"
    elif reasons or edited["state"] == "incomplete" or abstain:
        state = "incomplete"
    else:
        state = "supported"
    return {"state": state, "supported": state == "supported", "headline": HEADLINES[state], "reasons": reasons}


def _align(verdict: dict[str, Any], rec: dict[str, Any]) -> None:
    """ProofLab's verdict never says more than the evidence record's level
    (Session A's contract): `supported` needs `behavior_observed` or above,
    and only a controlled comparison may say the change turned the failure
    into a pass."""
    lvl = rec["claim"]["level"]
    verdict["level"] = lvl
    if verdict["state"] != "supported":
        # a claim that is not established supports nothing, whatever the scenario alone showed (Session A's S1,
        # S2d, S17): the record says what the scenario observed in `scenario_level`, and claims nothing
        rec["claim"]["scenario_level"] = lvl
        rec["claim"]["level"] = verdict["level"] = "not_established"
        rec["claim"]["text"] = "nothing is claimed"
        rec["claim"]["not_established"].append(
            f"the ProofLab claim: {verdict['state']}" + (f" ({verdict['reasons'][0][:200]})" if verdict["reasons"]
                                                         else ""))
        return
    if lvl not in {"behavior_observed", "supported_by_controlled_comparison"}:
        verdict.update(state="incomplete", supported=False, headline=HEADLINES["incomplete"])
        verdict["reasons"] = [f"the evidence contract caps this record at {lvl}: "
                              + "; ".join(x for x in rec["claim"]["not_established"]
                                          if x not in {"other inputs and scenarios", "other environments",
                                                       "the full test suite", "correctness of the change"})]
    elif lvl == "behavior_observed":
        verdict["headline"] = ("CLAIM SUPPORTED (EXPERIMENTAL, not certified) for the pinned scenario: the candidate "
                               "passes it and the original code failed it, with no regression detected. The scenario is not independent of the change, "
                               "so this is not a controlled comparison (evidence level behavior_observed)")
    else:
        verdict["headline"] = ("CLAIM SUPPORTED (EXPERIMENTAL, not certified) by a controlled comparison for the pinned "
                               "scenario: an independent "
                               "scenario fails on the original code (twice, and on a separate control copy) and passes "
                               "with the change, and no regression was detected")


def limitations(pp: dict[str, Any], repeat: int) -> tuple[list[str], list[str]]:
    """What the passport does not establish, and what was never tested."""
    lim = [*experimental_notes(),"A passing scenario shows the claim only for what this scenario checks; it is not a proof that the "
           "change is correct for other inputs, states or callers.",
           "ProofLab checks for mistakes, not for a hostile candidate: code under test runs in the scenario's own "
           "process and could defeat any check made there. This passport is also a local record that anyone who can "
           "write .repo-ai/state could forge, so a reviewer should run `repo-ai prove run` again."]
    claim, scen = pp["claim"], pp["scenario"]
    prov = scen.get("provenance") or {}
    agent = bool((claim.get("pinned") or {}).get("agent_shell"))
    if prov.get("kind") == "git":
        lim.append(f"The scenario is blob {str(prov.get('blob'))[:12]} of {scen['path']} at commit "
                   f"{str(prov.get('commit'))[:12]}; whoever wrote that commit wrote the oracle (check it with "
                   f"`git cat-file -p {str(prov.get('blob'))[:12]}`).")
    if agent:
        lim.append("The scenario was pinned from an agent session: if the agent that wrote the candidate also wrote "
                   "the scenario, the oracle is not independent. Have a person review it (sha256 "
                   f"{scen['sha256'][:12]}), or pin a reviewer's committed version with --from.")
    else:
        lim.append("The scenario was pinned from a terminal; who wrote it is not recorded.")
    if claim.get("replaced"):
        lim.append(f"The claim was re-pinned {claim['replaced']} time(s); its earlier scenarios were "
                   + ", ".join(str(h)[:12] for h in claim.get("earlier_scenarios") or []) + ".")
    lim += [f"Scenario check: {n}" for n in scen.get("notes") or []]
    subj = pp.get("subject") or {}
    if subj.get("files"):
        lim.append("The candidate side of the scenario ran on the base plus only the change's code under test ("
                   + ", ".join(subj["files"][:5]) + (" …" if len(subj["files"]) > 5 else "") + ", "
                   + ("declared with --subject" if subj.get("declared") else "inferred from the scenario's imports")
                   + ")." + (" Its other edits (" + ", ".join(subj.get("left_out", [])[:5])
                             + (" …" if len(subj.get("left_out", [])) > 5 else "")
                             + ") did not reach the scenario; existing tests that depend on them ran with the "
                               "base's versions." if subj.get("left_out") else "")
                   + " The same scenario also ran on the whole working tree as the change ships it, and the claim "
                     "needs both runs to pass the same way.")
    if subj.get("declared"):
        lim.append("The code under test was declared (--subject), and ProofLab takes that declaration at its word: "
                   "if a declared file also holds the expected values the scenario or existing tests compare against, "
                   "neither the scenario nor the regression checks can tell.")
    oracle = (pp.get("conditions") or {}).get("oracle") or {}
    touched = oracle.get("imported_changed") or []
    if touched:
        lim.append("The change edits files the scenario reaches by imports (" + ", ".join(touched[:5])
                   + (" …" if len(touched) > 5 else "") + "). ProofLab treats them as the code under test; if one of "
                   "them holds the expected values, the scenario does not check the claim. Review them, or move "
                   "expected values into the scenario.")
    data = oracle.get("changed_data") or []
    if data:
        lim.append("The change edits data files (" + ", ".join(data[:5]) + (" …" if len(data) > 5 else "")
                   + "). If the scenario reads one of them as its expected output, it does not check the claim; "
                   "pin it with --support, or keep it unchanged.")
    if scen.get("in_candidate_tree") == "absent":
        lim.append("The scenario is not in the candidate's tree (it was injected for the experiment): the change "
                   "does not ship this test.")
    lim.append(f"Each side ran {repeat} time(s); a flaky outcome that shows up less often is not ruled out.")
    cand_reps = ((pp["observations"] or {}).get("candidate") or {}).get("repeats") or []
    if any(r.get("canary") == "not-applicable" for r in cand_reps):
        lim.append("No assertion canary could run in the scenario's process (node runs each file alone; unittest "
                   "discovery from a nested top level runs files apart): code under test that disables assertions "
                   "would not be noticed.")
    else:
        lim.append("The assertion canary only shows that assertions still fail in the scenario's process; code "
                   "under test that recognises the scenario and behaves differently for it is not detected.")
    base = (pp["observations"] or {}).get("baseline") or {}
    if base.get("kind") == "matches-pinned-failure":
        lim.append("The base failure is accepted because it matches the pinned --expect-failure pattern, not "
                   "because it was judged to be the targeted behaviour.")
    reg = pp.get("regressions") or {}
    untested = []
    if reg.get("state") in {"none-detected", "detected"}:
        if reg.get("confidence") in {"medium", "low"}:
            lim.append(f"The regression check's test selection has {reg['confidence']} confidence (see "
                       "`repo-ai verify`).")
        if reg.get("pre_existing"):
            lim.append(f"{len(reg['pre_existing'])} test file(s) already fail at the base; they cannot show a "
                       "regression.")
        total, selected = reg.get("test_files_total") or 0, reg.get("selected") or 0
        if reg.get("full_suite") in {"not-run", None} and total and selected < total:
            untested.append(f"{total - selected} of {total} existing test file(s) were not selected by the "
                            "regression check and did not run.")
    for row in (pp.get("edited_tests") or {}).get("files") or []:
        if row.get("superseded"):
            lim.append(f"Base tests the claim declares superseded fail at the candidate ({row['path']}: "
                       + ", ".join(row["superseded"][:3]) + ").")
    cand = (pp["observations"] or {}).get("candidate") or {}
    n = len(((cand.get("repeats") or [{}])[0] or {}).get("outcomes") or {})
    if n:
        untested.append(f"Behaviour outside the scenario's {n} test(s).")
    env = pp.get("environment") or {}
    where = ", ".join(str(env[k]) for k in ("os", "python", "node", "image") if env.get(k))
    untested.append(f"Other platforms and environments: only {where or 'this machine'} in the "
                    f"{env.get('backend', 'local')} sandbox was used.")
    untested.append("The claim's wording itself: no tool checks that the scenario tests what the claim says.")
    return lim, untested


def reproduce(pp: dict[str, Any]) -> list[str]:
    scen, base = pp["scenario"], pp["baseline"]
    prov = scen.get("provenance") or {}
    cmd = pp["conditions"].get("command") or "(the scenario's test command)"
    where = (f"git show {prov.get('commit', '')[:12]}:{scen['path']} > {scen['path']}" if prov.get("kind") == "git"
             else f"copy the pinned bytes from .repo-ai/state/prove/blobs/{scen['sha256']} to {scen['path']}")
    return [
        f"repo-ai prove run {pp['claim']['id']} --base {base['commit'][:12]}",
        f"# by hand: check out {base['commit'][:12]} in a separate worktree, then {where}",
        f"# check the bytes: sha256 of {scen['path']} must be {scen['sha256']}",
        f"# at the base, in a sandbox: {cmd}   -> expect a failure in "
        + (", ".join((pp['observations'].get('baseline') or {}).get('targets_failing') or []) or "the targeted tests"),
        f"# at the candidate: {cmd}   -> expect every test to pass",
        f"repo-ai verify --run --base {base['commit'][:12]}   # the regression check",
    ]


def digest(pp: dict[str, Any]) -> str:
    body = {k: v for k, v in pp.items() if k not in {"digest", "path"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def finish(state_dir: Path, pp: dict[str, Any], *, problems: list[dict[str, str]] | None = None,
           baseline: dict | None = None, candidate: dict | None = None, edited: dict | None = None,
           regressions: dict | None = None, integrity: dict | None = None, seconds: float = 0.0,
           runner=None, repeat: int = 0, evidence_in: dict[str, Any] | None = None,
           abstain: list[str] | None = None) -> dict[str, Any]:
    pp["observations"] = {"baseline": baseline, "candidate": candidate}
    pp["edited_tests"], pp["regressions"], pp["integrity"] = edited, regressions, integrity
    pp["abstain"] = list(abstain or [])
    pp["verdict"] = decide(problems, baseline, candidate, edited, regressions, integrity, abstain)
    pp["executed"] = not problems
    pp["repeat"] = repeat
    pp["seconds"] = round(seconds, 2)
    pp["limitations"], pp["untested"] = limitations(pp, repeat) if not problems else (
        [*experimental_notes(), "Nothing ran: the experiment stopped before execution."], [])
    pp["reproduce"] = reproduce(pp)
    pp["evidence"] = []
    if evidence_in is not None:
        from . import contract
        rec = contract.record(pp, **evidence_in)
        pp["evidence"] = [rec]
        _align(pp["verdict"], rec)
    pp["digest"] = digest(pp)
    pp["path"] = str(save(state_dir, pp))
    return pp


def _dir(state_dir: Path, cid: str) -> Path:
    return cl.folder(state_dir) / "passports" / cid


def _history(folder: Path) -> list[Path]:
    def written(p: Path) -> tuple[int, str]:
        try:
            return p.stat().st_mtime_ns, p.name
        except OSError:
            return 0, p.name
    return sorted(folder.glob("2*.json"), key=written, reverse=True) if folder.is_dir() else []


def save(state_dir: Path, pp: dict[str, Any]) -> Path:
    from ..fsutil import atomic_write
    folder = _dir(state_dir, pp["claim"]["id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{os.getpid():07d}.json")
    atomic_write(path, json.dumps({k: v for k, v in pp.items() if k != "path"}, indent=1, sort_keys=True) + "\n")
    for old in _history(folder)[KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def latest(state_dir: Path, cid: str) -> dict[str, Any] | None:
    """The newest valid passport of this claim (by write time)."""
    for path in _history(_dir(state_dir, cid))[:KEEP]:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema") == SCHEMA and data.get("digest") == digest(data):
            data["path"] = str(path)
            return data
    return None


def status(root: Path, state_dir: Path, cid: str, env_key: str | None = None) -> dict[str, Any]:
    """Whether the newest passport still describes this claim, base, working
    tree and test environment (`env_key`: verify's environment key now; ""
    when it cannot be computed, which makes the state "unknown"). Reads files
    and git; runs no repository code."""
    pp = latest(state_dir, cid)
    if pp is None:
        return {"state": "none", "reasons": ["no passport yet: `repo-ai prove run` records one"], "passport": None}
    reasons = []
    record = cl.load(state_dir, cid, missing_ok=True)
    if record is None:
        reasons.append("the claim is no longer pinned")
    elif record.get("settings") != pp["claim"].get("settings"):
        reasons.append("the claim was pinned again with other settings since this experiment")
    rev = pp["baseline"].get("revision") or "HEAD"
    try:
        commit = ch.resolve_base(root, rev)
        if commit != pp["baseline"].get("commit"):
            reasons.append(f"the base {rev} now resolves to {commit[:12]}, not {str(pp['baseline'].get('commit'))[:12]}")
        elif ch.fingerprint(root, rev) != pp["candidate"].get("fingerprint"):
            reasons.append("the working tree changed since this experiment")
    except ch.ChangeError as exc:
        reasons.append(f"the base {rev} cannot be resolved ({exc})")
    scen = pp["scenario"]
    # the fingerprint covers the scenario unless git ignores it: check its bytes directly, when the
    # experiment saw the pinned bytes there
    for item, what in [(scen, "scenario"), *((s, "support file") for s in pp.get("support") or [])]:
        p = root / item["path"]
        if not reasons and item.get("in_candidate_tree") == "identical" and (
                not p.is_file() or p.is_symlink() or cl.sha256(p.read_bytes()) != item["sha256"]):
            reasons.append(f"{item['path']} is no longer the pinned {what}")
    recorded = (pp.get("environment") or {}).get("key")
    unknown = False
    if env_key is not None and recorded:
        if not env_key:
            unknown = True
        elif env_key != recorded:
            reasons.append("the test environment changed since this experiment (interpreter, installed packages, "
                           "node_modules, image or repo-ai version)")
    state = "stale" if reasons else ("unknown" if unknown else "fresh")
    if unknown:
        reasons.append("the test environment could not be checked here (no sandbox or interpreter)")
    if pp.get("evidence"):  # what a consumer must show now (the contract's freshness rule)
        from . import contract
        pp["evidence"] = [contract.fresh_view(r, state) for r in pp["evidence"]]
    return {"state": state, "reasons": reasons, "passport": pp}


STALE_HEADLINE = "CLAIM NOT ESTABLISHED: the passport no longer describes this claim and working tree ({state})"


def export_view(pp: dict[str, Any], freshness: dict[str, Any]) -> dict[str, Any]:
    """The passport as every export shows it now (JSON, Markdown, in-toto,
    `prove status`): its freshness, and, unless fresh, a verdict that
    supports nothing. The recorded verdict is kept under `verdict.recorded`.
    `freshness`: what `status` returned (state and reasons)."""
    out = json.loads(json.dumps({k: v for k, v in pp.items() if k != "path"}))
    if not (isinstance(out.get("experimental"), dict) and out["experimental"].get("known_false_proofs")):
        out["experimental"] = json.loads(json.dumps(EXPERIMENTAL))  # a passport written before the standing existed
    state = str(freshness.get("state") or "unknown")
    out["freshness"] = {"state": state, "reasons": list(freshness.get("reasons") or [])}
    if state != "fresh":
        v = out["verdict"]
        out["verdict"] = {"state": "stale", "supported": False, "level": "not_established",
                          "headline": STALE_HEADLINE.format(state=state),
                          "reasons": [*out["freshness"]["reasons"], *v.get("reasons", [])],
                          "recorded": {k: v.get(k) for k in ("state", "supported", "level", "headline")}}
    return out
