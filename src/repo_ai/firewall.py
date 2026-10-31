"""Skill Firewall: quarantine and layered inspection of third-party skills.

Every external skill is treated as adversarial. It is fetched by immutable
commit and blob SHA into a quarantine store:
- outside every repository;
- files are written non-executable (0600);
- never in a directory Claude Code auto-discovers;
- after validating paths, sizes, counts and file types;
- symlinks and submodules are refused.

Nothing is executed to inspect it.

Inspection layers. Each finding carries a severity, whether it is
`confirmed`, `suspected` or `unknown`, and `file:line` evidence with
secrets redacted:

1. specification: Agent Skills fields and constraints;
2. instructions: prompt injection, authority claims, hidden text,
   requests to change permissions, settings or memory;
3. code: remote execution, exfiltration, credential access, destructive
   commands, persistence, obfuscation, binaries;
4. dependencies and network: declared dependencies, URL and git
   dependencies, lifecycle scripts, hosts and IP literals;
5. provenance: publisher impersonation, forks, archived repos, repository
   age;
6. licence;
7. compatibility: required services and network access;
8. conflicts: name collisions and trigger overlap with existing skills.

Verdict: `blocked` if any critical finding (never installable), `review`
if any high finding or incomplete evidence, `eligible` otherwise. No
scanner can prove a skill safe: `eligible` means no known problem.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .security import redact_text

MAX_FILES, MAX_TOTAL, MAX_FILE = 200, 3_000_000, 600_000
TEXT_EXT = {".md", ".txt", ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".json",
            ".yaml", ".yml", ".toml", ".html", ".css", ".rb", ".pl", ".ps1", ".bat", ".cfg",
            ".ini", ".xml", ".csv", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".sql", ".xsd",
            ".xsl", ".xslt", ".rst", ".mdx", ""}
# Licences are matched as whole SPDX identifiers (case-insensitive), never as
# substrings. MPL-2.0 is file-level copyleft and stays permissive for reuse
# (as before); the other MPL versions, and every GPL/LGPL/AGPL/EPL/EUPL and
# CC-*-SA licence, are copyleft. BSL-1.0 is the Boost licence, not BUSL.
PERMISSIVE = {"MIT", "MIT-0", "APACHE-2.0", "BSD-2-CLAUSE", "BSD-3-CLAUSE", "ISC", "MPL-2.0",
              "CC-BY-3.0", "CC-BY-4.0", "CC0-1.0", "UNLICENSE", "0BSD", "ZLIB", "BSL-1.0",
              "PYTHON-2.0", "PSF-2.0"}
COPYLEFT = {"GPL-1.0", "GPL-2.0", "GPL-3.0", "AGPL-1.0", "AGPL-3.0", "LGPL-2.0", "LGPL-2.1", "LGPL-3.0",
            "EPL-1.0", "EPL-2.0", "MPL-1.0", "MPL-1.1", "MPL-2.0-NO-COPYLEFT-EXCEPTION",
            "EUPL-1.0", "EUPL-1.1", "EUPL-1.2", "CC-BY-SA-1.0", "CC-BY-SA-2.0", "CC-BY-SA-2.5",
            "CC-BY-SA-3.0", "CC-BY-SA-4.0"}
# Licence findings that make a skill not installable (no usable reuse right).
LICENSE_GATE_RULES = frozenset({"no-usable-license", "license-restricted", "license-unrecognized"})
SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


class QuarantineError(RuntimeError):
    pass


@dataclass(slots=True)
class Finding:
    severity: str        # critical | high | medium | low | info
    kind: str            # confirmed | suspected | unknown
    category: str
    rule: str
    file: str = ""
    line: int = 0
    evidence: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Report:
    candidate_id: str
    content_hash: str
    files: list[dict[str, Any]]
    findings: list[Finding] = field(default_factory=list)
    license: str = ""
    verdict: str = "unknown"
    complete: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "content_hash": self.content_hash,
                "files": self.files, "license": self.license, "verdict": self.verdict,
                "complete": self.complete, "findings": [f.to_json() for f in self.findings],
                "counts": self.counts()}

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out


# --------------------------------------------------------------------------
# quarantine
# --------------------------------------------------------------------------
def quarantine_root() -> Path:
    """Owner-only from the start: quarantined third-party content is nobody else's to read."""
    from .registry import registry_home
    root = registry_home() / "quarantine"
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


_SAFE_PART = re.compile(r"^[A-Za-z0-9._+@=-][A-Za-z0-9 ._+@=-]{0,120}$")


def safe_rel(path: str) -> PurePosixPath:
    p = PurePosixPath(path)
    if p.is_absolute() or not p.parts or any(part in {"..", "."} or not _SAFE_PART.match(part)
                                             for part in p.parts) or "\x00" in path:
        raise QuarantineError(f"unsafe path in artifact: {path!r}")
    return p


def content_hash(files: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x["path"]):
        h.update(f"{f['path']}\x00{f['sha256']}\n".encode())
    return h.hexdigest()


def _store(dest: Path, rel: PurePosixPath, data: bytes) -> dict[str, Any]:
    target = dest / "files" / rel
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return {"path": rel.as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def quarantine_github(client, cand) -> tuple[Path, list[dict[str, Any]], list[Finding]]:
    """Fetch every file under the candidate's directory at its pinned commit."""
    from .radar import _tree
    _, tree = _tree(client, cand.owner, cand.repo, cand.commit)
    prefix = cand.path.rstrip("/") + "/" if cand.path else ""
    entries = [e for e in tree if e.get("path", "").startswith(prefix) or not prefix]
    findings: list[Finding] = []
    dest = quarantine_root() / hashlib.sha256(cand.id.encode()).hexdigest()[:24]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, mode=0o700)
    files: list[dict[str, Any]] = []
    total = 0
    for entry in entries:
        rel_raw = entry["path"][len(prefix):]
        mode = entry.get("mode", "100644")
        if entry.get("type") == "tree":
            continue
        if mode == "120000":
            findings.append(Finding("high", "confirmed", "artifact", "symlink", rel_raw, 0,
                                    "symbolic link in the skill (not fetched)"))
            continue
        if entry.get("type") == "commit" or mode == "160000":
            findings.append(Finding("high", "confirmed", "artifact", "submodule", rel_raw, 0,
                                    "git submodule (unreviewable nested source)"))
            continue
        try:
            rel = safe_rel(rel_raw)
        except QuarantineError as exc:
            findings.append(Finding("critical", "confirmed", "artifact", "unsafe-path", rel_raw, 0,
                                    str(exc)))
            continue
        size = int(entry.get("size") or 0)
        if len(files) >= MAX_FILES or size > MAX_FILE or total + size > MAX_TOTAL:
            findings.append(Finding("high", "unknown", "artifact", "too-large", rel.as_posix(), 0,
                                    f"not fetched ({size} bytes; limits {MAX_FILE}/{MAX_TOTAL})"))
            continue
        data = _from_tarball(client, cand, entry["path"])
        if data is None:
            blob = client.get("api.github.com",
                              f"/repos/{cand.owner}/{cand.repo}/git/blobs/{entry['sha']}", ttl=-1)
            data = base64.b64decode(blob.get("content", ""))
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest() != entry["sha"]:
            findings.append(Finding("critical", "confirmed", "integrity", "blob-mismatch",
                                    rel.as_posix(), 0, "content does not match its git blob SHA"))
            continue
        total += len(data)
        meta = _store(dest, rel, data)
        meta["executable"] = mode == "100755"
        files.append(meta)
    (dest / "manifest.json").write_text(json.dumps({"candidate": cand.to_json(), "files": files},
                                                   indent=1), encoding="utf-8")
    return dest, files, findings


_TARBALLS: dict[tuple[str, str, str], dict[str, bytes]] = {}


def _from_tarball(client, cand, repo_path: str) -> bytes | None:
    """Read one file from the repo tarball at the pinned commit (one request
    per repo instead of one per file). Members are validated: no links, no
    devices, no absolute or `..` paths, size-capped; the caller still checks
    the git blob SHA of what it returns."""
    import io
    import tarfile
    key = (cand.owner, cand.repo, cand.commit)
    if key not in _TARBALLS:
        try:
            raw = client.tarball(cand.owner, cand.repo, cand.commit)
        except Exception:  # noqa: BLE001 - fall back to per-blob fetches
            _TARBALLS[key] = {}
            return None
        members: dict[str, bytes] = {}
        total = 0
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            for info in tar.getmembers():
                if not info.isfile() or info.size > MAX_FILE:
                    continue
                name = info.name.split("/", 1)[1] if "/" in info.name else ""
                if not name or ".." in name.split("/") or name.startswith("/"):
                    continue
                total += info.size
                if total > 40_000_000:
                    break
                fh = tar.extractfile(info)
                if fh is not None:
                    members[name] = fh.read(MAX_FILE + 1)
        _TARBALLS[key] = members
    return _TARBALLS[key].get(repo_path)


def quarantine_local(source: Path, label: str,
                     store: Path | None = None) -> tuple[Path, list[dict[str, Any]], list[Finding]]:
    """Quarantine a local directory (used for adversarial fixtures and for
    vetting a skill someone sent you). Symlinks are never followed.
    `store` replaces the quarantine root (the inventory uses a temporary one)."""
    findings: list[Finding] = []
    dest = (store or quarantine_root()) / hashlib.sha256(
        f"local:{source.resolve()}:{label}".encode()).hexdigest()[:24]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, mode=0o700)
    files: list[dict[str, Any]] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        for name in sorted([*dirnames, *filenames]):
            full = Path(dirpath) / name
            rel_raw = full.relative_to(source).as_posix()
            if full.is_symlink():
                findings.append(Finding("high", "confirmed", "artifact", "symlink", rel_raw, 0,
                                        f"symbolic link -> {os.readlink(full)} (not followed)"))
                if name in dirnames:
                    dirnames.remove(name)
                continue
            if name in dirnames:
                continue
            try:
                rel = safe_rel(rel_raw)
            except QuarantineError as exc:
                findings.append(Finding("critical", "confirmed", "artifact", "unsafe-path", rel_raw, 0,
                                        str(exc)))
                continue
            st = os.lstat(full)
            if not stat.S_ISREG(st.st_mode):  # FIFOs, devices and sockets are never read
                findings.append(Finding("high", "confirmed", "artifact", "special-file", rel.as_posix(), 0,
                                        "not a regular file (not read)"))
                continue
            size = st.st_size
            if len(files) >= MAX_FILES or size > MAX_FILE or total + size > MAX_TOTAL:
                findings.append(Finding("high", "unknown", "artifact", "too-large", rel.as_posix(), 0,
                                        f"not copied ({size} bytes)"))
                continue
            fd = os.open(str(full), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as fh:
                data = fh.read(MAX_FILE + 1)  # the size may change after the stat
            if len(data) > MAX_FILE or total + len(data) > MAX_TOTAL:
                findings.append(Finding("high", "unknown", "artifact", "too-large", rel.as_posix(), 0,
                                        "grew past the size limit while being read"))
                continue
            total += len(data)
            meta = _store(dest, rel, data)
            meta["executable"] = bool(st.st_mode & stat.S_IXUSR)
            files.append(meta)
    (dest / "manifest.json").write_text(json.dumps({"source": f"local:{label}", "files": files},
                                                   indent=1), encoding="utf-8")
    return dest, files, findings


def _archive_findings(path: str, data: bytes) -> list[Finding]:
    """An archive inside a skill: list members without extracting them."""
    import io
    import tarfile
    import zipfile
    names: list[str] = []
    links: list[str] = []
    try:
        if path.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        else:
            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                for m in tf.getmembers():
                    names.append(m.name)
                    if m.issym() or m.islnk():
                        links.append(f"{m.name} -> {m.linkname}")
    except Exception as exc:  # noqa: BLE001 - malformed archives are findings, not crashes
        return [Finding("high", "unknown", "artifact", "unreadable-archive", path, 0, str(exc)[:120])]
    out = [Finding("medium", "unknown", "artifact", "archive", path, 0,
                   f"bundled archive with {len(names)} member(s); contents not inspected")]
    for f in quarantine_archive_member_check(names):
        f.file = f"{path}!{f.file}"
        out.append(f)
    for link in links:
        out.append(Finding("high", "confirmed", "artifact", "archive-link", path, 0, link[:120]))
    return out


def quarantine_archive_member_check(names: list[str]) -> list[Finding]:
    """For archives (zip/tar) offered as skills: every member path must be safe."""
    out = []
    for name in names:
        try:
            safe_rel(name)
        except QuarantineError as exc:
            out.append(Finding("critical", "confirmed", "artifact", "archive-path", name, 0, str(exc)))
    return out


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------
_RULES: list[tuple[str, str, str, str, re.Pattern[str]]] = [
    # (severity, kind, category, rule, pattern) — applied to every text file
    ("critical", "confirmed", "remote-exec", "download-piped-to-shell",
     re.compile(r"(?i)\b(curl|wget|iwr|invoke-webrequest)\b[^\n|]*\|&?\s*(sudo\s+)?(ba|z|da|k|fi)?sh\b")),
    ("critical", "confirmed", "remote-exec", "download-substituted-into-shell",
     # bash -c "$(curl …)", sh <(curl …), python -c "$(wget …)"
     # (`.` only where a command starts: "1. `curl` for API testing" is a numbered list item)
     re.compile(r"(?i)(\b((ba|z|da|k)?sh|python[0-9.]*|node|perl|ruby|eval|source)|(?<![\w.])\.)\s+(-\w+\s+)*"
                r"[\"']?\s*(\$\(|`|<\()\s*(curl|wget|iwr|invoke-webrequest)\b")),
    ("critical", "confirmed", "remote-exec", "download-then-run",
     re.compile(r"(?i)\b(curl|wget)\b[^\n]*?(\s-[a-zA-Z]*[oO]\s*|--output[= ]\s*|>\s*)(\S+)[^\n]*?(&&|;|\|\|)\s*"
                r"(chmod\s+\+?[0-7x]+\s+\S+\s*(&&|;)\s*)?(sudo\s+)?((ba|z|da|k)?sh|python[0-9.]*|node|perl|ruby|"
                r"source|\.)?\s*[./~$]")),
    ("high", "confirmed", "remote-exec", "shell-command-substitution",
     # an interpreter told to run whatever a command prints: sh -c "$(tail … assets/logo.png)"
     re.compile(r"\b((ba|z|da|k)?sh|python[0-9.]*|node|perl|ruby)\s+(-\w+\s+)*-c\s*[\"']?\s*(\$\(|`)")),
    ("high", "confirmed", "remote-exec", "process-substitution-into-shell",
     re.compile(r"\b((ba|z|da|k)?sh|source|\.)\s+<\(")),
    ("high", "confirmed", "remote-exec", "xargs-shell",
     re.compile(r"\|\s*xargs\b[^\n|]*\b((ba|z|da|k)?sh|python[0-9.]*|node|perl|ruby)\b")),
    ("high", "confirmed", "remote-exec", "executes-asset",
     # an interpreter run directly on an asset (not a script taking an asset as an argument)
     re.compile(r"(?i)\b((ba|z|da|k)?sh|python[0-9.]*|node|perl|ruby|source|eval|exec)\s+(-\w+\s+)*[\"']?(\S*/)?assets?/|"
                r"\bchmod\s+\S+\s+[\"']?(\S*/)?assets?/|"
                r"(\$\(|`)\s*(cat|tail|head|base64|xxd|dd|strings|sed|awk)\b[^\n]*\bassets?/")),
    ("high", "confirmed", "remote-exec", "pipe-to-shell",
     # a command piped into an interpreter (case-sensitive: `| Python |` is a table cell)
     re.compile(r"[^\s|]\s*\|&?\s*(sudo\s+)?(/(usr/)?bin/)?((ba|z|da|k|fi)?sh|python[0-9.]*|node|perl|ruby)"
                r"(?![\w.-])(?!\s*\|)")),
    ("critical", "confirmed", "remote-exec", "eval-remote",
     re.compile(r"(?i)(eval|exec|source)\s*[\"'(]?\s*\$?\(\s*(curl|wget)|python[0-9.]*\s+-c\s+[\"']?\$\((curl|wget)")),
    ("critical", "confirmed", "credentials", "credential-files",
     re.compile(r"(?i)(~|\$HOME|/home/\w+|/Users/\w+)/\.(ssh|aws|gnupg|kube|docker/config|config/gh|netrc|npmrc|pypirc)\b|\.aws/credentials|id_(rsa|ed25519)\b")),
    ("critical", "confirmed", "credentials", "keychain-or-token-cli",
     re.compile(r"(?i)security\s+find-(generic|internet)-password|gh\s+auth\s+token|secret-tool\s+lookup|cmdkey\s+/list")),
    ("low", "confirmed", "credentials", "secret-env-access",
     re.compile(r"(?i)\b(ANTHROPIC_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|NPM_TOKEN|CLAUDE_CODE_OAUTH_TOKEN)\b")),
    ("critical", "suspected", "exfiltration", "env-dump-to-network",
     re.compile(r"(?i)(\benv\b|printenv|os\.environ|process\.env)[^\n]{0,80}(curl|wget|requests\.(post|put)|fetch\(|urlopen|\bnc\b)")),
    ("high", "suspected", "exfiltration", "post-file-contents",  # uploads are common in API docs: review
     re.compile(r"(?i)curl\b[^\n]*((-d|--data(-binary|-raw|-urlencode)?|-F|--form|--upload-file|-T)\s*[\"']?@(?!-)"
                r"|(-F|--form)\s+[\"']?[\w.-]+=@(?!-))")),
    ("critical", "confirmed", "exfiltration", "netcat-pipe",
     re.compile(r"(?i)\|\s*(nc|ncat|netcat|socat)\b\s+\S+\s+\d+")),
    ("high", "confirmed", "destructive", "recursive-delete",  # other flags may come first; one parse per flag
     re.compile(r"(?i)\brm\s+(?:-{1,2}[a-z][a-z-]*\s+)*?-[a-z]*(r[a-z]*f|f[a-z]*r)[a-z]*\s+(?:-{1,2}[a-z][a-z-]*\s+)*?"
                r"[\"']?(/|~/?|\$\{?HOME\}?[\"']?/?|\*|\.\.?/?|/\*)[\"'*.]*(\s|$|;|&)")),
    ("high", "confirmed", "destructive", "git-destructive",
     re.compile(r"(?i)\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+(-f\b|--force)|branch\s+-D)")),
    ("critical", "confirmed", "destructive", "disk-wipe",
     re.compile(r"(?i)\bmkfs\b|\bdd\s+if=\S+\s+of=/dev/|>\s*/dev/(sd|disk|nvme)")),
    ("critical", "confirmed", "persistence", "persistence",
     re.compile(r"(?i)\bcrontab\b|launchctl\s+(load|bootstrap)|LaunchAgents|systemctl\s+--user\s+enable|"
                # a redirect into a shell dotfile (`<Text>Profile` in JSX is not one)
                r">>?\s*[\"']?(~|\$HOME|\$\{HOME\})?/?\.(bashrc|zshrc|profile|bash_profile)\b|"
                r"\.git/hooks/|PROMPT_COMMAND=")),
    ("critical", "confirmed", "permission-escalation", "bypass-permissions",
     re.compile(r"(?i)dangerously-skip-permissions|bypassPermissions|allowUnsandboxedCommands\s*[\"']?\s*:\s*true|"
                r"dangerouslyDisableSandbox")),
    ("critical", "suspected", "permission-escalation", "edit-claude-settings",
     # a redirect must *target* the .claude path (the `>` closing `<skill-dir>` is not a redirect);
     # copy/move/tee/link/write calls may name it anywhere in the next 80 characters
     re.compile(r"(?i)(>>?\s*[\"']?[^\s\"'|;&<>]*|(\btee\b|\bcp\b|\bmv\b|\bln\b|write_text|writeFile|"
                r"open\([^)]*[\"'][wa][\"'])[^\n]{0,80})\.claude/(settings(\.local)?\.json|CLAUDE\.md|agents/|"
                r"skills/|hooks)|"
                r"[\"']permissions[\"']\s*:\s*\{\s*[\"']allow")),
    ("medium", "confirmed", "permission-escalation", "sudo-or-chmod",
     re.compile(r"(?i)\bsudo\s+\S|chmod\s+(-R\s+)?(777|u\+s|\+s)\b|\bsetuid\b")),
    ("high", "suspected", "obfuscation", "decode-and-run",
     re.compile(r"(?i)base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh|exec\(\s*(base64|codecs)\.|eval\(\s*atob\(|"
                r"exec\(compile\(|String\.fromCharCode\([^)]{40,}")),
]
_INJECTION = re.compile(
    r"(?i)(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|above|earlier|system)\s+"
    r"(instructions|prompts|rules|messages)|you\s+are\s+now\s+(a|an|in)\s+\w+\s+(mode|assistant|agent)|"
    r"(here\s+is|this\s+is|use)\s+(your|the|a)\s+new\s+system\s+prompt|new\s+system\s+prompt\s*:|"
    r"(do\s+not|don't|never)\s+(tell|inform|reveal\s+to|mention\s+to)\s+(the\s+)?user\s+"
    r"(about|that\s+(you|this|we|it)|anything|what\s+you|you\s+are)|act\s+as\s+(root|admin|the\s+system)|"
    r"override\s+(the\s+)?(system|safety|project)\s+(prompt|instructions|rules)|"
    r"\b(run|execute|install|delete|remove|send|upload|push|deploy|commit)\b[^.\n]{0,40}\bwithout\s+"
    r"(asking|confirmation|permission|telling)|silently\s+(run|execute|install|send|upload|delete)|"
    r"this\s+(skill|message|instruction)\s+(has|takes)\s+(higher|highest|top)\s+priority")
_NEGATED = re.compile(r"(?i)\b(never|don't|do\s+not|must\s+not|avoid|instead\s+of|rather\s+than|"
                      r"not\s+safe|dangerous|forbidden|refuse)\b")
# Code only (scripts, fenced blocks): what a program does, which prose may legitimately name (skill-vet-fresh-v1:
# a reverse shell and a keychain reader carried no finding at all).
_CODE_RULES: list[tuple[str, str, str, str, re.Pattern[str]]] = [
    ("critical", "confirmed", "remote-exec", "reverse-shell",  # a shell wired to a network stream (not a port probe)
     re.compile(r"(?i)\b(ba|z|k)?sh\s+-i\b[^\n;&|]{0,40}[<>]&?\s*/dev/(tcp|udp)/|/dev/(tcp|udp)/\S+\s+0>&1|"
                r"\bexec\s+\d+<>\s*/dev/(tcp|udp)/|\b(nc|ncat|netcat)\b[^\n|&;]{0,80}\s-[a-z]*e\s+\S*sh\b|"
                r"\bsocat\b[^\n]{0,120}\bexec:[^\n]{0,40}sh\b")),
    ("critical", "confirmed", "destructive", "no-preserve-root",
     re.compile(r"(?i)\brm\b[^\n;&|]{0,80}--no-preserve-root\b")),
    ("high", "suspected", "credentials", "credential-store-path",  # a path alone is not theft: review, not blocked
     re.compile(r"(?i)[\"']\.(ssh|aws|gnupg|netrc|docker)[\"'/]|Library/Keychains|\blogins\.json\b|Login Data\b|"
                r"\bkey4\.db\b|\bCookies\.binarycookies\b")),
]
# Whole code file or block, across lines: a secret read and a network send in the same program, and a download
# made executable. One finding per file each.
_SECRET_SOURCE = re.compile(r"(?i)(\bcat\b[^\n]*\.env\b|\$\(\s*(env|printenv)\b|\bos\.environ\b|\bprocess\.env\b|"
                            r"[\"']\.(ssh|aws|gnupg|netrc)[\"'/]|~/\.(ssh|aws|gnupg|netrc)|Library/Keychains|"
                            r"\blogins\.json\b|Login Data\b|\bopen\([^\n)]*\.env[\"'])")
_NETWORK_SEND = re.compile(r"(?i)\bcurl\b[^\n]*(\s-d\b|--data|\s-F\b|--form|\s-T\b|--upload-file|-X\s*(POST|PUT))|"
                           r"\burlopen\s*\([^\n]*data\s*=|\burlopen\s*\(\s*[^\n,)]+,\s*\w|"
                           r"\brequests\.(post|put)\s*\(|\bhttpx\.(post|put)\s*\(|\bfetch\s*\([^\n]*method\s*:\s*"
                           r"[\"'](POST|PUT)|\bwget\b[^\n]*--post-(data|file)|\bsocket\.(socket|create_connection)\b")
_FETCHED_EXEC = re.compile(r"(?i)\b(curl|wget)\b[^\n]*(\s-[a-zA-Z]*[oO]\s|--output[= ]|>\s*\S)")
_MAKE_EXEC = re.compile(r"(?i)\bchmod\s+(\+x|u\+x|[0-7]*[1357][0-7]{0,2}\b)")


_SOCKET_TO_SHELL = (re.compile(r"(?i)\bsocket\.(socket|create_connection)\b|\.connect\s*\(\s*\("),
                    re.compile(r"(?i)\bdup2\s*\(\s*[\w.]+\.fileno\(\)"),
                    re.compile(r"(?i)/bin/(ba|z|k)?sh\b|\bpty\.spawn\s*\(|\bsubprocess\.\w+\(\s*\[?\s*[\"'](ba|z)?sh\b"))
MAX_SCAN_LINE = 2_000  # longer lines are cut for these patterns (a SKILL.md line over 2,000 is already a surface)


def code_risks(code: str) -> list[tuple[str, str, str]]:
    """(category, rule, evidence) for whole-program behaviour that no single line shows. Evidence is redacted."""
    out = []
    code = "\n".join(line[:MAX_SCAN_LINE] for line in code.splitlines())
    if all(p.search(code) for p in _SOCKET_TO_SHELL):
        out.append(("remote-exec", "reverse-shell", "a socket is connected, duplicated onto stdio and given a shell"))
    src, send = _SECRET_SOURCE.search(code), _NETWORK_SEND.search(code)
    if src and send:
        out.append(("exfiltration", "read-and-send",
                    redact_text(f"reads {src.group(0)[:40]!r}, sends {send.group(0)[:60]!r}")[:140]))
    fetched, made = _FETCHED_EXEC.search(code), _MAKE_EXEC.search(code)
    if fetched and made:
        out.append(("remote-exec", "download-made-executable",
                    redact_text(f"{fetched.group(0)[:60]!r} then {made.group(0)[:30]!r}")[:140]))
    return out


# What a skill's prose asks the agent to do, by attack class (skill-vet-fresh-v1: prose-only skills that took over
# the agent, hid things from the user or weakened the project's checks read as inert). Matched per paragraph, so a
# sentence wrapped over lines still matches. No negation clears a match: "never mind the old notes, delete …" is
# phrased like a prohibition, and a prohibition about these subjects costs only a question under SAFE_AUTO.
_W = r"[^.!?\n]{0,48}"
_INSTRUCTION_RISKS: list[tuple[str, re.Pattern[str]]] = [
    ("authority-override", re.compile(
        r"(?i)\b(ignore|disregard|forget|override|supersede|overrule)\b" + _W +
        r"\b(instructions?|prompts?|rules?|guidelines?|guardrails?|polic(y|ies)|directives?|constraints?)\b|"
        r"\b(this|these)\s+(skill|block|section|directives?|instructions?|rules?)\b" + _W +
        r"\b(wins?|takes?\s+precedence|overrides?|outranks?|supersedes?|prevails?|beats?)\b|"
        r"\b(outrank|override|overrule|take\s+precedence\s+over)s?\b" + _W + r"\b(the\s+)?(user|developer|operator)\b|"
        r"\byou\s+are\s+(now\s+)?(an?\s+)?(unrestricted|unfiltered|jailbroken)\b|"
        r"\b(stop|never)\s+refus(e|ing)\b")),
    ("concealment", re.compile(
        r"(?i)\b(do\s+not|don't|never|without)\s+(tell|telling|inform|informing|reveal|revealing|mention|mentioning|"
        r"disclos(e|ing)|report|reporting|notify|notifying|surface|surfacing|flag|flagging|show|showing)\b" + _W +
        r"\b(user|human|reviewer|maintainer|anyone|skill|this|that|these|changes?|failures?|warnings?)\b|"
        r"\b(hide|conceal|omit|suppress|bury)\b" + _W +
        r"\b(from\s+the\s+(user|summary|report|diff|output|reviewer)|changes?|failures?|warnings?|errors?|this\s+step)\b|"
        r"\b(covertly|secretly)\b|\b(silently|quietly)\s+(run|execute|install|send|upload|post|delete|remove|add|"
        r"commit|push|modify|change|disable|edit|rewrite|apply|proceed|continue|acknowledge)\w*\b|"
        r"\b(acknowledge|proceed|continue)\w*\s+(silently|quietly)\b|"
        r"\b(report|describe|present|mark|show|summari[sz]e)\w*\b" + _W +
        r"\b(as\s+)?(pass(ing|ed)?|green|successful|success|clean)\b" + _W +
        r"\b(even\s+(if|when|though)|regardless|whether\s+or\s+not)\b")),
    ("approval-bypass", re.compile(
        r"(?i)\b(assume|treat|consider)\b" + _W + r"\b(approv\w*|consent\w*|permission\w*|confirmation\w*)\b" + _W +
        r"\b(granted|given|cancel+ed|implied|unnecessary|not\s+needed)\b|"
        r"\bauto[- ]?approv\w*\b|\bbypass\s*permissions\b|\bdangerously[- ]?skip\w*|--no-verify\b|--yolo\b|"
        r"\b(skip|disabl|turn(s|ed|ing)?\s+off|bypass|remov|suppress)\w*\b" + _W +
        r"\b(confirmations?|approvals?|permission\s+(prompts?|checks?)|safety\s+(checks?|guidelines?|rules?)|"
        r"guardrails?|sandbox(ing)?)\b|"
        r"\b(most|maximally|fully)\s+permissive\b")),
    ("verification-weakening", re.compile(
        r"(?i)\b(lower|reduce|drop|relax|loosen)\b" + _W + r"\b(coverage|threshold|fail[-_ ]under|minimum)\b|"
        r"\b(coverage|threshold|fail[-_ ]under)\b" + _W + r"\bto\s+0\b|"
        r"\b(disabl|skip|remov|delet|comment(s|ed|ing)?\s+out|neuter|bypass|xfail)\w*\b" + _W +
        r"\b(failing|required|security)\s+(tests?|checks?|jobs?|scans?|steps?)\b|"
        r"\b(disabl|skip|remov|delet|neuter|bypass)\w*\b" + _W + r"\b(tests?|checks?|jobs?|scans?|steps?)\b" + _W +
        r"\b(fail(ing|s|ed)?|security|required)\b|"
        r"\breports?\s+(success|pass(ing|ed)?|green)\b" + _W + r"\bwithout\b|\[(skip\s+ci|ci\s+skip)\]|"
        r"\b(disabl|remov|delet|bypass|neuter)\w*\b" + _W +
        r"\b(ci|pipeline|pre-commit|hooks?|gates?|branch\s+protection|status\s+checks?|linters?)\b|"
        r"\bcontinue-on-error\b|\ballow_failure\b")),
    ("agent-config-persistence", re.compile(
        r"(?i)\b(append|add|write|insert|edit|modify|update|create|register|install)\w*\b" + _W +
        r"(CLAUDE\.md|AGENTS\.md|GEMINI\.md|\.cursorrules|copilot-instructions|\.claude/|\.codex/|\.gemini/|"
        r"\.vscode/settings|\.(bash|zsh)rc|\.profile\b|\.bash_profile|crontab|LaunchAgents|\bgit\s+hooks?\b|"
        r"\.git/hooks)")),
    ("destructive", re.compile(
        r"(?i)\b(delet|remov|wip|eras|purg|destroy|overwrit)\w*\b" + _W +
        r"(\.env\b|~/|\$HOME\b|\bhome\s+(directory|folder)|\bdownloads\b|\bdesktop\b|\buntracked\b|"
        r"\b(git\s+)?history\b|\ball\s+(files|branches|tags|data)\b|\beverything\b|\bother\s+branches\b)|"
        r"\bforce[- ]push\w*\b|\bpush\s+(--force|-f)\b|\breset\s+--hard\b|\bclean\s+-[a-z]*f[a-z]*d")),
    ("identity-takeover", re.compile(
        r"(?i)\bCODEOWNERS\b|\b(add|make|set|list)\w*\b" + _W + r"\b(maintainers?|owners?|required\s+reviewers?|"
        r"admins?|collaborators?)\b|\bgit\s+config\b" + _W + r"\buser\.(email|name)\b|"
        r"\b(rewrite|change|replace|amend)\w*\b" + _W + r"\b(authors?(hip)?|committers?|commit\s+identity)\b|"
        r"--reset-author\b|\bfilter-(branch|repo)\b")),
]
_PARA_BREAK = re.compile(r"\n[ \t]*\n|\n(?=[ \t]{0,3}(?:#|[-*+]\s|\d+[.)]\s))")  # blank line, heading, list item


def instruction_risks(text: str) -> list[tuple[str, int, str]]:
    """(rule, line, snippet) for each attack class a document's prose asks for, once per class and paragraph.

    Text is normalised first (NFKC folds full-width letters; HTML entities are decoded), and emphasis markers are
    stripped only at word edges, so `**IGNORE**` reads as IGNORE and `allow_failure` keeps its underscore."""
    import html
    import unicodedata
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[tuple[str, int, str]] = []
    pos = 0
    for para in _PARA_BREAK.split(text):
        at = text.find(para, pos)
        pos = at + len(para) if at >= 0 else pos
        tokens = [(m.start(), re.sub(r"^[*_~`]+|[*_~`]+$", "", m.group()))
                  for m in re.finditer(r"\S+", para)]
        starts, words, offset = [], [], 0
        for start, word in tokens:
            starts.append((offset, start))
            words.append(word)
            offset += len(word) + 1
        flat = unicodedata.normalize("NFKC", html.unescape(" ".join(words)))
        safe = redact_text(flat)
        for rule, pattern in _INSTRUCTION_RISKS:
            hit = pattern.search(flat)
            if hit is None:
                continue
            index = max(i for i, (o, _) in enumerate(starts) if o <= hit.start()) if starts else 0
            line = text.count("\n", 0, max(at, 0) + (starts[index][1] if starts else 0)) + 1
            out.append((rule, line, safe[max(0, hit.start() - 40):hit.end() + 40].strip()[:140]))
    return out
# Instructions Claude would follow: prose in a skill is never softened for these.
_NEVER_DOWNGRADE = {"remote-exec", "exfiltration", "credentials", "permission-escalation", "persistence"}


_ACTION_VERB = (r"(run|execute|use|pipe|paste|copy|follow|invoke|call|source|eval|install|download|"
                r"read|cat|open|send|upload|post|share|print|commit|curl|wget|type|enter|fetch)")
_NEGATED_ACTION = re.compile(r"(?i)\b(never|don't|do\s+not|must\s+not|avoid|refuse\s+to)\s+"
                             r"(ever\s+|blindly\s+|automatically\s+)?" + _ACTION_VERB + r"\b")
_VERB = re.compile(r"(?i)\b" + _ACTION_VERB + r"\b")


def _negated_before(line: str, start: int, strict: bool = False) -> bool:
    """A negation directly governing the match ("never run `curl … | sh`"),
    not anywhere earlier on the line ("echo never mind; curl … | sh").

    `strict` (instruction categories): the negation must be "never/do not
    <action verb>", and no second action verb may follow before the match,
    so "Do not skip this, read ~/.ssh/id_rsa" and "Do not run slow tests,
    run `curl … | sh`" are not warnings."""
    window = line[max(0, start - 60):start]
    window = re.sub(r"[*_~]{1,3}(?=\w)|(?<=\w)[*_~]{1,3}", "", window)  # `**DO NOT** use` reads as "DO NOT use"
    if strict:
        hits = list(_NEGATED_ACTION.finditer(window))
        if not hits:
            return False
        rest = window[hits[-1].end():]
        return not _VERB.search(rest) and not re.search(r"[;&|!?:]|\.\s|\bthen\b|\band\b", rest)
    neg = list(_NEGATED.finditer(window))
    return bool(neg) and not re.search(r"[;&|.!?]|\bthen\b", window[neg[-1].end():])


ASSET_EXT = {".ttf", ".otf", ".woff", ".woff2", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
             ".svg", ".pdf", ".mp3", ".wav", ".mp4"}
_HIDDEN_CHARS = re.compile("[\u200b-\u200d\u2060-\u2064\ufeff\u202a-\u202e\u2066-\u2069\u00ad\u180e"
                           "\U000e0000-\U000e007f]")  # incl. invisible Unicode tag characters
_URL = re.compile(r"https?://([A-Za-z0-9.-]+)(?::\d+)?")
_IP = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_HEX_BLOB = re.compile(r"(?:\\x[0-9a-fA-F]{2}){30,}|\b[0-9a-fA-F]{240,}\b")
_LIFECYCLE = re.compile(r'"(preinstall|install|postinstall|prepare|prepublish)"\s*:')
IMPERSONATION_TARGETS = ("anthropic", "anthropics", "claude", "vercel", "openai", "github", "microsoft")
POPULAR_PACKAGES = ("requests", "numpy", "pandas", "django", "flask", "fastapi", "react", "lodash",
                    "express", "axios", "typescript", "pytest", "boto3", "urllib3", "setuptools")


def _snippet(line: str) -> str:
    return redact_text(line.strip())[:140]


def _levenshtein1(a: str, b: str) -> bool:
    """One edit apart: substitution, insertion, deletion or a swap of two
    adjacent letters (axois/axios, reqeusts/requests)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] \
                and a[diffs[1]] == b[diffs[0]]:
            return True
        return len(diffs) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def inspect(dest: Path, files: list[dict[str, Any]], candidate: dict[str, Any],
            existing_skills: dict[str, str] | None = None,
            prior: list[Finding] | None = None) -> Report:
    from .skillcheck import parse_front_matter
    findings = list(prior or [])
    root = dest / "files"
    skill_md = next((f for f in files if f["path"] == "SKILL.md"), None)
    report = Report(candidate.get("id", ""), content_hash(files), files)
    texts: dict[str, str] = {}
    for f in files:
        data = (root / f["path"]).read_bytes()
        ext = PurePosixPath(f["path"]).suffix.lower()
        if data[:4] in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") or data[:2] == b"MZ":
            findings.append(Finding("critical", "confirmed", "binary", "executable-binary", f["path"], 0,
                                    "compiled executable in a skill (cannot be reviewed)"))
            continue
        if f["path"].endswith((".zip", ".tar", ".tar.gz", ".tgz")):
            findings.extend(_archive_findings(f["path"], data))
            report.complete = False
            continue
        if ext in ASSET_EXT and ext != ".svg" and not _magic_ok(ext, data):
            findings.append(Finding("high", "confirmed", "obfuscation", "disguised-file", f["path"], 0,
                                    f"content does not match its {ext} extension (hidden payload?)"))
            report.complete = False
            continue
        if ext in ASSET_EXT and ext != ".svg":
            for run in re.findall(rb"[\x09\x0a\x0d\x20-\x7e]{12,}", data[:MAX_FILE]):
                s = run.decode("ascii")
                if re.match(r"\s*#!\s*/(usr/)?(local/)?s?bin/", s) or any(r[4].search(s) for r in _RULES
                                                       if r[2] in _NEVER_DOWNGRADE):
                    findings.append(Finding("high", "confirmed", "obfuscation", "script-in-asset", f["path"], 0,
                                            _snippet(s)))
                    break
        if b"\x00" in data[:8192] or (ext not in TEXT_EXT and not data.isascii()):
            if ext in ASSET_EXT:
                findings.append(Finding("info", "confirmed", "binary", "asset", f["path"], 0,
                                        "binary asset (font/image/media), not executable"))
            else:
                findings.append(Finding("medium", "unknown", "binary", "binary-file", f["path"], 0,
                                        "binary file not inspected"))
                report.complete = False
            continue
        texts[f["path"]] = data.decode("utf-8", "replace")
        if f.get("executable"):
            findings.append(Finding("info", "confirmed", "code", "executable-bit", f["path"], 0,
                                    "marked executable upstream (installed non-executable)"))

    # 1. specification
    name_hint = str(candidate.get("name") or "")
    dir_name = PurePosixPath(str(candidate.get("path") or name_hint)).name or name_hint
    if skill_md is None:
        findings.append(Finding("critical", "confirmed", "spec", "missing-skill-md", "", 0,
                                "no SKILL.md at the skill root"))
    else:
        problem = front_problem(texts.get("SKILL.md", ""))
        if problem:
            findings.append(Finding("high", "confirmed", "spec", "front-matter-format", "SKILL.md", 1,
                                    problem + " (not installable)"))
        else:
            yaml_problem = strict_front_problem(sanitize_front_matter(texts.get("SKILL.md", ""))[0])
            if yaml_problem:
                findings.append(Finding("high", "confirmed", "spec", "front-matter-yaml", "SKILL.md", 1,
                                        yaml_problem + " (not installable)"))
        front, _, error = parse_front_matter(texts.get("SKILL.md", ""))
        if error or front is None:
            front = _loose_front(texts.get("SKILL.md", ""))
            if front is None:
                findings.append(Finding("high", "confirmed", "spec", "front-matter", "SKILL.md", 1,
                                        error or "unparseable front matter"))
                front = {}
        name = str(front.get("name", ""))
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
            findings.append(Finding("medium", "confirmed", "spec", "name", "SKILL.md", 1,
                                    f"name {name!r} violates the Agent Skills name rules"))
        elif dir_name and name != dir_name:
            findings.append(Finding("low", "confirmed", "spec", "name-dir-mismatch", "SKILL.md", 1,
                                    f"name {name!r} does not match directory {dir_name!r}"))
        desc = str(front.get("description", ""))
        if re.search(r"(?i)\b(any|every|all)\s+(task|request|prompt|conversation|question)s?\b|"
                     r"\balways\s+(use|activate|invoke|load)\b|\buse\s+(this\s+)?for\s+everything\b", desc):
            findings.append(Finding("medium", "confirmed", "trigger", "over-broad-trigger", "SKILL.md", 1,
                                    "description asks to be used for every task (false activations)"))
        if not desc.strip() or len(desc) > 1024:
            findings.append(Finding("medium", "confirmed", "spec", "description", "SKILL.md", 1,
                                    f"description length {len(desc)} (must be 1-1024)"))
        if len(str(front.get("compatibility", ""))) > 500:
            findings.append(Finding("low", "confirmed", "spec", "compatibility-length", "SKILL.md", 1, ""))
        for key in front_keys(texts.get("SKILL.md", "")):
            if key in ESCALATING_KEYS:
                findings.append(Finding("high", "confirmed", "permission-escalation",
                                        "allowed-tools" if key == "allowed-tools" else "front-matter-escalation",
                                        "SKILL.md", 1, f"front matter declares {key!r} (it would change "
                                        "what Claude may do; repo-ai removes it on install)"))
            elif key not in SAFE_FRONT_KEYS:
                findings.append(Finding("info", "confirmed", "spec", "removed-front-matter", "SKILL.md", 1,
                                        f"front-matter key {key!r} is removed on install"))
        report.license = _license(front, files, texts, candidate)
        comp = str(front.get("compatibility", "")).lower()
        if re.search(r"internet|network access|api key|docker|cloud account|paid", comp):
            findings.append(Finding("medium", "confirmed", "compatibility", "external-requirements",
                                    "SKILL.md", 1, f"declares requirements: {comp[:120]}"))
        lines = len(texts.get("SKILL.md", "").splitlines())
        if lines > 500:
            findings.append(Finding("low", "confirmed", "spec", "long-skill-md", "SKILL.md", 0,
                                    f"{lines} lines (spec recommends < 500)"))

    # 2./3. instructions and code, line by line
    hosts: dict[str, str] = {}
    for path, text in texts.items():
        # licence and notice files are installed with an inert skill, so their text is read as documentation
        is_doc = path.endswith((".md", ".txt")) or PurePosixPath(path).name.upper() in {"LICENSE", "COPYING", "NOTICE"}
        # one leading byte-order mark is an encoding signature, not hidden text
        # (editors and Anthropic's own docx skill write it); any other is flagged
        if _HIDDEN_CHARS.search(text[1:] if text.startswith("\ufeff") else text):
            findings.append(Finding("high", "confirmed", "obfuscation", "hidden-unicode", path, 0,
                                    "zero-width or bidirectional control characters"))
        for m in re.finditer(r"<!--(.*?)-->", text, re.S):
            if _INJECTION.search(m.group(1)) or re.search(r"(?i)\b(run|execute|send|curl)\b", m.group(1)):
                findings.append(Finding("high", "confirmed", "prompt-injection", "hidden-comment", path,
                                        text[:m.start()].count("\n") + 1, _snippet(m.group(1))))
        if _B64_BLOB.search(text) and not path.endswith((".svg", ".css")):
            findings.append(Finding("high", "suspected", "obfuscation", "encoded-blob", path, 0,
                                    "long base64-like payload"))
        if _HEX_BLOB.search(text):
            findings.append(Finding("high", "suspected", "obfuscation", "hex-blob", path, 0,
                                    "long hex/escape-encoded payload"))
        if is_doc:
            for rule, at, snip in instruction_risks(text):
                findings.append(Finding("high", "suspected", "instruction-risk", rule, path, at, snip))
        contexts = line_contexts(path, text)
        raw_lines = text.splitlines()
        code = "\n".join(ln for ln, c in zip(raw_lines, contexts, strict=False) if c == "code")
        for category, rule, evidence in code_risks(code):
            sev = "critical" if rule == "reverse-shell" else "high"
            findings.append(Finding(sev, "suspected", category, rule, path, 0, evidence))
        for lineno, line in enumerate(raw_lines, 1):
            ctx = contexts[lineno - 1] if lineno - 1 < len(contexts) else "code"
            logical = line
            nxt = lineno
            while logical.rstrip().endswith("\\") and nxt < len(raw_lines) and nxt - lineno < 20:
                logical = logical.rstrip()[:-1] + " " + raw_lines[nxt]  # shell line continuation
                nxt += 1
            for severity, kind, category, rule, pattern in _RULES:
                hit = pattern.search(logical)
                if ctx == "comment" or hit is None:
                    continue
                if ctx in ("prose", "inline") and _negated_before(logical, hit.start(),
                                                                  strict=category in _NEVER_DOWNGRADE):
                    severity, kind = "info", "suspected"  # "never run X": named as something not to do
                elif ctx == "prose" and category not in _NEVER_DOWNGRADE:
                    # described in documentation, not written as a command: one level lower
                    severity = {"critical": "high", "high": "medium", "medium": "low"}.get(severity, "info")
                    kind = "suspected"
                findings.append(Finding(severity, kind, category, rule, path, lineno, _snippet(logical)))
            if ctx == "code":
                for severity, kind, category, rule, pattern in _CODE_RULES:
                    if pattern.search(logical[:MAX_SCAN_LINE]):
                        findings.append(Finding(severity, kind, category, rule, path, lineno, _snippet(logical)))
            if (is_doc or ctx == "comment") and _INJECTION.search(line):
                findings.append(Finding("high", "confirmed", "prompt-injection", "injection-phrase",
                                        path, lineno, _snippet(line)))
            for host in _URL.findall(line):
                hosts.setdefault(host.lower(), f"{path}:{lineno}")
            for ip in _IP.findall(line):
                octets = [int(x) for x in ip]
                if not all(o <= 255 for o in octets) or ctx not in ("code", "inline"):
                    continue
                if octets == [169, 254, 169, 254]:
                    findings.append(Finding("critical", "confirmed", "network", "cloud-metadata", path,
                                            lineno, _snippet(line)))
                elif octets[0] == 10 or octets[:2] == [192, 168] or \
                        (octets[0] == 172 and 16 <= octets[1] <= 31):
                    findings.append(Finding("medium", "suspected", "network", "private-ip", path, lineno,
                                            _snippet(line)))
    # 4. dependencies and network
    for path, text in texts.items():
        name = PurePosixPath(path).name
        if name == "package.json":
            if _LIFECYCLE.search(text):
                findings.append(Finding("high", "confirmed", "lifecycle", "npm-lifecycle-script", path, 0,
                                        "install-time script (runs code on npm install)"))
            try:
                pkg = json.loads(text)
            except ValueError:
                pkg = {}
            for section in ("dependencies", "devDependencies"):
                for dep, ver in (pkg.get(section) or {}).items():
                    _dep_checks(findings, path, str(dep), str(ver))
        elif name in {"requirements.txt"} or name.startswith("requirements"):
            for lineno, line in enumerate(text.splitlines(), 1):
                dep = re.split(r"[<>=!~\[; ]", line.strip(), maxsplit=1)[0]
                if dep and not dep.startswith("#"):
                    _dep_checks(findings, path, dep, line, lineno)
        elif name == "setup.py":
            findings.append(Finding("high", "confirmed", "lifecycle", "setup-py", path, 0,
                                    "setup.py runs arbitrary code at install"))
        elif name in {"hooks.json", "settings.json", "settings.local.json"}:
            findings.append(Finding("critical", "confirmed", "lifecycle", "claude-hooks-or-settings",
                                    path, 0, "ships Claude Code hooks/settings (would run or change "
                                    "permissions outside the skill)"))
    for host, where in sorted(hosts.items()):
        if host not in {"github.com", "docs.github.com", "agentskills.io", "claude.com",
                        "code.claude.com", "docs.anthropic.com", "www.anthropic.com", "anthropic.com"}:
            findings.append(Finding("info", "confirmed", "network", "external-host", where.split(":")[0],
                                    int(where.split(":")[1]), host))
    # 5. provenance
    owner = str(candidate.get("owner", "")).lower()
    for target in IMPERSONATION_TARGETS:
        if owner != target and target in owner and owner not in {"anthropics", "vercel-labs"}:
            findings.append(Finding("high", "suspected", "provenance", "publisher-impersonation", "", 0,
                                    f"owner {owner!r} resembles {target!r} but is not the official account"))
            break
    if candidate.get("archived"):
        findings.append(Finding("medium", "confirmed", "provenance", "archived-repo", "", 0,
                                "upstream repository is archived (unmaintained)"))
    if candidate.get("fork"):
        findings.append(Finding("low", "confirmed", "provenance", "fork", "", 0, "repository is a fork"))
    created = str(candidate.get("created_at", ""))
    if created and created[:4].isdigit() and int(candidate.get("stars", 0) or 0) < 5:
        findings.append(Finding("low", "confirmed", "provenance", "low-adoption", "", 0,
                                f"{candidate.get('stars', 0)} stars, created {created[:10]}"))
    # 6. licence
    lic_class = license_class(report.license)
    if lic_class == "none":
        findings.append(Finding("high", "confirmed", "license", "no-usable-license", "", 0,
                                f"licence {report.license or 'missing'}: reuse rights unclear"))
    elif lic_class == "restricted":
        findings.append(Finding("high", "confirmed", "license", "license-restricted", "", 0,
                                f"{report.license}: non-commercial or source-available terms"))
    elif lic_class == "unrecognized":
        findings.append(Finding("high", "confirmed", "license", "license-unrecognized", "", 0,
                                f"licence {report.license!r} is not a recognised SPDX licence"))
    elif lic_class == "copyleft":
        findings.append(Finding("medium", "confirmed", "license", "copyleft", "", 0,
                                f"{report.license}: copyleft obligations"))
    # 8. conflicts
    from .skills_lab import overlap
    name = str(candidate.get("name", ""))
    desc = str(candidate.get("description", "") or (_loose_front(texts.get("SKILL.md", "")) or {})
               .get("description", ""))
    for other, text in (existing_skills or {}).items():
        if other == name:
            findings.append(Finding("high", "confirmed", "conflict", "name-collision", "", 0,
                                    f"a skill named {name!r} already exists"))
        elif overlap(desc, text) >= 0.5:
            findings.append(Finding("medium", "suspected", "conflict", "trigger-overlap", "", 0,
                                    f"description overlaps /{other}"))
    report.findings = sorted(findings, key=lambda f: (-SEVERITY_ORDER[f.severity], f.category, f.file, f.line))
    report.verdict = verdict(report)
    return report


_COMMENT_PREFIX = {".py": ("#",), ".sh": ("#",), ".bash": ("#",), ".zsh": ("#",), ".rb": ("#",),
                   ".pl": ("#",), ".yaml": ("#",), ".yml": ("#",), ".toml": ("#",), ".ps1": ("#",),
                   ".js": ("//",), ".mjs": ("//",), ".cjs": ("//",), ".ts": ("//",), ".tsx": ("//",),
                   ".jsx": ("//",), ".go": ("//",), ".java": ("//",), ".rs": ("//",), ".kt": ("//",),
                   ".css": (), ".sql": ("--",), ".html": ()}
# Only these languages have /* ... */ comments; elsewhere `/*` is ordinary text
# (a shell line `/* 2>/dev/null` must not hide the lines after it).
_BLOCK_COMMENT_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".java", ".rs", ".kt", ".css",
                      ".c", ".h", ".cpp", ".cs", ".swift"}


_MAGIC = {".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
          ".gif": (b"GIF87a", b"GIF89a"), ".webp": (b"RIFF",), ".ico": (b"\x00\x00\x01\x00",),
          ".pdf": (b"%PDF",), ".woff": (b"wOFF",), ".woff2": (b"wOF2",),
          ".ttf": (b"\x00\x01\x00\x00", b"true", b"OTTO"), ".otf": (b"OTTO", b"\x00\x01\x00\x00"),
          ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), ".wav": (b"RIFF",)}


def _magic_ok(ext: str, data: bytes) -> bool:
    if ext == ".mp4":
        return data[4:8] == b"ftyp"
    return data.startswith(_MAGIC.get(ext, (b"",)))


def line_contexts(path: str, text: str) -> list[str]:
    """`code` | `comment` | `prose` | `inline` per line. Markdown is prose,
    except fenced or indented blocks (code) and sentences quoting inline code
    (inline: full severity, but "never run `x`" still counts as a warning);
    scripts are code except comments."""
    lines = text.splitlines()
    ext = PurePosixPath(path).suffix.lower()
    if ext in {".md", ".txt", ".markdown", ".rst"}:
        out = []
        fence = None
        for line in lines:
            stripped = line.lstrip()
            marker = stripped[:3] if stripped.startswith(("```", "~~~")) else None
            if marker and (fence is None or fence == marker):
                fence = None if fence else marker
                out.append("code")
                continue
            if fence or line.startswith(("    ", "\t")):
                out.append("code")
            else:
                out.append("inline" if "`" in line else "prose")  # inline: a sentence quoting code
        return out
    prefixes = _COMMENT_PREFIX.get(ext, ("#",))
    blocks = ext in _BLOCK_COMMENT_EXT
    out = []
    in_block = False
    for line in lines:
        s = line.strip()
        if in_block:
            out.append("comment")
            if "*/" in s:
                in_block = False
            continue
        if blocks and s.startswith("/*") and "*/" not in s:
            in_block = True
            out.append("comment")
        elif s.startswith(prefixes) and not s.startswith("#!"):
            out.append("comment")
        else:
            out.append("code")
    return out


# The only front-matter keys a third-party skill keeps at install. Everything
# else (allowed-tools in any spelling or quoting, hooks, model, context,
# agent, YAML tricks such as flow maps or merge keys) is removed.
SAFE_FRONT_KEYS = ("name", "description", "license", "compatibility", "metadata", "argument-hint",
                   "disable-model-invocation")
ESCALATING_KEYS = {"allowed-tools", "hooks", "permissions", "permission-mode", "disallowed-tools"}


def _norm_key(raw: str) -> str:
    """`'Allowed_Tools'`, `? allowed-tools`, `{allowed-tools` all normalise to
    `allowed-tools` (YAML indicators and quotes stripped)."""
    raw = raw.strip().lstrip("?{[-, \t").strip().strip("'\"").strip()
    return re.sub(r"[\s_]+", "-", raw).lower()


_FRONT = re.compile(r"\A(---\r?\n)(.*?)(\r?\n---)(?=\r?\n|\Z)", re.S)


def front_problem(text: str) -> str:
    """SKILL.md must open with an exact `---` line and close with one, with no
    other delimiter-like line in between: parsers disagree about anything else,
    and a disagreement can hide keys from the firewall."""
    lines = text.split("\n")
    if lines[0].rstrip("\r") != "---":
        return "SKILL.md does not start with a plain `---` line (BOM, spaces or no front matter)"
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line == "---":
            return ""
        if line.startswith(("---", "...")) or line.rstrip() == "---":
            return f"front matter contains a delimiter-like line {line[:20]!r}"
    return "front matter has no closing `---` line"


def sanitize_front_matter(text: str) -> tuple[str, list[str]]:
    """Keep only allowlisted top-level keys (and their indented children)."""
    m = _FRONT.match(text)
    if not m:
        return text, []
    kept: list[str] = []
    removed: list[str] = []
    keep = False
    for line in m.group(2).splitlines():
        if not line.strip():
            kept.append(line)
            continue
        if line[0] in " \t" or line.startswith("-") or line.lstrip().startswith("#"):
            if keep:
                kept.append(line)
            continue
        key = _norm_key(line.split(":", 1)[0]) if ":" in line else ""
        keep = key in SAFE_FRONT_KEYS
        if keep:
            kept.append(line)
        else:
            removed.append(key or line.strip()[:40])
    if not removed:
        return text, []
    return m.group(1) + "\n".join(kept) + m.group(3) + text[m.end():], removed


_PLAIN_KEY = re.compile(r"([a-z][a-z0-9-]*):(?:[ ]+(.*))?$")
_BLOCK = re.compile(r"[|>][+-]?[0-9]?\s*(#.*)?$")


def strict_front_problem(text: str) -> str:
    """Validate *sanitized* front matter against a small YAML subset that
    every YAML parser reads the same way. Anything else could make Claude
    Code's parser see keys repo-ai did not (anchors, aliases, tags, merge
    keys, flow collections, complex keys, tab indentation, duplicates, or a
    plain value containing `: `), so it is refused rather than guessed."""
    problem = front_problem(text)
    if problem:
        return problem
    m = _FRONT.match(text)
    assert m is not None  # front_problem passed
    seen: set[str] = set()
    current = ""
    block = False
    plain = False  # a multi-line plain scalar: `description:` then indented text
    for raw in m.group(2).replace("\r\n", "\n").split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())] or raw.startswith("\t"):
            return "front matter uses tab indentation"
        if raw[0] == " ":
            if block:
                continue  # body of a block scalar: text, not YAML structure
            if plain:
                if _unsafe_scalar(raw.strip()):
                    return f"unsupported continuation of {current!r}: {raw.strip()[:40]!r}"
                continue
            if current != "metadata":
                return f"unexpected indented line under {current or 'nothing'!r}"
            child = _PLAIN_KEY.match(raw.strip())
            if not child or child.group(1) == "<<":
                return f"unsupported metadata line {raw.strip()[:40]!r}"
            if child.group(2) is not None and _unsafe_scalar(child.group(2)):
                return f"unsupported metadata value {raw.strip()[:40]!r}"
            continue
        top = _PLAIN_KEY.match(raw)
        if not top:
            return f"unsupported front-matter line {raw[:40]!r}"
        key, value = top.group(1), top.group(2)
        if key not in SAFE_FRONT_KEYS:
            return f"front-matter key {key!r} survived sanitizing"
        if key in seen:
            return f"duplicate front-matter key {key!r}"
        seen.add(key)
        current, block, plain = key, False, False
        if value is None or not value.strip():
            if key in {"description", "compatibility", "license"}:
                plain = True  # its text follows on indented lines (or it is empty)
            elif key != "metadata":
                return f"{key!r} has no value"
            continue
        if key == "metadata":
            return "metadata must be an indented mapping"
        if _BLOCK.fullmatch(value.strip()) and key in {"description", "compatibility", "license"}:
            block = True
            continue
        if _unsafe_scalar(value):
            return f"unsupported value for {key!r}: {value[:40]!r}"
    return ""


def _unsafe_scalar(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if v[0] in "\"'":
        end = v.rfind(v[0])
        if end == 0:
            return True  # unterminated quote
        rest = v[end + 1:].strip()
        return bool(rest) and not rest.startswith("#")
    if v[0] in "&*!{[|>%@`,?:" or (v[0] == "-" and not re.fullmatch(r"-?\d+(\.\d+)?", v)):
        return True  # anchors, aliases, tags, flow collections, sequences, indicators
    return ": " in v.split(" #", 1)[0]


def front_keys(text: str) -> list[str]:
    m = _FRONT.match(text)
    out = []
    for line in (m.group(2).splitlines() if m else []):
        if line.strip() and line[0] not in " \t-#":
            out.append(_norm_key(line.split(":", 1)[0] if ":" in line else line)[:40])
    return out


def _loose_front(text: str) -> dict[str, Any] | None:
    m = re.match(r"---\n(.*?)\n---", text.replace("\r\n", "\n"), re.S)
    if not m:
        return None
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            out[_norm_key(key)] = value.strip().strip('"\'')
    return out


_LIC_RANK = {"permissive": 0, "copyleft": 1, "unrecognized": 2, "none": 3, "restricted": 4}
_LIC_NONE = {"NOASSERTION", "NONE", "OTHER", "PROPRIETARY", "UNLICENSED"}
_COPYLEFT_FAMILY = re.compile(r"(?:A|L)?GPL-\d(?:\.\d+)*|EPL-\d\.\d|MPL-\d\.\d|EUPL-\d\.\d"
                              r"|CC-BY-SA-\d\.\d(?:-[A-Z]{2,3})?")
_RESTRICTED_FAMILY = re.compile(r"CC-BY(?:-[A-Z]+)*-(?:NC|ND)(?:-[A-Z]+)*-\d\.\d(?:-[A-Z]{2,3})?"
                                r"|BUSL-\d\.\d|SSPL-\d\.\d|ELASTIC-\d\.\d|COMMONS-CLAUSE"
                                r"|POLYFORM-[A-Z0-9.\-]+|CONFLUENT-COMMUNITY-\d\.\d"
                                r"|(?:LICENSEREF|DOCUMENTREF)-[A-Z0-9.\-:]+")
_GNU_SUFFIX = re.compile(r"((?:A|L)?GPL-\d(?:\.\d+)*|GFDL-\d\.\d)-(?:ONLY|OR-LATER)")
# Exceptions that only relax a licence (WITH ...); anything else is unrecognised.
_BENIGN_EXCEPTIONS = {"CLASSPATH-EXCEPTION-2.0", "LLVM-EXCEPTION", "GCC-EXCEPTION-2.0", "GCC-EXCEPTION-3.1",
                      "AUTOCONF-EXCEPTION-2.0", "AUTOCONF-EXCEPTION-3.0", "BISON-EXCEPTION-2.2",
                      "FONT-EXCEPTION-2.0"}
# Common spelled-out names, matched as whole phrases only.
_LIC_ALIASES = {"MIT LICENSE": "MIT", "MIT LICENCE": "MIT", "THE MIT LICENSE": "MIT", "EXPAT": "MIT",
                "APACHE 2.0": "APACHE-2.0", "APACHE-2": "APACHE-2.0", "APACHE LICENSE 2.0": "APACHE-2.0",
                "APACHE LICENSE VERSION 2.0": "APACHE-2.0", "APACHE LICENCE 2.0": "APACHE-2.0",
                "ISC LICENSE": "ISC", "BSD 2-CLAUSE": "BSD-2-CLAUSE", "BSD 3-CLAUSE": "BSD-3-CLAUSE",
                "BSD 2-CLAUSE LICENSE": "BSD-2-CLAUSE", "BSD 3-CLAUSE LICENSE": "BSD-3-CLAUSE"}
# Word-boundary phrases in free text (never short substrings).
_RESTRICTED_WORDS = re.compile(r"\b(?:non-?commercial|no-?derivatives|no derivative works|commons clause"
                               r"|source[- ]available|business source licen[cs]e"
                               r"|server side public licen[cs]e|elastic licen[cs]e|polyform)\b", re.I)
_NONE_WORDS = re.compile(r"\b(?:proprietary|all rights reserved|unlicensed)\b", re.I)
_LICENSE_FILE_REF = re.compile(r"\b(?:LICEN[CS]E|COPYING)(?:\.[A-Za-z]{2,4})?\b", re.I)
_LIC_TOKEN = re.compile(r"\(|\)|[A-Za-z0-9.\-:]+\+?|\S")
_UNRECOGNISED_FILE = "unrecognised LICENSE file"


class _LicenseParseError(ValueError):
    pass


def _license_id_class(word: str) -> str:
    """Class of one identifier or spelled-out phrase (already upper-cased)."""
    if word in _LIC_ALIASES:
        word = _LIC_ALIASES[word]
    word = _GNU_SUFFIX.sub(r"\1", word.rstrip("+"))
    if _RESTRICTED_FAMILY.fullmatch(word) or _RESTRICTED_WORDS.search(word):
        return "restricted"
    if word in PERMISSIVE:
        return "permissive"
    if word in COPYLEFT or _COPYLEFT_FAMILY.fullmatch(word):
        return "copyleft"
    if word in _LIC_NONE or _NONE_WORDS.search(word):
        return "none"
    return "unrecognized"


def _parse_license(expr: str) -> tuple[str, str]:
    """(class, canonical upper-case expression) of an SPDX licence expression.

    Grammar: or := and (OR and)*; and := with ((AND | '+') with)*;
    with := term (WITH exception)?; term := '(' or ')' | word+.
    AND takes the most restrictive operand, OR the least restrictive one;
    a run of plain words is one spelled-out name (`Commons Clause`).
    Raises _LicenseParseError on anything else (stray punctuation, ...).
    """
    toks = [t.upper() for t in _LIC_TOKEN.findall(expr)]
    pos = 0

    def peek() -> str:
        return toks[pos] if pos < len(toks) else ""

    def words() -> str:
        nonlocal pos
        out = []
        while peek() and peek() not in {"(", ")", "+", "AND", "OR", "WITH"}:
            if not re.fullmatch(r"[A-Z0-9.\-:]+\+?", peek()):
                raise _LicenseParseError(peek())
            out.append(peek())
            pos += 1
        if not out:
            raise _LicenseParseError(peek() or "end")
        return " ".join(out)

    def term() -> tuple[str, str]:
        nonlocal pos
        if peek() == "(":
            pos += 1
            cls, text = or_expr()
            if peek() != ")":
                raise _LicenseParseError("unbalanced")
            pos += 1
            return cls, f"({text})"
        name = words()
        canonical = _LIC_ALIASES.get(name, name)
        return _license_id_class(name), canonical

    def with_expr() -> tuple[str, str]:
        nonlocal pos
        cls, text = term()
        if peek() == "WITH":
            pos += 1
            exc = words()
            if _license_id_class(exc) == "restricted":
                cls = "restricted"
            elif exc not in _BENIGN_EXCEPTIONS:
                cls = max(cls, "unrecognized", key=_LIC_RANK.__getitem__)
            text = f"{text} WITH {exc}"
        return cls, text

    def and_expr() -> tuple[str, str]:
        nonlocal pos
        cls, text = with_expr()
        while peek() in {"AND", "+"}:
            op = "AND" if peek() == "AND" else "+"
            pos += 1
            c2, t2 = with_expr()
            cls, text = max(cls, c2, key=_LIC_RANK.__getitem__), f"{text} {op} {t2}"
        return cls, text

    def or_expr() -> tuple[str, str]:
        nonlocal pos
        cls, text = and_expr()
        while peek() == "OR":
            pos += 1
            c2, t2 = and_expr()
            cls, text = min(cls, c2, key=_LIC_RANK.__getitem__), f"{text} OR {t2}"
        return cls, text

    if not toks:
        return "none", ""
    cls, text = or_expr()
    if pos != len(toks):
        raise _LicenseParseError(peek())
    return cls, text


def license_class(expr: str) -> str:
    """`permissive` | `copyleft` | `restricted` | `none` | `unrecognized`.

    Permissive only when the whole expression is (an OR needs one permissive
    option). Free text that is not an SPDX expression is never permissive:
    it is `restricted` or `none` if it says so in whole words, otherwise
    `unrecognized`.
    """
    text = re.sub(r"\s+", " ", (expr or "").strip())
    alias = _LIC_ALIASES.get(text.upper().replace(",", "").rstrip("."))
    if alias:
        return _license_id_class(alias)
    try:
        cls, _ = _parse_license(text)
    except _LicenseParseError:
        cls = "unrecognized"
    if cls == "unrecognized":
        if _RESTRICTED_WORDS.search(text):
            return "restricted"
        if _NONE_WORDS.search(text):
            return "none"
    return cls


def _license_display(declared: str) -> str:
    """Canonical form of a recognised expression; otherwise the text, cut
    short with a marker that keeps a cut expression unparseable."""
    text = re.sub(r"\s+", " ", declared.strip())
    alias = _LIC_ALIASES.get(text.upper().replace(",", "").rstrip("."))
    if alias:
        return alias
    try:
        cls, canonical = _parse_license(text)
    except _LicenseParseError:
        cls, canonical = "unrecognized", ""
    if cls != "unrecognized" and canonical and len(canonical) <= 200:
        return canonical
    return text if len(text) <= 200 else text[:200] + "\u2026"


def _license(front: dict[str, Any], files: list[dict[str, Any]], texts: dict[str, str],
             candidate: dict[str, Any]) -> str:
    raw = front.get("license")
    declared = "" if raw is None else str(raw).strip()
    license_files = [f for f in files
                     if PurePosixPath(f["path"]).name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))]
    if declared:
        # "See LICENSE.txt" and similar: read the file, unless the text
        # itself already says the terms are restricted or proprietary.
        if (license_class(declared) == "unrecognized" and _LICENSE_FILE_REF.search(declared)):
            for f in license_files:
                detected = _detect_license(texts.get(f["path"], ""))
                if detected:
                    return detected
        return _license_display(declared)
    for f in license_files:
        detected = _detect_license(texts.get(f["path"], ""))
        if detected:
            return detected
    if license_files:
        return _UNRECOGNISED_FILE
    return str(candidate.get("repo_license") or "")


# Licence-text signatures: whole phrases on word boundaries, whitespace
# collapsed. Restrictive riders are checked first, so "MIT + Commons
# Clause" text is never read as MIT.
_LICENSE_TEXT_SIGNATURES: tuple[tuple[str, str], ...] = (
    (r"\bcommons clause\b", "COMMONS-CLAUSE"),
    (r"\bbusiness source licen[cs]e\b", "BUSL-1.1"),
    (r"\bserver side public licen[cs]e\b", "SSPL-1.0"),
    (r"\belastic licen[cs]e\b", "ELASTIC-2.0"),
    (r"\bpolyform\b", "POLYFORM-NONCOMMERCIAL-1.0.0"),
    (r"\bnon-?commercial\b", "LICENSEREF-NONCOMMERCIAL"),
    (r"\bno-?derivatives\b|\bno derivative works\b", "LICENSEREF-NODERIVATIVES"),
    (r"\bgnu affero general public license\b", "AGPL-3.0"),
    (r"\bgnu lesser general public license\b.*\bversion 3\b", "LGPL-3.0"),
    (r"\bgnu (?:lesser|library) general public license\b", "LGPL-2.1"),
    (r"\bgnu general public license\b.*\bversion 3\b", "GPL-3.0"),
    (r"\bgnu general public license\b", "GPL-2.0"),
    (r"\beuropean union public licen[cs]e\b", "EUPL-1.2"),
    (r"\beclipse public license\b.*\bversion 2\.0\b|\beclipse public license (?:- )?v ?2\.0\b", "EPL-2.0"),
    (r"\beclipse public license\b", "EPL-1.0"),
    (r"\bmozilla public license,? version 2\.0\b", "MPL-2.0"),
    (r"\bmozilla public license\b", "MPL-1.1"),
    (r"\bcreative commons attribution-sharealike\b", "CC-BY-SA-4.0"),
    (r"\bcc0 1\.0 universal\b", "CC0-1.0"),
    (r"\bcreative commons attribution 4\.0 international\b", "CC-BY-4.0"),
    (r"\bmit license\b|\bpermission is hereby granted, free of charge\b", "MIT"),
    (r"\bapache license\b.*\bversion 2\.0\b", "APACHE-2.0"),
    (r"\bredistribution and use in source and binary forms\b.*\bneither the name\b", "BSD-3-CLAUSE"),
    (r"\bredistribution and use in source and binary forms\b", "BSD-2-CLAUSE"),
    (r"\bpermission to use, copy, modify, and(?:/or)? distribute this software for any purpose "
     r"with or without fee is hereby granted\b", "ISC"),
    (r"\bthis is free and unencumbered software released into the public domain\b", "UNLICENSE"),
    (r"\bboost software license\b", "BSL-1.0"),
    (r"\bproprietary\b|\ball rights reserved\b", "PROPRIETARY"),
)


def _detect_license(text: str) -> str:
    t = re.sub(r"\s+", " ", text.lower())
    for pattern, spdx in _LICENSE_TEXT_SIGNATURES:
        if re.search(pattern, t):
            return spdx
    return ""


def _dep_checks(findings: list[Finding], path: str, dep: str, spec: str, line: int = 0) -> None:
    low = dep.lower()
    if re.search(r"(git\+|https?://|file:|github:)", spec):
        findings.append(Finding("high", "confirmed", "dependencies", "url-dependency", path, line,
                                f"{dep} from {spec[:80]}"))
    for popular in POPULAR_PACKAGES:
        if low != popular and _levenshtein1(low, popular):
            findings.append(Finding("high", "suspected", "dependencies", "typosquat", path, line,
                                    f"{dep!r} is one edit away from {popular!r}"))
    findings.append(Finding("info", "confirmed", "dependencies", "dependency", path, line, dep))


def verdict(report: Report) -> str:
    if any(f.severity == "critical" for f in report.findings):
        return "blocked"
    if any(f.severity == "high" for f in report.findings) or not report.complete:
        return "review"
    return "eligible"


def render(report: Report, limit: int = 25) -> str:
    counts = report.counts()
    lines = [f"firewall: {report.candidate_id}",
             f"  verdict: {report.verdict.upper()}  licence: {report.license or 'missing'}  "
             f"files: {len(report.files)}  content: sha256:{report.content_hash[:16]}",
             "  findings: " + (", ".join(f"{n} {s}" for s, n in sorted(
                 counts.items(), key=lambda kv: -SEVERITY_ORDER[kv[0]])) or "none")]
    for f in [x for x in report.findings if x.severity != "info"][:limit]:
        where = f"{f.file}:{f.line}" if f.line else f.file
        lines.append(f"  [{f.severity}/{f.kind}] {f.category}/{f.rule} {where} {f.evidence}")
    if report.verdict == "eligible":
        lines.append("  note: no known problem found; no scanner can prove a skill safe")
    return "\n".join(lines)
