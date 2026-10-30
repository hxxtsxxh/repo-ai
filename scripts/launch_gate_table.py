"""Render docs/launch/ACCEPTANCE.json as the gate table in docs/launch/LAUNCH_REPORT.md.

    python scripts/launch_gate_table.py           # rewrite the table between the markers
    python scripts/launch_gate_table.py --check   # exit 1 if the report's table is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "docs" / "launch" / "ACCEPTANCE.json"
REPORT = ROOT / "docs" / "launch" / "LAUNCH_REPORT.md"
BEGIN, END = "<!-- gate-table:begin -->", "<!-- gate-table:end -->"


def _cell(text: str | None, limit: int = 220) -> str:
    text = " ".join((text or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def table() -> str:
    data = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    rows = ["| Gate | Result | At | Limits / blocker |", "|---|---|---|---|"]
    for g in data["gates"]:
        note = g.get("blocker") or g.get("limitations") or ""
        if g.get("blocker") and g.get("limitations"):
            note = f"{g['limitations']} **Blocker:** {g['blocker']}"
        rows.append(f"| {g['id']} | **{g['result']}** | {g.get('code_sha') or '–'} | {_cell(note)} |")
    counts: dict[str, int] = {}
    for g in data["gates"]:
        counts[g["result"]] = counts.get(g["result"], 0) + 1
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    return "\n".join([BEGIN, f"Launch status in the registry: `{data['launch_status']}`. Counts: {summary}.", "",
                      *rows, END])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    text = REPORT.read_text(encoding="utf-8")
    if BEGIN in text:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _m: table(), text, flags=re.S)
    else:
        new = text.replace("GATE_TABLE", table())
    if args.check:
        if new != text:
            print("LAUNCH_REPORT gate table is stale: run python scripts/launch_gate_table.py", file=sys.stderr)
            return 1
        return 0
    REPORT.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
