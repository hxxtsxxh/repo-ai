"""Capability bundles: what a vetted capability *is*, and how it reaches a host, reversibly.

Five object kinds are modelled apart, because they carry very different power:

| kind               | what runs                                   | how repo-ai treats it                       |
|--------------------|---------------------------------------------|---------------------------------------------|
| `skill`            | nothing by itself: instructions (+ files)   | installable; inert only if SKILL.md-only    |
| `plugin`           | hooks, bin/, monitors, settings, LSP        | inspected (`pluginvet`), never installed    |
| `mcp_server`       | a spawned process or a remote endpoint      | never installed; repo-ai writes no MCP config |
| `provider_adapter` | a coding-agent CLI repo-ai drives           | built in; per-run consent, never from content |
| `static_tool`      | a local binary repo-ai runs (ruff adapter)  | per-binary approval (`capabilities approve`) |

A directory with SKILL.md *and* scripts, executables, hooks or an MCP manifest
is not inert. `assess` decides inertness structurally (file set, modes, front
matter, hidden characters, commands, URLs, accounts) on top of the firewall:
the firewall's `eligible` is necessary and never sufficient.

A `CapabilityBundle` is the exact bytes of one vetted skill, pinned to the
content hash that was reviewed. Host translators turn it into files for one
agent host, inside that host's project skills directory only:

- every SKILL.md carries a repo-ai ownership marker (`kind=capability-bundle`);
- front matter is reduced to the firewall's allowlist: no permission is ever added;
- files are written non-executable;
- an existing file repo-ai does not own is a conflict: the install is refused,
  nothing is overwritten;
- a machine-local manifest records, per path, the bytes that were there before
  the first install and the hash of what repo-ai wrote, so uninstall puts back
  exactly what was there (and keeps any file you edited since).

Host support is labelled honestly. `claude-code` is the target repo-ai's skill
portfolio already installs to. Every other host is `CAPABILITY_EXPORT_ONLY`:
the path comes from local inspection of that CLI (bundled docs or binary
strings) or from repo-ai's existing host notes, and repo-ai has not observed
the host load a skill from it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import firewall

SCHEMA_MANIFEST = "repo-ai.capability-bundle-manifest/1"
SCHEMA_ASSESSMENT = "repo-ai.capability-assessment/1"
MARKER_KIND = "capability-bundle"

KINDS = ("skill", "plugin", "mcp_server", "provider_adapter", "static_tool")
KIND_RULES = {
    "skill": "installable into a host skills directory; SAFE_AUTO only when inert (SKILL.md-only)",
    "plugin": "never installed or enabled by repo-ai; inspected only (experimental pluginvet)",
    "mcp_server": "never installed; repo-ai writes no MCP configuration",
    "provider_adapter": "built into repo-ai; each live run needs your explicit consent and budget",
    "static_tool": "a local binary; runs only after you approve its exact hash in a terminal",
}

INERT_MAX_BYTES = 32_768        # SKILL.md size cap for SAFE_AUTO
INERT_MAX_LINE = 2_000          # a longer line can hide content past the visible edge
LICENSE_FILES = frozenset({"LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md", "NOTICE",
                           "NOTICE.md", "NOTICE.txt"})
INERT_FRONT_KEYS = frozenset({"name", "description", "license", "metadata", "argument-hint",
                              "disable-model-invocation"})

_PLUGIN_PATHS = re.compile(r"^(\.claude-plugin/|hooks/|monitors/|bin/|\.lsp\.json$|settings(\.local)?\.json$|"
                           r"\.claude/settings)")
_MCP_PATHS = re.compile(r"(^|/)(\.mcp\.json|mcp\.json|smithery\.yaml)$")
_MCP_DEPS = re.compile(r"@modelcontextprotocol/|\bfastmcp\b|\bmcp\[cli\]|[\"']mcp[\"']\s*[:,>=~]|^\s*mcp\s*[>=~]",
                       re.M)
_SCRIPT_EXT = {".sh", ".bash", ".zsh", ".fish", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rb", ".pl",
               ".php", ".ps1", ".psm1", ".bat", ".cmd", ".exe", ".dll", ".so", ".dylib", ".jar", ".wasm",
               ".lua", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".applescript", ".scpt"}
_BINARY_MAGIC = (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"MZ", b"\x00asm",
                 b"PK\x03\x04")

# Structural (not pattern-scanner) signals in SKILL.md text that make it more than inert instructions.
_HIDDEN = re.compile("[​-‏ -‮⁠-⁤⁦-⁩﻿­᠎͏"
                     "\U000e0000-\U000e007f]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_COMMENT = re.compile(r"<!--")
_URL = re.compile(r"(?i)\b(?:https?|ftp|file|ssh|git|wss?)://|\bwww\.[a-z0-9-]+\.|"
                  # a bare host with a path or port ("raw.githubusercontent.com/acme/x", "gist.github.com/a")
                  r"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?::\d{2,5})?/[\w~%.-]|"
                  # an agent's own fetch/browse tools, and in-code fetches
                  r"\bweb\s?fetch\b|\bweb\s?search\b|\bfetch\s+tool\b|\bbrowser\s+tool\b|\bbrowse\s+to\b|"
                  r"\burlopen\b|\brequests\.(?:get|post|put)\b|\bfetch\s*\(|\bhttpx\.|\bXMLHttpRequest\b|"
                  r"\bsocket\.(?:socket|create_connection)\b")
# Markdown that never renders: link-reference "comments" such as `[//]: # (hidden text)`
_MD_COMMENT = re.compile(r"(?m)^[ \t]{0,3}\[[^\]\n]*\]:[ \t]*(?:#|<>)")
# Licence URLs that standard licence texts carry; anything else in a licence file is a surface
_LICENSE_HOSTS = re.compile(r"(?i)\b(?:https?://)?(?:www\.)?(?:apache\.org|opensource\.org|gnu\.org|fsf\.org|"
                            r"mozilla\.org|creativecommons\.org|spdx\.org|unlicense\.org)(?:/[^\s)>\]]*)?")
_NETWORK_CMD = re.compile(r"(?i)(?<![\w-])(curl|wget|invoke-webrequest|iwr|nc|ncat|netcat|telnet|ssh|scp|sftp|rsync|"
                          r"ftp|git\s+(clone|pull|fetch|push|submodule)|pip3?\s+install|uv\s+(add|pip\s+install)|"
                          r"npm\s+(i|install|exec)|pnpm\s+(add|dlx)|yarn\s+(add|dlx)|npx|bunx|uvx|pipx|"
                          r"docker\s+(run|pull)|podman\s+(run|pull)|gem\s+install|cargo\s+install|"
                          r"go\s+install|brew\s+install|apt(-get)?\s+install)(?![\w-])")
_MCP_TEXT = re.compile(r"(?i)\bmcp__|\.mcp\.json|\bmcp\s+servers?\b|\bclaude\s+mcp\s+add\b|\bmcpServers\b")
_ACCOUNT = re.compile(r"(?i)\$\{?[A-Z0-9_]*(TOKEN|SECRET|API_?KEY|PASSWORD|PASSWD|CREDENTIALS?)\b|"
                      r"\bapi[ _-]?keys?\b|\baccess[ _-]?tokens?\b|\boauth\b|\blog\s?in\s+(to|with)\b|"
                      r"\bsign\s+in\s+(to|with)\b|\bpersonal access token\b")
_PERMISSION = re.compile(r"(?i)\ballowed[-_ ]tools\b|\bsettings(\.local)?\.json\b|\bbypassPermissions\b|"
                         r"--dangerously|\bpermission[-_ ]?mode\b|\bdefaultMode\b|\bdisallowed[-_ ]tools\b|"
                         r"\bhooks?\s*:|\bauto[- ]?approve|\bsudo\b|\bchmod\b|\bchown\b")
_HIDDEN_CMD = re.compile(r"(?i)\bbase64\s+(-d|--decode)\b|\bfrom_?base64\b|\batob\s*\(|\beval\b|\bexec\s*\(|"
                         r"\bsource\s+<\(|\$\(|`[^`\n]*\$\(")
_FIREWALL_INFO_BLOCKERS = {"executable-bit", "external-host", "removed-front-matter", "dependency", "asset",
                           "binary-file"}
_FIREWALL_LOW_BLOCKERS = {"long-skill-md", "compatibility-length", "name-dir-mismatch"}


class BundleError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
def classify(files: list[dict[str, Any]], read: Any = None) -> dict[str, Any]:
    """Object kind of a vetted directory, plus every executable or configuring component found.

    `read(path) -> bytes` gives a file's bytes (for manifests and magic numbers)."""
    paths = [str(f.get("path", "")) for f in files]
    components: list[str] = []
    for f in files:
        p = str(f.get("path", ""))
        ext = PurePosixPath(p).suffix.lower()
        if _PLUGIN_PATHS.search(p):
            components.append(f"plugin-component:{p}")
        if _MCP_PATHS.search(p):
            components.append(f"mcp-manifest:{p}")
        if ext in _SCRIPT_EXT:
            components.append(f"script:{p}")
        if f.get("executable"):
            components.append(f"executable-bit:{p}")
        data = b""
        if read is not None:
            try:
                data = read(p)
            except OSError:
                data = b""
        if data[:4] in _BINARY_MAGIC or data[:2] == b"MZ":
            components.append(f"binary:{p}")
        elif data.startswith(b"#!"):
            components.append(f"shebang:{p}")
        if PurePosixPath(p).name in {"package.json", "pyproject.toml", "requirements.txt", "setup.py",
                                     "setup.cfg", "Cargo.toml", "go.mod", "Gemfile"}:
            components.append(f"package-manifest:{p}")
            if data and _MCP_DEPS.search(data.decode("utf-8", errors="replace")):
                components.append(f"mcp-dependency:{p}")
    if any(c.startswith("plugin-component:") for c in components):
        kind = "plugin"
    elif any(c.startswith(("mcp-manifest:", "mcp-dependency:")) for c in components):
        kind = "mcp_server"
    elif "SKILL.md" in paths:
        kind = "skill"
    else:
        kind = "unknown"
    return {"kind": kind, "components": sorted(set(components))}


def registry_objects() -> list[dict[str, Any]]:
    """The non-content kinds repo-ai knows about: provider adapters and static tools."""
    from .capabilities import load_manifest as load_capabilities
    from .providers.discovery import PROVIDERS
    out = [{"id": f"provider.{p}", "kind": "provider_adapter", "approval": "per-capability",
            "rule": KIND_RULES["provider_adapter"]} for p in PROVIDERS]
    try:
        records = list(load_capabilities().get("capabilities") or [])
    except Exception:  # noqa: BLE001 - the registry is optional for this listing
        records = []
    for rec in records:
        if rec.get("kind") == "adapter":
            out.append({"id": rec.get("id"), "kind": "static_tool", "approval": "per-capability",
                        "rule": KIND_RULES["static_tool"]})
    return out


# --------------------------------------------------------------------------
# inertness
# --------------------------------------------------------------------------
def _text_surfaces(text: str) -> list[str]:
    out: list[str] = []
    if _HIDDEN.search(text):
        out.append("hidden-unicode")
    if any(ord(ch) > 127 and ch.isalpha() for ch in text):  # homoglyphs and full-width letters defeat text checks
        out.append("non-ascii-letters")
    import unicodedata
    if any(ord(ch) > 127 and (unicodedata.category(ch)[0] == "M" or unicodedata.category(ch) in {"Cf", "Co", "Cn"})
           for ch in text):  # combining marks and variation selectors split words without being letters
        out.append("non-ascii-marks")
    if _CONTROL.search(text):
        out.append("control-characters")
    if _HTML_COMMENT.search(text):
        out.append("hidden-html-comment")
    if _MD_COMMENT.search(text):
        out.append("hidden-markdown-comment")
    if any(len(line) > INERT_MAX_LINE for line in text.splitlines()):
        out.append("overlong-line")
    if _URL.search(text):
        out.append("network-reference")
    if _NETWORK_CMD.search(text):
        out.append("network-execution")
    if _MCP_TEXT.search(text):
        out.append("mcp-reference")
    if _ACCOUNT.search(text):
        out.append("external-account")
    if _PERMISSION.search(text):
        out.append("permission-change")
    if _HIDDEN_CMD.search(text):
        out.append("hidden-command")
    from .skillcheck import RISKY_RE
    if RISKY_RE.search(text):
        out.append("risky-command")
    return out


def front_name(text: str) -> str:
    """The SKILL.md front-matter `name`, as the firewall reads it ('' when absent)."""
    front = firewall._loose_front(text or "") or {}
    return str(front.get("name", "")).strip()


def path_key(rel: str) -> str:
    """How a case-insensitive, normalising filesystem (APFS, NTFS) sees a path."""
    import unicodedata
    return "/".join(unicodedata.normalize("NFC", part).rstrip(". ").casefold() for part in rel.split("/"))


def path_collisions(paths: list[str]) -> list[str]:
    """Paths that land on the same file under case folding or trailing dots/spaces,
    a trailing dot or space anywhere, and any file other than SKILL.md that folds to skill.md."""
    out: list[str] = []
    seen: dict[str, str] = {}
    for rel in sorted(paths):
        key = path_key(rel)
        if any(part != part.rstrip(". ") for part in rel.split("/")):
            out.append(f"{rel} (trailing dot or space)")
        if key in seen:
            out.append(f"{rel} collides with {seen[key]}")
        seen.setdefault(key, rel)
        if rel != "SKILL.md" and key == "skill.md":
            out.append(f"{rel} folds to SKILL.md")
    return out


def _license_surfaces(rel: str, text: str) -> list[str]:
    """A licence file ships with the skill, so its text gets the same checks as SKILL.md,
    minus the licence vocabulary ("publish", "distribute") and the standard licence URLs."""
    cleaned = _LICENSE_HOSTS.sub(" ", text)
    out = [s for s in _text_surfaces(cleaned) if s != "risky-command"]
    if "`" in text:
        out.append("code-span")
    return [f"{s}:{rel}" for s in out]


def assess(dest: Path, report: firewall.Report, name: str | None = None) -> dict[str, Any]:
    """Kind, installability and inertness of one quarantined candidate.

    `inert` is true only when every structural check passes *and* the firewall
    found nothing that matters. It is the only thing SAFE_AUTO may act on.
    `name` is the install name; a front-matter name that differs is a surface."""
    root = dest / "files"

    def read(rel: str) -> bytes:
        firewall.safe_rel(rel)
        return (root / rel).read_bytes()

    cls = classify(report.files, read)
    kind = cls["kind"]
    reasons: list[str] = []
    surfaces: list[str] = list(cls["components"])
    installable = kind == "skill"
    if kind != "skill":
        reasons.append(f"object kind {kind}: {KIND_RULES.get(kind, 'not a skill directory')}")
    if report.verdict == "blocked":
        installable = False
        reasons.append("firewall verdict blocked")
    if any(f.rule in firewall.LICENSE_GATE_RULES for f in report.findings):
        installable = False
        reasons.append("no usable, recognised, unrestricted licence")
    skill_bytes = b""
    try:
        skill_bytes = read("SKILL.md") if any(f["path"] == "SKILL.md" for f in report.files) else b""
    except (OSError, firewall.QuarantineError):
        skill_bytes = b""
    try:
        skill_text = skill_bytes.decode("utf-8")
    except UnicodeDecodeError:
        skill_text = ""
        surfaces.append("non-utf8-skill-md")
    if kind == "skill" and firewall.front_problem(skill_text):
        installable = False
        reasons.append("SKILL.md front matter is malformed")

    # structural checks for SAFE_AUTO
    extra = sorted(f["path"] for f in report.files if f["path"] != "SKILL.md" and f["path"] not in LICENSE_FILES)
    if extra:
        surfaces.append("files-beyond-skill-md:" + ",".join(extra[:6]) + ("…" if len(extra) > 6 else ""))
    if len(skill_bytes) > INERT_MAX_BYTES:
        surfaces.append(f"oversized-skill-md:{len(skill_bytes)}")
    keys = set(firewall.front_keys(skill_text))
    if keys - INERT_FRONT_KEYS:
        surfaces.append("front-matter-keys:" + ",".join(sorted(keys - INERT_FRONT_KEYS))[:120])
    if firewall.strict_front_problem(skill_text):
        surfaces.append("front-matter-not-strict")
    declared = front_name(skill_text)
    if name is not None and declared != name:
        surfaces.append(f"name-mismatch:{declared[:40]}")
    for problem in path_collisions([str(f["path"]) for f in report.files]):
        installable = False
        reasons.append(f"path collision: {problem}")
        surfaces.append("path-collision")
    for f in report.files:  # licence files are copied into the host directory: their text is checked too
        if f["path"] in LICENSE_FILES:
            try:
                lic = read(f["path"]).decode("utf-8")
            except (OSError, UnicodeDecodeError, firewall.QuarantineError):
                surfaces.append(f"non-utf8:{f['path']}")
                continue
            surfaces.extend(_license_surfaces(f["path"], lic))
    surfaces.extend(_text_surfaces(skill_text))

    # the firewall: necessary, never sufficient
    if report.verdict != "eligible":
        surfaces.append(f"firewall-verdict:{report.verdict}")
    if not report.complete:
        surfaces.append("firewall-incomplete")
    for fnd in report.findings:
        if fnd.rule == "external-host" and fnd.file in LICENSE_FILES and _LICENSE_HOSTS.search(fnd.evidence or ""):
            continue  # a standard licence's own URL (apache.org, opensource.org, ...)
        sev = firewall.SEVERITY_ORDER.get(fnd.severity, 0)
        if sev >= firewall.SEVERITY_ORDER["medium"] or (fnd.severity == "low" and fnd.rule in
                                                        _FIREWALL_LOW_BLOCKERS) \
                or (fnd.severity == "info" and fnd.rule in _FIREWALL_INFO_BLOCKERS):
            surfaces.append(f"finding:{fnd.category}/{fnd.rule}")
    surfaces = sorted(set(surfaces))
    inert = installable and not surfaces
    return {"schema": SCHEMA_ASSESSMENT, "kind": kind, "installable": installable, "inert": inert,
            "requires_approval": not inert, "surfaces": surfaces, "reasons": reasons,
            "content_hash": report.content_hash, "firewall_verdict": report.verdict,
            "firewall_complete": report.complete,
            "note": "a firewall verdict of eligible is not a safety claim; inert is a structural property"}


# --------------------------------------------------------------------------
# bundles
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BundleFile:
    path: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(slots=True)
class CapabilityBundle:
    name: str
    kind: str
    content_hash: str                 # the reviewed upstream content hash (the pin)
    files: tuple[BundleFile, ...]     # upstream bytes, verified against the pin
    source: dict[str, Any] = field(default_factory=dict)
    assessment: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "content_hash": self.content_hash,
                "files": [{"path": f.path, "sha256": f.sha256, "size": len(f.data)} for f in self.files],
                "source": self.source, "assessment": self.assessment}


_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def check_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64:
        raise BundleError(f"invalid skill name {name!r}")


def from_files(name: str, root: Path, files: list[dict[str, Any]], expected_hash: str, *,
               source: dict[str, Any] | None = None, assessment: dict[str, Any] | None = None,
               kind: str = "skill") -> CapabilityBundle:
    """Read `files` from `root` and verify every byte against the reviewed hash.

    A file whose bytes differ from the vetted listing, or a listing whose hash
    differs from `expected_hash`, is refused: content may not change between
    vet and install."""
    check_name(name)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""):
        raise BundleError("the reviewed content hash must be a full sha256 hex digest")
    if firewall.content_hash(files) != expected_hash:
        raise BundleError(f"content changed since it was reviewed ({expected_hash[:16]} → "
                          f"{firewall.content_hash(files)[:16]}); vet it again")
    out: list[BundleFile] = []
    for f in sorted(files, key=lambda x: x["path"]):
        rel = firewall.safe_rel(str(f["path"]))
        path = root / rel
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            raise BundleError(f"{rel} is not a regular file; refusing")
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(firewall.MAX_FILE + 1)
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise BundleError(f"{rel} changed after it was vetted (hash mismatch); refusing")
        out.append(BundleFile(rel.as_posix(), data))
    return CapabilityBundle(name, kind, expected_hash, tuple(out), dict(source or {}), dict(assessment or {}))


def from_quarantine(name: str, dest: Path, report: firewall.Report, expected_hash: str,
                    source: dict[str, Any] | None = None) -> CapabilityBundle:
    assessment = assess(dest, report, name)
    if report.content_hash != expected_hash:
        raise BundleError(f"content changed since it was reviewed ({expected_hash[:16]} → "
                          f"{report.content_hash[:16]}); vet it again")
    return from_files(name, dest / "files", report.files, expected_hash, source=source,
                      assessment=assessment, kind=assessment["kind"])


# --------------------------------------------------------------------------
# host translators
# --------------------------------------------------------------------------
INSTALL_TARGET = "INSTALL_TARGET"
EXPORT_ONLY = "CAPABILITY_EXPORT_ONLY"


@dataclass(frozen=True, slots=True)
class HostTranslator:
    host: str
    skills_dir: str
    support: str
    evidence: str
    observed: str = ""  # a dated observation of the host loading a repo-ai-installed skill; "" = never observed

    def target_dir(self, name: str) -> PurePosixPath:
        check_name(name)
        return PurePosixPath(self.skills_dir) / name

    def to_json(self) -> dict[str, Any]:
        return {"host": self.host, "skills_dir": self.skills_dir, "support": self.support,
                "runtime_observed": bool(self.observed), "evidence": self.evidence,
                **({"observed": self.observed} if self.observed else {})}


HOSTS: dict[str, HostTranslator] = {t.host: t for t in (
    HostTranslator("claude-code", ".claude/skills", INSTALL_TARGET,
                   "the project skills directory repo-ai's portfolio has always installed to",
                   "2026-10-30, Claude Code 2.1.314: listed in the session's skills and invoked by the model "
                   "(docs/engineering/evidence/SKILL-HOSTS-2026-10-30.md)"),
    HostTranslator("codex", ".agents/skills", EXPORT_ONLY,
                   "codex-cli 0.165.0 binary strings name `.agents/skills` (a repository skills root) and "
                   "`$CODEX_HOME/skills`; not observed loading a skill"),
    HostTranslator("gemini-cli", ".gemini/skills", EXPORT_ONLY,
                   "gemini-cli 0.65.0 bundled docs: workspace skills in `.gemini/skills/` or the "
                   "`.agents/skills/` alias, which takes precedence; not observed loading a skill"),
    HostTranslator("antigravity", ".agents/skills", EXPORT_ONLY,
                   "agy binary strings: `{workspace}/.agents/skills/{skill_name}/SKILL.md`; not observed "
                   "loading a skill"),
    HostTranslator("opencode", ".agents/skills", INSTALL_TARGET,
                   "OpenCode reads repository skills from `.agents/skills` by default (not when "
                   "OPENCODE_DISABLE_CLAUDE_CODE is set)",
                   "2026-10-30, OpenCode 2.2.1: its skill tool returned the installed bytes on request "
                   "(docs/engineering/evidence/SKILL-HOSTS-2026-10-30.md)"),
    HostTranslator("ibm-bob", ".bob/skills", EXPORT_ONLY,
                   "repo-ai's Bob notes (bobsetup.py, from IBM's published docs): `.bob/skills/<name>/SKILL.md`; "
                   "not observed loading a skill"),
)}
DEFAULT_HOSTS = ("claude-code",)


def parse_hosts(spec: str | None) -> tuple[str, ...]:
    if not spec:
        return DEFAULT_HOSTS
    hosts = tuple(dict.fromkeys(h.strip() for h in spec.split(",") if h.strip()))
    unknown = [h for h in hosts if h not in HOSTS]
    if unknown or not hosts:
        raise BundleError(f"unknown host {', '.join(unknown) or spec!r}; choose from {', '.join(HOSTS)}")
    return hosts


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def ownership_marker(bundle_hash: str, body_for_sha: str) -> str:
    """No host in the marker: hosts that share a directory (`.agents/skills`) get identical bytes."""
    from .fsutil import short_hash
    return f"<!-- repo-ai:managed kind={MARKER_KIND} bundle={bundle_hash[:16]} sha={short_hash(body_for_sha)} -->"


def render_skill_md(text: str, bundle_hash: str, host: str) -> tuple[str, list[str]]:
    """Sanitized SKILL.md with a repo-ai ownership marker after the front matter.

    The marker's sha follows `fsutil.managed_state`, so a hand edit turns the file
    into the user's. Front matter keeps only the firewall's allowlist."""
    sanitized, removed = firewall.sanitize_front_matter(text)
    leftover = set(firewall.front_keys(sanitized)) - set(firewall.SAFE_FRONT_KEYS)
    strict = firewall.strict_front_problem(sanitized)
    if leftover or strict or firewall.front_problem(sanitized):
        raise BundleError(f"front matter did not sanitize cleanly ({strict or sorted(leftover)}); refusing")
    m = firewall._FRONT.match(sanitized)
    if not m:  # pragma: no cover - front_problem above already refuses this
        raise BundleError("SKILL.md has no front matter")
    eol = _eol(sanitized)
    cut = m.end()
    rest = sanitized[cut:]
    if rest.startswith("\r\n"):
        head, tail = sanitized[:cut + 2], rest[2:]
    elif rest.startswith("\n"):
        head, tail = sanitized[:cut + 1], rest[1:]
    else:
        head, tail = sanitized[:cut] + eol, rest
    lf_body = (head + tail).replace("\r\n", "\n")
    marker = ownership_marker(bundle_hash, lf_body)
    return head + marker + eol + tail, removed


def translate(bundle: CapabilityBundle, host: str) -> tuple[dict[str, str], list[str]]:
    """{project-relative path: exact text} for one host, plus install-time modifications."""
    from .portfolio import _exact_text
    if bundle.kind != "skill":
        raise BundleError(f"only skills are installed; this is a {bundle.kind} ({KIND_RULES.get(bundle.kind, '')})")
    translator = HOSTS[host]
    base = translator.target_dir(bundle.name)
    collisions = path_collisions([f.path for f in bundle.files])
    if collisions:
        raise BundleError("paths collide on a case-insensitive filesystem: " + "; ".join(collisions[:4]))
    skill = next((f for f in bundle.files if f.path == "SKILL.md"), None)
    declared = front_name(skill.data.decode("utf-8", errors="replace")) if skill else ""
    if declared != bundle.name:
        raise BundleError(f"SKILL.md names itself {declared[:40]!r}, not {bundle.name!r}: a skill may not "
                          "claim another skill's name")
    out: dict[str, str] = {}
    modified: list[str] = []
    for f in bundle.files:
        rel = firewall.safe_rel(f.path)
        text = _exact_text(f.data, f.path)
        if f.path == "SKILL.md":
            text, removed = render_skill_md(text, bundle.content_hash, host)
            if removed:
                modified.append("removed front-matter keys from SKILL.md: " + ", ".join(removed[:8]))
        target = base / rel
        if not str(target).startswith(str(base) + "/"):  # pragma: no cover - safe_rel guarantees this
            raise BundleError(f"{f.path} leaves the skill directory")
        out[target.as_posix()] = text
    if f"{base.as_posix()}/SKILL.md" not in out:
        raise BundleError("the bundle has no SKILL.md")
    return out, modified


# --------------------------------------------------------------------------
# manifests (machine-local: they steer deletions, so a clone must not supply one)
# --------------------------------------------------------------------------
def manifest_dir(root: Path) -> Path:
    from .registry import machine_dir
    return machine_dir(root) / "bundles"


def _manifest_path(root: Path, name: str) -> Path:
    check_name(name)
    return manifest_dir(root) / f"{name}.json"


def load_manifest(root: Path, name: str) -> dict[str, Any]:
    path = _manifest_path(root, name)
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_MANIFEST or data.get("name") != name:
        data = {"schema": SCHEMA_MANIFEST, "name": name, "hosts": {}}
    raw_hosts = data.get("hosts")
    hosts: dict[str, Any] = raw_hosts if isinstance(raw_hosts, dict) else {}
    clean: dict[str, Any] = {}
    for host, entry in hosts.items():
        if host not in HOSTS or not isinstance(entry, dict):
            continue
        base = HOSTS[host].target_dir(name).as_posix() + "/"
        paths = {p: v for p, v in (entry.get("paths") or {}).items()
                 if isinstance(p, str) and p.startswith(base) and isinstance(v, dict) and _safe_project_rel(p)}
        target = HOSTS[host].target_dir(name)
        allowed = {target.as_posix(), *(p.as_posix() for p in target.parents if p.as_posix() != ".")}
        dirs = [d for d in (entry.get("created_dirs") or []) if isinstance(d, str) and d in allowed]
        clean[host] = {**entry, "paths": paths, "created_dirs": dirs}
    data["hosts"] = clean
    raw_record = data.get("record")
    record: dict[str, Any] = raw_record if isinstance(raw_record, dict) else {}
    data["record"] = {
        "approved_by": str(record.get("approved_by", ""))[:40] if isinstance(record.get("approved_by"), str) else "",
        "hosts": [h for h in (record.get("hosts") or []) if isinstance(h, str) and h in HOSTS],
        "content_hash": str(record.get("content_hash", "")) if re.fullmatch(
            r"[0-9a-f]{64}", str(record.get("content_hash", ""))) else "",
        "status": record.get("status") if record.get("status") in ("active", "disabled") else "",
    } if record else {}
    return data


def get_record(root: Path, name: str) -> dict[str, Any]:
    """The machine-local install record: who approved it, for which hosts, which content.

    This, not the committed lockfile, is authoritative for `approved_by`, hosts and
    status: a `git pull` can rewrite the lockfile, not this."""
    return dict(load_manifest(root, name).get("record") or {})


def set_record(root: Path, name: str, **fields: Any) -> dict[str, Any]:
    man = load_manifest(root, name)
    record = dict(man.get("record") or {})
    record.update(fields)
    man["record"] = record
    save_manifest(root, man)
    return get_record(root, name)


def _safe_project_rel(rel: str) -> bool:
    try:
        firewall.safe_rel(rel)
        return True
    except firewall.QuarantineError:
        return False


def save_manifest(root: Path, data: dict[str, Any]) -> None:
    from .fsutil import atomic_write
    path = _manifest_path(root, data["name"])
    try:
        path.resolve().relative_to(root.resolve())
        raise BundleError("REPO_AI_HOME points inside this repository: refusing to keep install manifests there")
    except ValueError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not data.get("hosts") and not data.get("record"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    atomic_write(path, json.dumps(data, indent=1, sort_keys=True) + "\n")


def all_manifests(root: Path) -> dict[str, dict[str, Any]]:
    d = manifest_dir(root)
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        if _NAME.fullmatch(p.stem):
            out[p.stem] = load_manifest(root, p.stem)
    return out


def _sha_file(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _owners(root: Path, rel: str, exclude: tuple[str, str] | None = None) -> list[tuple[str, str, str]]:
    """Other (name, host, written sha) entries that own `rel`."""
    out = []
    for name, man in all_manifests(root).items():
        for host, entry in man["hosts"].items():
            if exclude == (name, host):
                continue
            rec = entry["paths"].get(rel)
            if rec and rec.get("written_sha256"):
                out.append((name, host, rec["written_sha256"]))
    return out


def _owned_by_others(root: Path, target_dir: Path) -> bool:
    """True when the directory is empty, or every file in it is another host export's, unedited."""
    if not target_dir.is_dir() or target_dir.is_symlink():
        return False
    for dirpath, dirnames, filenames in os.walk(target_dir, followlinks=False):
        if any((Path(dirpath) / d).is_symlink() for d in dirnames):
            return False
        for f in filenames:
            path = Path(dirpath) / f
            rel = path.relative_to(root).as_posix()
            current = _sha_file(path)
            if current is None or not any(o[2] == current for o in _owners(root, rel)):
                return False
    return True


# --------------------------------------------------------------------------
# install / uninstall
# --------------------------------------------------------------------------
@dataclass(slots=True)
class InstallPlan:
    root: Path
    bundle: CapabilityBundle
    hosts: tuple[str, ...]
    plan: Any                                   # fsutil.Plan
    writes: dict[str, dict[str, str]] = field(default_factory=dict)   # host -> rel -> text
    shared: dict[str, list[str]] = field(default_factory=dict)        # host -> rels already identical (another host)
    stale: dict[str, list[str]] = field(default_factory=dict)         # host -> rels of the old version to remove
    conflicts: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    created_dirs: dict[str, list[str]] = field(default_factory=dict)
    legacy: dict[str, list[str]] = field(default_factory=dict)        # host -> rels owned per the lockfile only

    def diff(self) -> str:
        return str(self.plan.diff())

    def to_json(self) -> dict[str, Any]:
        return {"name": self.bundle.name, "content_hash": self.bundle.content_hash,
                "hosts": [HOSTS[h].to_json() for h in self.hosts],
                "writes": {h: sorted(w) for h, w in self.writes.items()},
                "shared": self.shared, "removes": self.stale, "conflicts": self.conflicts,
                "modified": self.modified, "diff": self.diff()}


def _missing_dirs(root: Path, rel_dir: PurePosixPath) -> list[str]:
    out = []
    cur = PurePosixPath()
    for part in rel_dir.parts:
        cur = cur / part
        if not (root / cur).exists():
            out.append(cur.as_posix())
    return out


def plan_install(root: Path, bundle: CapabilityBundle, hosts: tuple[str, ...],
                 previous_files: dict[str, list[dict[str, Any]]] | None = None) -> InstallPlan:
    """Plan writes for every host. Nothing is written; `conflicts` lists every refusal.

    `previous_files` (host -> lock-style file list) lets a skill installed before
    manifests existed be upgraded. The caller must derive it from machine-local
    evidence (the object store), never from the committed lockfile alone: a file
    listed there counts as repo-ai's when its bytes are exactly that evidence."""
    from .fsutil import Plan, UnsafePath, ensure_inside
    plan = Plan(root)
    ip = InstallPlan(root, bundle, hosts, plan)
    man = load_manifest(root, bundle.name)
    collisions = path_collisions([f.path for f in bundle.files])
    if collisions:
        ip.conflicts.extend(f"bundle: {c}" for c in collisions)
        return ip
    if "claude-code" in hosts:
        from .adapters.claude_content import CURATED_SKILL_NAMES, NATIVE_MANAGEMENT_SKILLS
        if bundle.name in CURATED_SKILL_NAMES or bundle.name in NATIVE_MANAGEMENT_SKILLS:
            ip.conflicts.append(f"claude-code: {bundle.name} is reserved for a curated repo-ai skill")
            return ip
    for host in hosts:
        texts, modified = translate(bundle, host)
        for m in modified:
            if m not in ip.modified:
                ip.modified.append(m)
        base = HOSTS[host].target_dir(bundle.name)
        mine = man["hosts"].get(host, {}).get("paths", {})
        legacy = {f"{base.as_posix()}/{f['path']}": f["sha256"] for f in (previous_files or {}).get(host, [])
                  if isinstance(f, dict) and _safe_project_rel(str(f.get("path", "")))}
        target_dir = root / base
        try:
            ensure_inside(root, target_dir / "SKILL.md")
        except UnsafePath as exc:
            ip.conflicts.append(f"{host}: {exc}")
            continue
        if target_dir.exists() and not mine and not legacy and not _owned_by_others(root, target_dir):
            ip.conflicts.append(f"{host}: {base.as_posix()} already exists and is not repo-ai managed")
            continue
        ip.created_dirs[host] = _missing_dirs(root, base)  # never a directory that already existed
        ip.legacy[host] = sorted(rel for rel, sha in legacy.items() if _sha_file(root / rel) == sha)
        writes: dict[str, str] = {}
        shared: list[str] = []
        for rel, text in sorted(texts.items()):
            path = root / rel
            try:
                ensure_inside(root, path)
            except UnsafePath as exc:
                ip.conflicts.append(f"{host}: {exc}")
                continue
            data = text.encode("utf-8")
            current = _sha_file(path)
            if path.is_symlink() or (path.exists() and not path.is_file()):
                ip.conflicts.append(f"{host}: {rel} is a symlink or not a regular file")
                continue
            if current is None:
                writes[rel] = text
                continue
            ours = (mine.get(rel) or {}).get("written_sha256") or legacy.get(rel)
            if ours and current == ours:
                writes[rel] = text
                continue
            others = [o for o in _owners(root, rel, (bundle.name, host)) if o[2] == current]
            if others and current == hashlib.sha256(data).hexdigest():
                shared.append(rel)  # another host's export already wrote these exact bytes
                continue
            reason = "edited since repo-ai wrote it" if ours else "exists and is not repo-ai's"
            ip.conflicts.append(f"{host}: {rel} {reason}; never overwritten")
        ip.writes[host] = writes
        ip.shared[host] = shared
        stale = [rel for rel, rec in {**{k: {"written_sha256": v} for k, v in legacy.items()}, **mine}.items()
                 if rel not in texts and rec.get("written_sha256")
                 and _sha_file(root / rel) == rec.get("written_sha256")]
        ip.stale[host] = sorted(stale)
    if not ip.conflicts:
        for host in hosts:
            for rel, text in ip.writes.get(host, {}).items():
                plan.write(root / rel, text)
            for rel in ip.stale.get(host, []):
                if not _owners(root, rel, (bundle.name, host)):
                    plan.delete(root / rel)
    return ip


def apply_install(ip: InstallPlan) -> dict[str, Any]:
    """Write the planned files and record, per path, what was there before repo-ai first wrote it."""
    if ip.conflicts:
        raise BundleError("refusing to install: " + "; ".join(ip.conflicts[:6]))
    root = ip.root
    man = load_manifest(root, ip.bundle.name)
    # baselines are captured before anything is written
    pending: dict[str, dict[str, Any]] = {}
    for host in ip.hosts:
        entry = man["hosts"].get(host) or {"paths": {}, "created_dirs": []}
        paths = dict(entry["paths"])
        for rel in [*ip.writes.get(host, {}), *ip.shared.get(host, [])]:
            if rel in paths:
                continue
            path = root / rel
            prior = None
            if path.is_file() and not path.is_symlink() and rel not in ip.shared.get(host, []) \
                    and rel not in ip.legacy.get(host, []):
                raw = path.read_bytes()
                prior = {"sha256": hashlib.sha256(raw).hexdigest(), "b64": base64.b64encode(raw).decode()}
            paths[rel] = {"baseline": prior}
        created = list(dict.fromkeys([*entry.get("created_dirs", []), *ip.created_dirs.get(host, [])]))
        pending[host] = {"paths": paths, "created_dirs": created}
    ip.plan.apply()
    for host in ip.hosts:
        rec = pending[host]
        for rel, text in ip.writes.get(host, {}).items():
            rec["paths"][rel]["written_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        for rel in ip.shared.get(host, []):
            rec["paths"][rel]["written_sha256"] = _sha_file(root / rel)
            rec["paths"][rel]["shared"] = True
        for rel in ip.stale.get(host, []):
            if rel in rec["paths"] and rec["paths"][rel].get("baseline") is None:
                rec["paths"].pop(rel, None)
        man["hosts"][host] = {**rec, "content_hash": ip.bundle.content_hash,
                              "support": HOSTS[host].support}
    save_manifest(root, man)
    return man


def plan_uninstall(root: Path, name: str, plan: Any,
                   hosts: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Add to `plan` what puts back exactly what was there before repo-ai's first install of `name`.

    A file still byte-identical to what repo-ai wrote is restored to its
    baseline (deleted when there was none). A file you edited is kept. A path
    another host's export still uses is left in place."""
    from .fsutil import UnsafePath, ensure_inside
    man = load_manifest(root, name)
    targets = [h for h in (hosts or tuple(man["hosts"])) if h in man["hosts"]]
    kept: list[str] = []
    restored: list[str] = []
    dirs: list[str] = []
    handover: list[tuple[str, str]] = []
    for host in targets:
        entry = man["hosts"][host]
        for rel, rec in sorted(entry["paths"].items()):
            path = root / rel
            try:
                ensure_inside(root, path)
            except UnsafePath:
                kept.append(f"{rel} (unsafe path: left untouched)")
                continue
            if path.is_symlink():
                kept.append(f"{rel} (symlink: left untouched)")
                continue
            current = _sha_file(path)
            if current is None:
                continue
            if current != rec.get("written_sha256"):
                kept.append(f"{rel} (edited since repo-ai wrote it)")
                continue
            sharers = [o for o in _owners(root, rel, (name, host))
                       if o[2] == current and (o[0] != name or o[1] not in targets)]
            if sharers:
                kept.append(f"{rel} (still used by another host's export)")
                handover.extend((o[0], o[1]) for o in sharers)
                continue
            baseline = rec.get("baseline")
            if baseline:
                try:
                    raw = base64.b64decode(str(baseline.get("b64", "")), validate=True)
                except ValueError:
                    raw = b""
                if hashlib.sha256(raw).hexdigest() != baseline.get("sha256"):
                    kept.append(f"{rel} (manifest baseline corrupt: left untouched)")
                    continue
                try:
                    plan.write(path, raw.decode("utf-8"))
                except UnicodeDecodeError:
                    kept.append(f"{rel} (baseline is not UTF-8 text: left untouched)")
                    continue
            else:
                plan.delete(path)
            if rel not in restored:
                restored.append(rel)
        dirs.extend(d for d in entry.get("created_dirs", []) if d not in dirs)
    return {"name": name, "hosts": targets, "restored": restored, "kept": kept,
            "created_dirs": sorted(dirs, key=lambda p: -len(PurePosixPath(p).parts)),
            "handover": sorted(set(handover))}


def remove_created_dirs(root: Path, dirs: list[str]) -> None:
    """Remove only directories repo-ai created, deepest first, and only when empty."""
    from .fsutil import UnsafePath, ensure_inside
    for d in sorted(set(dirs), key=lambda p: -len(PurePosixPath(p).parts)):
        path = root / d
        try:
            ensure_inside(root, path)
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
        except (OSError, UnsafePath):
            continue


def uninstall(root: Path, name: str, hosts: tuple[str, ...] | None = None, *,
              dry_run: bool = False) -> dict[str, Any]:
    """Byte-exact uninstall of `name` from `hosts` (all recorded hosts by default)."""
    from .fsutil import Plan
    plan = Plan(root)
    result = plan_uninstall(root, name, plan, hosts)
    result["diff"] = plan.diff()
    if dry_run:
        return result
    plan.apply()
    remove_created_dirs(root, result["created_dirs"])
    man = load_manifest(root, name)
    for host in result["hosts"]:
        man["hosts"].pop(host, None)
    save_manifest(root, man)
    # a host export that still shares a path inherits the directories this one created
    left = [d for d in result["created_dirs"] if (root / d).is_dir()]
    for other_name, other_host in result.pop("handover"):
        other = load_manifest(root, other_name)
        if other_host in other["hosts"] and left:
            entry = other["hosts"][other_host]
            entry["created_dirs"] = list(dict.fromkeys([*entry.get("created_dirs", []), *left]))
            save_manifest(root, other)
            other = load_manifest(root, other_name)  # re-validated: only that host's own ancestors survive
            save_manifest(root, other)
    return result
