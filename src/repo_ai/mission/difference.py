"""How passing tournament candidates differ: in source only (formatting, comments) or in code that can behave
differently, and where. No candidate code is run here; it is parsed.

Each candidate's diff is applied, in a temporary directory, to the frozen commit's copies of the files it touches.
Two candidates are COSMETIC variants when they touch the same files and every file is byte-identical or, for Python,
parses to the same syntax tree (formatting, comments and line breaks differ; names, literals, docstrings and order do
not). Anything else is SUBSTANTIVE: the frozen tests pass on both, so they do not decide between them, and the
definitions that differ are named so a developer can write the test that does.
"""
from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .. import gitbin

_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)


def changed_files(diff: str) -> list[str]:
    return sorted({b for _, b in _DIFF_FILE.findall(diff)} | {a for a, _ in _DIFF_FILE.findall(diff)})


def _after(root: Path, base: str, diff: str) -> dict[str, str | None] | None:
    """The touched files after the diff (None: deleted); None when the diff does not apply to the frozen commit."""
    files = changed_files(diff)
    with tempfile.TemporaryDirectory(prefix="repo-ai-difference-") as tmp:
        work = Path(tmp)
        for rel in files:
            if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
                return None
            shown = subprocess.run([gitbin.git(), "show", f"{base}:{rel}"], cwd=root, capture_output=True,
                                   timeout=30, check=False)
            if shown.returncode == 0:
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                (work / rel).write_bytes(shown.stdout)
        patch = work.parent / (work.name + ".patch")
        try:
            patch.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
            with tempfile.TemporaryDirectory(prefix="repo-ai-git-home-") as home:  # no user git configuration
                applied = subprocess.run([gitbin.git(), "apply", str(patch)], cwd=work, capture_output=True,
                                         timeout=30, check=False, env=gitbin.no_user_config_env(home))
            if applied.returncode != 0:
                return None
        finally:
            patch.unlink(missing_ok=True)
        return {rel: (work / rel).read_text("utf-8", "replace") if (work / rel).is_file() else None for rel in files}


def _tree(text: str) -> str | None:
    try:
        return ast.dump(ast.parse(text), include_attributes=False)
    except (SyntaxError, ValueError):
        return None


def _definitions(text: str) -> dict[str, str]:
    """Qualified name -> syntax tree of each function and class (methods as Class.method), plus module-level code."""
    try:
        module = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    out: dict[str, str] = {}
    rest: list[ast.stmt] = []

    def walk(nodes: list[ast.stmt], prefix: str) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[prefix + node.name] = ast.dump(node, include_attributes=False)
            elif isinstance(node, ast.ClassDef):
                # the class itself: bases, keywords, decorators and everything but its methods
                header = [*node.bases, *node.keywords, *node.decorator_list,
                          *(n for n in node.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))]
                out[prefix + node.name] = "|".join(ast.dump(n, include_attributes=False) for n in header)
                walk([n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                     prefix + node.name + ".")
            elif not prefix:
                rest.append(node)
    walk(module.body, "")
    out["<module level>"] = ast.dump(ast.Module(body=rest, type_ignores=[]), include_attributes=False)
    return out


def _compare_file(rel: str, a: str | None, b: str | None) -> tuple[str, list[str]]:
    if a == b:
        return "IDENTICAL", []
    if a is None or b is None or not rel.endswith(".py"):
        return "SUBSTANTIVE", [rel]
    ta, tb = _tree(a), _tree(b)
    if ta is not None and ta == tb:
        return "COSMETIC", []
    da, db = _definitions(a), _definitions(b)
    names = sorted(n for n in set(da) | set(db) if da.get(n) != db.get(n))
    return "SUBSTANTIVE", [f"{rel}:{n}" for n in names] or [rel]


def compare(root: Path, base: str, diffs: dict[str, str]) -> dict[str, Any]:
    """`diffs`: candidate id -> diff from the frozen commit `base`, for passing candidates in the tournament's order.
    Returns pairwise differences and groups of candidates that are cosmetic variants of the first in the group."""
    after = {cid: _after(root, base, diff) for cid, diff in diffs.items()}
    ids = list(diffs)
    pairs = []
    group_of: dict[str, str] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            fa, fb = after[a], after[b]
            if fa is None or fb is None:
                kind, where = "UNKNOWN", ["a diff did not apply to the frozen commit"]
            elif set(fa) != set(fb):
                kind, where = "SUBSTANTIVE", sorted(set(fa) ^ set(fb))
            else:
                kinds, where = [], []
                for rel in sorted(fa):
                    k, w = _compare_file(rel, fa[rel], fb[rel])
                    kinds.append(k)
                    where += w
                kind = ("SUBSTANTIVE" if "SUBSTANTIVE" in kinds else "COSMETIC" if "COSMETIC" in kinds
                        else "IDENTICAL")
            pairs.append({"candidates": [a, b], "difference": kind, "where": where})
            if kind in ("IDENTICAL", "COSMETIC") and b not in group_of:
                group_of[b] = group_of.get(a, a)
    groups: dict[str, list[str]] = {}
    for cid in ids:
        groups.setdefault(group_of.get(cid, cid), []).append(cid)
    return {"pairs": pairs, "groups": list(groups.values()),
            "rule": "COSMETIC: same files, each byte-identical or the same Python syntax tree; else SUBSTANTIVE"}
