"""Task-aware retrieval.

The problem this solves: Bob's context window is 270k tokens, but the *useful*
budget for a task is a few thousand. Handing it a whole repository is worse
than handing it nothing, because irrelevant files crowd out the ones that
matter and push the thread toward condensation.

So `repo-ai context "fix the login bug"` answers a narrower question: **which
15 files, and which lines within them, should Bob look at first?**

Ranking is a weighted blend of these signals. None of them is an embedding.

  lexical    BM25 over identifiers (3x) and doc text, via SQLite FTS5,
             scaled by IDF-weighted query-term coverage (an *absolute*
             measure, so an off-topic prompt cannot reach a high score)
  literal    paths, `@path` mentions, and stack-trace frames named in the prompt
  symbolic   exact/prefix match on symbol names mentioned in the prompt
  intent     the prompt's task class boosts directories and file roles
  structure  import-graph centrality — widely-imported files are load-bearing
  history    git recency and churn — recently-touched code is likely in scope
  proximity  neighbours of already-selected files (imports, importers,
             co-change partners, and the tests that cover them)

Every weight is a constant in `WEIGHTS` below. They are tuned, not learned,
and they are meant to be edited: if your repo ranks badly, change a number and
re-run. That transparency is the point — an embedding score cannot be debugged
by reading it. `repo-ai explain "<task>"` prints the per-signal breakdown.

Priors (centrality, recency, churn, intent role) only re-order files that
already have content evidence or are neighbours of one. A file never makes
the list on priors alone, and a prompt with no real evidence yields an empty
result (`confidence: none`) rather than padding.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import PurePosixPath

from .index import Index, fts_escape

# --------------------------------------------------------------------------
# Intent taxonomy
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Intent:
    name: str
    keywords: tuple[str, ...]
    path_hints: tuple[str, ...]
    role_boost: dict[str, float] = field(default_factory=dict)
    symbol_hints: tuple[str, ...] = ()
    # Files that *are* the answer for this intent, not merely near it. These
    # count as standalone evidence; `path_hints` only amplify other evidence.
    canonical: tuple[str, ...] = ()


INTENTS: tuple[Intent, ...] = (
    Intent(
        "auth",
        ("auth", "authn", "authz", "login", "logout", "signin", "sign-in", "signup",
         "session", "token", "jwt", "oauth", "oidc", "saml", "sso", "password",
         "credential", "permission", "role", "rbac", "acl", "authorize",
         "authenticate", "mfa", "2fa", "csrf", "cookie", "principal", "identity"),
        ("auth", "login", "session", "user", "account", "identity", "security",
         "middleware", "guard", "permission", "policy", "iam"),
        {"source": 1.0, "test": 0.55, "config": 0.5},
        ("login", "authenticate", "authorize", "verifyToken", "getSession",
         "currentUser", "requireAuth", "hasPermission"),
    ),
    Intent(
        "api",
        ("endpoint", "route", "rest", "api", "controller", "handler", "graphql",
         "resolver", "grpc", "openapi", "swagger", "request", "response",
         "serializer", "schema", "dto", "payload", "http", "webhook"),
        ("route", "routes", "api", "controller", "handler", "endpoint", "resource",
         "view", "resolver", "schema", "serializer", "dto", "graphql", "proto"),
        {"source": 1.0, "config": 0.6, "doc": 0.4},
        ("router", "controller", "handler", "resolver", "serializer"),
    ),
    Intent(
        "database",
        ("database", "db", "query", "sql", "orm", "migration", "schema", "table",
         "column", "index", "transaction", "repository", "dao", "entity", "model",
         "postgres", "mysql", "mongo", "redis", "seed", "n+1"),
        ("model", "models", "entity", "entities", "repository", "repositories",
         "migration", "migrations", "schema", "db", "database", "dao", "store",
         "persistence", "prisma", "sql"),
        {"source": 1.0, "config": 0.6},
        ("Model", "Entity", "Repository", "migrate", "query"),
    ),
    Intent(
        "ci",
        ("ci", "cd", "pipeline", "workflow", "build fail", "github action",
         "gitlab", "jenkins", "travis", "circleci", "release", "publish",
         "artifact", "runner", "job", "stage", "tekton", "azure pipeline"),
        (".github", "workflows", ".gitlab-ci", "jenkins", "ci", "cd", "pipeline",
         "scripts", "build", "release", ".circleci", "tekton"),
        {"config": 1.0, "infra": 0.9, "build": 0.9, "source": 0.3},
        canonical=(r"\.github/workflows/", r"\.gitlab-ci\.ya?ml$", r"(^|/)Jenkinsfile$",
                   r"\.circleci/", r"azure-pipelines\.ya?ml$", r"(^|/)\.travis\.ya?ml$",
                   r"(^|/)tekton/", r"(^|/)Makefile$"),
    ),
    Intent(
        "deploy",
        ("deploy", "deployment", "kubernetes", "k8s", "helm", "chart", "docker",
         "container", "image", "terraform", "infra", "cluster", "ingress",
         "manifest", "rollout", "environment", "staging", "production", "ansible"),
        ("deploy", "deployment", "k8s", "kubernetes", "helm", "charts", "terraform",
         "infra", "infrastructure", "docker", "ops", "manifests", "ansible"),
        {"infra": 1.0, "config": 0.8, "build": 0.7, "source": 0.25},
        canonical=(r"(^|/)Dockerfile", r"(^|/)docker-compose[^/]*\.ya?ml$",
                   r"(^|/)Chart\.ya?ml$", r"(^|/)values[^/]*\.ya?ml$",
                   r"\.tf$", r"(^|/)k8s/", r"(^|/)kubernetes/", r"(^|/)helm/",
                   r"(^|/)serverless\.ya?ml$"),
    ),
    Intent(
        "test",
        ("test", "tests", "spec", "unit test", "integration test", "e2e", "flaky",
         "coverage", "mock", "stub", "fixture", "assertion", "failing test",
         "snapshot", "regression test"),
        ("test", "tests", "spec", "__tests__", "e2e", "integration", "fixtures",
         "mocks", "cypress", "playwright"),
        {"test": 1.0, "fixture": 0.8, "source": 0.7, "config": 0.4},
    ),
    Intent(
        "frontend",
        ("component", "ui", "css", "style", "layout", "render", "hook", "state",
         "props", "page", "view", "button", "form", "modal", "responsive",
         "accessibility", "a11y", "tailwind", "dark mode", "client-side"),
        ("component", "components", "ui", "pages", "views", "styles", "css",
         "hooks", "layouts", "frontend", "web", "client", "app", "src/app"),
        {"source": 1.0, "config": 0.35},
        ("Component", "use", "render", "Page", "Layout"),
    ),
    Intent(
        "config",
        ("config", "configuration", "setting", "env", "environment variable",
         "feature flag", "toggle", "constant", "parameter", "yaml", "toml",
         "dotenv", "secret manager"),
        ("config", "configs", "settings", "conf", "env", "environments"),
        {"config": 1.0, "source": 0.6, "build": 0.5},
    ),
    Intent(
        "performance",
        ("slow", "performance", "perf", "latency", "optimize", "optimization",
         "memory leak", "cpu", "profil", "cache", "caching", "throughput",
         "bottleneck", "timeout", "n+1", "benchmark", "scale"),
        ("cache", "worker", "queue", "job", "batch", "pool", "benchmark"),
        {"source": 1.0, "test": 0.4, "config": 0.4},
    ),
    Intent(
        "security",
        ("security", "vulnerability", "cve", "injection", "xss", "sanitize",
         "escape", "encrypt", "decrypt", "hash", "tls", "ssl", "cors",
         "rate limit", "audit", "owasp", "secret"),
        ("security", "auth", "crypto", "middleware", "validation", "sanitiz",
         "policy", "guard"),
        {"source": 1.0, "config": 0.7, "infra": 0.5},
    ),
    Intent(
        "observability",
        ("log", "logging", "logger", "trace", "tracing", "metric", "monitor",
         "alert", "telemetry", "observability", "instrument", "span", "sentry",
         "datadog", "prometheus", "opentelemetry", "instana"),
        ("logging", "logger", "telemetry", "metrics", "monitoring", "observability",
         "tracing", "middleware"),
        {"source": 1.0, "config": 0.6, "infra": 0.5},
    ),
    Intent(
        "dependency",
        ("dependency", "dependencies", "upgrade", "bump", "version", "package",
         "vulnerable package", "npm audit", "peer dep", "lockfile", "migrate to",
         "deprecated"),
        ("package.json", "pyproject", "requirements", "pom.xml", "go.mod",
         "Cargo.toml", "Gemfile", "build.gradle"),
        {"build": 1.0, "config": 0.7, "source": 0.4},
        canonical=(r"(^|/)package\.json$", r"(^|/)pyproject\.toml$",
                   r"(^|/)requirements[^/]*\.txt$", r"(^|/)pom\.xml$",
                   r"(^|/)go\.mod$", r"(^|/)Cargo\.toml$", r"(^|/)Gemfile$",
                   r"(^|/)build\.gradle(\.kts)?$", r"(^|/)composer\.json$"),
    ),
    Intent(
        "docs",
        ("document", "documentation", "readme", "docstring", "comment", "explain",
         "guide", "tutorial", "changelog", "adr", "onboarding", "how does",
         "what is", "walk me through", "architecture"),
        ("docs", "doc", "documentation", "readme", "adr", "rfc"),
        {"doc": 1.0, "source": 0.6},
    ),
    Intent(
        "refactor",
        ("refactor", "rename", "extract", "move", "restructure", "clean up",
         "cleanup", "dedupe", "duplicate", "dead code", "simplify", "split",
         "modernize", "migrate"),
        (),
        {"source": 1.0, "test": 0.7},
    ),
    Intent(
        "bug",
        ("bug", "fix", "broken", "error", "exception", "crash", "fail", "failing",
         "traceback", "stack trace", "regression", "does not work", "doesn't work",
         "500", "404", "null", "undefined", "nan", "hang", "deadlock"),
        (),
        {"source": 1.0, "test": 0.8, "config": 0.4},
    ),
    Intent(
        "feature",
        ("add", "implement", "create", "build", "support", "introduce", "new",
         "feature", "enable", "extend"),
        (),
        {"source": 1.0, "test": 0.7, "doc": 0.35},
    ),
)

INTENT_BY_NAME = {intent.name: intent for intent in INTENTS}

# --------------------------------------------------------------------------
# Weights — edit these to retune ranking
# --------------------------------------------------------------------------
WEIGHTS: dict[str, float] = {
    "lexical": 5.0,        # BM25 x IDF term coverage on identifiers/doc text
    "symbol_exact": 6.0,   # prompt named a symbol that exists here
    "path_literal": 9.0,   # prompt named this path directly
    "intent_canonical": 5.5,  # file *is* the canonical artefact for this intent
    "intent_path": 2.4,    # path segment matches an intent hint
    "intent_role": 1.6,    # file role matches what this intent needs
    "centrality": 2.2,     # widely imported
    "recency": 1.5,        # touched recently
    "churn": 0.9,          # frequently changed
    "entrypoint": 1.2,
    "route_match": 4.0,    # prompt looks like a URL that this file serves
    "path_term": 3.0,      # the task's words name this file (stem tokens of the filename)
    "neighbour": 1.8,      # imported by / imports a selected file
    "coupling": 1.5,       # historically co-changed with a selected file
    "test_of": 1.8,        # tests a selected source file (import or naming link)
    "trace_frame": 8.0,    # prompt contains a stack-trace frame in this file
    "scope": 2.5,          # inside the requested --scope
    "generated_penalty": -6.0,
    "depth_penalty": -0.18,
    "vendor_penalty": -4.0,
}

_STOPWORDS = frozenset("""
a an the and or but if then else for while do to from in on at by of with
without into onto is are was were be been being have has had can could should
would will shall may might must not no yes it its this that these those there
here what when where which who whom how why all any some each every please
help me my our your their i we you he she they them us make sure need want
add fix update change use using used get set new old also just very really
thanks thank ok okay great good nice looks look like so too than then just
let lets let's tell show give find explain describe write code file files
something anything everything way thing things work works working does did
conversation chat summarize summary summarise earlier previous above below far
difference between simple terms meaning mean
""".split())

_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
_CAMEL_RE = re.compile(r"\b([a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*)\b")
_PASCAL_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
_DOTTED_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+)\.([a-z_][A-Za-z0-9_]+)\b")
_PATH_RE = re.compile(r"(?<![\w@])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6}|[\w-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs|vue|svelte|ya?ml|toml|json|md|sql|sh))\b")
_MENTION_RE = re.compile(r"(?:^|\s)@/?((?:[\w.-]+/)*[\w.-]+)")
_QUOTED_RE = re.compile(r"[\"'`]([^\"'`\n]{2,80})[\"'`]")
_URLPATH_RE = re.compile(r"(?<![\w.])(/[a-zA-Z0-9_\-/{}:.]{2,80})")
_SNAKE_RE = re.compile(r"\b([a-z]+(?:_[a-z0-9]+)+)\b")
_SUBWORD_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# Stack-trace frames: Python, Node/JS, Go/Rust/C-style path:line, Java/Kotlin.
_TRACE_RES = (
    re.compile(r'File "([^"]+)", line (\d+)'),
    re.compile(r"\(?((?:[\w.@-]+/)*[\w.@-]+\.(?:js|jsx|ts|tsx|mjs|cjs)):(\d+)(?::\d+)?\)?"),
    re.compile(r"((?:[\w.-]+/)*[\w.-]+\.(?:go|rs|c|cc|cpp|h|hpp|rb|php|py|cs|swift|scala)):(\d+)"),
    re.compile(r"at [\w.$]+\(([\w$]+\.(?:java|kt|scala)):(\d+)\)"),
)
_ACK_RE = re.compile(
    r"(?i)^\s*(yes|yep|yeah|no|nope|ok(ay)?|sure|thanks?( you)?|thx|great|cool|nice|perfect|"
    r"continue|go( ahead)?|do it|proceed|sounds good|lgtm|looks good|got it|done|next|"
    r"please continue|keep going)\b[\s.!,]*(please|thanks|then)?[\s.!]*$")


def split_identifier(name: str) -> list[str]:
    """`getUserById` -> [get, user, by, id]; `validate_credentials` -> [validate, credentials]."""
    parts: list[str] = []
    for chunk in re.split(r"[_\-$.]+", name):
        parts.extend(m.lower() for m in _SUBWORD_RE.findall(chunk))
    return [p for p in parts if len(p) > 1]


def is_trivial_prompt(prompt: str, min_chars: int = 20) -> bool:
    text = prompt.strip()
    return len(text) < min_chars or bool(_ACK_RE.match(text))


@dataclass(slots=True)
class Query:
    text: str
    intents: list[str]
    identifiers: list[str]
    paths: list[str]
    url_paths: list[str]
    terms: list[str]
    frames: list[tuple[str, int]] = field(default_factory=list)


# Keywords that change meaning with a suffix: "documented"/"commented" in a
# bug report are not requests about documentation.
_WHOLE_WORD_KEYWORDS = frozenset({"document", "comment"})


def classify(prompt: str) -> Query:
    lower = prompt.lower()
    scores: dict[str, float] = {}
    for intent in INTENTS:
        hits = 0.0
        for kw in intent.keywords:
            if " " in kw:
                if kw in lower:
                    hits += 1.6
            elif len(kw) <= 4 or kw in _WHOLE_WORD_KEYWORDS:
                # Short keywords match whole words only: otherwise "log"
                # fires on "login" and "db" on "dbg".
                if re.search(rf"\b{re.escape(kw)}\b", lower):
                    hits += 1.0
            elif re.search(rf"\b{re.escape(kw)}\w{{0,3}}\b", lower):
                hits += 1.0
        if hits:
            scores[intent.name] = hits
    # "bug" and "feature" are weak priors; only keep them when nothing stronger.
    strong = {k: v for k, v in scores.items() if k not in {"bug", "feature", "refactor"}}
    ranked = sorted((strong or scores).items(), key=lambda kv: (-kv[1], kv[0]))
    intents = [name for name, _ in ranked[:3]]
    if not intents:
        intents = ["feature"]
    for weak in ("bug", "refactor"):
        if weak in scores and weak not in intents and len(intents) < 4:
            intents.append(weak)

    frames: list[tuple[str, int]] = []
    for pattern in _TRACE_RES:
        for path, line in pattern.findall(prompt):
            frame = (path.lstrip("./"), int(line))
            if frame not in frames:
                frames.append(frame)
    frames = frames[:12]

    identifiers: list[str] = []
    for pattern in (_CAMEL_RE, _SNAKE_RE, _PASCAL_RE):
        identifiers.extend(pattern.findall(prompt))
    for cls_name, member in _DOTTED_RE.findall(prompt):
        identifiers.extend([cls_name, member])
    # a prompt that is one name is the name the user looks for, even a stopword (a function named `mean`, `get`
    # or `update`); within prose a stopword stays one, so the ranking of prose prompts is unchanged
    alone = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]{2,})\s*", prompt)
    if alone and alone.group(1).lower() in _STOPWORDS:
        identifiers.append(alone.group(1))
    for quoted in _QUOTED_RE.findall(prompt):
        # A quoted plain word ("error", "message") is prose or a JSON key, not
        # a code identifier; require identifier shape (snake, camel, dotted...).
        if re.fullmatch(r"[\w.$-]+", quoted) and re.search(r"[_.$]|[a-z][A-Z]|^[A-Z][a-z]+[A-Z]",
                                                           quoted):
            identifiers.append(quoted)
    identifiers = [i for i in dict.fromkeys(identifiers) if len(i) >= 3][:20]

    paths = list(dict.fromkeys(_PATH_RE.findall(prompt) + _MENTION_RE.findall(prompt)
                               + [f for f, _ in frames]))[:16]
    url_paths = [
        u for u in dict.fromkeys(_URLPATH_RE.findall(prompt))
        if u not in paths and "." not in PurePosixPath(u).name
    ][:8]

    words: list[str] = []
    for w in _IDENT_RE.findall(prompt):
        if w.lower() in _STOPWORDS or len(w) <= 2:
            continue
        words.append(w)
        if ("_" in w or any(c.isupper() for c in w[1:])):
            words.extend(p for p in split_identifier(w) if p not in _STOPWORDS and len(p) > 2)
    terms = list(dict.fromkeys(words))[:30]

    return Query(prompt, intents, identifiers, paths, url_paths, terms, frames)


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Hit:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    lines: list[tuple[int, int, str]] = field(default_factory=list)  # start, end, label
    role: str = ""
    language: str = ""
    total_lines: int = 0
    component: str = ""
    summary: str = ""
    evidence: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Retrieval:
    query: Query
    hits: list[Hit]
    confidence: str  # high | medium | low | none
    signals: dict[str, float] = field(default_factory=dict)
    scope: str = ""
    cached: bool = False  # served from the query cache


@lru_cache(maxsize=64)
def _canonical_re(patterns: tuple[str, ...]) -> re.Pattern[str] | None:
    if not patterns:
        return None
    return re.compile("|".join(patterns), re.IGNORECASE)


def _canonical_match(intent: Intent, path: str) -> bool:
    pattern = _canonical_re(intent.canonical)
    return bool(pattern and pattern.search(path))


_VENDOR_RE = re.compile(r"(^|/)(vendor|third_party|node_modules|dist|build|\.min\.)")

# Files that carry a name but almost no answerable content.
_LOW_VALUE_RE = re.compile(
    r"(^|/)(\.gitignore|\.gitattributes|\.dockerignore|\.editorconfig|"
    r"\.gitkeep|LICENSE[^/]*|NOTICE|CODEOWNERS|\.npmrc|\.nvmrc|"
    r"CODE_OF_CONDUCT\.md|CHANGELOG\.md)$"
    r"|\.lock(\.hcl)?$|\.lock$|-lock\.(json|yaml)$",
    re.IGNORECASE,
)

# Signals that count as *content evidence* (as opposed to priors).
_EVIDENCE_KEYS = frozenset({"lexical", "path_term", "symbol_exact", "path_literal", "route_match",
                            "intent_canonical", "trace_frame"})


def _term_document_sets(index: Index, terms: list[str]) -> tuple[dict[str, set[str]], int]:
    total = index.conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"] or 1
    out: dict[str, set[str]] = {}
    for term in terms[:16]:
        rows = index.search(fts_escape(term, prefix_min=5), limit=400)
        out[term] = {r["path"] for r in rows}
    return out, total


def retrieve(
    index: Index,
    prompt: str,
    max_files: int = 14,
    include_tests: bool = True,
    scope_paths: set[str] | None = None,
    scope_label: str = "",
) -> tuple[Query, list[Hit]]:
    """Backwards-compatible wrapper around `search_task` (v0.4 signature)."""
    result = search_task(index, prompt, max_files, include_tests, scope_paths, scope_label)
    return result.query, result.hits


def search_task(
    index: Index,
    prompt: str,
    max_files: int = 14,
    include_tests: bool = True,
    scope_paths: set[str] | None = None,
    scope_label: str = "",
    prior: dict[str, float] | None = None,
) -> Retrieval:
    query = classify(prompt)
    scores: dict[str, float] = defaultdict(float)
    parts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    reasons: dict[str, list[str]] = defaultdict(list)
    line_hints: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    signals: dict[str, float] = {}

    def add(path: str, weight_key: str, factor: float, reason: str = "") -> None:
        if not path or path not in file_rows:
            return
        value = WEIGHTS[weight_key] * factor
        scores[path] += value
        parts[path][weight_key] += value
        if reason and reason not in reasons[path]:
            reasons[path].append(reason)

    file_rows = {row["path"]: row for row in index.all_files()}
    if not file_rows:
        return Retrieval(query, [], "none", signals, scope_label)

    # --- 1. literal paths, mentions and stack-trace frames -----------------
    def resolve_literal(raw: str) -> list[str]:
        raw = raw.lstrip("./")
        if raw in file_rows:
            return [raw]
        matches = [p for p in file_rows if p.endswith("/" + raw)]
        return matches if len(matches) <= 3 else []

    frame_paths: set[str] = set()
    for raw, line in query.frames:
        for path in resolve_literal(raw):
            frame_paths.add(path)
            add(path, "trace_frame", 1.0, f"stack frame line {line}")
            line_hints[path].append((max(1, line - 8), line + 8, f"frame L{line}"))
    for raw in query.paths:
        for path in resolve_literal(raw):
            if path not in frame_paths:
                add(path, "path_literal", 1.0, "named in the request")

    # --- 2. lexical: BM25 x IDF-weighted term coverage -----------------------
    if query.terms:
        term_docs, total = _term_document_sets(index, query.terms)
        idf = {t: math.log(1 + total / len(docs)) for t, docs in term_docs.items() if docs}
        known_terms = len(idf)
        signals["vocabulary_hit"] = round(known_terms / max(len(term_docs), 1), 3)
        idf_total = sum(idf.values()) or 1.0
        coverage: dict[str, float] = defaultdict(float)
        matched: dict[str, int] = defaultdict(int)
        for term, docs in term_docs.items():
            for path in docs:
                coverage[path] += idf.get(term, 0.0)
                matched[path] += 1
        if coverage:
            for path in coverage:
                coverage[path] /= idf_total
            fts_query = fts_escape(" ".join(query.terms), prefix_min=5)
            rows = index.search(fts_query, limit=150)
            bm = {r["path"]: r["score"] for r in rows}
            if bm:
                best, worst = min(bm.values()), max(bm.values())
                span = (worst - best) or 1.0
            # Ranking uses coverage *relative to the best file*: a long bug
            # report dilutes absolute coverage across many incidental words,
            # which let structural priors (hubs, recency) outrank the file the
            # report is about. Absolute coverage still drives confidence (§7).
            top_cov = max(coverage.values()) or 1.0
            for path, cov in coverage.items():
                norm = (worst - bm[path]) / span if path in bm else 0.0
                strength = (cov / top_cov) * (0.55 + 0.45 * norm)
                if cov * signals["vocabulary_hit"] > 0.02 and strength > 0.05:
                    add(path, "lexical", strength, "keyword match")
            best_path = max(coverage, key=lambda p: (coverage[p], p))
            signals["best_coverage"] = round(coverage[best_path], 3)
            signals["best_matched_terms"] = max(matched.values())

    # --- 2b. filename terms --------------------------------------------------
    # "interest" in a bug report and InterestCalculator.java: the file's own
    # name is the strongest cheap evidence of what it is about.
    if query.terms:
        stems = {_stem(t) for t in query.terms if len(t) >= 4}
        prefixes = {s[:4] for s in stems}
        for path in file_rows:
            tokens = _filename_tokens(path.rsplit("/", 1)[-1].split(".", 1)[0])
            if not tokens or not any(tok[:4] in prefixes for tok in tokens):
                continue
            hit = sum(1 for tok in tokens if tok in stems)
            if hit:
                add(path, "path_term", hit / len(tokens), "named like the task")

    # --- 3. symbols ----------------------------------------------------------
    for ident in query.identifiers[:10]:
        rows = index.find_symbol(ident, limit=12)
        exact = [r for r in rows if r["name"] == ident or r["name"].lower() == ident.lower()]
        for row in exact or rows[:4]:
            factor = 1.0 if row in exact else 0.35
            add(row["path"], "symbol_exact", factor, f"defines `{row['name']}`")
            line_hints[row["path"]].append(
                (row["line"], row["end_line"], f"{row['kind']} {row['name']}"))
        if exact:
            signals["symbol_hits"] = signals.get("symbol_hits", 0) + 1

    # --- 4. routes -------------------------------------------------------------
    if query.url_paths or "api" in query.intents:
        for row in index.routes(1200):
            pattern = row["path_pattern"]
            for url in query.url_paths:
                if pattern == url or pattern.rstrip("/").endswith(url.rstrip("/")):
                    add(row["file"], "route_match", 1.0, f"serves {row['method']} {pattern}")
                    line_hints[row["file"]].append(
                        (row["line"], row["line"] + 20, f"{row['method']} {pattern}"))
                    signals["route_hits"] = signals.get("route_hits", 0) + 1
            for term in query.terms:
                if len(term) > 3 and term.lower() in pattern.lower():
                    add(row["file"], "route_match", 0.4, f"route {row['method']} {pattern}")

    # --- 5. intent shaping -----------------------------------------------------
    # Prose (READMEs, guides) shares vocabulary with any bug report; unless
    # the request is about documentation, its lexical match counts less.
    if "docs" not in query.intents:
        for path, value in list(parts.items()):
            doc_row = file_rows.get(path)
            if doc_row is not None and doc_row["role"] == "doc" and value.get("lexical"):
                cut = value["lexical"] * 0.55
                scores[path] -= cut
                parts[path]["lexical"] -= cut
    evidenced = {p for p, s in scores.items() if s > 0}
    active = [INTENT_BY_NAME[name] for name in query.intents if name in INTENT_BY_NAME]
    for path, row in file_rows.items():
        lower_path = path.lower()
        role = row["role"]
        damp = 1.0 if path in evidenced else 0.45

        for rank, intent in enumerate(active):
            rank_decay = 1.0 / (1 + rank * 0.6)
            decay = rank_decay * damp
            if _canonical_match(intent, path):
                add(path, "intent_canonical", rank_decay, f"canonical {intent.name} file")
            for hint in intent.path_hints:
                if hint in lower_path:
                    add(path, "intent_path", decay, f"{intent.name} path")
                    break
            boost = intent.role_boost.get(role)
            if boost:
                add(path, "intent_role", boost * decay)

        if _LOW_VALUE_RE.search(path):
            scores[path] -= 4.0
            parts[path]["low_value"] -= 4.0

        # Structural priors re-order evidenced files; on a file with no
        # content evidence of its own they count half (hubs are everywhere).
        damp_prior = 1.0 if path in evidenced else 0.5
        add(path, "centrality", (row["centrality"] or 0.0) * damp_prior)
        add(path, "recency", (row["recency"] or 0.0) * damp_prior)
        if row["churn"]:
            add(path, "churn", min(row["churn"] / 3000.0, 1.0) * damp_prior)
        if row["is_entrypoint"]:
            add(path, "entrypoint", damp_prior, "entrypoint")
        if role == "generated":
            add(path, "generated_penalty", 1.0)
        if _VENDOR_RE.search(path):
            add(path, "vendor_penalty", 1.0)
        add(path, "depth_penalty", float(path.count("/")))
        if not include_tests and role == "test":
            scores[path] -= 8.0
            parts[path]["excluded_tests"] -= 8.0
        if scope_paths is not None and path in scope_paths:
            add(path, "scope", 1.0, f"in scope ({scope_label})" if scope_label else "in scope")

    evidence = {p: sum(v for k, v in parts[p].items() if k in _EVIDENCE_KEYS) for p in parts}


    # --- 6. neighbourhood expansion from evidenced seeds ---------------------
    seeds = sorted(((p, s) for p, s in scores.items() if evidence.get(p, 0) > 0),
                   key=lambda kv: (-kv[1], kv[0]))[:8]
    neighbours: set[str] = set()
    for path, base in seeds:
        if base <= 0:
            continue
        if base <= 0:
            continue
        factor = min(base / 20.0, 1.0)
        name = PurePosixPath(path).name
        for importer in index.importers_of(path, limit=12):
            add(importer, "neighbour", factor, f"imports {name}")
            neighbours.add(importer)
        for row in index.imports_of(path, limit=25):
            if row["resolved_path"]:
                add(row["resolved_path"], "neighbour", factor, f"imported by {name}")
                neighbours.add(row["resolved_path"])
        for peer in index.coupled_with(path, limit=5):
            add(peer, "coupling", factor, f"co-changes with {name}")
            neighbours.add(peer)
        if include_tests:
            for row in index.tests_for(path):
                link = 1.0 if row["evidence"] == "import" else 0.8
                add(row["test_path"], "test_of", factor * link * 1.6, f"tests {name}")
                neighbours.add(row["test_path"])

    # --- 7. confidence -----------------------------------------------------------
    strong = any(parts[p].get(k, 0) > 0 for p in parts
                 for k in ("trace_frame", "path_literal", "route_match"))
    strong = strong or signals.get("symbol_hits", 0) > 0
    lexical = signals.get("best_coverage", 0.0) * signals.get("vocabulary_hit", 0.0)
    canonical = any(parts[p].get("intent_canonical", 0) > 0 and parts[p].get("lexical", 0) > 0
                    for p in parts)
    multi = signals.get("best_matched_terms", 0) >= 2
    if strong or (lexical >= 0.45 and multi):
        confidence = "high"
    elif (lexical >= 0.25 and multi) or canonical:
        confidence = "medium"
    elif lexical > 0:
        confidence = "low"
    else:
        confidence = "none"
    signals["lexical_strength"] = round(lexical, 3)

    # Promoted outcome prior (episodes.py): re-orders files that already made
    # the candidate list, by at most ±30 % of their own score; never adds one.
    if prior:
        from .episodes import apply_prior
        for path, delta in prior.items():
            if path in scores and (evidence.get(path, 0) > 0 or path in neighbours):
                bonus = apply_prior(scores[path], delta) - scores[path]
                scores[path] += bonus
                parts[path]["outcome_prior"] += bonus
                if delta > 0 and "worked in past sessions" not in reasons[path]:
                    reasons[path].append("worked in past sessions")

    # --- 8. assemble ---------------------------------------------------------------
    hits: list[Hit] = []
    top = max((s for p, s in scores.items() if evidence.get(p, 0) > 0 or p in neighbours),
              default=0.0)
    floor = max(0.8, top * 0.22)
    for path, score in scores.items():
        if score <= floor:
            continue
        if evidence.get(path, 0) <= 0 and path not in neighbours:
            continue  # priors alone never put a file on the list
        if scope_paths is not None and path not in scope_paths and path not in neighbours:
            continue
        row = file_rows[path]
        hints = line_hints.get(path, [])
        if not hints and evidence.get(path, 0) > 0 and row["role"] in {"source", "test"}:
            hints = _symbol_ranges_for_terms(index, path, query.terms)
        merged = _merge_ranges(hints, row["lines"])
        hits.append(Hit(
            path=path, score=round(score, 2), reasons=reasons[path][:4],
            lines=merged, role=row["role"], language=row["language"],
            total_lines=row["lines"], component=row["component"],
            summary=row["doc_summary"], evidence=round(evidence.get(path, 0.0), 2),
            breakdown={k: round(v, 2) for k, v in sorted(parts[path].items()) if abs(v) >= 0.01},
        ))

    hits.sort(key=lambda h: (-h.score, h.path))
    if confidence == "none":
        hits = []
    hits = _diversify(hits, max_files)
    if include_tests:
        hits = _promote_test(index, hits)
    return Retrieval(query, hits, confidence, signals, scope_label)


def _promote_test(index: Index, hits: list[Hit], within: int = 5) -> list[Hit]:
    """Make sure the shortlist's head carries a test for its top source file.

    A fix without its test is half a context; this moves the strongest
    import-linked test of the top two source hits into the first `within`.
    """
    head = hits[:within]
    if any(h.role == "test" for h in head) or len(hits) <= within:
        return hits
    positions = {h.path: i for i, h in enumerate(hits)}
    for top in [h for h in head if h.role == "source"][:2]:
        for row in index.tests_for(top.path):
            idx = positions.get(row["test_path"])
            if idx is not None and idx >= within:
                test = hits.pop(idx)
                test.reasons = [*test.reasons, "test for top result"][:4]
                hits.insert(within - 1, test)
                return hits
    return hits


@lru_cache(maxsize=8192)
def _filename_tokens(stem: str) -> tuple[str, ...]:
    return tuple(_stem(tok) for tok in split_identifier(stem) if len(tok) >= 4)


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in ("ations", "ation", "ings", "ing", "ers", "er", "ies", "es", "ed", "s", "ion"):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _symbol_ranges_for_terms(index: Index, path: str, terms: list[str],
                             limit: int = 2) -> list[tuple[int, int, str]]:
    """Line ranges of the symbols in `path` whose name shares a word with the task."""
    stems = {_stem(t) for t in terms if len(t) >= 4}
    if not stems:
        return []
    scored: list[tuple[int, int, int, str]] = []
    for row in index.symbols_for(path):
        words = {_stem(w) for w in split_identifier(row["name"]) if len(w) >= 4}
        overlap = sum(1 for w in words for s in stems if w.startswith(s) or s.startswith(w))
        if overlap:
            scored.append((-overlap, row["line"], row["end_line"], f"{row['kind']} {row['name']}"))
    scored.sort()
    return [(line, end, label) for _, line, end, label in scored[:limit]]


def _merge_ranges(
    ranges: list[tuple[int, int, str]], file_lines: int, pad: int = 6
) -> list[tuple[int, int, str]]:
    if not ranges:
        return []
    expanded = sorted(
        (max(1, s - pad), min(file_lines or e + pad, e + pad), label)
        for s, e, label in ranges
    )
    merged: list[tuple[int, int, str]] = []
    for start, end, label in expanded:
        if merged and start <= merged[-1][1] + 4:
            prev_start, prev_end, prev_label = merged[-1]
            labels = prev_label if label in prev_label else f"{prev_label}, {label}"
            merged[-1] = (prev_start, max(prev_end, end), labels[:120])
        else:
            merged.append((start, end, label))
    return merged[:5]


def _diversify(hits: list[Hit], limit: int) -> list[Hit]:
    """Avoid returning 14 files from the same directory."""
    if len(hits) <= limit:
        return hits
    per_dir: dict[str, int] = defaultdict(int)
    cap = max(3, limit // 3)
    chosen: list[Hit] = []
    overflow: list[Hit] = []
    for hit in hits:
        directory = str(PurePosixPath(hit.path).parent)
        if per_dir[directory] < cap:
            per_dir[directory] += 1
            chosen.append(hit)
        else:
            overflow.append(hit)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        chosen.extend(overflow[: limit - len(chosen)])
    chosen.sort(key=lambda h: (-h.score, h.path))
    return chosen


def adaptive_cut(hits: list[Hit], hard_max: int) -> list[Hit]:
    """For prompt injection: keep the clear leaders, drop the long tail."""
    if not hits:
        return []
    top = hits[0].score
    kept = [h for h in hits if h.score >= top * 0.35]
    return kept[:hard_max]


# --------------------------------------------------------------------------
# Scopes
# --------------------------------------------------------------------------
def scope_files(index: Index, scope: str, changed: list[str] | None = None) -> set[str] | None:
    """Resolve a --scope expression to a set of indexed paths (None = no scope)."""
    if not scope:
        return None
    kind, _, arg = scope.partition(":")
    rows = index.all_files()
    if kind in {"diff", "branch"}:
        wanted = set(changed or [])
        return {r["path"] for r in rows if r["path"] in wanted}
    if kind == "component":
        return {r["path"] for r in rows if r["component"] == arg or r["path"].startswith(arg.rstrip("/") + "/")}
    if kind in {"lang", "language"}:
        return {r["path"] for r in rows if r["language"].lower() == arg.lower()}
    if kind == "path":
        return {r["path"] for r in rows if fnmatch(r["path"], arg) or r["path"].startswith(arg.rstrip("/") + "/")}
    if kind == "tests":
        return {r["path"] for r in rows if r["role"] == "test"}
    raise ValueError(f"unknown scope {scope!r} (diff, branch, component:<name>, lang:<language>, "
                     "path:<glob>, tests)")


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def cache_key(prompt: str, fingerprint: str, **options: object) -> str:
    from . import __version__
    weights = json.dumps(WEIGHTS, sort_keys=True)
    payload = json.dumps({"p": " ".join(prompt.split()), "f": fingerprint, "w": weights,
                          "v": __version__,
                          "o": options}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def to_cache(result: Retrieval) -> str:
    """Cache payload. Nothing derived from the prompt's text is stored (the key
    is a hash); the query is re-classified from the live prompt on a hit."""
    return json.dumps({
        "v": 2,
        "hits": [{"path": h.path, "score": h.score, "reasons": h.reasons, "lines": h.lines,
                  "role": h.role, "language": h.language, "total_lines": h.total_lines,
                  "component": h.component, "summary": h.summary, "evidence": h.evidence,
                  "breakdown": h.breakdown} for h in result.hits],
        "confidence": result.confidence, "signals": result.signals, "scope": result.scope,
    })


def from_cache(text: str, prompt: str = "") -> Retrieval | None:
    try:
        data = json.loads(text)
        if data.get("v") != 2 or "query" in data:
            return None  # an older entry that held prompt text: never served
        query = classify(prompt)
        hits = [Hit(path=h["path"], score=h["score"], reasons=h["reasons"],
                    lines=[tuple(x) for x in h["lines"]], role=h["role"], language=h["language"],
                    total_lines=h["total_lines"], component=h["component"], summary=h["summary"],
                    evidence=h.get("evidence", 0.0), breakdown=h.get("breakdown", {}))
                for h in data["hits"]]
        return Retrieval(query, hits, data["confidence"], data.get("signals", {}), data.get("scope", ""))
    except (KeyError, TypeError, ValueError):
        return None


def cached_search(index: Index, prompt: str, *, max_files: int, include_tests: bool,
                  scope: str = "", scope_paths: set[str] | None = None,
                  use_cache: bool = True, prior: dict[str, float] | None = None) -> Retrieval:
    fingerprint = index.get_meta("fingerprint")
    cacheable = use_cache and bool(fingerprint) and scope.split(":")[0] not in {"diff", "branch"}
    prior_sig = hashlib.sha256(json.dumps(prior or {}, sort_keys=True).encode()).hexdigest()[:12]
    key = cache_key(prompt, fingerprint, m=max_files, t=include_tests, s=scope,
                    p=prior_sig) if cacheable else ""
    if key:
        hit = index.cache_get(key)
        if hit:
            cached = from_cache(hit, prompt)
            if cached is not None:
                cached.cached = True
                return cached
    result = search_task(index, prompt, max_files, include_tests, scope_paths, scope, prior)
    if key:
        index.cache_put(key, to_cache(result))
    return result


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    """Rough but stable: ~4 chars/token for English + code."""
    return max(1, len(text) // 4)


def render_context(
    query: Query,
    hits: list[Hit],
    facts_summary: str = "",
    budget_tokens: int = 6000,
    mention_prefix: str = "@/",
    quarantined: frozenset[str] = frozenset(),
) -> str:
    """Markdown block for Bob (emits `@/path:start-end` mentions, Bob's syntax)."""
    hits = [h for h in hits if h.path not in quarantined]
    lines: list[str] = []
    lines.append("<repo-ai-context>")
    lines.append(
        f"Retrieved by repo-ai for this request. Task class: "
        f"{', '.join(query.intents)}. Start with these files; ignore the rest of "
        f"the repository unless they prove insufficient."
    )
    if facts_summary:
        lines.append("")
        lines.append(facts_summary.strip())
    lines.append("")
    lines.append("| # | File | Why | Look at |")
    lines.append("|---|------|-----|---------|")

    mentions: list[str] = []
    for idx, hit in enumerate(hits, start=1):
        if hit.lines:
            spans = ", ".join(f"L{s}-{e}" for s, e, _ in hit.lines[:3])
            labels = "; ".join(label for _, _, label in hit.lines[:2])
            look = f"{spans} ({labels})" if labels else spans
            mentions.append(f"{mention_prefix}{hit.path}:{hit.lines[0][0]}-{hit.lines[0][1]}")
        else:
            look = f"whole file ({hit.total_lines} lines)" if hit.total_lines < 400 else "skim first"
            mentions.append(f"{mention_prefix}{hit.path}")
        why = ", ".join(hit.reasons) or hit.role
        summary = f" — {_clean(hit.summary)}" if hit.summary else ""
        lines.append(f"| {idx} | `{hit.path}`{summary} | {why} | {look} |")
        if estimate_tokens("\n".join(lines)) > budget_tokens:
            lines.append(f"| … | _{len(hits) - idx} more suppressed by token budget_ | | |")
            break

    lines.append("")
    lines.append("Ready-to-use mentions: " + " ".join(mentions[:12]))
    lines.append("</repo-ai-context>")
    return "\n".join(lines)


def _clean(text: str) -> str:
    """Single line, no table/markup breakers, bounded."""
    return re.sub(r"[\x00-\x1f|`<>]+", " ", text).strip()[:120]


def render_claude(result: Retrieval, budget_tokens: int, verify: str = "",
                  quarantined: frozenset[str] = frozenset(), max_chars: int = 9000) -> str:
    """Compact shortlist for Claude Code (plain paths with :line ranges).

    Hard limits: `budget_tokens` and `max_chars` (Claude Code caps hook context
    at 10,000 characters). Returns "" when there is nothing worth injecting.
    """
    hits = [h for h in result.hits if h.path not in quarantined]
    if not hits:
        return ""
    header = (f'<repo-ai-context confidence="{result.confidence}" task="{", ".join(result.query.intents)}">\n'
              "Files likely relevant to this request (ranked by repo-ai; read the line ranges first, "
              "verify before relying on them):")
    footer = "</repo-ai-context>"
    lines = [header]
    for idx, hit in enumerate(hits, start=1):
        loc = hit.path
        if hit.lines:
            loc += ":" + ",".join(f"{s}-{e}" for s, e, _ in hit.lines[:2])
        why = "; ".join(hit.reasons[:3]) or hit.role
        summary = f" — {_clean(hit.summary)}" if hit.summary else ""
        entry = f"{idx}. {loc}{summary} ({why})"
        candidate = "\n".join([*lines, entry, footer])
        if estimate_tokens(candidate) > budget_tokens or len(candidate) > max_chars:
            break
        lines.append(entry)
    if len(lines) == 1:
        return ""
    if verify:
        tail = f"Verify with: `{verify}`"
        if estimate_tokens("\n".join([*lines, tail, footer])) <= budget_tokens:
            lines.append(tail)
    lines.append(footer)
    return "\n".join(lines)


def render_json(query: Query, hits: list[Hit], confidence: str = "",
                signals: dict[str, float] | None = None) -> dict[str, object]:
    return {
        "prompt": query.text,
        "intents": query.intents,
        "identifiers": query.identifiers,
        "paths": query.paths,
        "url_paths": query.url_paths,
        "frames": [list(f) for f in query.frames],
        "confidence": confidence,
        "signals": signals or {},
        "results": [
            {
                "path": h.path,
                "score": h.score,
                "evidence": h.evidence,
                "breakdown": h.breakdown,
                "role": h.role,
                "language": h.language,
                "component": h.component,
                "lines": h.total_lines,
                "reasons": h.reasons,
                "ranges": [{"start": s, "end": e, "label": lb} for s, e, lb in h.lines],
                "mention": (f"@/{h.path}:{h.lines[0][0]}-{h.lines[0][1]}"
                            if h.lines else f"@/{h.path}"),
            }
            for h in hits
        ],
    }


def render_explain(result: Retrieval) -> str:
    q = result.query
    out = [f"task classes: {', '.join(q.intents)}",
           f"terms: {', '.join(q.terms) or '-'}",
           f"identifiers: {', '.join(q.identifiers) or '-'}",
           f"paths/frames: {', '.join(q.paths) or '-'}",
           f"confidence: {result.confidence}  "
           + "  ".join(f"{k}={v}" for k, v in sorted(result.signals.items())),
           ""]
    if not result.hits:
        out.append("no results (no content evidence for this prompt)")
        return "\n".join(out)
    keys = sorted({k for h in result.hits for k in h.breakdown})
    out.append(f"{'#':>2}  {'score':>6}  {'evid':>5}  path")
    for idx, hit in enumerate(result.hits, start=1):
        out.append(f"{idx:>2}  {hit.score:6.2f}  {hit.evidence:5.2f}  {hit.path}")
        detail = ", ".join(f"{k}={hit.breakdown[k]:+.2f}" for k in keys if k in hit.breakdown)
        out.append(f"    {detail}")
        if hit.reasons:
            out.append(f"    why: {'; '.join(hit.reasons)}")
    return "\n".join(out)
