"""Symbol and import extraction.

Three tiers, chosen per file:

  * **Python** -> `ast` from the standard library. Exact, zero dependencies.
  * **Anything else, with `repo-ai-cli[ast]` installed** -> tree-sitter queries.
  * **Fallback** -> line-anchored regexes tuned per language family.

The fallback is deliberately conservative: it prefers missing a symbol over
inventing one, because a wrong symbol index is worse than a thin one. Bob has
`FindSymbol` and `grep` for precision work; repo-ai's job is orientation.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath

from .logging_setup import get_logger
from .models import ImportEdge, Symbol

log = get_logger()


# --------------------------------------------------------------------------
# tree-sitter (optional)
# --------------------------------------------------------------------------
_TS_LANG_NAMES = {
    "JavaScript": "javascript", "TypeScript": "typescript", "Java": "java",
    "Go": "go", "Rust": "rust", "Ruby": "ruby", "PHP": "php", "C#": "c_sharp",
    "C": "c", "C++": "cpp", "Kotlin": "kotlin", "Scala": "scala",
    "Swift": "swift", "Lua": "lua", "Elixir": "elixir", "Bash": "bash",
    "Shell": "bash", "SQL": "sql", "HCL": "hcl", "Terraform": "hcl",
}

_TS_NODE_KIND = {
    "function_declaration": "function", "function_definition": "function",
    "method_definition": "method", "method_declaration": "method",
    "class_declaration": "class", "class_definition": "class",
    "interface_declaration": "interface", "struct_item": "struct",
    "struct_specifier": "struct", "enum_declaration": "enum",
    "enum_item": "enum", "type_alias_declaration": "type",
    "type_declaration": "type", "impl_item": "impl",
    "function_item": "function", "trait_item": "interface",
    "arrow_function": "function", "module": "module",
    "object_declaration": "class", "record_declaration": "class",
    "constructor_declaration": "method",
}


@lru_cache(maxsize=32)
def _get_ts_parser(language: str):  # pragma: no cover - optional dependency
    ts_name = _TS_LANG_NAMES.get(language)
    if not ts_name:
        return None
    try:
        import tree_sitter_language_pack as pack
        from tree_sitter_language_pack import get_parser
    except Exception:
        return None
    # tree-sitter-language-pack >= 1.0 can download grammars on demand. repo-ai
    # makes no network calls: only grammars already on disk are used.
    downloaded = getattr(pack, "downloaded_languages", None)
    if downloaded is not None:
        try:
            if ts_name not in set(downloaded()):
                return None
        except Exception:
            return None
    try:
        return get_parser(ts_name)
    except Exception:
        return None


def _ts_symbols(path: str, text: str, language: str) -> list[Symbol]:  # pragma: no cover
    parser = _get_ts_parser(language)
    if parser is None:
        return []
    try:
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return []

    symbols: list[Symbol] = []
    source = text.encode("utf-8")

    def node_text(node) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def walk(node, parent: str = "") -> None:
        kind = _TS_NODE_KIND.get(node.type)
        current_parent = parent
        if kind:
            name_node = node.child_by_field_name("name")
            name = node_text(name_node) if name_node is not None else ""
            if name:
                first_line = node_text(node).split("\n", 1)[0][:200]
                symbols.append(Symbol(
                    path=path, name=name, kind=kind,
                    line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=first_line.strip().rstrip("{").strip(),
                    parent=parent,
                ))
                if kind in {"class", "interface", "struct", "impl", "enum"}:
                    current_parent = name
        for child in node.children:
            walk(child, current_parent)

    walk(tree.root_node)
    return symbols


# --------------------------------------------------------------------------
# Python: stdlib ast
# --------------------------------------------------------------------------
def _py_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []
    for arg in list(args.posonlyargs) + list(args.args):
        parts.append(arg.arg)
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    for arg in args.kwonlyargs:
        parts.append(arg.arg)
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(parts)})"


def python_symbols_and_imports(
    path: str, text: str
) -> tuple[list[Symbol], list[ImportEdge], str]:
    """Parse a Python file. Returns (symbols, imports, module_docstring)."""
    text = text.removeprefix("\ufeff")  # a UTF-8 BOM is valid Python source, but not inside a str
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return _regex_symbols(path, text, "Python"), _regex_imports(path, text, "Python"), ""
    except (ValueError, RecursionError):
        return [], [], ""

    symbols: list[Symbol] = []
    imports: list[ImportEdge] = []
    module_doc = (ast.get_docstring(tree) or "").split("\n")[0][:300]

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def _add(self, node, kind: str, signature: str) -> None:
            name = getattr(node, "name", "")
            if not name:
                return
            symbols.append(Symbol(
                path=path, name=name, kind=kind,
                line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno) or node.lineno,
                signature=signature,
                parent=".".join(self.stack),
                exported=not name.startswith("_"),
                docstring=(ast.get_docstring(node) or "").split("\n")[0][:200]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "",
            ))

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            bases = []
            for base in node.bases:
                try:
                    bases.append(ast.unparse(base))
                except Exception:
                    pass
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
            self._add(node, "class", sig)
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def _visit_func(self, node) -> None:
            kind = "method" if self.stack else "function"
            self._add(node, kind, _py_signature(node))
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_func
        visit_AsyncFunctionDef = _visit_func

        def visit_Assign(self, node: ast.Assign) -> None:
            # Module-level CONSTANTS are worth indexing; locals are not.
            if self.stack:
                return
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 2:
                    symbols.append(Symbol(
                        path=path, name=target.id, kind="const",
                        line=node.lineno, end_line=node.lineno,
                        signature=target.id,
                    ))

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.append(ImportEdge(src_path=path, raw_target=alias.name))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            if node.level:  # relative import
                base = str(PurePosixPath(path).parent)
                for _ in range(node.level - 1):
                    base = str(PurePosixPath(base).parent)
                target = f"{base}/{module.replace('.', '/')}" if module else base
                imports.append(ImportEdge(src_path=path, raw_target=target))
                sep = "/"
            else:
                target = module
                imports.append(ImportEdge(src_path=path, raw_target=module))
                sep = "."
            # `from pkg import submodule` imports a *file*. Record each name as
            # an optional edge ("?" prefix): kept only if it resolves to a file.
            for alias in node.names[:20]:
                if alias.name != "*" and target:
                    imports.append(ImportEdge(src_path=path,
                                              raw_target=f"?{target}{sep}{alias.name}"))

    Visitor().visit(tree)
    return symbols, imports, module_doc


# --------------------------------------------------------------------------
# Regex fallback
# --------------------------------------------------------------------------
_JS_TS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("class", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*[=<]")),
    ("enum", re.compile(r"^\s*(?:export\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?(?:function|\([^)]*\)\s*(?::\s*[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)")),
    ("component", re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:const|function)\s+([A-Z][\w$]*)\s*[:=(]")),
)

_LANG_PATTERNS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "JavaScript": _JS_TS_PATTERNS,
    "TypeScript": _JS_TS_PATTERNS,
    "Vue": _JS_TS_PATTERNS,
    "Svelte": _JS_TS_PATTERNS,
    "Java": (
        ("class", re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:abstract\s+)?class\s+(\w+)")),
        ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+(\w+)")),
        ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+(\w+)")),
        ("record", re.compile(r"^\s*(?:public\s+)?record\s+(\w+)")),
        ("method", re.compile(r"^\s{2,}(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?[\w<>\[\],.\s?]+\s+(\w+)\s*\([^;]*\)\s*(?:throws[\w\s,.]+)?\{")),
    ),
    "Kotlin": (
        ("class", re.compile(r"^\s*(?:open\s+|data\s+|sealed\s+|abstract\s+)*class\s+(\w+)")),
        ("interface", re.compile(r"^\s*interface\s+(\w+)")),
        ("object", re.compile(r"^\s*object\s+(\w+)")),
        ("function", re.compile(r"^\s*(?:suspend\s+)?fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(\w+)\s*\(")),
    ),
    "Go": (
        ("function", re.compile(r"^func\s+(\w+)\s*\(")),
        ("method", re.compile(r"^func\s+\([^)]*\)\s*(\w+)\s*\(")),
        ("type", re.compile(r"^type\s+(\w+)\s+")),
    ),
    "Rust": (
        ("function", re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)")),
        ("struct", re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?struct\s+(\w+)")),
        ("enum", re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?enum\s+(\w+)")),
        ("interface", re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?trait\s+(\w+)")),
        ("impl", re.compile(r"^\s*impl(?:<[^>]*>)?\s+(?:\w+\s+for\s+)?(\w+)")),
    ),
    "Ruby": (
        ("class", re.compile(r"^\s*class\s+([A-Z]\w*)")),
        ("module", re.compile(r"^\s*module\s+([A-Z]\w*)")),
        ("method", re.compile(r"^\s*def\s+(?:self\.)?(\w+[?!=]?)")),
    ),
    "PHP": (
        ("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+(\w+)")),
        ("interface", re.compile(r"^\s*interface\s+(\w+)")),
        ("trait", re.compile(r"^\s*trait\s+(\w+)")),
        ("function", re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|static\s+)*function\s+(\w+)\s*\(")),
    ),
    "C#": (
        ("class", re.compile(r"^\s*(?:public|internal|private|protected)?\s*(?:static\s+|sealed\s+|abstract\s+|partial\s+)*class\s+(\w+)")),
        ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+(\w+)")),
        ("record", re.compile(r"^\s*(?:public\s+)?record\s+(\w+)")),
        ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+(\w+)")),
        ("method", re.compile(r"^\s{2,}(?:public|private|protected|internal)\s+(?:static\s+|async\s+|virtual\s+|override\s+)*[\w<>\[\],.\s?]+\s+(\w+)\s*\(")),
    ),
    "C": (
        ("function", re.compile(r"^[A-Za-z_][\w\s*]*\s+\*?(\w+)\s*\([^;]*\)\s*\{")),
        ("struct", re.compile(r"^\s*typedef\s+struct\s*\w*\s*\{|^\s*struct\s+(\w+)\s*\{")),
    ),
    "C++": (
        ("class", re.compile(r"^\s*class\s+(\w+)")),
        ("struct", re.compile(r"^\s*struct\s+(\w+)")),
        ("function", re.compile(r"^[A-Za-z_][\w\s:*&<>,]*\s+\*?(\w+)\s*\([^;]*\)\s*(?:const\s*)?\{")),
    ),
    "Swift": (
        ("class", re.compile(r"^\s*(?:public\s+|open\s+|final\s+)*class\s+(\w+)")),
        ("struct", re.compile(r"^\s*(?:public\s+)?struct\s+(\w+)")),
        ("interface", re.compile(r"^\s*(?:public\s+)?protocol\s+(\w+)")),
        ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+(\w+)")),
        ("function", re.compile(r"^\s*(?:public\s+|private\s+|internal\s+|static\s+|override\s+)*func\s+(\w+)")),
    ),
    "Scala": (
        ("class", re.compile(r"^\s*(?:abstract\s+|final\s+|case\s+)*class\s+(\w+)")),
        ("object", re.compile(r"^\s*(?:case\s+)?object\s+(\w+)")),
        ("interface", re.compile(r"^\s*trait\s+(\w+)")),
        ("function", re.compile(r"^\s*def\s+(\w+)")),
    ),
    "Elixir": (
        ("module", re.compile(r"^\s*defmodule\s+([\w.]+)")),
        ("function", re.compile(r"^\s*defp?\s+(\w+[?!]?)")),
    ),
    "Shell": (
        ("function", re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{")),
    ),
    "SQL": (
        ("table", re.compile(r"(?i)^\s*create\s+(?:or\s+replace\s+)?table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?([\w.]+)")),
        ("view", re.compile(r"(?i)^\s*create\s+(?:or\s+replace\s+)?view\s+[`\"\[]?([\w.]+)")),
        ("function", re.compile(r"(?i)^\s*create\s+(?:or\s+replace\s+)?(?:function|procedure)\s+[`\"\[]?([\w.]+)")),
    ),
    "Terraform": (
        ("resource", re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"')),
        ("module", re.compile(r'^\s*module\s+"([^"]+)"')),
        ("variable", re.compile(r'^\s*variable\s+"([^"]+)"')),
        ("output", re.compile(r'^\s*output\s+"([^"]+)"')),
    ),
    "COBOL": (
        ("program", re.compile(r"(?i)^\s*PROGRAM-ID\.\s+([\w-]+)")),
        ("section", re.compile(r"(?i)^\s*([\w-]+)\s+SECTION\s*\.")),
    ),
    "RPG": (
        ("procedure", re.compile(r"(?i)^\s*dcl-proc\s+([\w$#@]+)")),
        ("subroutine", re.compile(r"(?i)^\s*begsr\s+([\w$#@]+)")),
    ),
}

_IMPORT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "JavaScript": (
        re.compile(r"""^\s*import\s+(?:[\w*{},\s]+\s+from\s+)?['"]([^'"]+)['"]"""),
        re.compile(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)"""),
        re.compile(r"""^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""\bimport\(\s*['"]([^'"]+)['"]\s*\)"""),
    ),
    "Java": (re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;"),),
    "Kotlin": (re.compile(r"^\s*import\s+([\w.]+)"),),
    "Go": (re.compile(r'^\s*(?:_\s+|\w+\s+)?"([^"]+)"\s*$'),),
    "Rust": (re.compile(r"^\s*(?:pub\s+)?use\s+([\w:]+)"),),
    "Ruby": (re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]"""),),
    "PHP": (re.compile(r"^\s*use\s+([\w\\]+)"),),
    "C#": (re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;"),),
    "C": (re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]'),),
    "Swift": (re.compile(r"^\s*import\s+(\w+)"),),
    "Scala": (re.compile(r"^\s*import\s+([\w.]+)"),),
    "Elixir": (re.compile(r"^\s*(?:import|alias|use)\s+([\w.]+)"),),
}
_IMPORT_PATTERNS["TypeScript"] = _IMPORT_PATTERNS["JavaScript"]
_IMPORT_PATTERNS["Vue"] = _IMPORT_PATTERNS["JavaScript"]
_IMPORT_PATTERNS["Svelte"] = _IMPORT_PATTERNS["JavaScript"]
_IMPORT_PATTERNS["C++"] = _IMPORT_PATTERNS["C"]

_MAX_PARSE_LINES = 20_000


def _regex_symbols(path: str, text: str, language: str) -> list[Symbol]:
    patterns = _LANG_PATTERNS.get(language)
    if not patterns:
        return []
    symbols: list[Symbol] = []
    parent = ""
    parent_indent = -1
    lines = text.splitlines()[:_MAX_PARSE_LINES]
    seen: set[tuple[str, int]] = set()

    for idx, line in enumerate(lines, start=1):
        if len(line) > 1000:
            continue
        indent = len(line) - len(line.lstrip())
        if parent and indent <= parent_indent:
            parent = ""
            parent_indent = -1
        for kind, pattern in patterns:
            match = pattern.match(line) if pattern.pattern.startswith("^") else pattern.search(line)
            if not match:
                continue
            groups = [g for g in match.groups() if g]
            if not groups:
                continue
            name = ".".join(groups) if kind == "resource" else groups[0]
            key = (name, idx)
            if key in seen:
                continue
            seen.add(key)
            symbols.append(Symbol(
                path=path, name=name, kind=kind, line=idx, end_line=idx,
                signature=line.strip()[:200].rstrip("{").strip(),
                parent=parent if kind in {"method", "function"} else "",
                exported="export" in line or "pub " in line or "public" in line
                         or not name.startswith("_"),
            ))
            if kind in {"class", "interface", "struct", "module", "object", "trait"}:
                parent = name
                parent_indent = indent
            break
    return symbols


def _regex_imports(path: str, text: str, language: str) -> list[ImportEdge]:
    patterns = _IMPORT_PATTERNS.get(language)
    if not patterns:
        return []
    edges: list[ImportEdge] = []
    seen: set[str] = set()
    # Imports live near the top of nearly every language; cap the scan.
    for line in text.splitlines()[:800]:
        if len(line) > 500:
            continue
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                target = match.group(1).strip()
                if target and target not in seen:
                    seen.add(target)
                    edges.append(ImportEdge(src_path=path, raw_target=target))
                break
    return edges


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
@dataclass(slots=True)
class ParseResult:
    symbols: list[Symbol]
    imports: list[ImportEdge]
    module_doc: str = ""


def parse_file(path: str, text: str, language: str, use_tree_sitter: bool = True) -> ParseResult:
    """Extract symbols and imports from one file."""
    if language == "Python":
        symbols, imports, doc = python_symbols_and_imports(path, text)
        return ParseResult(symbols, imports, doc)

    symbols = []
    if use_tree_sitter:
        try:
            symbols = _ts_symbols(path, text, language)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("tree-sitter failed on %s: %s", path, exc)
            symbols = []
    if not symbols:
        symbols = _regex_symbols(path, text, language)

    imports = _regex_imports(path, text, language)
    return ParseResult(symbols, imports)


def tree_sitter_available() -> bool:
    try:  # pragma: no cover - optional dependency
        import tree_sitter_language_pack  # noqa: F401
        return True
    except Exception:
        return False
