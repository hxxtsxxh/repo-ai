"""Capability-based provider routing for zero, one or many installed coding agents.

Routing is deterministic and explainable. Every considered provider gets a list of
reasons, and "no agent" / "not authorized" are first-class outcomes rather than a
silent fallback to some default provider. Choosing a provider is separate from
authorizing it: only providers the user authorized (per-run flag, or the persisted
per-project allowlist) can be selected for live execution.

Only readiness facts that were actually evaluated are reported; stages that need a
live run (protocol-validated, edit-proven) are never inferred here.

Each provider also gets an explicit ``readiness`` state:

  NOT_INSTALLED             no executable on PATH
  INSTALLED_UNPROBED        installed and isolatable; authentication/quota never observed (the honest default)
  AVAILABLE_BUT_UNAUTHORIZED  usable, but the user has not consented to live use
  SETUP_REQUIRED            the provider has no login repo-ai's isolation can use (checked offline: whether a
                            token variable is set or a dedicated login directory exists; no credential is read)
  AUTHORIZED_BUT_UNREADY    a recent live attempt showed missing/failed login
  USAGE_LIMITED             a recent live attempt hit a quota/rate limit (expires)
  ACCOUNT_INELIGIBLE        a recent live attempt showed the account/tier is not entitled
  RUNTIME_UNSUPPORTED       this provider has no supported containment on this platform
  ISOLATION_BLOCKED         untrusted/unidentifiable executable, or no sandbox on this host
  READY                     a recent live run of this exact binary succeeded (expires; not a guarantee)
  UNKNOWN                   no information

Observations are cached with an expiry and the executable's identity; a changed binary discards them.
Computing readiness never starts a provider and never makes a billable call.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..fsutil import atomic_write
from .adapters import _execution_sandbox_prefix, contract_for
from .discovery import PROVIDERS, discover

POLICY_SCHEMA = "repo-ai.provider-policy/1"
DEFAULT_ORDER = ("bob", "claude", "codex", "agy", "gemini", "opencode")
COOLDOWN_SECONDS = 3600.0
OBSERVATION_TTL = {"READY": 86_400.0, "USAGE_LIMITED": COOLDOWN_SECONDS, "AUTHORIZED_BUT_UNREADY": 3600.0,
                   "ACCOUNT_INELIGIBLE": 43_200.0}
READINESS_STATES = ("NOT_INSTALLED", "INSTALLED_UNPROBED", "SETUP_REQUIRED", "AVAILABLE_BUT_UNAUTHORIZED", "AUTHORIZED_BUT_UNREADY",
                    "USAGE_LIMITED", "ACCOUNT_INELIGIBLE", "RUNTIME_UNSUPPORTED", "ISOLATION_BLOCKED", "READY", "UNKNOWN")
_BLOCKING = frozenset({"NOT_INSTALLED", "SETUP_REQUIRED", "AUTHORIZED_BUT_UNREADY", "USAGE_LIMITED", "ACCOUNT_INELIGIBLE",
                       "RUNTIME_UNSUPPORTED", "ISOLATION_BLOCKED", "UNKNOWN"})
# Stable coarse vocabulary for scripts. ``readiness`` stays authoritative and unchanged. ISOLATED_READY means
# installed and containable by repo-ai's sandbox; it is NOT proof of login or quota (see ``not_evaluated``).
# repo-ai has no un-isolated "host" execution path, so there is deliberately no HOST_READY.
STATUS_CLASS = {
    "NOT_INSTALLED": "NOT_INSTALLED", "AVAILABLE_BUT_UNAUTHORIZED": "NOT_AUTHORIZED",
    "SETUP_REQUIRED": "BLOCKED_AUTH", "AUTHORIZED_BUT_UNREADY": "BLOCKED_AUTH", "ACCOUNT_INELIGIBLE": "BLOCKED_AUTH", "USAGE_LIMITED": "BLOCKED_QUOTA",
    "ISOLATION_BLOCKED": "BLOCKED_SANDBOX", "RUNTIME_UNSUPPORTED": "UNSUPPORTED",
    "INSTALLED_UNPROBED": "ISOLATED_READY", "READY": "ISOLATED_READY", "UNKNOWN": "UNKNOWN",
}
_MAX_POLICY_BYTES = 65_536


def policy_path(root: Path) -> Path:
    from ..config import load_config
    from ..paths import resolve_layout
    return resolve_layout(root, load_config(root)).state_dir / "providers.json"


def load_policy(root: Path) -> dict[str, Any]:
    """Return the persisted per-project provider policy; absent or corrupt means 'no policy'."""
    path = policy_path(root)
    empty: dict[str, Any] = {"schema": POLICY_SCHEMA, "exists": False, "authorized": [], "preferred": [], "cooldown": {},
                             "observations": {}}
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_POLICY_BYTES:
            return empty
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict) or raw.get("schema") != POLICY_SCHEMA:
        return empty
    authorized = [p for p in raw.get("authorized", []) if p in PROVIDERS]
    preferred = [p for p in raw.get("preferred", []) if p in PROVIDERS]
    cooldown = {k: float(v) for k, v in (raw.get("cooldown") or {}).items()
                if k in PROVIDERS and isinstance(v, (int, float)) and not isinstance(v, bool)}
    observations: dict[str, dict[str, Any]] = {}
    raw_obs = raw.get("observations")
    for name, obs in (raw_obs.items() if isinstance(raw_obs, dict) else []):
        if (name in PROVIDERS and isinstance(obs, dict) and obs.get("state") in OBSERVATION_TTL
                and isinstance(obs.get("until"), (int, float)) and not isinstance(obs.get("until"), bool)
                and isinstance(obs.get("identity"), str) and len(obs["identity"]) <= 128):
            observations[name] = {"state": obs["state"], "until": float(obs["until"]), "identity": obs["identity"]}
    return {"schema": POLICY_SCHEMA, "exists": True, "authorized": authorized, "preferred": preferred,
            "cooldown": cooldown, "observations": observations}


def _save(root: Path, policy: dict[str, Any]) -> None:
    body = {k: policy.get(k, {} if k in {"cooldown", "observations"} else []) for k in
            ("authorized", "preferred", "cooldown", "observations")}
    body["schema"] = POLICY_SCHEMA
    atomic_write(policy_path(root), json.dumps(body, indent=2, sort_keys=True) + "\n")


def authorize(root: Path, provider: str, *, prefer: bool = False) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ValueError("unknown provider")
    policy = load_policy(root)
    if provider not in policy["authorized"]:
        policy["authorized"].append(provider)
    if prefer and provider not in policy["preferred"]:
        policy["preferred"].append(provider)
    _save(root, policy)
    return load_policy(root)


def revoke(root: Path, provider: str) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ValueError("unknown provider")
    policy = load_policy(root)
    policy["authorized"] = [p for p in policy["authorized"] if p != provider]
    policy["preferred"] = [p for p in policy["preferred"] if p != provider]
    _save(root, policy)
    return load_policy(root)


def note_rate_limited(root: Path, provider: str, *, now: float | None = None) -> None:
    """Remember a quota/rate-limit observation so routing skips that provider for a while."""
    if provider not in PROVIDERS:
        return
    policy = load_policy(root)
    policy["cooldown"][provider] = (time.time() if now is None else now) + COOLDOWN_SECONDS
    _save(root, policy)


def note_observation(root: Path, provider: str, state: str, identity: str, *, now: float | None = None) -> None:
    """Cache one live-run observation (READY / USAGE_LIMITED / ...) with an expiry, bound to the binary identity."""
    if provider not in PROVIDERS or state not in OBSERVATION_TTL:
        return
    policy = load_policy(root)
    policy["observations"][provider] = {"state": state, "identity": str(identity)[:128],
                                        "until": (time.time() if now is None else now) + OBSERVATION_TTL[state]}
    _save(root, policy)


def classify_failure(reasons: list[str]) -> str | None:
    """Map provider failure text to a cacheable state; None when the failure says nothing about the account."""
    text = " ".join(reasons).lower()
    if any(k in text for k in ("ineligible", "not eligible", "entitlement")):
        return "ACCOUNT_INELIGIBLE"
    if any(k in text for k in ("not logged in", "authentication", "unauthenticated", "please log in", "login required")):
        return "AUTHORIZED_BUT_UNREADY"
    if any(k in text for k in ("rate limit", "usage limit", "spend limit", "quota")):
        return "USAGE_LIMITED"
    return None


def _isolated_ready(provider: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="repo-ai-route-") as d:
        base = Path(d)
        return _execution_sandbox_prefix(base, base, allow_network=True, provider=provider, live=True) is not None


def setup_problems(provider: str) -> list[str]:
    """Offline: what stops repo-ai's isolation from authenticating this provider at all. Reads no secret."""
    if provider == "claude":
        from . import claude_auth
        return list(claude_auth.plan().problems)
    if provider == "opencode":
        from . import opencode_cfg
        return opencode_cfg.setup_problems()
    return []


def _readiness(name: str, prof: dict[str, Any], installed: bool, isolated: bool, limited: bool,
               obs: dict[str, Any] | None, consented: bool, setup_missing: bool = False) -> str:
    if not prof:
        return "UNKNOWN"
    stage = prof.get("stage")
    if stage == "NOT_INSTALLED":
        return "NOT_INSTALLED"
    if stage == "BLOCKED":
        return "ISOLATION_BLOCKED"
    if not installed:
        return "UNKNOWN"
    if not isolated:
        return ("RUNTIME_UNSUPPORTED" if name in {"agy", "opencode"} and not sys.platform == "darwin"
                else "ISOLATION_BLOCKED")
    if setup_missing:
        return "SETUP_REQUIRED"
    if limited or (obs and obs["state"] == "USAGE_LIMITED"):
        return "USAGE_LIMITED"
    if obs and obs["state"] in {"ACCOUNT_INELIGIBLE", "AUTHORIZED_BUT_UNREADY"}:
        return obs["state"]
    if not consented:
        return "AVAILABLE_BUT_UNAUTHORIZED"
    return "READY" if obs and obs["state"] == "READY" else "INSTALLED_UNPROBED"


def route(root: Path, *, max_cost_usd: float = 0.0, run_authorized: bool = False,
          preferred: list[str] | None = None, now: float | None = None,
          profiles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Decide which provider (if any) may run live. Never invokes a model, never reads credentials.

    outcome: SELECTED | NO_AGENT (nothing usable installed/ready) | NOT_AUTHORIZED (usable, but no consent).
    """
    root = root.resolve()
    policy = load_policy(root)
    clock = time.time() if now is None else now
    found = profiles if profiles is not None else discover(root, probe=False)
    by_name = {p["provider"]: p for p in found}
    order: list[str] = []
    for name in [*(preferred or []), *policy["preferred"], *DEFAULT_ORDER, *PROVIDERS]:
        if name in PROVIDERS and name not in order:
            order.append(name)
    considered: list[dict[str, Any]] = []
    usable: list[str] = []
    selectable: list[str] = []
    for name in order:
        prof = by_name.get(name) or {}
        contract = contract_for(name)
        reasons: list[str] = []
        installed = prof.get("stage") == "DISCOVERED"
        if not installed:
            reasons.append(f"not usable: {prof.get('status', 'NOT_INSTALLED')}")
        ready = installed and _isolated_ready(name)
        if installed and not ready:
            reasons.append("no isolation sandbox that restricts this provider on this platform")
        limited = policy["cooldown"].get(name, 0.0) > clock
        if limited:
            reasons.append("recent quota/rate-limit observation; cooling down")
        obs = policy["observations"].get(name)
        stale = False
        if obs and (obs["until"] <= clock or obs["identity"] != (prof.get("identity_sha256") or "")):
            obs, stale = None, True  # expired, or recorded for a different binary
        hard_budget = bool(contract.enforces_hard_usd_budget)
        if max_cost_usd > 0 and not hard_budget:
            reasons.append("cannot enforce a USD ceiling (cost is not capped by the CLI)")
        if run_authorized:
            # a per-run flag authorizes any provider unless the project persisted an allowlist
            consented = not policy["authorized"] or name in policy["authorized"]
        else:
            consented = name in policy["authorized"]
        setup = setup_problems(name) if installed else []
        reasons.extend(f"setup required: {p}" for p in setup)
        readiness = _readiness(name, prof, installed, bool(ready), limited, obs, consented, bool(setup))
        if obs and obs["state"] in _BLOCKING:
            reasons.append(f"recent live observation: {obs['state']}")
        capable = (installed and ready and not limited and readiness not in _BLOCKING
                   and not (max_cost_usd > 0 and not hard_budget))
        if capable:
            usable.append(name)
            if not consented:
                reasons.append("not authorized (use --allow-live-provider, or `repo-ai agents authorize " + name + "`)")
            else:
                selectable.append(name)
        considered.append({
            "provider": name, "installed": installed, "isolated_ready": bool(ready), "cooling_down": limited,
            "readiness": readiness, "status_class": STATUS_CLASS.get(readiness, "UNKNOWN"),
            "observation_stale": stale, "auth_observed": bool(obs and obs["state"] == "READY"),
            "hard_usd_budget": hard_budget, "authorized": consented, "eligible": name in selectable,
            "cost_semantics": "enforced ceiling" if hard_budget else "UNKNOWN (not enforceable by the CLI)",
            "reasons": reasons or ["eligible"],
        })
    if selectable:
        outcome, selected = "SELECTED", selectable[0]
        why = f"{selected}: first eligible provider in order {', '.join(order[:5])}"
    elif usable:
        outcome, selected = "NOT_AUTHORIZED", None
        why = "usable provider(s) exist (" + ", ".join(usable) + ") but none is authorized for live execution"
    else:
        outcome, selected = "NO_AGENT", None
        why = "no installed provider is ready, within the cost policy and not rate-limited; repo-ai continues offline"
    return {"schema": "repo-ai.provider-route/1", "outcome": outcome, "selected": selected, "why": why,
            "policy_present": policy["exists"], "considered": considered,
            "not_evaluated": ["authenticated", "quota_remaining", "protocol_validated", "edit_proven"]}


__all__ = ["DEFAULT_ORDER", "READINESS_STATES", "STATUS_CLASS", "authorize", "classify_failure", "load_policy", "note_observation",
           "note_rate_limited", "revoke", "route", "policy_path", "setup_problems"]
