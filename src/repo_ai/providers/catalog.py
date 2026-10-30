"""The provider catalog: which coding agents exist and what repo-ai can honestly do with each.

Reading it never executes anything: detection is a PATH lookup only, and a repository-owned executable is reported
as untrusted rather than as installed. An installed agent repo-ai has no adapter for is reported as such, never as
usable (0/1/many detection without logo inflation).
"""
from __future__ import annotations

import json
import os
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

SCHEMA = "repo-ai.provider-catalog/1"
REPO_AI_STATES = ("EXECUTION", "BLOCKED", "PLANNED", "UNSUPPORTED")
UPSTREAM = ("HEADLESS_CLI", "HOST_ONLY", "CONTEXT_SKILLS_ONLY", "REMOTE_SERVICE", "DISCONTINUED", "UNKNOWN")
BASES = ("observed", "docs")


def load() -> dict[str, Any]:
    data = json.loads(resources.files("repo_ai.providers").joinpath("catalog.json").read_text("utf-8"))
    problems = validate(data)
    if problems:
        raise ValueError("invalid provider catalog: " + "; ".join(problems[:5]))
    return data


def validate(data: Any) -> list[str]:
    from .discovery import PROVIDERS
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("providers"), list):
        return ["not a provider catalog"]
    problems = []
    ids = [p.get("id") for p in data["providers"] if isinstance(p, dict)]
    if len(ids) != len(set(ids)):
        problems.append("duplicate ids")
    for p in data["providers"]:
        pid = p.get("id")
        if p.get("repo_ai") not in REPO_AI_STATES or p.get("upstream") not in UPSTREAM or p.get("basis") not in BASES:
            problems.append(f"{pid}: unknown state")
        if p.get("repo_ai") in {"EXECUTION", "BLOCKED"} and (pid not in PROVIDERS or p.get("basis") != "observed"):
            problems.append(f"{pid}: {p.get('repo_ai')} needs a repo-ai adapter and an observation")
        if pid in PROVIDERS and p.get("repo_ai") not in {"EXECUTION", "BLOCKED"}:
            problems.append(f"{pid}: has an adapter but is labelled {p.get('repo_ai')}")
    missing = set(PROVIDERS) - set(ids)
    if missing:
        problems.append("adapters missing from the catalog: " + ", ".join(sorted(missing)))
    return problems


def detect(root: Path, catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Each catalog entry with whether one of its executables is on PATH. No subprocess is started."""
    catalog = catalog or load()
    root = root.resolve()
    rows = []
    for entry in catalog["providers"]:
        found = None
        untrusted = False
        for name in entry.get("executables") or []:
            path = shutil.which(name)
            if not path:
                continue
            resolved = Path(os.path.abspath(path)).resolve()
            if resolved == root or root in resolved.parents:
                untrusted = True
                continue
            found = str(resolved)
            break
        if found and entry["repo_ai"] in {"EXECUTION", "BLOCKED"}:
            presence = "INSTALLED"
        elif found:
            presence = "INSTALLED_NO_ADAPTER"
        else:
            presence = "UNTRUSTED_EXECUTABLE" if untrusted else "NOT_FOUND"
        rows.append({**entry, "presence": presence, "executable": found})
    return rows


__all__ = ["REPO_AI_STATES", "SCHEMA", "detect", "load", "validate"]
