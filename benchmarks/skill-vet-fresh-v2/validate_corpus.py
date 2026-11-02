"""Check an independently written skill-vet-fresh-v2 delivery before it is committed (AUTHOR-BRIEF.md). CI only.

    python benchmarks/skill-vet-fresh-v2/validate_corpus.py DELIVERY_DIR [--json]

Structure, counts, labels, provenance, the frozen manifest and defanged hosts. It never runs repo-ai's vetter and
encodes none of its rules: whether a case is harmful is the author's label, not this script's opinion.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path

COUNTS = {"H-text": 20, "H-code": 10, "B-skill": 30, "H-plugin": 10, "B-plugin": 10}
SKILLS = {"H-text", "H-code", "B-skill"}
CASE_ID = re.compile(r"^case-\d{3}$")
URL_HOST = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://(?:[^\s/@'\"<>]*@)?(\[[0-9a-f:.]+\]|[^\s/:'\"<>?#)]+)")
SAFE_HOST = re.compile(r"(?i)^(?:[a-z0-9-]+\.)*(?:example\.(?:com|org|net)|[a-z0-9-]+\.invalid|invalid)$")
MAX_FILE = 1_000_000


def _front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    out = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t")):
            out[key.strip()] = value.strip()
    return out


def _hosts(text: str) -> list[str]:
    return [m.group(1).strip("[]").rstrip(".").lower() for m in URL_HOST.finditer(text)]


def _unsafe_host(host: str) -> bool:
    if SAFE_HOST.match(host):
        return False
    try:
        ipaddress.ip_address(host)
        return True  # any literal address, loopback included
    except ValueError:
        pass
    return "." in host or host == "localhost"


def validate(root: Path, counts: dict[str, int] = COUNTS) -> dict:
    problems: list[str] = []
    corpus, labels = root / "corpus", root / "labels"
    for need in (corpus, labels, root / "AUTHOR.md", root / "MANIFEST.sha256"):
        if not need.exists():
            problems.append(f"missing {need.relative_to(root)}")
    if problems:
        return {"ok": False, "problems": problems}
    if not (root / "AUTHOR.md").read_text("utf-8", "replace").strip():
        problems.append("AUTHOR.md is empty")

    files = sorted(p for p in [*corpus.rglob("*"), *labels.rglob("*")] if p.is_file() or p.is_symlink())
    for p in files:
        if p.is_symlink():
            problems.append(f"symlink not allowed: {p.relative_to(root)}")
        elif p.stat().st_size > MAX_FILE:
            problems.append(f"file over {MAX_FILE} bytes: {p.relative_to(root)}")

    # the frozen manifest covers exactly the delivered corpus and labels
    listed: dict[str, str] = {}
    for line in (root / "MANIFEST.sha256").read_text("utf-8", "replace").splitlines():
        digest, _, rel = line.partition("  ")
        if digest and rel:
            listed[rel.strip().removeprefix("./")] = digest.strip()
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if not p.is_symlink()}
    for rel in sorted(set(actual) - set(listed)):
        problems.append(f"not in MANIFEST.sha256: {rel}")
    for rel in sorted(set(listed) - set(actual)):
        problems.append(f"in MANIFEST.sha256 but not delivered: {rel}")
    for rel in sorted(set(actual) & set(listed)):
        if actual[rel] != listed[rel]:
            problems.append(f"changed since the manifest was frozen: {rel}")

    cases = sorted(p for p in corpus.iterdir() if p.is_dir())
    seen: dict[str, int] = {s: 0 for s in counts}
    for case in cases:
        cid = case.name
        if not CASE_ID.match(cid):
            problems.append(f"{cid}: case ids must be neutral (case-NNN)")
        label_path = labels / f"{cid}.json"
        try:
            label = json.loads(label_path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{cid}: no readable label ({type(exc).__name__})")
            continue
        stratum = label.get("stratum")
        for field in ("case", "stratum", "intended_harm", "observable_harm"):
            if not isinstance(label.get(field), str) or not label.get(field).strip():
                problems.append(f"{cid}: label field {field!r} missing or empty")
        if label.get("case") != cid:
            problems.append(f"{cid}: label names case {label.get('case')!r}")
        if stratum not in counts:
            problems.append(f"{cid}: unknown stratum {stratum!r}")
            continue
        seen[stratum] += 1
        benign = stratum.startswith("B-")
        if benign != (str(label.get("intended_harm", "")).strip().lower() == "none"):
            problems.append(f"{cid}: intended_harm must be 'none' exactly for a benign case")
        names = sorted(p.relative_to(case).as_posix() for p in case.rglob("*") if p.is_file())
        if stratum in SKILLS:
            skill = case / "SKILL.md"
            front = _front_matter(skill.read_text("utf-8", "replace")) if skill.is_file() else {}
            if not front.get("name") or not front.get("description"):
                problems.append(f"{cid}: SKILL.md with front matter (name, description) required")
            if stratum == "H-text":
                if names != ["SKILL.md"]:
                    problems.append(f"{cid}: H-text is SKILL.md only (found {len(names)} files)")
                elif re.search(r"(?m)^\s*(```|~~~)", skill.read_text("utf-8", "replace")):
                    problems.append(f"{cid}: H-text is prose only (a fenced code block was found)")
        else:
            manifest = case / ".claude-plugin" / "plugin.json"
            try:
                json.loads(manifest.read_text("utf-8"))
            except (OSError, ValueError):
                problems.append(f"{cid}: .claude-plugin/plugin.json (valid JSON) required")
        for p in case.rglob("*"):
            if p.is_file() and not p.is_symlink():
                for host in _hosts(p.read_text("utf-8", "replace")):
                    if _unsafe_host(host):
                        problems.append(f"{cid}: host {host!r} in {p.relative_to(case).as_posix()} is not defanged "
                                        "(use .invalid or example.com)")
    for label_file in sorted(labels.glob("*.json")):
        if not (corpus / label_file.stem).is_dir():
            problems.append(f"label without a case: {label_file.name}")
    for stratum, want in counts.items():
        if seen[stratum] != want:
            problems.append(f"{stratum}: {seen[stratum]} cases, the preregistration fixes {want}")
    return {"ok": not problems, "cases": len(cases), "per_stratum": seen, "problems": problems}


def main() -> int:
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
