"""Skill autonomy policy: how much the Skill Intelligence Network may do on its own.

One explicit level per checkout, inspectable (`repo-ai skills policy show`) and
revocable (`repo-ai skills policy revoke`):

| level           | network discovery | install with a per-hash approval | autopilot installs on its own        |
|-----------------|-------------------|----------------------------------|--------------------------------------|
| `OFFLINE`       | refused           | local sources only               | nothing                              |
| `DISCOVER_ONLY` | allowed           | refused                          | nothing                              |
| `PROPOSE`       | allowed           | allowed                          | nothing; it proposes (the default)   |
| `SAFE_AUTO`     | allowed           | allowed                          | inert SKILL.md-only skills, only     |
| `TRIAL`         | allowed           | allowed                          | nothing; inert ones proposed for a trial |
| `MANUAL_ONLY`   | allowed           | allowed, full 64-hex hash only   | nothing; autopilot proposes nothing  |

Live trials (`skills benchmark` / `tournament`, which call a model) are refused
under `OFFLINE` and `DISCOVER_ONLY`, and keep their own `--max-cost-usd` cap
everywhere else.

What no level changes: anything with scripts, hooks, MCP servers, plugins,
binaries, provider adapters, static tools, external accounts, permission
changes or network execution needs a per-capability approval at every level
(`capbundle.assess`). A static scanner's `eligible` is never treated as safe:
`SAFE_AUTO` needs the structural inertness check as well.

Where it lives: the machine-local directory for this checkout
(`registry.machine_dir`), never the repository. A cloned repository can commit
anything under `.repo-ai/`, so a committed file must not be able to grant
itself `SAFE_AUTO`. Raising the level to `SAFE_AUTO` or `TRIAL` is refused from
an agent shell, hook or CI, or without a terminal; lowering it and `revoke` are
always allowed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SCHEMA = "repo-ai.skills-policy/1"
LEVELS = ("OFFLINE", "DISCOVER_ONLY", "PROPOSE", "SAFE_AUTO", "TRIAL", "MANUAL_ONLY")
DEFAULT = "PROPOSE"
RAISING = frozenset({"SAFE_AUTO", "TRIAL"})  # levels that let repo-ai act with less asking
FILE_NAME = "skills-policy.json"
HISTORY_KEEP = 20

DESCRIPTIONS = {
    "OFFLINE": "no network use; installs from local sources only, each with a per-hash approval",
    "DISCOVER_ONLY": "discovery and vetting only; nothing is installed",
    "PROPOSE": "repo-ai proposes; every install needs your approval of a content hash",
    "SAFE_AUTO": "autopilot may install inert, pinned, SKILL.md-only skills into repo-ai-owned "
                 "project scope; everything else needs your approval",
    "TRIAL": "like PROPOSE; autopilot proposes inert candidates for a budget-capped trial",
    "MANUAL_ONLY": "no automation; installs need the full 64-hex content hash",
}


class PolicyError(RuntimeError):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def policy_path(root: Path) -> Path:
    from .registry import machine_dir
    return machine_dir(root) / FILE_NAME


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _check_outside(root: Path) -> None:
    if _inside(policy_path(root), root):
        raise PolicyError("REPO_AI_HOME points inside this repository: a policy stored there could be "
                          "committed and forged by a clone. Point it outside the repository")


def load(root: Path) -> dict[str, Any]:
    """The current policy. A missing, unreadable or invalid file means the default."""
    path = policy_path(root)
    data: dict[str, Any] = {}
    note = ""
    if _inside(path, root):
        note = "REPO_AI_HOME is inside the repository: its policy file is ignored (default applies)"
    else:
        try:
            raw = json.loads(path.read_text("utf-8"))
            data = raw if isinstance(raw, dict) else {}
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            data, note = {}, "the policy file is unreadable: the default applies"
    level = data.get("level")
    if level not in LEVELS:
        if level is not None:
            note = f"unknown level {str(level)[:30]!r} in the policy file: the default applies"
        level = DEFAULT
    raw_history = data.get("history")
    history: list[Any] = raw_history if isinstance(raw_history, list) else []
    return {"schema": SCHEMA, "level": level, "default": level == DEFAULT and not data.get("level"),
            "set_at": data.get("set_at") if isinstance(data.get("set_at"), str) else None,
            "set_by": data.get("set_by") if isinstance(data.get("set_by"), str) else None,
            "description": DESCRIPTIONS[level], "path": str(path), "history": history[-HISTORY_KEEP:],
            **({"note": note} if note else {})}


def level(root: Path) -> str:
    return str(load(root)["level"])


def _agent_markers(env: dict[str, str]) -> list[str]:
    from .capabilities import AGENT_ENV
    return [k for k in AGENT_ENV if k in env]


def _save(root: Path, current: dict[str, Any], new_level: str, event: str, by: str) -> dict[str, Any]:
    from .fsutil import atomic_write
    _check_outside(root)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    history = list(current.get("history") or [])
    history.append({"at": now, "event": event, "from": current["level"], "to": new_level, "by": by})
    data = {"schema": SCHEMA, "level": new_level, "set_at": now, "set_by": by,
            "history": history[-HISTORY_KEEP:]}
    path = policy_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(path, json.dumps(data, indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - best effort on exotic filesystems
        pass
    return load(root)


def set_level(root: Path, new_level: str, *, env: dict[str, str] | None = None,
              interactive: bool = True) -> dict[str, Any]:
    """Set the level. Raising it (SAFE_AUTO, TRIAL) needs a human in a terminal."""
    wanted = str(new_level or "").strip().upper().replace("-", "_")
    if wanted not in LEVELS:
        raise PolicyError(f"unknown level {new_level!r}; choose one of: {', '.join(LEVELS)}")
    env = dict(os.environ) if env is None else env
    if wanted in RAISING:
        agent = _agent_markers(env)
        if agent:
            raise PolicyError(f"refusing to raise the skill policy to {wanted} from an agent shell, hook or CI "
                              f"({', '.join(agent)} is set): run this command yourself in a terminal", 5)
        if not interactive:
            raise PolicyError(f"refusing to raise the skill policy to {wanted} without a terminal (stdin is "
                              "not a TTY): run this command yourself in a terminal", 5)
    current = load(root)
    return _save(root, current, wanted, "set", "user (terminal)" if wanted in RAISING else "user")


def revoke(root: Path) -> dict[str, Any]:
    """Back to the default. Always allowed, from anywhere: revoking only reduces autonomy."""
    current = load(root)
    return _save(root, current, DEFAULT, "revoke", "user")


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------
def network_allowed(lvl: str) -> bool:
    return lvl != "OFFLINE"


def install_problem(lvl: str, *, remote: bool, approve: str) -> str:
    """Why an explicit install is refused under this level ('' when allowed)."""
    if lvl == "DISCOVER_ONLY":
        return "the skill policy is DISCOVER_ONLY: nothing is installed (repo-ai skills policy set PROPOSE)"
    if lvl == "OFFLINE" and remote:
        return "the skill policy is OFFLINE: installing a remote skill needs the network"
    if lvl == "MANUAL_ONLY" and len(approve or "") != 64:
        return "the skill policy is MANUAL_ONLY: --approve must name the full 64-hex content hash"
    return ""


def trial_problem(lvl: str) -> str:
    if lvl in {"OFFLINE", "DISCOVER_ONLY"}:
        return f"the skill policy is {lvl}: live trials call a model and are refused"
    return ""


def decide(lvl: str, assessment: dict[str, Any], *, nominated: bool = False,
           recommended: bool = False) -> dict[str, Any]:
    """What autopilot may do with one vetted candidate.

    actions: `auto_install` (SAFE_AUTO, inert only), `propose_install`,
    `propose_trial` (TRIAL, inert only), `needs_approval` (not inert),
    `refuse` (blocked or not installable), `none` (level does nothing).
    """
    inert = bool(assessment.get("inert"))
    installable = bool(assessment.get("installable"))
    wanted = nominated or recommended
    reasons = list(assessment.get("reasons") or [])
    if not installable:
        return {"action": "refuse", "reasons": reasons or ["not installable"]}
    if lvl == "MANUAL_ONLY":
        return {"action": "none", "reasons": ["MANUAL_ONLY: autopilot proposes nothing"]}
    if lvl in {"OFFLINE", "DISCOVER_ONLY"}:
        return {"action": "none", "reasons": [f"{lvl}: autopilot installs nothing"]}
    if not inert:
        return {"action": "needs_approval",
                "reasons": ["not inert, so a per-capability approval is required at every level", *reasons]}
    if not wanted:
        return {"action": "none", "reasons": ["not recommended for an evidence-backed gap, and not named"]}
    if lvl == "SAFE_AUTO":
        return {"action": "auto_install", "reasons": ["inert, pinned SKILL.md-only skill under SAFE_AUTO"]}
    if lvl == "TRIAL":
        return {"action": "propose_trial", "reasons": ["inert: a budget-capped trial can measure it first"]}
    return {"action": "propose_install", "reasons": ["inert; PROPOSE needs your approval of its hash"]}
