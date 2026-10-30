"""The analysis pipeline.

`run_analysis()` is the only entry point. It handles both the full build and
the incremental update; the difference is which files get re-parsed, not which
code path runs. That keeps `init` and `update` from drifting apart.

Stages:
  scan -> parse -> resolve imports -> manifests -> frameworks -> components
       -> routes -> tests -> docs -> git -> score -> persist

Incremental runs re-parse only changed files, but every *derived* fact
(import resolution, centrality, conventions, test links) is recomputed over
the whole repository from the index. That is what keeps `update` output
identical to a fresh `rebuild` on the same tree.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import __version__
from .config import Config
from .docs import analyze_docs
from .frameworks import (
    detect_external_services, detect_frameworks, discover_components,
    extract_routes, is_entrypoint,
)
from .gitinfo import (
    GitInfo,
    collect as git_collect,
    current_head,
    recency_scores,
)
from .index import Index, now_iso, open_index
from .languages import is_code
from .logging_setup import get_logger
from .manifests import MANIFEST_MANAGERS, is_manifest, manager_for, parse_manifest
from .models import FileRecord, ImportEdge, RepoFacts, Route, Symbol
from .parser import parse_file, tree_sitter_available
from .retrieval import split_identifier
from .scanner import ScanResult, analysis_text, scan
from .security import redact_url_credentials
from .testing import coverage_signals, discover_test_suites

log = get_logger()

_INDEX_EXTS_FOR_RESOLUTION = (
    "", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rb",
    ".java", ".kt", ".rs", ".php", ".cs", ".vue", ".svelte",
)


@dataclass(slots=True)
class AnalysisResult:
    facts: RepoFacts
    scan: ScanResult
    git: GitInfo
    symbols: list[Symbol]
    imports: list[ImportEdge]
    file_texts: dict[str, str]
    elapsed: float
    incremental: bool
    changed: list[str]
    removed: list[str]


# --------------------------------------------------------------------------
# Import resolution
# --------------------------------------------------------------------------
def _build_path_lookup(paths: list[str]) -> dict[str, str]:
    """Index files by every suffix a relative import might use."""
    lookup: dict[str, str] = {}
    for path in paths:
        p = PurePosixPath(path)
        stem_path = str(p.with_suffix(""))
        keys = {path, stem_path}
        if p.stem in {"index", "__init__", "mod"}:
            keys.add(str(p.parent))
        # Also register the dotted module form for Python/Java-style imports.
        keys.add(stem_path.replace("/", "."))
        if p.stem == "__init__":
            keys.add(str(p.parent).replace("/", "."))
        if path.endswith(".py") and len(p.parts) > 2 and p.parts[0] in {"src", "lib"}:
            # src layout: `src/pkg/mod.py` is imported as `pkg.mod`
            inner = PurePosixPath(*p.parts[1:])
            keys.add(str(inner.with_suffix("")).replace("/", "."))
            if p.stem == "__init__":
                keys.add(str(inner.parent).replace("/", "."))
        for key in keys:
            lookup.setdefault(key, path)
            # Register progressively shorter suffixes so `utils/auth` resolves
            # even when the file is `src/lib/utils/auth.ts`.
            parts = key.split("/")
            for i in range(1, min(len(parts), 4)):
                lookup.setdefault("/".join(parts[i:]), path)
    return lookup


def _normalize_relative(src: str, target: str) -> str:
    base = PurePosixPath(src).parent
    if target.startswith("./") or target.startswith("../"):
        resolved = os.path.normpath(str(base / target))
    elif target.startswith("/"):
        resolved = target.lstrip("/")
    else:
        return target
    return resolved.replace(os.sep, "/").lstrip("./")


def _python_module(target: str, path_set: set[str], lookup: dict[str, str]) -> str:
    dotted = target.replace("/", ".").strip(".")
    if not dotted or dotted.startswith("."):
        return ""
    rel = dotted.replace(".", "/")
    for root in ("", "src/", "lib/"):
        for probe in (f"{root}{rel}.py", f"{root}{rel}/__init__.py", f"{root}{rel}.pyi"):
            if probe in path_set:
                return probe
    hit = lookup.get(dotted, "") or lookup.get(rel, "")
    return hit if hit.endswith((".py", ".pyi")) else ""


_JS_SOURCES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")

# TypeScript ESM (NodeNext / bundler) imports name the *emitted* file: `./math.js`
# is written in `math.ts`. TypeScript's own substitution table.
_TS_FOR_JS = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}


def _ts_source_for_js(candidate: str, path_set: set[str]) -> str:
    """`dir/math.js` -> `dir/math.ts` when only the TypeScript source exists."""
    stem, dot, ext = candidate.rpartition(".")
    if not dot or "/" in ext:
        return ""
    for sub in _TS_FOR_JS.get("." + ext, ()):
        if stem + sub in path_set:
            return stem + sub
    return ""


def package_mains(root: Path | None, all_paths: list[str]) -> dict[str, str]:
    """Directory -> the file Node loads for `require(dir)`: package.json `exports`
    (string or `"."`), `module`, `main`, then `index.*`."""
    import json
    path_set = set(all_paths)
    out: dict[str, str] = {}
    if root is None:
        return out
    for pj in (p for p in all_paths if PurePosixPath(p).name == "package.json" and "node_modules/" not in p):
        try:
            data = json.loads((root / pj).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        base = str(PurePosixPath(pj).parent)
        base = "" if base == "." else base
        exports = data.get("exports")
        if isinstance(exports, dict):
            dot = exports.get(".")
            exports = dot if isinstance(dot, str) else (dot.get("require") or dot.get("import") or dot.get("default")
                                                         if isinstance(dot, dict) else None)
        for entry in (exports, data.get("module"), data.get("main")):
            if not isinstance(entry, str):
                continue
            rel = os.path.normpath(os.path.join(base, entry)).replace(os.sep, "/").lstrip("./")
            for probe in (rel, *(rel + e for e in _JS_SOURCES), *(f"{rel}/index{e}" for e in _JS_SOURCES)):
                if probe in path_set:
                    out.setdefault(base, probe)
                    break
    return out


def resolve_imports(
    edges: list[ImportEdge], all_paths: list[str], tsconfig_aliases: dict[str, str],
    mains: dict[str, str] | None = None,
) -> list[ImportEdge]:
    lookup = _build_path_lookup(all_paths)
    path_set = set(all_paths)
    mains = mains or {}
    kept: list[ImportEdge] = []
    # Dotted packages that exist in the repo (`app`, `app.api`): an import of
    # one is first-party even when its `__init__.py` is empty and unindexed.
    packages: set[str] = set()
    for path in all_paths:
        if path.endswith(".py"):
            parts = PurePosixPath(path).with_suffix("").parts
            for i in range(1, len(parts)):
                packages.add(".".join(parts[:i]))
                if parts[0] in {"src", "lib"} and i > 1:
                    packages.add(".".join(parts[1:i]))

    for edge in edges:
        target = edge.raw_target.strip()
        optional = target.startswith("?")
        target = target.lstrip("?")
        edge.resolved_path = ""
        edge.external_package = ""
        if not target:
            continue
        kept.append(edge)

        for alias, real in tsconfig_aliases.items():
            if target.startswith(alias):
                target = real + target[len(alias):]
                break

        candidate = _normalize_relative(edge.src_path, target)
        found = ""
        if edge.src_path.endswith(_JS_SOURCES) and target.startswith((".", "/")):
            # Node: `require("..")` or `require("./lib")` loads that directory's package
            # entry (package.json) or its index file
            directory = os.path.normpath(str(PurePosixPath(edge.src_path).parent / target)).replace(os.sep, "/")
            directory = "" if directory == "." else directory.lstrip("./")
            entry = mains.get(directory) or next(
                (f"{directory}/index{e}".lstrip("/") for e in _JS_SOURCES
                 if f"{directory}/index{e}".lstrip("/") in path_set), "")
            if entry and entry != edge.src_path and candidate not in path_set and not any(
                    candidate + e in path_set for e in _JS_SOURCES):
                edge.resolved_path = entry
                continue
        if edge.src_path.endswith(".py"):
            # a Python import names a module or package, never a doc or data file:
            # `import markdown` is markdown/__init__.py, not docs/reference/markdown.md
            found = _python_module(target, path_set, lookup)
            if found:
                if found != edge.src_path:
                    edge.resolved_path = found
                continue

        if candidate in path_set:
            found = candidate
        else:
            for ext in _INDEX_EXTS_FOR_RESOLUTION:
                probe = candidate + ext if ext else candidate
                if probe in path_set:
                    found = probe
                    break
                if probe in lookup:
                    found = lookup[probe]
                    break
            if not found:
                found = _ts_source_for_js(candidate, path_set)
            if not found:
                for index_name in ("index.ts", "index.tsx", "index.js",
                                   "__init__.py", "mod.rs", "index.jsx"):
                    probe = f"{candidate}/{index_name}"
                    if probe in path_set:
                        found = probe
                        break
            if not found:
                found = lookup.get(candidate, "") or lookup.get(target, "")

        if found and found != edge.src_path:
            edge.resolved_path = found
        elif optional:
            kept.pop()  # `from x import name` where name is not a module file
        elif "/" not in target and target in packages:
            continue  # first-party package (namespace or empty __init__): internal, unresolved
        elif not target.startswith((".", "/")):
            # External package: keep the top-level name only.
            head = target.split("/")[0] if "/" in target else target.split(".")[0]
            if target.startswith("@") and "/" in target:
                head = "/".join(target.split("/")[:2])
            edge.external_package = head
    return kept


def _read_tsconfig_aliases(root: Path) -> dict[str, str]:
    import json
    import re as _re

    aliases: dict[str, str] = {}
    for name in ("tsconfig.json", "jsconfig.json"):
        path = root / name
        if not path.is_file():
            continue
        try:
            raw = path.read_text("utf-8", errors="replace")
            raw = _re.sub(r"//[^\n]*", "", raw)
            raw = _re.sub(r"/\*.*?\*/", "", raw, flags=_re.S)
            raw = _re.sub(r",(\s*[}\]])", r"\1", raw)
            data = json.loads(raw)
        except Exception:
            continue
        options = data.get("compilerOptions") or {}
        base = (options.get("baseUrl") or "").strip("./")
        for alias, targets in (options.get("paths") or {}).items():
            if not targets:
                continue
            clean_alias = alias.rstrip("*")
            clean_target = str(targets[0]).rstrip("*").lstrip("./")
            if base and not clean_target.startswith(base):
                clean_target = f"{base}/{clean_target}".strip("/")
            aliases[clean_alias] = clean_target
    return aliases


# --------------------------------------------------------------------------
# Centrality
# --------------------------------------------------------------------------
def compute_centrality(edges: list[ImportEdge], paths: list[str]) -> dict[str, float]:
    """Normalised in-degree: how many other files import this one."""
    in_degree: Counter[str] = Counter()
    for edge in edges:
        if edge.resolved_path:
            in_degree[edge.resolved_path] += 1
    if not in_degree:
        return {p: 0.0 for p in paths}
    peak = max(in_degree.values())
    return {p: round(in_degree.get(p, 0) / peak, 4) for p in paths}


# --------------------------------------------------------------------------
# Convention inference
# --------------------------------------------------------------------------
def infer_conventions(
    files: list[FileRecord], symbols: list[tuple[str, str]], root: Path
) -> dict[str, object]:
    """`symbols` is every (name, kind) pair in the index, in a stable order."""
    conventions: dict[str, object] = {}

    def name_style(names: list[str]) -> str:
        if not names:
            return "unknown"
        snake = sum(1 for n in names if "_" in n and n.islower())
        camel = sum(1 for n in names if n[:1].islower() and any(c.isupper() for c in n))
        pascal = sum(1 for n in names if n[:1].isupper())
        kebab = sum(1 for n in names if "-" in n)
        best = max(
            (("snake_case", snake), ("camelCase", camel),
             ("PascalCase", pascal), ("kebab-case", kebab)),
            key=lambda kv: kv[1],
        )
        return best[0] if best[1] else "mixed"

    func_names = [n for n, k in symbols if k in {"function", "method"}][:4000]
    class_names = [n for n, k in symbols if k in {"class", "interface", "struct"}][:2000]
    file_stems = [PurePosixPath(f.path).stem for f in files if f.role == "source"][:4000]

    conventions["function_naming"] = name_style(func_names)
    conventions["naming_sample_size"] = {"functions": len(func_names), "types": len(class_names)}
    conventions["type_naming"] = name_style(class_names)
    conventions["file_naming"] = name_style(file_stems)

    # Indentation: sample real source files.
    tabs = spaces = 0
    widths: Counter[int] = Counter()
    for record in files[:1500]:
        if record.role != "source" or not is_code(record.language):
            continue
        try:
            text = (root / record.path).read_text("utf-8", errors="replace")[:20000]
        except OSError:
            continue
        for line in text.splitlines()[:200]:
            if line.startswith("\t"):
                tabs += 1
            elif line.startswith("  "):
                spaces += 1
                widths[len(line) - len(line.lstrip(" "))] += 1
    conventions["indentation"] = "tabs" if tabs > spaces else "spaces"
    if widths:
        common = [w for w, _ in widths.most_common(6) if w > 0]
        base = min(common) if common else 4
        conventions["indent_width"] = base

    tooling: list[str] = []
    for name, label in (
        (".editorconfig", "EditorConfig"), (".prettierrc", "Prettier"),
        (".prettierrc.json", "Prettier"), (".prettierrc.js", "Prettier"),
        (".eslintrc", "ESLint"), (".eslintrc.json", "ESLint"),
        ("eslint.config.js", "ESLint"), ("eslint.config.mjs", "ESLint"),
        (".flake8", "flake8"), ("ruff.toml", "Ruff"), (".ruff.toml", "Ruff"),
        ("setup.cfg", "setup.cfg"), (".pylintrc", "Pylint"),
        (".rubocop.yml", "RuboCop"), ("rustfmt.toml", "rustfmt"),
        (".golangci.yml", "golangci-lint"), (".golangci.yaml", "golangci-lint"),
        ("checkstyle.xml", "Checkstyle"), ("spotbugs.xml", "SpotBugs"),
        (".pre-commit-config.yaml", "pre-commit"),
        (".husky", "Husky"), ("lefthook.yml", "Lefthook"),
        ("commitlint.config.js", "commitlint"),
        (".editorconfig", "EditorConfig"),
    ):
        if (root / name).exists() and label not in tooling:
            tooling.append(label)
    conventions["tooling"] = tooling

    conventions["has_typescript_strict"] = False
    tsconfig = root / "tsconfig.json"
    if tsconfig.is_file():
        try:
            conventions["has_typescript_strict"] = '"strict": true' in tsconfig.read_text(
                "utf-8", errors="replace")
        except OSError:
            pass

    return conventions


# --------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------
def _parse_one(args: tuple[FileRecord, str, bool]):
    record, text, use_ts = args
    try:
        return record.path, parse_file(record.path, text, record.language, use_ts)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("parse failed for %s: %s", record.path, exc)
        return record.path, None



def _collect_git_cached(
    root: Path,
    cfg: Config,
    index: Index,
    tracked: set[str],
    incremental: bool,
) -> GitInfo:
    """Collect git signals, reusing the previous walk when HEAD has not moved.

    The numstat walk plus `shortlog` costs a couple of seconds on a repository
    with tens of thousands of commits. None of it can change without a new
    commit, so key the cache on HEAD. Working-tree edits are picked up by the
    file scan, not by this.
    """
    head = current_head(root)
    if incremental and head:
        cached = index.get_meta("git_cache")
        if cached:
            try:
                payload = json.loads(cached)
            except json.JSONDecodeError:
                payload = None
            if payload and payload.get("head") == head:
                log.info("git: reusing cached history for %s", head)
                return GitInfo.from_json(payload["git"])

    git = git_collect(root, cfg.git_history_days, cfg.git_max_commits, tracked)
    if head:
        index.set_meta("git_cache", json.dumps({"head": head, "git": git.to_json()}))
    return git


_TEST_STEM_RE = (
    # (pattern on test filename, how to derive the source stem)
    re.compile(r"^test_(.+)$"),
    re.compile(r"^(.+)_test$"),
    re.compile(r"^(.+)[._](?:test|spec)$"),
    re.compile(r"^(.+?)Tests?$"),
)


def _test_subject_stem(path: str) -> str:
    stem = PurePosixPath(path).stem
    for pattern in _TEST_STEM_RE:
        match = pattern.match(stem)
        if match and match.group(1):
            return match.group(1)
    return ""


def compute_test_links(files: list[FileRecord], edges: list[ImportEdge]) -> list[tuple[str, str, str]]:
    """(test_path, source_path, evidence) — 'import' or 'name'.

    Import evidence is strong (the test loads the module). Name evidence
    (`test_auth.py` -> `auth.py`) is weaker and only used when the stem maps to
    a unique source file, or to one in the test's own component.
    """
    roles = {f.path: f.role for f in files}
    links: set[tuple[str, str, str]] = set()
    for edge in edges:
        if edge.resolved_path and roles.get(edge.src_path) == "test" \
                and roles.get(edge.resolved_path) == "source":
            links.add((edge.src_path, edge.resolved_path, "import"))
    by_stem: dict[str, list[FileRecord]] = defaultdict(list)
    for record in files:
        if record.role == "source":
            by_stem[PurePosixPath(record.path).stem.lower()].append(record)
    components = {f.path: f.component for f in files}
    for record in files:
        if record.role != "test":
            continue
        stem = _test_subject_stem(record.path).lower()
        if not stem:
            continue
        candidates = by_stem.get(stem, [])
        if len(candidates) > 1:
            candidates = [c for c in candidates if c.component == components.get(record.path)]
        if len(candidates) == 1 and (record.path, candidates[0].path, "import") not in links:
            links.add((record.path, candidates[0].path, "name"))
    return sorted(links)


def run_analysis(
    root: Path,
    cfg: Config,
    context_dir: Path,
    incremental: bool = False,
    state_dir: Path | None = None,
    prune: tuple[str, ...] = (),
) -> AnalysisResult:
    started = time.monotonic()

    # Open the index first so an incremental scan can reuse stored records for
    # files whose size and mtime are unchanged.
    index = open_index(state_dir or context_dir)
    if incremental and index.get_meta("needs_reanalysis") == "1":
        log.info("index schema was migrated; running a full re-analysis once")
        incremental = False
    known = index.file_records() if incremental else None
    # set before anything is scanned or written: a rebuild killed during the scan (its index
    # still empty) must read as interrupted, never as "0 files indexed, context is current"
    index.set_meta("needs_reanalysis", "1")

    if not prune:
        prune = tuple(
            p.relative_to(root).as_posix()
            for p in {context_dir, state_dir or context_dir}
            if p != root and root in p.parents
        )
    log.info("scanning %s", root)
    scan_result = scan(root, cfg, known=known, prune=prune)
    log.info("scan complete: %d indexable files (%d seen, %d skipped, %d unchanged)",
             len(scan_result.files), scan_result.total_seen,
             sum(scan_result.skipped.values()), scan_result.reused)

    previous = index.file_hashes() if incremental else {}
    current = {f.path: f.sha1 for f in scan_result.files}

    # Crash safety: the index is written in several separately committed steps, and
    # a file's stored hash is what tells the next incremental run it is up to date.
    # Until the last step has committed, the index says it needs a full
    # re-analysis, so a run killed halfway (SIGKILL, power loss) can never leave
    # a file marked current without its symbols, imports or search entries.
    index.set_meta("needs_reanalysis", "1")
    if incremental:
        changed = [p for p, h in current.items() if previous.get(p) != h]
        removed = [p for p in previous if p not in current]
        log.info("incremental: %d changed, %d removed, %d unchanged",
                 len(changed), len(removed), len(current) - len(changed))
    else:
        index.reset()
        changed = list(current)
        removed = []

    if removed or changed:
        index.delete_paths(removed + changed)

    changed_set = set(changed)
    to_parse = [f for f in scan_result.files if f.path in changed_set]

    # --- read text for the files we need ---------------------------------
    file_texts: dict[str, str] = {}
    needed = {f.path for f in to_parse}
    # Docs, manifests, and configs are always re-read: they are small and they
    # drive the generated narrative.
    # Test files are re-read too: framework detection votes on their imports,
    # and skipping them on incremental runs made `update` disagree with `init`.
    for record in scan_result.files:
        if record.role in {"doc", "build", "config", "test"} or record.path in needed:
            needed.add(record.path)
    for record in scan_result.files:
        if record.path in needed:
            try:
                file_texts[record.path] = analysis_text(record.path, (root / record.path).read_text(
                    "utf-8", errors="replace"))
            except OSError:
                continue

    # --- parse ------------------------------------------------------------
    use_ts = cfg.use_tree_sitter and tree_sitter_available()
    if cfg.parse_symbols and to_parse:
        log.info("parsing %d files (%s)", len(to_parse),
                 "tree-sitter + stdlib ast" if use_ts else "stdlib ast + regex fallback")
    workers = cfg.workers or min(32, (os.cpu_count() or 4) * 2)
    symbols: list[Symbol] = []
    imports: list[ImportEdge] = []
    routes: list[Route] = []

    if cfg.parse_symbols and to_parse:
        payload = [(r, file_texts.get(r.path, ""), use_ts) for r in to_parse
                   if file_texts.get(r.path)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for path, parsed in pool.map(_parse_one, payload):
                if parsed is None:
                    continue
                symbols.extend(parsed.symbols)
                imports.extend(parsed.imports)
                if parsed.module_doc:
                    for rec in to_parse:
                        if rec.path == path:
                            rec.doc_summary = rec.doc_summary or parsed.module_doc
                            break

    for record in to_parse:
        text = file_texts.get(record.path, "")
        if text and record.role in {"source", "config"}:
            routes.extend(extract_routes(record.path, text, record.language))

    # --- manifests ---------------------------------------------------------
    commands: dict[str, list[str]] = defaultdict(list)
    dependencies = []
    manifest_paths: list[str] = []
    for record in scan_result.files:
        if is_manifest(record.path):
            manifest_paths.append(record.path)
            text = file_texts.get(record.path, "")
            if not text:
                try:
                    text = (root / record.path).read_text("utf-8", errors="replace")
                except OSError:
                    text = ""
            if text:
                dependencies.extend(parse_manifest(root, record.path, text, commands))
    log.info("found %d manifests, %d declared dependencies",
             len(manifest_paths), len(dependencies))

    # --- entrypoints / frameworks / components -----------------------------
    for record in scan_result.files:
        record.is_entrypoint = is_entrypoint(record.path) and record.role == "source"

    frameworks, by_layer = detect_frameworks(scan_result.files, dependencies)
    # Makefiles describe commands, not package boundaries.
    package_manifests = [m for m in manifest_paths if manager_for(m) != "make"]
    components = discover_components(scan_result.files, package_manifests, root.name)
    comp_lookup = sorted(
        ((c.root, c.name) for c in components if c.root != "."),
        key=lambda kv: len(kv[0]), reverse=True,
    )
    for record in scan_result.files:
        record.component = next(
            (name for root_dir, name in comp_lookup
             if record.path.startswith(root_dir + "/")),
            components[0].name if components else root.name,
        )

    # --- docs / tests -------------------------------------------------------
    doc_records, doc_commands = analyze_docs(scan_result.files, file_texts)
    for cmd in doc_commands:
        bucket = ("test" if any(t in cmd for t in ("test", "pytest", "jest", "vitest", "rspec"))
                  else "build" if any(t in cmd for t in ("build", "compile", "package"))
                  else "run")
        if cmd not in commands[bucket]:
            commands[bucket].append(cmd)

    test_suites = discover_test_suites(scan_result.files, file_texts, dependencies, commands)

    # --- git ----------------------------------------------------------------
    tracked = set(current)
    git = _collect_git_cached(root, cfg, index, tracked, incremental)
    if git.is_repo:
        log.info("git: %s@%s, %d commits, %d contributors",
                 git.branch or "?", git.head or "?", git.commit_count, git.contributors)

    # --- imports & centrality ----------------------------------------------
    aliases = _read_tsconfig_aliases(root)
    all_paths = [f.path for f in scan_result.files]
    # Re-resolve the *whole* edge set against the current file list, once.
    # Edges from unchanged files are reloaded raw, so a deleted target no
    # longer resolves and a newly added file starts receiving its importers.
    existing = [
        ImportEdge(row["src_path"], row["raw_target"])
        for row in index.conn.execute(
            "SELECT src_path, raw_target FROM imports ORDER BY rowid")
    ] if incremental else []
    all_edges = resolve_imports(existing + imports, all_paths, aliases, package_mains(root, all_paths))
    all_edges.sort(key=lambda e: (e.src_path, e.raw_target))
    centrality = compute_centrality(all_edges, all_paths)
    recency = recency_scores(git)
    churn = {s.path: s.churn for s in git.hotspots}

    # --- persist ------------------------------------------------------------
    index.upsert_files(scan_result.files)
    if symbols:
        index.insert_symbols(symbols)
    index.replace_imports(all_edges)
    test_links = compute_test_links(scan_result.files, all_edges)
    index.replace_test_links(test_links)
    if routes:
        index.insert_routes(routes)
    index.replace_dependencies(dependencies)
    index.replace_coupling(git.coupling)
    index.set_scores({
        p: (centrality.get(p, 0.0), recency.get(p, 0.0), churn.get(p, 0))
        for p in all_paths
    })
    _index_search_documents(index, scan_result.files, symbols, file_texts, changed_set, routes)
    _index_graph_evidence(root, index, scan_result.files, all_edges, file_texts, changed_set,
                          set(removed))
    index.clear_cache()  # derived; also purges pre-0.6 entries that held prompt text
    index.optimize()

    # --- facts --------------------------------------------------------------
    languages: Counter[str] = Counter()
    for record in scan_result.files:
        if is_code(record.language):
            languages[record.language] += record.lines

    facts = RepoFacts(
        root=str(root),
        name=root.name,
        context_dir=(context_dir.relative_to(root).as_posix()
                     if root in context_dir.parents else ""),
        generated_at=now_iso(),
        tool_version=__version__,
        git_head=git.head,
        git_branch=git.branch,
        git_remote=redact_url_credentials(git.remote),
        total_files_seen=scan_result.total_seen,
        indexed_files=len(scan_result.files),
        skipped_files=sum(scan_result.skipped.values()),
        total_loc=sum(f.lines for f in scan_result.files if is_code(f.language)),
        languages=dict(languages.most_common(25)),
        package_managers=sorted({manager_for(m) for m in manifest_paths} - {"", "make"}),
        frameworks=frameworks,
        build_systems=sorted(set(by_layer.get("build", []) + by_layer.get("ci", []))),
        components=components,
        entrypoints=[f.path for f in scan_result.files if f.is_entrypoint][:40],
        dependencies=dependencies,
        routes=_reload_routes(index),
        test_suites=test_suites,
        commands={k: v[:8] for k, v in commands.items() if v},
        docs=doc_records,
        ci_workflows=[f.path for f in scan_result.files
                      if "/.github/workflows/" in "/" + f.path
                      or f.path.endswith((".gitlab-ci.yml", "Jenkinsfile",
                                          "azure-pipelines.yml"))][:25],
        infra=[f.path for f in scan_result.files if f.role == "infra"][:60],
        conventions=infer_conventions(scan_result.files, index.symbol_names_kinds(), root),
        hotspots=git.hotspots[:40],
        recent_files=[p for p in git.recent_files if p in current][:20],
        secret_hits=scan_result.secret_hits,
        quarantined=list(scan_result.quarantined),
        external_services=detect_external_services(
            dependencies,
            "\n".join(file_texts.get(f.path, "")[:4000]
                      for f in scan_result.files if f.role in {"config", "infra"}),
        ),
    )
    facts.conventions["layers"] = by_layer
    facts.conventions["test_coverage_signals"] = coverage_signals(scan_result.files, file_texts)
    facts.conventions["generated_paths"] = generated_paths(scan_result.files)
    facts.conventions["test_links"] = len(test_links)
    facts.important_files = rank_important_files(
        scan_result.files, centrality, recency, churn, facts)

    if scan_result.quarantined:
        facts.warnings.append(
            f"{len(scan_result.quarantined)} file(s) quarantined by the secret scanner "
            "and excluded from the index. See SECURITY_NOTES.md."
        )
    if not git.is_repo:
        facts.warnings.append("Not a Git repository: recency and hotspot ranking are disabled.")
    if not use_ts and cfg.parse_symbols:
        facts.warnings.append(
            "tree-sitter not installed: non-Python symbol extraction uses the regex "
            "fallback. Install with `pip install 'repo-ai-cli[ast]'` (with pipx: `pipx inject repo-ai-cli "
            "'tree-sitter>=0.23' 'tree-sitter-language-pack>=0.7,<1.0'`) for higher fidelity."
        )

    index.set_meta("generated_at", facts.generated_at)
    index.set_meta("git_head", git.head)
    index.set_meta("tool_version", __version__)
    index.set_meta("indexed_files", str(len(scan_result.files)))
    index.set_meta("fingerprint", _fingerprint(scan_result.files, git.head))
    index.set_meta("needs_reanalysis", "0")  # last: every step above has committed
    index.close()

    elapsed = time.monotonic() - started
    log.info("analysis complete in %.1fs", elapsed)
    return AnalysisResult(
        facts=facts, scan=scan_result, git=git, symbols=symbols,
        imports=all_edges, file_texts=file_texts, elapsed=elapsed,
        incremental=incremental, changed=changed, removed=removed,
    )


def _index_graph_evidence(root: Path, index: Index, files: list[FileRecord],
                          edges: list[ImportEdge], file_texts: dict[str, str],
                          changed: set[str], removed: set[str]) -> None:
    """Symbol-use and API-literal evidence for the graph (see graph.py).

    Uses are recomputed for changed files *and* for files importing a changed
    or removed file, because a renamed symbol in B invalidates A's uses of B.
    """
    from .graph import compute_refs, extract_url_literals

    roles = {f.path: f.role for f in files}
    targets: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.resolved_path and edge.resolved_path != edge.src_path:
            targets[edge.src_path].add(edge.resolved_path)
    touched = changed | removed
    recompute = sorted(src for src, dsts in targets.items()
                       if src in changed or dsts & touched)
    texts: dict[str, str] = {}
    for src in recompute:
        text = file_texts.get(src)
        if text is None:
            try:
                text = analysis_text(src, (root / src).read_text("utf-8", errors="replace"))
            except OSError:
                continue
        texts[src] = text
    wanted = sorted({d for s in recompute for d in targets[s]})
    names: dict[str, list[str]] = defaultdict(list)
    for i in range(0, len(wanted), 500):
        chunk = wanted[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for row in index.conn.execute(
                f"SELECT DISTINCT path, name FROM symbols WHERE parent='' AND path IN ({marks})",
                chunk):
            names[row["path"]].append(row["name"])
    index.replace_refs_for(recompute, compute_refs(texts, targets, names))
    literals = []
    for path in sorted(changed):
        if roles.get(path) in {"source", "test"} and path in file_texts:
            literals.extend(extract_url_literals(path, file_texts[path]))
    if literals:
        index.insert_url_refs(literals)


def _reload_routes(index: Index) -> list[Route]:
    rows = index.conn.execute(
        "SELECT * FROM routes ORDER BY file, line, method, path_pattern LIMIT 1000").fetchall()
    return [Route(r["method"], r["path_pattern"], r["handler"], r["file"], r["line"], r["framework"])
            for r in rows]


def _fingerprint(files: list[FileRecord], head: str) -> str:
    """Changes whenever any indexed file's content changes. Keys the query cache."""
    import hashlib
    digest = hashlib.sha256(head.encode())
    for record in files:
        digest.update(f"{record.path}\0{record.sha1}\n".encode())
    return digest.hexdigest()[:20]


def generated_paths(files: list[FileRecord], limit: int = 15) -> list[str]:
    """Directories (or single files) holding generated, machine-owned output."""
    dirs: Counter[str] = Counter()
    for record in files:
        if record.role == "generated":
            parent = str(PurePosixPath(record.path).parent)
            dirs[record.path if parent == "." else parent + "/"] += 1
    return [d for d, _ in sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def _index_search_documents(
    index: Index,
    files: list[FileRecord],
    symbols: list[Symbol],
    file_texts: dict[str, str],
    changed: set[str],
    routes: list[Route] | None = None,
) -> None:
    """Populate FTS5. Identifiers are stored separately so they can be weighted."""
    by_path: dict[str, list[Symbol]] = defaultdict(list)
    for symbol in symbols:
        by_path[symbol.path].append(symbol)
    route_words: dict[str, list[str]] = defaultdict(list)
    for route in routes or []:
        words = [w for w in re.split(r"[^A-Za-z0-9]+", route.path_pattern) if len(w) > 1]
        route_words[route.file].extend(["route", route.method.lower(), *words])

    for record in files:
        if record.path not in changed:
            continue
        syms = by_path.get(record.path, [])
        names: list[str] = []
        for symbol in syms:
            for part in (symbol.name, symbol.parent):
                if part:
                    names.append(part)
                    names.extend(split_identifier(part))
            names.append(symbol.kind)
        path_parts = [w for seg in record.path.split("/") for w in split_identifier(seg)]
        identifiers = " ".join(dict.fromkeys(path_parts + names + route_words.get(record.path, [])))

        text = file_texts.get(record.path, "")
        if record.role == "doc":
            body = text[:60_000]
        else:
            body = " ".join(
                filter(None, [record.doc_summary, *(s.signature for s in syms[:200]),
                              *(s.docstring for s in syms[:200])])
            )
            if not body:
                body = text[:8_000]
        index.index_document(record.path, record.role, identifiers, body)
    index.commit()


def rank_important_files(
    files: list[FileRecord],
    centrality: dict[str, float],
    recency: dict[str, float],
    churn: dict[str, int],
    facts: RepoFacts,
) -> list[dict[str, object]]:
    """Blend structural and historical signals into a 'read this first' list."""
    route_files = Counter(r.file for r in facts.routes)
    max_churn = max(churn.values()) if churn else 1
    entry_set = set(facts.entrypoints)
    manifest_names = set(MANIFEST_MANAGERS)

    scored: list[tuple[float, FileRecord, list[str]]] = []
    for record in files:
        if record.role in {"generated", "fixture"}:
            continue
        reasons: list[str] = []
        score = 0.0

        cent = centrality.get(record.path, 0.0)
        if cent > 0:
            score += cent * 40
            if cent > 0.25:
                reasons.append(f"imported widely ({int(cent * 100)}% of peak)")

        if record.path in entry_set:
            score += 30
            reasons.append("entrypoint")

        if PurePosixPath(record.path).name in manifest_names:
            score += 18
            reasons.append("package manifest")

        if record.role == "doc":
            score += 10
        if record.role == "infra":
            score += 6

        if record.path in route_files:
            score += min(route_files[record.path] * 3, 18)
            reasons.append(f"{route_files[record.path]} route(s)")

        churn_score = churn.get(record.path, 0) / max_churn if max_churn else 0
        score += churn_score * 14
        if churn_score > 0.35:
            reasons.append("high churn")

        rec = recency.get(record.path, 0.0)
        score += rec * 10
        if rec > 0.6:
            reasons.append("changed recently")

        depth = record.path.count("/")
        score -= depth * 1.2
        if record.role == "test":
            score -= 6

        if score > 5:
            scored.append((score, record, reasons))

    scored.sort(key=lambda item: -item[0])
    return [
        {
            "path": record.path,
            "score": round(score, 1),
            "role": record.role,
            "language": record.language,
            "lines": record.lines,
            "component": record.component,
            "why": reasons or ["structurally significant"],
            "summary": record.doc_summary,
        }
        for score, record, reasons in scored[:60]
    ]
