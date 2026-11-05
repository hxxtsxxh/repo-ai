"""The evidence graph: typed edges with provenance over the index.

Every edge says *how* it is known:

========== ===========================================================
proof      meaning
========== ===========================================================
parser     an AST/regex parser read it from source (definitions, imports)
resolver   an import was resolved to a file in this repository
manifest   a package manifest declares it (components, dependencies)
git        commit history shows it (co-change)
naming     a naming convention suggests it (test ↔ source by file name)
pattern    a framework pattern matched (routes)
heuristic  a textual match suggests it (symbol uses, API-path literals)
========== ===========================================================

Only parser/resolver/manifest/git edges are *proven*. Naming, pattern and
heuristic edges are labelled as such everywhere they are shown. Nothing here
is a second database: edges are assembled on demand from the index tables,
so they are invalidated by the same incremental update that changes them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

PROVEN = frozenset({"parser", "resolver", "manifest", "git"})

# Names too generic to count as evidence that one file uses another.
_GENERIC = frozenset(
    "get set run main init new add put post delete update create read write load save "
    "open close start stop test setup teardown call apply build make parse format value "
    "values data item items name names type types id key keys config default error errors "
    "result results self cls args kwargs app api log logger util utils helper helpers".split())
_IMPORT_LINE = re.compile(r"^\s*(?:import|from|export\s+\*?\s*from|#include|using|require)\b|"
                          r"^\s*(?:const|let|var)\s+[\w{}\s,]+=\s*require\(")
_URL_LITERAL = re.compile(r"""["'`](/(?:[A-Za-z0-9_.~\-]+|\{[^}/]{1,40}\}|:[A-Za-z_]\w*|\$\{[^}]{1,40}\})"""
                          r"""(?:/(?:[A-Za-z0-9_.~\-]+|\{[^}/]{1,40}\}|:[A-Za-z_]\w*|\$\{[^}]{1,40}\}))*/?)["'`]""")
_STATIC_SUFFIX = re.compile(r"\.(?:js|mjs|css|png|jpe?g|gif|svg|ico|html?|map|json|txt|md|woff2?)$",
                            re.I)


# --------------------------------------------------------------------------
# extraction (run by the analyser)
# --------------------------------------------------------------------------
def compute_refs(texts: dict[str, str], targets: dict[str, set[str]],
                 names_by_path: dict[str, list[str]]) -> list[tuple[str, str, str, int]]:
    """(src, dst, symbol, line) for each symbol of an imported file that the
    importer mentions outside its import lines (first mention per symbol)."""
    rows: list[tuple[str, str, str, int]] = []
    for src in sorted(texts):
        text = texts[src]
        owners: dict[str, list[str]] = defaultdict(list)
        for dst in sorted(targets.get(src, ())):
            for name in names_by_path.get(dst, ()):
                if len(name) >= 3 and name.lower() not in _GENERIC and not name.startswith("__"):
                    owners[name].append(dst)
        if not owners:
            continue
        pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in
                                               sorted(owners, key=len, reverse=True)) + r")\b")
        seen: set[str] = set()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _IMPORT_LINE.match(line):
                continue
            for match in pattern.finditer(line):
                name = match.group(1)
                if name in seen:
                    continue
                seen.add(name)
                for dst in owners[name]:
                    rows.append((src, dst, name, lineno))
            if len(seen) == len(owners):
                break
    return rows


def extract_url_literals(path: str, text: str, limit: int = 80) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _URL_LITERAL.finditer(line):
            url = match.group(1)
            if len(url) < 2 or len(url) > 160 or _STATIC_SUFFIX.search(url) or url.count("/") < 1:
                continue
            if url in {"/", "//"}:
                continue
            rows.append((path, url, lineno))
            if len(rows) >= limit:
                return rows
    return rows


def normalize_route(path: str) -> str:
    """'/orders/{id}', '/orders/:id', '/orders/<int:id>', `/orders/${id}` -> '/orders/*'."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    path = re.sub(r"\{[^}]*\}|<[^>]*>|:[A-Za-z_]\w*|\$\{[^}]*\}|\*+", "*", path)
    return path.lower()


def route_matches(literal: str, pattern: str) -> bool:
    a = normalize_route(literal).split("/")
    b = normalize_route(pattern).split("/")
    if len(a) != len(b):
        return False
    return all(x == y or x == "*" or y == "*" for x, y in zip(a, b, strict=True))


# --------------------------------------------------------------------------
# edges
# --------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class Edge:
    src: str
    dst: str
    kind: str
    proof: str
    confidence: float
    evidence: str = ""

    @property
    def proven(self) -> bool:
        return self.proof in PROVEN

    def to_json(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "kind": self.kind, "proof": self.proof,
                "proven": self.proven, "confidence": self.confidence, "evidence": self.evidence}


def file_edges(index, path: str, *, routes: list | None = None,
               file_rows: dict[str, Any] | None = None) -> list[Edge]:
    """Every edge touching one file, both directions."""
    edges: list[Edge] = []
    row = (file_rows or {}).get(path) or index.get_file(path)
    if row is not None and row["component"]:
        edges.append(Edge(f"component:{row['component']}", path, "contains", "manifest", 1.0))
    for sym in index.symbols_for(path):
        if not sym["parent"]:
            edges.append(Edge(path, f"symbol:{sym['name']}", "defines", "parser", 1.0,
                              f"{path}:{sym['line']}"))
    for imp in index.imports_of(path):
        if imp["resolved_path"]:
            edges.append(Edge(path, imp["resolved_path"], "imports", "resolver", 1.0,
                              f"import {imp['raw_target'].lstrip('?')}"))
    for importer in index.importers_of(path, limit=200):
        edges.append(Edge(importer, path, "imports", "resolver", 1.0))
    for link in index.tests_for(path):
        proof = "parser" if link["evidence"] == "import" else "naming"
        edges.append(Edge(link["test_path"], path, "tests", proof,
                          0.95 if proof == "parser" else 0.6, link["evidence"]))
    for src in index.sources_tested_by(path):
        edges.append(Edge(path, src, "tests", "parser", 0.95))
    for peer in index.coupled_with(path, limit=8):
        edges.append(Edge(path, peer, "co_changes", "git", 0.7, "changed together in history"))
    for ref in index.refs_from(path):
        edges.append(Edge(path, ref["dst_path"], "uses", "heuristic", 0.7,
                          f"{path}:{ref['line']} mentions {ref['symbol']}"))
    for ref in index.refs_to(path):
        edges.append(Edge(ref["src_path"], path, "uses", "heuristic", 0.7,
                          f"{ref['src_path']}:{ref['line']} mentions {ref['symbol']}"))
    all_routes = routes if routes is not None else index.routes(5000)
    for route in all_routes:
        if route["file"] == path:
            edges.append(Edge(path, f"route:{route['method']} {route['path_pattern']}", "exposes",
                              "pattern", 0.85, f"{path}:{route['line']}"))
    for lit in index.url_refs(path):
        for route in all_routes:
            if route["file"] != path and route_matches(lit["url"], route["path_pattern"]):
                edges.append(Edge(path, f"route:{route['method']} {route['path_pattern']}",
                                  "consumes_api", "heuristic", 0.6,
                                  f"{path}:{lit['line']} \"{lit['url']}\" → {route['file']}"))
    return _dedupe(edges)


def node_edges(index, node: str) -> list[Edge]:
    if node.startswith("symbol:"):
        name = node[len("symbol:"):]
        out = [Edge(r["path"], node, "defines", "parser", 1.0, f"{r['path']}:{r['line']}")
               for r in index.find_symbol(name, limit=40)]
        for row in index.conn.execute("SELECT src_path, dst_path, line FROM refs WHERE symbol=? "
                                      "ORDER BY src_path LIMIT 200", (name,)):
            out.append(Edge(row["src_path"], row["dst_path"], "uses", "heuristic", 0.7,
                            f"{row['src_path']}:{row['line']} mentions {name}"))
        return _dedupe(out)
    if node.startswith("route:"):
        label = node[len("route:"):]
        method, _, pattern = label.partition(" ")
        out = []
        for route in index.routes(5000):
            if route["path_pattern"] == pattern and route["method"] == method:
                out.append(Edge(route["file"], node, "exposes", "pattern", 0.85,
                                f"{route['file']}:{route['line']}"))
        for lit in index.url_refs():
            if route_matches(lit["url"], pattern):
                out.append(Edge(lit["path"], node, "consumes_api", "heuristic", 0.6,
                                f"{lit['path']}:{lit['line']} \"{lit['url']}\""))
        return _dedupe(out)
    if node.startswith("component:"):
        name = node[len("component:"):]
        return [Edge(node, r["path"], "contains", "manifest", 1.0)
                for r in index.conn.execute("SELECT path FROM files WHERE component=? "
                                            "ORDER BY path LIMIT 500", (name,))]
    return file_edges(index, node)


def neighborhood(index, start: str, depth: int = 1, kinds: Iterable[str] = (),
                 limit: int = 120) -> list[Edge]:
    wanted = set(kinds)
    routes = index.routes(5000)
    seen_nodes = {start}
    frontier = [start]
    out: list[Edge] = []
    for _ in range(max(depth, 1)):
        nxt: list[str] = []
        for node in frontier:
            edges = node_edges(index, node) if ":" in node.split("/")[0] else \
                file_edges(index, node, routes=routes)
            for edge in edges:
                if wanted and edge.kind not in wanted:
                    continue
                out.append(edge)
                for other in (edge.src, edge.dst):
                    if other not in seen_nodes and not other.startswith(("symbol:", "route:",
                                                                         "component:")):
                        seen_nodes.add(other)
                        nxt.append(other)
                if len(out) >= limit:
                    return _dedupe(out)
        frontier = nxt
    return _dedupe(out)


def _dedupe(edges: list[Edge]) -> list[Edge]:
    best: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        key = (edge.src, edge.dst, edge.kind)
        if key not in best or edge.confidence > best[key].confidence:
            best[key] = edge
    return sorted(best.values(), key=lambda e: (e.kind, e.src, e.dst))


def render(edges: list[Edge], start: str) -> str:
    if not edges:
        return f"no edges for {start} (is it indexed? try `repo-ai symbol` or `repo-ai search`)"
    lines = [f"evidence graph around {start} ({len(edges)} edges; "
             "proof: parser/resolver/manifest/git = proven, naming/pattern/heuristic = inferred)"]
    by_kind: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        by_kind[edge.kind].append(edge)
    for kind in sorted(by_kind):
        lines.append(f"  {kind}:")
        for edge in by_kind[kind][:30]:
            mark = "" if edge.proven else f" [{edge.proof}]"
            ev = f" — {edge.evidence}" if edge.evidence else ""
            lines.append(f"    {edge.src} → {edge.dst}{mark}{ev}")
        if len(by_kind[kind]) > 30:
            lines.append(f"    … {len(by_kind[kind]) - 30} more")
    return "\n".join(lines)
