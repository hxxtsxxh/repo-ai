"""Build a public source export: one fresh commit of a curated tree.

The private repository's history contains material that must not become
public (the sealed-v2 confirmatory set and its authoring notes, held-out
labels, a corporate author address, local paths and spend notes). A
visibility flip would expose all of it, including `refs/pull/*`, which the
owner cannot rewrite. This script instead writes a new repository whose only
commit is the tree at REF minus EXCLUDED paths, then audits that tree.

    python scripts/public_export.py --out /tmp/repo-ai-public            # build + audit
    python scripts/public_export.py --out /tmp/repo-ai-public --audit-only

It never pushes, never touches a remote, and never modifies this checkout.
Pushing the result to a public repository is a separate, owner-approved step.
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Path prefixes (POSIX, relative to the repository root) left out of the export.
EXCLUDED = (
    "benchmarks/sealed-v2/",          # sealed confirmatory set: publishing it ends its use as a holdout
    "benchmarks/authoring/",          # authoring notes contain the upstream fixes for sealed tasks
    "benchmarks/verify-eval/results/",  # held-out labels, mutated upstream sources, local logs
    "docs/research/",                 # research ledgers, corpora, personal browsing notes
    "docs/EXECUTION_LEDGER.md",       # spend ledger and private-repository notes
    "docs/roadmap/BOB-CONTINUOUS-EXECUTION.md",   # provider account states, local paths
    "docs/roadmap/BOB-NEXT-PHASE-CONTINUATION.md",
    "benchmarks/results/option-a-v0.7.5/runs.jsonl",      # per-run records with local paths
    "benchmarks/results/sealed-v2-pairs-v0.7.7/runs.jsonl",
    "docs/launch/CLAUDE_ULTIMATE_PRODUCT_LAUNCH_MISSION.md",
)

# Text that must not appear anywhere in the exported tree. Spelled in pieces so this
# file does not match itself.
_USER = b"heet" + b"shah"
FORBIDDEN = [
    (re.compile(re.escape(_USER + b"@" + b"ibm.com")), "corporate e-mail address"),
    (re.compile(re.escape(b"/Users/" + _USER) + rb"\b"), "local home path"),
    (re.compile(re.escape(b"claude-" + b"501/-Users-")), "local Claude Code scratch path"),
    (re.compile(re.escape(b"github." + b"ibm.com")), "enterprise GitHub host"),
    (re.compile(re.escape(b"keep it " + b"private")), "private-only policy text"),
    (re.compile(rb"IBM " + rb"Confidential", re.I), "confidentiality marking"),
]

AUTHOR = "Heet Shah <84190049+hxxtsxxh@users.noreply.github.com>"


def excluded(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in EXCLUDED)


def git(*args: str, cwd: Path = ROOT, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, **kw)


def export_tree(ref: str, out: Path) -> list[str]:
    archive = git("archive", "--format=tar", ref).stdout
    kept: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if excluded(member.name) or not (member.isfile() or member.isdir() or member.issym()):
                continue
            tar.extract(member, out, filter="data")
            if member.isfile():
                kept.append(member.name)
    return kept


def audit(out: Path) -> list[str]:
    problems = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and ".git" not in p.relative_to(out).parts):
        rel = path.relative_to(out).as_posix()
        if excluded(rel):
            problems.append(f"{rel}: excluded path present")
        data = path.read_bytes()
        for pattern, what in FORBIDDEN:
            if pattern.search(data):
                problems.append(f"{rel}: {what}")
    return problems


def commit(out: Path, ref: str) -> str:
    sha = git("rev-parse", ref).stdout.decode().strip()
    version = re.search(r'__version__ = "([^"]+)"', (out / "src/repo_ai/__init__.py").read_text()).group(1)
    name, email = AUTHOR.rsplit(" <", 1)
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email.rstrip(">"),
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email.rstrip(">"),
           "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    git("init", "-q", "-b", "main", cwd=out)
    git("add", "-A", cwd=out)
    msg = (f"repo-ai {version}: public source\n\nCurated export of the private development tree at {sha[:12]}. "
           "Sealed benchmark sets, held-out labels, research ledgers and personal run records are not included; "
           "see scripts/public_export.py for the exact list.\n")
    git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", msg, cwd=out, env=env)
    return git("rev-parse", "HEAD", cwd=out).stdout.decode().strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="HEAD", help="private commit to export (default: HEAD)")
    ap.add_argument("--out", required=True, type=Path, help="new directory for the export (must not exist)")
    ap.add_argument("--audit-only", action="store_true", help="audit an existing export directory")
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if not args.audit_only:
        if out.exists():
            print(f"{out} exists; choose a new directory", file=sys.stderr)
            return 2
        out.mkdir(parents=True)
        try:
            kept = export_tree(args.ref, out)
        except BaseException:
            shutil.rmtree(out, ignore_errors=True)
            raise
        print(f"exported {len(kept)} files from {args.ref}")
    problems = audit(out)
    for p in problems:
        print("FAIL " + p, file=sys.stderr)
    if problems:
        return 1
    print("audit: no excluded paths, no forbidden text")
    if not args.audit_only:
        print("commit " + commit(out, args.ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
