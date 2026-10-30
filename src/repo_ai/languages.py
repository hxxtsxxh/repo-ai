"""Language detection and file-role classification.

Two jobs:
  * map a path to a language (extension first, then filename, then shebang)
  * decide what a file *is* (source / test / config / doc / build / infra /
    generated / fixture) because role drives both ranking and rendering
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

EXT_LANG: dict[str, str] = {
    ".py": "Python", ".pyi": "Python", ".pyx": "Cython",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".mts": "TypeScript", ".cts": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala",
    ".groovy": "Groovy", ".gradle": "Gradle",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".rake": "Ruby",
    ".php": "PHP", ".cs": "C#", ".fs": "F#", ".vb": "VB.NET",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".cxx": "C++",
    ".hpp": "C++", ".hh": "C++", ".hxx": "C++",
    ".m": "Objective-C", ".mm": "Objective-C++", ".swift": "Swift",
    ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang",
    ".hrl": "Erlang", ".hs": "Haskell", ".ml": "OCaml", ".clj": "Clojure",
    ".cljs": "ClojureScript", ".lua": "Lua", ".r": "R", ".jl": "Julia",
    ".pl": "Perl", ".pm": "Perl", ".zig": "Zig", ".nim": "Nim", ".v": "V",
    ".sol": "Solidity", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".fish": "Shell", ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".sql": "SQL", ".psql": "SQL", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".proto": "Protobuf", ".thrift": "Thrift", ".avsc": "Avro",
    ".tf": "Terraform", ".tfvars": "Terraform", ".hcl": "HCL",
    ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".jsonc": "JSON",
    ".json5": "JSON", ".toml": "TOML", ".ini": "INI", ".cfg": "INI",
    ".properties": "Properties", ".xml": "XML", ".xsd": "XML",
    ".html": "HTML", ".htm": "HTML", ".vue": "Vue", ".svelte": "Svelte",
    ".astro": "Astro", ".css": "CSS", ".scss": "SCSS", ".sass": "Sass",
    ".less": "Less", ".styl": "Stylus",
    ".md": "Markdown", ".mdx": "MDX", ".rst": "reStructuredText",
    ".adoc": "AsciiDoc", ".txt": "Text", ".csv": "CSV", ".tsv": "CSV",
    ".ipynb": "Jupyter", ".tex": "TeX",
    ".cbl": "COBOL", ".cob": "COBOL", ".cpy": "COBOL",
    ".rpgle": "RPG", ".sqlrpgle": "RPG", ".rpg": "RPG", ".clle": "CL",
    ".dds": "DDS", ".pli": "PL/I", ".asm": "Assembly", ".s": "Assembly",
    ".jcl": "JCL",
}

FILENAME_LANG: dict[str, str] = {
    "Dockerfile": "Dockerfile", "Containerfile": "Dockerfile",
    "Makefile": "Make", "makefile": "Make", "GNUmakefile": "Make",
    "CMakeLists.txt": "CMake", "Rakefile": "Ruby", "Gemfile": "Ruby",
    "Vagrantfile": "Ruby", "Brewfile": "Ruby", "Podfile": "Ruby",
    "Jenkinsfile": "Groovy", "build.gradle": "Gradle",
    "settings.gradle": "Gradle", "Procfile": "Text", "BUILD": "Bazel",
    "BUILD.bazel": "Bazel", "WORKSPACE": "Bazel", "justfile": "Just",
    "Justfile": "Just", "Taskfile.yml": "YAML", ".gitignore": "Ignore",
    ".dockerignore": "Ignore", ".bobignore": "Ignore",
}

SHEBANG_LANG: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^#!.*\bpython[0-9.]*\b"), "Python"),
    (re.compile(r"^#!.*\bnode\b"), "JavaScript"),
    (re.compile(r"^#!.*\b(bash|sh|zsh|dash)\b"), "Shell"),
    (re.compile(r"^#!.*\bruby\b"), "Ruby"),
    (re.compile(r"^#!.*\bperl\b"), "Perl"),
    (re.compile(r"^#!.*\bphp\b"), "PHP"),
]

# Languages we treat as "real code" for LOC / component sizing.
CODE_LANGUAGES: frozenset[str] = frozenset({
    "Python", "Cython", "JavaScript", "TypeScript", "Java", "Kotlin", "Scala",
    "Groovy", "Go", "Rust", "Ruby", "PHP", "C#", "F#", "VB.NET", "C", "C++",
    "Objective-C", "Objective-C++", "Swift", "Dart", "Elixir", "Erlang",
    "Haskell", "OCaml", "Clojure", "ClojureScript", "Lua", "R", "Julia",
    "Perl", "Zig", "Nim", "V", "Solidity", "Shell", "PowerShell", "Vue",
    "Svelte", "Astro", "SQL", "COBOL", "RPG", "CL", "PL/I", "Assembly",
})

DOC_LANGUAGES: frozenset[str] = frozenset({
    "Markdown", "MDX", "reStructuredText", "AsciiDoc", "Text", "TeX",
})

CONFIG_LANGUAGES: frozenset[str] = frozenset({
    "YAML", "JSON", "TOML", "INI", "Properties", "XML", "HCL", "Terraform",
})

TEST_DIR_TOKENS: frozenset[str] = frozenset({
    "test", "tests", "spec", "specs", "__tests__", "__test__", "testing",
    "e2e", "integration-tests", "it", "acceptance", "cypress", "playwright",
    "testdata", "fixtures", "__fixtures__", "__mocks__", "mocks", "stubs",
})

TEST_FILE_RE = re.compile(
    r"(^|[._/-])(test|tests|spec|specs)([._/-]|$)"
    r"|(^|/)test_[^/]+$"
    r"|_test\.[a-z]+$"
    r"|\.(test|spec)\.[a-z]+$"
    r"|Test[s]?\.(java|kt|scala|cs)$"
    r"|(^|/)conftest\.py$",
    re.IGNORECASE,
)

INFRA_TOKENS: frozenset[str] = frozenset({
    "terraform", "infra", "infrastructure", "deploy", "deployment",
    "deployments", "k8s", "kubernetes", "helm", "charts", "ansible",
    "cloudformation", "pulumi", "cdk", ".github", ".gitlab", ".circleci",
    "ops", "devops", "docker",
})

DOC_DIR_TOKENS: frozenset[str] = frozenset({
    "doc", "docs", "documentation", "adr", "adrs", "rfc", "rfcs",
    "design-docs", "architecture", "wiki",
})

BUILD_FILENAMES: frozenset[str] = frozenset({
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "Pipfile", "pom.xml", "build.gradle",
    "build.gradle.kts", "settings.gradle", "go.mod", "Cargo.toml",
    "Gemfile", "composer.json", "Makefile", "CMakeLists.txt", "build.sbt",
    "mix.exs", "pubspec.yaml", "deno.json", "bun.lockb", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "tsconfig.json",
    "webpack.config.js", "vite.config.ts", "vite.config.js", "rollup.config.js",
    "Taskfile.yml", "justfile", "BUILD.bazel", "WORKSPACE",
})

GENERATED_MARKERS: tuple[str, ...] = (
    "@generated",
    "auto-generated",
    "autogenerated",
    "automatically generated",
    "code generated by",
    "do not edit",
    "do not modify this file",
    "this file was generated",
    "generated by protoc",
    "generated by openapi-generator",
    "generated by swagger",
    "generated from",
    "@nocheck",
)

GENERATED_PATH_RE = re.compile(
    r"(^|/)(generated|gen|__generated__|_generated|autogen|codegen|"
    r"\.generated|proto_gen|pb|swagger|openapi-client|graphql/generated)(/|$)"
    r"|[._-](pb|pb2|pb3|generated|g|designer|freezed|gen)\.[a-z]+$"
    r"|\.(pb|pb2)\.[a-z]+$"
    r"|(^|/)migrations?/\d{4,}",
    re.IGNORECASE,
)

MINIFIED_RE = re.compile(r"\.(min|bundle|chunk)\.(js|css)$|-[0-9a-f]{8,}\.(js|css)$")


def detect_language(path: str, first_line: str = "") -> str:
    p = PurePosixPath(path)
    name = p.name
    if name in FILENAME_LANG:
        return FILENAME_LANG[name]
    if name.startswith("Dockerfile"):
        return "Dockerfile"
    if name.startswith("Makefile"):
        return "Make"
    # Handle compound suffixes such as .d.ts and .config.js
    suffix = p.suffix.lower()
    if suffix in EXT_LANG:
        return EXT_LANG[suffix]
    if first_line.startswith("#!"):
        for pattern, lang in SHEBANG_LANG:
            if pattern.match(first_line):
                return lang
    if not suffix and name.isupper():
        return "Text"
    return "Other"


def is_generated(path: str, head: str) -> bool:
    """Heuristic: path pattern, minification, or an explicit banner."""
    if GENERATED_PATH_RE.search(path) or MINIFIED_RE.search(path):
        return True
    probe = head[:2000].lower()
    return any(marker in probe for marker in GENERATED_MARKERS)


def classify_role(path: str, language: str, head: str = "") -> str:
    """Return one of: generated|test|fixture|doc|build|infra|config|source."""
    p = PurePosixPath(path)
    parts = [part.lower() for part in p.parts]
    name = p.name

    if is_generated(path, head):
        return "generated"

    if name in BUILD_FILENAMES or name.startswith("Dockerfile"):
        return "build"

    dir_tokens = set(parts[:-1])
    if dir_tokens & {"testdata", "fixtures", "__fixtures__", "__mocks__", "mocks", "stubs"}:
        return "fixture"
    if (dir_tokens & TEST_DIR_TOKENS) or TEST_FILE_RE.search(path):
        return "test"
    if dir_tokens & INFRA_TOKENS or language in {"Terraform", "HCL"}:
        return "infra"
    if language in DOC_LANGUAGES or (dir_tokens & DOC_DIR_TOKENS):
        return "doc"
    if language in CONFIG_LANGUAGES or name.startswith("."):
        return "config"
    if language in CODE_LANGUAGES:
        return "source"
    return "config" if language != "Other" else "source"


def is_code(language: str) -> bool:
    return language in CODE_LANGUAGES
