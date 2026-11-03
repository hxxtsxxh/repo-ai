"""How passing tournament candidates differ: in source only (formatting, comments) or in code that can compute
differently, and where. No candidate code is run here; it is parsed.

Each candidate's files are rebuilt from the frozen commit with `shortlist`'s reconstruction (scratch directory
confined from any enclosing repository; created, deleted, renamed, mode-changed or binary files, and a diff that does
not change every file it names, give no reconstruction). Two candidates are IDENTICAL when the rebuilt files are the
same bytes, COSMETIC when every file is byte-identical or a Python file with the same syntax tree
(`shortlist.code_identity`: comments, formatting and line positions ignored; strict UTF-8; a file with a coding cookie
or that does not parse counts by its bytes), so a non-Python file changed the same way in both does not hide it,
SUBSTANTIVE otherwise (the definitions that differ
are named), and UNKNOWN when either cannot be rebuilt. COSMETIC means no difference in what the code computes, except code
that reads its own source or line numbers (tracebacks, `inspect`, logging) or compile-time warnings.
"""
from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .shortlist import _post_images, code_fingerprint, code_identity, diff_stats


def _definitions(text: bytes) -> dict[str, str] | None:
    """Qualified name -> syntax tree of each function and class (methods as Class.method; a class's own entry is its
    bases, keywords, decorators and non-method body) and of the remaining module-level code."""
    try:
        module = ast.parse(text.decode("utf-8"))
        out: dict[str, str] = {}
        rest: list[ast.stmt] = []

        def walk(nodes: Sequence[ast.stmt], prefix: str) -> None:
            def key(name: str) -> str:
                # a property setter, singledispatch `_`, an overload: keep each one, numbered by position (an extra
                # same-named definition earlier in one candidate shifts the later numbers: over-inclusive, never
                # missing a place)
                n, k = name, 1
                while n in out:
                    k += 1
                    n = f"{name}#{k}"
                return n

            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[key(prefix + node.name)] = ast.dump(node, include_attributes=False)
                elif isinstance(node, ast.ClassDef):
                    methods: list[ast.stmt] = [n for n in node.body
                                               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    header = [*node.bases, *node.keywords, *node.decorator_list,
                              *(n for n in node.body if n not in methods)]
                    name = key(prefix + node.name)
                    out[name] = "|".join(ast.dump(n, include_attributes=False) for n in header)
                    walk(methods, name + ".")
                elif not prefix:
                    rest.append(node)
        walk(module.body, "")
        out["<module level>"] = ast.dump(ast.Module(body=rest, type_ignores=[]), include_attributes=False)
        return out
    except (SyntaxError, UnicodeDecodeError, ValueError, RecursionError, MemoryError):
        return None


def _where(a: dict[str, bytes], b: dict[str, bytes]) -> list[str]:
    where: list[str] = []
    for rel in sorted(a):
        if a[rel] == b[rel]:
            continue
        same_tree = code_fingerprint({rel: a[rel]})
        if same_tree is not None and same_tree == code_fingerprint({rel: b[rel]}):
            continue  # this file differs only in comments or formatting
        da = _definitions(a[rel]) if rel.endswith(".py") else None
        db = _definitions(b[rel]) if rel.endswith(".py") else None
        if da is None or db is None:
            where.append(rel)
            continue
        names = sorted(n for n in set(da) | set(db) if da.get(n) != db.get(n))
        where += [f"{rel}:{n}" for n in names] or [rel]  # e.g. reordered definitions: the file itself
    return where


def compare(root: Path, base: str, diffs: dict[str, str]) -> dict[str, Any]:
    """`diffs`: candidate id -> diff from the frozen commit `base`, for passing candidates in the tournament's order.
    Returns pairwise differences and groups of candidates that are identical or cosmetic variants of each other."""
    images: dict[str, dict[str, bytes] | None] = {}
    prints: dict[str, str | None] = {}
    for cid, diff in diffs.items():
        try:
            images[cid] = _post_images(root, base, diff, diff_stats(diff)["files"])
        except Exception:  # noqa: BLE001 - a rebuild that fails makes no claim; it never loses the comparison
            images[cid] = None
        rebuilt = images[cid]
        prints[cid] = code_identity(rebuilt) if rebuilt is not None else None
    ids = list(diffs)
    pairs = []
    group_of: dict[str, str] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ia, ib = images[a], images[b]
            if ia is None or ib is None:
                kind, where = "UNKNOWN", ["a candidate's files could not be rebuilt exactly from the frozen commit"]
            elif set(ia) != set(ib):
                kind, where = "SUBSTANTIVE", sorted(set(ia) ^ set(ib))
            elif ia == ib:
                kind, where = "IDENTICAL", []
            elif prints[a] is not None and prints[a] == prints[b]:
                kind, where = "COSMETIC", []
            else:
                kind, where = "SUBSTANTIVE", _where(ia, ib)
            pairs.append({"candidates": [a, b], "difference": kind, "where": where})
            if kind in ("IDENTICAL", "COSMETIC") and b not in group_of:
                group_of[b] = group_of.get(a, a)
    groups: dict[str, list[str]] = {}
    for cid in ids:
        groups.setdefault(group_of.get(cid, cid), []).append(cid)
    return {"pairs": pairs, "groups": list(groups.values()),
            "rule": "IDENTICAL: same rebuilt bytes; COSMETIC: every file byte-identical or the same Python syntax tree "
                    "(shortlist.code_identity); "
                    "SUBSTANTIVE: otherwise, definitions named; UNKNOWN: not rebuilt exactly"}
