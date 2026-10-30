"""Skill Radar: evidence-driven discovery of public Agent Skills.

Nothing here touches the network unless the user runs
`repo-ai skills discover --online`. Normal `init` and `update` never do.

**Profile.** The Project Capability Profiler derives a capability profile
from repo-ai's own index: languages, frameworks, test and CI tooling,
routes, migrations, frontend components, and recorded friction. A
capability *gap* is proposed only with repository evidence (for example,
"42 React components, no accessibility test dependency"), never merely
because a framework is present.

**Queries.** Search queries are built only from a fixed public vocabulary
(technology names from repo-ai's detection catalogues, plus generic
capability words). Repository text, paths, names and identifiers are never
sent.

**Providers.**

==============  ===========================================================
anthropic       github.com/anthropics/skills (official)
vercel          github.com/vercel-labs/agent-skills (official)
github          GitHub code search for SKILL.md (authenticated through gh
                or $GITHUB_TOKEN; 10 code searches/minute)
marketplace     `.claude-plugin/marketplace.json` repos the user configured
publishers      trusted owners/repos the user configured
skills.sh       documented API; every endpoint needs a Vercel OIDC token
                ($SKILLS_SH_TOKEN). Skipped without one
==============  ===========================================================

Every candidate is pinned to an immutable commit SHA and blob SHAs. Calls
are bounded (request cap, timeouts, rate-limit headers), cached on disk
with a TTL, and restricted to fixed API hosts: no user-supplied URL is
fetched except `https://github.com/<owner>/<repo>/…`, which is parsed into
API calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

API_HOSTS = frozenset({"api.github.com", "skills.sh"})
# GitHub serves repository tarballs from codeload (the only redirect followed).
DOWNLOAD_HOSTS = frozenset({"codeload.github.com"})
MAX_TARBALL = 60_000_000
CACHE_TTL_S = 24 * 3600
MAX_REQUESTS = 80
CLI_MAX_REQUESTS = 60      # `--max-requests` default for discover, install and updates
VET_MAX_REQUESTS = 400     # `skills vet` default: one SKILL.md blob per skill, plus files
VET_LIMIT = 200            # `skills vet --vet-limit` default
TIMEOUT_S = 15
OFFICIAL = {"anthropic": ("anthropics", "skills"), "vercel": ("vercel-labs", "agent-skills")}
KNOWN_PUBLISHERS = {"anthropics", "vercel-labs", "openai", "github", "microsoft", "google",
                    "aws", "cloudflare", "supabase", "stripe", "clickhouse"}


class RadarError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# capability profile
# --------------------------------------------------------------------------
# Public vocabulary: the only words that may appear in a discovery query.
CAPABILITY_WORDS = {
    "accessibility": "accessibility a11y testing",
    "migrations": "database migration",
    "api-contract": "api contract openapi",
    "security-review": "security review",
    "test-coverage": "unit testing test generation",
    "ci-debugging": "ci github actions debugging",
    "frontend-design": "frontend ui design",
    "performance": "performance profiling",
    "docs": "documentation",
    "dependency-upgrades": "dependency upgrade",
}


@dataclass(slots=True)
class Gap:
    id: str
    title: str
    evidence: list[str]
    strength: float          # 0..1, how strongly the repository needs it
    covered_by: list[str]    # existing skills/native commands that already address it
    query_terms: list[str]   # public vocabulary only

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Profile:
    languages: list[str]
    frameworks: list[str]
    test_frameworks: list[str]
    ci: list[str]
    databases: list[str]
    gaps: list[Gap] = field(default_factory=list)
    existing_skills: list[str] = field(default_factory=list)
    own_packages: list[str] = field(default_factory=list)  # local only: never part of a discovery query

    def to_json(self) -> dict[str, Any]:
        return {"languages": self.languages, "frameworks": self.frameworks,
                "test_frameworks": self.test_frameworks, "ci": self.ci,
                "databases": self.databases, "existing_skills": self.existing_skills,
                "gaps": [g.to_json() for g in self.gaps], "own_packages": self.own_packages}


# Built-in Claude Code commands that already cover a capability.
NATIVE_COVERAGE = {"security-review": ["/security-review (built in)"],
                   "ci-debugging": [], "test-coverage": [], "docs": [],
                   "frontend-design": []}
_DB_DEPS = {"psycopg2": "postgresql", "psycopg": "postgresql", "asyncpg": "postgresql",
            "pg": "postgresql", "mysqlclient": "mysql", "mysql2": "mysql", "sqlalchemy": "sql",
            "prisma": "sql", "@prisma/client": "sql", "typeorm": "sql", "sequelize": "sql",
            "mongoose": "mongodb", "pymongo": "mongodb", "redis": "redis", "sqlite3": "sqlite",
            "django": "sql", "flyway": "sql", "liquibase": "sql", "alembic": "sql"}
_A11Y_DEPS = {"jest-axe", "@axe-core/react", "axe-core", "@testing-library/jest-dom",
              "cypress-axe", "pa11y", "@axe-core/playwright"}


def _skill_texts(root: Path) -> dict[str, str]:
    """Each installed skill's description: what it claims to do and what
    Claude matches on (a body that merely mentions tests is not test authoring)."""
    out = {}
    for path in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
        try:
            text = path.read_text("utf-8", errors="replace")[:4000]
        except OSError:
            continue
        m = re.search(r"^description:\s*(.+)$", text.split("\n---", 1)[0], re.M)
        out[path.parent.name] = (m.group(1).strip().strip('"') if m else "").lower()
    return out


def build_profile(root: Path, facts: dict[str, Any], index, episodes: list[dict[str, Any]]) -> Profile:
    langs = [str(x[0]) if isinstance(x, (list, tuple)) else str(x)
             for x in facts.get("languages") or []][:6]
    from .registry import framework_names
    frameworks = framework_names(facts)
    tests = sorted({str(s.get("framework")) for s in facts.get("test_suites") or []
                    if isinstance(s, dict) and s.get("framework")})
    ci = sorted({PathLike(p).top for p in facts.get("ci_workflows") or []})
    deps = {str(d.get("name", "")).lower() for d in facts.get("dependencies") or [] if isinstance(d, dict)}
    dbs = sorted({_DB_DEPS[d] for d in deps if d in _DB_DEPS})
    skills = _skill_texts(root)
    rows = {r["path"]: r for r in index.all_files()}
    gaps: list[Gap] = []

    from .adapters.claude_content import NATIVE_MANAGEMENT_SKILLS

    def covered(*words: str) -> list[str]:  # management skills cover no task capability
        return sorted(name for name, text in skills.items()
                      if name not in NATIVE_MANAGEMENT_SKILLS and any(w in text for w in words))

    # frontend accessibility: components exist, no a11y testing dependency
    components = [p for p, r in rows.items() if p.endswith((".tsx", ".jsx", ".vue", ".svelte"))
                  and r["role"] == "source"]
    if len(components) >= 5 and not (deps & _A11Y_DEPS):
        gaps.append(Gap("accessibility", "Accessibility testing for UI components",
                        [f"{len(components)} UI component files", "no accessibility test dependency "
                         "(jest-axe, axe-core, pa11y…) declared"],
                        min(1.0, len(components) / 40), covered("accessib", "a11y", "axe"),
                        _terms("accessibility", frameworks)))
    # migrations: migration tooling or directories present
    migration_dirs = sorted({p.split("/migrations/")[0] + "/migrations" for p in rows
                             if "/migrations/" in p or p.startswith("migrations/")})
    if migration_dirs or deps & {"alembic", "flyway", "liquibase", "prisma", "knex"}:
        gaps.append(Gap("migrations", "Database migration authoring and review",
                        [f"migration directories: {', '.join(migration_dirs[:3]) or '-'}",
                         f"migration tooling: {', '.join(sorted(deps & {'alembic', 'flyway', 'liquibase', 'prisma', 'knex'})) or '-'}"],
                        0.7, covered("migration"), _terms("migrations", frameworks + dbs)))
    # API contracts: many routes, no OpenAPI artefact
    routes = facts.get("routes") or []
    has_openapi = any(re.search(r"openapi|swagger", p, re.I) for p in rows)
    if len(routes) >= 8:
        gaps.append(Gap("api-contract", "API contract validation",
                        [f"{len(routes)} HTTP routes", "OpenAPI spec present" if has_openapi
                         else "no OpenAPI/Swagger spec found"],
                        0.4 if has_openapi else 0.7, covered("openapi", "contract", "endpoint"),
                        _terms("api-contract", frameworks)))
    # test coverage: many source files with no linked test
    sources = [p for p, r in rows.items() if r["role"] == "source"]
    tested = {row["src_path"] for row in index.conn.execute("SELECT src_path FROM test_links")}
    if len(sources) >= 10:
        untested = [s for s in sources if s not in tested]
        share = len(untested) / len(sources)
        if share >= 0.5:
            gaps.append(Gap("test-coverage", "Test authoring for untested modules",
                            [f"{len(untested)} of {len(sources)} source files have no linked test"],
                            round(share, 2), covered("write test", "test authoring", "untested",
                                                       "coverage"), _terms("test-coverage", tests or frameworks)))
    # CI debugging: CI exists and recorded sessions show failing known commands
    fails = sum(1 for ep in episodes for c in ep.get("commands") or [] if not c[3])
    if ci and fails >= 3:
        gaps.append(Gap("ci-debugging", "CI and build failure debugging",
                        [f"CI: {', '.join(ci)}", f"{fails} failed known-command runs recorded"],
                        min(1.0, fails / 10), covered("ci ", "github actions", "workflow"),
                        _terms("ci-debugging", [])))
    # security review: auth code present
    auth_files = [p for p in sources if re.search(r"auth|login|token|session|password", p, re.I)]
    if len(auth_files) >= 2:
        gaps.append(Gap("security-review", "Security review of authentication code",
                        [f"{len(auth_files)} authentication-related source files"],
                        0.5, covered("security") + NATIVE_COVERAGE["security-review"],
                        _terms("security-review", frameworks)))
    for gap in gaps:
        if gap.covered_by:
            gap.strength = round(gap.strength * 0.4, 2)  # already partly covered
    gaps.sort(key=lambda g: -g.strength)
    return Profile(langs, frameworks, tests, ci, dbs, gaps, sorted(skills), own_packages(rows))


# too generic to show that a skill was written for this repository
_GENERIC_PACKAGES = {
    "src", "app", "apps", "lib", "core", "utils", "util", "common", "main", "test", "tests", "docs", "scripts",
    "examples", "tools", "config", "settings", "api", "server", "client", "cli", "data", "model", "models", "user",
    "users", "auth", "admin", "base", "shared", "helpers", "services", "service", "views", "schemas", "types",
    "internal", "plugins", "storage", "store", "tasks", "jobs", "workers", "static", "templates", "migrations",
    "database", "web", "site", "package", "project", "python", "source", "modules", "components", "handlers"}


def own_packages(paths: Iterable[str]) -> list[str]:
    """Top-level Python packages the repository itself defines (`pkg/__init__.py`, `src/pkg/__init__.py`)."""
    names = set()
    for path in paths:
        parts = path.split("/")
        if parts[0] == "src":
            parts = parts[1:]
        if len(parts) == 2 and parts[1] == "__init__.py" and parts[0].isidentifier():
            name = parts[0].lower()
            if len(name) >= 4 and name not in _GENERIC_PACKAGES:
                names.add(name)
    return sorted(names)


class PathLike:
    def __init__(self, path: str):
        self.top = path.split("/")[-1] if ".github" not in path else "github-actions"


_PUBLIC_TECH = re.compile(r"^[a-z0-9.+# -]{2,30}$")


def _terms(capability: str, tech: Iterable[str]) -> list[str]:
    """Public vocabulary only: a capability phrase plus at most two well-known
    technology names (which come from repo-ai's own detection catalogue)."""
    words = [CAPABILITY_WORDS[capability]]
    vocab = tech_vocabulary()
    for t in tech:
        low = str(t).lower()
        if low in vocab and low not in words:
            words.append(low)
        if len(words) >= 3:
            break
    return words


_VOCAB: set[str] | None = None


def tech_vocabulary() -> set[str]:
    """Every word a discovery query may contain: capability words plus the
    public technology names in repo-ai's own detection catalogues. Nothing
    from the repository itself."""
    global _VOCAB
    if _VOCAB is None:
        from .frameworks import DEP_FRAMEWORKS
        from .languages import CODE_LANGUAGES
        words: set[str] = set(" ".join(CAPABILITY_WORDS.values()).split())
        for dep, (label, _layer) in DEP_FRAMEWORKS.items():
            words.update(re.findall(r"[a-z0-9.+#-]+", f"{dep} {label}".lower()))
        for lang in CODE_LANGUAGES:
            words.update(re.findall(r"[a-z0-9.+#-]+", lang.lower()))
        words.update({"pytest", "jest", "vitest", "junit", "unittest", "mocha", "playwright",
                      "cypress", "postgresql", "mysql", "mongodb", "redis", "sqlite", "sql",
                      "react", "typescript", "javascript", "python", "java", "go", "rust"})
        _VOCAB = {w for w in words if 2 <= len(w) <= 24 and not w.isdigit()}
    return _VOCAB


def sanitize_query(text: str) -> str:
    vocab = tech_vocabulary()
    out = [w for w in re.findall(r"[a-z0-9.+#-]+", text.lower()) if w in vocab]
    return " ".join(dict.fromkeys(out[:8]))


# --------------------------------------------------------------------------
# private on-disk state (cache, quarantine): owner-only
# --------------------------------------------------------------------------
def private_dir(path: Path) -> Path:
    """Create `path` (and parents) and make it owner-only (0700), even if it already existed."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def write_private(path: Path, data: bytes) -> None:
    """Write a file owner-only (0600) into an owner-only directory, replacing it atomically."""
    import secrets
    private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def harden_tree(path: Path) -> None:
    """Directories 0700 and files 0600 under `path` (a quarantine written by another module).
    Symbolic links are never followed or changed."""
    if path.is_symlink() or not path.is_dir():
        return
    private_dir(path)
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames:
            full = Path(dirpath) / name
            if not full.is_symlink():
                os.chmod(full, 0o700)
        for name in filenames:
            full = Path(dirpath) / name
            if not full.is_symlink():
                os.chmod(full, 0o600)


# --------------------------------------------------------------------------
# bounded, cached HTTP
# --------------------------------------------------------------------------
class Client:
    def __init__(self, cache_dir: Path, max_requests: int | None = MAX_REQUESTS, offline: bool = False):
        self.cache_dir = cache_dir
        self.max_requests = CLI_MAX_REQUESTS if max_requests is None else max_requests
        self.requests = 0
        self.offline = offline
        self.notes: list[str] = []
        self._token: str | None = None

    def _github_token(self) -> str | None:
        if self._token is None:
            self._token = os.environ.get("GITHUB_TOKEN") or ""
            if not self._token and shutil.which("gh"):
                try:
                    out = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                         capture_output=True, text=True, timeout=10, check=False)
                    self._token = out.stdout.strip() if out.returncode == 0 else ""
                except (OSError, subprocess.SubprocessError):
                    self._token = ""
        return self._token or None

    def get(self, host: str, path: str, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None, ttl: int = CACHE_TTL_S) -> Any:
        if host not in API_HOSTS:
            raise RadarError(f"refusing to contact {host}: not an allowed API host")
        query = urllib.parse.urlencode(sorted((params or {}).items()))
        url = f"https://{host}{path}" + (f"?{query}" if query else "")
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        cached = self.cache_dir / f"{key}.json"
        if cached.is_file() and (ttl < 0 or time.time() - cached.stat().st_mtime < ttl):
            return json.loads(cached.read_text("utf-8"))
        if self.offline:
            raise RadarError(f"offline and not cached: {url}")
        if self.requests >= self.max_requests:
            raise RadarError(f"request cap reached ({self.max_requests}); results are partial")
        self.requests += 1
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "repo-ai-skill-radar"})
        for name, value in (headers or {}).items():  # credentials never follow a redirect
            req.add_unredirected_header(name, value)
        if host == "api.github.com":
            token = self._github_token()
            if token:
                req.add_unredirected_header("Authorization", f"Bearer {token}")  # never follows a redirect
        try:
            with _opener().open(req, timeout=TIMEOUT_S) as resp:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if remaining is not None and remaining.isdigit() and int(remaining) < 2:
                    self.notes.append(f"{host} rate limit nearly exhausted")
                data = json.loads(resp.read(5_000_000).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise RadarError(f"{host} rate limited or forbidden ({exc.code}); try later") from exc
            raise RadarError(f"{host} returned {exc.code} for {path}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RadarError(f"{host} unavailable: {exc}") from exc
        write_private(cached, json.dumps(data).encode("utf-8"))
        return data


    def tarball(self, owner: str, repo: str, commit: str) -> bytes:
        """One immutable tarball per (repo, commit), cached forever."""
        check_slug(owner, repo)
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise RadarError(f"refusing to fetch a non-pinned ref: {commit!r}")
        cached = self.cache_dir / "tarballs" / f"{owner}__{repo}__{commit}.tar.gz"
        if cached.is_file():
            return cached.read_bytes()
        if self.offline:
            raise RadarError("offline and tarball not cached")
        if self.requests >= self.max_requests:
            raise RadarError(f"request cap reached ({self.max_requests}); results are partial")
        self.requests += 1
        req = urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}/tarball/{commit}",
                                     headers={"User-Agent": "repo-ai-skill-radar"})
        token = self._github_token()
        if token:
            req.add_unredirected_header("Authorization", f"Bearer {token}")  # never follows a redirect
        try:
            with _opener().open(req, timeout=60) as resp:
                data = resp.read(MAX_TARBALL + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RadarError(f"tarball download failed: {exc}") from exc
        if len(data) > MAX_TARBALL:
            raise RadarError("repository tarball exceeds the size limit")
        write_private(cached, data)
        return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        parsed = urllib.parse.urlparse(newurl)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or host not in API_HOSTS | DOWNLOAD_HOSTS:
            raise urllib.error.HTTPError(newurl, code, f"redirect to {host} refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_NoRedirect)


def parse_github_url(url: str) -> tuple[str, str, str | None, str | None]:
    """https://github.com/owner/repo[/tree/<ref>/<path>] → (owner, repo, ref, path).
    `/blob/<ref>/<dir>/SKILL.md` means that skill's directory.
    Anything else is refused (no arbitrary fetches: SSRF)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.port not in (None, 443):
        raise RadarError(f"only https://github.com/<owner>/<repo> sources are accepted: {url}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", p) for p in parts[:2]):
        raise RadarError(f"not a repository URL: {url}")
    ref: str | None = None
    path: str | None = None
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        ref, path = parts[3], "/".join(parts[4:]) or None
        if parts[2] == "blob" and path is not None and (path == "SKILL.md" or path.endswith("/SKILL.md")):
            path = path.rsplit("/", 1)[0] if "/" in path else None
    return parts[0], parts[1].removesuffix(".git"), ref, path


# --------------------------------------------------------------------------
# candidates and providers
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Candidate:
    id: str                 # owner/repo/path-to-skill-dir@commit
    name: str
    provider: str
    owner: str
    repo: str
    path: str               # directory containing SKILL.md, repo-relative
    commit: str             # immutable
    skill_md_sha: str       # git blob sha of SKILL.md
    description: str = ""
    url: str = ""
    stars: int = 0
    repo_license: str = ""
    pushed_at: str = ""
    created_at: str = ""
    archived: bool = False
    fork: bool = False
    matched_gaps: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _repo_meta(client: Client, owner: str, repo: str) -> dict[str, Any]:
    return client.get("api.github.com", f"/repos/{owner}/{repo}")


def _tree(client: Client, owner: str, repo: str, ref: str) -> tuple[str, list[dict[str, Any]]]:
    sha, tree, _truncated = _tree_full(client, owner, repo, ref)
    return sha, tree


def _tree_full(client: Client, owner: str, repo: str, ref: str) -> tuple[str, list[dict[str, Any]], bool]:
    """(commit sha, recursive tree entries, whether GitHub truncated the tree)."""
    commit = client.get("api.github.com", f"/repos/{owner}/{repo}/commits/{ref}")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RadarError(f"GitHub did not resolve ref {str(ref)[:60]!r} to a commit")
    tree = client.get("api.github.com", f"/repos/{owner}/{repo}/git/trees/{sha}",
                      {"recursive": "1"}, ttl=-1)  # immutable by commit
    if not isinstance(tree, dict) or not isinstance(tree.get("tree", []), list):
        raise RadarError(f"GitHub returned no file tree for commit {sha[:12]}")
    entries = [e for e in tree.get("tree", []) if isinstance(e, dict)]
    return sha, entries, bool(tree.get("truncated"))


def _blob_text(client: Client, owner: str, repo: str, sha: str, limit: int = 200_000) -> str:
    import base64
    blob = client.get("api.github.com", f"/repos/{owner}/{repo}/git/blobs/{sha}", ttl=-1)
    if int(blob.get("size", 0)) > limit:
        raise RadarError(f"blob {sha[:10]} too large ({blob.get('size')} bytes)")
    return base64.b64decode(blob.get("content", "")).decode("utf-8", "replace")


def _front_description(text: str) -> tuple[str, str]:
    m = re.match(r"---\n(.*?)\n---", text.replace("\r\n", "\n"), re.S)
    name: str = ""
    desc: str = ""
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"\'')
            elif line.startswith("description:"):
                desc = line.split(":", 1)[1].strip().strip('"\'')
    return name, desc


_SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_REF = re.compile(r"[A-Za-z0-9._/-]{1,200}")


def check_ref(ref: str) -> None:
    if not isinstance(ref, str) or not _REF.fullmatch(ref) or ".." in ref:
        raise RadarError(f"invalid git ref: {str(ref)[:60]!r}")


def is_skill_md(path: str) -> bool:
    return path == "SKILL.md" or path.endswith("/SKILL.md")


def _in_scope(path: str, under: str | None) -> bool:
    if not under:
        return True
    under = under.rstrip("/")
    return path.startswith(under + "/") or path == f"{under}/SKILL.md"


def check_slug(owner: str, repo: str) -> None:
    """GitHub owner/repo names only: anything else could steer an API path
    or a cache filename (values come from config and third-party APIs)."""
    for part in (owner, repo):
        if not isinstance(part, str) or not _SLUG.fullmatch(part) or part in {".", ".."}:
            raise RadarError(f"invalid GitHub owner/repository name: {str(part)[:60]!r}")


def repo_candidates(client: Client, owner: str, repo: str, provider: str, ref: str | None = None,
                    limit: int = 40, under: str | None = None) -> list[Candidate]:
    check_slug(owner, repo)
    if ref is not None:
        check_ref(ref)
    meta = _repo_meta(client, owner, repo)
    sha, tree = _tree(client, owner, repo, ref or meta.get("default_branch") or "HEAD")
    out = []
    for entry in tree:
        path = entry.get("path", "")
        if not isinstance(path, str) or not is_skill_md(path) or entry.get("type") != "blob" \
                or not _in_scope(path, under):
            continue
        try:
            out.append(_candidate(client, owner, repo, provider, sha, entry, meta))
        except RadarError as exc:
            client.notes.append(str(exc))
            continue
        if len(out) >= limit:
            break
    return out


def _candidate(client: Client, owner: str, repo: str, provider: str, sha: str,
               entry: dict[str, Any], meta: dict[str, Any]) -> Candidate:
    path = entry["path"]
    skill_dir = path.rsplit("/", 1)[0] if "/" in path else ""
    blob_sha = entry.get("sha")
    if not isinstance(blob_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
        raise RadarError(f"tree entry {str(path)[:80]!r} has no valid blob SHA")
    try:
        text = _blob_text(client, owner, repo, blob_sha)
    except (ValueError, TypeError) as exc:  # undecodable base64 or a malformed blob response
        raise RadarError(f"blob {blob_sha[:10]} could not be decoded: {exc}") from exc
    name, desc = _front_description(text)
    lic = meta.get("license")
    return Candidate(
        id=f"{owner}/{repo}/{skill_dir}@{sha[:12]}", name=name or skill_dir.rsplit("/", 1)[-1],
        provider=provider, owner=owner, repo=repo, path=skill_dir, commit=sha,
        skill_md_sha=blob_sha, description=desc[:1024],
        url=f"https://github.com/{owner}/{repo}/tree/{sha}/{skill_dir}",
        stars=int(meta.get("stargazers_count") or 0),
        repo_license=(lic.get("spdx_id") if isinstance(lic, dict) else "") or "",
        pushed_at=meta.get("pushed_at") or "", created_at=meta.get("created_at") or "",
        archived=bool(meta.get("archived")), fork=bool(meta.get("fork")))


# --------------------------------------------------------------------------
# vetting one pasted source
# --------------------------------------------------------------------------
@dataclass(slots=True)
class VetSource:
    """What `skills vet` learned about one GitHub source before quarantining anything.

    `problems` are source-level errors (identity, reachability, a truncated tree):
    any of them means the vet is incomplete and nothing from the source may be installed."""
    owner: str
    repo: str
    ref: str | None
    under: str | None
    meta: dict[str, Any]
    full_name: str
    default_branch: str
    commit: str
    tree: list[dict[str, Any]]
    truncated: bool
    skill_paths: list[str]                       # every SKILL.md in scope, in tree order
    candidates: list[Candidate]
    skill_errors: list[tuple[str, str]]          # (SKILL.md path, error) for skills not read
    skipped: list[str]                           # SKILL.md paths beyond the limit
    problems: list[str] = field(default_factory=list)


def vet_source(client: Client, owner: str, repo: str, ref: str | None, under: str | None,
               limit: int = VET_LIMIT) -> VetSource:
    """Resolve and check one source: repository identity, the commit, its reachability
    from the default branch when a SHA was given, and every SKILL.md (up to `limit`).
    Raises RadarError only when nothing could be resolved at all."""
    check_slug(owner, repo)
    if ref is not None:
        check_ref(ref)
    problems: list[str] = []
    meta = _repo_meta(client, owner, repo)
    if not isinstance(meta, dict):
        raise RadarError("GitHub returned no repository metadata")
    expected = f"{owner}/{repo}"
    full = meta.get("full_name")
    full_name = full if isinstance(full, str) else ""
    if not full_name:
        problems.append(f"GitHub's metadata for {expected} has no full_name: the repository's "
                        "identity could not be confirmed")
    elif full_name.lower() != expected.lower():
        problems.append(f"the URL names {expected} but GitHub answered for {full_name} (renamed, "
                        "transferred or redirected); vet the real repository's URL instead")
    default = meta.get("default_branch") or "HEAD"
    if not isinstance(default, str) or not _REF.fullmatch(default) or ".." in default:
        problems.append(f"the repository's default branch name is not a plain ref: {str(default)[:60]!r}")
        default = "HEAD"
    sha, tree, truncated = _tree_full(client, owner, repo, ref or default)
    if truncated:
        problems.append("GitHub truncated this commit's file tree (too many files): SKILL.md files "
                        "or files of the listed skills may be missing, so nothing from this source "
                        "can be installed")
    if ref and re.fullmatch(r"[0-9a-f]{7,40}", ref) and sha.startswith(ref):
        try:
            status = commit_reachability(client, owner, repo, default, sha)
        except RadarError as exc:
            problems.append(f"could not check that commit {sha[:12]} is on the default branch "
                            f"{default}: {exc}")
        else:
            if status not in {"behind", "identical"}:
                problems.append(f"commit {sha[:12]} is not reachable from the default branch {default} "
                                f"(compare status {status!r}): it may be a commit pushed to a fork in "
                                f"the same network, not part of {expected}")
    skill_entries = [e for e in tree if isinstance(e.get("path"), str) and is_skill_md(e["path"])
                     and e.get("type") == "blob" and _in_scope(e["path"], under)]
    candidates: list[Candidate] = []
    errors: list[tuple[str, str]] = []
    for entry in skill_entries[:max(0, limit)]:
        try:
            candidates.append(_candidate(client, owner, repo, "url", sha, entry, meta))
        except (RadarError, KeyError) as exc:
            errors.append((entry["path"], str(exc)))
    return VetSource(owner, repo, ref, under, meta, full_name, default, sha, tree, truncated,
                     [e["path"] for e in skill_entries], candidates, errors,
                     [e["path"] for e in skill_entries[max(0, limit):]], problems)


def commit_reachability(client: Client, owner: str, repo: str, base: str, sha: str) -> str:
    """GitHub's compare status of `sha` against `base`: `behind` or `identical` means the
    commit is in base's history; `ahead` or `diverged` means it is not (for example, a
    commit that exists only in a fork but is served under the parent's name)."""
    check_slug(owner, repo)
    check_ref(base)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RadarError(f"not a commit SHA: {sha[:60]!r}")
    res = client.get("api.github.com", f"/repos/{owner}/{repo}/compare/{base}...{sha}",
                     {"per_page": "1"})
    status = res.get("status") if isinstance(res, dict) else None
    if not isinstance(status, str):
        raise RadarError("GitHub's compare response has no status")
    return status


def search_github(client: Client, query: str, limit: int = 10) -> list[Candidate]:
    q = sanitize_query(query)
    if not q:
        return []
    res = client.get("api.github.com", "/search/code",
                     {"q": f"filename:SKILL.md {q}", "per_page": min(limit, 30)}, ttl=6 * 3600)
    out: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for item in res.get("items", [])[:limit]:
        full = item.get("repository", {}).get("full_name", "")
        path = item.get("path", "")
        if "/" not in full or not path.endswith("SKILL.md") or path != "SKILL.md" and not path.endswith("/SKILL.md"):
            continue
        owner, repo = full.split("/", 1)
        skill_dir = path.rsplit("/", 1)[0] if "/" in path else ""
        if (full, skill_dir) in seen:
            continue
        seen.add((full, skill_dir))
        try:
            found = repo_candidates(client, owner, repo, "github", under=skill_dir or None, limit=1)
        except RadarError as exc:
            client.notes.append(str(exc))
            continue
        out.extend(found)
    return out


def marketplace_candidates(client: Client, owner: str, repo: str) -> list[Candidate]:
    """Skills of plugins listed in a `.claude-plugin/marketplace.json`."""
    check_slug(owner, repo)
    meta = _repo_meta(client, owner, repo)
    sha, tree = _tree(client, owner, repo, meta.get("default_branch") or "HEAD")
    entry = next((e for e in tree if e.get("path") == ".claude-plugin/marketplace.json"), None)
    if not entry:
        return []
    data = json.loads(_blob_text(client, owner, repo, entry["sha"]))
    out = []
    for plugin in data.get("plugins", []) if isinstance(data, dict) else []:
        source = plugin.get("source") if isinstance(plugin, dict) else None
        if isinstance(source, str) and source.startswith("./"):
            out += repo_candidates(client, owner, repo, "marketplace", ref=sha,
                                   under=source[2:].rstrip("/"), limit=10)
    return out


def skills_sh_candidates(client: Client, query: str, token: str | None) -> list[Candidate]:
    if not token:
        client.notes.append("skills.sh skipped: its API requires a Vercel OIDC token "
                            "(set SKILLS_SH_TOKEN)")
        return []
    q = sanitize_query(query)
    res = client.get("skills.sh", "/api/v1/skills/search", {"q": q, "limit": 20},
                     headers={"x-vercel-oidc-token": token}, ttl=3600)
    out = []
    for item in res.get("data", []):
        source = str(item.get("source", ""))
        if item.get("isDuplicate") or source.count("/") < 1:
            continue
        owner, _, repo = source.partition("/")
        try:
            found = repo_candidates(client, owner, repo, "skills.sh", limit=20)
        except RadarError as exc:
            client.notes.append(str(exc))
            continue
        out += [c for c in found if c.name == item.get("slug") or c.name == item.get("name")]
    return out


def discover(profile: Profile, cfg_publishers: list[str], cfg_marketplaces: list[str],
             client: Client, providers: Iterable[str]) -> dict[str, Any]:
    providers = list(providers)
    candidates: list[Candidate] = []
    queries = [" ".join(g.query_terms) for g in profile.gaps]
    errors = []

    def attempt(label: str, fn) -> None:
        try:
            candidates.extend(fn())
        except RadarError as exc:
            errors.append(f"{label}: {exc}")

    if "anthropic" in providers:
        attempt("anthropic", lambda: repo_candidates(client, *OFFICIAL["anthropic"], "anthropic"))
    if "vercel" in providers:
        attempt("vercel", lambda: repo_candidates(client, *OFFICIAL["vercel"], "vercel"))
    for spec in cfg_publishers if "publishers" in providers else []:
        owner, _, repo = spec.partition("/")
        if owner and repo:
            attempt(f"publisher {spec}", lambda o=owner, r=repo: repo_candidates(client, o, r, "publisher"))
    for spec in cfg_marketplaces if "marketplace" in providers else []:
        owner, _, repo = spec.partition("/")
        if owner and repo:
            attempt(f"marketplace {spec}", lambda o=owner, r=repo: marketplace_candidates(client, o, r))
    if "github" in providers:
        for q in queries[:4]:
            attempt(f"github search '{sanitize_query(q)}'", lambda q=q: search_github(client, q, 6))
    if "skills.sh" in providers:
        token = os.environ.get("SKILLS_SH_TOKEN")
        for q in queries[:3]:
            attempt("skills.sh", lambda q=q: skills_sh_candidates(client, q, token))
    deduped = dedupe(candidates)
    for cand in deduped:
        cand.matched_gaps = match_gaps(cand, profile)
    return {"candidates": deduped, "queries": [sanitize_query(q) for q in queries],
            "errors": errors, "notes": client.notes, "requests": client.requests}


def dedupe(cands: list[Candidate]) -> list[Candidate]:
    """Same SKILL.md content (blob sha) in several repos is one skill: keep the
    copy from a known publisher, else the most-starred, and list the others."""
    groups: dict[str, list[Candidate]] = {}
    for c in cands:
        groups.setdefault(c.skill_md_sha, []).append(c)
    out = []
    for group in groups.values():
        group.sort(key=lambda c: (c.owner.lower() not in KNOWN_PUBLISHERS, c.fork, -c.stars, c.id))
        keep = group[0]
        keep.duplicates = [c.id for c in group[1:]]
        out.append(keep)
    seen_ids: set[str] = set()
    unique = []
    for c in out:
        if c.id not in seen_ids:
            seen_ids.add(c.id)
            unique.append(c)
    return unique


GAP_KEYWORDS = {
    "accessibility": ("accessib", "a11y", "axe", "wcag", "aria"),
    "migrations": ("migration", "schema change", "alembic", "flyway", "liquibase", "prisma migrate"),
    "api-contract": ("openapi", "swagger", "api contract", "contract test", "api spec"),
    "test-coverage": ("unit test", "write tests", "test generation", "testing", "test-driven", "tdd"),
    "ci-debugging": ("github actions", "ci failure", "ci/cd", "build failure", "pipeline", "workflow run"),
    "security-review": ("security", "vulnerab", "owasp", "threat model", "secure code"),
    "frontend-design": ("frontend", "ui design", "component design", "css", "design system"),
    "performance": ("performance", "profil", "latency", "optimi"),
    "docs": ("documentation", "docstring", "readme"),
    "dependency-upgrades": ("dependency", "upgrade", "migration guide"),
}


def match_gaps(cand: Candidate, profile: Profile) -> list[str]:
    """Gaps this candidate addresses, by capability-specific keywords in its
    own name and description (never by shared generic words)."""
    text = f"{cand.name.replace('-', ' ')} {cand.description}".lower()
    return [gap.id for gap in profile.gaps
            if any(k in text for k in GAP_KEYWORDS.get(gap.id, ()))]
