"""Passports for people: the terminal, a Markdown report for a pull request,
and an unsigned in-toto Statement for tools.

Rendering is a pure function of the passport (and of the freshness computed
when it is shown), so the same passport always renders to the same bytes. No
source code is ever shown; test ids and failure messages come from the code
under test, so they are cleaned (``experiment.clean``) and shown only inside
code spans, where Markdown, HTML and @-mentions do nothing.
"""

from __future__ import annotations

import json
from typing import Any

from .experiment import clean

IN_TOTO_STATEMENT = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://github.com/hxxtsxxh/repo-ai/blob/main/docs/PROOFLAB.md#passport-v1"


def code(text: object, limit: int = 160) -> str:
    """`text` as one inline code span that nothing inside can close."""
    # a pipe would split a table cell even inside a code span
    body = clean(str(text), limit).replace("`", "'").replace("|", "¦")
    return f"`{body}`" if body else "``"


ZWSP = "​"
_PROSE_ESCAPES = (("\\", "\\\\"), ("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("@", "@" + ZWSP), ("[", "\\["),
                  ("]", "\\]"), ("(", "\\("), ("*", "\\*"), ("_", "\\_"), ("`", "'"), ("|", "\\|"), ("~", "\\~"),
                  ("://", ":" + ZWSP + "//"), ("www.", "www" + ZWSP + "."), ("$", "\\$"), ("#", "#" + ZWSP))


def prose(text: object, limit: int = 600) -> str:
    """Text that is not ours (the claim, reasons quoting test output) as inert
    Markdown. The backslash goes first, so an escape in the text cannot cancel
    ours; links, bracketed or bare (which GitHub autolinks), are broken with a
    zero-width space."""
    body = clean(str(text), limit)
    for a, b in _PROSE_ESCAPES:
        body = body.replace(a, b)
    return body


def _side(obs: dict[str, Any] | None) -> str:
    if not obs:
        return "not run"
    reps = obs.get("repeats") or []
    if not reps:
        return obs.get("why", obs.get("state", ""))
    first = reps[0]
    fails = sorted(t for t, o in first["outcomes"].items() if o == "fail")
    skips = sum(1 for o in first["outcomes"].values() if o == "skip")
    total = len(first["outcomes"])
    if not first["trusted"]:
        return "incomplete: " + clean(first["reason"], 120)
    text = f"{total - len(fails) - skips} of {total} passed" + (f", {len(fails)} failed" if fails else "") + (
        f", {skips} skipped" if skips else "")
    return text


def _failure_rows(obs: dict[str, Any] | None, limit: int = 5) -> list[tuple[str, str]]:
    if not obs or not obs.get("repeats"):
        return []
    first = obs["repeats"][0]
    rows = [(t, first["failures"].get(t, "")) for t, o in sorted(first["outcomes"].items()) if o == "fail"]
    return rows[:limit]


def _consistency(obs: dict[str, Any] | None) -> str:
    reps = (obs or {}).get("repeats") or []
    if not reps:
        return "-"
    same = len({tuple(sorted(r["outcomes"].items())) for r in reps}) == 1
    return f"{len(reps)}, {'consistent' if same else 'INCONSISTENT'}"


def _standing(pp: dict[str, Any]) -> dict[str, Any]:
    """ProofLab's standing as the passport records it (an older passport
    without one gets today's, which is never less cautious)."""
    from .passport import EXPERIMENTAL
    got = pp.get("experimental")
    return got if isinstance(got, dict) and got.get("known_false_proofs") else EXPERIMENTAL


def markdown(pp: dict[str, Any], fresh: dict[str, Any] | None = None) -> str:
    v = pp["verdict"]
    claim, scen, base, cand = pp["claim"], pp["scenario"], pp["baseline"], pp["candidate"]
    obs = pp.get("observations") or {}
    b, c = obs.get("baseline"), obs.get("candidate")
    shipped = (c or {}).get("shipped")
    out = [f"## ProofLab passport: {code(claim['id'], 64)}", ""]
    if fresh is not None and fresh["state"] != "fresh":
        out.append(f"**⚠️ STALE: this passport no longer describes the claim and working tree (it said: "
                   f"{(v.get('recorded') or v)['state']}). Run `repo-ai prove run` again.**")
    else:
        out.append(f"**{'✅' if v['supported'] else '❌'} {v['headline']}**")
    out.append("")
    # right under the verdict, whatever it is: ProofLab's standing and its open false proofs
    out += ["> **⚠️ EXPERIMENTAL, NOT CERTIFIED.** ProofLab is opt-in and outside repo-ai's stable verification "
            "claims; its independent certification is blocked. A supported verdict is a local experiment record, "
            "not a proof.", ">"]
    out += [f"> **Known false proof (open, {code(k.get('id'), 40)}):** {prose(k.get('summary'), 400)}"
            for k in _standing(pp).get("known_false_proofs") or []]
    out.append("")
    text = claim.get("text")
    out.append("> **Claim:** " + (prose(text) if text else f"(redacted; sha256 {code(claim['sha256'][:16])})"))
    out.append("")
    if fresh is not None:
        out.append(f"Freshness when exported: **{fresh['state']}**"
                   + ("" if fresh["state"] == "fresh" else " (" + "; ".join(prose(r, 160) for r in fresh["reasons"][:3])
                                                            + ")"))
        out.append("")
    prov = scen.get("provenance") or {}
    origin = {"git": f"blob {code(str(prov.get('blob'))[:12])} at commit {code(str(prov.get('commit'))[:12])}",
              "file": "a file outside the repository", "worktree": "the working tree"}.get(str(prov.get("kind")), "unknown")
    who = "an agent session" if (claim.get("pinned") or {}).get("agent_shell") else "a terminal"
    out += ["| | Before (base) | After (candidate) |", "|---|---|---|",
            f"| Revision | {code(base['commit'][:12])} ({code(base['revision'], 40)}) | working tree "
            f"{code(cand['fingerprint'][:12])}, {cand['changed_files_total']} changed file(s) |",
            f"| Scenario | {code(scen['path'])}, same bytes | {code(scen['path'])}, same bytes |",
            f"| Observed | {_side(b)} | {_side(c)} |",
            f"| Runs | {_consistency(b)} | {_consistency(c)} |",
            *([f"| As shipped (whole working tree) | | {_side(shipped)}, {_consistency(shipped)} |"]
              if shipped else []), ""]
    rows = _failure_rows(b)
    if rows:
        out.append("**Failing before:**")
        out += [f"- {code(t, 120)}: {code(m, 200)}" for t, m in rows]
        out.append("")
    rows = _failure_rows(c)
    if rows:
        out.append("**Failing after:**")
        out += [f"- {code(t, 120)}: {code(m, 200)}" for t, m in rows]
        out.append("")
    if pp.get("executed"):
        reg = pp.get("regressions") or {}
        line = f"**Regressions:** {reg.get('state', '-')}"
        if reg.get("verdict"):
            line += (f" (verify: {code(reg['verdict'], 100)}; {reg.get('passed', 0)} test file(s) passed of "
                     f"{reg.get('selected', 0)} selected, {reg.get('test_files_total') or '?'} in the project; "
                     f"confidence {reg.get('confidence') or '?'})")
        out.append(line)
        for nf in (reg.get("new_failures") or [])[:5]:
            out.append(f"- new failure: {code(nf.get('test_file'))} " + ", ".join(code(t, 80) for t in nf["tests"][:3]))
        ed = pp.get("edited_tests") or {}
        files = ed.get("files") or []
        if files:
            out.append(f"**Edited tests:** the base's own version of {len(files)} edited test file(s) run against "
                       f"the candidate: {ed.get('state')}")
            for row in files:
                if row.get("new_failures"):
                    out.append(f"- {code(row['path'])}: " + ", ".join(code(t, 80) for t in row["new_failures"][:3]))
        else:
            out.append("**Edited tests:** the candidate edits no existing test file")
        integ = pp.get("integrity") or {}
        oracle = (pp.get("conditions") or {}).get("oracle") or {}
        out.append(f"**Integrity:** source tree {'unchanged' if integ.get('unchanged') else 'CHANGED'}; "
                   f"{oracle.get('checked', 0)} oracle input(s) identical at both revisions; "
                   f"runner {code(pp['conditions'].get('command') or pp['conditions']['runner'].get('command'), 100)}")
        out.append("")
    if v["reasons"]:
        out.append("### Why")
        out += [f"- {prose(r, 300)}" for r in v["reasons"][:8]]
        out.append("")
    out.append("### What this does not establish")
    out += [f"- {prose(x, 400)}" for x in pp.get("limitations") or []]
    out.append("")
    if pp.get("untested"):
        out.append("### Not tested")
        out += [f"- {prose(x, 300)}" for x in pp["untested"]]
        out.append("")
    out.append("### Reproduce")
    out += ["```sh", *[clean(x, 400).replace("```", "'''") for x in pp.get("reproduce") or []], "```", ""]
    env = pp.get("environment") or {}
    envs = ", ".join(f"{k} {clean(env[k], 60)}" for k in ("backend", "os", "python", "node", "image") if env.get(k))
    out.append(f"<sub>scenario sha256 {code(scen['sha256'])} from {origin}, pinned from {who} · {envs} · "
               f"repo-ai {clean(str(pp.get('repo_ai_version')), 20)} · {pp['schema']} · passport "
               f"{code(pp['digest'][:16])} · recorded {clean(pp['created'], 40)}</sub>")
    return "\n".join(out) + "\n"


def text(pp: dict[str, Any], fresh: dict[str, Any] | None = None) -> str:
    """The terminal view: the conclusion first."""
    v = pp["verdict"]
    obs = pp.get("observations") or {}
    lines = ["EXPERIMENTAL, NOT CERTIFIED: ProofLab is not a certified proof system; known open false proof(s): "
             + ", ".join(str(k.get("id")) for k in _standing(pp).get("known_false_proofs") or []), v["headline"]]
    lines += [f"  - {clean(r, 300)}" for r in v["reasons"][:6]]
    claim = pp["claim"]
    lines.append(f"claim {claim['id']}: " + (clean(claim['text'], 200) if claim.get("text") else "(redacted)"))
    scen = pp["scenario"]
    lines.append(f"scenario {scen['path']}  sha256 {scen['sha256'][:16]}  ({(scen.get('provenance') or {}).get('kind')})")
    if pp.get("executed"):
        lines.append(f"  before  {pp['baseline']['commit'][:12]}: {_side(obs.get('baseline'))}"
                     f"  [{(obs.get('baseline') or {}).get('state')}]")
        for t, m in _failure_rows(obs.get("baseline"), 3):
            lines.append(f"            {clean(t, 100)}: {clean(m, 140)}")
        lines.append(f"  after   base + code under test: {_side(obs.get('candidate'))}  "
                     f"[{(obs.get('candidate') or {}).get('state')}]")
        shipped = (obs.get("candidate") or {}).get("shipped")
        if shipped:
            lines.append(f"  shipped whole working tree: {_side(shipped)}  [{shipped.get('state')}]")
        for t, m in _failure_rows(obs.get("candidate"), 3):
            lines.append(f"            {clean(t, 100)}: {clean(m, 140)}")
        reg = pp.get("regressions") or {}
        lines.append(f"  regressions: {reg.get('state')}" + (f"  (verify: {clean(reg['verdict'], 100)})"
                                                            if reg.get("verdict") else ""))
        ed = pp.get("edited_tests") or {}
        if ed.get("files"):
            lines.append(f"  edited tests (base versions at the candidate): {ed.get('state')}")
        integ = pp.get("integrity") or {}
        lines.append(f"  integrity: source tree {'unchanged' if integ.get('unchanged') else 'CHANGED'}; "
                     f"{pp['seconds']:.1f}s")
    if fresh is not None:
        lines.append(f"freshness: {fresh['state']}" + ("" if fresh["state"] == "fresh" else
                                                     " (" + "; ".join(clean(r, 200) for r in fresh["reasons"][:3]) + ")"))
    lines.append("not established by this passport:")
    lines += [f"  - {clean(x, 300)}" for x in (pp.get("limitations") or [])[:6]]
    lines.append(f"passport {pp['digest'][:16]}  (`repo-ai prove report {claim['id']}` exports it as Markdown)")
    return "\n".join(lines) + "\n"


def in_toto(pp: dict[str, Any]) -> dict[str, Any]:
    """The passport as an unsigned in-toto Statement v1. Signing it (DSSE,
    cosign) is the user's choice and needs their own keys or identity. `pp`:
    the export view (`passport.export_view`), so the predicate carries its
    freshness and, unless fresh, a verdict that supports nothing."""
    subject = [{"name": "candidate-working-tree", "digest": {"repoAiFingerprint": pp["candidate"]["fingerprint"]}},
               {"name": pp["scenario"]["path"], "digest": {"sha256": pp["scenario"]["sha256"]}}]
    predicate = {k: pp.get(k) for k in ("claim", "baseline", "candidate", "scenario", "support", "conditions",
                                        "environment", "observations", "edited_tests", "regressions", "integrity",
                                        "verdict", "limitations", "untested", "created", "repo_ai_version",
                                        "experimental",
                                        "freshness", "evidence")}
    predicate["baseline"] = {**pp["baseline"], "digest": {"gitCommit": pp["baseline"]["commit"]}}
    predicate["experimental"] = _standing(pp)
    predicate["passport_digest"] = pp["digest"]
    predicate["signed"] = False
    return {"_type": IN_TOTO_STATEMENT, "subject": subject, "predicateType": PREDICATE_TYPE,
            "predicate": json.loads(json.dumps(predicate, sort_keys=True))}
