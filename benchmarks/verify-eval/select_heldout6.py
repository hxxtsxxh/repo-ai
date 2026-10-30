#!/usr/bin/env python3
"""Held-out-6 candidate selection (PROTOCOL.md Amendment 5), recorded.

Run only after FREEZE.md records the held-out-6 freeze. Records, per quota,
every ordered candidate's repository metadata (licence, archived, stars,
default-branch head) and whether check 8 excludes it (named in any earlier
selection record, a corpus project or a task base). For the code-search
quotas it records each query, every result, and the eligibility-by-metadata
list in star order, query by query.

Test configuration is read afterwards, one candidate at a time in list
order, only to apply checks 3-5 and 7; each read and decision goes to
FREEZE.md and `results/heldout6/reads.json`. The engine under test is never
run here.

    VEV_SELECT_CACHE=... python select_heldout6.py > results/heldout6/selection.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import select_heldout4 as S4  # noqa: E402  (metadata and rate-limit helpers, unchanged)
import select_heldout5 as S5  # noqa: E402  (code search and task bases, unchanged)

PY_DEPS = ["jpadilla/pyjwt", "Kludex/python-multipart", "prettytable/prettytable", "sloria/environs",
           "python-jsonschema/referencing", "scrapy/parsel", "scrapy/w3lib", "pyca/service-identity",
           "jaraco/keyring", "Pylons/webob"]
PY_UNITTEST = ["mkdocs/mkdocs", "python-websockets/websockets", "stefankoegl/python-json-pointer",
               "stefankoegl/python-json-patch", "gruns/icecream", "google/textfsm", "ronaldoussoren/altgraph",
               "amoffat/sh", "python/mypy_extensions", "wbond/oscrypto"]
PY_LARGE = ["networkx/networkx", "pygments/pygments", "python-babel/babel", "pallets/werkzeug",
            "sqlalchemy/alembic", "sphinx-doc/sphinx"]
QUERIES = {
    "javascript": ['"describe, it" "node:test" language:JavaScript',
                   '"node:assert" "node:test" language:JavaScript'],
    "typescript": ['"describe, it" "node:test" language:TypeScript',
                   '"node:assert" "node:test" language:TypeScript'],
    "control": ['"testEnvironment" filename:jest.config.js',
                '"defineConfig" "test" filename:vitest.config.ts'],
}


def seen_before() -> set[str]:
    """Check 8: every repository any earlier set named or examined (held-out-3
    to held-out-5 records, the corpus)."""
    names = S5.seen_before()

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
    for f in sorted((HERE / "results" / "heldout5").glob("*.json")):
        walk(json.loads(f.read_text("utf-8")))
    return names


def main() -> int:
    seen = seen_before()
    bases = S5.task_base_names()

    def row(full: str) -> dict:
        r = S4.meta(full, seen)
        if "error" not in r:
            r["excluded_check8"] = r["repo"].lower() in seen or r["repo"].split("/")[-1].lower() in bases
        return r
    record: dict = {"seen_before": len(seen), "task_bases": sorted(bases),
                    "python_deps": [row(r) for r in PY_DEPS], "python_unittest": [row(r) for r in PY_UNITTEST],
                    "python_large": [row(r) for r in PY_LARGE]}
    for key, queries in QUERIES.items():
        record[key] = []
        for query in queries:
            found = S5.search(query)
            rows = [row(r) for r in found]
            record[key].append({
                "query": query, "results": found,
                "metadata_errors": sorted(r["repo"] for r in rows if "error" in r),
                "eligible_by_metadata": sorted(
                    (r for r in rows if "error" not in r and not r["archived"] and r["stars"] >= 50
                     and r["licence"] in S4.PERMISSIVE and not r["excluded_check8"]),
                    key=lambda r: (-r["stars"], r["repo"].lower()))})
    json.dump(record, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
