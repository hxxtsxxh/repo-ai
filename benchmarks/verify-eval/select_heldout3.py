#!/usr/bin/env python3
"""Held-out-3 candidate selection (PROTOCOL.md Amendment 2), recorded.

For each quota, walk the ordered candidates and record a decision for each one:
- repository metadata: licence, archived, stars, default-branch head;
- whether it was used in an earlier set;
- for JS, the code-search query and its raw results.

Test configuration is read only to classify the runner (eligibility check
3). The engine under test is never run here.

    python select_heldout3.py > selection.json
"""

from __future__ import annotations

import json
import subprocess
import sys

PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "PSF-2.0", "0BSD", "Unlicense"}
PYTHON = ["pallets/itsdangerous", "python-humanize/humanize", "r1chardj0n3s/parse", "pytoolz/toolz",
          "mahmoud/boltons", "python-poetry/tomlkit", "astanin/python-tabulate", "pallets/markupsafe",
          "python-attrs/cattrs", "hynek/structlog", "pypa/packaging", "jquast/wcwidth",
          "python-jsonschema/jsonschema", "Delgan/loguru", "tox-dev/filelock", "hukkin/mdformat",
          "executablebooks/markdown-it-py", "jaraco/inflect"]
USED = {"cachetools", "markdown", "pyflakes", "simplejson", "tomli", "peewee", "pyfakefs", "elementpath",
        "genshi", "pathspec", "python-pathspec", "pony", "supervisor", "svgwrite", "oauthlib", "pydal", "bottle",
        "asn1crypto", "lark", "more-itertools", "pyasn1", "dnspython", "sqlglot", "typing_extensions",
        "geojson-vt", "webidl-conversions", "culori", "busboy", "simple-statistics", "cel-js",
        "primitive-geometry", "t-a-i", "marked", "decimal.js", "bignumber.js", "source-map"}


def gh(*args: str) -> object:
    out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"error": out.stderr.strip()[:200]}


def meta(full: str) -> dict:
    d = gh(f"repos/{full}")
    if not isinstance(d, dict) or "full_name" not in d:
        return {"repo": full, "error": str(d)[:200]}
    head = gh(f"repos/{full}/commits/{d['default_branch']}")
    licence = (d.get("license") or {}).get("spdx_id")
    return {"repo": d["full_name"], "licence": licence, "stars": d["stargazers_count"], "archived": d["archived"],
            "default_branch": d["default_branch"],
            "head": head.get("sha", "") if isinstance(head, dict) else "",
            "used_before": full.split("/")[1].lower() in {u.lower() for u in USED}}


def code_search(query: str) -> list[str]:
    d = gh("-X", "GET", "search/code", "-f", f"q={query}", "-f", "per_page=100")
    items = d.get("items", []) if isinstance(d, dict) else []
    return sorted({i["repository"]["full_name"] for i in items if i.get("path") == "package.json"})


def main() -> int:
    record: dict = {"python": [meta(r) for r in PYTHON]}
    for key, query in (("node_test", '"node --test" filename:package.json'),
                       ("vitest", '"vitest run" filename:package.json')):
        found = code_search(query)
        rows = [meta(r) for r in found]
        rows = [r for r in rows if "error" not in r]
        eligible = sorted((r for r in rows if not r["archived"] and r["stars"] >= 300
                           and r["licence"] in PERMISSIVE and not r["used_before"]),
                          key=lambda r: -r["stars"])
        record[key] = {"query": query, "results": found, "eligible_by_metadata": eligible}
    json.dump(record, sys.stdout, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
