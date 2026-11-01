"""Capability registry: what repo-ai and approved local tools can do for a task.

A small curated manifest (`capabilities.json`) describes each capability:
- what it does and which needs it serves;
- its provider, pinned source and licence;
- permissions, network use and overhead;
- known limitations, fallback and removal;
- what it adds beyond native Claude Code.

Everything that depends on this machine is computed at read time and kept in
six separate lifecycle fields, never one status:

  discovered -> reviewed -> approved -> available -> invoked -> validated

- `approved` exists only for adapters that run a local binary. It binds the
  executable's real path, sha256 and version, and lives outside the
  repository (`registry.machine_dir`), so a cloned repository cannot approve
  anything for you.
- `invoked` and `validated` come from repo-ai's own run log. `measured_effect`
  stays null: unit tests do not show that an agent benefits.

`recommend()` is deterministic and offline. From the task text, the
repository's languages and frameworks and the changed files, it names at
most three capabilities, or says that nothing is needed. It runs no process
and never ranks by popularity.

Activation keeps its stages apart:
1. show (`list`, `show`);
2. recommend;
3. prepare: resolve the binary and print the approval line, writing nothing;
4. approve: a human binds the hash;
5. run: re-checks the binding, uses a fixed argument list and records the result;
6. revoke.

repo-ai never installs a tool, and never writes Claude Code settings,
hooks, MCP configuration or permission rules.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from . import gitbin

SCHEMA_RECORD = "repo-ai.capability/1"
SCHEMA_RECOMMENDATION = "repo-ai.capability-recommendation/1"
SCHEMA_RESULT = "repo-ai.capability-result/1"
MAX_RECOMMENDED = 3
EXPERIMENTAL = "experimental matcher: not validated on a fresh corpus; it misses relevant capabilities"
ADAPTER_VERSION = "ruff-security/1"
APPROVALS = "capabilities.json"
EXIT_NOT_AVAILABLE, EXIT_BINDING_CHANGED, EXIT_TOOL_ERROR = 3, 4, 5
KIND_ORDER = {"builtin": 0, "adapter": 1, "external": 2}

# --------------------------------------------------------------------------
# the curated ruff rule subset (stable flake8-bandit rules; chosen from
# `ruff rule --all` before any evaluation; S320 is removed in ruff 0.12+,
# which the real-binary test found). Excluded as noise for a
# change-scoped scan: S101 (assert), S110/S112 (try-except-pass/continue),
# S311 (random), S4xx (imports), S603/S606/S607 (any subprocess call).
# --------------------------------------------------------------------------
RUFF_RULES: dict[str, tuple[str, str]] = {
    "S102": ("high", "use of exec"), "S103": ("medium", "permissive file permissions"),
    "S104": ("medium", "binding to all interfaces"), "S105": ("medium", "hardcoded password string"),
    "S106": ("medium", "hardcoded password argument"), "S107": ("medium", "hardcoded password default"),
    "S108": ("medium", "insecure temporary file"), "S113": ("low", "HTTP request without timeout"),
    "S201": ("medium", "Flask debug mode"), "S202": ("high", "tarfile extraction without member checks"),
    "S301": ("high", "pickle deserialization"), "S302": ("high", "marshal deserialization"),
    "S303": ("medium", "insecure hash function"), "S304": ("medium", "insecure cipher"),
    "S305": ("medium", "insecure cipher mode"), "S306": ("medium", "insecure mktemp"),
    "S307": ("high", "use of eval"), "S308": ("high", "mark_safe (XSS)"),
    "S310": ("low", "URL open without a scheme check"), "S312": ("medium", "telnet"),
    "S313": ("medium", "XML parsing of untrusted data"), "S314": ("medium", "XML parsing of untrusted data"),
    "S315": ("medium", "XML parsing of untrusted data"), "S316": ("medium", "XML parsing of untrusted data"),
    "S317": ("medium", "XML parsing of untrusted data"), "S318": ("medium", "XML parsing of untrusted data"),
    "S319": ("medium", "XML parsing of untrusted data"),
    "S321": ("medium", "FTP"), "S323": ("high", "unverified SSL context"),
    "S324": ("medium", "insecure hash function"), "S501": ("high", "TLS certificate verification disabled"),
    "S502": ("medium", "insecure SSL/TLS version"), "S503": ("medium", "insecure SSL/TLS default"),
    "S504": ("medium", "ssl.wrap_socket without a version"), "S505": ("medium", "weak cryptographic key"),
    "S506": ("high", "unsafe yaml.load"), "S507": ("high", "SSH without host key verification"),
    "S508": ("medium", "insecure SNMP version"), "S509": ("medium", "weak SNMP cryptography"),
    "S601": ("high", "shell injection through paramiko"), "S602": ("high", "subprocess with shell=True"),
    "S604": ("high", "call with shell=True"), "S605": ("high", "process started with a shell"),
    "S608": ("high", "SQL built from strings"), "S609": ("medium", "wildcard injection"),
    "S610": ("high", "Django extra() (SQL injection)"), "S611": ("high", "Django RawSQL (SQL injection)"),
    "S612": ("medium", "insecure logging.config.listen"), "S701": ("high", "Jinja2 autoescape disabled"),
    "S702": ("medium", "Mako templates"), "S704": ("medium", "unsafe markup"),
}

# --------------------------------------------------------------------------
# needs: the closed vocabulary capability records declare (`needs` in capabilities.json).
# Matching a task to needs is capdiscovery's job; this module only names them.
# --------------------------------------------------------------------------
NEED_BY_ID: dict[str, str] = {
    "verify-change": "check that a change works: the tests that cover it",
    "blast-radius": "what else depends on the changed code",
    "shortlist-files": "where to start reading for this task",
    "review-diff": "facts about the diff before review",
    "vet-third-party": "a third-party skill or plugin before installing it",
    "audit-installed": "what is installed in the agent setup now",
    "context-budget": "how much context the agent setup loads",
    "security-code": "insecure patterns in changed code",
    "dependency-vuln": "known-vulnerable dependencies",
    "precise-refs": "exact definitions and references of a symbol",
    "browser-runtime": "evidence from a running UI",
    "test-adequacy": "whether the tests would catch a bug",
    "property-invariants": "invariants checked over generated inputs",
    "security-review-deep": "a structured security review of a risky change",
}
EXT_LANG = {".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
            ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust",
            ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
            ".vue": "Vue", ".svelte": "Svelte", ".scala": "Scala", ".c": "C", ".h": "C", ".cpp": "C++"}


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------
def load_manifest(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        from importlib import resources
        text = resources.files(__package__).joinpath("capabilities.json").read_text("utf-8")
    else:
        text = path.read_text("utf-8")
    data = json.loads(text)
    ids = [c["id"] for c in data["capabilities"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate capability id in the manifest")
    return data


def by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in manifest["capabilities"]}


# --------------------------------------------------------------------------
# repository profile (no index needed)
# --------------------------------------------------------------------------
def profile(root: Path, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    facts = facts or {}
    langs = list(facts.get("languages") or {})
    frameworks = [str(f.get("name") if isinstance(f, dict) else f) for f in facts.get("frameworks") or []]
    deps = [str(d.get("name") if isinstance(d, dict) else d) for d in facts.get("dependencies") or []][:400]
    if not langs:
        from collections import Counter

        from .gitinfo import _run
        files = _run(root, ["ls-files"], timeout=20).splitlines()[:20_000]
        counts = Counter(EXT_LANG.get(PurePosixPath(f).suffix.lower(), "") for f in files)
        langs = [lang for lang, n in counts.most_common() if lang and n >= 1][:6]
    return {"languages": langs, "frameworks": frameworks, "dependencies": deps}


def _status_paths(root: Path) -> list[str]:
    """Staged, unstaged and untracked paths from one NUL-separated `git status`."""
    from .gitinfo import _run
    parts = _run(root, ["--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                 timeout=30).split("\0")
    paths, i = [], 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            paths.append(entry[3:])
            if entry[0] in "RC":  # a rename's old path follows; skip it
                i += 1
        i += 1
    return paths


MAX_CHANGED_PATHS = 2000


def changed_files(root: Path, base: str = "HEAD", agent_dirs: bool = False) -> list[str]:
    """Changed paths against `base` plus the working tree. Against HEAD that is
    one `git status` call instead of four diffs."""
    from .gitinfo import _run, safe_ref
    paths = _status_paths(root)
    if base != "HEAD":
        if not safe_ref(base):
            return []
        paths += [p for p in _run(root, ["diff", "--name-only", "-z", "--end-of-options", base], timeout=60)
                  .split("\0") if p]
    skip = (".repo-ai/",) if agent_dirs else (".repo-ai/", ".claude/", ".bob/")
    return sorted({p for p in paths if not p.startswith(skip)})[:MAX_CHANGED_PATHS]


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------
_WHY = {"lang": "does not fit this change's languages", "python-only": "the Python adapter covers this change",
        "frontend": "needs a front-end", "docs-only": "the change is docs only", "trivial": "the task is text work",
        "excluded": "excluded"}


def recommend(task: str, prof: dict[str, Any], changed: list[str] | None, manifest: dict[str, Any],
              states: dict[str, dict[str, Any]] | None = None, deny: list[str] | None = None) -> dict[str, Any]:
    """Deterministic: discovery (capdiscovery) under the trust gates (capselect). No process is run.

    The top tier needs a strong task signal; weaker matches are listed under `consider` and never
    recommended. Task text is never echoed: agents read this output.
    """
    from . import capdiscovery, capselect

    task = " ".join(str(task).split())
    disc = capdiscovery.discover(task, prof, list(changed or []), manifest)
    gated = capselect.gate(disc, manifest, states or {}, list(deny or []))
    records = by_id(manifest)
    recs = []
    for top in capselect.recommend_top3(gated):
        cap = records[top["id"]]
        item = next(c for c in gated["candidates"] if c["id"] == top["id"])
        avail = (states or {}).get(cap["id"], {}).get("available") or {"status": False, "reason": "unknown"}
        need = next((d["need"] for d in disc["candidates"] if d["id"] == cap["id"]), "")
        recs.append({"id": cap["id"], "title": cap["title"], "kind": cap["kind"],
                     "score": next((d["score"] for d in disc["candidates"] if d["id"] == cap["id"]), 0.0),
                     "need": need, "why": [f"{need}: {NEED_BY_ID.get(need, need)}"], "fit": item.get("fit", []),
                     "gate": top["gate"], "adds_beyond_native": cap.get("adds_beyond_native", ""),
                     "native_alternatives": cap.get("native_alternatives", []),
                     "available": bool(avail.get("status")), "availability": avail.get("reason", ""),
                     "next_step": _next_step(cap, avail), "limitations": cap.get("limitations", [])[:2]})
    shown = {r["id"] for r in recs}
    consider = [c["id"] for c in gated["candidates"] if not c.get("blocked") and c["id"] not in shown][:3]
    not_rec = [{"id": e["id"], "reason": _WHY.get(e["why"], e["why"])} for e in gated["excluded"]]
    not_rec += [{"id": c["id"], "reason": f"ruled out by the task's constraint ({c['why'].split(':', 1)[1]})"}
                for c in gated["candidates"] if c.get("blocked")]
    abstain = ""
    if not recs:
        if gated["hint"] == "docs-only" or any(e["why"] == "trivial" for e in gated["excluded"]):
            abstain = "text or docs work; your own tools suffice"
        elif any(c.get("blocked") for c in gated["candidates"]):
            abstain = "the matching capability is ruled out by your constraint"
        elif consider:
            abstain = "no strong match; see consider"
        else:
            abstain = "no capability beats your own tools here"
    return {"schema": SCHEMA_RECOMMENDATION, "task_sha256": hashlib.sha256(task.encode()).hexdigest()[:16],
            "signals": {"languages": gated["langs"], "changed_files": len(list(changed or [])),
                        "hint": gated["hint"],
                        "constraints": {"explicit": gated["explicit"], "inferred": gated["inferred"],
                                        "note": "--deny is enforced; constraints inferred from the task "
                                                "text are best-effort and miss many"}},
            "recommended": recs, "consider": consider, "not_recommended": not_rec[:6], "abstain_reason": abstain,
            "lexicon_sha256": disc["lexicon_sha256"], "experimental": EXPERIMENTAL,
            "note": "deterministic and offline; nothing was run. Benefit to an agent is not measured."}


def _next_step(cap: dict[str, Any], avail: dict[str, Any]) -> str:
    if avail.get("status"):
        act = cap.get("activation") or {}
        run = act.get("run") or []
        if cap["id"] == "repo-ai.skills-vet":
            return "repo-ai skills vet <github-url>   (network access is your decision)"
        if cap["id"] == "repo-ai.context":
            return "repo-ai capabilities run repo-ai.context --task-stdin   (the task on stdin)"
        return "repo-ai " + " ".join(run) if run else ""
    reason = avail.get("reason", "")
    if cap["kind"] == "adapter" and reason in ("not_approved", "binding_changed"):
        return "the user vets and approves this exact binary in their own terminal (docs/CAPABILITIES.md)"
    if cap["kind"] == "adapter" and reason == "not_installed":
        return "not installed; repo-ai does not install tools"
    if cap["kind"] == "adapter":
        return "no adapter yet; use the fallback: " + cap.get("fallback", "")
    if cap["kind"] == "external":
        return "you decide: " + (cap.get("activation") or {}).get("method", "")[:120]
    return reason


# --------------------------------------------------------------------------
# lifecycle state (computed)
# --------------------------------------------------------------------------
def index_ready(root: Path, index_path: Path) -> bool:
    """The index exists and git does not track it: an index shipped in the repository was not built here."""
    if not index_path.is_file():
        return False
    try:
        rel = index_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return True  # outside the checkout
    return _git_strict(root, ["ls-files", "--error-unmatch", "--", rel]).returncode != 0


def _approvals_path(root: Path) -> Path:
    from .registry import machine_dir
    return machine_dir(root) / APPROVALS


def load_approvals(root: Path) -> dict[str, Any]:
    try:
        data = json.loads(_approvals_path(root).read_text("utf-8"))
    except FileNotFoundError:
        return {"version": 1, "approvals": {}}
    except (OSError, ValueError):
        return {"version": 1, "approvals": {}, "error": "approvals file is unreadable; nothing is approved"}
    if not isinstance(data, dict) or not isinstance(data.get("approvals"), dict):
        return {"version": 1, "approvals": {}, "error": "approvals file is malformed; nothing is approved"}
    return data


def _save_approvals(root: Path, data: dict[str, Any], event: dict[str, Any]) -> None:
    path = _approvals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)
    with open(path.with_name("capabilities-journal.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": _now(), **event}) + "\n")


def runs_dir(root: Path) -> Path:
    """Run log and SARIF, outside the repository: a clone cannot forge them."""
    from .registry import machine_dir
    return machine_dir(root) / "capability-runs"


def _runs_path(state_dir: Path) -> Path:
    return state_dir / "runs.jsonl"


def _runs(state_dir: Path | None) -> list[dict[str, Any]]:
    if state_dir is None:
        return []
    try:
        lines = _runs_path(state_dir).read_text("utf-8").splitlines()[-500:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def state(root: Path, cap: dict[str, Any], *, indexed: bool, approvals: dict[str, Any],
          runs: list[dict[str, Any]], manifest_date: str = "") -> dict[str, Any]:
    review = cap.get("review") or {}
    life: dict[str, Any] = {
        "discovered": {"status": True, "source": "curated manifest", "at": manifest_date},
        "reviewed": {"status": review.get("status", "not-reviewed"), "ref": review.get("ref", "")},
    }
    if cap["kind"] == "builtin":
        life["approved"] = {"status": "not-required", "note": "built in; runs nothing outside repo-ai"}
        needs_index = cap["id"] in ("repo-ai.impact", "repo-ai.context", "repo-ai.review", "repo-ai.verify")
        life["available"] = {"status": indexed or not needs_index,
                             "reason": "ok" if indexed or not needs_index else "needs `repo-ai init`"}
    elif cap["id"] == "adapter.ruff-security":
        appr = (approvals.get("approvals") or {}).get(cap["id"])
        if appr:
            check = verify_binding(appr)
            life["approved"] = {"status": "approved", "at": appr.get("approved_at"), "path": appr.get("path"),
                                "sha256": str(appr.get("sha256", ""))[:16], "version": appr.get("version")}
            life["available"] = {"status": check == "ok", "reason": check}
        else:
            found = find_executable("ruff", root)
            life["approved"] = {"status": "not-approved"}
            life["available"] = {"status": False, "reason": "not_approved" if found else "not_installed",
                                 "found": str(found) if found else ""}
    elif cap["kind"] == "adapter":
        life["approved"] = {"status": "not-applicable", "note": "no adapter is implemented"}
        life["available"] = {"status": False, "reason": "no_adapter"}
    else:
        life["approved"] = {"status": "not-managed", "note": "installed and enabled by you, never by repo-ai"}
        life["available"] = {"status": False, "reason": "not_managed_by_repo_ai"}
    mine = [r for r in runs if r.get("capability") == cap["id"]]
    last = mine[-1] if mine else {}
    life["invoked"] = {"count": len(mine), "last_at": last.get("at", ""), "last_status": last.get("status", "")}
    life["validated"] = {"status": last.get("validated", "never") if last else "never",
                         "measured_effect": None,
                         "note": "output checked against its schema; benefit to an agent is not measured"}
    return life


def all_states(root: Path, manifest: dict[str, Any], *, indexed: bool, state_dir: Path | None) -> dict[str, Any]:
    approvals = load_approvals(root)
    runs = _runs(state_dir)
    return {c["id"]: state(root, c, indexed=indexed, approvals=approvals, runs=runs,
                           manifest_date=manifest.get("updated", "")) for c in manifest["capabilities"]}


# --------------------------------------------------------------------------
# binding an approval to an executable
# --------------------------------------------------------------------------
def _inside(path: Path, root: Path) -> bool:
    """Containment by file identity, not spelling: on a case-insensitive file
    system `/x/CASEREPO/bin` is inside `/x/CaseRepo`."""
    try:
        target = os.stat(root)
    except OSError:
        return False
    p = path.resolve()
    for cand in (p, *p.parents):
        try:
            st = os.stat(cand)
        except OSError:
            continue
        if (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino):
            return True
    return False


def _clean_path_entries(root: Path) -> list[str]:
    out = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue  # ".", "" and relative entries resolve against the repository
        if _inside(Path(entry), root):
            continue
        out.append(entry)
    return out


def find_executable(name: str, root: Path) -> Path | None:
    hit = shutil.which(name, path=os.pathsep.join(_clean_path_entries(root)))
    return Path(hit).resolve() if hit else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def adapter_hash() -> str:
    spec = json.dumps({"v": ADAPTER_VERSION, "rules": sorted(RUFF_RULES), "argv": _ruff_argv_template()})
    return hashlib.sha256(spec.encode()).hexdigest()


def _ruff_argv_template() -> list[str]:
    # --ignore-noqa: a file-level noqa directive in the scanned code must not silence the scan
    return ["check", "--isolated", "--no-cache", "--no-fix", "--ignore-noqa", "--output-format", "sarif",
            "--select", ",".join(sorted(RUFF_RULES)), "--"]


class CapabilityError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_NOT_AVAILABLE):
        super().__init__(message)
        self.code = code


def prepare(root: Path, cap_id: str, executable: str | None = None) -> dict[str, Any]:
    """Resolve the binary and describe exactly what approval would bind. Writes nothing."""
    if cap_id != "adapter.ruff-security":
        raise CapabilityError(f"{cap_id} has nothing to prepare: built-ins need no approval and external "
                              "capabilities are installed by you")
    path = Path(executable).expanduser() if executable else find_executable("ruff", root)
    if path is None:
        raise CapabilityError("ruff was not found on PATH (repository-relative PATH entries are ignored); "
                              "pass --executable /absolute/path/to/ruff", EXIT_NOT_AVAILABLE)
    if not path.is_absolute():
        raise CapabilityError("--executable must be an absolute path")
    real = path.resolve()
    if not real.is_file() or not os.access(real, os.X_OK):
        raise CapabilityError(f"{real} is not an executable file")
    if _inside(real, root):
        raise CapabilityError(f"{real} is inside the repository: code in the repository (or a clone of it) could "
                              "replace it. Use a ruff installed outside the repository")
    digest = _sha256(real)
    links = real.stat().st_nlink
    return {"capability": cap_id, "path": str(real), "sha256": digest, "size": real.stat().st_size,
            "hard_links": links,
            "adapter_hash": adapter_hash(),
            "argv": [str(real), *_ruff_argv_template(), "<changed .py files>"],
            "approve": f"repo-ai capabilities approve {cap_id} --sha256 {digest[:16]}"
                       + (f" --executable {real}" if executable else ""),
            "note": "approving lets repo-ai run exactly this file, with these arguments, on changed Python "
                    "files; it never installs anything and never changes Claude Code settings"
                    + (f". This file has {links} hard links: another name can change it (the run then refuses, "
                       "because the hash no longer matches)" if links > 1 else "")}


def _machine_dir_outside(root: Path) -> None:
    from .registry import machine_dir
    if _inside(machine_dir(root), root):
        raise CapabilityError("REPO_AI_HOME points inside this repository: approvals and run records would be "
                              "written where a clone can forge them. Point it outside the repository")


def _private_tmp(root: Path) -> Path:
    """A temporary-files directory under repo-ai's machine dir, never TMPDIR (which may point anywhere)."""
    _machine_dir_outside(root)
    tmp = runs_dir(root) / "tmp"
    tmp.mkdir(mode=0o700, parents=True, exist_ok=True)
    return tmp


def _private_copy(entry: dict[str, Any], dest: Path) -> Path:
    """Copy the approved binary into a private directory and hash the copy:
    what runs is exactly what was hashed, even if the original is swapped
    between the check and the start."""
    src = Path(str(entry["path"]))
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    copy = dest / src.name
    shutil.copyfile(src, copy)
    copy.chmod(0o700)
    if _sha256(copy) != entry.get("sha256"):
        raise CapabilityError(f"the approved ruff changed since approval ({src}); approve it again after checking",
                              EXIT_BINDING_CHANGED)
    return copy


AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "REPO_AI_IN_HOOK", "REPO_AI_AGENT", "AI_AGENT",
             "CI", "GITHUB_ACTIONS")


def approve(root: Path, cap_id: str, sha256_prefix: str, executable: str | None = None,
            env: dict[str, str] | None = None, interactive: bool = True) -> dict[str, Any]:
    """A human binds the exact executable. Refused inside agent shells, hooks and
    CI. That is defence in depth, not a boundary: Claude Code's own permission
    prompt is the boundary."""
    env = dict(os.environ) if env is None else env
    agent = [k for k in AGENT_ENV if k in env]  # set at all, even empty
    if agent:
        raise CapabilityError(f"refusing to approve from an agent shell, hook or CI ({', '.join(agent)} is set): "
                              "run this command yourself in a terminal")
    if not interactive:
        raise CapabilityError("refusing to approve without a terminal (stdin is not a TTY): run this command "
                              "yourself in a terminal")
    _machine_dir_outside(root)
    prep = prepare(root, cap_id, executable)
    prefix = sha256_prefix.strip().lower()
    if len(prefix) < 12 or not prep["sha256"].startswith(prefix):
        raise CapabilityError("the --sha256 prefix (12+ hex characters) does not match the executable; run "
                              "`repo-ai capabilities prepare` again", EXIT_BINDING_CHANGED)
    with tempfile.TemporaryDirectory(prefix="approve-", dir=_private_tmp(root)) as tmp:
        copy = _private_copy({"path": prep["path"], "sha256": prep["sha256"]}, Path(tmp) / "bin")
        version = _version(copy)
        problem = _self_test(copy, Path(tmp))
    if not re.match(r"^ruff \d+\.\d+", version):
        raise CapabilityError(f"{prep['path']} did not identify itself as ruff ({version[:60]!r})", EXIT_TOOL_ERROR)
    if problem:
        raise CapabilityError(f"{prep['path']} cannot run the adapter's rule set: {problem}", EXIT_TOOL_ERROR)
    data = load_approvals(root)
    data.pop("error", None)
    entry = {"path": prep["path"], "sha256": prep["sha256"], "size": prep["size"], "version": version,
             "adapter_hash": prep["adapter_hash"], "approved_at": _now(), "approved_by": "user (terminal)"}
    data.setdefault("approvals", {})[cap_id] = entry
    _save_approvals(root, data, {"event": "approve", "capability": cap_id, "sha256": prep["sha256"][:16],
                                 "path": prep["path"]})
    return {"capability": cap_id, "approved": entry}


def revoke(root: Path, cap_ids: list[str] | None) -> list[str]:
    data = load_approvals(root)
    current = data.get("approvals") or {}
    gone = sorted(current) if not cap_ids else [c for c in cap_ids if c in current]
    for c in gone:
        current.pop(c, None)
    if gone:
        data.pop("error", None)
        _save_approvals(root, data, {"event": "revoke", "capabilities": gone})
    return gone


def forget(root: Path) -> list[str]:
    """`repo-ai uninstall`: delete this checkout's approvals and their journal."""
    removed = []
    if runs_dir(root).is_dir():
        shutil.rmtree(runs_dir(root))
        removed.append(str(runs_dir(root)))
    path = _approvals_path(root)
    for p in (path, path.with_name("capabilities-journal.jsonl")):
        try:
            p.unlink()
            removed.append(str(p))
        except FileNotFoundError:
            continue
    return removed


def _version(path: Path) -> str:
    try:
        proc = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=10,
                              env=_clean_env(), check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"error: {exc}"
    return (proc.stdout or proc.stderr).strip().splitlines()[0][:80] if (proc.stdout or proc.stderr) else ""


def _self_test(path: Path, tmp: Path) -> str:
    """Lint an empty file with the exact arguments a run uses: an unknown or
    removed rule fails here, at approval, instead of at the first scan."""
    argv = [str(path), *_ruff_argv_template()[:-1], "--stdin-filename", "selftest.py", "-"]
    with tempfile.TemporaryDirectory(prefix="home-", dir=tmp) as home:
        try:
            proc = subprocess.run(argv, input=b"", capture_output=True, timeout=20, check=False,
                                  env={**_clean_env(), "HOME": home, "XDG_CONFIG_HOME": home}, cwd=home)
        except (OSError, subprocess.SubprocessError) as exc:
            return str(exc)[:200]
    if proc.returncode != 0:
        return _untrusted(proc.stderr.decode("utf-8", "replace") or f"exit {proc.returncode}", 200)
    return ""


def verify_binding(entry: dict[str, Any]) -> str:
    path = Path(str(entry.get("path", "")))
    try:
        if not path.is_file():
            return "binding_changed"
        if entry.get("adapter_hash") != adapter_hash():
            return "binding_changed"
        if path.stat().st_size != entry.get("size") or _sha256(path) != entry.get("sha256"):
            return "binding_changed"
    except OSError:
        return "binding_changed"
    return "ok"


def _clean_env() -> dict[str, str]:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):  # Windows needs these to start a process
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁠-⁤﻿]")


def _untrusted(text: str, limit: int = 200) -> str:
    """Tool output can quote repository content (an identifier, a string) and is
    therefore untrusted: control and invisible characters removed, capped."""
    from .security import redact_text
    return redact_text(_CONTROL.sub(" ", str(text)))[:limit]


def run(root: Path, state_dir: Path, cap_id: str, *, base: str = "HEAD", task: str = "",
        files: list[str] | None = None, manifest: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
    manifest = manifest or load_manifest()
    cap = by_id(manifest).get(cap_id)
    if cap is None:
        raise CapabilityError(f"unknown capability {cap_id!r} (see `repo-ai capabilities list`)")
    started = time.monotonic()
    if cap["kind"] == "builtin":
        result = _run_builtin(root, cap, task)
    elif cap_id == "adapter.ruff-security":
        result = _run_ruff(root, state_dir, base, files, timeout)
    else:
        raise CapabilityError(f"{cap_id} is not run by repo-ai: {_next_step(cap, {'reason': 'no_adapter'})}")
    result.update(schema=SCHEMA_RESULT, capability=cap_id, at=_now(),
                  duration_s=round(time.monotonic() - started, 3))
    _record(state_dir, result)
    return result


SCHEMA_EVIDENCE = "repo-ai.static-security-evidence/1"
EVIDENCE_FIELDS = ("capability", "at", "status", "validated", "files", "skipped", "binding_sha256",
                   "adapter_hash", "tool_version", "output_sha256", "diff_fingerprint", "findings", "counts")


def _evidence_path(state_dir: Path, cap_id: str) -> Path:
    return state_dir / "evidence" / f"{cap_id}.json"


def evidence(root: Path, state_dir: Path, cap_id: str = "adapter.ruff-security", *, base: str = "HEAD",
             files: list[str] | None = None) -> dict[str, Any]:
    """The last static-security result, offered as evidence only while it still describes this change.

    Reads, never runs: no adapter is started. `fresh` needs a validated run whose fingerprint (base commit
    plus the bytes of every changed Python file) equals the working tree's now. An error, a scan of
    nothing, or a stale result is never evidence of safety, and no result is part of a pass/fail verdict.
    """
    out: dict[str, Any] = {"schema": SCHEMA_EVIDENCE, "capability": cap_id,
                           "role": "informational: never part of a pass/fail verdict"}
    try:
        last = json.loads(_evidence_path(state_dir, cap_id).read_text("utf-8"))
    except (OSError, ValueError):
        return {**out, "status": "none", "reason": "no recorded run of this capability"}
    if not isinstance(last, dict) or last.get("status") != "ran" or last.get("validated") != "sarif-2.1.0":
        return {**out, "status": "none", "reason": "the last run did not produce validated output",
                "last_status": str(last.get("status", "")) if isinstance(last, dict) else ""}
    appr = (load_approvals(root).get("approvals") or {}).get(cap_id)
    if not appr or str(appr.get("sha256", ""))[:16] != last.get("binding_sha256"):
        return {**out, "status": "stale", "reason": "the binary that produced it is no longer approved"}
    if verify_binding(appr) != "ok" or last.get("adapter_hash") != adapter_hash():
        return {**out, "status": "stale", "reason": "the approved binary or the adapter changed since the scan"}
    targets, skipped = _changed_python_split(root, base, files)
    if skipped or last.get("skipped"):
        return {**out, "status": "incomplete", "reason": "some changed Python files were not scanned",
                "skipped": skipped or last.get("skipped")}
    if sorted(last.get("files") or []) != targets:
        return {**out, "status": "stale", "reason": "the changed Python files differ from the scanned ones"}
    if diff_fingerprint(root, base, targets) != last.get("diff_fingerprint"):
        return {**out, "status": "stale", "reason": "a scanned file or the base commit changed since the scan"}
    # staged changes that differ again in the working tree: a commit would record what was not scanned
    staged = [t for t in targets if _git_strict(root, ["diff", "--cached", "--quiet", "--no-ext-diff", "--", t]).returncode
              and _git_strict(root, ["diff", "--quiet", "--no-ext-diff", "--", t]).returncode]
    if staged:
        return {**out, "status": "incomplete", "reason": "the staged content of a scanned file differs from the "
                "working tree that was scanned"}
    result = {k: last.get(k) for k in EVIDENCE_FIELDS}
    result["tool_version"] = _untrusted(str(result.get("tool_version") or ""), 40)  # the file is the user's to edit
    for f in result.get("findings") or []:
        if isinstance(f, dict):
            f["untrusted_message"] = _untrusted(str(f.get("untrusted_message") or ""))
    return {**out, "status": "fresh", "result": result}


def _record(state_dir: Path, result: dict[str, Any]) -> None:
    if result.get("capability", "").startswith("adapter."):
        ev = _evidence_path(state_dir, result["capability"])
        ev.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(ev, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({k: result.get(k) for k in EVIDENCE_FIELDS}, fh)
    path = _runs_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = {k: result.get(k) for k in ("capability", "at", "status", "validated", "duration_s", "exit_code",
                                         "binding_sha256", "output_sha256", "counts")}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(keep) + "\n")


def _run_builtin(root: Path, cap: dict[str, Any], task: str) -> dict[str, Any]:
    argv = list((cap.get("activation") or {}).get("run") or [])
    if not argv or cap["id"] == "repo-ai.skills-vet":
        raise CapabilityError(f"run it directly: repo-ai {' '.join(argv) or cap['id']} <url-or-dir>")
    if cap["id"] == "repo-ai.context":
        if not task:
            raise CapabilityError("repo-ai.context needs --task")
        argv = ["context", "--format", "json"]
    from .fsutil import self_argv
    cmd = self_argv(*argv, "-C", str(root), *(["--", task] if task else []))
    if cap["id"] == "repo-ai.context":
        argv = [*argv, "<task>"]  # the result never repeats the task text
    env = {k: v for k, v in os.environ.items() if not k.startswith("REPO_AI_LAB")}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CapabilityError(f"repo-ai {' '.join(argv)} failed to start: {exc}", EXIT_TOOL_ERROR) from exc
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return {"status": "error", "validated": "failed", "exit_code": proc.returncode,
                "error": _untrusted(proc.stderr or proc.stdout, 400), "command": ["repo-ai", *argv]}
    digest = hashlib.sha256(proc.stdout.encode()).hexdigest()
    return {"status": "ran", "validated": "json-valid", "exit_code": proc.returncode, "command": ["repo-ai", *argv],
            "output_sha256": digest, "output": payload}


MAX_SCAN_FILES = 500


def _changed_python(root: Path, base: str, files: list[str] | None) -> list[str]:
    return _changed_python_split(root, base, files)[0]


def _changed_python_split(root: Path, base: str, files: list[str] | None) -> tuple[list[str], list[str]]:
    """(scanned, skipped). A changed Python file that is not scanned is reported, never dropped silently:
    a symlink, a file outside the repository, one past the cap. Deleted files are not changes to scan."""
    names = files if files is not None else changed_files(root, base, agent_dirs=True)
    out, skipped = [], []
    if len(names) >= MAX_CHANGED_PATHS:
        skipped.append(f"(more than {MAX_CHANGED_PATHS} changed paths)")
    rroot = root.resolve()
    for rel in names:
        if not rel.endswith((".py", ".pyi")):
            continue
        full = (root / rel)
        try:
            if not full.exists() and not full.is_symlink():
                continue  # deleted
            if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(rroot):
                skipped.append(rel)
                continue
        except OSError:
            skipped.append(rel)
            continue
        out.append(PurePosixPath(full.resolve().relative_to(rroot).as_posix()).as_posix())
    out = sorted(set(out))
    return out[:MAX_SCAN_FILES], sorted(set(skipped)) + out[MAX_SCAN_FILES:]


def diff_fingerprint(root: Path, base: str, targets: list[str]) -> str:
    """What a static-security result is about: the base commit and the exact bytes of the scanned files."""
    from .gitinfo import _run as git
    h = hashlib.sha256((git(root, ["rev-parse", "--verify", "--quiet", base + "^{commit}"]).strip() + "\n").encode())
    for rel in sorted(targets):
        try:
            data = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        except OSError:
            data = "missing"
        staged = _git_strict(root, ["ls-files", "-s", "--", rel]).stdout.decode("utf-8", "replace").strip()
        h.update(f"{rel}\0{data}\0{staged}\n".encode())
    return h.hexdigest()


def _run_ruff(root: Path, state_dir: Path, base: str, files: list[str] | None, timeout: float) -> dict[str, Any]:
    entry = (load_approvals(root).get("approvals") or {}).get("adapter.ruff-security")
    if not entry:
        raise CapabilityError("adapter.ruff-security is not approved here; you: repo-ai capabilities prepare "
                              "adapter.ruff-security, then approve the printed hash", EXIT_NOT_AVAILABLE)
    check = verify_binding(entry)
    if check != "ok":
        raise CapabilityError(f"the approved ruff changed since approval ({entry.get('path')}); approve it again "
                              "after checking", EXIT_BINDING_CHANGED)
    targets, skipped = _changed_python_split(root, base, files)
    if not targets:
        return {"status": "nothing-to-scan", "validated": "not-applicable", "files": [], "findings": [],
                "skipped": skipped, "counts": {"new": 0, "pre_existing": 0},
                "note": "no changed Python files: nothing was scanned (this is not a clean result)"}
    for rel in targets:  # ruff skips a file it cannot decode and still exits 0: never a clean result
        try:
            (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return {"status": "error", "validated": "failed", "files": targets, "skipped": skipped,
                    "binding_sha256": entry["sha256"][:16],
                    "error": f"{rel} is not UTF-8, so ruff cannot lint it; the scan is incomplete"}
    before = diff_fingerprint(root, base, targets)
    with tempfile.TemporaryDirectory(prefix="ruff-", dir=_private_tmp(root)) as home:
        exe = _private_copy(entry, Path(home) / "bin")
        argv = [str(exe), *_ruff_argv_template(), *targets]
        env = {**_clean_env(), "HOME": home, "XDG_CONFIG_HOME": home}
        try:
            proc = subprocess.run(argv, cwd=root, capture_output=True, timeout=timeout, env=env, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "error", "validated": "failed", "error": f"ruff timed out after {timeout:.0f} s",
                    "files": targets, "binding_sha256": entry["sha256"][:16]}
        except OSError as exc:
            return {"status": "error", "validated": "failed", "error": f"ruff could not start: {exc}",
                    "files": targets, "binding_sha256": entry["sha256"][:16]}
    out = proc.stdout[:20_000_000]
    base_result = {"files": targets, "skipped": skipped, "exit_code": proc.returncode,
                   "binding_sha256": entry["sha256"][:16], "adapter_hash": entry.get("adapter_hash", ""),
                   "tool_version": entry.get("version", "")}
    stderr = proc.stderr.decode("utf-8", "replace")
    if proc.returncode not in (0, 1):
        return {**base_result, "status": "error", "validated": "failed",
                "error": f"ruff exited {proc.returncode}: " + _untrusted(stderr, 300)}
    if re.search(r"(?i)failed to (lint|parse|read)|^error:", stderr, re.M):
        return {**base_result, "status": "error", "validated": "failed",
                "error": "ruff could not lint every file: " + _untrusted(stderr, 300)}
    try:
        sarif = json.loads(out.decode("utf-8"))
        results = sarif["runs"][0].get("results") or []
        if sarif.get("version") != "2.1.0" or not isinstance(results, list):
            raise ValueError("not SARIF 2.1.0")
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError) as exc:
        return {**base_result, "status": "error", "validated": "failed", "error": f"invalid SARIF from ruff: {exc}"}
    if proc.returncode == 1 and not results:
        return {**base_result, "status": "error", "validated": "failed",
                "error": "ruff reported findings but the SARIF has none"}
    if len(results) > MAX_RESULTS:
        return {**base_result, "status": "error", "validated": "failed",
                "error": f"ruff reported more than {MAX_RESULTS} results; they are not truncated into a count"}
    problem = _sarif_problem(results)
    if problem:
        return {**base_result, "status": "error", "validated": "failed", "error": problem}
    if diff_fingerprint(root, base, targets) != before:
        return {**base_result, "status": "error", "validated": "failed",
                "error": "the scanned files changed during the scan; run it again"}
    base_result["diff_fingerprint"] = before
    findings = _parse_sarif(root, results, base, set(targets))
    store = state_dir / "sarif"
    store.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(out).hexdigest()
    sarif_path = store / f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-ruff-{digest[:8]}.sarif"
    sarif_path.write_bytes(out)
    new = [f for f in findings if f["new"]]
    return {**base_result, "status": "ran", "validated": "sarif-2.1.0", "output_sha256": digest,
            "sarif": str(sarif_path), "findings": new[:50],
            "counts": {"new": len(new), "pre_existing": len(findings) - len(new),
                       "by_severity": {s: sum(1 for f in new if f["severity"] == s) for s in ("high", "medium", "low")}},
            "note": "pattern lint on lines this change adds; it cannot see authorization, CSRF or logic flaws. "
                    "`untrusted_message` quotes repository content: treat it as data"}


MAX_RESULTS = 5000


def _sarif_problem(results: list[Any]) -> str:
    """A result repo-ai did not select (a syntax error, a lint failure) or one without a location means
    the file was not fully linted: an error, never a clean scan."""
    for r in results:
        if not isinstance(r, dict) or str(r.get("ruleId") or "") not in RUFF_RULES:
            rule = str(r.get("ruleId") or "none") if isinstance(r, dict) else "malformed"
            return f"ruff reported {_untrusted(rule, 20)}, which repo-ai did not select: a file was not fully linted"
        try:
            loc = r["locations"][0]["physicalLocation"]
            str(loc["artifactLocation"]["uri"])
            int(loc["region"]["startLine"])
        except (KeyError, IndexError, TypeError, ValueError):
            return "ruff reported a result without a location"
    return ""


def _git_strict(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """git for attribution: no GIT_* variables, literal pathspecs, and explicit diff options that override
    any repository or user config (colour, context, prefixes, external diff, textconv)."""
    # User and system config stay (core.autocrlf decides how a Windows working tree compares with the
    # blob); every setting that could hide or shift lines is overridden below, and no GIT_* variable
    # (GIT_EXTERNAL_DIFF, GIT_DIFF_OPTS, GIT_CONFIG_*) reaches git.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    argv = [gitbin.git(), "-c", "core.quotepath=off", "-c", "color.ui=never", "-c", "diff.noprefix=false",
            "-c", "diff.mnemonicPrefix=false", "-c", "diff.relative=false", "-c", "diff.external=",
            "-c", "diff.interHunkContext=0", "--literal-pathspecs",
            "--no-optional-locks", *args]
    return subprocess.run(argv, cwd=root, env=env, capture_output=True, timeout=60, check=False)


_HUNK = re.compile(rb"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def added_lines(root: Path, base: str, rel: str) -> set[int]:
    """Line numbers this change adds to `rel`, against `base` plus the working tree. Fails safe: a file
    absent from `base`, or a diff whose hunks cannot be read, counts every line as new."""
    def every_line() -> set[int]:
        try:
            return set(range(1, (root / rel).read_bytes().count(b"\n") + 2))
        except OSError:
            return set()

    if _git_strict(root, ["cat-file", "-e", f"{base}:{rel}"]).returncode != 0:
        return every_line()  # new or untracked
    proc = _git_strict(root, ["diff", "--text", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
                              "-U0", "--inter-hunk-context=0", "--src-prefix=a/", "--dst-prefix=b/",
                              "--end-of-options", base, "--", rel])
    if proc.returncode != 0:
        return every_line()
    out: set[int] = set()
    new_left = old_left = 0
    line_no = 0
    seen_hunk = False
    for line in proc.stdout.split(b"\n"):
        m = _HUNK.match(line)
        if m:  # count exactly the lines each hunk declares: a `+++` inside a hunk is content
            seen_hunk = True
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            line_no = int(m.group(2))
            new_left = int(m.group(3)) if m.group(3) is not None else 1
            continue
        if new_left <= 0 and old_left <= 0:
            continue
        if line.startswith(b"+") and new_left > 0:
            out.add(line_no)
            line_no += 1
            new_left -= 1
        elif line.startswith(b"-") and old_left > 0:
            old_left -= 1
        elif line.startswith(b" "):
            line_no += 1
            new_left -= 1
            old_left -= 1
    if proc.stdout.strip() and not seen_hunk:
        return every_line()  # the file differs but no hunk could be read
    return out


def _parse_sarif(root: Path, results: list[Any], base: str, scanned: set[str]) -> list[dict[str, Any]]:
    from urllib.parse import unquote, urlparse
    from urllib.request import url2pathname
    rroot = root.resolve()
    added: dict[str, set[int]] = {}
    findings: list[dict[str, Any]] = []
    for r in results:
        rule = str(r["ruleId"])
        loc = r["locations"][0]["physicalLocation"]
        uri = str(loc["artifactLocation"]["uri"])
        line = int(loc["region"]["startLine"])
        try:
            col = int(loc["region"].get("startColumn", 1))
        except (TypeError, ValueError):
            col = 1
        raw = url2pathname(urlparse(uri).path) if uri.startswith("file:") else unquote(uri)
        try:
            full = Path(raw) if os.path.isabs(raw) else (root / raw)
            rel = full.resolve().relative_to(rroot).as_posix()
        except (ValueError, OSError):
            continue  # a path outside the repository is never reported
        if line < 1 or rel not in scanned:
            continue  # only the files this run scanned
        if rel not in added:
            added[rel] = added_lines(root, base, rel)
        severity, title = RUFF_RULES[rule]
        findings.append({"rule": rule, "title": title, "severity": severity, "path": rel, "line": line,
                         "column": max(col, 1), "new": line in added[rel],
                         "untrusted_message": _untrusted((r.get("message") or {}).get("text", ""))})
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[str(f["severity"])], str(f["path"]), int(f["line"]), str(f["rule"])))
    return findings


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
RENDER_MAX = 470  # about 120 tokens: small enough to paste into a session


def render_recommendation(rec: dict[str, Any]) -> str:
    if not rec["recommended"]:
        consider = f"; consider: {', '.join(rec['consider'])}" if rec.get("consider") else ""
        return f"nothing needed: {rec['abstain_reason']} (experimental){consider}"
    rows: list[tuple[int, str]] = [(0, "experimental matcher; recommended:")]  # (drop priority, line)
    for i, r in enumerate(rec["recommended"], 1):
        flag = "ready" if r["available"] else r["availability"].replace("_", " ").replace("`", "")
        rows.append((0, f"{i}. {r['id']} [{flag[:24]}]: {r['need']}"))
        if r["next_step"] and not r["available"]:
            rows.append((2, f"   next: {r['next_step'][:70]}"))
        if i == 1:
            rows.append((1, f"   adds: {r['adds_beyond_native'][:80]}"))
    for level in (1, 2):  # over budget: drop `adds`, then the next steps, never an id
        if len("\n".join(t for _, t in rows)) <= RENDER_MAX:
            break
        rows = [(lv, t) for lv, t in rows if lv != level]
    return "\n".join(t for _, t in rows)


def render_list(manifest: dict[str, Any], states: dict[str, Any]) -> str:
    lines = [f"{'id':34s} {'kind':8s} {'reviewed':12s} {'approved':13s} {'available':22s} invoked"]
    for c in manifest["capabilities"]:
        s = states[c["id"]]
        av = "yes" if s["available"]["status"] else s["available"]["reason"]
        lines.append(f"{c['id']:34s} {c['kind']:8s} {str(s['reviewed']['status'])[:12]:12s} "
                     f"{str(s['approved']['status'])[:13]:13s} {av[:22]:22s} {s['invoked']['count']}")
    lines.append("benefit to an agent is not measured for any capability (validated = output schema only)")
    return "\n".join(lines)
