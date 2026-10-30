"""File discovery and the ignore pipeline.

Filter order (cheapest and most decisive first):

  1. hard-coded directory blocklist      -> prune whole subtrees, never descend
  2. `.gitignore` (+ nested ones)        -> respect the repo's own intent
  3. `.dockerignore`                     -> catches build-only artifacts
  4. `.bobignore`                        -> user's explicit "Bob must not see this"
  5. `.repo-ai.toml` extra_excludes      -> project-specific tuning
  6. extension blocklist                 -> binaries, media, model weights
  7. size ceiling                        -> >1.5 MB recorded but not parsed
  8. binary sniff (NUL byte in first 8k) -> catches unknown binary formats
  9. secret path globs                   -> quarantine before any read
 10. generated-content banner            -> `@generated`, `DO NOT EDIT`, minified

Anything surviving all ten is indexed. `include_overrides` can re-admit paths
dropped by 1/6 (useful when a vendored directory really is first-party code).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pathspec

from .config import DEFAULT_SECRET_PATH_GLOBS, Config
from .fsutil import strip_managed_blocks
from .languages import classify_role, detect_language
from .logging_setup import get_logger
from .models import FileRecord, SecretHit
from .security import path_is_secretlike, scan_text, should_quarantine

log = get_logger()

_BINARY_PROBE = 8192


@dataclass(slots=True)
class ScanResult:
    files: list[FileRecord]
    secret_hits: list[SecretHit]
    quarantined: list[str]
    skipped: dict[str, int]
    total_seen: int
    oversized: list[str]
    lockfiles: list[str]
    reused: int = 0


def _spec(lines) -> pathspec.PathSpec:
    # GitIgnoreSpec reproduces git's own edge cases (and avoids the
    # deprecated "gitwildmatch" factory name).
    return pathspec.GitIgnoreSpec.from_lines(list(lines))


def _load_ignore_spec(root: Path, filename: str) -> pathspec.PathSpec | None:
    path = root / filename
    if not path.is_file():
        return None
    try:
        lines = path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return _spec(lines)


# Control characters (including newlines) in a filename are almost always
# hostile: they break Markdown tables and could smuggle text into an agent's
# context through a file list. Such files are skipped, never echoed.
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f]")


_AGENT_DIRS = frozenset({".repo-ai", ".claude", ".bob"})


def _within(root_real: str, path: str) -> bool:
    real = os.path.realpath(path)
    return real == root_real or real.startswith(root_real + os.sep)


def _is_binary(chunk: bytes) -> bool:
    if b"\x00" in chunk:
        return True
    if not chunk:
        return False
    # High ratio of non-text bytes -> treat as binary.
    text_chars = bytes(range(0x20, 0x7F)) + b"\n\r\t\f\b\x1b"
    nontext = sum(1 for b in chunk if b not in text_chars)
    return nontext / len(chunk) > 0.30


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def _leading_doc(text: str, language: str) -> str:
    """First meaningful docstring/comment line, used as a one-line file summary."""
    lines = text.splitlines()[:40]
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#!") or line.startswith("<?") or line.startswith("# -*-"):
            continue
        for prefix in ('"""', "'''", "///", "//!", "//", "#", "*", "/*", "--", "%"):
            if line.startswith(prefix):
                cleaned = line[len(prefix):].strip(" *\"'/-")
                if len(cleaned) > 12:
                    return cleaned[:200]
                break
        else:
            # First non-comment line: stop looking.
            break
    return ""


# Shared instruction files that may contain repo-ai managed blocks. The blocks
# are stripped before classification and indexing so repo-ai never treats its
# own output as evidence about the repository.
INSTRUCTION_FILES = frozenset({"AGENTS.md", "CLAUDE.md", "CLAUDE.local.md",
                               ".gitignore", ".bobignore"})


_SCAFFOLD_LINE = re.compile(r"^\s*(#\s+\S.*|@(?:\./)?AGENTS\.md|<!--.*repo-ai.*-->)\s*$")


def _scaffold_only(text: str) -> bool:
    """Nothing but blank lines, a title, an `@AGENTS.md` import, or repo-ai's
    own comments — i.e. a file repo-ai created, not repository knowledge."""
    return all(not line.strip() or _SCAFFOLD_LINE.match(line) for line in text.splitlines())


def analysis_text(rel: str, text: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if name in INSTRUCTION_FILES:
        text = strip_managed_blocks(text)
        if name == ".gitignore":
            # v0.4 appended an unmarked "# repo-ai" section; repo-ai migrates
            # it into a managed block, which must not count as drift.
            from .adapters.base import strip_legacy_gitignore
            text = strip_legacy_gitignore(text)
    return text


def scan(
    root: Path,
    cfg: Config,
    known: dict[str, FileRecord] | None = None,
    prune: tuple[str, ...] = (),
) -> ScanResult:
    """Walk the repository and return the set of indexable files.

    `known` maps path -> the FileRecord from the previous run. When a file's
    size and mtime both match, its content is not read again: the stored
    hash, language, role, and summary are reused. On a large repository this
    is the difference between a 9-second update and a sub-second one, and it
    is safe because any edit moves mtime.

    Pass `known=None` (the default) to force a full re-read.

    `prune` lists repo-relative directories that are never descended into —
    repo-ai's own output and state directories, wherever they are configured.
    """
    files: list[FileRecord] = []
    reused = 0
    secret_hits: list[SecretHit] = []
    quarantined: list[str] = []
    oversized: list[str] = []
    lockfiles: list[str] = []
    skipped: dict[str, int] = {}
    total_seen = 0

    def bump(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    root_gitignore = _load_ignore_spec(root, ".gitignore") if cfg.respect_gitignore else None
    dockerignore = _load_ignore_spec(root, ".dockerignore") if cfg.respect_dockerignore else None
    bobignore = _load_ignore_spec(root, ".bobignore")
    # Nested .gitignore files apply to their own subtree. They are loaded as
    # the walk reaches them (os.walk is top-down), so one pass suffices.
    nested: dict[str, pathspec.PathSpec] = {}

    extra_spec = _spec(cfg.extra_excludes) if cfg.extra_excludes else None
    override_spec = _spec(cfg.include_overrides) if cfg.include_overrides else None
    pruned = {p.strip("/") for p in prune if p and p.strip("/")}
    root_real = os.path.realpath(root)

    exclude_dirs = set(cfg.exclude_dirs)
    exclude_exts = set(cfg.exclude_exts)
    lockfile_names = set(cfg.lockfiles)

    def nested_ignored(rel: str) -> bool:
        for prefix, spec in nested.items():
            if rel.startswith(prefix + "/") and spec.match_file(rel[len(prefix) + 1:]):
                return True
        return False

    def ignored(rel: str) -> str:
        """Return the ignore reason, or '' when the file is allowed.

        `include_overrides` re-admit only what repo-ai's own defaults or
        `extra_excludes` dropped. They never re-admit gitignored, dockerignored
        or .bobignored files: those are often machine-local and secret-bearing,
        and the override may come from a cloned repository's config.
        """
        if root_gitignore is not None and root_gitignore.match_file(rel):
            return "gitignore"
        if nested and nested_ignored(rel):
            return "gitignore-nested"
        if dockerignore is not None and dockerignore.match_file(rel):
            return "dockerignore"
        if bobignore is not None and bobignore.match_file(rel):
            return "bobignore"
        if override_spec is not None and override_spec.match_file(rel):
            return ""
        if extra_spec is not None and extra_spec.match_file(rel):
            return "config-exclude"
        return ""

    for dirpath, dirnames, filenames in os.walk(root, followlinks=cfg.follow_symlinks):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")

        if rel_dir and cfg.respect_gitignore and ".gitignore" in filenames:
            spec = _load_ignore_spec(Path(dirpath), ".gitignore")
            if spec is not None:
                nested[rel_dir] = spec

        # Prune. Modifying dirnames in place stops os.walk descending.
        keep: list[str] = []
        for d in sorted(dirnames):
            rel_sub = f"{rel_dir}/{d}" if rel_dir else d
            if rel_sub in pruned or d in _AGENT_DIRS:
                continue  # repo-ai / agent configuration: not part of the codebase census
            if d in exclude_dirs:
                bump("excluded-dir")
                continue
            if _UNSAFE_NAME.search(d):
                bump("unsafe-name")
                continue
            if cfg.follow_symlinks and os.path.islink(os.path.join(dirpath, d)) \
                    and not _within(root_real, os.path.join(dirpath, d)):
                bump("symlink-escape")
                continue
            if root_gitignore is not None and root_gitignore.match_file(rel_sub + "/"):
                bump("gitignore-dir")
                continue
            if nested and nested_ignored(rel_sub + "/"):
                bump("gitignore-dir")
                continue
            keep.append(d)
        dirnames[:] = keep

        for filename in sorted(filenames):
            total_seen += 1
            if len(files) >= cfg.max_files:
                bump("max-files-cap")
                continue

            if _UNSAFE_NAME.search(filename):
                bump("unsafe-name")
                continue

            rel = f"{rel_dir}/{filename}" if rel_dir else filename
            abs_path = Path(dirpath) / filename

            # A symlinked file can point anywhere (`notes.txt -> ~/.ssh/id_rsa`).
            # Never follow one unless asked, and never outside the repository.
            if os.path.islink(abs_path):
                if not cfg.follow_symlinks or not _within(root_real, str(abs_path)):
                    bump("symlink")
                    continue

            if filename in lockfile_names:
                lockfiles.append(rel)
                bump("lockfile")
                continue

            reason = ignored(rel)
            if reason:
                bump(reason)
                continue

            lower = filename.lower()
            if any(lower.endswith(ext) for ext in exclude_exts):
                bump("binary-ext")
                continue

            if path_is_secretlike(rel, DEFAULT_SECRET_PATH_GLOBS):
                quarantined.append(rel)
                secret_hits.append(SecretHit(
                    path=rel, line=0, rule="secret-path-pattern",
                    severity="high", redacted="(file quarantined by name)",
                ))
                bump("secret-path")
                continue

            try:
                stat = abs_path.stat()
            except OSError:
                bump("stat-error")
                continue

            if not abs_path.is_file():
                bump("not-a-file")
                continue

            if stat.st_size > cfg.max_file_bytes:
                oversized.append(rel)
                bump("oversized")
                continue

            if stat.st_size == 0:
                bump("empty")
                continue

            prior = known.get(rel) if known else None
            if (prior is not None
                    and prior.size == stat.st_size
                    and abs(prior.mtime - stat.st_mtime) < 1e-6):
                # Unchanged since the last run: trust the stored record and
                # skip the read, the hash, and the secret scan.
                files.append(prior)
                reused += 1
                continue

            try:
                data = abs_path.read_bytes()
            except OSError as exc:
                log.debug("read failed for %s: %s", rel, exc)
                bump("read-error")
                continue

            if _is_binary(data[:_BINARY_PROBE]):
                bump("binary-content")
                continue

            text = data.decode("utf-8", errors="replace")
            if filename in INSTRUCTION_FILES:
                text = analysis_text(rel, text)
                if _scaffold_only(text):
                    total_seen -= 1  # nothing but repo-ai's own managed block
                    continue
            first_line = text.split("\n", 1)[0][:200]
            language = detect_language(rel, first_line)
            role = classify_role(rel, language, analysis_text(rel, text)[:4000])

            if cfg.detect_secrets:
                hits = scan_text(rel, text)
                if hits:
                    secret_hits.extend(hits)
                    # Only embedded key material justifies removing the whole
                    # file from the index. A dev database URL inside a
                    # docker-compose file is reported, not hidden: losing that
                    # file would cost more architectural context than it
                    # protects, and Bob can read it from disk anyway.
                    if should_quarantine(hits):
                        quarantined.append(rel)
                        bump("secret-content")
                        continue

            files.append(FileRecord(
                path=rel,
                size=stat.st_size,
                lines=text.count("\n") + (0 if text.endswith("\n") else 1),
                language=language,
                # Instruction files are hashed without repo-ai's managed blocks,
                # so repo-ai's own edits never count as a change to the repo.
                sha1=_sha1(text.encode("utf-8")) if filename in INSTRUCTION_FILES else _sha1(data),
                mtime=stat.st_mtime,
                role=role,
                doc_summary=_leading_doc(analysis_text(rel, text), language),
            ))

    files.sort(key=lambda f: f.path)
    return ScanResult(
        files=files,
        secret_hits=secret_hits,
        reused=reused,
        quarantined=sorted(set(quarantined)),
        skipped=skipped,
        total_seen=total_seen,
        oversized=oversized,
        lockfiles=sorted(set(lockfiles)),
    )


def content_sha(root: Path, rel: str) -> str:
    """The hash the scanner would store for `rel` right now ('' if unreadable)."""
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return ""
    if rel.rsplit("/", 1)[-1] in INSTRUCTION_FILES:
        return _sha1(analysis_text(rel, data.decode("utf-8", errors="replace")).encode("utf-8"))
    return _sha1(data)


def real_drift(root: Path, index, paths: list[str]) -> list[str]:
    """Drop paths whose content still matches the index (e.g. only a managed
    block changed). Paths not in the index count as drift unless they are
    instruction files containing nothing but repo-ai blocks."""
    out: list[str] = []
    for rel in paths:
        row = index.get_file(rel)
        if row is not None:
            if content_sha(root, rel) != row["sha1"]:
                out.append(rel)
            continue
        name = rel.rsplit("/", 1)[-1]
        if name in INSTRUCTION_FILES:
            try:
                text = (root / rel).read_text("utf-8", errors="replace")
            except OSError:
                continue
            if _scaffold_only(analysis_text(rel, text)):
                continue
        out.append(rel)
    return out


def read_text(root: Path, rel: str, limit: int = 2_000_000) -> str:
    try:
        data = (root / rel).read_bytes()[:limit]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")
