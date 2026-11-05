"""The index: a single SQLite file (`.repo-ai/state/index.db`, or
`.bob/context/index.db` for v0.4-layout installs).

Why SQLite and not a vector database:

  * it ships with Python — no daemon, no install step, no version drift
  * FTS5 gives BM25 ranking over identifiers and doc text for free
  * transactional incremental updates are trivial (delete-by-path + insert)
  * one file is easy to `.gitignore`, easy to delete, easy to inspect
  * it is fully local, which matters for proprietary code

The schema is deliberately small. Everything that Bob reads is a Markdown file;
the database exists to make `repo-ai context` fast and incremental.
"""

from __future__ import annotations

import json
import sqlite3
import time
import zlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from .logging_setup import get_logger
from .models import Dependency, FileRecord, ImportEdge, Route, Symbol

log = get_logger()

SCHEMA_VERSION = 6
# Oldest schema we can migrate forward instead of rebuilding.
_MIGRATABLE_FROM = 4


class IndexTooNew(RuntimeError):
    """The index was written by a newer repo-ai; refuse to clobber it."""

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path         TEXT PRIMARY KEY,
    size         INTEGER NOT NULL,
    lines        INTEGER NOT NULL,
    language     TEXT NOT NULL,
    sha1         TEXT NOT NULL,
    mtime        REAL NOT NULL,
    role         TEXT NOT NULL,
    is_entrypoint INTEGER NOT NULL DEFAULT 0,
    component    TEXT NOT NULL DEFAULT '',
    doc_summary  TEXT NOT NULL DEFAULT '',
    centrality   REAL NOT NULL DEFAULT 0,
    recency      REAL NOT NULL DEFAULT 0,
    churn        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_files_role ON files(role);
CREATE INDEX IF NOT EXISTS idx_files_lang ON files(language);
CREATE INDEX IF NOT EXISTS idx_files_component ON files(component);

CREATE TABLE IF NOT EXISTS symbols (
    id        INTEGER PRIMARY KEY,
    path      TEXT NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    line      INTEGER NOT NULL,
    end_line  INTEGER NOT NULL,
    signature TEXT NOT NULL DEFAULT '',
    parent    TEXT NOT NULL DEFAULT '',
    exported  INTEGER NOT NULL DEFAULT 1,
    docstring TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);

CREATE TABLE IF NOT EXISTS imports (
    src_path         TEXT NOT NULL,
    raw_target       TEXT NOT NULL,
    resolved_path    TEXT NOT NULL DEFAULT '',
    external_package TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_imports_src ON imports(src_path);
CREATE INDEX IF NOT EXISTS idx_imports_resolved ON imports(resolved_path);
CREATE INDEX IF NOT EXISTS idx_imports_external ON imports(external_package);

CREATE TABLE IF NOT EXISTS dependencies (
    name     TEXT NOT NULL,
    version  TEXT NOT NULL DEFAULT '',
    manager  TEXT NOT NULL,
    scope    TEXT NOT NULL DEFAULT 'runtime',
    manifest TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_deps_name ON dependencies(name);

CREATE TABLE IF NOT EXISTS routes (
    method       TEXT NOT NULL,
    path_pattern TEXT NOT NULL,
    handler      TEXT NOT NULL DEFAULT '',
    file         TEXT NOT NULL,
    line         INTEGER NOT NULL,
    framework    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_routes_file ON routes(file);

CREATE TABLE IF NOT EXISTS coupling (
    path_a TEXT NOT NULL,
    path_b TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_coupling_a ON coupling(path_a);

CREATE TABLE IF NOT EXISTS test_links (
    test_path TEXT NOT NULL,
    src_path  TEXT NOT NULL,
    evidence  TEXT NOT NULL DEFAULT 'import'
);
CREATE INDEX IF NOT EXISTS idx_test_links_src ON test_links(src_path);
CREATE INDEX IF NOT EXISTS idx_test_links_test ON test_links(test_path);

-- v6: evidence for the graph. `refs` are uses of a symbol that an imported
-- file defines (word match outside import lines: heuristic); `url_refs` are
-- string literals that look like API paths (matched to routes: heuristic).
CREATE TABLE IF NOT EXISTS refs (
    src_path TEXT NOT NULL,
    dst_path TEXT NOT NULL,
    symbol   TEXT NOT NULL,
    line     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refs_src ON refs(src_path);
CREATE INDEX IF NOT EXISTS idx_refs_dst ON refs(dst_path);

CREATE TABLE IF NOT EXISTS url_refs (
    path TEXT NOT NULL,
    url  TEXT NOT NULL,
    line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_url_refs_path ON url_refs(path);

CREATE TABLE IF NOT EXISTS query_cache (
    key     TEXT PRIMARY KEY,
    created REAL NOT NULL,
    payload BLOB NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
    path UNINDEXED,
    kind UNINDEXED,
    identifiers,
    text,
    tokenize = "porter unicode61 remove_diacritics 2 tokenchars '_$'"
);
"""


class Index:
    """Thin, explicit wrapper over the SQLite connection."""

    def __init__(self, db_path: Path, busy_timeout_ms: int = 5000) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=busy_timeout_ms / 1000)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        version = self._stored_version()
        if version != SCHEMA_VERSION:
            # DDL only when needed: hooks open the index on every prompt and
            # should not take a write lock just to confirm the schema.
            self._upgrade(version)

    # -- lifecycle --------------------------------------------------------
    def _stored_version(self) -> int | None:
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return -1

    def _upgrade(self, version: int | None) -> None:
        if version is not None and version > SCHEMA_VERSION:
            raise IndexTooNew(
                f"{self.db_path} uses schema v{version}, newer than this repo-ai "
                f"(v{SCHEMA_VERSION}). Upgrade repo-ai, or run `repo-ai rebuild`.")
        if version is not None and version < 5:
            # v5 changed the FTS tokenizer (porter stemming); the virtual table
            # must be recreated. Its rows are derived, so nothing is lost.
            self.conn.execute("DROP TABLE IF EXISTS search")
        self.conn.executescript(_SCHEMA)
        if version is None:
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            return
        if version >= _MIGRATABLE_FROM:
            # v4 -> v5 added `test_links` and `query_cache`; v5 -> v6 added
            # `refs` and `url_refs` (all created above by CREATE IF NOT
            # EXISTS). Their contents are derived, so flag a one-time full
            # re-analysis instead of dropping anything.
            log.info("index schema v%d -> v%d: migrated in place; next update re-analyses",
                     version, SCHEMA_VERSION)
            self.set_meta("needs_reanalysis", "1")
        else:
            log.warning("index schema v%s is too old to migrate; rebuilding it", version)
            self.reset()
            self.set_meta("last_reset_reason", f"schema v{version} -> v{SCHEMA_VERSION}")
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    def reset(self) -> None:
        for table in ("files", "symbols", "imports", "dependencies",
                      "routes", "coupling", "search", "test_links", "query_cache",
                      "refs", "url_refs"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- meta -------------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value) if not isinstance(value, str) else value),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # -- writes -----------------------------------------------------------
    def upsert_files(self, records: Iterable[FileRecord]) -> None:
        self.conn.executemany(
            "INSERT INTO files(path,size,lines,language,sha1,mtime,role,"
            "is_entrypoint,component,doc_summary) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, lines=excluded.lines, "
            "language=excluded.language, sha1=excluded.sha1, mtime=excluded.mtime, "
            "role=excluded.role, is_entrypoint=excluded.is_entrypoint, "
            "component=excluded.component, doc_summary=excluded.doc_summary",
            [r.to_row() for r in records],
        )
        self.conn.commit()

    def delete_paths(self, paths: Sequence[str]) -> None:
        if not paths:
            return
        cur = self.conn.cursor()
        cur.executemany("DELETE FROM files WHERE path=?", [(p,) for p in paths])
        cur.executemany("DELETE FROM symbols WHERE path=?", [(p,) for p in paths])
        cur.executemany("DELETE FROM imports WHERE src_path=?", [(p,) for p in paths])
        cur.executemany("DELETE FROM routes WHERE file=?", [(p,) for p in paths])
        cur.executemany("DELETE FROM search WHERE path=?", [(p,) for p in paths])
        cur.executemany("DELETE FROM refs WHERE src_path=? OR dst_path=?", [(p, p) for p in paths])
        cur.executemany("DELETE FROM url_refs WHERE path=?", [(p,) for p in paths])
        cur.executemany("DELETE FROM coupling WHERE path_a=? OR path_b=?",
                        [(p, p) for p in paths])
        self.conn.commit()

    def insert_symbols(self, symbols: Iterable[Symbol]) -> None:
        self.conn.executemany(
            "INSERT INTO symbols(path,name,kind,line,end_line,signature,parent,"
            "exported,docstring) VALUES(?,?,?,?,?,?,?,?,?)",
            [(s.path, s.name, s.kind, s.line, s.end_line, s.signature, s.parent,
              int(s.exported), s.docstring) for s in symbols],
        )
        self.conn.commit()

    def replace_imports(self, edges: Iterable[ImportEdge]) -> None:
        self.conn.execute("DELETE FROM imports")
        self.insert_imports(edges)

    def replace_test_links(self, links: Iterable[tuple[str, str, str]]) -> None:
        self.conn.execute("DELETE FROM test_links")
        self.conn.executemany(
            "INSERT INTO test_links(test_path, src_path, evidence) VALUES(?,?,?)", list(links))
        self.conn.commit()

    def replace_refs_for(self, sources: Iterable[str],
                         rows: Iterable[tuple[str, str, str, int]]) -> None:
        self.conn.executemany("DELETE FROM refs WHERE src_path=?", [(s,) for s in sources])
        self.conn.executemany(
            "INSERT INTO refs(src_path, dst_path, symbol, line) VALUES(?,?,?,?)", list(rows))
        self.conn.commit()

    def insert_url_refs(self, rows: Iterable[tuple[str, str, int]]) -> None:
        self.conn.executemany("INSERT INTO url_refs(path, url, line) VALUES(?,?,?)", list(rows))
        self.conn.commit()

    def refs_from(self, path: str, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT dst_path, symbol, line FROM refs WHERE src_path=? ORDER BY line LIMIT ?",
            (path, limit)).fetchall()

    def refs_to(self, path: str, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT src_path, symbol, line FROM refs WHERE dst_path=? ORDER BY src_path, line "
            "LIMIT ?", (path, limit)).fetchall()

    def url_refs(self, path: str | None = None, limit: int = 2000) -> list[sqlite3.Row]:
        if path is None:
            return self.conn.execute("SELECT path, url, line FROM url_refs ORDER BY path, line "
                                     "LIMIT ?", (limit,)).fetchall()
        return self.conn.execute("SELECT path, url, line FROM url_refs WHERE path=? "
                                 "ORDER BY line LIMIT ?", (path, limit)).fetchall()

    def insert_imports(self, edges: Iterable[ImportEdge]) -> None:
        self.conn.executemany(
            "INSERT INTO imports(src_path,raw_target,resolved_path,external_package) "
            "VALUES(?,?,?,?)",
            [(e.src_path, e.raw_target, e.resolved_path, e.external_package) for e in edges],
        )
        self.conn.commit()

    def replace_dependencies(self, deps: Iterable[Dependency]) -> None:
        self.conn.execute("DELETE FROM dependencies")
        self.conn.executemany(
            "INSERT INTO dependencies(name,version,manager,scope,manifest) VALUES(?,?,?,?,?)",
            [(d.name, d.version, d.manager, d.scope, d.manifest) for d in deps],
        )
        self.conn.commit()

    def insert_routes(self, routes: Iterable[Route]) -> None:
        self.conn.executemany(
            "INSERT INTO routes(method,path_pattern,handler,file,line,framework) "
            "VALUES(?,?,?,?,?,?)",
            [(r.method, r.path_pattern, r.handler, r.file, r.line, r.framework) for r in routes],
        )
        self.conn.commit()

    def replace_coupling(self, coupling: dict[str, list[str]]) -> None:
        self.conn.execute("DELETE FROM coupling")
        rows = [(a, b, 1) for a, peers in coupling.items() for b in peers]
        if rows:
            self.conn.executemany(
                "INSERT INTO coupling(path_a,path_b,weight) VALUES(?,?,?)", rows)
        self.conn.commit()

    def index_document(self, path: str, kind: str, identifiers: str, text: str) -> None:
        self.conn.execute(
            "INSERT INTO search(path, kind, identifiers, text) VALUES(?,?,?,?)",
            (path, kind, identifiers[:60_000], text[:120_000]),
        )

    def commit(self) -> None:
        self.conn.commit()

    def set_scores(self, scores: dict[str, tuple[float, float, int]]) -> None:
        """path -> (centrality, recency, churn)."""
        self.conn.executemany(
            "UPDATE files SET centrality=?, recency=?, churn=? WHERE path=?",
            [(c, r, ch, p) for p, (c, r, ch) in scores.items()],
        )
        self.conn.commit()

    # -- reads ------------------------------------------------------------
    def file_hashes(self) -> dict[str, str]:
        return {row["path"]: row["sha1"]
                for row in self.conn.execute("SELECT path, sha1 FROM files")}

    def file_records(self) -> dict[str, FileRecord]:
        """Stored records keyed by path, for the incremental scan fast path."""
        rows = self.conn.execute(
            "SELECT path, size, lines, language, sha1, mtime, role, doc_summary FROM files"
        )
        return {
            row["path"]: FileRecord(
                path=row["path"],
                size=row["size"],
                lines=row["lines"],
                language=row["language"],
                sha1=row["sha1"],
                mtime=row["mtime"],
                role=row["role"],
                doc_summary=row["doc_summary"] or "",
            )
            for row in rows
        }

    def all_files(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM files ORDER BY path"))

    def get_file(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()

    def symbols_for(self, path: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM symbols WHERE path=? ORDER BY line", (path,)))

    def find_symbol(self, name: str, limit: int = 40) -> list[sqlite3.Row]:
        exact = list(self.conn.execute(
            "SELECT s.*, f.role, f.language FROM symbols s LEFT JOIN files f ON f.path=s.path "
            "WHERE s.name = ? ORDER BY (f.role='source') DESC, s.path LIMIT ?",
            (name, limit)))
        if exact:
            return exact
        return list(self.conn.execute(
            "SELECT s.*, f.role, f.language FROM symbols s LEFT JOIN files f ON f.path=s.path "
            "WHERE s.name LIKE ? ORDER BY length(s.name), s.path LIMIT ?",
            (f"%{name}%", limit)))

    def importers_of(self, path: str, limit: int = 60) -> list[str]:
        return [row["src_path"] for row in self.conn.execute(
            "SELECT DISTINCT src_path FROM imports WHERE resolved_path=? LIMIT ?",
            (path, limit))]

    def imports_of(self, path: str, limit: int = 80) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT raw_target, resolved_path, external_package FROM imports "
            "WHERE src_path=? LIMIT ?", (path, limit)))

    def coupled_with(self, path: str, limit: int = 6) -> list[str]:
        return [row["path_b"] for row in self.conn.execute(
            "SELECT path_b FROM coupling WHERE path_a=? ORDER BY weight DESC LIMIT ?",
            (path, limit))]

    def tests_for(self, path: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT test_path, evidence FROM test_links WHERE src_path=? "
            "ORDER BY (evidence='import') DESC, test_path", (path,)))

    def sources_tested_by(self, test_path: str) -> list[str]:
        return [r["src_path"] for r in self.conn.execute(
            "SELECT src_path FROM test_links WHERE test_path=? ORDER BY src_path", (test_path,))]

    def symbol_names_kinds(self) -> list[tuple[str, str]]:
        return [(r["name"], r["kind"]) for r in self.conn.execute(
            "SELECT name, kind FROM symbols ORDER BY path, line, name")]

    # -- query cache -------------------------------------------------------
    def cache_get(self, key: str) -> str | None:
        try:
            row = self.conn.execute("SELECT payload FROM query_cache WHERE key=?", (key,)).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        try:
            return zlib.decompress(row["payload"]).decode("utf-8")
        except (zlib.error, UnicodeDecodeError):
            return None

    def cache_put(self, key: str, payload: str, keep: int = 300) -> None:
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO query_cache(key, created, payload) VALUES(?,?,?)",
                (key, time.time(), zlib.compress(payload.encode("utf-8"))))
            self.conn.execute(
                "DELETE FROM query_cache WHERE key NOT IN "
                "(SELECT key FROM query_cache ORDER BY created DESC LIMIT ?)", (keep,))
            self.conn.commit()
        except sqlite3.OperationalError:  # locked by a concurrent update: skip
            self.conn.rollback()

    def clear_cache(self) -> None:
        self.conn.execute("DELETE FROM query_cache")
        self.conn.commit()

    def routes(self, limit: int = 500) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM routes ORDER BY path_pattern LIMIT ?", (limit,)))

    def dependencies(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM dependencies ORDER BY manager, scope, name"))

    def search(self, query: str, limit: int = 60) -> list[sqlite3.Row]:
        """BM25 search over identifiers (weighted 3x) and text."""
        try:
            return list(self.conn.execute(
                "SELECT path, kind, bm25(search, 0.0, 0.0, 3.0, 1.0) AS score "
                "FROM search WHERE search MATCH ? ORDER BY score LIMIT ?",
                (query, limit)))
        except sqlite3.OperationalError:
            return []

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("files", "symbols", "imports", "dependencies", "routes", "test_links"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        return out

    def optimize(self) -> None:
        try:
            self.conn.execute("INSERT INTO search(search) VALUES('optimize')")
            self.conn.execute("ANALYZE")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass


def open_index(state_dir: Path, busy_timeout_ms: int = 5000) -> Index:
    """Open (or create) `<state_dir>/index.db`. A symlinked database (or WAL)
    is refused: it could point at another SQLite file outside the repository."""
    db = state_dir / "index.db"
    for candidate in (db, db.with_name("index.db-wal"), db.with_name("index.db-shm")):
        if candidate.is_symlink():
            raise RuntimeError(f"{candidate} is a symlink; refusing to open it")
    return Index(db, busy_timeout_ms)


def fts_escape(query: str, prefix_min: int = 0) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms.

    Every term is wrapped in double quotes after splitting on non-word
    characters, so FTS5 operators (`OR`, `NEAR`, `*`, `^`, column filters,
    quotes) in user input are inert. With `prefix_min`, terms of at least that
    length also match as prefixes (`route` -> `router`, `routes`).
    """
    import re
    terms = [t for t in re.split(r"[^\w$_]+", query) if len(t) > 1]
    if not terms:
        return '""'
    return " OR ".join(f'"{t}"*' if prefix_min and len(t) >= prefix_min else f'"{t}"'
                       for t in terms[:32])


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
