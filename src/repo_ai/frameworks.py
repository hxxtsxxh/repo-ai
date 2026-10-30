"""Framework detection, component discovery, and route extraction.

`Component` is the unit that makes monorepos tractable: instead of one
undifferentiated file list, the repository becomes N named things with their
own language, manifest, entrypoint, and test suite. Every downstream artefact
(architecture doc, repo map, retrieval boost) is organised around components.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from .languages import is_code
from .models import Component, Dependency, FileRecord, Route

# --------------------------------------------------------------------------
# Framework fingerprints: dependency name -> (framework label, layer)
# --------------------------------------------------------------------------
DEP_FRAMEWORKS: dict[str, tuple[str, str]] = {
    # JS/TS frontend
    "react": ("React", "frontend"), "react-dom": ("React", "frontend"),
    "next": ("Next.js", "fullstack"), "vue": ("Vue", "frontend"),
    "nuxt": ("Nuxt", "fullstack"), "svelte": ("Svelte", "frontend"),
    "@sveltejs/kit": ("SvelteKit", "fullstack"),
    "@angular/core": ("Angular", "frontend"), "solid-js": ("SolidJS", "frontend"),
    "astro": ("Astro", "frontend"), "preact": ("Preact", "frontend"),
    "@remix-run/react": ("Remix", "fullstack"),
    # JS/TS backend
    "express": ("Express", "backend"), "fastify": ("Fastify", "backend"),
    "koa": ("Koa", "backend"), "@nestjs/core": ("NestJS", "backend"),
    "hapi": ("hapi", "backend"), "@hapi/hapi": ("hapi", "backend"),
    "hono": ("Hono", "backend"), "apollo-server": ("Apollo GraphQL", "backend"),
    "@apollo/server": ("Apollo GraphQL", "backend"),
    "graphql": ("GraphQL", "api"), "trpc": ("tRPC", "api"),
    "@trpc/server": ("tRPC", "api"), "socket.io": ("Socket.IO", "realtime"),
    # Python
    "django": ("Django", "fullstack"), "flask": ("Flask", "backend"),
    "fastapi": ("FastAPI", "backend"), "starlette": ("Starlette", "backend"),
    "tornado": ("Tornado", "backend"), "aiohttp": ("aiohttp", "backend"),
    "pyramid": ("Pyramid", "backend"), "sanic": ("Sanic", "backend"),
    "litestar": ("Litestar", "backend"), "strawberry-graphql": ("Strawberry GraphQL", "api"),
    "celery": ("Celery", "async"), "sqlalchemy": ("SQLAlchemy", "data"),
    "alembic": ("Alembic", "data"), "pydantic": ("Pydantic", "data"),
    "django-rest-framework": ("DRF", "api"), "djangorestframework": ("DRF", "api"),
    "pandas": ("pandas", "data"), "numpy": ("NumPy", "data"),
    "torch": ("PyTorch", "ml"), "tensorflow": ("TensorFlow", "ml"),
    "scikit-learn": ("scikit-learn", "ml"), "transformers": ("Transformers", "ml"),
    "langchain": ("LangChain", "ml"), "llama-index": ("LlamaIndex", "ml"),
    # Java / JVM
    "org.springframework.boot:spring-boot-starter": ("Spring Boot", "backend"),
    "org.springframework.boot:spring-boot-starter-web": ("Spring Boot", "backend"),
    "org.springframework:spring-core": ("Spring", "backend"),
    "io.quarkus:quarkus-core": ("Quarkus", "backend"),
    "io.micronaut:micronaut-core": ("Micronaut", "backend"),
    "org.hibernate:hibernate-core": ("Hibernate", "data"),
    "io.dropwizard:dropwizard-core": ("Dropwizard", "backend"),
    # Go
    "github.com/gin-gonic/gin": ("Gin", "backend"),
    "github.com/labstack/echo": ("Echo", "backend"),
    "github.com/gofiber/fiber": ("Fiber", "backend"),
    "github.com/go-chi/chi": ("chi", "backend"),
    "github.com/gorilla/mux": ("gorilla/mux", "backend"),
    "google.golang.org/grpc": ("gRPC", "api"),
    # Rust / Ruby / PHP / .NET
    "axum": ("Axum", "backend"), "actix-web": ("Actix Web", "backend"),
    "rocket": ("Rocket", "backend"), "tokio": ("Tokio", "async"),
    "rails": ("Rails", "fullstack"), "sinatra": ("Sinatra", "backend"),
    "laravel/framework": ("Laravel", "fullstack"), "symfony/framework-bundle": ("Symfony", "fullstack"),
    # Data stores / infra clients
    "pg": ("PostgreSQL", "database"), "psycopg2": ("PostgreSQL", "database"),
    "psycopg2-binary": ("PostgreSQL", "database"), "psycopg": ("PostgreSQL", "database"),
    "asyncpg": ("PostgreSQL", "database"), "mysql2": ("MySQL", "database"),
    "pymysql": ("MySQL", "database"), "mysqlclient": ("MySQL", "database"),
    "mongoose": ("MongoDB", "database"), "pymongo": ("MongoDB", "database"),
    "mongodb": ("MongoDB", "database"), "redis": ("Redis", "cache"),
    "ioredis": ("Redis", "cache"), "elasticsearch": ("Elasticsearch", "search"),
    "@elastic/elasticsearch": ("Elasticsearch", "search"),
    "prisma": ("Prisma", "data"), "@prisma/client": ("Prisma", "data"),
    "typeorm": ("TypeORM", "data"), "sequelize": ("Sequelize", "data"),
    "drizzle-orm": ("Drizzle", "data"), "knex": ("Knex", "data"),
    "kafkajs": ("Kafka", "messaging"), "confluent-kafka": ("Kafka", "messaging"),
    "pika": ("RabbitMQ", "messaging"), "amqplib": ("RabbitMQ", "messaging"),
    "boto3": ("AWS SDK", "cloud"), "aws-sdk": ("AWS SDK", "cloud"),
    "@aws-sdk/client-s3": ("AWS SDK", "cloud"),
    "google-cloud-storage": ("GCP SDK", "cloud"),
    "azure-storage-blob": ("Azure SDK", "cloud"),
    "ibm-cloud-sdk-core": ("IBM Cloud SDK", "cloud"),
    "ibm-watson": ("IBM Watson", "cloud"),
    # auth
    "passport": ("Passport", "auth"), "jsonwebtoken": ("JWT", "auth"),
    "pyjwt": ("JWT", "auth"), "python-jose": ("JWT", "auth"),
    "next-auth": ("NextAuth", "auth"), "@auth/core": ("Auth.js", "auth"),
    "authlib": ("Authlib", "auth"), "passlib": ("Passlib", "auth"),
    "bcrypt": ("bcrypt", "auth"), "argon2-cffi": ("Argon2", "auth"),
    "django-allauth": ("django-allauth", "auth"),
    "org.springframework.boot:spring-boot-starter-security": ("Spring Security", "auth"),
    # test frameworks
    "jest": ("Jest", "test"), "vitest": ("Vitest", "test"),
    "mocha": ("Mocha", "test"), "jasmine": ("Jasmine", "test"),
    "@playwright/test": ("Playwright", "test"), "playwright": ("Playwright", "test"),
    "cypress": ("Cypress", "test"), "puppeteer": ("Puppeteer", "test"),
    "@testing-library/react": ("Testing Library", "test"),
    "pytest": ("pytest", "test"), "unittest2": ("unittest", "test"),
    "nose": ("nose", "test"), "hypothesis": ("Hypothesis", "test"),
    "junit:junit": ("JUnit", "test"), "org.junit.jupiter:junit-jupiter": ("JUnit 5", "test"),
    "org.testng:testng": ("TestNG", "test"), "org.mockito:mockito-core": ("Mockito", "test"),
    "rspec": ("RSpec", "test"), "minitest": ("Minitest", "test"),
    "phpunit/phpunit": ("PHPUnit", "test"),
    "testify": ("Testify", "test"), "github.com/stretchr/testify": ("Testify", "test"),
}

FILE_FRAMEWORKS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"(^|/)next\.config\.(js|ts|mjs)$"), "Next.js", "fullstack"),
    (re.compile(r"(^|/)nuxt\.config\.(js|ts)$"), "Nuxt", "fullstack"),
    (re.compile(r"(^|/)angular\.json$"), "Angular", "frontend"),
    (re.compile(r"(^|/)vite\.config\.(js|ts)$"), "Vite", "build"),
    (re.compile(r"(^|/)webpack\.config\.(js|ts)$"), "Webpack", "build"),
    (re.compile(r"(^|/)manage\.py$"), "Django", "fullstack"),
    (re.compile(r"(^|/)wsgi\.py$"), "WSGI", "backend"),
    (re.compile(r"(^|/)asgi\.py$"), "ASGI", "backend"),
    (re.compile(r"(^|/)Gemfile$"), "Bundler", "build"),
    (re.compile(r"(^|/)config/routes\.rb$"), "Rails", "fullstack"),
    (re.compile(r"(^|/)artisan$"), "Laravel", "fullstack"),
    (re.compile(r"(^|/)docker-compose\.ya?ml$"), "Docker Compose", "infra"),
    (re.compile(r"(^|/)Dockerfile"), "Docker", "infra"),
    (re.compile(r"(^|/)Chart\.ya?ml$"), "Helm", "infra"),
    (re.compile(r"(^|/).*\.tf$"), "Terraform", "infra"),
    (re.compile(r"(^|/)serverless\.ya?ml$"), "Serverless Framework", "infra"),
    (re.compile(r"(^|/)template\.ya?ml$"), "AWS SAM", "infra"),
    (re.compile(r"(^|/)skaffold\.ya?ml$"), "Skaffold", "infra"),
    (re.compile(r"(^|/)\.github/workflows/"), "GitHub Actions", "ci"),
    (re.compile(r"(^|/)\.gitlab-ci\.ya?ml$"), "GitLab CI", "ci"),
    (re.compile(r"(^|/)Jenkinsfile$"), "Jenkins", "ci"),
    (re.compile(r"(^|/)\.travis\.ya?ml$"), "Travis CI", "ci"),
    (re.compile(r"(^|/)azure-pipelines\.ya?ml$"), "Azure Pipelines", "ci"),
    (re.compile(r"(^|/)\.circleci/config\.ya?ml$"), "CircleCI", "ci"),
    (re.compile(r"(^|/)tekton/"), "Tekton", "ci"),
    (re.compile(r"(^|/)openapi\.(ya?ml|json)$"), "OpenAPI", "api"),
    (re.compile(r"(^|/)swagger\.(ya?ml|json)$"), "Swagger", "api"),
    (re.compile(r"(^|/)schema\.graphql$"), "GraphQL", "api"),
    (re.compile(r"(^|/)\.proto$|\.proto$"), "Protobuf/gRPC", "api"),
    (re.compile(r"(^|/)alembic\.ini$"), "Alembic", "data"),
    (re.compile(r"(^|/)prisma/schema\.prisma$"), "Prisma", "data"),
    (re.compile(r"(^|/)knexfile\.(js|ts)$"), "Knex", "data"),
]

ENTRYPOINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)(main|index|app|server|cli|__main__|bootstrap|entry|start)\.(py|js|ts|tsx|jsx|go|rs|rb|php|java|kt)$"),
    re.compile(r"(^|/)manage\.py$"),
    re.compile(r"(^|/)wsgi\.py$|(^|/)asgi\.py$"),
    re.compile(r"(^|/)Application\.java$|(^|/)\w*Application\.java$"),
    re.compile(r"(^|/)Program\.cs$|(^|/)Startup\.cs$"),
    re.compile(r"(^|/)cmd/[^/]+/main\.go$"),
    re.compile(r"(^|/)src/main\.rs$|(^|/)src/bin/[^/]+\.rs$"),
    re.compile(r"(^|/)bin/[^/.]+$"),
)

# --------------------------------------------------------------------------
# Route extraction
# --------------------------------------------------------------------------
_ROUTE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Express / Koa / Fastify / Hono: app.get('/path', handler)
    # `api` and `client` are deliberately excluded: `api.get('/x')` in a
    # frontend service module is a *call*, not a route definition.
    ("Express-like", re.compile(
        r"""\b(?:app|router|server|route[rs]?|\w+Router|\w+Routes)\s*\.\s*"""
        r"""(get|post|put|patch|delete|options|head|all)\s*\(\s*['"`]([^'"`]+)['"`]"""
        r"""\s*,""",
        re.I)),
    # FastAPI / Flask decorators: @app.get("/path")
    ("Python decorator", re.compile(
        r"""@\s*(?:\w+)\s*\.\s*(get|post|put|patch|delete|options|head|route)\s*\(\s*['"]([^'"]+)['"]""",
        re.I)),
    # NestJS / Spring annotations
    ("Annotation", re.compile(
        r"""@(Get|Post|Put|Patch|Delete|RequestMapping|GetMapping|PostMapping|"""
        r"""PutMapping|DeleteMapping|PatchMapping)\s*\(\s*(?:value\s*=\s*)?['"]([^'"]*)['"]""")),
    # Django urls.py: path('route/', view)
    ("Django", re.compile(r"""\b(?:path|re_path|url)\s*\(\s*r?['"]([^'"]*)['"]\s*,\s*([\w.]+)""")),
    # Go gin/echo: r.GET("/path", h); chi: r.Get("/path", h); net/http: HandleFunc
    ("Go router", re.compile(
        r"""\b\w+\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Get|Post|Put|Patch|Delete|Head|"""
        r"""Options|Handle|HandleFunc|Method)\s*\(\s*"""
        r"""(?:"(?:GET|POST|PUT|PATCH|DELETE)"\s*,\s*)?"([^"]+)\"""")),
    # ASP.NET Core minimal APIs: app.MapGet("/path", ...)
    ("ASP.NET", re.compile(r"""\.Map(Get|Post|Put|Patch|Delete|Methods)\s*\(\s*@?"([^"]+)\"""")),
    # Rails routes.rb
    ("Rails", re.compile(r"""^\s*(get|post|put|patch|delete)\s+['"]([^'"]+)['"]""", re.M | re.I)),
]


# A route pattern only makes sense in the languages that framework runs in.
# Without this, `@app.get("/flights")` in a FastAPI service was being reported
# as an "Express-like" route.
_FRAMEWORK_LANGUAGES: dict[str, frozenset[str]] = {
    "Express-like": frozenset({"JavaScript", "TypeScript"}),
    "Python decorator": frozenset({"Python"}),
    "Django": frozenset({"Python"}),
    "Go router": frozenset({"Go"}),
    "ASP.NET": frozenset({"C#"}),
    "Rails": frozenset({"Ruby"}),
    "Annotation": frozenset({"Java", "Kotlin", "TypeScript", "C#"}),
}


_NEXT_APP_ROUTE = re.compile(r"(^|/)(app|pages)/(.+?)/(route|page)\.(ts|tsx|js|jsx)$")
_NEXT_API_ROUTE = re.compile(r"(^|/)pages/api/(.+)\.(ts|tsx|js|jsx)$")


_PY_WEB_FRAMEWORK = re.compile(r"(?i)\b(fastapi|flask|quart|sanic|starlette|bottle)\b")


def _python_route_label(text: str) -> str:
    match = _PY_WEB_FRAMEWORK.search(text[:4000])
    if not match:
        return "Python decorator"
    return {"fastapi": "FastAPI", "flask": "Flask", "quart": "Quart",
            "sanic": "Sanic", "starlette": "Starlette",
            "bottle": "Bottle"}[match.group(1).lower()]


def extract_routes(path: str, text: str, language: str) -> list[Route]:
    """Best-effort endpoint extraction. Precision over recall."""
    routes: list[Route] = []
    if len(text) > 400_000:
        return routes

    # Filesystem routing (Next.js style) needs no content scan.
    m = _NEXT_API_ROUTE.search(path)
    if m:
        routes.append(Route("ANY", "/api/" + m.group(2), path, path, 1, "Next.js"))
    m = _NEXT_APP_ROUTE.search(path)
    if m and m.group(4) == "route":
        routes.append(Route("ANY", "/" + m.group(3), path, path, 1, "Next.js App Router"))

    py_label = _python_route_label(text) if language == "Python" else ""

    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if len(line) > 600 or "(" not in line:
            continue
        for framework, pattern in _ROUTE_PATTERNS:
            if framework in _FRAMEWORK_LANGUAGES and language not in _FRAMEWORK_LANGUAGES[framework]:
                continue
            match = pattern.search(line)
            if not match:
                continue
            groups = match.groups()
            if framework == "Django":
                pattern_str, handler = groups[0], groups[1]
                method = "ANY"
            elif framework == "Annotation":
                verb = groups[0]
                method = re.sub(r"Mapping|Request", "", verb).upper() or "ANY"
                pattern_str, handler = groups[1], ""
            else:
                method = groups[0].upper()
                pattern_str = groups[1]
                handler = ""
            if method == "ROUTE":
                method = "ANY"
            if not pattern_str or len(pattern_str) > 200:
                continue
            if not (pattern_str.startswith("/") or pattern_str.startswith(":")
                    or framework in {"Annotation", "Django"}):
                continue
            label = py_label if framework == "Python decorator" and py_label else framework
            routes.append(Route(method, pattern_str, handler, path, idx, label))
            break
    return routes


# --------------------------------------------------------------------------
# Detection entry points
# --------------------------------------------------------------------------
def detect_frameworks(
    files: list[FileRecord], deps: list[Dependency]
) -> tuple[list[str], dict[str, list[str]]]:
    """Return (framework list, layer -> frameworks)."""
    found: dict[str, str] = {}
    dep_names = {d.name.lower() for d in deps}
    for dep_name, (label, layer) in DEP_FRAMEWORKS.items():
        if dep_name.lower() in dep_names:
            found[label] = layer
    for record in files:
        for pattern, label, layer in FILE_FRAMEWORKS:
            if pattern.search(record.path):
                found.setdefault(label, layer)
    by_layer: dict[str, list[str]] = defaultdict(list)
    for label, layer in found.items():
        by_layer[layer].append(label)
    for values in by_layer.values():
        values.sort()
    return sorted(found), dict(by_layer)


_BARREL_PARENTS = frozenset({
    "types", "utils", "util", "helpers", "hooks", "components", "common",
    "constants", "styles", "assets", "interfaces", "models", "context",
    "contexts", "providers", "store", "stores", "lib", "shared", "ui",
})


def is_entrypoint(path: str) -> bool:
    """True for real program entrypoints, not barrel re-export files.

    `src/types/index.ts` exists only to re-export; treating it as an
    entrypoint pollutes both the architecture doc and the ranking.
    """
    p = PurePosixPath(path)
    if p.stem == "index" and p.parent.name.lower() in _BARREL_PARENTS:
        return False
    return any(pattern.search(path) for pattern in ENTRYPOINT_PATTERNS)


def _component_kind(root: str, manifests: list[str], files: list[FileRecord]) -> str:
    lower = root.lower()
    if any(tok in lower for tok in ("infra", "terraform", "deploy", "k8s", "helm", "charts")):
        return "infra"
    if any(tok in lower for tok in ("doc", "docs", "website")):
        return "docs"
    if any(tok in lower for tok in ("script", "tools", "tooling", "build", "ci")):
        return "tooling"
    names = {PurePosixPath(m).name for m in manifests}
    has_entry = any(f.is_entrypoint for f in files)
    if any(tok in lower for tok in ("service", "server", "backend", "api", "worker", "daemon")):
        return "service"
    if any(tok in lower for tok in ("web", "frontend", "ui", "app", "client", "portal")):
        return "app"
    if "Dockerfile" in names or has_entry:
        return "service"
    return "library"


def discover_components(
    files: list[FileRecord], manifest_paths: list[str], root_name: str
) -> list[Component]:
    """Group files into logical components anchored on manifests.

    A component root is the directory containing a package manifest. Files are
    assigned to the deepest matching component root, so a monorepo with
    `services/api/package.json` and `services/api/web/package.json` produces
    two components with correct ownership.
    """
    roots: list[str] = []
    for manifest in manifest_paths:
        parent = str(PurePosixPath(manifest).parent)
        parent = "" if parent == "." else parent
        if parent not in roots:
            roots.append(parent)

    # A monorepo with only a root manifest still benefits from top-level split.
    if roots in ([""], []) :
        top_dirs = Counter(
            p.path.split("/", 1)[0] for p in files
            if "/" in p.path and is_code(p.language)
        )
        significant = [d for d, count in top_dirs.items() if count >= 8]
        if len(significant) >= 2:
            roots = sorted(significant) + [""]

    roots.sort(key=len, reverse=True)  # deepest first
    buckets: dict[str, list[FileRecord]] = defaultdict(list)
    manifests_by_root: dict[str, list[str]] = defaultdict(list)

    for manifest in manifest_paths:
        parent = str(PurePosixPath(manifest).parent)
        parent = "" if parent == "." else parent
        manifests_by_root[parent].append(manifest)

    for record in files:
        for candidate in roots:
            if candidate == "" or record.path.startswith(candidate + "/"):
                buckets[candidate].append(record)
                break

    components: list[Component] = []
    for comp_root, comp_files in buckets.items():
        if not comp_files:
            continue
        code_files = [f for f in comp_files if is_code(f.language) and f.role in {"source", "test"}]
        # A directory with its own manifest is a declared package: keep it
        # however small. Inferred (manifest-less) components need some mass.
        if comp_root and not manifests_by_root.get(comp_root) and len(code_files) < 3 \
                and len(comp_files) < 6:
            continue
        if comp_root and not code_files and not any(f.role in {"config", "infra"} for f in comp_files):
            continue
        langs = Counter(f.language for f in code_files)
        name = comp_root.split("/")[-1] if comp_root else root_name
        entry = sorted(
            (f.path for f in comp_files if f.is_entrypoint),
            key=lambda p: (p.count("/"), len(p)),
        )[:4]
        components.append(Component(
            name=name or root_name,
            root=comp_root or ".",
            kind=_component_kind(comp_root, manifests_by_root.get(comp_root, []), comp_files),
            languages=[lang for lang, _ in langs.most_common(4)],
            manifests=sorted(manifests_by_root.get(comp_root, [])),
            file_count=len(comp_files),
            loc=sum(f.lines for f in code_files),
            entrypoints=entry,
        ))

    components.sort(key=lambda c: (-c.loc, c.root))
    return components


EXTERNAL_SERVICE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bstripe\b"), "Stripe"),
    (re.compile(r"(?i)\btwilio\b"), "Twilio"),
    (re.compile(r"(?i)\bsendgrid\b"), "SendGrid"),
    (re.compile(r"(?i)\bauth0\b"), "Auth0"),
    (re.compile(r"(?i)\bokta\b"), "Okta"),
    (re.compile(r"(?i)\bkeycloak\b"), "Keycloak"),
    (re.compile(r"(?i)\bs3\.amazonaws|boto3|aws-sdk\b"), "AWS"),
    (re.compile(r"(?i)\bgoogleapis|gcp\b"), "Google Cloud"),
    (re.compile(r"(?i)\bazure\b"), "Azure"),
    (re.compile(r"(?i)\bibm(cloud)?\.com|watsonx?\b"), "IBM Cloud"),
    (re.compile(r"(?i)\bsentry\b"), "Sentry"),
    (re.compile(r"(?i)\bdatadog\b"), "Datadog"),
    (re.compile(r"(?i)\binstana\b"), "IBM Instana"),
    (re.compile(r"(?i)\bprometheus\b"), "Prometheus"),
    (re.compile(r"(?i)\bopentelemetry|otel\b"), "OpenTelemetry"),
    (re.compile(r"(?i)\bsnowflake\b"), "Snowflake"),
    (re.compile(r"(?i)\bopenai\.com|api\.openai\b"), "OpenAI"),
    (re.compile(r"(?i)\banthropic\b"), "Anthropic"),
]


def detect_external_services(deps: list[Dependency], config_text: str) -> list[str]:
    blob = " ".join(d.name for d in deps) + " " + config_text[:200_000]
    found = {label for pattern, label in EXTERNAL_SERVICE_PATTERNS if pattern.search(blob)}
    return sorted(found)
