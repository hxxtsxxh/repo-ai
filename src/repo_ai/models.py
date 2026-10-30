"""Dataclasses shared across repo-ai.

Everything that crosses a module boundary is one of these types. Keeping them
in one place makes the JSON serialisation in `index.py` and the rendering in
`render.py` easy to keep in sync.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class FileRecord:
    """One indexed source file."""

    path: str  # POSIX-style, relative to repo root
    size: int
    lines: int
    language: str
    sha1: str
    mtime: float
    role: str = "source"  # source|test|config|doc|build|infra|generated|fixture
    is_entrypoint: bool = False
    component: str = ""  # logical component / service this file belongs to
    doc_summary: str = ""  # module docstring / leading comment, first line

    def to_row(self) -> tuple:
        return (
            self.path,
            self.size,
            self.lines,
            self.language,
            self.sha1,
            self.mtime,
            self.role,
            int(self.is_entrypoint),
            self.component,
            self.doc_summary,
        )


@dataclass(slots=True)
class Symbol:
    """A named, addressable code entity."""

    path: str
    name: str
    kind: str  # function|method|class|interface|type|struct|enum|const|route|component
    line: int
    end_line: int
    signature: str = ""
    parent: str = ""  # enclosing class/namespace, if any
    exported: bool = True
    docstring: str = ""

    @property
    def qualified_name(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name


@dataclass(slots=True)
class ImportEdge:
    """A resolved or unresolved import from one file to another module."""

    src_path: str
    raw_target: str
    resolved_path: str = ""  # empty when the target is external
    external_package: str = ""  # populated when the import is third-party


@dataclass(slots=True)
class Dependency:
    """A declared third-party dependency."""

    name: str
    version: str
    manager: str  # npm|pip|maven|gradle|go|cargo|gem|composer|nuget
    scope: str = "runtime"  # runtime|dev|test|peer|optional
    manifest: str = ""


@dataclass(slots=True)
class Route:
    """An HTTP route / RPC endpoint discovered in source."""

    method: str
    path_pattern: str
    handler: str
    file: str
    line: int
    framework: str = ""


@dataclass(slots=True)
class SecretHit:
    """A candidate secret. Never stores the secret value itself."""

    path: str
    line: int
    rule: str
    severity: str  # high|medium|low
    redacted: str  # e.g. "AKIA****************"
    entropy: float = 0.0


@dataclass(slots=True)
class Component:
    """A logical unit: a service, app, package, or top-level module."""

    name: str
    root: str
    kind: str  # service|app|library|infra|docs|tooling
    languages: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    file_count: int = 0
    loc: int = 0
    entrypoints: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class GitFileStat:
    path: str
    commits: int
    last_commit_iso: str
    authors: int
    churn: int  # lines added + removed in the analysed window


@dataclass(slots=True)
class TestSuite:
    name: str
    root: str
    framework: str
    kind: str  # unit|integration|e2e|unknown
    file_count: int
    command: str = ""


@dataclass(slots=True)
class RepoFacts:
    """Everything the analyzer learned. Serialised to context.json."""

    root: str = ""
    name: str = ""
    context_dir: str = ""  # repo-relative directory holding the generated docs
    generated_at: str = ""
    tool_version: str = ""
    git_head: str = ""
    git_branch: str = ""
    git_remote: str = ""
    total_files_seen: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    total_loc: int = 0
    languages: dict[str, int] = field(default_factory=dict)  # language -> LOC
    package_managers: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    test_suites: list[TestSuite] = field(default_factory=list)
    commands: dict[str, list[str]] = field(default_factory=dict)  # kind -> commands
    docs: list[dict[str, str]] = field(default_factory=list)
    ci_workflows: list[str] = field(default_factory=list)
    infra: list[str] = field(default_factory=list)
    conventions: dict[str, Any] = field(default_factory=dict)
    hotspots: list[GitFileStat] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)
    secret_hits: list[SecretHit] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)  # paths withheld from every output
    important_files: list[dict[str, Any]] = field(default_factory=list)
    external_services: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False, default=str)
