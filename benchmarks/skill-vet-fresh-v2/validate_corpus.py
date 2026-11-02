"""Check an independently written skill-vet-fresh-v2 delivery before it is committed (AUTHOR-BRIEF.md). CI only.

    REPO_AI_SECURITY_FIXTURES=1 python benchmarks/skill-vet-fresh-v2/validate_corpus.py DELIVERY_DIR [--json]

Structure, counts, labels, provenance, the frozen manifest and defanged hosts in harmful cases. The layout is the one
`run.py` loads (`labels.json` with `{"cases": [...]}`, `corpus/<id>/`). It never runs repo-ai's vetter and encodes
none of its rules: whether a case is harmful is the author's label, not this script's opinion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

COUNTS = {"H-text": 20, "H-code": 10, "B-skill": 30, "H-plugin": 10, "B-plugin": 10}
SKILLS = {"H-text", "H-code", "B-skill"}
CASE_ID = re.compile(r"^case-\d{3}$")
FIELDS = ("id", "stratum", "intended_harm", "observable_harm")
# a URL's host: userinfo may not contain ? # \ (they end the authority), the host is a run of host characters or a
# bracketed literal; a placeholder host ({x}, $X, <x>) does not match and is not checked
URL_HOST = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://(?:[^\s/?#\\@]*@)?(\[[^\]\s]*\]|[a-z0-9._%-]+)")
BARE_HOST = re.compile(r"(?i)(?<![\w@/.-])((?:[a-z0-9_-]+\.)+[a-z][a-z0-9-]{1,62})(?=[/:][^\s])")
EMAIL_HOST = re.compile(r"(?i)\b[a-z0-9._%+-]+@((?:[a-z0-9_-]+\.)+[a-z][a-z0-9-]{1,62})\b")
BARE_IP = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")
SAFE_HOST = re.compile(r"(?i)^(?:[a-z0-9_-]+\.)*(?:example\.com|[a-z0-9_-]+\.invalid)$")
FILE_SUFFIXES = {"py", "md", "json", "js", "mjs", "cjs", "ts", "sh", "txt", "yml", "yaml", "toml", "cfg", "ini", "html",
                 "css", "lock", "log", "rs", "go", "rb", "java", "kt", "swift", "c", "h", "cpp", "env", "pem", "key",
                 "csv", "xml", "zip", "tar", "gz", "png", "jpg", "svg", "pdf"}
MAX_FILE = 1_000_000


def _front_matter(text: str) -> dict[str, str]:
    text = text.lstrip("﻿")
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}
    body = text.replace("\r\n", "\n")
    end = body.find("\n---", 4)
    if end < 0:
        return {}
    out = {}
    for line in body[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t")):
            out[key.strip()] = value.strip()
    return out


def hosts(text: str) -> list[str]:
    """Hosts named in URLs, e-mail addresses, scheme-less `host/path` or `host:port` forms and bare IPv4 addresses."""
    # IDNA treats these as label separators too; NFKC folds full-width forms
    text = unicodedata.normalize("NFKC", text).translate({0x3002: ".", 0xFF0E: ".", 0xFF61: "."})
    found = [m.group(1) for m in URL_HOST.finditer(text)]
    found += [m.group(1) for m in EMAIL_HOST.finditer(text)]
    found += [m.group(1) for m in BARE_HOST.finditer(text) if m.group(1).rsplit(".", 1)[-1].lower() not in FILE_SUFFIXES]
    found += [m.group(1) for m in BARE_IP.finditer(text)]
    return [h.strip().rstrip(".").lower() for h in found if h.strip()]


def unsafe_host(host: str) -> bool:
    """Anything but example.com or a .invalid name (with optional subdomains) is not defanged."""
    return not SAFE_HOST.match(host) or "%" in host


def _prose_only(text: str) -> str | None:
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        stripped = line.lstrip(" >\t")
        if stripped.startswith(("```", "~~~")):
            return "a fenced code block"
        if (line.startswith("    ") or line.startswith("\t")) and line.strip() and \
                (i == 0 or not lines[i - 1].strip()) and not re.match(r"^\s*([-*+]|\d+[.)])\s", line):
            return "an indented code block"
    if re.search(r"(?i)<\s*(pre|code)\b", text):
        return "a <pre> or <code> element"
    return None


def _manifest(path: Path) -> tuple[dict[str, str], list[str]]:
    listed, bad = {}, []
    for line in path.read_text("utf-8", "replace").split("\n"):
        line = line.rstrip("\r")
        if not line:
            continue
        m = re.match(r"^\\?([0-9A-Fa-f]{64}) [ *](.+)$", line)
        if not m:
            bad.append(line[:80])
            continue
        listed[m.group(2).removeprefix("./")] = m.group(1).lower()
    return listed, bad


def validate(root: Path, counts: dict[str, int] = COUNTS) -> dict:
    problems: list[str] = []
    corpus, labels_path, author, manifest = (root / "corpus", root / "labels.json", root / "AUTHOR.md",
                                             root / "MANIFEST.sha256")
    for need in (corpus, labels_path, author, manifest):
        if not need.exists():
            problems.append(f"missing {need.relative_to(root)}")
        elif need.is_symlink():
            problems.append(f"symlink not allowed: {need.relative_to(root)}")
    if problems:
        return {"ok": False, "problems": problems}
    if not author.read_text("utf-8", "replace").strip():
        problems.append("AUTHOR.md is empty")

    files = sorted(p for p in corpus.rglob("*") if p.is_file() or p.is_symlink())
    for p in [*files, *(d for d in corpus.rglob("*") if d.is_dir() and d.is_symlink())]:
        if p.is_symlink():
            problems.append(f"symlink not allowed: {p.relative_to(root)}")
        elif p.stat().st_size > MAX_FILE:
            problems.append(f"file over {MAX_FILE} bytes: {p.relative_to(root)}")

    # the frozen manifest covers exactly the corpus, labels.json and AUTHOR.md
    listed, bad = _manifest(manifest)
    problems += [f"MANIFEST.sha256: unreadable line {b!r}" for b in bad]
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [*files, labels_path, author] if not p.is_symlink()}
    for rel in sorted(set(actual) - set(listed)):
        problems.append(f"not in MANIFEST.sha256: {rel}")
    for rel in sorted(set(listed) - set(actual)):
        problems.append(f"in MANIFEST.sha256 but not delivered: {rel}")
    for rel in sorted(set(actual) & set(listed)):
        if actual[rel] != listed[rel]:
            problems.append(f"changed since the manifest was frozen: {rel}")

    try:
        raw = json.loads(labels_path.read_text("utf-8"))
        entries = raw["cases"] if isinstance(raw, dict) else None
    except (ValueError, KeyError):
        entries = None
    if not isinstance(entries, list):
        return {"ok": False, "problems": [*problems, 'labels.json must be {"cases": [ ... ]}']}
    labels: dict[str, dict] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"labels.json entry {i} is not an object")
            continue
        bad_fields = [f for f in FIELDS if not isinstance(entry.get(f), str) or not entry[f].strip()]
        if bad_fields:
            problems.append(f"labels.json entry {i}: missing or empty {', '.join(bad_fields)}")
            continue
        if entry["id"] in labels:
            problems.append(f"labels.json: {entry['id']} labelled twice")
        labels[entry["id"]] = entry

    entries_on_disk = sorted(corpus.iterdir())
    for p in entries_on_disk:
        if not p.is_dir():
            problems.append(f"corpus/{p.name}: only case directories belong in corpus/")
    cases = [p for p in entries_on_disk if p.is_dir() and not p.is_symlink()]
    seen: dict[str, int] = {s: 0 for s in counts}
    for case in cases:
        cid = case.name
        if not CASE_ID.match(cid):
            problems.append(f"{cid}: case ids must be neutral (case-NNN)")
        label = labels.get(cid)
        if label is None:
            problems.append(f"{cid}: no entry in labels.json")
            continue
        stratum = label["stratum"]
        if stratum not in counts:
            problems.append(f"{cid}: unknown stratum {stratum!r}")
            continue
        seen[stratum] += 1
        benign = stratum.startswith("B-")
        for field in ("intended_harm", "observable_harm"):
            if benign != (label[field].strip().lower() == "none"):
                problems.append(f"{cid}: {field} must be 'none' for a benign case and a sentence for a harmful one")
        names = sorted(p.relative_to(case).as_posix() for p in case.rglob("*") if p.is_file())
        if stratum in SKILLS:
            skill = case / "SKILL.md"
            text = skill.read_text("utf-8", "replace") if skill.is_file() else ""
            front = _front_matter(text)
            if not front.get("name") or not front.get("description"):
                problems.append(f"{cid}: SKILL.md with front matter (name, description) required")
            if stratum == "H-text":
                if names != ["SKILL.md"]:
                    problems.append(f"{cid}: H-text is SKILL.md only (found {len(names)} files)")
                elif (why := _prose_only(text)):
                    problems.append(f"{cid}: H-text is prose only ({why} was found)")
        else:
            try:
                json.loads((case / ".claude-plugin" / "plugin.json").read_text("utf-8"))
            except (OSError, ValueError):
                problems.append(f"{cid}: .claude-plugin/plugin.json (valid JSON) required")
        if not benign:
            for p in case.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    for host in hosts(p.read_text("utf-8", "replace")):
                        if unsafe_host(host):
                            problems.append(f"{cid}: host {host!r} in {p.relative_to(case).as_posix()} is not "
                                            "defanged (use example.com or a .invalid name)")
    for cid in sorted(set(labels) - {c.name for c in cases}):
        problems.append(f"labels.json names {cid}, which has no case directory")
    for stratum, want in counts.items():
        if seen[stratum] != want:
            problems.append(f"{stratum}: {seen[stratum]} cases, the preregistration fixes {want}")
    return {"ok": not problems, "cases": len(cases), "per_stratum": seen, "problems": problems}


def main() -> int:
    if os.environ.get("REPO_AI_SECURITY_FIXTURES") != "1":
        print("this reads a corpus of defanged attack-like fixtures; run it in CI with REPO_AI_SECURITY_FIXTURES=1",
              file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("delivery", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = validate(args.delivery.resolve())
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        print("OK" if report["ok"] else "NOT OK")
        for problem in report["problems"]:
            print("  " + problem)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
