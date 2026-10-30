"""Where a static import graph cannot see consumers.

Detected, with file:line provenance:

* **loaders** - calls that load code by a computed name (``importlib.
  import_module(name)``, ``__import__``, entry points, ``pkgutil`` scans;
  ``require(x)`` / ``import(x)`` with a non-literal argument). A string
  prefix in the argument (``f"pkg.ext.{n}"``, ```./plugins/${n}```) narrows
  the loader to the modules under that prefix.
* **literal loads** - the same calls with a literal name: a real edge the
  import graph misses.
* **registrations** - entry points declared in pyproject.toml / setup.cfg:
  a module reachable by a registered *name*, not by its path.
* **string references** - string literals naming a repository module or
  file (``"markdown.extensions.toc"``, ``"toc"`` for a registered name).

None of this proves a dynamic edge exists; it marks where the static answer
may be incomplete, so the selector can say so instead of reporting "low risk".
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

PY_LOADERS = {"import_module": "import", "__import__": "import", "load_module": "import",
              "exec_module": "import", "spec_from_file_location": "path", "run_module": "import",
              "run_path": "path", "load_entry_point": "entry-point", "iter_entry_points": "entry-point",
              "entry_points": "entry-point", "iter_modules": "scan", "walk_packages": "scan",
              "load_source": "path", "import_string": "import", "import_object": "import"}
JS_DYNAMIC = re.compile(r"\b(require|import)\s*\(\s*(?!['\"][^'\"`]*['\"]\s*\))([^)]{0,120})\)")
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx")
MAX_FILE = 1_500_000


@dataclass(slots=True)
class Site:
    path: str
    line: int
    kind: str          # import | path | entry-point | scan | require
    prefix: str = ""   # module/path prefix the computed name starts with, if known

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "kind": self.kind, "prefix": self.prefix or None}


@dataclass(slots=True)
class DynamicFacts:
    modules: dict[str, str] = field(default_factory=dict)       # python file -> dotted module
    loaders: list[Site] = field(default_factory=list)           # computed-name loaders
    literal_loads: dict[str, list[Site]] = field(default_factory=dict)   # target file -> sites
    registrations: dict[str, list[dict[str, str]]] = field(default_factory=dict)  # target -> entry points
    string_refs: dict[str, list[Site]] = field(default_factory=dict)     # target file -> sites
    source_readers: list[Site] = field(default_factory=list)  # files that glob/read source files as data

    def exposure(self, path: str, static_importers: int) -> list[dict[str, Any]]:
        """Reasons the static answer for `path` may be incomplete."""
        out: list[dict[str, Any]] = []
        module = self.modules.get(path, "")
        for reg in self.registrations.get(path, []):
            out.append({"kind": "registered", "detail": f"entry point {reg['group']}:{reg['name']} "
                        f"in {reg['config']}", "evidence": reg})
        for site in self.loaders:
            if site.prefix and _under_prefix(path, module, site.prefix):
                out.append({"kind": "loaded-by-computed-name", "detail":
                            f"{site.path}:{site.line} loads `{site.prefix}…` by a computed name",
                            "evidence": site.to_json()})
        if not out and static_importers == 0 and self.loaders and not path.endswith("__main__.py"):
            generic = [s for s in self.loaders if not s.prefix and _same_package(path, s.path)]
            if generic:
                s = generic[0]
                out.append({"kind": "possibly-loaded-dynamically", "detail":
                            f"no static importer, and {s.path}:{s.line} loads modules by a computed "
                            f"name ({s.kind})", "evidence": s.to_json()})
        return out


def _under_prefix(path: str, module: str, prefix: str) -> bool:
    if "/" in prefix or prefix.startswith("."):
        clean = prefix.lstrip("./")
        return bool(clean) and path.startswith(clean)
    return bool(module) and bool(prefix) and (module + ".").startswith(prefix)


def _same_package(a: str, b: str) -> bool:
    pa, pb = PurePosixPath(a).parts, PurePosixPath(b).parts
    return bool(pa) and bool(pb) and pa[0] == pb[0]


def module_names(files: list[str]) -> dict[str, str]:
    """Dotted module names for Python files, from package structure (src/
    layouts included)."""
    present = set(files)
    out: dict[str, str] = {}
    for f in files:
        if not f.endswith(".py"):
            continue
        p = PurePosixPath(f)
        parts = [p.stem] if p.stem != "__init__" else []
        cur = p.parent
        while str(cur) not in {"", "."} and (cur / "__init__.py").as_posix() in present:
            parts.insert(0, cur.name)
            cur = cur.parent
        if parts:
            out[f] = ".".join(parts)
    return out


def _const_prefix(node: ast.AST) -> tuple[bool, str]:
    """(is a literal, the literal or its constant prefix)"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True, node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return False, str(node.values[0].value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        lit, pre = _const_prefix(node.left)
        if lit:
            return False, pre
    return False, ""


SCAN_VERSION = 1


def analyze(root: Path, files: list[str], config_files: list[str] | None = None,
            cache_path: Path | None = None) -> DynamicFacts:
    """`cache_path`: per-file Python scans keyed by (size, mtime, inode), so a
    plan re-parses only the files that changed since the last plan."""
    facts = DynamicFacts(modules=module_names(files))
    by_module = {m: f for f, m in facts.modules.items()}
    file_set = set(files)
    names: dict[str, str] = {}  # registered entry-point name -> target file
    for cfg in config_files or [f for f in files if PurePosixPath(f).name in {"pyproject.toml", "setup.cfg"}]:
        for group, name, target in _entry_points(root / cfg):
            mod = target.split(":")[0].strip()
            tfile = by_module.get(mod)
            if tfile:
                facts.registrations.setdefault(tfile, []).append(
                    {"config": cfg, "group": group, "name": name, "target": target})
                names.setdefault(name, tfile)
    cache = _load_cache(cache_path)
    fresh: dict[str, Any] = {}
    for f in files:
        suffix = PurePosixPath(f).suffix.lower()
        if suffix not in {".py", *JS_SUFFIXES}:
            continue
        if suffix == ".py":
            sig = _signature(root / f)
            hit = cache.get(f)
            if sig and hit and hit.get("sig") == sig:
                scan = hit["scan"]
            else:
                try:
                    text = (root / f).read_text("utf-8", errors="replace")[:MAX_FILE].removeprefix("\ufeff")
                except OSError:
                    continue
                scan = _python_scan(text)
            if sig:
                fresh[f] = {"sig": sig, "scan": scan}
            _python(f, scan, facts, by_module, names)
        else:
            try:
                text = (root / f).read_text("utf-8", errors="replace")[:MAX_FILE].removeprefix("\ufeff")
            except OSError:
                continue
            _javascript(f, text, facts, file_set)
    _save_cache(cache_path, fresh)
    return facts


def _signature(path: Path) -> list[int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ino]


def _load_cache(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("files", {}) if isinstance(data, dict) and data.get("version") == SCAN_VERSION else {}


def _save_cache(path: Path | None, files: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        from ..fsutil import atomic_write  # a temporary file per writer, removed on failure
        atomic_write(path, json.dumps({"version": SCAN_VERSION, "files": files}, separators=(",", ":")))
    except OSError:
        pass


def _python_scan(text: str) -> dict[str, Any]:
    """What a Python file contributes, independent of the rest of the
    repository: loader calls, source globs, and identifier-like strings."""
    scan: dict[str, Any] = {"calls": [], "globs": [], "strings": []}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return scan
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            kind = PY_LOADERS.get(name)
            if kind:
                arg = node.args[0] if node.args else None
                literal, prefix = _const_prefix(arg) if arg is not None else (False, "")
                scan["calls"].append([kind, literal, prefix, node.lineno])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                re.fullmatch(r"(?:\*\*/)?\*\.pyi?|.*[/\\]\*\.pyi?", node.value):
            # a glob for source files ('*.py', '**/*.py'): this file reads sources as data
            scan["globs"].append(getattr(node, "lineno", 0))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if 2 < len(value) < 200 and " " not in value:
                scan["strings"].append([value, getattr(node, "lineno", 0)])
    return scan


def _python(path: str, scan: dict[str, Any], facts: DynamicFacts, by_module: dict[str, str],
            names: dict[str, str]) -> None:
    for kind, literal, prefix, lineno in scan["calls"]:
        if literal and kind == "import":
            target = by_module.get(prefix.lstrip("."))
            if target:
                facts.literal_loads.setdefault(target, []).append(Site(path, lineno, kind))
                continue
        if kind in {"entry-point", "scan"} or not literal:
            facts.loaders.append(Site(path, lineno, kind, prefix if not literal else ""))
    for lineno in scan["globs"]:
        facts.source_readers.append(Site(path, lineno, "source-glob"))
    for value, lineno in scan["strings"]:
        target = by_module.get(value) or by_module.get(value.split(":")[0]) or names.get(value)
        if target and target != path:
            facts.string_refs.setdefault(target, []).append(Site(path, lineno, "string"))


_JS_STRING = re.compile(r"""(['"`])((?:\.{1,2}/|/)?[\w@./-]{2,160})\1""")


def _javascript(path: str, text: str, facts: DynamicFacts, file_set: set[str]) -> None:
    for m in JS_DYNAMIC.finditer(text):
        arg = m.group(2).strip()
        prefix = ""
        pm = re.match(r"""[`'"]([^`'"$]*)""", arg)
        if pm:
            prefix = str(PurePosixPath(path).parent / pm.group(1)) if pm.group(1).startswith(".") else pm.group(1)
        line = text.count("\n", 0, m.start()) + 1
        facts.loaders.append(Site(path, line, "require", prefix))
    base = PurePosixPath(path).parent
    for m in _JS_STRING.finditer(text):
        raw = m.group(2)
        if not raw.startswith("."):
            continue
        cand = _normalize(base / raw)
        for target in (cand, *(cand + s for s in JS_SUFFIXES), *(f"{cand}/index{s}" for s in JS_SUFFIXES)):
            if target in file_set and target != path:
                line = text.count("\n", 0, m.start()) + 1
                facts.string_refs.setdefault(target, []).append(Site(path, line, "string"))
                break


def _normalize(p: PurePosixPath) -> str:
    parts: list[str] = []
    for part in p.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def _entry_points(path: Path) -> list[tuple[str, str, str]]:
    try:
        text = path.read_text("utf-8", errors="replace")[:500_000]
    except OSError:
        return []
    out: list[tuple[str, str, str]] = []
    if path.name == "pyproject.toml":
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:  # pragma: no cover - Python 3.10
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ModuleNotFoundError:
                return out
        try:
            data = tomllib.loads(text)
        except ValueError:
            return out
        project = data.get("project") or {}
        groups = dict(project.get("entry-points") or {})
        if project.get("scripts"):
            groups["console_scripts"] = project["scripts"]
        for group, entries in groups.items():
            if isinstance(entries, dict):
                out += [(group, str(n), str(t)) for n, t in entries.items()]
    else:  # setup.cfg [options.entry_points]
        section = re.search(r"(?ms)^\[options\.entry_points\]\s*$(.*?)(?=^\[|\Z)", text)
        group = ""
        for line in (section.group(1).splitlines() if section else []):
            if re.match(r"^\S.*=\s*$", line):
                group = line.split("=")[0].strip()
            elif "=" in line and group:
                name, _, target = line.strip().partition("=")
                out.append((group, name.strip(), target.strip()))
    return out
