"""Completion gate for coding agents (Claude Code / Codex ``Stop`` hooks).

Silent (exit 0, no output) unless the working tree holds behavioural code
changes with no passing verification evidence for that exact change. Then
it blocks the stop **once per change** with a short reason naming the
command to run. It never blocks twice for the same change, never more than
`verify_gate_max_blocks` times in one agent session, never while the agent
is already continuing because of a stop hook, and fails open on any error:
a broken gate must not trap an agent.

Evidence also covers a later rewrite that cannot change behaviour (a
formatter run by another Stop hook, say): see
`changes.semantic_fingerprint`.

A pass counts only while the test environment it was made in is still
installed (`evidence.environment_check`: the metadata of the recorded
paths; the gate never runs an interpreter or repository code). A pass that
went stale that way is shown once more, as unverified.
"""

from __future__ import annotations

import json
from pathlib import Path

from .evidence import PASSING_VERDICTS as PASSING  # noqa: E402  (one definition of "passed")


def gate(root: Path, layout, payload: str, mode: str = "block", max_blocks: int = 3) -> int:
    """`repo-ai verify --gate`: print the decision (if any); always exit 0."""
    try:
        data = json.loads(payload) if payload.strip() else {}
    except ValueError:
        data = {}
    out = decision(root, layout, data if isinstance(data, dict) else {}, mode=mode, max_blocks=max_blocks)
    if out:
        print(out)
    return 0


def decision(root: Path, layout, data: dict, mode: str = "block", max_blocks: int = 3) -> str:
    """The Stop-hook JSON to emit, or "" to stay silent. `mode`: "block"
    (default) asks the agent to verify, once per change and at most
    `max_blocks` times per session (`data["session_id"]`); "report" never
    blocks and shows the person one line about the change's evidence."""
    if data.get("stop_hook_active"):
        return ""
    try:
        from . import changes, evidence
        change = changes.detect(root, "HEAD")
        code = [f for f in change.files if f.behavioral and not f.binary and
                f.suffix in {".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx"}]
        if not code:
            return ""
        rec = evidence.latest(layout.state_dir) or {}
        if rec.get("fingerprint") != change.fingerprint:  # the latest may be another session's run
            rec = evidence.for_fingerprint(layout.state_dir, change.fingerprint) or rec
        same = bool(rec) and rec.get("fingerprint") == change.fingerprint
        if rec and not same:
            semantic = changes.semantic_fingerprint(root, "HEAD")
            if semantic and rec.get("semantic_fingerprint") == semantic:
                same = True
            elif semantic:  # a formatter-only rewrite of a change verified before another session's run
                older = evidence.for_fingerprint(layout.state_dir, change.fingerprint, semantic=semantic)
                if older is not None:
                    rec, same = older, True
        moved = ""  # the pass was made in a test environment that has changed since (X13b)
        if same and str(rec.get("verdict", "")).startswith(PASSING):
            status, detail = evidence.environment_check(rec, root)
            if status == "unchanged":
                return ""
            moved = detail
        # shown once per change, and once more when a pass of it goes stale
        static = rec.get("environment_static")
        token = change.fingerprint + (f":env:{static.get('digest', '') if isinstance(static, dict) else ''}"
                                      if moved else "")
        state_path = layout.state_dir / "gate.json"
        state = _load(state_path)
        if token in state["seen"]:
            return ""
        session = str(data.get("session_id") or "")[:200]
        blocks = state["blocks"].get(session, 0)
        if mode != "report" and blocks >= max(0, int(max_blocks)):
            return ""  # a hard bound per session, whatever the fingerprint churn
        state["seen"] = (state["seen"] + [token])[-50:]
        if mode != "report":
            state["blocks"].pop(session, None)
            state["blocks"][session] = blocks + 1
            state["blocks"] = dict(list(state["blocks"].items())[-20:])
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), "utf-8")
        why = (f"passed in a test environment that has changed since ({moved}), so it is unverified now" if moved
               else "fails" if same else "has no verification evidence")
        names = ", ".join(f.path for f in code[:4]) + (f" (+{len(code) - 4} more)" if len(code) > 4 else "")
        if mode == "report":
            verdict = str(rec.get("verdict")) if same else ""
            line = (f"repo-ai: the change to {names} {why} (`repo-ai verify --run` runs its tests again)" if moved else
                    f"repo-ai: the last verification of this exact change to {names}: {verdict}" if verdict else
                    f"repo-ai: the change to {names} has no verification evidence (`repo-ai verify` previews "
                    "the tests, `repo-ai verify --run` runs them sandboxed)")
            return json.dumps({"systemMessage": line})
        reason = (f"repo-ai: the current change to {names} {why}. Run `repo-ai verify --run` to execute the "
                  "tests that can show whether it broke something (sandboxed; `repo-ai verify` previews "
                  "them), then report the result. If verification is impossible here, say so instead "
                  "of claiming the change works. (Shown once per change.)")
        return json.dumps({"decision": "block", "reason": reason})
    except Exception:  # noqa: BLE001 - fail open
        return ""


def _load(path: Path) -> dict:
    """{"seen": [fingerprints already shown], "blocks": {session: count}};
    the list-only form written before 0.7.7's session cap is read as "seen"."""
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, list):
        data = {"seen": data}
    if not isinstance(data, dict):
        data = {}
    seen = [x for x in data.get("seen", []) if isinstance(x, str)] if isinstance(data.get("seen"), list) else []
    raw = data.get("blocks")
    blocks: dict = raw if isinstance(raw, dict) else {}
    return {"seen": seen, "blocks": {str(k): v for k, v in blocks.items() if isinstance(v, int)}}
