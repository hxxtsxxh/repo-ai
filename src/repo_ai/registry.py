"""Cross-repository registry and portable pattern library (opt-in).

Nothing here runs unless the user registers a repository. The default is no
registration and no sharing. repo-ai never discovers repositories on its own:
no scanning of home directories, cloud drives or corporate folders.

The registry lives outside every repository (`$REPO_AI_HOME`, else
`$XDG_DATA_HOME/repo-ai`, else `~/.local/share/repo-ai`) and is partitioned
into **zones** (`personal`, `work`, or any user-defined name):

* a repository belongs to exactly one zone;
* every cross-repository command reads only the current repository's zone;
* each zone has its own pattern library, so no repository names, paths,
  URLs, prompts or source text propagate between zones;
* zone policy decides whether opt-in model drafting is allowed. `work`
  denies it by default, and so does every user-defined zone. Only the
  `personal` zone allows it, and only after the user opts in.

Patterns are sanitized to stack signatures (languages, frameworks, test
frameworks), rule kinds and topics, generated-skill kinds and aggregate
outcome counts. They never contain paths, names, URLs or command text.
`repo-ai registry audit` checks these invariants.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

VERSION = 1
ZONE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
DEFAULT_POLICY = {
    "personal": {"llm": "allow", "patterns": "on", "discovery": "allow"},
    "work": {"llm": "deny", "patterns": "on", "discovery": "deny"},
}
# Unregistered repositories: no model drafting; online discovery only when
# explicitly requested (queries carry public technology names, never code).
FALLBACK_POLICY = {"llm": "deny", "patterns": "on", "discovery": "allow"}
PATTERN_KEYS = frozenset({"stack", "rules", "skills", "outcomes", "thirdparty", "repos", "updated",
                          "by_repo"})
_REPO_PATTERN_KEYS = frozenset({"stack", "rules", "skills", "outcomes", "thirdparty"})
_SUSPICIOUS = re.compile(r"(/|\\|https?:|@|\.(com|net|org|io|internal|corp|local)\b)", re.I)


class RegistryError(ValueError):
    pass


def registry_home() -> Path:
    env = os.environ.get("REPO_AI_HOME")
    if env:
        return Path(env)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "repo-ai"


def _zone_dir(zone: str) -> Path:
    if not ZONE_RE.match(zone):
        raise RegistryError(f"invalid zone name {zone!r} (lowercase letters, digits, hyphens)")
    return registry_home() / "zones" / zone


def machine_dir(root: Path) -> Path:
    """Machine-local state for one checkout, outside the repository: a cloned
    repository can commit anything under .repo-ai/, so state that steers
    repo-ai (tuning, the optimisation journal, radar results) lives here."""
    return registry_home() / "repos" / repo_id(root)


def repo_id(root: Path) -> str:
    """Identity of the directory itself (device + inode), not its spelling: on
    case-insensitive or symlinked paths two spellings are one repository."""
    try:
        st = os.stat(root)
        key = f"inode:{st.st_dev}:{st.st_ino}"
    except OSError:
        key = "path:" + os.path.normcase(str(root.resolve()))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _load_zone(zone: str) -> dict[str, Any]:
    path = _zone_dir(zone) / "registry.json"
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", VERSION)
    data.setdefault("zone", zone)
    data.setdefault("policy", dict(DEFAULT_POLICY.get(zone, FALLBACK_POLICY)))
    data.setdefault("repos", {})
    return data


def _save_zone(zone: str, data: dict[str, Any]) -> None:
    directory = _zone_dir(zone)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(registry_home(), 0o700)
    except OSError:
        pass
    _atomic_json(directory / "registry.json", data)


def _atomic_json(path: Path, data: Any) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def zones() -> list[str]:
    base = registry_home() / "zones"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and ZONE_RE.match(p.name))


def zone_of(root: Path) -> str | None:
    rid = repo_id(root)
    found = [z for z in zones() if rid in _load_zone(z)["repos"]]
    return found[0] if len(found) == 1 else (None if not found else "!conflict")


def policy_for(root: Path) -> tuple[str | None, dict[str, str]]:
    zone = zone_of(root)
    if zone == "!conflict":  # in two zones: deny everything until `registry audit` is fixed
        return zone, {"llm": "deny", "patterns": "off", "discovery": "deny"}
    if zone is None:
        return zone, dict(FALLBACK_POLICY)
    return zone, dict(_load_zone(zone)["policy"])


def llm_allowed(root: Path) -> tuple[bool, str]:
    zone, policy = policy_for(root)
    if zone == "!conflict":
        return False, "this repository is registered in more than one zone (run registry audit)"
    if policy.get("llm") != "allow":
        where = f"zone `{zone}`" if zone else "unregistered repositories"
        return False, (f"model drafting is denied for {where}. Register this repository in a "
                       "zone that allows it (`repo-ai registry add --zone personal`), or change "
                       "that zone's policy deliberately with `repo-ai registry policy`")
    return True, f"allowed by zone `{zone}`"


def add(root: Path, zone: str, label: str | None = None, move: bool = False) -> str:
    root = root.resolve()
    current = zone_of(root)
    if current == "!conflict":
        raise RegistryError("repository is in several zones; fix with `repo-ai registry audit`")
    if current and current != zone:
        if not move:
            raise RegistryError(f"already registered in zone `{current}`; zones do not share "
                                f"repositories (use --move to move it, which leaves `{current}`'s "
                                "pattern library untouched)")
        remove(root)
    data = _load_zone(zone)
    data["repos"][repo_id(root)] = {"path": str(root), "label": label or root.name,
                                    "added": int(time.time())}
    _save_zone(zone, data)
    return zone


def remove(root: Path) -> str | None:
    rid = repo_id(root)
    for zone in zones():
        data = _load_zone(zone)
        if rid in data["repos"]:
            del data["repos"][rid]
            _save_zone(zone, data)
            return zone
    return None


def set_policy(zone: str, key: str, value: str) -> dict[str, str]:
    allowed = {"llm": {"allow", "deny"}, "patterns": {"on", "off"}, "discovery": {"allow", "deny"}}
    if key not in allowed or value not in allowed[key]:
        raise RegistryError("policy keys: llm=allow|deny, patterns=on|off, discovery=allow|deny")
    data = _load_zone(zone)
    data["policy"][key] = value
    _save_zone(zone, data)
    return data["policy"]


def members(zone: str) -> list[dict[str, Any]]:
    data = _load_zone(zone)
    out = []
    for rid, entry in sorted(data["repos"].items(), key=lambda kv: kv[1].get("label", "")):
        path = Path(entry.get("path", ""))
        out.append({"id": rid, "label": entry.get("label", rid), "path": str(path),
                    "exists": path.is_dir(), "indexed": _index_for(path) is not None})
    return out


def purge(zone: str) -> bool:
    directory = _zone_dir(zone)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True


# --------------------------------------------------------------------------
# patterns (sanitized, per zone)
# --------------------------------------------------------------------------
def framework_names(facts: dict[str, Any]) -> list[str]:
    """facts.json lists frameworks as names (older builds: {"name": ...})."""
    out = set()
    for f in facts.get("frameworks") or []:
        name = f.get("name") if isinstance(f, dict) else f
        if isinstance(name, str) and name and len(name) <= 40:
            out.add(name)
    return sorted(out)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_HEX = re.compile(r"^[0-9a-f]{12,64}$")


def _sanitize_thirdparty(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public, pinned GitHub skills only: a local-path source would leak a path."""
    out = []
    for e in entries:
        src = e.get("source") or {}
        fields = [str(e.get("name", "")), str(src.get("owner", "")), str(src.get("repo", ""))]
        if src.get("provider") == "local" or not all(_SAFE_ID.match(f) for f in fields):
            continue
        commit, digest = str(src.get("commit") or ""), str(e.get("content_hash") or "")
        if not (_HEX.match(commit) and _HEX.match(digest)):
            continue
        from .portfolio import verified_evidence
        ev = verified_evidence(e)
        out.append({"name": fields[0], "owner": fields[1], "repo": fields[2], "commit": commit,
                    "content_hash": digest, "stage": str(e.get("stage", "canary"))[:12],
                    "evidence": str(ev.get("status", "not evaluated"))[:16],
                    "diff": ev.get("diff") if isinstance(ev.get("diff"), (int, float)) else None})
    return sorted(out, key=lambda x: str(x["name"]))[:20]


def sanitize_pattern(facts: dict[str, Any], rules: list[dict[str, Any]],
                     skills: list[str], outcomes: dict[str, Any],
                     thirdparty: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    langs = facts.get("languages") or []
    stack = sorted({str(x[0]) if isinstance(x, (list, tuple)) else str(x) for x in langs})[:6]
    frameworks = framework_names(facts)[:10]
    tests = sorted({str(s.get("framework")) for s in facts.get("test_suites") or []
                    if isinstance(s, dict) and s.get("framework")})
    by_status = outcomes.get("by_status", {}) if isinstance(outcomes, dict) else {}
    return {
        "stack": {"languages": stack, "frameworks": frameworks, "tests": tests},
        "rules": sorted({f"{r.get('kind')}:{r.get('topic') or '-'}" for r in rules}),
        "skills": sorted({re.sub(r"[^a-z0-9-]", "", s) for s in skills}),
        "outcomes": {k: int(v) for k, v in by_status.items() if isinstance(v, int)},
        "thirdparty": _sanitize_thirdparty(thirdparty or []),
    }


def stack_key(pattern: dict[str, Any]) -> str:
    s = pattern["stack"]
    return "|".join([",".join(s["languages"][:3]), ",".join(s["frameworks"][:4]),
                     ",".join(s["tests"][:2])])


def contribute(root: Path, facts: dict[str, Any], rules: list[dict[str, Any]],
               skills: list[str], outcomes: dict[str, Any],
               thirdparty: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    zone = zone_of(root)
    if zone in (None, "!conflict"):
        raise RegistryError("register this repository first: repo-ai registry add --zone <zone>")
    policy = _load_zone(zone)["policy"]
    if policy.get("patterns") != "on":
        raise RegistryError(f"zone `{zone}` has patterns turned off")
    pattern = sanitize_pattern(facts, rules, skills, outcomes, thirdparty)
    path = _zone_dir(zone) / "patterns.json"
    try:
        library = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        library = {}
    key = stack_key(pattern)
    contributors = set(library.get(key, {}).get("repos", []))
    me = hashlib.sha256((zone + repo_id(root)).encode()).hexdigest()[:10]
    contributors.add(me)
    # per-repository patterns (anonymous ids) so Stack Packs can count support
    by_repo = dict(library.get(key, {}).get("by_repo") or {})
    by_repo[me] = pattern
    library[key] = {**pattern, "repos": sorted(contributors), "by_repo": by_repo,
                    "updated": int(time.time())}
    _atomic_json(path, library)
    return {"zone": zone, "key": key, "pattern": pattern}


def patterns(zone: str) -> dict[str, Any]:
    try:
        data = json.loads((_zone_dir(zone) / "patterns.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def suggest(root: Path, facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Patterns from the *same zone* whose stack matches this repository."""
    zone = zone_of(root)
    if zone in (None, "!conflict"):
        return []
    mine = sanitize_pattern(facts, [], [], {})
    out = []
    for key, pat in patterns(zone).items():
        overlap = len(set(pat["stack"]["frameworks"]) & set(mine["stack"]["frameworks"])) + \
            len(set(pat["stack"]["languages"]) & set(mine["stack"]["languages"]))
        if overlap:
            out.append({"stack": key, "overlap": overlap, "rules": pat["rules"],
                        "skills": pat["skills"], "outcomes": pat["outcomes"],
                        "contributors": len(pat.get("repos", []))})
    return sorted(out, key=lambda p: (-p["overlap"], p["stack"]))[:5]


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------
def audit() -> dict[str, Any]:
    problems: list[str] = []
    seen: dict[str, str] = {}
    report: dict[str, Any] = {"home": str(registry_home()), "zones": []}
    for zone in zones():
        data = _load_zone(zone)
        z: dict[str, Any] = {"zone": zone, "policy": data["policy"], "repos": len(data["repos"]),
                             "patterns": 0, "missing_paths": 0}
        for rid, entry in data["repos"].items():
            path = Path(entry.get("path", ""))
            ident = repo_id(path) if path.is_dir() else rid
            for key in {rid, ident}:
                if key in seen and seen[key] != zone:
                    problems.append(f"repository {entry.get('label', rid)} is in zones "
                                    f"`{seen[key]}` and `{zone}`")
                seen.setdefault(key, zone)
            if not path.is_dir():
                z["missing_paths"] += 1
        for pat in patterns(zone).values():
            z["patterns"] += 1
            extra = set(pat) - PATTERN_KEYS
            by_repo = pat.get("by_repo") if isinstance(pat.get("by_repo"), dict) else {}
            for sub in by_repo.values():
                extra |= set(sub) - _REPO_PATTERN_KEYS if isinstance(sub, dict) else {"by_repo"}
            if extra:
                problems.append(f"zone `{zone}` pattern has unexpected fields {sorted(extra)}")
            for value in _strings({k: v for k, v in pat.items() if k != "repos"}):
                if _SUSPICIOUS.search(value):
                    problems.append(f"zone `{zone}` pattern contains a path/URL-like value "
                                    f"{value[:40]!r}")
        report["zones"].append(z)
    report["problems"] = sorted(set(problems))
    return report


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


# --------------------------------------------------------------------------
# cross-repository context and impact (one zone only)
# --------------------------------------------------------------------------
def _index_for(path: Path):
    for candidate in (path / ".repo-ai" / "state", path / ".bob" / "context"):
        if (candidate / "index.db").is_file():
            return candidate
    return None


def _open_readonly(state_dir: Path):
    import sqlite3
    # as_uri() percent-escapes `?`/`#` in the path, so mode=ro cannot be dropped.
    conn = sqlite3.connect((state_dir / "index.db").resolve().as_uri() + "?mode=ro", uri=True,
                           timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def peers(root: Path) -> tuple[str | None, list[dict[str, Any]]]:
    zone = zone_of(root)
    if zone in (None, "!conflict"):
        return zone, []
    me = repo_id(root)
    return zone, [m for m in members(zone) if m["id"] != me and m["exists"] and m["indexed"]]


def crossrepo_context(root: Path, task: str, per_repo: int = 3) -> dict[str, Any]:
    from .index import Index
    from .retrieval import search_task
    zone, others = peers(root)
    results = []
    for peer in others:
        state = _index_for(Path(peer["path"]))
        if state is None:
            continue
        index = Index.__new__(Index)
        index.conn = _open_readonly(state)
        try:
            found = search_task(index, task[:4000], max_files=per_repo, include_tests=False)
        finally:
            index.conn.close()
        if found.confidence in {"high", "medium"}:
            results.append({"repo": peer["label"], "confidence": found.confidence,
                            "files": [{"path": h.path, "why": h.reasons[:2]}
                                      for h in found.hits[:per_repo]]})
    return {"zone": zone, "searched": len(others), "results": results}


def crossrepo_impact(root: Path, index) -> dict[str, Any]:
    """Who in this zone consumes what this repository exposes: HTTP routes
    (matched to API-path literals) and the package this repository declares."""
    from .graph import route_matches
    zone, others = peers(root)
    my_routes = [dict(r) for r in index.routes(5000)]
    my_packages = _declared_package_names(root)
    links = []
    for peer in others:
        state = _index_for(Path(peer["path"]))
        if state is None:
            continue
        conn = _open_readonly(state)
        try:
            try:
                literals = conn.execute("SELECT path, url, line FROM url_refs").fetchall()
            except Exception:  # noqa: BLE001 - peer index from an older repo-ai
                literals = []
            deps = conn.execute("SELECT name, manifest FROM dependencies").fetchall()
        finally:
            conn.close()
        for lit in literals:
            for route in my_routes:
                if route_matches(lit["url"], route["path_pattern"]):
                    links.append({"repo": peer["label"], "kind": "consumes_api",
                                  "proof": "heuristic", "confidence": 0.6,
                                  "evidence": f"{lit['path']}:{lit['line']} \"{lit['url']}\"",
                                  "target": f"{route['method']} {route['path_pattern']} "
                                            f"({route['file']})"})
        for dep in deps:
            if dep["name"] in my_packages:
                links.append({"repo": peer["label"], "kind": "depends_on_package",
                              "proof": "manifest", "confidence": 1.0,
                              "evidence": f"{dep['manifest']} declares {dep['name']}",
                              "target": dep["name"]})
    return {"zone": zone, "searched": len(others), "links": links}


def _declared_package_names(root: Path) -> set[str]:
    names: set[str] = set()
    try:
        data = json.loads((root / "package.json").read_text("utf-8"))
        if isinstance(data.get("name"), str):
            names.add(data["name"])
    except (OSError, ValueError, AttributeError):
        pass
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        with (root / "pyproject.toml").open("rb") as fh:
            name = (tomllib.load(fh).get("project") or {}).get("name")
        if isinstance(name, str):
            names.add(name)
    except (OSError, ValueError):
        pass
    for path in sorted(root.glob("packages/*/package.json"))[:50]:
        try:
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data.get("name"), str):
                names.add(data["name"])
        except (OSError, ValueError, AttributeError):
            continue
    return names
