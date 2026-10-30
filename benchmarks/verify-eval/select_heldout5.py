#!/usr/bin/env python3
"""Held-out-5 candidate selection (PROTOCOL.md Amendments 4 and 4a), recorded.

Run only after FREEZE.md records the engine freeze. Records, for each
ordered candidate of each quota:
- repository metadata (licence, archived, stars, default-branch head);
- whether it is excluded by check 8 (named in any earlier selection record,
  a corpus project, a task base).

For the JavaScript and TypeScript quotas it also records the code-search
query, every result and the eligibility-by-metadata list, in star order.
Test configuration is read afterwards, one candidate at a time in list order,
only to apply eligibility checks 3-5 and 7. Every read and its decision is
written to FREEZE.md and `results/heldout5/reads.json`. The engine under
test is never run here.

    VEV_SELECT_CACHE=... python select_heldout5.py > results/heldout5/selection.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import select_heldout4 as S4  # noqa: E402  (metadata and rate-limit helpers, unchanged)

PY_DEPS = ["marshmallow-code/marshmallow", "python-attrs/attrs", "pytest-dev/pluggy", "dateutil/dateutil",
           "tqdm/tqdm", "Textualize/rich", "simonw/sqlite-utils", "theskumar/python-dotenv",
           "python-semver/python-semver", "Pylons/waitress"]
PY_STDLIB = ["andialbrecht/sqlparse", "python-hyper/h11", "pallets/click", "benjaminp/six"]
JS_QUERY = "\"require('node:test')\" language:JavaScript"
TS_QUERY = '"--experimental-strip-types" filename:package.json'
TASK_BASES = ("benchmarks/sealed-v2/bases", "benchmarks/tasks/bases")


def seen_before() -> set[str]:
    """Check 8: every repository any earlier set named or examined."""
    names: set[str] = set()

    def walk(x: object) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {"repo", "full_name"} and isinstance(v, str):
                    names.add(v.lower())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                if isinstance(v, str) and "/" in v and " " not in v and not v.startswith(("http", "/")):
                    names.add(v.lower())
                walk(v)
    for folder in ("heldout3", "heldout4"):
        for f in sorted((HERE / "results" / folder).glob("selection*.json")):
            walk(json.loads(f.read_text("utf-8")))
    for proj in json.loads((HERE / "corpus.json").read_text("utf-8"))["projects"].values():
        url = str(proj.get("url") or "")
        if "github.com/" in url:
            names.add(url.split("github.com/", 1)[1].strip("/").lower())
    return names


def task_base_names() -> set[str]:
    root = HERE.parent.parent
    out: set[str] = set()
    for rel in TASK_BASES:
        d = root / rel
        if d.is_dir():
            out |= {p.name.lower().split("-", 1)[-1] for p in d.iterdir()}
    return out


def search(query: str) -> list[str]:
    found: set[str] = set()
    for page in range(1, 11):
        for _attempt in range(10):  # code search: 10 requests a minute; wait, never truncate
            d = S4.gh("-X", "GET", "search/code", "-f", f"q={query}", "-f", "per_page=100", "-f", f"page={page}")
            if isinstance(d, dict) and "items" in d:
                break
            time.sleep(65)
        else:
            raise SystemExit(f"code search failed for page {page}: {d}")
        items = d["items"]
        found |= {i["repository"]["full_name"] for i in items}
        if len(items) < 100:
            break
        time.sleep(7)
    return sorted(found)


def main() -> int:
    seen = seen_before()
    bases = task_base_names()

    def row(full: str) -> dict:
        r = S4.meta(full, seen)
        if "error" not in r:
            r["excluded_check8"] = r["repo"].lower() in seen or r["repo"].split("/")[-1].lower() in bases
        return r
    record: dict = {"seen_before": len(seen), "task_bases": sorted(bases),
                    "python_deps": [row(r) for r in PY_DEPS], "python_stdlib": [row(r) for r in PY_STDLIB]}
    for key, query in (("javascript", JS_QUERY), ("typescript", TS_QUERY)):
        found = search(query)
        rows = [row(r) for r in found]
        record[key] = {"query": query, "results": found,
                       "metadata_errors": sorted(r["repo"] for r in rows if "error" in r),
                       "eligible_by_metadata": sorted(
                           (r for r in rows if "error" not in r and not r["archived"] and r["stars"] >= 50
                            and r["licence"] in S4.PERMISSIVE and not r["excluded_check8"]),
                           key=lambda r: (-r["stars"], r["repo"].lower()))}
    json.dump(record, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
