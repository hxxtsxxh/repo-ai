#!/usr/bin/env python3
"""Held-out-4 candidate selection (PROTOCOL.md Amendment 3), recorded.

Records, for each ordered candidate of each quota, the repository metadata
(licence, archived, stars, default-branch head) and whether an earlier set
read it; for the JavaScript quotas, the code-search query, every result page,
and the eligibility-by-metadata list. Test configuration is read afterwards,
one candidate at a time in list order, only to apply eligibility checks 3-5
and 7 (the decisions are written to FREEZE.md). The engine under test is
never run here.

    python select_heldout4.py > results/heldout4/selection.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "PSF-2.0", "0BSD", "Unlicense"}
PY_DEPS = ["python-poetry/tomlkit", "astanin/python-tabulate", "pallets/markupsafe", "python-attrs/cattrs",
           "hynek/structlog", "pypa/packaging", "jquast/wcwidth", "python-jsonschema/jsonschema", "Delgan/loguru",
           "tox-dev/filelock", "hukkin/mdformat", "executablebooks/markdown-it-py", "jaraco/inflect"]
PY_STDLIB = ["jmespath/jmespath.py", "martinblech/xmltodict", "dbader/schedule", "grantjenks/python-sortedcontainers",
             "kjd/idna", "docopt/docopt", "chardet/chardet", "pyparsing/pyparsing", "tartley/colorama"]
QUERY = '"node --test" filename:package.json'


def gh(*args: str) -> object:
    out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"error": out.stderr.strip()[:200]}


def seen_in_heldout3() -> set[str]:
    """Every repository named in a held-out-3 selection record."""
    names: set[str] = set()

    def walk(x: object) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {"repo", "full_name"} and isinstance(v, str):
                    names.add(v.lower())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                if isinstance(v, str) and "/" in v and " " not in v:
                    names.add(v.lower())
                walk(v)
    for f in sorted((HERE / "results" / "heldout3").glob("selection-*.json")):
        walk(json.loads(f.read_text("utf-8")))
    return names


_CACHE: dict = {}


def _wait_for_quota() -> None:
    """Pause while the API quota is nearly spent: a repository whose
    metadata could not be read must not be dropped silently."""
    import time
    while True:
        d = gh("rate_limit")
        core = (d.get("resources") or {}).get("core") if isinstance(d, dict) else None
        if not core or core.get("remaining", 0) > 50:
            return
        time.sleep(max(5, int(core.get("reset", time.time() + 60)) - int(time.time()) + 5))


def meta(full: str, seen: set[str]) -> dict:
    """Repository metadata, cached in $VEV_SELECT_CACHE (resumable), with
    errors recorded rather than dropped."""
    import os
    path = os.environ.get("VEV_SELECT_CACHE")
    if path and not _CACHE and os.path.exists(path):
        _CACHE.update(json.load(open(path)))
    if full in _CACHE and "error" not in _CACHE[full]:
        row = dict(_CACHE[full])
        row["in_heldout3_records"] = row["repo"].lower() in seen
        return row
    _wait_for_quota()
    row = _meta(full, seen)
    _CACHE[full] = row
    if path:
        json.dump(_CACHE, open(path, "w"))
    return row


def _meta(full: str, seen: set[str]) -> dict:
    d = gh(f"repos/{full}")
    if not isinstance(d, dict) or "full_name" not in d:
        return {"repo": full, "error": str(d)[:200]}
    head = gh(f"repos/{full}/commits/{d['default_branch']}")
    return {"repo": d["full_name"], "licence": (d.get("license") or {}).get("spdx_id"),
            "stars": d["stargazers_count"], "archived": d["archived"], "default_branch": d["default_branch"],
            "head": head.get("sha", "") if isinstance(head, dict) else "",
            "in_heldout3_records": d["full_name"].lower() in seen}


def search_all(query: str) -> list[str]:
    found: set[str] = set()
    for page in range(1, 11):
        d = gh("-X", "GET", "search/code", "-f", f"q={query}", "-f", "per_page=100", "-f", f"page={page}")
        items = d.get("items", []) if isinstance(d, dict) else []
        found |= {i["repository"]["full_name"] for i in items if i.get("path") == "package.json"}
        if len(items) < 100:
            break
    return sorted(found)


def search_imports(language: str) -> list[str]:
    """Amendment 3b: repositories whose test files import node:test."""
    found: set[str] = set()
    query = f'"from \'node:test\'" language:{language}'
    import time
    for page in range(1, 11):
        for _attempt in range(10):  # the code-search limit is 10 requests a minute: wait, never truncate
            d = gh("-X", "GET", "search/code", "-f", f"q={query}", "-f", "per_page=100", "-f", f"page={page}")
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


def amendment_3b() -> dict:
    seen = seen_in_heldout3()
    out: dict = {}
    for language in ("JavaScript", "TypeScript"):
        found = search_imports(language)
        every = [meta(x, seen) for x in found]
        rows = [r for r in every if "error" not in r]
        out[language] = {"query": f"\"from 'node:test'\" language:{language}", "results": found,
                         "metadata_errors": sorted(r["repo"] for r in every if "error" in r),
                         "eligible_by_metadata": sorted(
                             (r for r in rows if not r["archived"] and r["stars"] >= 50 and r["licence"] in PERMISSIVE
                              and not r["in_heldout3_records"]), key=lambda r: -r["stars"])}
    return out


def main() -> int:
    if "--amendment-3b" in sys.argv:
        json.dump(amendment_3b(), sys.stdout, indent=1)
        return 0
    seen = seen_in_heldout3()
    record: dict = {"python_deps": [meta(r, seen) for r in PY_DEPS],
                    "python_stdlib": [meta(r, seen) for r in PY_STDLIB]}
    found = search_all(QUERY)
    rows = [meta(r, seen) for r in found]
    rows = [r for r in rows if "error" not in r]
    eligible = sorted((r for r in rows if not r["archived"] and r["stars"] >= 50 and r["licence"] in PERMISSIVE
                       and not r["in_heldout3_records"]), key=lambda r: -r["stars"])
    record["node_test"] = {"query": QUERY, "results": found, "eligible_by_metadata": eligible}
    json.dump(record, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
