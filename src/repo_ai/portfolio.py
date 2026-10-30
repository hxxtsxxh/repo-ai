"""Skill portfolio: approved third-party skills, pinned and reversible.

`.repo-ai/skills.lock.json` (committed, reviewable) records every
third-party skill repo-ai installed. Each entry holds:
- source: provider, repo, path and immutable commit;
- content hash and per-file SHA-256;
- licence;
- firewall verdict and finding counts;
- who approved which hash, and when;
- install-time modifications (for example, stripped `allowed-tools`);
- trial evidence;
- previous versions, for rollback.

Approved content is kept by content hash in the machine-local object store
(`$REPO_AI_HOME/quarantine/objects/<hash>/`), so reinstall and rollback work
offline and are reproducible.

Installing requires the user's explicit approval of a specific content
hash. repo-ai re-fetches the pinned commit, re-hashes and re-inspects it,
and refuses if anything changed since review.

Installed files are tracked by hash. Removal deletes only files still
byte-identical to what was installed, so a file you edited is never
deleted. `skills disable --third-party --all` is the kill switch.

Writes go through `capbundle`: the reviewed content becomes a pinned
`CapabilityBundle`, a host translator places it (Claude Code by default; other
hosts are export-only), conflicts with files repo-ai does not own refuse the
install, and a machine-local manifest makes uninstall and rollback byte-exact.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Any

from . import firewall

LOCK_NAME = "skills.lock.json"
LOCK_VERSION = 1


class PortfolioError(RuntimeError):
    pass


def lock_path(root: Path) -> Path:
    return root / ".repo-ai" / LOCK_NAME


def load_lock(root: Path) -> dict[str, Any]:
    path = lock_path(root)
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", LOCK_VERSION)
    raw = data.get("skills")
    skills: dict[Any, Any] = raw if isinstance(raw, dict) else {}
    # The lockfile is committed, so it is untrusted input: an entry that could
    # name a path outside its skill directory or outside the object store is
    # never acted on (reported by `skills portfolio`/`health`).
    data["skills"], invalid, raw_invalid = {}, {}, {}
    for name, entry in skills.items():
        problem = entry_problem(name, entry)
        if problem:
            invalid[str(name)[:80]] = problem
            raw_invalid[name] = entry
        else:
            entry["name"] = name  # the key is the identity, whatever the entry says
            data["skills"][name] = entry
    data["invalid"] = invalid
    data["_invalid_raw"] = raw_invalid  # written back untouched: never acted on, never deleted
    return data


_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_HASH = re.compile(r"[0-9a-f]{64}")


def entry_problem(name: Any, entry: Any) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64:
        return "invalid skill name"
    if not isinstance(entry, dict) or entry.get("name", name) != name:
        return "entry name does not match its key"
    if entry.get("status") not in ("active", "disabled"):
        return "unknown status"
    if not isinstance(entry.get("content_hash"), str) or not _HASH.fullmatch(entry["content_hash"]):
        return "content_hash is not a sha256 hex digest"
    for h in entry.get("history") or []:
        if not isinstance(h, dict) or not _HASH.fullmatch(str(h.get("content_hash", ""))):
            return "history holds an invalid content hash"
    files = entry.get("files")
    if not isinstance(files, list):
        return "files is not a list"
    for f in files:
        if not isinstance(f, dict) or not _HASH.fullmatch(str(f.get("sha256", ""))):
            return "file entry without a sha256"
        try:
            firewall.safe_rel(str(f.get("path", "")))
        except firewall.QuarantineError:
            return f"unsafe file path {str(f.get('path'))[:60]!r}"
    return ""


def save_lock(root: Path, data: dict[str, Any]) -> None:
    from .fsutil import atomic_write, ensure_inside
    path = lock_path(root)
    ensure_inside(root, path)
    raw_invalid = data.get("_invalid_raw") or {}
    data = {k: v for k, v in data.items() if k not in {"invalid", "_invalid_raw"}}
    data["skills"] = {**{k: v for k, v in raw_invalid.items() if k not in data.get("skills", {})},
                      **data.get("skills", {})}
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def objects_dir() -> Path:
    return firewall.quarantine_root() / "objects"


def _store_object(dest: Path, chash: str) -> Path:
    target = objects_dir() / chash
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copytree(dest / "files", target / "files")
    return target


def strip_allowed_tools(text: str) -> tuple[str, bool]:
    """Reduce SKILL.md front matter to the safe allowlist (firewall.SAFE_FRONT_KEYS)."""
    text, removed = firewall.sanitize_front_matter(text)
    return text, bool(removed)


SCRIPT_EXT = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1", ".bat"}


def has_scripts(files: list[dict[str, Any]]) -> list[str]:
    return [f["path"] for f in files if PurePosixPath(f["path"]).suffix.lower() in SCRIPT_EXT
            or f.get("executable")]


def _exact_text(data: bytes, path: str) -> str:
    """The file as text that writes back byte-for-byte, or a refusal: files
    are installed through the text-only plan, and decoding binary content
    with replacement characters would silently corrupt it."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PortfolioError(f"{path} is not UTF-8 text (binary asset); installing it could not "
                             "preserve its bytes, so this skill is not installable") from None
    if text.encode("utf-8") != data:  # pragma: no cover - utf-8 round-trips exactly
        raise PortfolioError(f"{path} would not be preserved byte-for-byte; refusing")
    return text


def verified_evidence(entry: dict[str, Any]) -> dict[str, Any]:
    """Trial evidence only when this machine holds the experiment it cites.
    The lockfile is committed repository content: a cloned repository could
    claim any trial result, so an unbacked claim counts as not evaluated."""
    ev = dict(entry.get("evidence") or {})
    if ev.get("status") not in {"pilot", "evaluated"}:
        return ev or {"status": "not evaluated"}
    from .coding_lab import experiment_dir
    exp = str(ev.get("experiment") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", exp) or exp.startswith(".") \
            or not (experiment_dir(exp) / "experiment.json").is_file():
        return {"status": "unverified", "claimed_status": ev.get("status"),
                "note": "no local experiment record backs this claim"}
    return ev


def install(root: Path, name: str, src_dir: Path, report: firewall.Report, candidate: dict[str, Any],
            approve: str, *, accept_review: bool = False, allow_scripts: bool = False,
            dry_run: bool = False, hosts: tuple[str, ...] | None = None,
            pinned_hash: str | None = None, approved_by: str = "user") -> dict[str, Any]:
    """Install verified, approved content (already re-fetched and re-inspected).

    `pinned_hash` is the content hash that was reviewed; the bytes written are
    re-verified against it. `hosts` defaults to the hosts of the installed
    version (Claude Code for a new skill); a host dropped on an upgrade is
    uninstalled byte-exactly. `approved_by` is `user` (a per-hash approval) or
    `policy:SAFE_AUTO` (autopilot, inert skills only)."""
    from . import capbundle
    if not approve or not report.content_hash.startswith(approve) or len(approve) < 12:
        raise PortfolioError(f"approval must name the reviewed content hash (at least 12 hex "
                             f"chars of {report.content_hash}); got {approve!r}")
    skill_text = (src_dir / "files" / "SKILL.md").read_text("utf-8", errors="replace") \
        if (src_dir / "files" / "SKILL.md").is_file() else ""
    problem = firewall.front_problem(skill_text)
    if problem:
        raise PortfolioError(f"not installable: {problem}")
    if report.verdict == "blocked":
        raise PortfolioError("the firewall blocked this skill: "
                             + "; ".join(f"{f.category}/{f.rule}" for f in report.findings
                                         if f.severity == "critical")[:300])
    if any(f.rule in firewall.LICENSE_GATE_RULES for f in report.findings):
        raise PortfolioError(f"no usable, recognised and unrestricted licence ({report.license or 'missing'}): "
                             "not installable")
    if report.verdict == "review" and not accept_review:
        raise PortfolioError("high-severity findings need explicit --accept-review after you have "
                             "read them: " + "; ".join(f"{f.category}/{f.rule}" for f in report.findings
                                                      if f.severity == "high")[:300])
    scripts = has_scripts(report.files)
    if scripts and not allow_scripts:
        raise PortfolioError(f"this skill ships scripts ({', '.join(scripts[:4])}); Claude could run "
                             "them later. Re-run with --allow-scripts after reviewing them")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        raise PortfolioError(f"invalid skill name {name!r}")
    try:
        bundle = capbundle.from_quarantine(name, src_dir, report, pinned_hash or report.content_hash,
                                           source={k: candidate.get(k) for k in
                                                   ("provider", "owner", "repo", "path", "commit", "url")})
        if bundle.kind != "skill":
            raise capbundle.BundleError(f"this is a {bundle.kind}, not a skill: "
                                        f"{capbundle.KIND_RULES.get(bundle.kind, 'not installable')}")
        if approved_by != "user" and not bundle.assessment.get("inert"):
            raise capbundle.BundleError("only an inert skill can be installed without a per-hash approval")
        lock = load_lock(root)
        entry = lock["skills"].get(name)
        previous_hosts = tuple(h for h in ((entry or {}).get("hosts") or ["claude-code"]) if h in capbundle.HOSTS)
        if hosts is None:
            hosts = previous_hosts if entry else capbundle.DEFAULT_HOSTS
        dropped = tuple(h for h in previous_hosts if entry and h not in hosts)
        ip = capbundle.plan_install(root, bundle, hosts, _legacy_files(root, name, entry))
    except (capbundle.BundleError, firewall.QuarantineError) as exc:
        raise PortfolioError(str(exc)) from exc
    if dry_run:
        return {"dry_run": True, "files": [f["path"] for f in report.files], "modified": ip.modified,
                "conflicts": ip.conflicts, "plan": ip.to_json(), "assessment": bundle.assessment}
    if ip.conflicts:
        raise PortfolioError("refusing to install (nothing was written): " + "; ".join(ip.conflicts[:6]))
    try:
        capbundle.apply_install(ip)
        if dropped:
            capbundle.uninstall(root, name, dropped)
    except capbundle.BundleError as exc:
        raise PortfolioError(str(exc)) from exc
    _store_object(src_dir, report.content_hash)
    history = list((entry or {}).get("history", []))
    if entry:
        history.append({k: entry[k] for k in ("content_hash", "commit", "approved_at", "files")
                        if k in entry})
    lock["skills"][name] = {
        "name": name, "status": "active",
        "source": {"provider": candidate.get("provider"), "owner": candidate.get("owner"),
                   "repo": candidate.get("repo"), "path": candidate.get("path"),
                   "commit": candidate.get("commit"), "url": candidate.get("url")},
        "content_hash": report.content_hash, "files": _host_files(ip, "claude-code"),
        "hosts": list(hosts), "kind": bundle.kind, "inert": bool(bundle.assessment.get("inert")),
        "upstream_files": report.files, "license": report.license,
        "verdict": report.verdict, "finding_counts": report.counts(),
        "approved_hash": approve, "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "approved_by": approved_by,
        "accepted_review": bool(accept_review and report.verdict == "review"),
        "scripts": scripts, "modified": ip.modified,
        "description": str(candidate.get("description", ""))[:1024],
        "evidence": (entry or {}).get("evidence", {"status": "not evaluated"}),
        # canary until a live controlled trial shows it does not hurt (promote)
        "stage": (entry or {}).get("stage", "canary") if (entry or {}).get("content_hash") ==
        report.content_hash else "canary",
        "history": history[-5:],
    }
    save_lock(root, lock)
    return lock["skills"][name]


def _host_files(ip, host: str) -> list[dict[str, Any]]:
    """Lockfile-style file list (paths relative to the skill directory) for one host."""
    import hashlib

    from .capbundle import HOSTS
    if host not in ip.hosts:
        return []
    base = HOSTS[host].target_dir(ip.bundle.name).as_posix() + "/"
    texts = {**ip.writes.get(host, {})}
    out = []
    for rel, text in sorted(texts.items()):
        out.append({"path": rel[len(base):], "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    return out


def _legacy_files(root: Path, name: str, entry: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """For a skill installed before manifests existed: its lockfile file list counts as repo-ai's
    (only files still byte-identical to it are ever replaced or removed)."""
    from .capbundle import load_manifest
    if not entry or load_manifest(root, name)["hosts"].get("claude-code"):
        return {}
    return {"claude-code": list(entry.get("files") or [])}


def _plan_remove(root: Path, plan, entry: dict[str, Any]) -> list[str]:
    import hashlib
    kept: list[str] = []
    target = root / ".claude" / "skills" / entry["name"]
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        return ["(skill directory is a symlink or not a directory: left untouched)"]
    for f in entry.get("files", []):
        path = target / f["path"]
        if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
            kept.append(f["path"] + " (symlink: left untouched)")
            continue
        try:
            current = path.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(current).hexdigest() == f["sha256"]:
            plan.delete(path)
            plan.remove_dir_if_empty(path.parent)
        else:
            kept.append(f["path"])
    plan.remove_dir_if_empty(target)
    return kept


def disable(root: Path, names: list[str] | None = None) -> list[str]:
    """Remove installed third-party skills from `.claude/skills` (kill switch
    when `names` is None). Lock entries and objects stay for re-enabling."""
    from .fsutil import Plan
    lock = load_lock(root)
    out = []
    for name, entry in sorted(lock["skills"].items()):
        if names is not None and name not in names:
            continue
        if entry.get("status") != "active":
            continue
        plan = Plan(root)  # one plan per skill: one bad entry never stops the kill switch
        try:
            kept = _remove_installed(root, plan, entry)
        except Exception as exc:  # noqa: BLE001 - report and keep disabling the rest
            out.append(f"{name} (FAILED: {exc})")
            continue
        entry["status"] = "disabled"
        out.append(name + (f" (kept: {', '.join(kept)})" if kept else ""))
    save_lock(root, lock)
    return out


def _remove_installed(root: Path, plan, entry: dict[str, Any]) -> list[str]:
    """Byte-exact removal through the manifest when there is one; the lockfile's hashes otherwise."""
    from . import capbundle
    man = capbundle.load_manifest(root, entry["name"])
    if not man["hosts"]:
        kept = _plan_remove(root, plan, entry)
        plan.apply()
        return kept
    result = capbundle.uninstall(root, entry["name"])
    return [k.split("/", 3)[-1] if k.startswith(".claude/skills/") else k for k in result["kept"]]


def enable(root: Path, name: str) -> dict[str, Any]:
    """Re-install a disabled skill from the object store after verifying it."""
    lock = load_lock(root)
    entry = lock["skills"].get(name)
    if not entry:
        raise PortfolioError(f"{name} is not in the portfolio")
    return _restore(root, entry, entry["content_hash"], lock)


def rollback(root: Path, name: str) -> dict[str, Any]:
    lock = load_lock(root)
    entry = lock["skills"].get(name)
    if not entry or not entry.get("history"):
        raise PortfolioError(f"{name}: no previous version recorded")
    prev = entry["history"].pop()
    return _restore(root, entry, prev["content_hash"], lock, commit=prev.get("commit"))


def verified_object(chash: str) -> tuple[Path, list[dict[str, Any]]]:
    """The object store copy of `chash`, re-hashed: never trust its name."""
    import hashlib
    if not _HASH.fullmatch(chash or ""):
        raise PortfolioError("invalid content hash")
    obj = objects_dir() / chash / "files"
    if not obj.is_dir() or obj.is_symlink():
        raise PortfolioError(f"content {chash[:12]} is not in the local object store; "
                             "re-discover and re-approve it")
    files = []
    for path in sorted(p for p in obj.rglob("*") if p.is_file() or p.is_symlink()):
        if path.is_symlink():
            raise PortfolioError(f"object store copy of {chash[:12]} contains a symlink; refusing")
        files.append({"path": path.relative_to(obj).as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if firewall.content_hash(files) != chash:
        raise PortfolioError(f"object store copy of {chash[:12]} is corrupt; refusing")
    return obj, files


def _restore(root: Path, entry: dict[str, Any], chash: str, lock: dict[str, Any],
             commit: str | None = None) -> dict[str, Any]:
    """Re-install `chash` from the object store through the bundle translators.

    The translation is deterministic, so a rollback writes exactly the bytes the
    earlier install wrote."""
    from . import capbundle
    obj, files = verified_object(chash)
    hosts = tuple(h for h in (entry.get("hosts") or ["claude-code"]) if h in capbundle.HOSTS) or ("claude-code",)
    try:
        kind = capbundle.classify(files, lambda rel: (obj / firewall.safe_rel(rel)).read_bytes())["kind"]
        if kind != "skill":
            raise capbundle.BundleError(f"object store content {chash[:12]} is a {kind}, not a skill")
        bundle = capbundle.from_files(entry["name"], obj, files, chash)
        ip = capbundle.plan_install(root, bundle, hosts, _legacy_files(root, entry["name"], entry))
        if ip.conflicts:
            raise capbundle.BundleError("refusing (nothing was written): " + "; ".join(ip.conflicts[:6]))
        capbundle.apply_install(ip)
    except (capbundle.BundleError, firewall.QuarantineError) as exc:
        raise PortfolioError(str(exc)) from exc
    entry.update(status="active", content_hash=chash, files=_host_files(ip, "claude-code"))
    if commit:
        entry["source"]["commit"] = commit
    save_lock(root, lock)
    return entry


def remove_all_plan(root: Path, plan) -> None:
    """For `repo-ai uninstall`: remove every repo-ai-installed third-party skill
    (unmodified files only) and the lockfile."""
    from . import capbundle
    lock = load_lock(root)
    for entry in lock["skills"].values():
        if entry.get("status") == "active":
            try:  # one bad entry never stops the rest of the uninstall
                if capbundle.load_manifest(root, entry["name"])["hosts"]:
                    result = capbundle.plan_uninstall(root, entry["name"], plan)
                    for d in result["created_dirs"]:
                        plan.remove_dir_if_empty(root / d)
                else:
                    _plan_remove(root, plan, entry)
            except Exception:  # noqa: BLE001,S112 - its files are simply left in place
                continue
    if lock_path(root).exists():
        plan.delete(lock_path(root))


def installed_names(root: Path) -> set[str]:
    return {n for n, e in load_lock(root)["skills"].items() if e.get("status") == "active"}


def install_locked_into(ws: Path, lock_file: Path | None = None,
                        only: tuple[str, ...] | None = None) -> list[str]:
    """Lab arms with `thirdparty`: install the approved, active entries of a
    portfolio lockfile into a disposable workspace (from the object store)."""
    import os
    path = lock_file or (Path(os.environ["REPO_AI_LAB_SKILLS_LOCK"])
                         if os.environ.get("REPO_AI_LAB_SKILLS_LOCK") else None)
    if path is None or not path.is_file():
        return []
    data = json.loads(path.read_text("utf-8"))
    out = []
    for name, entry in sorted((data.get("skills") or {}).items()):
        if entry_problem(name, entry) or entry.get("status") != "active" or \
                (only is not None and name not in only):
            continue
        try:
            obj, _ = verified_object(entry["content_hash"])
        except PortfolioError:
            continue
        dest = ws / ".claude" / "skills" / name
        shutil.copytree(obj, dest, dirs_exist_ok=True)
        for p in dest.rglob("*"):
            if p.is_file():
                p.chmod(0o644)
        skill = dest / "SKILL.md"
        if skill.exists():
            text, _ = strip_allowed_tools(skill.read_text("utf-8", errors="replace"))
            skill.write_text(text, encoding="utf-8")
        out.append(name)
    return out


def check_updates(root: Path, client) -> list[dict[str, Any]]:
    from .radar import RadarError
    out = []
    for name, entry in sorted(load_lock(root)["skills"].items()):
        src = entry.get("source") or {}
        if not src.get("owner"):
            out.append({"name": name, "status": "local source: no upstream"})
            continue
        try:
            meta = client.get("api.github.com", f"/repos/{src['owner']}/{src['repo']}", ttl=3600)
            commits = client.get("api.github.com", f"/repos/{src['owner']}/{src['repo']}/commits",
                                 {"path": src.get("path") or "", "per_page": 1}, ttl=3600)
        except RadarError as exc:
            out.append({"name": name, "status": f"unknown ({exc})"})
            continue
        latest = commits[0]["sha"] if isinstance(commits, list) and commits else ""
        row = {"name": name, "pinned": (src.get("commit") or "")[:12], "latest": latest[:12],
               "archived": bool(meta.get("archived")),
               "license_now": ((meta.get("license") or {}) or {}).get("spdx_id") or "",
               "status": "up to date" if not latest or latest == src.get("commit") else
               "update available (re-audit + explicit approval required; never automatic)"}
        out.append(row)
    return out


STAGES = ("canary", "promoted", "harmful")


def record_trial(root: Path, name: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Store a trial result; a measured harm moves the skill to `harmful`."""
    lock = load_lock(root)
    entry = lock["skills"][name]
    entry["evidence"] = evidence
    if evidence.get("status") in {"pilot", "evaluated"} and (evidence.get("diff") or 0) < 0 \
            and "worse" in str(evidence.get("verdict", "")):
        entry["stage"] = "harmful"
    save_lock(root, lock)
    return entry


def promote(root: Path, name: str) -> dict[str, Any]:
    """Canary -> promoted, only on live trial evidence that it does not hurt."""
    lock = load_lock(root)
    entry = lock["skills"].get(name)
    if entry is None:
        raise PortfolioError(f"{name} is not in the portfolio")
    ev = verified_evidence(entry)
    if ev.get("status") == "pilot":  # n < 10: never a basis for a verdict, so never for promotion
        raise PortfolioError(f"{name}: a pilot trial (fewer than 10 pairs) cannot support promotion; "
                             "run a full trial")
    if ev.get("status") != "evaluated":
        raise PortfolioError(f"{name} has no locally recorded live trial evidence "
                             f"({ev.get('status', 'not evaluated')}); "
                             f"run: repo-ai skills benchmark {name} --max-cost-usd <budget>")
    if (ev.get("diff") or 0) < 0:
        raise PortfolioError(f"{name}: the trial was worse with it (diff {ev.get('diff')}); not promoted")
    entry["stage"] = "promoted"
    entry["promoted_on"] = {"experiment": ev.get("experiment"), "status": ev.get("status"),
                            "pairs": ev.get("pairs"), "diff": ev.get("diff")}
    save_lock(root, lock)
    return entry


def health(root: Path, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Local health of the whole skill portfolio (no network)."""
    import hashlib

    from .skills_lab import overlap
    lock = load_lock(root)
    skills_dir = root / ".claude" / "skills"
    descs: dict[str, str] = {}
    for p in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []:
        m = re.search(r"(?m)^description:\s*(.+)$", p.read_text("utf-8", errors="replace"))
        descs[p.parent.name] = m.group(1).strip().strip('"') if m else ""
    used: dict[str, dict[str, int]] = {}
    for ep in episodes or []:
        for _, sname, _v in ep.get("skills") or []:
            used.setdefault(sname, {}).setdefault(ep.get("status", "no-change"), 0)
            used[sname][ep.get("status", "no-change")] += 1
    rows = []
    for name, entry in sorted(lock["skills"].items()):
        issues = []
        for f in entry.get("files", []):
            path = skills_dir / name / f["path"]
            if entry.get("status") == "active":
                if not path.exists():
                    issues.append(f"missing file {f['path']}")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
                    issues.append(f"edited locally: {f['path']}")
        for other, desc in descs.items():
            if other != name and overlap(entry.get("description", ""), desc) >= 0.5:
                issues.append(f"trigger overlaps /{other}")
        stats = used.get(name, {})
        sessions = sum(stats.values())
        if sessions >= 5 and stats.get("failed", 0) / sessions > 0.5:
            issues.append(f"{stats['failed']} of {sessions} sessions using it failed tests")
        if entry.get("verdict") != "eligible":
            issues.append(f"installed with firewall verdict {entry.get('verdict')}")
        if entry.get("stage") == "harmful":
            issues.append("a controlled trial found outcomes worse with it: disable it")
        rows.append({"name": name, "status": entry.get("status"), "license": entry.get("license"),
                     "stage": entry.get("stage", "canary"),
                     "evidence": entry.get("evidence", {}).get("status", "not evaluated"),
                     "sessions_used": sessions, "issues": issues})
    return rows
