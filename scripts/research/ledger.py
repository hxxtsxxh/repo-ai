#!/usr/bin/env python3
"""Evidence ledger for inspiration-to-capability research (development only).

The ledger is one JSON file holding:
- sources: posts, videos, repos and threads, with what was actually observed;
- technologies: what the sources name, linked back to every source;
- dispositions and integration status.

This tool validates it and renders the Markdown tables a research report
embeds. It is not part of the repo-ai package and never touches the network.

    python scripts/research/ledger.py new  LEDGER.json URL [URL ...]
    python scripts/research/ledger.py check LEDGER.json
    python scripts/research/ledger.py render LEDGER.json [--into REPORT.md]

`render --into` replaces only the text between `<!-- ledger:begin -->` and
`<!-- ledger:end -->`; the hand-written analysis around it is kept.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "repo-ai.research-ledger/1"
STATUSES = {"INSPECTED", "PARTIALLY_VERIFIED", "INACCESSIBLE", "UNREVIEWED"}
FORMATS = {"video", "carousel", "image", "text", "repository", "unknown"}
CONFIDENCE = {"directly-observed", "externally-corroborated", "unverified"}
DISPOSITIONS = {
    "A": "native capability", "B": "optional integration or adapter", "C": "curated on-demand skill",
    "D": "experimental research candidate", "E": "reject (redundant or harmful)",
    "X": "out of scope (not a developer-tooling capability)",
}
INTEGRATION = {"implemented", "implemented-pending-review", "needs-session-a", "needs-authorization",
               "deferred", "rejected", "documented-only", "not-started"}
BEGIN, END = "<!-- ledger:begin -->", "<!-- ledger:end -->"


def new(path: Path, urls: list[str]) -> dict[str, Any]:
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}")
    data = {"schema": SCHEMA, "title": "", "collected": "", "method": "", "sources": [
        {"id": f"S{i:02d}", "url": u, "status": "UNREVIEWED", "format": "unknown", "creator": "",
         "published": "", "caption": "", "observations": [], "claims": [], "technologies": [],
         "unavailable": "", "notes": ""} for i, u in enumerate(urls, 1)], "technologies": []}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def check(data: dict[str, Any]) -> list[str]:
    """Problems that would make the ledger mislead a reader."""
    errs: list[str] = []
    if data.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    tech_ids = {t.get("id") for t in data.get("technologies", [])}
    cited: dict[str, set[str]] = {}
    seen: set[str] = set()
    for s in data.get("sources", []):
        sid = s.get("id", "?")
        if sid in seen:
            errs.append(f"{sid}: duplicate source id")
        seen.add(sid)
        status = s.get("status")
        if status not in STATUSES:
            errs.append(f"{sid}: status {status!r} not in {sorted(STATUSES)}")
        if s.get("format") not in FORMATS:
            errs.append(f"{sid}: format {s.get('format')!r} not in {sorted(FORMATS)}")
        obs = s.get("observations") or []
        if status == "INSPECTED":
            if not obs:
                errs.append(f"{sid}: INSPECTED needs at least one observation of the media itself")
            for o in obs:
                if not (o.get("at") and o.get("seen")):
                    errs.append(f"{sid}: every observation needs `at` (timestamp/slide) and `seen`")
        if status == "INACCESSIBLE" and not s.get("unavailable"):
            errs.append(f"{sid}: INACCESSIBLE must say what could not be obtained (`unavailable`)")
        if status == "INACCESSIBLE" and obs:
            errs.append(f"{sid}: INACCESSIBLE cannot carry media observations")
        if status == "PARTIALLY_VERIFIED" and not s.get("unavailable"):
            errs.append(f"{sid}: PARTIALLY_VERIFIED must say what remains unavailable")
        for c in s.get("claims") or []:
            if c.get("confidence") not in CONFIDENCE:
                errs.append(f"{sid}: claim {c.get('claim', '')[:40]!r} needs confidence in {sorted(CONFIDENCE)}")
        for t in s.get("technologies") or []:
            if t not in tech_ids:
                errs.append(f"{sid}: names technology {t!r} that has no technology entry")
            cited.setdefault(t, set()).add(sid)
    for t in data.get("technologies", []):
        tid = t.get("id", "?")
        if not cited.get(tid):
            errs.append(f"{tid}: no source mentions it (every technology must trace to a source)")
        if t.get("disposition") not in DISPOSITIONS:
            errs.append(f"{tid}: disposition must be one of {sorted(DISPOSITIONS)}")
        if not t.get("reason"):
            errs.append(f"{tid}: every disposition needs a reason")
        if t.get("integration") not in INTEGRATION:
            errs.append(f"{tid}: integration status must be one of {sorted(INTEGRATION)}")
        if t.get("repo") and not re.fullmatch(r"[0-9a-f]{40}", str(t.get("commit", ""))):
            if not t.get("commit_note"):
                errs.append(f"{tid}: a repository finding needs a 40-hex `commit` (or `commit_note` why not)")
        if t.get("integration", "").startswith("implemented") and not t.get("evidence"):
            errs.append(f"{tid}: 'implemented' needs `evidence` (tests, measurements)")
    return errs


def _cell(value: Any) -> str:
    text = ", ".join(value) if isinstance(value, list) else str(value or "—")
    return text.replace("|", "\\|").replace("\n", " ") or "—"


def render(data: dict[str, Any]) -> str:
    sources = data.get("sources", [])
    techs = {t["id"]: t for t in data.get("technologies", [])}
    cited: dict[str, list[str]] = {}
    for s in sources:
        for t in s.get("technologies") or []:
            cited.setdefault(t, []).append(s["id"])
    out = ["### Source status", "", "| # | Post | Status | Format | Creator | Published | Technologies |",
           "|---|---|---|---|---|---|---|"]
    for s in sources:
        out.append(f"| {s['id']} | [{_cell(s.get('post_id') or s['url'])}]({s['url']}) | **{s['status']}** | "
                   f"{_cell(s.get('format'))} | {_cell(s.get('creator'))} | {_cell(s.get('published'))} | "
                   f"{_cell([techs[t]['name'] for t in s.get('technologies') or [] if t in techs])} |")
    out += ["", "### Cross-post technology index", "",
            "| Technology | Mentioned in | Disposition | Integration | Licence | Source |",
            "|---|---|---|---|---|---|"]
    for tid, t in sorted(techs.items(), key=lambda kv: (-len(cited.get(kv[0], [])), kv[1]["name"].lower())):
        src = f"[{t['repo']}](https://github.com/{t['repo']})" + (
            f" @ `{t['commit'][:12]}`" if t.get("commit") else "") if t.get("repo") else _cell(t.get("url"))
        out.append(f"| {_cell(t['name'])} | {_cell(cited.get(tid, []))} | {t['disposition']} "
                   f"({DISPOSITIONS.get(t['disposition'], '?')}) | {_cell(t.get('integration'))} | "
                   f"{_cell(t.get('license'))} | {src} |")
    counts: dict[str, int] = {}
    for s in sources:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    out += ["", "Status totals: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + "."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("ledger", type=Path)
    p.add_argument("urls", nargs="+")
    p = sub.add_parser("check")
    p.add_argument("ledger", type=Path)
    p = sub.add_parser("render")
    p.add_argument("ledger", type=Path)
    p.add_argument("--into", type=Path, help="replace the marked block in this Markdown file")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        new(args.ledger, args.urls)
        print(f"wrote {args.ledger}")
        return 0
    data = json.loads(args.ledger.read_text("utf-8"))
    errs = check(data)
    if args.cmd == "check" or errs:
        for e in errs:
            print(f"ledger: {e}", file=sys.stderr)
        if errs:
            return 1
        print(f"ledger ok: {len(data.get('sources', []))} sources, {len(data.get('technologies', []))} technologies")
        return 0
    text = render(data)
    if args.into:
        doc = args.into.read_text("utf-8")
        if doc.count(BEGIN) != 1 or doc.count(END) != 1:
            raise SystemExit(f"{args.into} needs exactly one {BEGIN} ... {END} block")
        head, rest = doc.split(BEGIN, 1)
        tail = rest.split(END, 1)[1]
        args.into.write_text(head + BEGIN + "\n" + text + END + tail, encoding="utf-8")
        print(f"updated {args.into}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
