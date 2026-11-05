"""Package-manifest parsing.

Extracts, per manifest: package manager, declared dependencies (with scope),
and the commands a human would actually run. Commands matter more than the
dependency list — "how do I run the tests" is the single most useful fact you
can hand an agent, and it is the one most often missing from a README.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .logging_setup import get_logger
from .models import Dependency

log = get_logger()

MANIFEST_MANAGERS: dict[str, str] = {
    "package.json": "npm",
    "pyproject.toml": "pip",
    "requirements.txt": "pip",
    "Pipfile": "pip",
    "setup.py": "pip",
    "setup.cfg": "pip",
    "environment.yml": "conda",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "go.mod": "go",
    "Cargo.toml": "cargo",
    "Gemfile": "gem",
    "composer.json": "composer",
    "mix.exs": "hex",
    "pubspec.yaml": "pub",
    "build.sbt": "sbt",
    "Package.swift": "spm",
    "deno.json": "deno",
    "Makefile": "make",
    "makefile": "make",
    "GNUmakefile": "make",
}

_MAKEFILES = frozenset({"Makefile", "makefile", "GNUmakefile"})


def is_requirements_file(rel: str) -> bool:
    """`requirements.txt`, `requirements-dev.txt`, `requirements/base.txt`, ..."""
    path = Path(rel)
    name = path.name
    if not name.endswith(".txt"):
        return False
    if name.startswith("requirements"):
        return True
    return path.parent.name == "requirements"


def is_manifest(rel: str) -> bool:
    name = Path(rel).name
    return name in MANIFEST_MANAGERS or name.endswith(".csproj") or is_requirements_file(rel)

# Scripts whose names tell us what they do, mapped to a canonical command kind.
_SCRIPT_KIND = {
    "test": "test", "tests": "test", "test:unit": "test", "test:integration": "test",
    "test:e2e": "test", "unit": "test", "e2e": "test", "spec": "test",
    "check": "test", "verify": "test", "ci": "test",
    "build": "build", "compile": "build", "bundle": "build", "dist": "build",
    "start": "run", "dev": "run", "serve": "run", "watch": "run",
    "lint": "lint", "lint:fix": "lint", "format": "lint", "fmt": "lint",
    "typecheck": "lint", "types": "lint", "tsc": "lint",
    "migrate": "db", "db:migrate": "db", "seed": "db",
    "deploy": "deploy", "release": "deploy", "publish": "deploy",
}


def _add(commands: dict[str, list[str]], kind: str, cmd: str) -> None:
    bucket = commands.setdefault(kind, [])
    if cmd not in bucket:
        bucket.append(cmd)


def _npm_runner(root: Path, manifest_dir: Path) -> str:
    for lock, runner in (
        ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"), ("package-lock.json", "npm"),
    ):
        if (manifest_dir / lock).exists() or (root / lock).exists():
            return runner
    return "npm"


def parse_package_json(
    root: Path, rel: str, text: str, commands: dict[str, list[str]]
) -> list[Dependency]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    deps: list[Dependency] = []
    for key, scope in (
        ("dependencies", "runtime"), ("devDependencies", "dev"),
        ("peerDependencies", "peer"), ("optionalDependencies", "optional"),
    ):
        for name, version in (data.get(key) or {}).items():
            deps.append(Dependency(name=name, version=str(version), manager="npm",
                                   scope=scope, manifest=rel))

    runner = _npm_runner(root, (root / rel).parent)
    prefix = "" if rel == "package.json" else f"cd {shlex.quote(str(PurePosixPath(rel).parent))} && "
    for script in (data.get("scripts") or {}):
        kind = _SCRIPT_KIND.get(script.lower())
        if kind:
            _add(commands, kind, f"{prefix}{runner} run {script}")
        elif script.lower() in {"prepare", "postinstall", "prepublishOnly"}:
            continue
    if data.get("scripts"):
        _add(commands, "install", f"{prefix}{runner} install")
    return deps


def parse_pyproject(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    deps: list[Dependency] = []
    project = data.get("project") or {}
    for spec in project.get("dependencies") or []:
        name, version = _split_pep508(str(spec))
        deps.append(Dependency(name, version, "pip", "runtime", rel))
    for extra, specs in (project.get("optional-dependencies") or {}).items():
        scope = "dev" if extra in {"dev", "test", "tests", "lint"} else "optional"
        for spec in specs:
            name, version = _split_pep508(str(spec))
            deps.append(Dependency(name, version, "pip", scope, rel))

    poetry = ((data.get("tool") or {}).get("poetry") or {})
    for name, spec in (poetry.get("dependencies") or {}).items():
        if name.lower() == "python":
            continue
        version = spec if isinstance(spec, str) else str(spec.get("version", ""))
        deps.append(Dependency(name, version, "poetry", "runtime", rel))
    for body in (poetry.get("group") or {}).values():
        for name, spec in (body.get("dependencies") or {}).items():
            version = spec if isinstance(spec, str) else str(spec.get("version", ""))
            deps.append(Dependency(name, version, "poetry", "dev", rel))

    tools = data.get("tool") or {}
    if "pytest" in tools or any(d.name.startswith("pytest") for d in deps):
        _add(commands, "test", "pytest")
    if "ruff" in tools:
        _add(commands, "lint", "ruff check .")
    if "black" in tools:
        _add(commands, "lint", "black .")
    if "mypy" in tools:
        _add(commands, "lint", "mypy .")
    if poetry:
        _add(commands, "install", "poetry install")
    elif project:
        _add(commands, "install", "pip install -e .")
    scripts = project.get("scripts") or {}
    for name in scripts:
        _add(commands, "run", name)
    return deps


_PEP508 = re.compile(r"^\s*([A-Za-z0-9._\-]+)\s*(\[[^\]]*\])?\s*(.*)$")


def _split_pep508(spec: str) -> tuple[str, str]:
    spec = spec.split(";", 1)[0].strip()
    match = _PEP508.match(spec)
    if not match:
        return spec, ""
    return match.group(1), (match.group(3) or "").strip()


def parse_requirements(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    deps: list[Dependency] = []
    scope = "dev" if re.search(r"(dev|test)", rel, re.I) else "runtime"
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "http", "git+", ".")):
            continue
        name, version = _split_pep508(line)
        if name:
            deps.append(Dependency(name, version, "pip", scope, rel))
    _add(commands, "install", f"pip install -r {rel}")
    return deps


def parse_pom(rel: str, text: str, commands: dict[str, list[str]],
              root: Path | None = None) -> list[Dependency]:
    deps: list[Dependency] = []
    for block in re.finditer(r"<dependency>(.*?)</dependency>", text, re.S):
        body = block.group(1)
        group = re.search(r"<groupId>([^<]+)</groupId>", body)
        artifact = re.search(r"<artifactId>([^<]+)</artifactId>", body)
        version = re.search(r"<version>([^<]+)</version>", body)
        scope_m = re.search(r"<scope>([^<]+)</scope>", body)
        if artifact:
            name = f"{group.group(1)}:{artifact.group(1)}" if group else artifact.group(1)
            scope = (scope_m.group(1) if scope_m else "runtime").strip()
            deps.append(Dependency(name, version.group(1).strip() if version else "",
                                   "maven", "test" if scope == "test" else "runtime", rel))
    prefix = "" if rel == "pom.xml" else f"cd {shlex.quote(str(PurePosixPath(rel).parent))} && "
    # Only claim the wrapper when it is actually checked in next to the pom.
    has_wrapper = root is not None and (root / Path(rel).parent / "mvnw").is_file()
    wrapper = "./mvnw" if has_wrapper else "mvn"
    _add(commands, "build", f"{prefix}{wrapper} -q package -DskipTests")
    _add(commands, "test", f"{prefix}{wrapper} test")
    return deps


_GRADLE_DEP = re.compile(
    r"""^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation|"""
    r"""testCompileOnly|annotationProcessor|kapt)\s*\(?\s*['"]([^'"]+)['"]""",
    re.M,
)


def parse_gradle(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    deps: list[Dependency] = []
    for match in _GRADLE_DEP.finditer(text):
        config, coord = match.group(1), match.group(2)
        parts = coord.split(":")
        name = ":".join(parts[:2]) if len(parts) >= 2 else coord
        version = parts[2] if len(parts) >= 3 else ""
        scope = "test" if config.startswith("test") else "runtime"
        deps.append(Dependency(name, version, "gradle", scope, rel))
    prefix = "" if "/" not in rel else f"cd {shlex.quote(str(PurePosixPath(rel).parent))} && "
    _add(commands, "build", f"{prefix}./gradlew build -x test")
    _add(commands, "test", f"{prefix}./gradlew test")
    return deps


def parse_go_mod(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    deps: list[Dependency] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        target = line[len("require "):] if line.startswith("require ") else (line if in_block else "")
        if not target or target.startswith("//"):
            continue
        parts = target.split()
        if len(parts) >= 2:
            scope = "dev" if "// indirect" in raw else "runtime"
            deps.append(Dependency(parts[0], parts[1], "go", scope, rel))
    prefix = "" if rel == "go.mod" else f"cd {shlex.quote(str(PurePosixPath(rel).parent))} && "
    _add(commands, "build", f"{prefix}go build ./...")
    _add(commands, "test", f"{prefix}go test ./...")
    return deps


def parse_cargo(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    deps: list[Dependency] = []
    for key, scope in (("dependencies", "runtime"), ("dev-dependencies", "dev"),
                       ("build-dependencies", "dev")):
        for name, spec in (data.get(key) or {}).items():
            version = spec if isinstance(spec, str) else str(spec.get("version", ""))
            deps.append(Dependency(name, version, "cargo", scope, rel))
    _add(commands, "build", "cargo build")
    _add(commands, "test", "cargo test")
    return deps


def parse_gemfile(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    deps: list[Dependency] = []
    group = "runtime"
    for raw in text.splitlines():
        line = raw.strip()
        gmatch = re.match(r"group\s+:(\w+)", line)
        if gmatch:
            group = "dev" if gmatch.group(1) in {"development", "test"} else "runtime"
        match = re.match(r"""gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""", line)
        if match:
            deps.append(Dependency(match.group(1), match.group(2) or "", "gem", group, rel))
    _add(commands, "install", "bundle install")
    _add(commands, "test", "bundle exec rspec")
    return deps


def parse_composer(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    deps: list[Dependency] = []
    for key, scope in (("require", "runtime"), ("require-dev", "dev")):
        for name, version in (data.get(key) or {}).items():
            deps.append(Dependency(name, str(version), "composer", scope, rel))
    for script in (data.get("scripts") or {}):
        kind = _SCRIPT_KIND.get(script.lower())
        if kind:
            _add(commands, kind, f"composer {script}")
    return deps


def parse_makefile(rel: str, text: str, commands: dict[str, list[str]]) -> None:
    prefix = "" if rel in _MAKEFILES else f"-C {shlex.quote(str(PurePosixPath(rel).parent))} "
    for match in re.finditer(r"^([a-zA-Z][\w.-]*)\s*:(?![=:])", text, re.M):
        target = match.group(1)
        kind = _SCRIPT_KIND.get(target.lower())
        if kind:
            _add(commands, kind, f"make {prefix}{target}".strip())


_PKG_REF = re.compile(
    r"""<PackageReference\s+Include\s*=\s*["']([^"']+)["'](?:\s+Version\s*=\s*["']([^"']*)["'])?"""
    r"""(?:[^>]*?/>|[^>]*>(?:.*?<Version>([^<]*)</Version>)?)""",
    re.S | re.I,
)


def parse_csproj(rel: str, text: str, commands: dict[str, list[str]]) -> list[Dependency]:
    deps: list[Dependency] = []
    is_test = bool(re.search(r"<IsTestProject>\s*true", text, re.I)) or bool(
        re.search(r"(?i)(tests?|spec)\.csproj$", rel))
    for match in _PKG_REF.finditer(text):
        name = match.group(1).strip()
        version = (match.group(2) or match.group(3) or "").strip()
        scope = "test" if re.match(r"(?i)(xunit|nunit|mstest|moq|fluentassertions|"
                                   r"microsoft\.net\.test)", name) else "runtime"
        deps.append(Dependency(name, version, "nuget", scope, rel))
    _add(commands, "build", f"dotnet build {rel}")
    if is_test or any(d.scope == "test" for d in deps):
        _add(commands, "test", f"dotnet test {rel}")
    return deps


def parse_manifest(
    root: Path, rel: str, text: str, commands: dict[str, list[str]]
) -> list[Dependency]:
    """Dispatch on filename. Unknown manifests return an empty list."""
    name = Path(rel).name
    try:
        if name == "package.json":
            return parse_package_json(root, rel, text, commands)
        if name == "pyproject.toml":
            return parse_pyproject(rel, text, commands)
        if is_requirements_file(rel):
            return parse_requirements(rel, text, commands)
        if name == "pom.xml":
            return parse_pom(rel, text, commands, root)
        if name.endswith(".csproj"):
            return parse_csproj(rel, text, commands)
        if name in {"build.gradle", "build.gradle.kts"}:
            return parse_gradle(rel, text, commands)
        if name == "go.mod":
            return parse_go_mod(rel, text, commands)
        if name == "Cargo.toml":
            return parse_cargo(rel, text, commands)
        if name == "Gemfile":
            return parse_gemfile(rel, text, commands)
        if name == "composer.json":
            return parse_composer(rel, text, commands)
        if name in _MAKEFILES:
            parse_makefile(rel, text, commands)
            return []
    except Exception as exc:  # pragma: no cover - never let one manifest kill a run
        log.debug("manifest parse failed for %s: %s", rel, exc)
    return []


def manager_for(rel: str) -> str:
    name = Path(rel).name
    if name.endswith(".csproj"):
        return "nuget"
    if is_requirements_file(rel):
        return "pip"
    return MANIFEST_MANAGERS.get(name, "")
