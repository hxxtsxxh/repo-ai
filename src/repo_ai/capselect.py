"""Capability selection: trust gates, the candidate menu and selection checks.

Three parts are kept apart:
1. discovery (`capdiscovery.discover()`, not imported here) orders and filters
   records. Its result is passed in as a plain dict;
2. the gates below are the trust state. They read typed manifest fields and
   the machine-local lifecycle states (`capabilities.all_states`) only: never
   task text, never registry free text, never repository files;
3. selection (by an agent, a human or nobody) is re-validated against the
   gates every time. A selection is never an invocation.

Nothing here starts a process, installs anything or writes inside the
repository. `select` appends one line to a log outside the repository and
otherwise only computes.

Every string in the output is one of: a manifest constant (id, kind, a
prefix of `adds_beyond_native`), a closed code defined in this module, a
language name from `capabilities.EXT_LANG`, a hex digest or a fixed argv
token. The task and the changed paths are hashed, never emitted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import capabilities as caps

SCHEMA_CANDIDATES = "repo-ai.capability-candidates/1"
SCHEMA_SELECTION = "repo-ai.capability-selection/1"
K = 6
MAX_BYTES = 1800
MAX_SELECT_BYTES = 600
MAX_EXCLUDED = 6
ADDS_CHARS = 90
CONSTRAINTS = ("no-network", "no-exec", "static-only", "no-install", "no-third-party")
NONE = "none"
NONE_TEXT = "valid: your own tools are the default"
DOCS = "docs/CAPABILITIES.md"
EXIT_OK, EXIT_HUMAN, EXIT_STALE, EXIT_REFUSED = 0, 3, 6, 7
INIT_REASON = "needs `repo-ai init`"

ID_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+\Z")
DIGEST_RE = re.compile(r"^cd1:[0-9a-f]{32}\Z")
_HEX = re.compile(r"^[0-9a-f]+$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")

# --------------------------------------------------------------------------
# closed vocabularies
# --------------------------------------------------------------------------
GATE_CODES = ("unreviewed", "unpinned", "no-adapter", "not-run-by-repo-ai", "not-approved", "binding-changed",
              "not-installed", "needs-init", "needs-authorization")
REVIEWED = ("first-party", "reviewed")
IMPLEMENTED_ADAPTERS = ("adapter.ruff-security",)  # bound by path + sha256 + version at approval
RISK_CODES = ("network", "repo-code", "runs-binary", "external", "model-time")
TIERS = ("recommend", "consider")
HINTS = ("code-change", "docs-only", "no-change")
FIT_PREFIXES = ("need", "file", "lang")
FILE_SIGNALS = ("code", "python", "manifest", "frontend", "security-path", "docs", "tests", "config")
WHY_CODES = ("lang", "python-only", "frontend", "docs-only", "excluded", "covered", "no-signal", "duplicate")
LANGS = frozenset(caps.EXT_LANG.values()) | {"HTML", "CSS"}
# availability reasons `capabilities.state()` produces; anything else is "unknown"
REASONS = ("ok", "needs-init", "not_installed", "not_approved", "binding_changed", "no_adapter",
           "not_managed_by_repo_ai", "unknown")
DECISIONS = ("ready", "human", "none", "stale", "refused", "not-offered", "unknown")
# digest components, in the order their check nibbles are appended
COMPONENTS = ("task", "base", "commit", "changed", "indexed", "version", "deny", "all", "manifest", "trust",
              "list", "excluded")
SELECT_AGENT_ENV = tuple(dict.fromkeys((*caps.AGENT_ENV, "REPO_AI_AGENT")))
LOG_NAME = "selections.jsonl"
LOG_LINES = 2000

# G10: the only argv a `ready` selection can carry (after the leading "repo-ai").
# Never: verify --run / --record, skills vet --online, approve, prepare, revoke, any install.
READ_ONLY: frozenset[tuple[str, ...]] = frozenset({
    ("verify", "--json"),
    ("impact", "--changed", "--format", "json"),
    ("review", "--format", "json"),
    ("capabilities", "run", "repo-ai.context", "--json", "--task-stdin"),
    ("skills", "inventory", "--json"),
    ("skills", "vet"),
    ("budget", "--json"),
    ("capabilities", "run", "adapter.ruff-security", "--json"),
})
APPEND = {"repo-ai.context": "task-on-stdin", "repo-ai.skills-vet": "url-or-dir"}

# --------------------------------------------------------------------------
# the PROTOCOL.md section 4.4 constraint table, as data
# --------------------------------------------------------------------------
# repo-ai.skills-vet needs --online here: it has no offline mode on this branch, so no-network rules it out
_NO_NETWORK = frozenset({"adapter.dependency-audit", "adapter.semgrep", "ext.browser-evidence", "repo-ai.skills-vet"})
_NO_EXEC = frozenset({"ext.mutation-testing", "ext.property-testing", "ext.browser-evidence"})
_STATIC_EXTRA = frozenset({"ext.lsp-references"})
# allowed under the constraint, with a curated note instead of being forbidden
CONSTRAINT_NOTES: dict[tuple[str, str], str] = {
    ("no-exec", "repo-ai.verify"): "plan only; running tests needs your authorization",
    ("static-only", "repo-ai.verify"): "plan only; running tests needs your authorization",
}
VERIFY_NOTE = "plan only; running tests needs your authorization"

# --------------------------------------------------------------------------
# curated human steps: one fixed sentence per code. Lint-tested: no command,
# no backticks, no shell metacharacters, no URLs, no install/approve words.
# --------------------------------------------------------------------------
HUMAN_TEXT: dict[str, str] = {
    "not-approved": "This adapter runs a local binary only after the user has personally vetted and bound that "
                    "exact file in their own terminal. Tell the user, do not attempt it.",
    "binding-changed": "The local binary this adapter was bound to has changed since the user vetted it. Tell the "
                       "user it must be checked again, do not attempt it.",
    "not-installed": "The tool this capability needs is not present on this machine, and repo-ai never adds "
                     "tools. Tell the user and continue with your own tools.",
    "needs-init": "This built-in needs the repository index, which has not been built here. Tell the user and "
                  "continue with your own tools.",
    "no-adapter": "repo-ai has no adapter for this tool yet, so it cannot run it. Mention it to the user if it "
                  "fits and continue with your own tools.",
    "not-run-by-repo-ai": "This is an external tool the user sets up and runs themselves, never repo-ai or the "
                          "agent. Mention it to the user if it fits the task.",
    "unreviewed": "Nobody has reviewed this tool's source for repo-ai yet. Mention it to the user only as an "
                  "unvetted option, do not attempt it.",
    "unpinned": "This tool's source is not pinned to a reviewed version. Mention it to the user only as an "
                "unvetted option, do not attempt it.",
    "needs-authorization": "Running this goes beyond read-only commands and needs the user's explicit "
                           "authorization. Ask the user, do not attempt it.",
}
FORBIDDEN_TEXT = ("`", "$", "|", ";", "&&", "://", "www.", "npx", "pip", "npm", "pnpm", "yarn", "brew", "curl",
                  "wget", "approve", "prepare", "install", "/plugin", "mcp add", "--sha256", "sudo")


def lint_text(text: str) -> list[str]:
    """Problems with a curated sentence shown to an agent; empty when clean."""
    problems = []
    if not text.isascii() or not text.isprintable():
        problems.append("not printable ASCII")
    if len(text) > 160:
        problems.append("longer than 160 characters")
    low = text.lower()
    problems += [f"contains {tok!r}" for tok in FORBIDDEN_TEXT if tok in low]
    return problems


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------
def encode(obj: Any) -> str:
    """The one compact encoding for agent-facing output (and the digest)."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def _h(obj: Any) -> str:
    return hashlib.sha256(encode(obj).encode("ascii")).hexdigest()


# --------------------------------------------------------------------------
# trust gates
# --------------------------------------------------------------------------
def _caps(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c["id"]): c for c in manifest["capabilities"] if isinstance(c, dict) and "id" in c}


def _is_adapter(cid: str, cap: dict[str, Any]) -> bool:
    return cap.get("kind") == "adapter" or cid.startswith("adapter.")


def _is_external(cid: str, cap: dict[str, Any]) -> bool:
    return cap.get("kind") == "external" or cid.startswith("ext.")


def _avail(st: dict[str, Any] | None) -> tuple[bool, str]:
    """(available, raw reason) from a lifecycle state; a missing state is unavailable."""
    av = (st or {}).get("available")
    if not isinstance(av, dict):
        return False, "unknown"
    return av.get("status") is True, str(av.get("reason", "unknown"))


def _reason_code(raw: str) -> str:
    code = "needs-init" if raw == INIT_REASON else raw
    return code if code in REASONS else "unknown"


def constraint_forbidden(constraint: str, manifest: dict[str, Any], states: dict[str, Any]) -> set[str]:
    """Ids a constraint rules out (PROTOCOL.md section 4.4). Reads ids, `kind` and machine state only."""
    if constraint not in CONSTRAINTS:
        raise ValueError(f"unknown constraint class {constraint!r}; expected one of {', '.join(CONSTRAINTS)}")
    records = _caps(manifest)
    if constraint == "no-network":
        out = set(_NO_NETWORK)
    elif constraint == "no-exec":
        out = set(_NO_EXEC)
    elif constraint == "static-only":
        out = set(_NO_EXEC) | set(_STATIC_EXTRA) | {i for i, c in records.items() if _is_adapter(i, c)}
    elif constraint == "no-install":
        out = set()
        for i in records:
            ok, raw = _avail(states.get(i))
            if not ok and raw != INIT_REASON:
                out.add(i)
    else:  # no-third-party
        out = {i for i, c in records.items() if _is_adapter(i, c) or _is_external(i, c)}
    return out & set(records)


def _argv(cid: str, cap: dict[str, Any]) -> list[str] | None:
    """The argv a ready selection would carry: manifest constants and the validated id only."""
    if cid == "repo-ai.context":  # the task goes on stdin, never on a command line
        return ["repo-ai", "capabilities", "run", cid, "--json", "--task-stdin"]
    if cap.get("kind") == "builtin":
        run = (cap.get("activation") or {}).get("run")
        if not isinstance(run, list) or not run or not all(isinstance(t, str) for t in run):
            return None
        return ["repo-ai", *run]
    if cid in IMPLEMENTED_ADAPTERS and cap.get("kind") == "adapter":
        return ["repo-ai", "capabilities", "run", cid, "--json"]
    return None


def activation(cid: str, cap: dict[str, Any], st: dict[str, Any] | None) -> str:
    """G5-G10 in order; the first failing gate's code, or "ok". Typed fields and state only."""
    kind = cap.get("kind")
    # G5 reviewed
    if (cap.get("review") or {}).get("status") not in REVIEWED:
        return "unreviewed"
    # G6 provenance
    src = cap.get("source")
    if kind == "builtin":
        pass
    elif kind == "adapter":
        if cid not in IMPLEMENTED_ADAPTERS:
            return "unpinned"
    elif not (isinstance(src, dict) and _COMMIT.match(str(src.get("commit", "")))):
        return "unpinned"
    # G7 runner
    if kind == "adapter" and cid not in IMPLEMENTED_ADAPTERS:
        return "no-adapter"
    if kind not in ("builtin", "adapter"):
        return "not-run-by-repo-ai"
    available, raw = _avail(st)
    # G8 approval and binding (verify_binding's result, as `capabilities.state()` computed it)
    if kind == "adapter":
        approved = ((st or {}).get("approved") or {}).get("status") == "approved"
        if not approved:
            return "not-installed" if raw == "not_installed" else "not-approved"
        if not (available and raw == "ok"):
            return "binding-changed"
    # G9 available
    if not available:
        return {INIT_REASON: "needs-init", "binding_changed": "binding-changed",
                "not_approved": "not-approved", "no_adapter": "no-adapter",
                "not_managed_by_repo_ai": "not-run-by-repo-ai"}.get(raw, "not-installed")
    # G10 execution risk
    argv = _argv(cid, cap)
    if argv is None or tuple(argv[1:]) not in READ_ONLY:
        return "needs-authorization"
    return "ok"


def _effective(discovery: dict[str, Any], deny: list[str]) -> list[str]:
    asked = [str(c) for c in (discovery.get("constraints") or [])] + [str(d) for d in deny]
    for c in asked:
        if c not in CONSTRAINTS:
            raise ValueError(f"unknown constraint class {c!r}; expected one of {', '.join(CONSTRAINTS)}")
    return [c for c in CONSTRAINTS if c in asked]


def _fit(codes: Any) -> list[str]:
    out: list[str] = []
    for code in codes if isinstance(codes, list) else []:
        prefix, _, value = str(code).partition(":")
        if prefix == "need" and value in caps.NEED_BY_ID:
            pass
        elif prefix == "lang" and value in LANGS:
            pass
        elif not (prefix == "file" and value in FILE_SIGNALS):
            continue  # not a closed code: dropped, never echoed
        if code not in out:
            out.append(str(code))
    return out[:4]


def _why(code: Any) -> str:
    code = str(code)
    prefix, sep, value = code.partition(":")
    if sep:
        return code if prefix == "denied" and value in CONSTRAINTS else "excluded"
    return code if code in WHY_CODES else "excluded"


def gate(discovery: dict[str, Any], manifest: dict[str, Any], states: dict[str, Any],
         deny: list[str]) -> dict[str, Any]:
    """Discovery order kept; ranking never changes a gate. Blocked records never take a ready slot."""
    effective = _effective(discovery, deny)
    records = _caps(manifest)
    forbidden = {c: constraint_forbidden(c, manifest, states) for c in effective}
    hint = discovery.get("hint", "code-change")
    if hint not in HINTS:
        raise ValueError(f"unknown discovery hint {hint!r}")
    excluded: list[dict[str, str]] = []
    seen: set[str] = set()
    for e in discovery.get("excluded") or []:
        cid = str((e or {}).get("id", ""))
        if cid in records and cid not in seen:
            seen.add(cid)
            excluded.append({"id": cid, "why": _why(e.get("why", ""))})
    items: list[dict[str, Any]] = []
    for c in discovery.get("candidates") or []:
        cid = str((c or {}).get("id", ""))
        cap = records.get(cid)
        if cap is None or cid in seen:
            continue  # unknown or duplicate ids are dropped
        seen.add(cid)
        available, raw = _avail(states.get(cid))
        tier = c.get("tier")
        item: dict[str, Any] = {"id": cid, "kind": str(cap.get("kind", "")), "tier": tier if tier in TIERS else
                                "consider", "fit": _fit(c.get("fit")), "available": available,
                                "reason": _reason_code(raw)}
        denied = [k for k in effective if cid in forbidden[k]]
        if denied:
            item.update(blocked=True, why=f"denied:{denied[0]}")
        else:
            code = activation(cid, cap, states.get(cid))
            item.update(gate="ready" if code == "ok" else "human", code=code)
            notes = [CONSTRAINT_NOTES[(k, cid)] for k in effective if (k, cid) in CONSTRAINT_NOTES]
            if notes:
                item["note"] = notes[0]
        items.append(item)
    langs = sorted({str(x) for x in discovery.get("langs") or [] if str(x) in LANGS})
    explicit = [c for c in CONSTRAINTS if c in {str(d) for d in deny}]
    inferred = [c for c in effective if c not in explicit]
    return {"constraints": effective, "explicit": explicit, "inferred": inferred, "candidates": items,
            "excluded": excluded, "hint": hint, "langs": langs}


def recommend_top3(gated: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in gated["candidates"]:
        if not c.get("blocked") and c.get("tier") == "recommend":
            out.append({"id": c["id"], "available": c["available"], "reason": c["reason"], "gate": c["gate"]})
        if len(out) == 3:
            break
    return out


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------
def _trust(manifest: dict[str, Any], states: dict[str, Any]) -> dict[str, list[str]]:
    out = {}
    for cid, cap in sorted(_caps(manifest).items()):
        sha = str(((states.get(cid) or {}).get("approved") or {}).get("sha256", ""))[:16]
        out[cid] = [activation(cid, cap, states.get(cid)), sha if _HEX.match(sha) else ""]
    return out


def digest_components(gated: dict[str, Any], shown: list[str], manifest: dict[str, Any], states: dict[str, Any],
                      *, deny: list[str], digest_inputs: dict[str, Any], all_: bool) -> dict[str, str]:
    """One sha256 per component. No time, no environment, no absolute paths."""
    di = digest_inputs
    values: dict[str, Any] = {
        "task": str(di.get("task_sha256", "")), "base": str(di.get("base", "")),
        "commit": str(di.get("commit", "")), "changed": sorted(str(p) for p in di.get("changed") or []),
        "indexed": bool(di.get("indexed")), "version": str(di.get("version", "")),
        "deny": sorted({str(d) for d in deny}), "all": bool(all_), "manifest": _h(manifest),
        "trust": _trust(manifest, states), "list": list(shown),
        "excluded": [[e["id"], e["why"]] for e in gated["excluded"]]
                    + [[c["id"], c["why"]] for c in gated["candidates"] if c.get("blocked")],
    }
    return {k: _h(values[k]) for k in COMPONENTS}


def digest(components: dict[str, str]) -> str:
    """`cd1:` + 20 hex over every component + one check nibble per component
    (in COMPONENTS order), so a stale digest can name what changed without
    echoing any value."""
    return "cd1:" + _h(components)[:20] + "".join(components[k][0] for k in COMPONENTS)


def _stale_components(supplied: str, current: str) -> list[str]:
    if supplied == current:
        return []
    off = len("cd1:") + 20
    differ = [k for i, k in enumerate(COMPONENTS) if supplied[off + i] != current[off + i]]
    return differ or ["unidentified"]


# --------------------------------------------------------------------------
# the menu
# --------------------------------------------------------------------------
def _adds(text: str) -> str:
    text = " ".join(str(text).split())
    if len(text) <= ADDS_CHARS:
        return text
    cut = text[:ADDS_CHARS + 1]
    cut = cut[:cut.rfind(" ")] if " " in cut else text[:ADDS_CHARS]
    return cut.rstrip(" ,;:(")


def _risk(cid: str, cap: dict[str, Any]) -> list[str]:
    risk = set()
    if cap.get("network") is True or cid in _NO_NETWORK:
        risk.add("network")
    if cid in _NO_EXEC:
        risk.add("repo-code")
    if cap.get("kind") == "adapter":
        risk.add("runs-binary")
    if cap.get("kind") == "external":
        risk.add("external")
    if cap.get("model_spend") not in (False, None):
        risk.add("model-time")
    return [r for r in RISK_CODES if r in risk]


def _with_all(discovery: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """`--all`: every record not excluded by discovery, discovery's order first."""
    listed = {str((c or {}).get("id", "")) for c in discovery.get("candidates") or []}
    listed |= {str((e or {}).get("id", "")) for e in discovery.get("excluded") or []}
    gated = [(str(g[0]), str(g[1])) for g in discovery.get("gated") or [] if isinstance(g, (list, tuple))]
    excluded = [*(discovery.get("excluded") or []), *({"id": cid, "why": why} for cid, why in gated
                                                        if cid not in listed)]
    listed |= {cid for cid, _ in gated}
    extra = [{"id": cid, "tier": "consider", "fit": []} for cid in _caps(manifest) if cid not in listed]
    return {**discovery, "candidates": [*(discovery.get("candidates") or []), *extra], "excluded": excluded}


def _menu(discovery: dict[str, Any], manifest: dict[str, Any], states: dict[str, Any], deny: list[str],
          digest_inputs: dict[str, Any], all_: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if all_:
        discovery = _with_all(discovery, manifest)
    gated = gate(discovery, manifest, states, deny)
    records = _caps(manifest)
    limit = len(records) if all_ else K
    open_ = [c for c in gated["candidates"] if not c.get("blocked")][:limit]
    blocked = [c for c in gated["candidates"] if c.get("blocked")][:max(0, limit - len(open_))]
    entries: list[dict[str, Any]] = []
    for c in open_:
        cap = records[c["id"]]
        e = {k: c[k] for k in ("id", "kind", "gate", "tier", "fit", "available", "reason")}
        e["adds"] = _adds(cap.get("adds_beyond_native", ""))
        risk = _risk(c["id"], cap)
        if risk:
            e["risk"] = risk
        if "note" in c:
            e["note"] = c["note"]
        entries.append(e)
    for c in blocked:
        entries.append({k: c[k] for k in ("id", "kind", "tier", "fit", "available", "reason", "blocked", "why")})
    excluded = gated["excluded"] if all_ else gated["excluded"][:MAX_EXCLUDED]
    shown = [e["id"] for e in entries]
    comps = digest_components(gated, shown, manifest, states, deny=deny, digest_inputs=digest_inputs, all_=all_)
    out: dict[str, Any] = {
        "schema": SCHEMA_CANDIDATES, "digest": digest(comps),
        "repo": {"langs": gated["langs"], "hint": gated["hint"]},
        "candidates": entries, "excluded": [dict(e) for e in excluded],
        "omitted": max(0, len(records) - len(entries) - len(excluded)), "none": NONE_TEXT}
    if gated["constraints"]:
        # explicit (--deny) is authoritative; inferred from the task text is best-effort and misses many
        out["constraints"] = {"explicit": gated["explicit"], "inferred": gated["inferred"]}
    if not all_:
        # over the cap: drop `adds` from the lowest-ranked entries first; ids and gates stay
        for e in reversed(entries):
            if len(encode(out)) <= MAX_BYTES:
                break
            e.pop("adds", None)
        while len(encode(out)) > MAX_BYTES and out["excluded"]:
            out["excluded"].pop()
            out["omitted"] += 1
    return out, gated, comps


def candidates(discovery: dict[str, Any], manifest: dict[str, Any], states: dict[str, Any], *,
               deny: list[str], digest_inputs: dict[str, Any], all_: bool = False) -> dict[str, Any]:
    """The gated menu: at most K entries and 1,800 bytes encoded (no cap with `all_`)."""
    return _menu(discovery, manifest, states, deny, digest_inputs, all_)[0]


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------
def select(cap_id: str, supplied_digest: str, discovery: dict[str, Any], manifest: dict[str, Any],
           states: dict[str, Any], *, deny: list[str], digest_inputs: dict[str, Any], all_: bool = False,
           log_dir: Path | None = None) -> tuple[dict[str, Any], int]:
    """Validate a selection against freshly recomputed gates. Runs nothing; returns (output, exit code).
    A malformed id or digest raises ValueError (a usage error: exit 2)."""
    if not isinstance(cap_id, str) or not (cap_id == NONE or ID_RE.match(cap_id)):
        raise ValueError("the capability id must look like repo-ai.verify, or be none")
    if not isinstance(supplied_digest, str) or not DIGEST_RE.match(supplied_digest):
        raise ValueError("--digest must be cd1: followed by 32 hex characters, from `capabilities candidates`")
    menu, gated, _ = _menu(discovery, manifest, states, deny, digest_inputs, all_)
    records = _caps(manifest)
    current = menu["digest"]
    out: dict[str, Any] = {"schema": SCHEMA_SELECTION, "invoked": False}
    code = ""
    if cap_id != NONE and cap_id not in records:  # G0; an unknown id is never echoed
        out.update(decision="unknown")
        rc = EXIT_REFUSED
    elif stale := _stale_components(supplied_digest, current):  # G1; component codes only, never values
        out.update(id=cap_id, decision="stale", actor="agent", changed=stale)
        rc = EXIT_STALE
    elif cap_id == NONE:
        out.update(digest=current, id=NONE, decision="none", actor="agent")
        rc = EXIT_OK
    else:
        out.update(digest=current, id=cap_id)
        offered = {e["id"]: e for e in menu["candidates"]}
        refused = {e["id"]: e["why"] for e in gated["excluded"]}
        refused.update({c["id"]: c["why"] for c in gated["candidates"] if c.get("blocked")})
        entry = offered.get(cap_id)
        if cap_id in refused:  # G2
            code = refused[cap_id]
            out.update(decision="refused", code=code)
            rc = EXIT_REFUSED
        elif entry is None:
            out.update(decision="not-offered")
            rc = EXIT_REFUSED
        else:
            cap = records[cap_id]
            code = activation(cap_id, cap, states.get(cap_id))  # the current gate decides, never the menu
            argv = _argv(cap_id, cap)
            if code == "ok" and argv is not None:
                out.update(decision="ready", actor="agent", argv=argv)
                if cap_id in APPEND:
                    out["append"] = APPEND[cap_id]
                note = entry.get("note") or (VERIFY_NOTE if cap_id == "repo-ai.verify" else "")
                if note:
                    out["note"] = note
                rc = EXIT_OK
            else:
                code = code if code != "ok" else "needs-authorization"
                out.update(decision="human", actor="human", code=code, text=HUMAN_TEXT[code], docs=DOCS)
                rc = EXIT_HUMAN
    _log(log_dir, {"event": "select", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "digest": current, "task_sha256": _task16(digest_inputs),
                   "deny": sorted({str(d) for d in deny}), "ids": [e["id"] for e in menu["candidates"]],
                   "id": cap_id if cap_id == NONE or cap_id in records else "", "decision": out["decision"],
                   "code": code, "actor_env": [k for k in SELECT_AGENT_ENV if os.environ.get(k)]})
    return out, rc


def _task16(digest_inputs: dict[str, Any]) -> str:
    t = str(digest_inputs.get("task_sha256", ""))[:16]
    return t if len(t) == 16 and _HEX.match(t) else ""


def _log(log_dir: Path | None, record: dict[str, Any]) -> None:
    """One line, no task text and no paths, mode 0600, last LOG_LINES kept. Fails open."""
    if log_dir is None:
        return
    try:
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = log_dir / LOG_NAME
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(encode(record) + "\n")
        lines = path.read_text("utf-8").splitlines()
        if len(lines) > LOG_LINES:
            tmp = path.with_suffix(".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines[-LOG_LINES:]) + "\n")
            os.replace(tmp, path)
    except (OSError, ValueError):
        return


def render_text(obj: dict[str, Any]) -> str:
    """Plain text for a person at a terminal; built from the same closed fields as the JSON."""
    if obj.get("schema") == SCHEMA_CANDIDATES:
        lines = [f"candidates (experimental; digest {obj['digest']}):"]
        for e in obj["candidates"]:
            state = e["why"] if e.get("blocked") else (e["gate"] if e["gate"] == "ready" else e["reason"])
            lines.append(f"  {e['id']} [{state}] {e['tier']}" + (f": {e['adds'][:60]}" if e.get("adds") else ""))
        if not obj["candidates"]:
            lines.append("  none: your own tools are the default")
        lines.append("choose one with: repo-ai capabilities select <id|none> --digest <digest> (same task)")
        return "\n".join(lines)
    d = obj.get("decision", "")
    if d == "ready":
        return f"ready: {' '.join(obj['argv'])}" + (f" (add the {obj['append']})" if obj.get("append") else "") + (
            f"\n  {obj['note']}" if obj.get("note") else "")
    if d == "human":
        return f"for the user ({obj['code']}): {obj['text']}"
    if d == "stale":
        return "stale: " + ", ".join(obj.get("changed", [])) + " changed; call candidates again"
    if d == "refused":
        return f"refused: {obj.get('code', '')}"
    return d
